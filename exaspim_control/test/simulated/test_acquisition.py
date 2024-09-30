import sys
from logging import FileHandler
from pathlib import Path, WindowsPath
import logging
import numpy as np
from ruamel.yaml import YAML
from exaspim_control.exa_spim_instrument import ExASPIM
from exaspim_control.exa_spim_acquisition import ExASPIMAcquisition

if __name__ == '__main__':

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
    file_handler = FileHandler('C:\\Users\\adam.glaser\\Desktop\\output.log', 'w')
    file_handler.setLevel('INFO')
    file_handler.setFormatter(log_formatter)
    log_handler = logging.StreamHandler(sys.stdout)
    log_handler.setLevel('INFO')
    log_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)
    logger.addHandler(log_handler)

    # create yaml handler
    yaml = YAML()
    yaml.representer.add_representer(np.int32, lambda obj, val: obj.represent_int(int(val)))
    yaml.representer.add_representer(np.str_, lambda obj, val: obj.represent_str(str(val)))
    yaml.representer.add_representer(np.float64, lambda obj, val: obj.represent_float(float(val)))
    yaml.representer.add_representer(Path, lambda obj, val: obj.represent_str(str(val)))
    yaml.representer.add_representer(WindowsPath, lambda obj, val: obj.represent_str(str(val)))

    # instrument
    instrument = ExASPIM('./test/simulated/instrument.yaml',
                         yaml_handler=yaml,
                         log_level='INFO')

    # acquisition
    acquisition = ExASPIMAcquisition(instrument=instrument,
                                     config_filename='./test/simulated/acquisition.yaml',
                                     yaml_handler=yaml,
                                     log_level='INFO')
    acquisition.run()

    log_handler.close()
    logger.removeHandler(log_handler)
