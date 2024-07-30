from qtpy.QtWidgets import QApplication
import sys
from exaspim_control.exa_spim_view import ExASPIMInstrumentView, ExASPIMAcquisitionView
from view.acquisition_view import AcquisitionView
from exaspim_control.exa_spim_instrument import ExASPIM
from exaspim_control.exa_spim_acquisition import ExASPIMAcquisition
from pathlib import Path
import os


RESOURCES_DIR = (Path(os.path.dirname(os.path.realpath(__file__))))
ACQUISITION_YAML = RESOURCES_DIR / 'acquisition.yaml'
INSTRUMENT_YAML = RESOURCES_DIR / 'instrument.yaml'
GUI_YAML = RESOURCES_DIR / 'gui_config.yaml'

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # instrument
    instrument = ExASPIM(INSTRUMENT_YAML, log_level= 'INFO')
    # acquisition
    acquisition = ExASPIMAcquisition(instrument, ACQUISITION_YAML, log_level= 'INFO')
    #acquisition.run()
    instrument_view = ExASPIMInstrumentView(instrument, GUI_YAML, 'INFO')
    acquisition_view = ExASPIMAcquisitionView(acquisition, instrument_view)
    sys.exit(app.exec_())