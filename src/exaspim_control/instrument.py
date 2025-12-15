import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Thread

import numpy as np
from voxel.devices.axes.continous import VoxelAxis
from voxel.devices.base import VoxelDevice
from voxel.devices.camera.base import BaseCamera
from voxel.devices.daq.acq_task import AcquisitionTask
from voxel.devices.daq.base import VoxelDAQ
from voxel.devices.filterwheel.base import VoxelFilterWheel
from voxel.devices.flip_mount.base import BaseFlipMount
from voxel.devices.joystick.base import BaseJoystick
from voxel.devices.laser.base import BaseLaser

from exaspim_control.build import build_objects
from exaspim_control.config import ExASPIMConfig

type DeviceGroup[T: VoxelDevice] = dict[str, T]


@dataclass
class Stage:
    x: VoxelAxis
    y: VoxelAxis
    z: VoxelAxis
    theta: VoxelAxis | None = None

    @property
    def uids(self) -> set[str]:
        return {self.x.uid, self.y.uid, self.z.uid}


class ExASPIM:
    def __init__(self, config_path):
        self.cfg = ExASPIMConfig.from_yaml(Path(config_path))
        self.log = logging.getLogger(self.cfg.metadata.instrument_uid)

        self.devices, build_errors = build_objects(self.cfg.devices)

        if build_errors:
            error_messages = [f"{uid}: {err.error_type} - {err.traceback}" for uid, err in build_errors.items()]
            msg = "Device build errors:\n" + "\n".join(error_messages)
            raise RuntimeError(msg)

        self.camera = next(device for device in self.devices.values() if isinstance(device, BaseCamera))
        self.daq = next(device for device in self.devices.values() if isinstance(device, VoxelDAQ))
        self.stage = Stage(
            x=self.devices[self.cfg.stage.x],
            y=self.devices[self.cfg.stage.y],
            z=self.devices[self.cfg.stage.z],
            theta=self.devices[self.cfg.stage.theta] if self.cfg.stage.theta else None,
        )
        self.lasers: DeviceGroup[BaseLaser] = {}
        self.filter_wheels: DeviceGroup[VoxelFilterWheel] = {}
        self.axes: DeviceGroup[VoxelAxis] = {}
        self.focusing_axes: DeviceGroup[VoxelAxis] = {}
        self.flip_mounts: DeviceGroup[BaseFlipMount] = {}
        self.joysticks: DeviceGroup[BaseJoystick] = {}

        for device_name, device in self.devices.items():
            if isinstance(device, BaseLaser):
                self.lasers[device_name] = device
            elif isinstance(device, VoxelFilterWheel):
                self.filter_wheels[device_name] = device
            elif isinstance(device, VoxelAxis):
                self.axes[device_name] = device
                if device.uid not in self.stage.uids:
                    self.focusing_axes[device_name] = device
            elif isinstance(device, BaseFlipMount):
                self.flip_mounts[device_name] = device
            elif isinstance(device, BaseJoystick):
                self.joysticks[device_name] = device

        self._active_channel = next(iter(self.cfg.channels))

        # Livestream state
        self._is_livestreaming = False
        self._acq_task: AcquisitionTask | None = None
        self._frame_thread: Thread | None = None
        self._on_frame_callback: Callable[[np.ndarray], None] | None = None

    def disable_lasers(self):
        for laser in self.lasers.values():
            laser.disable()

    @property
    def active_channel_laser(self) -> BaseLaser:
        channel_cfg = self.cfg.channels[self._active_channel]
        return self.lasers[channel_cfg.laser]

    def _disable_channel(self, channel_name: str) -> None:
        """Disable hardware for a channel (laser)."""
        channel_cfg = self.cfg.channels[channel_name]
        self.lasers[channel_cfg.laser].disable()
        self.log.debug(f"Disabled channel '{channel_name}'")

    def set_active_channel(self, channel_name: str) -> None:
        """Switch to a different imaging channel.

        Stops livestream, switches hardware, restarts if was streaming.
        """
        if channel_name not in self.cfg.channels:
            msg = f"Channel '{channel_name}' not in config"
            raise ValueError(msg)

        if channel_name == self._active_channel:
            return  # No change needed

        old_channel = self._active_channel
        callback = self._on_frame_callback  # Preserve callback before stopping

        # Stop livestream (no-op if not streaming)
        self.stop_livestream()

        # Update active channel
        self._active_channel = channel_name

        channel_cfg = self.cfg.channels[channel_name]
        # Set filter positions
        for filter_name, filter_label in channel_cfg.filters.items():
            self.filter_wheels[filter_name].select(filter_label)

        self.log.info(f"Switched channel: {old_channel} -> {channel_name}")

        # Restart livestream with new channel if was running
        if callback:
            self.start_livestream(callback)

    def start_livestream(self, on_frame: Callable[[np.ndarray], None]) -> None:
        """Start livestream with current active channel.

        Args:
            on_frame: Callback invoked with each new frame (np.ndarray)
        """
        if self._is_livestreaming:
            self.log.warning("Livestream already running")
            return

        self._on_frame_callback = on_frame

        # 1. Enable channel hardware (laser) - must happen before DAQ claims pins
        self.disable_lasers()
        self.active_channel_laser.enable()

        # 2. Prepare and start camera (continuous acquisition)
        self.camera.prepare()
        self.camera.start(None)  # None = continuous acquisition

        # 3. Setup and start AcquisitionTask with channel-specific waveforms
        self._acq_task = AcquisitionTask(
            uid=f"livestream_{self._active_channel}",
            daq=self.daq,
            cfg=self.cfg.get_channel_acq_task_config(self._active_channel),
        )
        self._acq_task.setup()
        self._acq_task.start()

        # 4. Start frame grabber thread
        self._is_livestreaming = True
        self._frame_thread = Thread(target=self._frame_grabber_loop, daemon=True)
        self._frame_thread.start()

        self.log.info(f"Started livestream on channel '{self._active_channel}'")

    def _frame_grabber_loop(self) -> None:
        """Thread loop to continuously grab frames from camera."""
        self.log.debug("Frame grabber started")

        while self._is_livestreaming:
            try:
                # Use grab_frame() to actively get new frames (blocks until frame ready)
                frame = self.camera.grab_frame()
                if frame is not None and self._on_frame_callback:
                    self._on_frame_callback(frame)
            except Exception as e:
                self.log.warning(f"Failed to grab frame: {e}")

        self.log.debug("Frame grabber stopped")

    def stop_livestream(self) -> None:
        """Stop livestream gracefully."""
        if not self._is_livestreaming:
            return

        # 1. Set flag first so frame thread stops
        self._is_livestreaming = False

        # 2. Disable channel (laser first for safety)
        self.disable_lasers()

        # 3. Wait for frame thread to finish
        if self._frame_thread is not None:
            self._frame_thread.join(timeout=1.0)
            self._frame_thread = None

        # 4. Stop and close AcquisitionTask
        if self._acq_task is not None:
            self._acq_task.stop()
            self._acq_task.close()
            self._acq_task = None

        # 5. Stop camera
        self.camera.stop()

        # Clear callback
        self._on_frame_callback = None

        self.log.info("Stopped livestream")

    @property
    def is_livestreaming(self) -> bool:
        """Check if livestream is active."""
        return self._is_livestreaming

    def close(self) -> None:
        """Close all devices and clean up."""
        # Stop livestream first if running
        self.stop_livestream()

        # Close all devices
        for device in self.devices.values():
            try:
                device.close()
            except Exception as e:
                self.log.warning(f"Failed to close device: {e}")
