"""Device adapter using voxel.device interface system."""

import logging
import time
from threading import Thread

from PyQt6.QtCore import QObject, pyqtSignal
from voxel.device import (
    Command,
    DeviceInterface,
    PropertyInfo,
    collect_commands,
    collect_properties,
)
from voxel.interfaces.spim import SpimDevice


class DeviceAdapter[D: SpimDevice](QObject):
    """Adapter for SpimDevice using voxel.device introspection.

    Handles:
    - Property/command collection via collect_properties/collect_commands
    - Polling for streaming properties (stream=True)
    - Qt signal for thread-safe UI updates

    Inherits from QObject to enable thread-safe signal emission from polling thread.
    """

    # Signal emitted when a property value changes (thread-safe)
    # Args: property_name (str), value (object)
    propertyUpdated = pyqtSignal(str, object)

    def __init__(self, device: D, parent: QObject | None = None):
        super().__init__(parent)
        self._device = device
        self._properties = collect_properties(device)
        self._commands = collect_commands(device)
        self._polling = False
        self._poll_thread: Thread | None = None
        self.log = logging.getLogger(f"{__name__}.{device.uid}")

    @property
    def device(self) -> D:
        return self._device

    @property
    def interface(self) -> DeviceInterface:
        return DeviceInterface(
            uid=self._device.uid,
            type=self._device.__DEVICE_TYPE__,
            properties=self._properties,
            commands={name: cmd.info for name, cmd in self._commands.items()},
        )

    @property
    def properties(self) -> dict[str, PropertyInfo]:
        return self._properties

    @property
    def streaming_properties(self) -> dict[str, PropertyInfo]:
        """Get properties that should be polled (stream=True)."""
        return {name: info for name, info in self._properties.items() if info.stream}

    @property
    def commands(self) -> dict[str, Command]:
        return self._commands

    def start_polling(self, interval_ms: int = 500) -> None:
        """Start polling streaming properties."""
        if self._polling:
            return
        if not self.streaming_properties:
            self.log.debug("No streaming properties to poll")
            return
        self._polling = True
        self._poll_interval_ms = interval_ms
        self._poll_thread = Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        self.log.debug(f"Started polling {list(self.streaming_properties.keys())}")

    def stop_polling(self) -> None:
        """Stop polling streaming properties."""
        self._polling = False
        if self._poll_thread:
            self._poll_thread.join(timeout=1.0)
            self._poll_thread = None
            self.log.debug("Stopped polling")

    def _poll_loop(self) -> None:
        """Background thread that polls streaming properties."""
        props_to_poll = list(self.streaming_properties.keys())
        poll_interval_s = self._poll_interval_ms / 1000.0

        while self._polling:
            # Sleep in small increments for responsive shutdown
            sleep_increments = max(1, int(poll_interval_s / 0.1))
            for _ in range(sleep_increments):
                if not self._polling:
                    return
                time.sleep(0.1)

            for name in props_to_poll:
                if not self._polling:
                    return
                try:
                    value = getattr(self._device, name)
                    self._notify(name, value)
                except Exception as e:
                    self.log.warning(f"Failed to poll {name}: {e}")

    def _notify(self, prop_name: str, value: object) -> None:
        """Emit property update signal (thread-safe).

        Qt automatically marshals this to the main thread when receivers
        are connected with AutoConnection (default) or QueuedConnection.
        """
        self.propertyUpdated.emit(prop_name, value)

    def set_property(self, name: str, value: object) -> None:
        """Set a property value on the device."""
        setattr(self._device, name, value)

    def get_property(self, name: str) -> object:
        """Get a property value from the device."""
        return getattr(self._device, name)

    def execute_command(self, name: str, *args, **kwargs) -> object:
        """Execute a command on the device."""
        if name not in self._commands:
            raise ValueError(f"Unknown command: {name}")
        return self._commands[name](*args, **kwargs)
