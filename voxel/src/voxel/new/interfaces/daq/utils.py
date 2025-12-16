"""Utility functions for DAQ operations.

This module provides convenience functions for common DAQ operations.
"""

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .base import SpimDaq

from .base import AcqSampleMode


def pulse(
    daq: "SpimDaq",
    pin: str,
    duration_s: float,
    voltage_v: float,
    sample_rate_hz: int = 10000,
) -> None:
    """Generate a simple finite pulse on a single analog output pin.

    This is a convenience function that:
    1. Creates a temporary AO task
    2. Writes a pulse waveform at the specified voltage
    3. Waits for completion
    4. Returns the pin to rest voltage (0V)
    5. Cleans up the task

    Args:
        daq: The DAQ device to use.
        pin: Pin name to pulse (e.g., "ao0", "ao5").
        duration_s: Pulse duration in seconds.
        voltage_v: Pulse voltage level in volts.
        sample_rate_hz: Sample rate for the waveform (default: 10000 Hz).

    Example:
        from voxel.new.interfaces.daq import pulse

        # Generate a 100ms pulse at 5V on pin ao5
        pulse(daq, pin="ao5", duration_s=0.1, voltage_v=5.0)

        # Generate a 50ms pulse at 3.3V with higher sample rate
        pulse(daq, pin="ao0", duration_s=0.05, voltage_v=3.3, sample_rate_hz=50000)
    """
    task_name = f"_pulse_{pin}_{daq.uid}"
    num_samples = int(duration_s * sample_rate_hz)

    if num_samples <= 0:
        raise ValueError(f"Invalid duration: {duration_s}s results in {num_samples} samples")

    try:
        # Create task with single channel
        task = daq.create_ao_task(task_name, [pin])

        # Configure finite timing
        task.cfg_samp_clk_timing(
            rate=sample_rate_hz,
            sample_mode=AcqSampleMode.FINITE,
            samps_per_chan=num_samples,
        )

        # Write and execute pulse (high voltage)
        pulse_data = np.full(num_samples, voltage_v, dtype=np.float64)
        task.write(pulse_data)
        task.start()
        task.wait_until_done(timeout=duration_s + 1.0)
        task.stop()

        # Return to rest (0V)
        rest_data = np.zeros(num_samples, dtype=np.float64)
        task.write(rest_data)
        task.start()
        task.wait_until_done(timeout=duration_s + 1.0)

    finally:
        # Always clean up the task (releases pins automatically)
        daq.close_task(task_name)
