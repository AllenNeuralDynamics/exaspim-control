from qtpy.QtWidgets import QApplication, QMessageBox, QPushButton, QFileDialog
from view.instrument_view import InstrumentView
from view.acquisition_view import AcquisitionView
from pathlib import Path
import yaml
from voxel.processes.gpu.gputools.downsample_2d import DownSample2D
import inflection
import numpy as np
import skimage.measure

class ExASPIMInstrumentView(InstrumentView):
    """View for ExASPIM Instrument"""

    def __init__(self, instrument, config_path: Path, log_level='INFO'):

        super().__init__(instrument, config_path, log_level)
        QApplication.instance().aboutToQuit.connect(self.update_config_on_quit)
        self.viewer.scale_bar.visible = True
        self.viewer.scale_bar.unit = 'um'
        self.config_save_to = self.instrument.config_path

    def update_layer(self, args, snapshot: bool =False):
        """Multiscale image from exaspim and rotate images for volume widget
        :param args: tuple containing image and camera name
        :param snapshot: if image taken is a snapshot or not """

        (image, camera_name) = args
        if image is not None:
            layers = self.viewer.layers
            multiscale = [image]
            downsampler = DownSample2D(binning=2)
            for binning in range(1, 6):  # TODO: variable or get from somewhere?
                downsampled_frame = downsampler.run(multiscale[-1])
                multiscale.append(downsampled_frame)
            layer_name = f"{camera_name} {self.livestream_channel}" if not snapshot else \
                f"{camera_name} {self.livestream_channel} snapshot"
            if layer_name in self.viewer.layers and not snapshot:
                layer = self.viewer.layers[layer_name]
                layer.data = multiscale
            else:
                # Add image to a new layer if layer doesn't exist yet or image is snapshot
                layer = self.viewer.add_image(multiscale, name=layer_name,
                                              contrast_limits=(35, 70), scale=(0.75, 0.75))
                layer.mouse_drag_callbacks.append(self.save_image)
                if snapshot:  # emit signal if snapshot
                    self.snapshotTaken.emit(np.rot90(multiscale[-3], k=3), layer.contrast_limits)
                    layer.events.contrast_limits.connect(lambda event: self.contrastChanged.emit(np.rot90(layer.data[-3], k=3),
                                                                                                 layer.contrast_limits))

    def update_config_on_quit(self):
        """Add functionality to close function to save device properties to instrument config"""

        return_value = self.update_config_query()
        if return_value == QMessageBox.Ok:
            for device_name, device_specs in self.instrument.config['instrument']['devices'].items():
                self.update_config(device_name, device_specs)
            with open(self.config_save_to, 'w') as outfile:
                yaml.dump(self.instrument.config, outfile)

    def update_config(self, device_name, device_specs):
        """Update setting in instrument config if already there
        :param device_name: name of device
        :param device_specs: dictionary dictating how device should be set up"""

        device_type = inflection.pluralize(device_specs['type'])
        for key in device_specs.get('settings', {}).keys():
            device_object = getattr(self.instrument, device_type)[device_name]
            device_specs.get('settings')[key] = getattr(device_object, key)
            for subdevice_name, subdevice_specs in device_specs.get('subdevices', {}).items():
                self.update_config(subdevice_name, subdevice_specs)

    def update_config_query(self):
        """Pop up message asking if configuration would like to be saved"""
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Question)
        msgBox.setText(f"Do you want to update the instrument configuration file at {self.config_save_to} "
                       f"to current instrument state?")
        msgBox.setWindowTitle("Updating Configuration")
        msgBox.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        save_elsewhere = QPushButton('Change Directory')
        msgBox.addButton(save_elsewhere, QMessageBox.DestructiveRole)

        save_elsewhere.pressed.connect(lambda: self.select_directory(True, msgBox))

        return msgBox.exec()

    def select_directory(self, pressed, msgBox):
        """Select directory"""

        fname = QFileDialog()
        folder = fname.getSaveFileName(directory=str(self.instrument.config_path))
        if folder[0] != '': # user pressed cancel
            msgBox.setText(f"Do you want to update the instrument configuration file at {folder[0]} "
                           f"to current instrument state?")
            self.config_save_to = folder[0]

class ExASPIMAcquisitionView(AcquisitionView):
    """View for ExASPIM Acquisition"""

    def update_acquisition_layer(self, args):
        """Update viewer with latest frame taken during acquisition
        :param args: tuple containing image and camera name
        """

        (image, camera_name) = args
        if image is not None:
            downsampled = skimage.measure.block_reduce(image, (4,4), np.mean)
            super().update_acquisition_layer((downsampled, camera_name))