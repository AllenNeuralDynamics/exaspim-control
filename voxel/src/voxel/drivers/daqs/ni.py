"""NI DAQ driver implementation for SPIM systems."""

from collections.abc import Mapping
from enum import StrEnum

import numpy as np
from nidaqmx.constants import AcquisitionType as NiAcqType
from nidaqmx.constants import Level as NiLevel
from nidaqmx.errors import DaqError
from nidaqmx.system import System as NiSystem
from nidaqmx.system.device import Device as NiDevice
from nidaqmx.task import Task as NiTask
from voxel.device.quantity import VoltageRange
from voxel.interfaces.daq import (
    AcqSampleMode,
    AOTask,
    COTask,
    PinInfo,
    SpimDaq,
    TaskStatus,
)


class NiAOTask:
    """NI DAQ analog output task implementation.

    Wraps an NI-DAQmx task with analog output channels already configured.
    Channels are added at construction time via the factory method.
    """

    def __init__(self, task: NiTask, channel_names: list[str]) -> None:
        """Initialize with an existing NI task that has AO channels configured.

        Args:
            task: NI-DAQmx task with AO channels already added.
            channel_names: List of channel names in this task.
        """
        self._inst = task
        self._channel_names = channel_names
        self._status = TaskStatus.IDLE

    @property
    def name(self) -> str:
        """Get the task name."""
        return self._inst.name

    @property
    def status(self) -> TaskStatus:
        """Get the current task status."""
        return self._status

    @property
    def channel_names(self) -> list[str]:
        """Get names of channels in this task."""
        return self._channel_names

    def start(self) -> None:
        """Start the task."""
        self._inst.start()
        self._status = TaskStatus.RUNNING

    def stop(self) -> None:
        """Stop the task."""
        self._inst.stop()
        self._status = TaskStatus.IDLE

    def close(self) -> None:
        """Close the task and release resources."""
        self._inst.close()
        self._status = TaskStatus.IDLE

    def wait_until_done(self, timeout: float) -> None:
        """Wait for task completion or timeout.

        Args:
            timeout: Maximum time to wait in seconds.

        Raises:
            TimeoutError: If task does not complete within timeout.
        """
        try:
            self._inst.wait_until_done(timeout=timeout)
        except DaqError as e:
            if "timeout" in str(e).lower():
                raise TimeoutError(f"Task '{self.name}' did not complete within {timeout}s") from e
            raise

    def write(self, data: np.ndarray) -> int:
        """Write data to the analog output channels.

        Args:
            data: 1D array for single channel, 2D array (channels x samples) for multiple.

        Returns:
            Number of samples written per channel.
        """
        return self._inst.write(data)

    def cfg_samp_clk_timing(
        self,
        rate: float,
        sample_mode: AcqSampleMode,
        samps_per_chan: int,
    ) -> None:
        """Configure sample clock timing.

        Args:
            rate: Sample rate in Hz.
            sample_mode: FINITE or CONTINUOUS acquisition mode.
            samps_per_chan: Samples per channel (buffer size for continuous mode).
        """
        ni_sample_mode = NiAcqType.FINITE if sample_mode == AcqSampleMode.FINITE else NiAcqType.CONTINUOUS
        self._inst.timing.cfg_samp_clk_timing(rate=rate, sample_mode=ni_sample_mode, samps_per_chan=samps_per_chan)

    def cfg_dig_edge_start_trig(
        self,
        trigger_source: str,
        *,
        retriggerable: bool = False,
    ) -> None:
        """Configure digital edge start trigger.

        Args:
            trigger_source: PFI path (e.g., "/Dev1/PFI0").
            retriggerable: If True, task restarts on each trigger edge.
        """
        self._inst.triggers.start_trigger.cfg_dig_edge_start_trig(trigger_source=trigger_source)
        self._inst.triggers.start_trigger.retriggerable = retriggerable


class NiCOTask:
    """NI DAQ counter output task implementation.

    Generates pulse trains with configurable frequency and duty cycle.
    Timing is implicit (based on frequency), not sample-clock based.
    """

    def __init__(
        self,
        task: NiTask,
        counter_name: str,
        frequency_hz: float,
        duty_cycle: float,
        output_terminal: str | None,
    ) -> None:
        """Initialize with an existing NI task that has CO channel configured.

        Args:
            task: NI-DAQmx task with CO channel already added.
            counter_name: Name of the counter channel.
            frequency_hz: Pulse frequency in Hz.
            duty_cycle: Duty cycle (0.0 to 1.0).
            output_terminal: Output terminal path or None if using default.
        """
        self._inst = task
        self._counter_name = counter_name
        self._frequency_hz = frequency_hz
        self._duty_cycle = duty_cycle
        self._output_terminal = output_terminal
        self._status = TaskStatus.IDLE

    @property
    def name(self) -> str:
        """Get the task name."""
        return self._inst.name

    @property
    def status(self) -> TaskStatus:
        """Get the current task status."""
        return self._status

    @property
    def channel_names(self) -> list[str]:
        """Get names of channels in this task."""
        return [self._counter_name]

    @property
    def frequency_hz(self) -> float:
        """Get the pulse frequency in Hz."""
        return self._frequency_hz

    @property
    def duty_cycle(self) -> float:
        """Get the duty cycle (0.0 to 1.0)."""
        return self._duty_cycle

    @property
    def output_terminal(self) -> str | None:
        """Get the output terminal (PFI path) or None if using default."""
        return self._output_terminal

    def start(self) -> None:
        """Start the task."""
        self._inst.start()
        self._status = TaskStatus.RUNNING

    def stop(self) -> None:
        """Stop the task."""
        self._inst.stop()
        self._status = TaskStatus.IDLE

    def close(self) -> None:
        """Close the task and release resources."""
        self._inst.close()
        self._status = TaskStatus.IDLE

    def wait_until_done(self, timeout: float) -> None:
        """Wait for task completion or timeout.

        Args:
            timeout: Maximum time to wait in seconds.

        Raises:
            TimeoutError: If task does not complete within timeout.
        """
        try:
            self._inst.wait_until_done(timeout=timeout)
        except DaqError as e:
            if "timeout" in str(e).lower():
                raise TimeoutError(f"Task '{self.name}' did not complete within {timeout}s") from e
            raise

    def cfg_dig_edge_start_trig(
        self,
        trigger_source: str,
        *,
        retriggerable: bool = False,
    ) -> None:
        """Configure digital edge start trigger for the pulse train.

        Args:
            trigger_source: PFI path (e.g., "/Dev1/PFI0").
            retriggerable: If True, pulse train restarts on each trigger edge.
        """
        self._inst.triggers.start_trigger.cfg_dig_edge_start_trig(trigger_source=trigger_source)
        self._inst.triggers.start_trigger.retriggerable = retriggerable


class NiDaqModel(StrEnum):
    """Enumeration of supported NI DAQ models."""

    NI6738 = "PCIe-6738"
    NI6739 = "PCIe-6739"
    OTHER = "other"


class NiDaq(SpimDaq):
    """NI DAQ implementation for SPIM systems.

    Provides pin management and task factory methods for analog and counter output.
    """

    def __init__(self, dev: str, uid: str = "NiDAQ") -> None:
        """Initialize NI DAQ device.

        Args:
            dev: NI-DAQmx device name (e.g., "Dev1").
            uid: Unique identifier for this device.
        """
        super().__init__(uid=uid)
        self._name = dev
        self.system = NiSystem.local()
        self._inst, self.model = self._connect(name=self._name)

        # Task and pin tracking
        self._active_tasks: dict[str, NiAOTask | NiCOTask] = {}
        self._task_pins: dict[str, list[PinInfo]] = {}

        # Pin management
        self.channel_map: dict[str, PinInfo] = {}
        self.assigned_channels: set[str] = set()

        self._initialize_channel_mappings()

    def __repr__(self) -> str:
        return f"NiDaq(uid={self.uid!r}, device={self._name!r}, model={self.model})"

    def _connect(self, name: str) -> tuple[NiDevice, NiDaqModel]:
        """Connect to DAQ device."""
        try:
            nidaq = NiDevice(name)
            nidaq.reset_device()
            if "6738" in nidaq.product_type:
                model = NiDaqModel.NI6738
            elif "6739" in nidaq.product_type:
                model = NiDaqModel.NI6739
            else:
                model = NiDaqModel.OTHER
                self.log.warning(f"DAQ device {nidaq.product_type} might not be fully supported.")
        except DaqError as e:
            err_msg = f"Unable to connect to DAQ device {name}: {e}"
            raise RuntimeError(err_msg) from e
        else:
            return nidaq, model

    def _initialize_channel_mappings(self) -> None:
        """Initialize comprehensive channel mappings."""
        placeholder_task = "unassigned"

        # Handle counter channels
        for co_path in self._inst.co_physical_chans.channel_names:
            co_name = co_path.split("/")[-1].upper()
            self.channel_map[co_name] = PinInfo(pin=co_name, path=co_path, task_name=placeholder_task)

        # Handle analog channels
        for ao_path in self._inst.ao_physical_chans.channel_names:
            ao_name = ao_path.split("/")[-1].upper()
            self.channel_map[ao_name] = PinInfo(pin=ao_name, path=ao_path, task_name=placeholder_task)

        # Handle digital channels and PFI
        def generate_dio_names(dio_path: str) -> tuple[str, str | None]:
            dio_path_parts = dio_path.upper().split("/")
            port_num = int(dio_path_parts[-2].replace("PORT", ""))
            line_num = int(dio_path_parts[-1].replace("LINE", ""))
            pfi_name = f"PFI{(port_num - 1) * 8 + line_num}" if port_num > 0 else None
            line_name = f"P{port_num}.{line_num}"
            return line_name, pfi_name

        for dio_path in self._inst.do_lines.channel_names:
            dio_name, pfi_name = generate_dio_names(dio_path)
            info = PinInfo(pin=dio_name, path=dio_path, pfi=pfi_name, task_name=placeholder_task)
            self.channel_map[dio_name] = info
            if pfi_name:
                self.channel_map[pfi_name] = self.channel_map[dio_name]

    # ==================== Properties ====================

    @property
    def device_name(self) -> str:
        """Get the NI-DAQmx device name."""
        return self._name

    @property
    def ao_voltage_range(self) -> VoltageRange:
        """Get the analog output voltage range."""
        try:
            v_range = self._inst.ao_voltage_rngs
            v_min = v_range[0]
            v_max = v_range[1]
        except (DaqError, ImportError):
            v_min = -5.0
            v_max = 5.0
            self.log.warning("Failed to retrieve voltage range, using default -5V to 5V.")
        return VoltageRange(min=v_min, max=v_max)

    @property
    def available_pins(self) -> list[str]:
        """Get list of available (unassigned) pin names."""
        available = []
        for pin_name, info in self.channel_map.items():
            if info.path not in self.assigned_channels:
                available.append(pin_name)
        return sorted(set(available))

    @property
    def assigned_pins(self) -> dict[str, PinInfo]:
        """Get dictionary of currently assigned pins (name -> info)."""
        assigned = {}
        for pin_name, info in self.channel_map.items():
            if info.path in self.assigned_channels:
                if info.pin not in assigned:
                    assigned[info.pin] = info
        return assigned

    @property
    def active_tasks(self) -> Mapping[str, AOTask | COTask]:
        """Get dictionary of active tasks (name -> task instance)."""
        return self._active_tasks

    # ==================== Pin Management ====================

    def assign_pin(self, task_name: str, pin: str) -> PinInfo:
        """Assign a pin to a task and return its information."""
        pin = pin.upper()
        if pin not in self.channel_map:
            raise ValueError(f"Pin {pin} is not a valid pin name")

        info = self.channel_map[pin]
        if info.path in self.assigned_channels:
            if info.task_name != task_name:
                names = [n for n in (info.pin, info.pfi) if n]
                other_str = f" (also known as {', '.join(names)})" if names else ""
                raise ValueError(f"Pin {pin}{other_str} is already assigned to task '{info.task_name}'")

        # Create a new PinInfo with the correct task_name
        new_info = info.model_copy(update={"task_name": task_name})
        self.channel_map[pin] = new_info
        if new_info.pfi:
            self.channel_map[new_info.pfi] = new_info

        self.assigned_channels.add(new_info.path)
        return new_info

    def release_pin(self, pin: PinInfo) -> bool:
        """Release a previously assigned pin."""
        if pin.path in self.assigned_channels:
            self.assigned_channels.remove(pin.path)

            # Reset task_name to placeholder
            unassigned_info = pin.model_copy(update={"task_name": "unassigned"})
            self.channel_map[pin.pin] = unassigned_info
            if pin.pfi:
                self.channel_map[pin.pfi] = unassigned_info
            return True
        return False

    def release_pins_for_task(self, task_name: str) -> None:
        """Release all pins that were assigned to a specific task."""
        pins_to_release = [info for info in self.channel_map.values() if info.task_name == task_name]
        for pin_info in pins_to_release:
            self.release_pin(pin_info)

    def get_pfi_path(self, pin: str) -> str:
        """Get the full PFI path for a given pin."""
        info = self.channel_map.get(pin.upper())
        if info and info.pfi:
            return f"/{self._name}/{info.pfi}"
        raise ValueError(f"Pin {pin} does not have a PFI path or is not valid.")

    # ==================== Task Factory Methods ====================

    def create_ao_task(self, task_name: str, pins: list[str]) -> AOTask:
        """Create an analog output task with channels for specified pins.

        Args:
            task_name: Unique name for the task.
            pins: List of pin names (e.g., ["ao0", "ao1"]) to add as channels.

        Returns:
            Configured AOTask with channels already added.

        Raises:
            ValueError: If task_name already exists or pins are invalid/unavailable.
        """
        if task_name in self._active_tasks:
            raise ValueError(f"Task '{task_name}' already exists")

        if not pins:
            raise ValueError("At least one pin must be specified")

        assigned_pins: list[PinInfo] = []
        ni_task = NiTask(task_name)

        try:
            # Assign pins and add channels
            channel_names: list[str] = []
            for pin in pins:
                pin_info = self.assign_pin(task_name, pin)
                assigned_pins.append(pin_info)

                # Add AO channel
                channel_name = f"{task_name}_{pin_info.pin}"
                ni_task.ao_channels.add_ao_voltage_chan(pin_info.path, channel_name)
                channel_names.append(channel_name)

            # Create task wrapper
            task = NiAOTask(ni_task, channel_names)

            # Track task and its pins
            self._active_tasks[task_name] = task
            self._task_pins[task_name] = assigned_pins

            self.log.info(f"Created AO task '{task_name}' with pins: {[p.pin for p in assigned_pins]}")
            return task

        except (DaqError, ValueError) as e:
            # Cleanup on failure
            ni_task.close()
            for pin_info in assigned_pins:
                self.release_pin(pin_info)
            raise RuntimeError(f"Failed to create AO task '{task_name}': {e}") from e

    def create_co_task(
        self,
        task_name: str,
        counter: str,
        frequency_hz: float,
        duty_cycle: float = 0.5,
        pulses: int | None = None,
        output_pin: str | None = None,
    ) -> COTask:
        """Create a counter output pulse task.

        Args:
            task_name: Unique name for the task.
            counter: Counter pin name (e.g., "ctr0").
            frequency_hz: Pulse frequency in Hz.
            duty_cycle: Duty cycle (0.0 to 1.0), default 0.5.
            pulses: Number of pulses (None for continuous).
            output_pin: Optional pin to route output to (e.g., "PFI0").

        Returns:
            Configured COTask ready to start.

        Raises:
            ValueError: If task_name exists or counter is invalid/unavailable.
        """
        if task_name in self._active_tasks:
            raise ValueError(f"Task '{task_name}' already exists")

        # Assign the counter pin
        counter_pin_info = self.assign_pin(task_name, counter)
        assigned_pins = [counter_pin_info]

        ni_task = NiTask(task_name)
        output_terminal: str | None = None

        try:
            # Add counter output pulse channel
            co_chan = ni_task.co_channels.add_co_pulse_chan_freq(
                counter=counter_pin_info.path,
                freq=frequency_hz,
                duty_cycle=duty_cycle,
                idle_state=NiLevel.LOW,
            )

            # Route output to specified pin if provided
            if output_pin:
                output_terminal = self.get_pfi_path(output_pin)
                co_chan.co_pulse_term = output_terminal
                self.log.debug(f"Routed CO output to {output_terminal}")

            # Configure timing
            if pulses is None:
                # Continuous mode
                ni_task.timing.cfg_implicit_timing(sample_mode=NiAcqType.CONTINUOUS)
            else:
                # Finite mode
                ni_task.timing.cfg_implicit_timing(
                    sample_mode=NiAcqType.FINITE,
                    samps_per_chan=pulses,
                )

            # Create task wrapper
            task = NiCOTask(
                task=ni_task,
                counter_name=counter_pin_info.pin,
                frequency_hz=frequency_hz,
                duty_cycle=duty_cycle,
                output_terminal=output_terminal,
            )

            # Track task and its pins
            self._active_tasks[task_name] = task
            self._task_pins[task_name] = assigned_pins

            self.log.info(f"Created CO task '{task_name}': {frequency_hz}Hz, duty={duty_cycle}")
            return task

        except (DaqError, ValueError) as e:
            # Cleanup on failure
            ni_task.close()
            for pin_info in assigned_pins:
                self.release_pin(pin_info)
            raise RuntimeError(f"Failed to create CO task '{task_name}': {e}") from e

    def close_task(self, task_name: str) -> None:
        """Close a task and release its resources.

        Args:
            task_name: Name of the task to close.

        Raises:
            ValueError: If task_name doesn't exist.
        """
        if task_name not in self._active_tasks:
            raise ValueError(f"Task '{task_name}' does not exist")

        task = self._active_tasks[task_name]

        # Stop if running
        if task.status == TaskStatus.RUNNING:
            try:
                task.stop()
            except DaqError as e:
                self.log.warning(f"Error stopping task '{task_name}': {e}")

        # Close the underlying task
        try:
            task.close()
        except DaqError as e:
            self.log.warning(f"Error closing task '{task_name}': {e}")

        # Release pins
        self.release_pins_for_task(task_name)

        # Remove from tracking
        del self._active_tasks[task_name]
        self._task_pins.pop(task_name, None)

        self.log.info(f"Closed task '{task_name}'")

    def close(self) -> None:
        """Close the DAQ device and all active tasks."""
        # Close all active tasks
        super().close()

        # Reset the device
        try:
            self._inst.reset_device()
        except DaqError as e:
            self.log.warning(f"Error resetting device: {e}")
