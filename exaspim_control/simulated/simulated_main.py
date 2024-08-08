from qtpy.QtWidgets import QApplication
import sys
from exaspim_control.exa_spim_view import ExASPIMInstrumentView
from exaspim_control.exa_spim_view import ExASPIMAcquisitionView
from exaspim_control.exa_spim_instrument import ExASPIM
from exaspim_control.exa_spim_acquisition import ExASPIMAcquisition
from pathlib import Path, WindowsPath
import os
import numpy as np
from ruamel.yaml import YAML

RESOURCES_DIR = (Path(os.path.dirname(os.path.realpath(__file__))))
ACQUISITION_YAML = RESOURCES_DIR / 'acquisition.yaml'
INSTRUMENT_YAML = RESOURCES_DIR / 'instrument.yaml'
GUI_YAML = RESOURCES_DIR / 'gui_config.yaml'

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # create yaml handeler
    yaml = YAML()
    yaml.representer.add_representer(np.int32, lambda obj, val: obj.represent_int(int(val)))
    yaml.representer.add_representer(np.str_, lambda obj, val: obj.represent_str(str(val)))
    yaml.representer.add_representer(np.float64, lambda obj, val: obj.represent_float(float(val)))
    yaml.representer.add_representer(Path, lambda obj, val: obj.represent_str(str(val)))
    yaml.representer.add_representer(WindowsPath, lambda obj, val: obj.represent_str(str(val)))

    # instrument
    instrument = ExASPIM(config_filename=INSTRUMENT_YAML,
                         yaml_handler=yaml,
                         log_level='INFO')
    # acquisition
    acquisition = ExASPIMAcquisition(instrument=instrument,
                                     config_filename=ACQUISITION_YAML,
                                     yaml_handler=yaml, 
                                     log_level='INFO')

    instrument_view = ExASPIMInstrumentView(instrument, GUI_YAML)
    acquisition_view = ExASPIMAcquisitionView(acquisition, instrument_view)
    sys.exit(app.exec_())