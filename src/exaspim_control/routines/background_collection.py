import logging
import numpy as np
import tifffile
from pathlib import Path
from voxel.devices.camera.base import BaseCamera


class BackgroundCollection:

    def __init__(self, path: str):

        super().__init__()
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._path = Path(path)
        self._frame_count_px = 1
        self._filename = None
        self._acquisition_name = Path()
        self._data_type = None

    @property
    def frame_count_px(self):
        return self._frame_count_px

    @frame_count_px.setter
    def frame_count_px(self, frame_count_px: int):
        self._frame_count_px = frame_count_px

    @property
    def data_type(self):
        return self._data_type

    @data_type.setter
    def data_type(self, data_type: np.unsignedinteger):
        self.log.info(f"setting data type to: {data_type}")
        self._data_type = data_type

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, path: str):
        self._path = Path(path)
        self.log.info(f"setting path to: {path}")

    @property
    def acquisition_name(self):
        return self._acquisition_name

    @acquisition_name.setter
    def acquisition_name(self, acquisition_name: str):
        self._acquisition_name = Path(acquisition_name)
        self.log.info(f"setting acquisition name to: {acquisition_name}")

    @property
    def filename(self):
        return self._filename

    @filename.setter
    def filename(self, filename: str):
        self._filename = (
            filename.replace(".tiff", "").replace(".tif", "")
            if filename.endswith(".tiff") or filename.endswith(".tif")
            else f"{filename}"
        )
        self.log.info(f"setting filename to: {filename}")

    def start(self, device: BaseCamera):
        camera = device
        trigger = camera.trigger
        trigger["mode"] = "off"
        camera.trigger = trigger
        # prepare and start camera
        camera.prepare()
        camera.start()
        background_stack = np.zeros(
            (self._frame_count_px, camera.image_height_px, camera.image_width_px),
            dtype=self._data_type,
        )
        for frame in range(self._frame_count_px):
            background_stack[frame] = camera.grab_frame()
            camera.acquisition_state()
        # close writer and camera
        camera.stop()
        # reset the trigger
        trigger["mode"] = "on"
        camera.trigger = trigger
        # average and save the image
        background_image = np.mean(background_stack, axis=0)
        tifffile.imwrite(
            Path(self.path, self._acquisition_name, f"{self.filename}.tiff"), background_image.astype(self._data_type)
        )
