import logging
from pathlib import Path

from attr import dataclass
from voxel.devices.base import VoxelDevice
from voxel.devices.camera.base import BaseCamera
from voxel.devices.daq.base import VoxelDAQ
from voxel.devices.filterwheel.base import BaseFilterWheel
from voxel.devices.flip_mount.base import BaseFlipMount
from voxel.devices.joystick.base import BaseJoystick
from voxel.devices.laser.base import BaseLaser
from voxel.devices.stage.base import VoxelAxis

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

    @property
    def limits(self) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
        x_limits = self.x.limits_mm


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
        self.lasers: DeviceGroup = {}
        self.filter_wheels: DeviceGroup = {}
        self.focusing_axes: DeviceGroup = {}
        self.flip_mounts: DeviceGroup = {}
        self.joysticks: DeviceGroup = {}

        for device_name, device in self.devices.items():
            if isinstance(device, BaseLaser):
                self.lasers[device_name] = device
            elif isinstance(device, BaseFilterWheel):
                self.filter_wheels[device_name] = device
            elif isinstance(device, VoxelAxis) and device.uid not in self.stage.uids:
                self.focusing_axes[device_name] = device
            elif isinstance(device, BaseFlipMount):
                self.flip_mounts[device_name] = device
            elif isinstance(device, BaseJoystick):
                self.joysticks[device_name] = device

        self._active_channel = next(iter(self.cfg.channels))
        self.set_active_channel(self._active_channel)

    def set_active_channel(self, channel_name):
        if channel_name not in self.cfg.channels:
            self.log.error(f"Unable to set channel {channel_name}. Channel not found in config.")
        # move logic from gui.py and view/instrument_view.py
        self._active_channel = channel_name

    def close(self):
        """Close all devices."""
        for device in self.devices.values():
            try:
                device.close()
            except Exception as e:
                self.log.warning(f"Failed to close device: {e}")
