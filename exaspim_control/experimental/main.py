from qtpy.QtWidgets import QApplication
import sys
from exaspim_control.exa_spim_view import ExASPIMInstrumentView
from exaspim_control.exa_spim_view import ExASPIMAcquisitionView
from exaspim_control.exa_spim_instrument import ExASPIM
from exaspim_control.exa_spim_acquisition import ExASPIMAcquisition
from logging import FileHandler
from pathlib import Path
import logging
import os


RESOURCES_DIR = (Path(os.path.dirname(os.path.realpath(__file__))))
ACQUISITION_YAML = RESOURCES_DIR / 'acquisition.yaml'
INSTRUMENT_YAML = RESOURCES_DIR / 'instrument.yaml'
GUI_YAML = RESOURCES_DIR / 'gui_config.yaml'

if __name__ == "__main__":

    # Setup logging.
    # Create log handlers to dispatch:
    # - User-specified level and above to print to console if specified.
    logger = logging.getLogger()  # get the root logger.
    # Remove any handlers already attached to the root logger.
    logging.getLogger().handlers.clear()
    # logger level must be set to the lowest level of any handler.
    logger.setLevel(logging.DEBUG)
    fmt = '%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s'
    datefmt = '%Y-%m-%d,%H:%M:%S'
    log_formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)
    file_handler = FileHandler('output.log', 'w')
    file_handler.setLevel('INFO')
    file_handler.setFormatter(log_formatter)
    log_handler = logging.StreamHandler(sys.stdout)
    log_handler.setLevel('INFO')
    log_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)
    logger.addHandler(log_handler)

    app = QApplication(sys.argv)

    # instrument
    instrument = ExASPIM(INSTRUMENT_YAML, log_level='INFO')
    # acquisition
    acquisition = ExASPIMAcquisition(instrument, ACQUISITION_YAML, log_level='INFO')
    instrument_view = ExASPIMInstrumentView(instrument, GUI_YAML, log_level='INFO')
    acquisition_view = ExASPIMAcquisitionView(acquisition, instrument_view)

    log_handler.close()
    logger.removeHandler(log_handler)

    sys.exit(app.exec_())
