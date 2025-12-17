"""DAQ interface definitions for SPIM systems.

This module defines the SpimDaq interface and supporting types for data acquisition
operations. The main interface uses factory methods (create_ao_task, create_co_task)
to create typed task objects with automatic channel and pin management.
"""

from abc import abstractmethod
from collections.abc import Mapping
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict
from voxel.device import describe
from voxel.interfaces.spim import DeviceType, SpimDevice

if TYPE_CHECKING:
    from voxel.device.quantity import VoltageRange

    from .tasks import AOTask, COTask


class PinInfo(BaseModel):
    """Information about a channel's various representations and routing options.

    Attributes:
        pin: Port representation (e.g., "AO1", "P1.0", "CTR0").
        path: Physical channel name (e.g., "Dev1/port1/line0", "Dev1/ao0").
        task_name: Name of the task that assigned this pin.
        pfi: PFI representation if applicable (e.g., "PFI0").
    """

    pin: str
    path: str
    task_name: str
    pfi: str | None = None

    model_config = ConfigDict(frozen=True)


class AcqSampleMode(StrEnum):
    """Acquisition sample mode."""

    CONTINUOUS = "continuous"
    FINITE = "finite"


class TaskStatus(StrEnum):
    """Task execution status."""

    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"


class SpimDaq(SpimDevice):
    """Abstract interface for DAQ devices in SPIM systems.

    SpimDaq provides:
    - Pin management (assignment, release, tracking)
    - Task factory methods for AO and CO operations
    - Automatic cleanup on task close

    Example:
        # Create an analog output task
        task = daq.create_ao_task("galvo", pins=["ao0", "ao1"])
        task.cfg_samp_clk_timing(rate=10000, sample_mode=AcqSampleMode.FINITE, samps_per_chan=1000)
        task.write(waveform_data)
        task.start()
        task.wait_until_done(timeout=2.0)
        daq.close_task("galvo")  # Automatically releases pins

        # Create a counter output task
        clock = daq.create_co_task("clock", counter="ctr0", frequency_hz=1000, output_pin="PFI0")
        clock.start()
        # ... later ...
        daq.close_task("clock")

        # Cleanup all tasks
        daq.close()
    """

    __DEVICE_TYPE__ = DeviceType.DAQ

    # ==================== Properties ====================

    @property
    @abstractmethod
    @describe(label="Device Name", desc="NI-DAQmx device identifier")
    def device_name(self) -> str:
        """Get the NI-DAQmx device name."""

    @property
    @abstractmethod
    @describe(label="AO Voltage Range", units="V", desc="Analog output voltage range")
    def ao_voltage_range(self) -> "VoltageRange":
        """Get the analog output voltage range."""

    @property
    @abstractmethod
    @describe(label="Available Pins", desc="List of unassigned pin names", stream=True)
    def available_pins(self) -> list[str]:
        """Get list of available (unassigned) pin names."""

    @property
    @abstractmethod
    @describe(label="Assigned Pins", desc="Currently assigned pin information", stream=True)
    def assigned_pins(self) -> dict[str, PinInfo]:
        """Get dictionary of currently assigned pins (name -> info)."""

    @property
    @abstractmethod
    @describe(label="Active Tasks", desc="Currently active tasks", stream=True)
    def active_tasks(self) -> Mapping[str, "AOTask | COTask"]:
        """Get dictionary of active tasks (name -> task instance)."""

    # ==================== Pin Management ====================

    @abstractmethod
    def assign_pin(self, task_name: str, pin: str) -> PinInfo:
        """Assign a pin to a task and return its information.

        Args:
            task_name: Name of the task claiming this pin.
            pin: Pin name (e.g., "ao0", "ctr0", "PFI0").

        Returns:
            PinInfo with the pin's path and metadata.

        Raises:
            ValueError: If pin is invalid or already assigned to another task.
        """

    @abstractmethod
    def release_pin(self, pin: PinInfo) -> bool:
        """Release a previously assigned pin.

        Args:
            pin: PinInfo of the pin to release.

        Returns:
            True if pin was released, False if it wasn't assigned.
        """

    @abstractmethod
    def release_pins_for_task(self, task_name: str) -> None:
        """Release all pins that were assigned to a specific task.

        Args:
            task_name: Name of the task whose pins should be released.
        """

    @abstractmethod
    def get_pfi_path(self, pin: str) -> str:
        """Get the full PFI path for a given pin.

        Args:
            pin: Pin name (e.g., "PFI0", "P1.2").

        Returns:
            Full PFI path (e.g., "/Dev1/PFI0").

        Raises:
            ValueError: If pin doesn't have a PFI representation.
        """

    # ==================== Task Factory Methods ====================

    @abstractmethod
    @describe(label="Create AO Task", desc="Create an analog output task with channels.")
    def create_ao_task(self, task_name: str, pins: list[str]) -> "AOTask":
        """Create an analog output task with channels for specified pins.

        This method:
        1. Validates task_name is unique
        2. Assigns each pin to this task
        3. Creates the underlying task with AO channels
        4. Registers the task for tracking

        Args:
            task_name: Unique name for the task.
            pins: List of pin names (e.g., ["ao0", "ao1"]) to add as channels.

        Returns:
            Configured AOTask with channels already added.

        Raises:
            ValueError: If task_name already exists or pins are invalid/unavailable.

        Notes:
            Pins are released automatically when the task is closed via close_task().
        """

    @abstractmethod
    @describe(label="Create CO Task", desc="Create a counter output pulse task.")
    def create_co_task(
        self,
        task_name: str,
        counter: str,
        frequency_hz: float,
        duty_cycle: float = 0.5,
        pulses: int | None = None,
        output_pin: str | None = None,
    ) -> "COTask":
        """Create a counter output pulse task.

        This method:
        1. Validates task_name is unique
        2. Assigns the counter pin to this task
        3. Creates the underlying CO task with timing configured
        4. Optionally routes output to a PFI pin
        5. Registers the task for tracking

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

    @abstractmethod
    @describe(label="Close Task", desc="Close a task and release its pins.")
    def close_task(self, task_name: str) -> None:
        """Close a task and release its resources.

        This method:
        1. Stops the task if running
        2. Closes the underlying task
        3. Releases all pins assigned to this task
        4. Removes task from active_tasks

        Args:
            task_name: Name of the task to close.

        Raises:
            ValueError: If task_name doesn't exist.
        """

    # ==================== Lifecycle ====================

    @describe(label="Close", desc="Close the DAQ device and all active tasks.")
    def close(self) -> None:
        """Close the DAQ device and all active tasks.

        This method:
        1. Closes all active tasks (releasing their pins)
        2. Performs any driver-specific cleanup

        Subclasses should call super().close() and add any additional cleanup.
        """
        for task_name in list(self.active_tasks.keys()):
            try:
                self.close_task(task_name)
            except Exception as e:
                self.log.warning(f"Error closing task '{task_name}': {e}")
