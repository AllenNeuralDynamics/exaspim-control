from datetime import datetime
from pathlib import Path
from qtpy.QtCore import Signal
from view.acquisition_view import AcquisitionView
from view.instrument_view import InstrumentView
from voxel.processes.downsample.gpu.gputools.downsample_2d import GPUToolsDownSample2D
from view.widgets.base_device_widget import disable_button
from qtpy.QtWidgets import QPushButton
import numpy as np
import skimage.measure


class ExASPIMInstrumentView(InstrumentView):
    """View for ExASPIM Instrument"""

    def __init__(self, instrument, config_path: Path, log_level="INFO"):

        super().__init__(instrument, config_path, log_level)
        self.viewer.scale_bar.visible = True
        self.viewer.scale_bar.unit = "um"

    def update_layer(self, args, snapshot: bool = False) -> None:
        """Multiscale image from exaspim and rotate images for volume widget
        :param args: tuple containing image and camera name
        :param snapshot: if image taken is a snapshot or not"""

        (image, camera_name) = args

        if image is not None:
            _ = self.viewer.layers
            multiscale = [image]
            # downsampler = GPUToolsRankDownSample2D(binning=2, rank=-2, data_type="uint16")
            downsampler = GPUToolsDownSample2D(binning=2)
            for binning in range(1, 6):  # TODO: variable or get from somewhere?
                downsampled_frame = downsampler.run(multiscale[-1])
                multiscale.append(downsampled_frame)
            layer_name = (
                f"{camera_name} {self.livestream_channel}"
                if not snapshot
                else f"{camera_name} {self.livestream_channel} snapshot"
            )
            if layer_name in self.viewer.layers and not snapshot:
                layer = self.viewer.layers[layer_name]
                layer.data = multiscale
            else:
                # Add image to a new layer if layer doesn't exist yet or image is snapshot
                layer = self.viewer.add_image(
                    multiscale,
                    name=layer_name,
                    contrast_limits=(30, 400),
                    scale=(0.75, 0.75),
                    rotate=-90,
                )
                # TODO CHECK is multiscale already rotated 90? Or is the openGL window mixing up rows/columns?
                layer.mouse_drag_callbacks.append(self.save_image)
                if snapshot:  # emit signal if snapshot
                    self.snapshotTaken.emit(np.rot90(multiscale[-3], k=2), layer.contrast_limits)
                    layer.events.contrast_limits.connect(
                        lambda event: self.contrastChanged.emit(np.rot90(layer.data[-3], k=2), layer.contrast_limits)
                    )

    def dissect_image(self, args) -> None:
        """
        Process images for alignment mode
        """

        (image, camera_name) = args

        if image is not None:
            # Dissect image and add to viewer

            chunk = 1024
            border = 16

            lower_col = round((image.shape[1] / 2) - chunk)
            upper_col = round((image.shape[1] / 2) + chunk)
            lower_row = round((image.shape[0] / 2) - chunk)
            upper_row = round((image.shape[0] / 2) + chunk)

            length = chunk * 2
            width = chunk * 4

            container = np.zeros((length, width))
            container[border : chunk - border, chunk + border : chunk + length - border] = image[
                border : chunk - border, lower_col + border : upper_col - border
            ]  # Top
            container[-chunk + border : -border, chunk + border : chunk + length - border] = image[
                -chunk + border : -border, lower_col + border : upper_col - border
            ]  # bottom
            container[border:-border, border : chunk - border] = image[
                lower_row + border : upper_row - border, border : chunk - border
            ]  # left
            container[border:-border, -chunk + border : -border] = image[
                lower_row + border : upper_row - border, -chunk + border : -border
            ]  # right

            layer_name = f"{camera_name} {self.livestream_channel} Alignment"
            if layer_name in self.viewer.layers:
                layer = self.viewer.layers[layer_name]
                layer.data = container
            else:
                # Add image to a new layer if layer doesn't exist yet or image is snapshot
                layer = self.viewer.add_image(
                    container,
                    name=layer_name,
                    contrast_limits=(30, 400),
                    scale=(0.75, 0.75),
                    rotate=-90,
                )

    def enable_alignment_mode(self) -> None:
        """
        Toggle view middle edges when pressed
        :param camera_name: name of camera to set up
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

    def setup_camera_widgets(self):
        """
        Setup live view and snapshot button
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
            self.alignment_button.released.connect(lambda camera=camera_name: self.enable_alignment_mode(camera))

        stacked = self.stack_device_widgets("camera")
        self.viewer.window.add_dock_widget(stacked, area="right", name="Cameras", add_vertical_stretch=False)


class ExASPIMAcquisitionView(AcquisitionView):
    """View for ExASPIM Acquisition"""

    acquisitionEnded = Signal()
    acquisitionStarted = Signal((datetime))

    def update_acquisition_layer(self, image: np.ndarray, camera_name: str):
        """Update viewer with latest frame taken during acquisition
        :param image: numpy array to add to viewer
        :param camera_name: name of camera that image came off
        """

        if image is not None:
            # downsampler = GPUToolsRankDownSample2D(binning=4, rank=-2, data_type="uint16")
            # downsampled = downsampler.run(image)
            downsampled = skimage.measure.block_reduce(image, (4, 4), np.mean)
            super().update_acquisition_layer(downsampled, camera_name)

    def start_acquisition(self):
        """Overwrite to emit acquisitionStarted signal"""

        super().start_acquisition()
        self.acquisitionStarted.emit(datetime.now())

    def acquisition_ended(self):
        """Overwrite to emit acquisitionEnded signal"""
        super().acquisition_ended()
        self.acquisitionEnded.emit()
