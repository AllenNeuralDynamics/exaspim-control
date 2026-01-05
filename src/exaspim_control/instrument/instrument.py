import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Thread

import numpy as np
from voxel.device import build_objects
from voxel.interfaces.axes import Axis, DiscreteAxis
from voxel.interfaces.camera import SpimCamera, TriggerMode
from voxel.interfaces.daq import SpimDaq
from voxel.interfaces.laser import SpimLaser
from voxel.interfaces.spim import SpimDevice
from voxel.preview import PreviewFrame, PreviewGenerator

from exaspim_control.instrument.acq_task import AcquisitionTask
from exaspim_control.instrument.config import InstrumentConfig, ProfileConfig

type DeviceGroup[T: SpimDevice] = dict[str, T]
type PreviewFrameSink = Callable[[PreviewFrame], None]
type RawFrameSink = Callable[[np.ndarray, int], None]  # (frame, frame_idx)


@dataclass
class Stage:
    x: Axis
    y: Axis
    z: Axis

    @property
    def uids(self) -> set[str]:
        return {self.x.uid, self.y.uid, self.z.uid}

    def halt(self) -> None:
        """Halt all stage axes immediately."""
        self.x.halt()
        self.y.halt()
        self.z.halt()


class Instrument:
    def __init__(self, config_path):
        self.cfg = InstrumentConfig.from_yaml(Path(config_path))
        self.log = logging.getLogger(self.cfg.info.instrument_uid)

        self.devices, build_errors = build_objects(self.cfg.devices)

        if build_errors:
            error_messages = [f"{uid}: {err.error_type} - {err.traceback}" for uid, err in build_errors.items()]
            msg = "Device build errors:\n" + "\n".join(error_messages)
            raise RuntimeError(msg)

        self.camera = next(device for device in self.devices.values() if isinstance(device, SpimCamera))
        self.daq = next(device for device in self.devices.values() if isinstance(device, SpimDaq))
        self.stage = Stage(
            x=self.devices[self.cfg.stage.x],
            y=self.devices[self.cfg.stage.y],
            z=self.devices[self.cfg.stage.z],
        )
        self.lasers: DeviceGroup[SpimLaser] = {}
        self.filter_wheels: DeviceGroup[DiscreteAxis] = {}
        self.axes: DeviceGroup[Axis] = {}
        self.focusing_axes: DeviceGroup[Axis] = {}

        for device_name, device in self.devices.items():
            if isinstance(device, SpimLaser):
                self.lasers[device_name] = device
            elif isinstance(device, DiscreteAxis):
                self.filter_wheels[device_name] = device
            elif isinstance(device, Axis):
                self.axes[device_name] = device
                if device.uid not in self.stage.uids:
                    self.focusing_axes[device_name] = device

        self._active_profile = next(iter(self.cfg.profiles))

        # Livestream state
        self._is_livestreaming = False
        self._frame_thread: Thread | None = None
        self._frame_idx: int = 0

        # Preview state
        self._preview_sink: PreviewFrameSink = lambda _: None
        self._raw_frame_sink: RawFrameSink | None = None
        self._preview_target_width: int = 1024

        self._acq_task, self._preview_generator = self._set_active_profile(self._active_profile)

    def disable_lasers(self):
        for laser in self.lasers.values():
            laser.disable()

    @property
    def profiles(self) -> dict[str, ProfileConfig]:
        return self.cfg.profiles

    @property
    def preview(self) -> PreviewGenerator:
        return self._preview_generator

    @property
    def acq_task(self) -> AcquisitionTask:
        return self._acq_task

    @property
    def active_channel_laser(self) -> SpimLaser:
        channel_cfg = self.cfg.profiles[self._active_profile]
        return self.lasers[channel_cfg.laser]

    def _disable_channel(self, channel_name: str) -> None:
        """Disable hardware for a channel (laser)."""
        channel_cfg = self.cfg.profiles[channel_name]
        self.lasers[channel_cfg.laser].disable()
        self.log.debug(f"Disabled channel '{channel_name}'")

    def _set_active_profile(self, profile_name: str) -> tuple[AcquisitionTask, PreviewGenerator]:
        self._active_profile = profile_name

        if hasattr(self, "_acq_task") and self._acq_task is not None:
            self._acq_task.close()

        if hasattr(self, "_preview_generator"):
            self._preview_generator.shutdown()

        for filter_name, filter_label in self.cfg.profiles[profile_name].filters.items():
            self.filter_wheels[filter_name].select(filter_label)

        acq_task = AcquisitionTask(
            uid=f"{profile_name}_acq_task",
            daq=self.daq,
            cfg=self.cfg.get_channel_acq_task_config(profile_name),
        )
        acq_task.setup()

        preview_gen = PreviewGenerator(
            preview_sink=self._preview_sink,
            uid=profile_name,
            target_width=self._preview_target_width,
            raw_frame_sink=self._raw_frame_sink,
        )

        return acq_task, preview_gen

    def update_active_profile(self, profile_name: str) -> None:
        if profile_name not in self.cfg.profiles:
            msg = f"Profile '{profile_name}' not in config"
            raise ValueError(msg)

        if profile_name == self._active_profile:
            return

        old_profile = self._active_profile
        was_streaming = self._is_livestreaming
        preview_sink = self._preview_sink
        raw_frame_sink = self._raw_frame_sink

        self.stop_livestream()

        self._acq_task, self._preview_generator = self._set_active_profile(profile_name)

        self.log.info(f"Switched profile: {old_profile} -> {profile_name}")

        if was_streaming:
            self.start_livestream(preview_sink, raw_frame_sink)

    def start_livestream(
        self,
        on_preview: PreviewFrameSink,
        raw_frame_sink: RawFrameSink | None = None,
        *,
        target_width: int = 1024,
    ) -> None:
        if self._is_livestreaming:
            self.log.warning("Livestream already running")
            return

        self._preview_sink = on_preview
        self._raw_frame_sink = raw_frame_sink
        self._preview_target_width = target_width
        self._frame_idx = 0

        # Recreate preview generator with the real sink (includes raw_frame_sink)
        self._acq_task, self._preview_generator = self._set_active_profile(self._active_profile)

        self.disable_lasers()
        self.active_channel_laser.enable()

        self.camera.prepare(trigger_mode=TriggerMode.ON)
        self.camera.start(None)

        if self._acq_task:
            self._acq_task.start()
        else:
            self.log.error("Daq acq_task missing when starting livestream. Profile: %s", self._active_profile)

        self._is_livestreaming = True
        self._frame_thread = Thread(target=self._frame_grabber_loop, daemon=True)
        self._frame_thread.start()

        self.log.info(f"Started livestream on profile '{self._active_profile}'")

    def _frame_grabber_loop(self) -> None:
        self.log.debug("Frame grabber started")

        while self._is_livestreaming:
            try:
                frame = self.camera.grab_frame()
                if frame is not None:
                    # PreviewGenerator copies the frame and sends to both
                    # raw_frame_sink (napari) and preview sink (QLabel)
                    self._preview_generator.new_frame_sync(frame, self._frame_idx)
                    self._frame_idx += 1
            except Exception as e:
                self.log.warning(f"Failed to grab frame: {e}")

        self.log.debug("Frame grabber stopped")

    def stop_livestream(self) -> None:
        if not self._is_livestreaming:
            return

        self._is_livestreaming = False
        self.disable_lasers()

        if self._acq_task is not None:
            self._acq_task.stop()

        if self._frame_thread is not None:
            self._frame_thread.join(timeout=2.0)
            self._frame_thread = None

        self.camera.stop()

        self._preview_sink = lambda _: None
        self._raw_frame_sink = None

        self.log.info("Stopped livestream")

    @property
    def is_livestreaming(self) -> bool:
        return self._is_livestreaming

    def close(self) -> None:
        self.stop_livestream()
        self._preview_generator.shutdown()

        for device in self.devices.values():
            try:
                device.close()
            except Exception as e:
                self.log.warning(f"Failed to close device: {e}")
