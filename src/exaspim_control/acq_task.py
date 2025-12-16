import logging
from dataclasses import dataclass
from typing import Any, Self

import numpy as np
from pydantic import BaseModel, Field, computed_field, model_validator
from voxel.devices.daq.base import AcqSampleMode, PinInfo, VoxelDAQ
from voxel.devices.daq.quantity import Frequency, NormalizedRange, Time
from voxel.devices.daq.wave import Waveform


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
    pin_info: PinInfo
    wave: "Waveform"


class AcquisitionTask:
    """Orchestrates DAQ task creation and control via a DaqClient.

    This class lives in the Rig's process and communicates with the DAQ
    hardware through the DaqClient (which talks to DaqService over ZMQ).
    """

    def __init__(self, *, uid: str, daq: VoxelDAQ, cfg: AcqTaskConfig) -> None:
        self._uid = uid
        self._log = logging.getLogger(self._uid)
        self._daq = daq
        self._timing = cfg.timing
        self._waveforms = cfg.waveforms
        self._ports = cfg.ports
        self._channels: dict[str, WaveGenChannel] = {}
        self._clock_task_uid: str | None = None
        self._is_setup = False

    @property
    def uid(self) -> str:
        return self._uid

    def setup(self) -> None:
        """Set up the task: create task, assign pins, add channels, configure timing."""
        if self._is_setup:
            msg = f"Task '{self._uid}' is already set up"
            raise RuntimeError(msg)

        # Create the task on the service
        self._daq.create_task(self._uid)
        self._log.info(f"Created task '{self._uid}'")

        # Assign pins and add channels
        self._initialize_channels()

        # Configure timing
        self._configure_timing()

        # Create clock/trigger task if configured
        self._setup_clock_task()

        self._is_setup = True
        self._log.info(f"Task '{self._uid}' setup complete")

    def _initialize_channels(self) -> None:
        """Initialize pins and channels for the task."""
        for name, port in self._ports.items():
            if name not in self._waveforms:
                err_msg = f"No waveform defined for port '{name}'"
                raise ValueError(err_msg)

            # Assign pin via client
            pin_info = self._daq.assign_pin(task_name=self._uid, pin=port)
            self._log.debug(f"Assigned pin {name}: {pin_info}")

            # Add AO channel
            self._daq.add_ao_channel(self._uid, pin_info.path, name)
            self._log.debug(f"Added channel {name} with pin {pin_info.path}")

            # Store channel info locally
            self._channels[name] = WaveGenChannel(name=name, pin_info=pin_info, wave=self._waveforms[name])

    def _configure_timing(self) -> None:
        """Configure sample clock timing and trigger."""
        sample_mode = AcqSampleMode.CONTINUOUS

        if self._timing.clock:
            sample_mode = AcqSampleMode.FINITE
            trigger_source = self._daq.get_pfi_path(self._timing.clock.pin)
            self._daq.cfg_dig_edge_start_trig(self._uid, trigger_source, retriggerable=True)

        self._daq.cfg_samp_clk_timing(
            self._uid,
            float(self._timing.sample_rate),
            sample_mode,
            self._timing.num_samples,
        )

    def _setup_clock_task(self) -> None:
        """Create the clock/trigger task if configured."""
        if not self._timing.clock:
            return

        self._clock_task_uid = f"{self._uid}_clock"
        self._daq.create_co_pulse_task(
            task_name=self._clock_task_uid,
            counter=self._timing.clock.counter,
            frequency_hz=self._timing.frequency,
            duty_cycle=self._timing.clock.duty_cycle,
            output_pin=self._timing.clock.pin,
        )
        self._log.info(
            f"Created clock task '{self._clock_task_uid}' at {self._timing.frequency}Hz on {self._timing.clock.pin}"
        )

    def _write(self) -> None:
        """Generate and write waveform data to the task."""
        self._log.info("Writing waveforms to task...")

        # Get channel order from service
        task_info = self._daq.get_task_info(self._uid)
        channel_names = task_info.channels

        # Build data array in channel order
        data: list[list[float]] = []
        for name in channel_names:
            if name not in self._channels:
                err_msg = f"Channel '{name}' not found in local channels"
                raise ValueError(err_msg)
            waveform_array = self._channels[name].wave.get_array(self._timing.num_samples)
            data.append(waveform_array.tolist())

        self._log.info(f"Writing {len(data)} channels x {self._timing.num_samples} samples")
        written_samples = self._daq.write(self._uid, data)

        if written_samples != self._timing.num_samples:
            self._log.warning(f"Only wrote {written_samples} samples out of {self._timing.num_samples} requested.")

    def start(self) -> None:
        """Write waveforms and start the acquisition task."""
        if not self._is_setup:
            msg = f"Task '{self._uid}' is not set up. Call setup() first."
            raise RuntimeError(msg)

        self._write()

        # Start AO task first (it waits for trigger)
        self._daq.start_task(self._uid)
        self._log.info(f"Started task '{self._uid}'")

        # Start clock task (sends triggers to AO task)
        if self._clock_task_uid:
            self._daq.start_task(self._clock_task_uid)
            self._log.info(f"Started clock task '{self._clock_task_uid}'")

    def stop(self) -> None:
        """Stop the acquisition task."""
        # Stop clock task first (stops sending triggers)
        if self._clock_task_uid:
            self._daq.stop_task(self._clock_task_uid)
            self._log.info(f"Stopped clock task '{self._clock_task_uid}'")

        self._daq.stop_task(self._uid)
        self._log.info(f"Stopped task '{self._uid}'")

    def close(self) -> None:
        """Close the task and release resources."""
        # Close clock task first
        if self._clock_task_uid:
            self._daq.close_task(self._clock_task_uid)
            self._log.info(f"Closed clock task '{self._clock_task_uid}'")
            self._clock_task_uid = None

        self._daq.close_task(self._uid)
        self._is_setup = False
        self._channels.clear()
        self._log.info(f"Closed task '{self._uid}'")

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
