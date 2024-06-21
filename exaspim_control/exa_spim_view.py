from qtpy.QtWidgets import QApplication, QMessageBox, QPushButton, QFileDialog
from view.instrument_view import InstrumentView
from pathlib import Path
import os
import yaml
from voxel.processes.gpu.gputools.downsample_2d import DownSample2D
import inflection

RESOURCES_DIR = (Path(os.path.dirname(os.path.realpath(__file__))))
ACQUISITION_YAML = RESOURCES_DIR / 'acquisition.yaml'
INSTRUMENT_YAML = RESOURCES_DIR / 'instrument.yaml'
GUI_YAML = RESOURCES_DIR / 'gui_config.yaml'


class ExASPIMInstrumentView(InstrumentView):
    """View for ExASPIM Instrument"""

    def __init__(self, instrument, config_path: Path, log_level='INFO'):
        super().__init__(instrument, config_path, log_level)
        QApplication.instance().aboutToQuit.connect(self.update_config_on_quit)

        self.config_save_to = self.instrument.config_path

    def update_layer(self, args):
        """Multiscale image from exaspim
        :param args: tuple containing image and camera name"""

        (image, camera_name) = args
        if image is not None:
            multiscale = [image]
            for binning in range(2, 6):  # TODO: variable or get from somewhere?
                downsampled_frame = DownSample2D(binning=binning).run(image)
                multiscale.append(downsampled_frame)
            super().update_layer((multiscale, camera_name))

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