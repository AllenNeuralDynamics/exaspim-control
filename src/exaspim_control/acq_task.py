"""Acquisition task using the new DAQ API from voxel.interfaces.daq."""

import logging
from dataclasses import dataclass
from typing import Any, Self

import numpy as np
from pydantic import BaseModel, Field, computed_field, model_validator
from voxel.device.quantity import Frequency, NormalizedRange, Time
from voxel.interfaces.daq import AcqSampleMode, AOTask, COTask, SpimDaq
from voxel.interfaces.daq.wave import Waveform


class TriggerConfig(BaseModel):
    pin: str
    counter: str
    duty_cycle: float = Field(0.5, description="Duty cycle for the trigger signal (0.0 to 1.0)", ge=0, le=1)


class AcqTiming(BaseModel):
    sample_rate: Frequency = Field(..., description="Hz", gt=0)
    duration: Time = Field(..., description="Time for one cycle seconds", gt=0)
    rest_time: Time = Field(default=Time(0.0), description="Time between cycles", ge=0)
    clock: TriggerConfig | None = Field(None, description="Clock trigger configuration")

    @model_validator(mode="after")
    def validate_duration_and_sample_rate(self) -> Self:
        if self.sample_rate < 2 * self.frequency:
            err_msg = f"sample_rate ({self.sample_rate} Hz) must be ≥ 2x clock_freq ({self.frequency} Hz)"
            raise ValueError(err_msg)
        return self

    @computed_field
    @property
    def frequency(self) -> float:
        total_span = self.duration + self.rest_time
        return 1 / total_span if total_span > 0 else 0.0

    @computed_field
    @property
    def num_samples(self) -> int:
        return int(self.sample_rate * self.duration)


class AcqTaskConfig(BaseModel):
    timing: AcqTiming = Field(..., description="Acquisition timing parameters")
    waveforms: dict[str, Waveform] = Field(..., description="List of waveforms to acquire")
    ports: dict[str, str]

    @model_validator(mode="before")
    @classmethod
    def insert_missing_windows(cls, m: Any) -> Any:
        waveforms = m.get("waveforms", {})
        duration = m.get("timing", None).get("duration", None)
        if duration is None:
            return m
        for wf in waveforms.values():
            if "window" not in wf:
                wf["window"] = NormalizedRange()
        return m


@dataclass(frozen=True)
class WaveGenChannel:
    name: str
    pin: str
    wave: "Waveform"


class AcquisitionTask:
    """Orchestrates DAQ task creation and control using the new SpimDaq API.

    This class uses the new voxel.interfaces.daq API which provides:
    - Factory methods that return task objects (AOTask, COTask)
    - Methods directly on task objects instead of passing task names
    - Automatic pin management and cleanup
    """

    def __init__(self, *, uid: str, daq: SpimDaq, cfg: AcqTaskConfig) -> None:
        self._uid = uid
        self._log = logging.getLogger(self._uid)
        self._daq = daq
        self._timing = cfg.timing
        self._waveforms = cfg.waveforms
        self._ports = cfg.ports
        self._channels: dict[str, WaveGenChannel] = {}

        # Task objects (new API returns task instances)
        self._ao_task: AOTask | None = None
        self._clock_task: COTask | None = None
        self._is_setup = False

    @property
    def uid(self) -> str:
        return self._uid

    def setup(self) -> None:
        """Set up the task: create task with channels, configure timing."""
        if self._is_setup:
            msg = f"Task '{self._uid}' is already set up"
            raise RuntimeError(msg)

        # Validate that all ports have corresponding waveforms
        for name in self._ports:
            if name not in self._waveforms:
                err_msg = f"No waveform defined for port '{name}'"
                raise ValueError(err_msg)

        # Store channel info locally (for waveform generation)
        for name, port in self._ports.items():
            self._channels[name] = WaveGenChannel(name=name, pin=port, wave=self._waveforms[name])

        # Create the AO task with all channels in one call (new API)
        pins = list(self._ports.values())
        self._ao_task = self._daq.create_ao_task(self._uid, pins=pins)
        self._log.info(f"Created AO task '{self._uid}' with pins: {pins}")

        # Configure timing on the task object directly
        self._configure_timing()

        # Create clock/trigger task if configured
        self._setup_clock_task()

        self._is_setup = True
        self._log.info(f"Task '{self._uid}' setup complete")

    def _configure_timing(self) -> None:
        """Configure sample clock timing and trigger on the AO task."""
        if self._ao_task is None:
            raise RuntimeError("AO task not created")

        sample_mode = AcqSampleMode.CONTINUOUS

        if self._timing.clock:
            sample_mode = AcqSampleMode.FINITE
            trigger_source = self._daq.get_pfi_path(self._timing.clock.pin)
            # Configure trigger directly on task object (new API)
            self._ao_task.cfg_dig_edge_start_trig(trigger_source, retriggerable=True)

        # Configure timing directly on task object (new API)
        self._ao_task.cfg_samp_clk_timing(
            float(self._timing.sample_rate),
            sample_mode,
            self._timing.num_samples,
        )

    def _setup_clock_task(self) -> None:
        """Create the clock/trigger task if configured."""
        if not self._timing.clock:
            return

        clock_task_name = f"{self._uid}_clock"
        # Create CO task using new API - returns COTask object
        self._clock_task = self._daq.create_co_task(
            task_name=clock_task_name,
            counter=self._timing.clock.counter,
            frequency_hz=self._timing.frequency,
            duty_cycle=self._timing.clock.duty_cycle,
            output_pin=self._timing.clock.pin,
        )
        self._log.info(
            f"Created clock task '{clock_task_name}' at {self._timing.frequency}Hz on {self._timing.clock.pin}"
        )

    def _write(self) -> None:
        """Generate and write waveform data to the task."""
        if self._ao_task is None:
            raise RuntimeError("AO task not created")

        self._log.info("Writing waveforms to task...")

        # Get channel order from task object directly (new API)
        channel_names = self._ao_task.channel_names

        # Build data array in channel order
        # Map task channel names back to our port names
        # Channel names are typically "{task_name}_{PIN}" format
        data_arrays: list[np.ndarray] = []
        for channel_name in channel_names:
            # Find matching port by checking if channel name ends with the pin
            matched = False
            for name, channel in self._channels.items():
                if channel_name.upper().endswith(channel.pin.upper()):
                    waveform_array = channel.wave.get_array(self._timing.num_samples)
                    data_arrays.append(waveform_array)
                    matched = True
                    break

            if not matched:
                err_msg = f"Channel '{channel_name}' not found in local channels"
                raise ValueError(err_msg)

        # Stack arrays into 2D (channels x samples)
        data = np.vstack(data_arrays) if len(data_arrays) > 1 else data_arrays[0]
        self._log.info(f"Writing {len(data_arrays)} channels x {self._timing.num_samples} samples")

        # Write directly to task object (new API)
        written_samples = self._ao_task.write(data)

        if written_samples != self._timing.num_samples:
            self._log.warning(f"Only wrote {written_samples} samples out of {self._timing.num_samples} requested.")

    def start(self) -> None:
        """Write waveforms and start the acquisition task."""
        if not self._is_setup:
            msg = f"Task '{self._uid}' is not set up. Call setup() first."
            raise RuntimeError(msg)

        if self._ao_task is None:
            raise RuntimeError("AO task not created")

        self._write()

        # Start AO task first (it waits for trigger) - directly on task object
        self._ao_task.start()
        self._log.info(f"Started task '{self._uid}'")

        # Start clock task (sends triggers to AO task) - directly on task object
        if self._clock_task:
            self._clock_task.start()
            self._log.info(f"Started clock task '{self._clock_task.name}'")

    def stop(self) -> None:
        """Stop the acquisition task."""
        # Stop clock task first (stops sending triggers)
        if self._clock_task:
            self._clock_task.stop()
            self._log.info(f"Stopped clock task '{self._clock_task.name}'")

        if self._ao_task:
            self._ao_task.stop()
            self._log.info(f"Stopped task '{self._uid}'")

    def close(self) -> None:
        """Close the task and release resources."""
        # Close clock task first via DAQ (auto-releases pins)
        if self._clock_task:
            task_name = self._clock_task.name
            self._daq.close_task(self._clock_task.name)
            self._log.info(f"Closed clock task '{task_name}'")
            self._clock_task = None

        # Close AO task via DAQ (auto-releases pins)
        if self._ao_task:
            self._daq.close_task(self._uid)
            self._log.info(f"Closed task '{self._uid}'")
            self._ao_task = None

        self._is_setup = False
        self._channels.clear()

    def get_written_waveforms(self, target_points: int | None = None) -> dict[str, list[float]]:
        """Get the waveform data that was/will be written to the DAQ.

        Args:
            target_points: If provided, downsample to approximately this many points
                        using min-max downsampling to preserve peaks. Good values
                        are 1000-2000 for visualization.

        Returns:
            Dictionary mapping device IDs to lists of voltage values.
        """
        if not self._is_setup:
            msg = f"Task '{self._uid}' is not set up"
            raise RuntimeError(msg)

        waveforms = {}
        for name, channel in self._channels.items():
            waveform_array = channel.wave.get_array(self._timing.num_samples)

            # Add rest time as zeros
            rest_samples = int(self._timing.sample_rate * self._timing.rest_time)
            if rest_samples > 0:
                waveform_array = np.concatenate([waveform_array, np.zeros(rest_samples)])

            if target_points and len(waveform_array) > target_points:
                # Downsample using min-max to preserve peaks
                downsampled = self._downsample_minmax(waveform_array, target_points)
                waveforms[name] = downsampled
            else:
                waveforms[name] = waveform_array.tolist()

        return waveforms

    @staticmethod
    def _downsample_minmax(data: np.ndarray, target_points: int) -> list[float]:
        """Downsample using min-max algorithm to preserve peaks and troughs.

        For each bucket of samples, keeps both the minimum and maximum value,
        ensuring that all peaks are preserved in the downsampled data.
        """
        if len(data) <= target_points:
            return data.tolist()

        # Each bucket contributes 2 points (min and max)
        n_buckets = target_points // 2
        bucket_size = len(data) // n_buckets

        downsampled = []
        for i in range(n_buckets):
            start = i * bucket_size
            end = start + bucket_size if i < n_buckets - 1 else len(data)
            bucket = data[start:end]

            # Add min and max from this bucket
            downsampled.extend([float(bucket.min()), float(bucket.max())])

        return downsampled[:target_points]
