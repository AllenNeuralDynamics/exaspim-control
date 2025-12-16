"""Simulated DAQ driver for testing purposes."""

from collections.abc import Mapping

import numpy as np

from voxel.new.device.quantity import VoltageRange
from voxel.new.interfaces.daq import (
    AOTask,
    AcqSampleMode,
    COTask,
    PinInfo,
    SpimDaq,
    TaskStatus,
)


class MockAOTask:
    """Mock analog output task for testing.

    Simulates an AO task without actual hardware.
    """

    def __init__(self, name: str, channel_names: list[str]) -> None:
        """Initialize mock AO task.

        Args:
            name: Task name.
            channel_names: List of channel names in this task.
        """
        self._name = name
        self._channel_names = channel_names
        self._status = TaskStatus.IDLE
        self._rate: float = 0.0
        self._sample_mode: AcqSampleMode = AcqSampleMode.FINITE
        self._samps_per_chan: int = 0
        self._trigger_source: str | None = None
        self._retriggerable: bool = False
        self._last_write: np.ndarray | None = None

    @property
    def name(self) -> str:
        """Get the task name."""
        return self._name

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
        self._status = TaskStatus.RUNNING

    def stop(self) -> None:
        """Stop the task."""
        self._status = TaskStatus.IDLE

    def close(self) -> None:
        """Close the task and release resources."""
        self._status = TaskStatus.IDLE
        self._last_write = None

    def wait_until_done(self, timeout: float) -> None:
        """Wait for task completion (immediate in simulation)."""
        # Simulated task completes immediately
        pass

    def write(self, data: np.ndarray) -> int:
        """Write data to the analog output channels.

        Args:
            data: 1D array for single channel, 2D array (channels x samples) for multiple.

        Returns:
            Number of samples written per channel.
        """
        self._last_write = data
        if data.ndim == 1:
            return len(data)
        return data.shape[1]

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
            samps_per_chan: Samples per channel.
        """
        self._rate = rate
        self._sample_mode = sample_mode
        self._samps_per_chan = samps_per_chan

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
        self._trigger_source = trigger_source
        self._retriggerable = retriggerable


class MockCOTask:
    """Mock counter output task for testing.

    Simulates a CO task without actual hardware.
    """

    def __init__(
        self,
        name: str,
        counter_name: str,
        frequency_hz: float,
        duty_cycle: float,
        output_terminal: str | None,
    ) -> None:
        """Initialize mock CO task.

        Args:
            name: Task name.
            counter_name: Name of the counter channel.
            frequency_hz: Pulse frequency in Hz.
            duty_cycle: Duty cycle (0.0 to 1.0).
            output_terminal: Output terminal path or None if using default.
        """
        self._name = name
        self._counter_name = counter_name
        self._frequency_hz = frequency_hz
        self._duty_cycle = duty_cycle
        self._output_terminal = output_terminal
        self._status = TaskStatus.IDLE
        self._trigger_source: str | None = None
        self._retriggerable: bool = False

    @property
    def name(self) -> str:
        """Get the task name."""
        return self._name

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
        self._status = TaskStatus.RUNNING

    def stop(self) -> None:
        """Stop the task."""
        self._status = TaskStatus.IDLE

    def close(self) -> None:
        """Close the task and release resources."""
        self._status = TaskStatus.IDLE

    def wait_until_done(self, timeout: float) -> None:
        """Wait for task completion (immediate in simulation)."""
        # Simulated task completes immediately
        pass

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
        self._trigger_source = trigger_source
        self._retriggerable = retriggerable


class SimulatedDaq(SpimDaq):
    """A simulated DAQ device for testing purposes.

    Provides the full SpimDaq interface without requiring actual hardware.
    """

    def __init__(self, device_name: str = "MockDev1", uid: str = "") -> None:
        """Initialize simulated DAQ device.

        Args:
            device_name: Simulated device name (default: "MockDev1").
            uid: Unique identifier (defaults to lowercase device_name).
        """
        self._uid = uid or device_name.lower()
        self._device_name = device_name

        # Task and pin tracking
        self._active_tasks: dict[str, MockAOTask | MockCOTask] = {}
        self._task_pins: dict[str, list[PinInfo]] = {}
        self._assigned_pins: dict[str, PinInfo] = {}

        # Simulate available pins on the device
        self._all_pins = (
            [f"ao{i}" for i in range(64)]
            + [f"port0/line{i}" for i in range(8)]
            + [f"port1/line{i}" for i in range(8)]
            + [f"ctr{i}" for i in range(4)]
        )

        # Create PFI mappings
        self._pfi_map: dict[str, str] = {}
        for i in range(8):
            self._pfi_map[f"port1/line{i}"] = f"PFI{i}"
            self._pfi_map[f"PFI{i}"] = f"PFI{i}"

    def __repr__(self) -> str:
        return f"SimulatedDaq(uid={self._uid!r}, device={self._device_name!r})"

    # ==================== Properties ====================

    @property
    def uid(self) -> str:
        """Get the unique identifier of the DAQ device."""
        return self._uid

    @property
    def device_name(self) -> str:
        """Get the NI-DAQmx device name."""
        return self._device_name

    @property
    def ao_voltage_range(self) -> VoltageRange:
        """Get the analog output voltage range."""
        return VoltageRange(min=-10.0, max=10.0)

    @property
    def available_pins(self) -> list[str]:
        """Get list of available (unassigned) pin names."""
        assigned = {info.pin for info in self._assigned_pins.values()}
        return [pin for pin in self._all_pins if pin not in assigned]

    @property
    def assigned_pins(self) -> dict[str, PinInfo]:
        """Get dictionary of currently assigned pins (name -> info)."""
        return self._assigned_pins.copy()

    @property
    def active_tasks(self) -> Mapping[str, AOTask | COTask]:
        """Get dictionary of active tasks (name -> task instance)."""
        return self._active_tasks

    # ==================== Pin Management ====================

    def assign_pin(self, task_name: str, pin: str) -> PinInfo:
        """Assign a pin to a task and return its information."""
        pin_upper = pin.upper()
        pin_lower = pin.lower()

        # Check if already assigned
        if pin_lower in self._assigned_pins:
            info = self._assigned_pins[pin_lower]
            if info.task_name != task_name:
                raise ValueError(f"Pin '{pin}' is already assigned to task '{info.task_name}'")
            return info

        # Check if pin is valid
        if pin_lower not in [p.lower() for p in self._all_pins]:
            raise ValueError(f"Pin '{pin}' not available on device '{self._device_name}'")

        # Determine PFI path if applicable
        pfi = self._pfi_map.get(pin_lower)

        info = PinInfo(
            pin=pin_upper,
            path=f"/{self._device_name}/{pin_lower}",
            task_name=task_name,
            pfi=pfi,
        )
        self._assigned_pins[pin_lower] = info
        return info

    def release_pin(self, pin: PinInfo) -> bool:
        """Release a previously assigned pin."""
        pin_lower = pin.pin.lower()
        if pin_lower in self._assigned_pins:
            del self._assigned_pins[pin_lower]
            return True
        return False

    def release_pins_for_task(self, task_name: str) -> None:
        """Release all pins that were assigned to a specific task."""
        pins_to_release = [
            pin_name for pin_name, info in self._assigned_pins.items() if info.task_name == task_name
        ]
        for pin_name in pins_to_release:
            del self._assigned_pins[pin_name]

    def get_pfi_path(self, pin: str) -> str:
        """Get the full PFI path for a given pin."""
        pin_lower = pin.lower()
        pfi = self._pfi_map.get(pin_lower)
        if pfi:
            return f"/{self._device_name}/{pfi}"
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

        try:
            # Assign pins and build channel names
            channel_names: list[str] = []
            for pin in pins:
                pin_info = self.assign_pin(task_name, pin)
                assigned_pins.append(pin_info)
                channel_names.append(f"{task_name}_{pin_info.pin}")

            # Create mock task
            task = MockAOTask(task_name, channel_names)

            # Track task and its pins
            self._active_tasks[task_name] = task
            self._task_pins[task_name] = assigned_pins

            self.log.info(f"Created AO task '{task_name}' with pins: {[p.pin for p in assigned_pins]}")
            return task

        except ValueError:
            # Cleanup on failure
            for pin_info in assigned_pins:
                self.release_pin(pin_info)
            raise

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

        try:
            # Determine output terminal
            output_terminal: str | None = None
            if output_pin:
                output_terminal = self.get_pfi_path(output_pin)

            # Create mock task
            task = MockCOTask(
                name=task_name,
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

        except ValueError:
            # Cleanup on failure
            for pin_info in assigned_pins:
                self.release_pin(pin_info)
            raise

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
            task.stop()

        # Close the task
        task.close()

        # Release pins
        self.release_pins_for_task(task_name)

        # Remove from tracking
        del self._active_tasks[task_name]
        self._task_pins.pop(task_name, None)

        self.log.info(f"Closed task '{task_name}'")

    def close(self) -> None:
        """Close the DAQ device and all active tasks."""
        super().close()
