from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol # Keep Protocol for AOChannelInst if it's still a protocol

import numpy as np
from pydantic import BaseModel, ConfigDict
from voxel.devices.base import VoxelDevice

if TYPE_CHECKING:
    from .quantity import VoltageRange


class AOChannelInst(Protocol):
    """Protocol for analog output channel instances."""

    @property
    def name(self) -> str:
        """Get the name of the channel."""
        ...


class DaqTaskInst(ABC):
    """Abstract Base Class for DAQ task instances."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of the DAQ task."""
        ...

    @property
    @abstractmethod
    def status(self) -> "TaskStatus":
        """Get the current status of the task."""
        ...

    @property
    def info(self) -> "TaskInfo": # This is a concrete implementation, not abstract
        return TaskInfo(
            name=self.name,
            status=self.status,
            channels=self.get_channel_names(),
        )

    @abstractmethod
    def write(self, data: np.ndarray) -> int:
        """Write data to the DAQ task."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Start the DAQ task."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop the DAQ task."""
        ...

    @abstractmethod
    def wait_until_done(self, timeout: float) -> None:
        """Wait until the task is done or the timeout is reached."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close the DAQ task."""
        ...

    @abstractmethod
    def add_ao_channel(self, path: str, name: str) -> AOChannelInst:
        """Add an analog output voltage channel."""
        ...

    @abstractmethod
    def cfg_samp_clk_timing(self, rate: float, sample_mode: "AcqSampleMode", samps_per_chan: int) -> None:
        """Configure sample clock timing."""
        ...

    @abstractmethod
    def cfg_dig_edge_start_trig(self, trigger_source: str, *, retriggerable: bool) -> None:
        """Configure digital edge start trigger."""
        ...

    @abstractmethod
    def get_channel_names(self) -> list[str]:
        """Get the names of the channels in the task."""
        ...


class PinInfo(BaseModel):
    """Information about a channel's various representations and routing options."""

    pin: str  # Port representation if applicable (e.g., "AO1", "P1.0", "CTR0")
    path: str  # The physical channel name (e.g., "Dev1/port1/line0", "Dev1/ao0", "Dev1/ctr0")
    task_name: str  # The name of the task that assigned this pin
    pfi: str | None = None  # PFI representation if applicable (e.g., "PFI0")

    model_config = ConfigDict(frozen=True)


class AcqSampleMode(StrEnum):
    CONTINUOUS = "continuous"
    FINITE = "finite"


class TaskStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"


class TaskInfo(BaseModel):
    name: str
    status: TaskStatus
    channels: list[str]


class VoxelDAQ(VoxelDevice):
    def __init__(self, uid: str):
        super().__init__(uid=uid)
        self._tasks: dict[str, DaqTaskInst] = {}
        self._task_pins: dict[str, list[PinInfo]] = {}  # Track pins per task for cleanup

    def active_tasks(self) -> list[str]:
        return list(self._tasks.keys())

    def create_task(self, task_name: str) -> str:
        """Create a new DAQ task instance."""
        if task_name in self._tasks:
            msg = f"Task '{task_name}' already exists"
            raise ValueError(msg)

        task_inst = self._create_task_inst(task_name)
        self._tasks[task_name] = task_inst
        self._task_pins[task_name] = []
        self.log.info(f"Created task '{task_name}'")
        return task_name

    def _ensure_task(self, task_name) -> DaqTaskInst:
        if task_name not in self._tasks:
            msg = f"Task '{task_name}' does not exist"
            raise ValueError(msg)
        return self._tasks[task_name]

    def add_ao_channel(self, task_name: str, path: str, channel_name: str) -> str:
        """Add an analog output voltage channel to a task."""
        task = self._ensure_task(task_name)
        channel = task.add_ao_channel(path, channel_name)
        self.log.debug(f"Added AO channel '{channel_name}' to task '{task_name}'")
        return channel.name

    def cfg_samp_clk_timing(self, task_name: str, rate: float, sample_mode: AcqSampleMode, samps_per_chan: int) -> None:
        """Configure sample clock timing for a task."""
        task = self._ensure_task(task_name)
        task.cfg_samp_clk_timing(rate, sample_mode, samps_per_chan)
        self.log.debug(f"Configured timing for task '{task_name}': rate={rate}, mode={sample_mode}")

    def cfg_dig_edge_start_trig(self, task_name: str, trigger_source: str, retriggerable: bool = False) -> None:
        """Configure digital edge start trigger for a task."""
        task = self._ensure_task(task_name)
        task.cfg_dig_edge_start_trig(trigger_source, retriggerable=retriggerable)
        self.log.debug(f"Configured trigger for task '{task_name}': source={trigger_source}")

    def write(self, task_name: str, data: list[list[float]]) -> int:
        """Write data to a task. Data is 2D: [channels][samples]."""
        task = self._ensure_task(task_name)
        np_data = np.array(data, dtype=np.float64)
        samples_written = task.write(np_data)
        self.log.debug(f"Wrote {samples_written} samples to task '{task_name}'")
        return samples_written

    def start_task(self, task_name: str) -> None:
        """Start a task."""
        self._ensure_task(task_name).start()
        self.log.info(f"Started task '{task_name}'")

    def stop_task(self, task_name: str) -> None:
        """Start a task."""
        self._ensure_task(task_name).stop()
        self.log.info(f"Stopped task '{task_name}'")

    def close_task(self, task_name: str) -> None:
        """Close a task and release its resources."""
        task = self._ensure_task(task_name)
        task.close()
        for pin_info in self._task_pins.get(task_name, []):
            self.release_pin(pin_info)
        del self._tasks[task_name]
        del self._task_pins[task_name]
        self.log.info(f"Closed task '{task_name}'")

    def get_task_info(self, task_name: str) -> TaskInfo:
        """Get information about a specific task."""
        return self._ensure_task(task_name).info

    @property
    @abstractmethod
    def device_name(self) -> str:
        """Get the NI-DAQmx device name."""

    @property
    @abstractmethod
    def ao_voltage_range(self) -> "VoltageRange":
        """Get the analog output voltage range."""

    @property
    @abstractmethod
    def available_pins(self) -> list[str]:
        """Get list of available (unassigned) pin names."""

    @property
    @abstractmethod
    def assigned_pins(self) -> dict[str, PinInfo]:
        """Get dictionary of currently assigned pins (name -> info)."""

    @abstractmethod
    def assign_pin(self, task_name: str, pin: str) -> PinInfo:
        """Assign a pin to the DAQ device and return its information."""

    @abstractmethod
    def release_pin(self, pin: PinInfo) -> bool:
        """Release a previously assigned pin."""

    @abstractmethod
    def release_pins_for_task(self, task_name: str) -> None:
        """Release all pins that were assigned to a specific task."""

    @abstractmethod
    def get_pfi_path(self, pin: str) -> str:
        """Get the PFI path for a given pin."""

    @abstractmethod
    def pulse(self, pin: str, duration_s: float, voltage_v: float) -> None:
        """Generates a simple finite pulse on a single pin."""
        raise NotImplementedError

    @abstractmethod
    def _create_task_inst(self, task_name: str) -> DaqTaskInst:
        """Get a new task instance for the DAQ device."""
