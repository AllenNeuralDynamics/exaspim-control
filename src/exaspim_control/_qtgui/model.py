"""InstrumentModel - Reactive model wrapping an ExASPIM instrument."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from threading import Thread
from typing import TYPE_CHECKING

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from voxel.device import (
    Command,
    DeviceInterface,
    PropertyInfo,
    collect_commands,
    collect_properties,
)
from voxel.interfaces.spim import SpimDevice
from voxel.preview import PreviewFrame

if TYPE_CHECKING:
    from exaspim_control.instrument.instrument import Instrument

from exaspim_control.instrument.instrument import InstrumentMode

# Callback types for streaming
type PreviewFrameSink = Callable[[PreviewFrame], None]
type RawFrameSink = Callable[[np.ndarray, int], None]  # (frame, frame_idx)


class InstrumentModel(QObject):
    """Reactive model wrapping an ExASPIM instrument with DeviceAdapters.

    Mirrors the structure of ExASPIM but provides DeviceAdapters instead of
    raw devices. Manages adapter lifecycle (polling start/stop) and holds
    reactive stage/FOV state for UI updates.

    Attributes:
        camera: Adapter for the primary camera
        daq: Adapter for the DAQ (may be None)
        lasers: Dict of laser adapters by UID
        filter_wheels: Dict of filter wheel adapters by UID
        axes: Dict of all axis adapters by name
        focusing_axes: Dict of focusing axis adapters by name
        stage_adapters: Dict of stage axis adapters (keys: "x", "y", "z")
    """

    # Reactive state signals
    fovPositionChanged = pyqtSignal(list)
    fovDimensionsChanged = pyqtSignal(list)
    stageLimitsChanged = pyqtSignal(list)
    stageMovingChanged = pyqtSignal(bool)
    modeChanged = pyqtSignal(InstrumentMode)

    def __init__(self, instrument: Instrument, parent: QObject | None = None):
        """Initialize InstrumentModel.

        Args:
            instrument: The ExASPIM instrument instance
            parent: Parent QObject
        """
        super().__init__(parent)
        self._instrument = instrument
        self._globals = instrument.cfg.globals
        self.log = logging.getLogger(f"{__name__}.{instrument.cfg.info.instrument_uid}")

        # Create adapters for ALL devices (mirrors instrument.devices)
        self._adapters: dict[str, DeviceAdapter] = {
            name: DeviceAdapter(device, parent=self) for name, device in instrument.devices.items()
        }

        # === Grouped adapter access (mirrors ExASPIM structure) ===

        # Single devices
        self.camera = self._adapters[instrument.camera.uid]
        self.daq = self._adapters[instrument.daq.uid] if instrument.daq else None

        # Device groups
        self.lasers = {uid: self._adapters[uid] for uid in instrument.lasers}
        self.filter_wheels = {uid: self._adapters[uid] for uid in instrument.filter_wheels}
        self.axes = {name: self._adapters[axis.uid] for name, axis in instrument.axes.items()}
        self.focusing_axes = {name: self._adapters[axis.uid] for name, axis in instrument.focusing_axes.items()}

        # Stage adapters (named x, y, z for StageWidget)
        self.stage_adapters = {
            "x": self._adapters[instrument.stage.x.uid],
            "y": self._adapters[instrument.stage.y.uid],
            "z": self._adapters[instrument.stage.z.uid],
        }

        # === Config values ===
        self._unit = self._globals.unit
        self._fov_dimensions: list[float] = list(self._calculate_fov_dimensions())

        # Subscribe to stage adapter property updates for signal emission
        for adapter in self.stage_adapters.values():
            adapter.propertyUpdated.connect(self._on_stage_property)

        self.log.debug(
            f"Created InstrumentModel with {len(self._adapters)} adapters: "
            f"{len(self.lasers)} lasers, {len(self.filter_wheels)} filter wheels, "
            f"{len(self.axes)} axes"
        )

    # === Config Properties (read-only) ===

    @property
    def unit(self) -> str:
        """Unit for all measurements (e.g., 'mm')."""
        return self._unit

    # === Reactive FOV/Stage Properties (computed from adapters) ===

    @property
    def fov_position(self) -> list[float]:
        """Current FOV position [x, y, z] - read from stage adapters."""
        return [a.device.position_mm for a in self.stage_adapters.values()]

    @property
    def fov_dimensions(self) -> list[float]:
        """FOV dimensions [width, height, depth]."""
        return self._fov_dimensions

    @property
    def stage_limits(self) -> list[list[float]]:
        """Stage limits [[xmin, xmax], [ymin, ymax], [zmin, zmax]] - read from devices."""
        return self._get_stage_limits()

    @property
    def stage_moving(self) -> bool:
        """Whether any stage axis is currently moving - read from stage adapters."""
        return any(a.device.is_moving for a in self.stage_adapters.values())

    @property
    def mode(self) -> InstrumentMode:
        """Current operating mode of the instrument."""
        return self._instrument.mode

    # === Adapter Access ===

    @property
    def all_adapters(self) -> dict[str, DeviceAdapter]:
        """All adapters by device UID (for DevicesTab)."""
        return self._adapters

    @property
    def frame_task(self):
        """Current frame task (may be None when not streaming)."""
        return self._instrument.frame_task

    @property
    def profile_names(self) -> list[str]:
        """Available profile names for channel switching."""
        return list(self._instrument.profiles.keys())

    # === Actions ===

    def halt_stage(self) -> None:
        """Halt all stage axes immediately."""
        self._instrument.stage.halt()

    def set_active_profile(self, profile_name: str) -> None:
        """Switch to a different imaging profile (laser/filter configuration).

        Handles stopping livestream if running, switching hardware, and restarting.
        """
        self._instrument.update_active_profile(profile_name)
        self.log.info(f"Profile changed to: {profile_name}")

    def start_preview(
        self,
        on_preview: PreviewFrameSink,
        raw_frame_sink: RawFrameSink | None = None,
    ) -> None:
        """Start camera preview with callbacks.

        Args:
            on_preview: Callback for processed preview frames (for QLabel display)
            raw_frame_sink: Optional callback for raw frames (for napari viewer)
        """
        self._instrument.start_live_preview(on_preview=on_preview, raw_frame_sink=raw_frame_sink)
        self.modeChanged.emit(self._instrument.mode)
        self.log.debug("Preview started")

    def stop_preview(self) -> None:
        """Stop camera preview."""
        self._instrument.stop_live_preview()
        self.modeChanged.emit(self._instrument.mode)
        self.log.debug("Preview stopped")

    def take_snapshot(self) -> np.ndarray | None:
        """Capture a single frame from the camera.

        Returns:
            Captured frame as numpy array, or None if capture failed.
        """
        self.log.warning("take_snapshot() not yet implemented")
        return None

    # === Private Helpers ===

    def _calculate_fov_dimensions(self) -> tuple[float, float, float]:
        """Calculate FOV dimensions from camera and objective settings."""
        magnification = self._globals.objective_magnification
        camera = self._instrument.camera

        # Physical FOV from frame area divided by magnification
        area = camera.frame_area_mm
        width_mm = area.x / magnification
        height_mm = area.y / magnification

        # Swap width/height if camera is rotated 90 or 270 degrees
        cam_rotation = self._globals.camera_rotation_deg
        if cam_rotation in [-270, -90, 90, 270]:
            return (height_mm, width_mm, 0.0)
        return (width_mm, height_mm, 0.0)

    def _get_stage_limits(self) -> list[list[float]]:
        """Get stage limits from hardware."""
        stage = self._instrument.stage
        return [
            [stage.x.lower_limit_mm, stage.x.upper_limit_mm],
            [stage.y.lower_limit_mm, stage.y.upper_limit_mm],
            [stage.z.lower_limit_mm, stage.z.upper_limit_mm],
        ]

    def _on_stage_property(self, prop_name: str, _value: object) -> None:
        """Handle stage axis property updates - emit aggregated signals."""
        if prop_name == "position_mm":
            self.fovPositionChanged.emit(self.fov_position)
        elif prop_name == "is_moving":
            self.stageMovingChanged.emit(self.stage_moving)
        elif prop_name in ("lower_limit_mm", "upper_limit_mm"):
            self.stageLimitsChanged.emit(self.stage_limits)

    # === Lifecycle ===

    def start_polling(self) -> None:
        """Start polling on adapters with streaming properties."""
        started = 0
        for adapter in self._adapters.values():
            if adapter.streaming_properties:
                adapter.start_polling()
                started += 1
        self.log.debug(f"Started polling on {started} adapters")

    def stop_polling(self) -> None:
        """Stop polling on all adapters."""
        for adapter in self._adapters.values():
            adapter.stop_polling()
        self.log.debug("Stopped polling on all adapters")


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
        self._stopping = False  # Suppresses warnings during shutdown
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
        self._stopping = True  # Suppress warnings from race conditions during shutdown
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
                    # Suppress warnings during shutdown (race condition with Qt cleanup)
                    # Also suppress "deleted" errors which occur when Qt objects are garbage collected
                    if not self._stopping and "deleted" not in str(e):
                        self.log.warning(f"Failed to poll {name}: {e}")

    def _notify(self, prop_name: str, value: object) -> None:
        """Emit property update signal (thread-safe).

        Qt automatically marshals this to the main thread when receivers
        are connected with AutoConnection (default) or QueuedConnection.
        """
        self.propertyUpdated.emit(prop_name, value)

    def refresh(self) -> None:
        """Force refresh all streaming properties (one-shot poll)."""
        for name in self.streaming_properties:
            try:
                value = getattr(self._device, name)
                self._notify(name, value)
            except Exception as e:
                self.log.warning(f"Failed to refresh {name}: {e}")

    def set_property(self, name: str, value: object) -> None:
        """Set a property value on the device."""
        setattr(self._device, name, value)

    def get_property(self, name: str) -> object:
        """Get a property value from the device."""
        return getattr(self._device, name)

    def execute_command(self, name: str, *args, **kwargs) -> object:
        """Execute a command on the device."""
        if name not in self._commands:
            msg = f"Unknown command: {name}"
            raise ValueError(msg)
        return self._commands[name](*args, **kwargs)
