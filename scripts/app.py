import logging
import sys
from datetime import datetime
from logging import FileHandler
from pathlib import Path, WindowsPath

import numpy as np
from PyQt6.QtWidgets import QApplication
from rich.logging import RichHandler
from ruyaml import YAML
from exaspim_control.qtgui.main import InstrumentUI
from view.instrument_view import InstrumentView

from exaspim_control.acquisition import ExASPIMAcquisition
from exaspim_control.instrument import ExASPIM

logger = logging.getLogger(__name__)

yaml = YAML()
yaml.representer.add_representer(np.int64, lambda obj, val: obj.represent_int(int(val)))
yaml.representer.add_representer(np.int32, lambda obj, val: obj.represent_int(int(val)))
yaml.representer.add_representer(np.str_, lambda obj, val: obj.represent_str(str(val)))
yaml.representer.add_representer(np.float64, lambda obj, val: obj.represent_float(float(val)))
yaml.representer.add_representer(Path, lambda obj, val: obj.represent_str(str(val)))
yaml.representer.add_representer(WindowsPath, lambda obj, val: obj.represent_str(str(val)))


class ExASPIMApplication:
    """Application coordinator for ExASPIM control software."""

    def __init__(self, instrument_dir: Path, log_level: str = "INFO"):
        self.instrument_dir = instrument_dir
        self.log_level = log_level

        # Load configuration files
        self.acquisition_yaml = instrument_dir / "acquisition.yaml"
        self.instrument_yaml = instrument_dir / "instrument.yaml"
        self.gui_yaml = instrument_dir / "gui_config.yaml"

        self._validate_config_files()

        # Setup logging
        self.log_dir = instrument_dir / "logs"
        self.log_filename = self._setup_logging()

        # Setup YAML handler
        self.yaml = yaml

        # Create models (no view dependencies)
        self.instrument = ExASPIM(config_path=str(self.instrument_yaml), yaml_handler=self.yaml)

        self.acquisition = ExASPIMAcquisition(
            instrument=self.instrument,
            config_filename=str(self.acquisition_yaml),
            yaml_handler=self.yaml,
            log_level=log_level,
        )

        # View will be created in run() after QApplication is instantiated
        self.instrument_view = None

    def _validate_config_files(self) -> None:
        """
        Ensure all required config files exist.

        :raises FileNotFoundError: If any required config file is missing
        """
        missing = [
            config_file.name
            for config_file in [self.acquisition_yaml, self.instrument_yaml, self.gui_yaml]
            if not config_file.exists()
        ]

        if missing:
            msg = f"Missing configuration files in {self.instrument_dir}: {', '.join(missing)}"
            raise FileNotFoundError(msg)

    def _setup_logging(self) -> Path:
        """
        Setup file and console logging.

        :return: Path to log file
        """
        logger = logging.getLogger()
        logging.getLogger().handlers.clear()
        logger.setLevel(logging.DEBUG)

        self.log_dir.mkdir(exist_ok=True)
        log_filename = self.log_dir / f"output_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"

        # File handler
        fmt = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
        datefmt = "%Y-%m-%d,%H:%M:%S"
        log_formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

        file_handler = FileHandler(log_filename, "w")
        file_handler.setLevel("INFO")
        file_handler.setFormatter(log_formatter)

        # Rich console handler
        rich_handler = RichHandler(
            rich_tracebacks=True,
            markup=True,
            show_time=True,
            show_level=True,
            show_path=True,
        )
        rich_handler.setLevel("INFO")

        logger.addHandler(file_handler)
        logger.addHandler(rich_handler)

        logger.info(f"Starting ExASPIM Control for instrument: {self.instrument_dir.name}")
        logger.info(f"Configuration files loaded from: {self.instrument_dir}")

        return log_filename

    def _cleanup(self) -> None:
        """
        Final cleanup before application exits.

        Closes hardware connections and releases resources.
        """
        logger.info("Application shutting down - cleaning up resources")

        # Set closing flag in instrument_view (which manages all property workers)
        if self.instrument_view:
            self.instrument_view._is_closing = True

        # Close hardware connections
        try:
            if hasattr(self.instrument, "close"):
                self.instrument.close()
        except Exception as e:
            logger.exception(f"Error closing instrument: {e}")

        try:
            if hasattr(self.acquisition, "close"):
                self.acquisition.close()
        except Exception as e:
            logger.exception(f"Error closing acquisition: {e}")

    def run(self, argv=None) -> int:
        """
        Create QApplication, initialize views, and start the event loop.

        :param argv: Command line arguments (defaults to sys.argv)
        :return: Application exit code
        """
        if argv is None:
            argv = sys.argv

        # Create QApplication first
        app = QApplication(argv)

        # Connect cleanup before creating views
        app.aboutToQuit.connect(self._cleanup)

        # Create instrument view - it creates acquisition_view internally
        self.instrument_view = InstrumentView(
            acquisition=self.acquisition,
            gui_config_path=self.gui_yaml,
            log_filename=str(self.log_filename),
            viewer_title="ExA-SPIM control",
        )

        # Start event loop
        return app.exec()


class InstrumentApp:
    """Application coordinator using new InstrumentUI interface."""

    def __init__(self, instrument_dir: Path, log_level: str = "INFO"):
        self.instrument_dir = instrument_dir
        self.log_level = log_level

        # Load configuration files
        self.acquisition_yaml = instrument_dir / "acquisition.yaml"
        self.instrument_yaml = instrument_dir / "instrument.yaml"
        self.gui_yaml = instrument_dir / "gui_config.yaml"

        self._validate_config_files()

        # Setup logging
        self.log_dir = instrument_dir / "logs"
        self.log_filename = self._setup_logging()

        # Setup YAML handler
        self.yaml = yaml

        # Create models (no view dependencies)
        self.instrument = ExASPIM(config_path=str(self.instrument_yaml), yaml_handler=self.yaml)

        self.acquisition = ExASPIMAcquisition(
            instrument=self.instrument,
            config_filename=str(self.acquisition_yaml),
            yaml_handler=self.yaml,
            log_level=log_level,
        )

        # View will be created in run() after QApplication is instantiated
        self.instrument_ui = None

    def _validate_config_files(self) -> None:
        """
        Ensure all required config files exist.

        :raises FileNotFoundError: If any required config file is missing
        """
        missing = [
            config_file.name
            for config_file in [self.acquisition_yaml, self.instrument_yaml, self.gui_yaml]
            if not config_file.exists()
        ]

        if missing:
            msg = f"Missing configuration files in {self.instrument_dir}: {', '.join(missing)}"
            raise FileNotFoundError(msg)

    def _setup_logging(self) -> Path:
        """
        Setup file and console logging.

        :return: Path to log file
        """
        logger = logging.getLogger()
        logging.getLogger().handlers.clear()
        logger.setLevel(logging.DEBUG)

        self.log_dir.mkdir(exist_ok=True)
        log_filename = self.log_dir / f"output_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"

        # File handler
        fmt = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
        datefmt = "%Y-%m-%d,%H:%M:%S"
        log_formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

        file_handler = FileHandler(log_filename, "w")
        file_handler.setLevel("INFO")
        file_handler.setFormatter(log_formatter)

        # Rich console handler
        rich_handler = RichHandler(
            rich_tracebacks=True,
            markup=True,
            show_time=True,
            show_level=True,
            show_path=True,
        )
        rich_handler.setLevel("INFO")

        logger.addHandler(file_handler)
        logger.addHandler(rich_handler)

        logger.info(f"Starting ExASPIM Control (InstrumentUI mode) for instrument: {self.instrument_dir.name}")
        logger.info(f"Configuration files loaded from: {self.instrument_dir}")

        return log_filename

    def _cleanup(self) -> None:
        """
        Final cleanup before application exits.

        Closes hardware connections and releases resources.
        """
        logger.info("Application shutting down - cleaning up resources")

        # Set closing flag in instrument_ui (which manages all property workers)
        if self.instrument_ui:
            self.instrument_ui._is_closing = True

        # Close hardware connections
        try:
            if hasattr(self.instrument, "close"):
                self.instrument.close()
        except Exception as e:
            logger.exception(f"Error closing instrument: {e}")

        try:
            if hasattr(self.acquisition, "close"):
                self.acquisition.close()
        except Exception as e:
            logger.exception(f"Error closing acquisition: {e}")

    def run(self, argv=None) -> int:
        """
        Create QApplication, initialize views, and start the event loop.

        :param argv: Command line arguments (defaults to sys.argv)
        :return: Application exit code
        """
        if argv is None:
            argv = sys.argv

        # Create QApplication first
        app = QApplication(argv)

        # Connect cleanup before creating views
        app.aboutToQuit.connect(self._cleanup)

        # Create instrument UI - standalone Qt window
        self.instrument_ui = InstrumentUI(
            acquisition=self.acquisition,
            gui_config_path=self.gui_yaml,
            log_filename=str(self.log_filename),
            window_title="ExA-SPIM Control",
        )

        # Show the main window
        self.instrument_ui.show()

        # Start event loop
        return app.exec()
