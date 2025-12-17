"""DAQ interface module for SPIM systems.

This module provides:
- SpimDaq: Abstract interface for DAQ devices
- AOTask, COTask: Task protocols for analog and counter output
- pulse(): Convenience function for simple voltage pulses
- Supporting types: PinInfo, AcqSampleMode, TaskStatus
"""

from .base import AcqSampleMode, PinInfo, SpimDaq, TaskStatus
from .tasks import AOTask, COTask, DaqTask
from .utils import pulse

__all__ = [
    # Main interface
    "SpimDaq",
    # Task types
    "DaqTask",
    "AOTask",
    "COTask",
    # Supporting types
    "PinInfo",
    "AcqSampleMode",
    "TaskStatus",
    # Utilities
    "pulse",
]
