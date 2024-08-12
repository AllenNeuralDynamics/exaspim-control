from qtpy.QtWidgets import QApplication
import sys
from pathlib import Path, WindowsPath
import os
import numpy as np
from ruamel.yaml import YAML
from exaspim_control.metadata_launch import MetadataLaunch

RESOURCES_DIR = (Path(os.path.dirname(os.path.realpath(__file__))))
ACQUISITION_YAML = RESOURCES_DIR / 'acquisition.yaml'
INSTRUMENT_YAML = RESOURCES_DIR / 'instrument.yaml'
GUI_YAML = RESOURCES_DIR / 'gui_config.yaml'

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # create yaml handler
    yaml = YAML()
    yaml.representer.add_representer(np.int32, lambda obj, val: obj.represent_int(int(val)))
    yaml.representer.add_representer(np.str_, lambda obj, val: obj.represent_str(str(val)))
    yaml.representer.add_representer(np.float64, lambda obj, val: obj.represent_float(float(val)))
    yaml.representer.add_representer(Path, lambda obj, val: obj.represent_str(str(val)))
    yaml.representer.add_representer(WindowsPath, lambda obj, val: obj.represent_str(str(val)))

    MetadataLaunch(
        instrument_config_filename=INSTRUMENT_YAML,
        instrument_yaml_handler=yaml,
        log_level='INFO',
        acquisition_config_filename=ACQUISITION_YAML,
        acquisition_yaml_handler=yaml,
        gui_config_filename=GUI_YAML)

    sys.exit(app.exec_())