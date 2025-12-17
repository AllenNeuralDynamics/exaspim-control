"""Task protocols for DAQ operations.

This module defines the task interfaces for analog output (AO) and counter output (CO)
operations. Tasks are created via SpimDaq factory methods and provide a clean,
type-safe API for DAQ operations.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from .base import AcqSampleMode, TaskStatus


@runtime_checkable
class DaqTask(Protocol):
    """Base protocol for all DAQ tasks.

    Provides common task lifecycle operations shared by all task types.
    """

    @property
    def name(self) -> str:
        """Get the task name."""
        ...

    @property
    def status(self) -> "TaskStatus":
        """Get the current task status (IDLE, RUNNING, ERROR)."""
        ...

    @property
    def channel_names(self) -> list[str]:
        """Get names of channels in this task."""
        ...

    def start(self) -> None:
        """Start the task."""
        ...

    def stop(self) -> None:
        """Stop the task."""
        ...

    def close(self) -> None:
        """Close the task and release resources."""
        ...

    def wait_until_done(self, timeout: float) -> None:
        """Wait for task completion or timeout.

        Args:
            timeout: Maximum time to wait in seconds.

        Raises:
            TimeoutError: If task does not complete within timeout.
        """
        ...


@runtime_checkable
class AOTask(DaqTask, Protocol):
    """Protocol for analog output tasks.

    AOTasks support:
    - Writing voltage data to analog output channels
    - Sample clock timing configuration
    - Digital edge start triggers (optional)

    Example:
        task = daq.create_ao_task("galvo", pins=["ao0", "ao1"])
        task.cfg_samp_clk_timing(rate=10000, sample_mode=AcqSampleMode.FINITE, samps_per_chan=1000)
        task.write(data)
        task.start()
        task.wait_until_done(timeout=2.0)
        task.stop()
        daq.close_task("galvo")
    """

    def write(self, data: np.ndarray) -> int:
        """Write data to the analog output channels.

        Args:
            data: 1D array for single channel, 2D array (channels x samples) for multiple.

        Returns:
            Number of samples written per channel.
        """
        ...

    def cfg_samp_clk_timing(
        self,
        rate: float,
        sample_mode: "AcqSampleMode",
        samps_per_chan: int,
    ) -> None:
        """Configure sample clock timing.

        Args:
            rate: Sample rate in Hz.
            sample_mode: FINITE or CONTINUOUS acquisition mode.
            samps_per_chan: Samples per channel (buffer size for continuous mode).
        """
        ...

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
        ...


@runtime_checkable
class COTask(DaqTask, Protocol):
    """Protocol for counter output tasks.

    COTasks generate pulse trains with configurable frequency and duty cycle.
    Timing is implicit (based on frequency), not sample-clock based.

    Example:
        task = daq.create_co_task(
            "clock",
            counter="ctr0",
            frequency_hz=1000,
            duty_cycle=0.5,
            output_pin="PFI0"
        )
        task.start()
        # ... pulse train runs ...
        task.stop()
        daq.close_task("clock")
    """

    @property
    def frequency_hz(self) -> float:
        """Get the pulse frequency in Hz."""
        ...

    @property
    def duty_cycle(self) -> float:
        """Get the duty cycle (0.0 to 1.0)."""
        ...

    @property
    def output_terminal(self) -> str | None:
        """Get the output terminal (PFI path) or None if using default."""
        ...

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
        ...
