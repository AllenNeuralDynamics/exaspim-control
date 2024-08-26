from datetime import datetime
from pathlib import Path

import numpy as np
import skimage.measure
from qtpy.QtCore import Signal
from qtpy.QtWidgets import QApplication

from view.acquisition_view import AcquisitionView
from view.instrument_view import InstrumentView
from voxel.processes.downsample.gpu.gputools.rank_downsample_3d import \
    GPUToolsDownSample3D


class ExASPIMInstrumentView(InstrumentView):
    """View for ExASPIM Instrument"""

    def __init__(self, instrument, config_path: Path, log_level="INFO"):

        super().__init__(instrument, config_path, log_level)
        QApplication.instance().aboutToQuit.connect(self.update_config_on_quit)
        self.viewer.scale_bar.visible = True
        self.viewer.scale_bar.unit = "um"
        self.config_save_to = self.instrument.config_path

    def update_layer(self, args, snapshot: bool = False):
        """Multiscale image from exaspim and rotate images for volume widget
        :param args: tuple containing image and camera name
        :param snapshot: if image taken is a snapshot or not"""

        (image, camera_name) = args
        if image is not None:
            layers = self.viewer.layers
            multiscale = [image]
            downsampler = GPUToolsDownSample3D(binning=2, rank=-2, data_type="uint16")
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
                    contrast_limits=(35, 70),
                    scale=(0.75, 0.75),
                )
                layer.mouse_drag_callbacks.append(self.save_image)
                if snapshot:  # emit signal if snapshot
                    self.snapshotTaken.emit(
                        np.rot90(multiscale[-3], k=3), layer.contrast_limits
                    )
                    layer.events.contrast_limits.connect(
                        lambda event: self.contrastChanged.emit(
                            np.rot90(layer.data[-3], k=3), layer.contrast_limits
                        )
                    )


class ExASPIMAcquisitionView(AcquisitionView):
    """View for ExASPIM Acquisition"""

    acquisitionEnded = Signal()
    acquisitionStarted = Signal((datetime))

    def update_acquisition_layer(self, args):
        """Update viewer with latest frame taken during acquisition
        :param args: tuple containing image and camera name
        """

        (image, camera_name) = args
        if image is not None:
            downsampled = skimage.measure.block_reduce(image, (4, 4), np.mean)
            super().update_acquisition_layer((downsampled, camera_name))

    def start_acquisition(self):
        """Overwrite to emit acquisitionStarted signal"""

        super().start_acquisition()
        self.acquisitionStarted.emit(datetime.now())

    def acquisition_ended(self):
        """Overwrite to emit acquisitionEnded signal"""
        super().acquisition_ended()
        self.acquisitionEnded.emit()
