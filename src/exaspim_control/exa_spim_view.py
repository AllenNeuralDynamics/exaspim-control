import time
from datetime import datetime
from pathlib import Path

import numpy as np
from napari.utils.theme import get_theme
from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout

from view.acquisition_view import AcquisitionView
from view.instrument_view import InstrumentView
from view.widgets.base_device_widget import create_widget, disable_button
from voxel.processes.downsample.gpu.gputools.rank_downsample_2d import GPUToolsRankDownSample2D


class ExASPIMInstrumentView(InstrumentView):
    """Class for handling ExASPIM instrument view."""

    def __init__(self, instrument: object, config_path: Path, log_level: str = "INFO"):
        """
        Initialize the ExASPIMInstrumentView object.

        :param instrument: Instrument object
        :type instrument: object
        :param config_path: Configuration path
        :type config_path: Path
        :param log_level: Logging level, defaults to "INFO"
        :type log_level: str, optional
        """
        self.flip_mount_widgets = {}
        super().__init__(instrument, config_path, log_level)
        # other setup taken care of in base instrumentview class
        self.setup_flip_mount_widgets()

        # viewer constants for ExA-SPIM
        self.intensity_min = 30
        self.intensity_max = 400
        self.camera_rotation = -90
        self.resolution_levels = 6
        self.alignment_roi_size = 512
        self.viewer.scale_bar.visible = True
        self.viewer.scale_bar.unit = "um"
        self.viewer.scale_bar.position = "bottom_left"
        self.viewer.text_overlay.visible = True
        self.viewer.window._qt_viewer.canvas._scene_canvas.measure_fps(callback=self.update_fps)

    def setup_camera_widgets(self) -> None:
        """
        Set up camera widgets.
        """
        for camera_name, camera_widget in self.camera_widgets.items():

            # Add functionality to snapshot button
            snapshot_button = getattr(camera_widget, "snapshot_button", QPushButton())
            snapshot_button.pressed.connect(
                lambda button=snapshot_button: disable_button(button)
            )  # disable to avoid spamming
            snapshot_button.pressed.connect(lambda camera=camera_name: self.setup_live(camera, 1))

            # Add functionality to live button
            live_button = getattr(camera_widget, "live_button", QPushButton())
            live_button.pressed.connect(lambda button=live_button: disable_button(button))  # disable to avoid spamming
            live_button.pressed.connect(lambda camera=camera_name: self.setup_live(camera))
            live_button.pressed.connect(lambda camera=camera_name: self.toggle_live_button(camera))

            # Add functionality to the edges button
            self.alignment_button = getattr(camera_widget, "alignment_button", QPushButton())
            self.alignment_button.setCheckable(True)
            self.alignment_button.released.connect(self.enable_alignment_mode)

            # Add functionality to the crosshairs button
            self.crosshairs_button = getattr(camera_widget, "crosshairs_button", QPushButton())
            self.crosshairs_button.setCheckable(True)
            # self.crosshairs_button.released.connect(lambda camera=camera_name: self.show_crosshairs(camera))

        stacked = self.stack_device_widgets("camera")
        self.viewer.window.add_dock_widget(stacked, area="right", name="Cameras", add_vertical_stretch=False)

    def setup_filter_wheel_widgets(self) -> None:
        """
        Set up filter wheel widgets.
        """
        self.log.info("passing on setting up filter wheel widgets")
        pass

    def setup_stage_widgets(self) -> None:
        """
        Set up stage widgets.
        """
        stage_widgets = []
        for name, widget in {
            **self.tiling_stage_widgets,
            **self.scanning_stage_widgets,
            **self.focusing_stage_widgets,
        }.items():
            label = QLabel()
            frame = QFrame()
            layout = QVBoxLayout()
            layout.addWidget(create_widget("H", label, widget))
            frame.setLayout(layout)
            border_color = get_theme(self.viewer.theme, as_dict=False).foreground
            frame.setStyleSheet(f".QFrame {{ border:1px solid {border_color}; }} ")
            stage_widgets.append(frame)

        stage_axes_widget = create_widget("V", *stage_widgets)
        stage_axes_widget.setContentsMargins(0, 0, 0, 0)
        stage_axes_widget.layout().setSpacing(0)

        stage_scroll = QScrollArea()
        stage_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        stage_scroll.setWidget(stage_axes_widget)
        self.viewer.window.add_dock_widget(stage_axes_widget, area="left", name="Stages")

    def setup_flip_mount_widgets(self) -> None:
        """
        Set up flip mount widgets.
        """
        stacked = self.stack_device_widgets("flip_mount")
        self.viewer.window.add_dock_widget(stacked, area="right", name="Flip Mounts")

    def update_fps(self, fps: float) -> None:
        """
        Update the frames per second (FPS) display.

        :param fps: Frames per second
        :type fps: float
        """
        self.viewer.text_overlay.text = f"{fps:1.1f} fps"

    def update_layer(self, args: tuple, snapshot: bool = False) -> None:
        """
        Update the image layer in the viewer.

        :param args: Tuple containing image and camera name
        :type args: tuple
        :param snapshot: Whether the image is a snapshot, defaults to False
        :type snapshot: bool, optional
        """
        (image, camera_name) = args

        # calculate centroid of image
        y_center_um = image.shape[0] // 2 * self.instrument.cameras[camera_name].sampling_um_px
        x_center_um = image.shape[1] // 2 * self.instrument.cameras[camera_name].sampling_um_px

        if image is not None:
            _ = self.viewer.layers
            # add crosshairs to image
            if self.crosshairs_button.isChecked():
                image[image.shape[0] // 2 - 1: image.shape[0] // 2 + 1, :] = 1 << 16 - 1
                image[:, image.shape[1] // 2 - 1: image.shape[1] // 2 + 1] = 1 << 16 - 1
            multiscale = [image]
            downsampler = GPUToolsRankDownSample2D(binning=2, rank=-2, data_type="uint16")
            for binning in range(1, self.resolution_levels):
                downsampled_frame = downsampler.run(multiscale[-1])
                # add crosshairs to image
                if self.crosshairs_button.isChecked():
                    downsampled_frame[downsampled_frame.shape[0] // 2 - 1: downsampled_frame.shape[0] // 2 + 1, :] = (
                        1 << 16 - 1
                    )
                    downsampled_frame[:, downsampled_frame.shape[1] // 2 - 1: downsampled_frame.shape[1] // 2 + 1] = (
                        1 << 16 - 1
                    )
                multiscale.append(downsampled_frame)
            layer_name = (
                f"{camera_name} {self.livestream_channel}"
                if not snapshot
                else f"{camera_name} {self.livestream_channel} snapshot"
            )
            if layer_name in self.viewer.layers and not snapshot:
                layer = self.viewer.layers[layer_name]
                layer.data = multiscale
                layer.scale = (
                    self.instrument.cameras[camera_name].sampling_um_px,
                    self.instrument.cameras[camera_name].sampling_um_px,
                )
                layer.translate = (-x_center_um, y_center_um)
            else:
                # Add image to a new layer if layer doesn't exist yet or image is snapshot
                layer = self.viewer.add_image(
                    multiscale,
                    name=layer_name,
                    contrast_limits=(self.intensity_min, self.intensity_max),
                    scale=(
                        self.instrument.cameras[camera_name].sampling_um_px,
                        self.instrument.cameras[camera_name].sampling_um_px,
                    ),
                    translate=(-x_center_um, y_center_um),
                    rotate=self.camera_rotation,
                )
                # TODO CHECK is multiscale already rotated 90? Or is the openGL window mixing up rows/columns?
                layer.mouse_drag_callbacks.append(self.save_image)
                if snapshot:  # emit signal if snapshot
                    self.snapshotTaken.emit(np.rot90(multiscale[-3], k=2), layer.contrast_limits)
                    layer.events.contrast_limits.connect(
                        lambda event: self.contrastChanged.emit(np.rot90(layer.data[-3], k=2), layer.contrast_limits)
                    )

    def dissect_image(self, args: tuple) -> None:
        """
        Dissect the image and add to the viewer.

        :param args: Tuple containing image and camera name
        :type args: tuple
        """
        (image, camera_name) = args

        if image is not None:
            # Dissect image and add to viewer
            alignment_roi = self.alignment_roi_size
            combined_roi = np.zeros((alignment_roi * 3, alignment_roi * 3))
            # top left corner
            top_left = image[0:alignment_roi, 0:alignment_roi]
            combined_roi[0:alignment_roi, 0:alignment_roi] = top_left
            # top right corner
            top_right = image[0:alignment_roi, -alignment_roi:]
            combined_roi[0:alignment_roi, alignment_roi * 2: alignment_roi * 3] = top_right
            # bottom left corner
            bottom_left = image[-alignment_roi:, 0:alignment_roi]
            combined_roi[alignment_roi * 2: alignment_roi * 3, 0:alignment_roi] = bottom_left
            # bottom right corner
            bottom_right = image[-alignment_roi:, -alignment_roi:]
            combined_roi[alignment_roi * 2: alignment_roi * 3, alignment_roi * 2: alignment_roi * 3] = bottom_right
            # center left
            center_left = image[
                round((image.shape[0] / 2) - alignment_roi / 2): round((image.shape[0] / 2) + alignment_roi / 2),
                0:alignment_roi,
            ]
            combined_roi[alignment_roi: alignment_roi * 2, 0:alignment_roi] = center_left
            # center right
            center_right = image[
                round((image.shape[0] / 2) - alignment_roi / 2): round((image.shape[0] / 2) + alignment_roi / 2),
                -alignment_roi:,
            ]
            combined_roi[alignment_roi: alignment_roi * 2, alignment_roi * 2: alignment_roi * 3] = center_right
            # center top
            center_top = image[
                0:alignment_roi,
                round((image.shape[1] / 2) - alignment_roi / 2): round((image.shape[1] / 2) + alignment_roi / 2),
            ]
            combined_roi[0:alignment_roi, alignment_roi: alignment_roi * 2] = center_top
            # center bottom
            center_bottom = image[
                -alignment_roi:,
                round((image.shape[1] / 2) - alignment_roi / 2): round((image.shape[1] / 2) + alignment_roi / 2),
            ]
            combined_roi[alignment_roi * 2: alignment_roi * 3, alignment_roi: alignment_roi * 2] = center_bottom
            # center roi
            center = image[
                round((image.shape[0] / 2) - alignment_roi / 2): round((image.shape[0] / 2) + alignment_roi / 2),
                round((image.shape[1] / 2) - alignment_roi / 2): round((image.shape[1] / 2) + alignment_roi / 2),
            ]
            combined_roi[alignment_roi: alignment_roi * 2, alignment_roi: alignment_roi * 2] = center

            # add crosshairs to image
            combined_roi[alignment_roi - 2: alignment_roi + 2, :] = 1 << 16 - 1
            combined_roi[alignment_roi * 2 - 2: alignment_roi * 2 + 2, :] = 1 << 16 - 1
            combined_roi[:, alignment_roi - 2: alignment_roi + 2] = 1 << 16 - 1
            combined_roi[:, alignment_roi * 2 - 2: alignment_roi * 2 + 2] = 1 << 16 - 1

            layer_name = f"{camera_name} {self.livestream_channel} Alignment"
            if layer_name in self.viewer.layers:
                layer = self.viewer.layers[layer_name]
                layer.data = combined_roi
            else:
                layer = self.viewer.add_image(
                    combined_roi,
                    name=layer_name,
                    contrast_limits=(self.intensity_min, self.intensity_max),
                    scale=(self.pixel_size_y_um, self.pixel_size_x_um),
                    rotate=self.camera_rotation,
                )

    def enable_alignment_mode(self) -> None:
        """
        Enable alignment mode.
        """
        if not self.grab_frames_worker.is_running:
            return

        self.viewer.layers.clear()

        if self.alignment_button.isChecked():
            self.grab_frames_worker.yielded.disconnect(self.update_layer)
            self.grab_frames_worker.yielded.connect(self.dissect_image)
        else:
            self.grab_frames_worker.yielded.disconnect(self.dissect_image)
            self.grab_frames_worker.yielded.connect(self.update_layer)

    def dismantle_live(self, camera_name: str) -> None:
        """
        Dismantle live view for the specified camera.

        :param camera_name: Camera name
        :type camera_name: str
        """
        self.instrument.cameras[camera_name].abort()
        for daq_name, daq in self.instrument.daqs.items():
            # wait for daq tasks to finish - prevents devices from stopping in
            # unsafe state, i.e. lasers still on
            daq.co_task.stop()
            # sleep to allow last ao to play with 10% buffer
            time.sleep(1.0 / daq.co_frequency_hz * 1.1)
            # stop the ao task
            daq.ao_task.stop()


class ExASPIMAcquisitionView(AcquisitionView):
    """Class for handling ExASPIM acquisition view."""

    acquisitionEnded = Signal()
    acquisitionStarted = Signal((datetime,))

    def __init__(self, acquisition: object, instrument_view: ExASPIMInstrumentView):
        """
        Initialize the ExASPIMAcquisitionView object.

        :param acquisition: Acquisition object
        :type acquisition: object
        :param instrument_view: Instrument view object
        :type instrument_view: ExASPIMInstrumentView
        """
        super().__init__(acquisition=acquisition, instrument_view=instrument_view)
        # acquisition constants for ExA-SPIM
        self.acquisition_binning = 4

    def update_acquisition_layer(self, image: np.ndarray, camera_name: str) -> None:
        """
        Update the acquisition image layer in the viewer.

        :param image: Image array
        :type image: np.ndarray
        :param camera_name: Camera name
        :type camera_name: str
        """
        if image is not None:
            downsampler = GPUToolsRankDownSample2D(binning=self.acquisition_binning, rank=-2, data_type="uint16")
            acquisition_image = downsampler.run(image)

            # calculate centroid of image
            y_center_um = image.shape[0] // 2 * self.instrument.cameras[camera_name].sampling_um_px
            x_center_um = image.shape[1] // 2 * self.instrument.cameras[camera_name].sampling_um_px

            layer_name = f"{camera_name} acquisition"
            if layer_name in self.instrument_view.viewer.layers:
                layer = self.instrument_view.viewer.layers[layer_name]
                layer.data = acquisition_image
                layer.scale = (
                    self.acquisition_binning * self.instrument.cameras[camera_name].sampling_um_px,
                    self.acquisition_binning * self.instrument.cameras[camera_name].sampling_um_px,
                )
                layer.translate = (-x_center_um, y_center_um)
            else:
                # Add image to a new layer if layer doesn't exist yet or image is snapshot
                layer = self.instrument_view.viewer.add_image(
                    acquisition_image,
                    name=layer_name,
                    contrast_limits=(self.instrument_view.intensity_min, self.instrument_view.intensity_max),
                    scale=(
                        self.acquisition_binning * self.instrument.cameras[camera_name].sampling_um_px,
                        self.acquisition_binning * self.instrument.cameras[camera_name].sampling_um_px,
                    ),
                    translate=(-x_center_um, y_center_um),
                    rotate=self.instrument_view.camera_rotation,
                )

    def start_acquisition(self) -> None:
        """
        Start the acquisition process.
        """
        super().start_acquisition()
        self.acquisitionStarted.emit(datetime.now())

    def acquisition_ended(self) -> None:
        """
        Handle the end of the acquisition process.
        """
        super().acquisition_ended()
        self.acquisitionEnded.emit()
