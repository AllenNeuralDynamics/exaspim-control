"""
ExASPIM Application coordinator for multi-window microscope control.

This module provides the ExASPIMApplication class which manages the lifecycle
of the ExASPIM instrument control software, including:
- Configuration file loading and validation
- Model instantiation (instrument and acquisition)
- View creation and coordination
- Window close event coordination
- Resource cleanup on shutdown
"""

import logging
from datetime import datetime
from logging import FileHandler
from pathlib import Path, WindowsPath

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from rich.logging import RichHandler
from ruyaml import YAML

from exaspim_control.acquisition import ExASPIMAcquisition
from exaspim_control.instrument import ExASPIM
from exaspim_control.metadata_launch import MetadataLaunch
from exaspim_control.view import ExASPIMAcquisitionView, ExASPIMInstrumentView


class ExASPIMApplication(QObject):
    """
    Application coordinator for ExASPIM multi-window setup.

    Manages the complete lifecycle of the ExASPIM application including:
    - Loading configuration files from instrument directory
    - Creating instrument and acquisition models
    - Creating independent view windows without circular references
    - Coordinating window close events for synchronized shutdown
    - Cleaning up hardware resources on exit

    :param instrument_dir: Path to instrument directory containing config files
    :param log_level: Logging level (default: "INFO")
    """

    # Signals for clean shutdown coordination
    shutting_down = pyqtSignal()

    def __init__(self, instrument_dir: Path, log_level: str = "INFO"):
        super().__init__()

        self.instrument_dir = instrument_dir
        self.log_level = log_level
        self._shutting_down = False

        # Load configuration files
        self.acquisition_yaml = instrument_dir / "acquisition.yaml"
        self.instrument_yaml = instrument_dir / "instrument.yaml"
        self.gui_yaml = instrument_dir / "gui_config.yaml"

        self._validate_config_files()

        # Setup logging
        self.log_dir = instrument_dir / "logs"
        self.log_filename = self._setup_logging()

        # Setup YAML handler
        self.yaml = self._setup_yaml_handler()

        # Create models (no view dependencies)
        self.instrument = ExASPIM(
            config_filename=str(self.instrument_yaml), yaml_handler=self.yaml, log_level=log_level
        )

        self.acquisition = ExASPIMAcquisition(
            instrument=self.instrument,
            config_filename=str(self.acquisition_yaml),
            yaml_handler=self.yaml,
            log_level=log_level,
        )

        # Views will be created in run() after QApplication is instantiated
        self.instrument_view = None
        self.acquisition_view = None
        self.metadata_launch = None

    def _initialize_views(self) -> None:
        """
        Initialize Qt views after QApplication has been created.
        This must be called after QApplication is instantiated.
        """
        # Create views (no cross-references)
        self.instrument_view = ExASPIMInstrumentView(
            self.instrument, self.gui_yaml, save_acquisition_config_callback=self.save_acquisition_config_with_backup
        )

        self.acquisition_view = ExASPIMAcquisitionView(
            acquisition=self.acquisition,
            config=self.instrument_view.config,
            save_config_callback=self.save_acquisition_config,
            update_layer_callback=self._update_acquisition_layer,
        )

        # Set up cross-view communication via application
        self._connect_view_interactions()

        # Setup metadata bridge
        self.metadata_launch = MetadataLaunch(
            instrument=self.instrument,
            acquisition=self.acquisition,
            instrument_view=self.instrument_view,
            acquisition_view=self.acquisition_view,
            log_filename=str(self.log_filename),
        )

        # Coordinate window lifecycle
        self._setup_window_coordination()

    def _connect_view_interactions(self) -> None:
        """
        Connect signals between instrument and acquisition views.

        This handles cross-view communication that cannot be done through models alone,
        such as snapshot signals, contrast adjustments, and livestream coordination.
        """
        assert self.instrument_view is not None, "instrument_view must be initialized"
        assert self.acquisition_view is not None, "acquisition_view must be initialized"

        # Connect snapshot and contrast signals from instrument view to acquisition view
        if hasattr(self.instrument_view, "snapshotTaken") and hasattr(self.acquisition_view, "volume_model"):
            self.instrument_view.snapshotTaken.connect(self.acquisition_view.volume_model.add_fov_image)

        if hasattr(self.instrument_view, "contrastChanged") and hasattr(self.acquisition_view, "volume_model"):
            self.instrument_view.contrastChanged.connect(self.acquisition_view.volume_model.adjust_glimage_contrast)

        # Connect acquisition lifecycle signals for coordinated behavior
        if hasattr(self.acquisition_view, "acquisitionStarted"):
            self.acquisition_view.acquisitionStarted.connect(self._on_acquisition_started)

        if hasattr(self.acquisition_view, "acquisitionEnded"):
            self.acquisition_view.acquisitionEnded.connect(self._on_acquisition_ended)

    def _on_acquisition_started(self, start_time) -> None:
        """
        Handle acquisition start - stop livestream and disable instrument view.

        :param start_time: Datetime when acquisition started
        """
        # Stop livestream if running
        if hasattr(self.instrument_view, "grab_frames_worker") and self.instrument_view.grab_frames_worker.is_running:
            logging.info("Stopping livestream for acquisition")
            self.instrument_view.grab_frames_worker.quit()

        # Disable instrument view during acquisition
        if self.instrument_view is not None:
            self.instrument_view.setDisabled(True)
            logging.info("Instrument view disabled during acquisition")

    def _on_acquisition_ended(self) -> None:
        """
        Handle acquisition end - re-enable instrument view.
        """
        # Re-enable instrument view after acquisition
        if self.instrument_view is not None:
            self.instrument_view.setDisabled(False)
            logging.info("Instrument view re-enabled after acquisition")

    def save_acquisition_config_with_backup(self) -> None:
        """
        Wrapper for save_config_with_backup from acquisition view.
        This is called from the File menu in the instrument view.
        """
        if self.acquisition_view is not None:
            self.acquisition_view.save_config_with_backup()

    def _update_acquisition_layer(self, image: np.ndarray, camera_name: str) -> None:
        """
        Update the acquisition image layer in the instrument viewer.

        :param image: Image array to display
        :param camera_name: Name of camera
        """
        if self.instrument_view is None:
            return

        viewer = self.instrument_view.viewer
        pixel_size_um = self.instrument.cameras[camera_name].sampling_um_px
        y_center_um = image.shape[0] // 2 * pixel_size_um
        x_center_um = image.shape[1] // 2 * pixel_size_um

        layer_name = "acquisition"
        if layer_name in viewer.layers:
            layer = viewer.layers[layer_name]
            layer.data = image
            layer.scale = (pixel_size_um, pixel_size_um)
            layer.translate = (-x_center_um, y_center_um)
        else:
            # Get config values for display
            intensity_min = (
                self.instrument_view.config.get("instrument_view", {}).get("properties", {}).get("intensity_min", 0)
            )
            intensity_max = (
                self.instrument_view.config.get("instrument_view", {}).get("properties", {}).get("intensity_max", 65535)
            )
            camera_rotation = (
                self.instrument_view.config.get("instrument_view", {})
                .get("properties", {})
                .get("camera_rotation_deg", 0)
            )

            layer = viewer.add_image(
                image,
                name=layer_name,
                contrast_limits=(intensity_min, intensity_max),
                scale=(pixel_size_um, pixel_size_um),
                translate=(-x_center_um, y_center_um),
                rotate=camera_rotation,
            )

    def _setup_acquisition_file_menu(self, save_callback) -> None:
        """
        Add acquisition config save action to the file menu.

        :param save_callback: Callback to invoke when save is triggered
        """
        if self.instrument_view is None:
            return

        from PyQt6.QtGui import QAction

        viewer = self.instrument_view.viewer
        file_menu = viewer.window.file_menu

        # Add Save Acquisition Config action
        save_config_action = QAction("Save Acquisition Config", viewer.window._qt_window)
        save_config_action.triggered.connect(save_callback)
        file_menu.addAction(save_config_action)

    def save_acquisition_config(self, filename: str | None = None) -> None:
        """
        Save acquisition configuration to YAML file.

        This method handles saving the acquisition config including DAQ tasks
        and tile configuration. It's passed as a callback to the acquisition view.

        :param filename: Output filename (optional, will generate from metadata if not provided)
        """

        from exaspim_control.view import NonAliasingRTRepresenter

        # Create YAML handler with non-aliasing representer
        yaml = ruyaml.YAML()
        yaml.Representer = NonAliasingRTRepresenter

        # Save DAQ tasks to config
        if self.instrument.daqs:
            first_daq = self.instrument.daqs[next(iter(self.instrument.daqs.keys()))]
            self.acquisition.config["acquisition"]["daq"] = first_daq.tasks

        # Determine filename
        if filename is None:
            if self.acquisition.metadata is not None:
                acquisition_name = self.acquisition.metadata.acquisition_name
                filename = f"{acquisition_name}_tiles.yaml"
            else:
                filename = "acquisition_tiles.yaml"

        # Save the tile configuration to the YAML file
        output_path = self.instrument_dir / filename
        with open(output_path, "w") as file:
            yaml.dump(self.acquisition.config, file)

        logging.info(f"Saved acquisition configuration to: {output_path}")

    def _validate_config_files(self) -> None:
        """
        Ensure all required config files exist.

        :raises FileNotFoundError: If any required config file is missing
        """
        missing = []
        for config_file in [self.acquisition_yaml, self.instrument_yaml, self.gui_yaml]:
            if not config_file.exists():
                missing.append(config_file.name)

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

    def _setup_yaml_handler(self) -> YAML:
        """
        Configure YAML handler with custom representers.

        :return: Configured YAML handler
        """
        yaml = YAML()
        yaml.representer.add_representer(np.int64, lambda obj, val: obj.represent_int(int(val)))
        yaml.representer.add_representer(np.int32, lambda obj, val: obj.represent_int(int(val)))
        yaml.representer.add_representer(np.str_, lambda obj, val: obj.represent_str(str(val)))
        yaml.representer.add_representer(np.float64, lambda obj, val: obj.represent_float(float(val)))
        yaml.representer.add_representer(Path, lambda obj, val: obj.represent_str(str(val)))
        yaml.representer.add_representer(WindowsPath, lambda obj, val: obj.represent_str(str(val)))
        return yaml

    def _setup_window_coordination(self) -> None:
        """
        Connect window close events for coordinated shutdown.

        This method sets up pyqtSignal connections to ensure that when either window
        is closed, the other window is also closed and the application shuts down
        cleanly.
        """
        assert self.instrument_view is not None, "instrument_view must be initialized"
        assert self.acquisition_view is not None, "acquisition_view must be initialized"

        # When napari viewer closes, close acquisition view
        self.instrument_view.viewer.window.qt_viewer.destroyed.connect(self._on_instrument_view_closed)

        # When acquisition view closes, close napari viewer
        self.acquisition_view.destroyed.connect(self._on_acquisition_view_closed)

        # Connect to QApplication aboutToQuit for final cleanup
        app = QApplication.instance()
        assert app is not None, "QApplication must exist"
        app.aboutToQuit.connect(self._cleanup)

    def _on_instrument_view_closed(self) -> None:
        """
        Handle instrument view (napari) being closed.

        Closes the acquisition view and quits the application.
        """
        if self._shutting_down:
            return

        self._shutting_down = True
        self.shutting_down.emit()

        logging.info("Instrument view closed - shutting down application")

        assert self.acquisition_view is not None, "acquisition_view must be initialized"

        # Close acquisition view if still open
        if not self.acquisition_view.isHidden():
            self.acquisition_view.close()

        # Quit application
        app = QApplication.instance()
        assert app is not None, "QApplication must exist"
        app.quit()

    def _on_acquisition_view_closed(self) -> None:
        """
        Handle acquisition view being closed.

        Closes the instrument view (napari) and quits the application.
        """
        if self._shutting_down:
            return

        self._shutting_down = True
        self.shutting_down.emit()

        logging.info("Acquisition view closed - shutting down application")

        assert self.instrument_view is not None, "instrument_view must be initialized"

        # Close instrument view (napari) if still open
        try:
            if self.instrument_view.viewer.window._qt_window:
                self.instrument_view.viewer.close()
        except (AttributeError, RuntimeError):
            # Viewer already closed or Qt object deleted
            pass

        # Quit application
        app = QApplication.instance()
        assert app is not None, "QApplication must exist"
        app.quit()

    def _cleanup(self) -> None:
        """
        Final cleanup before application exits.

        Closes hardware connections and releases resources.
        """
        logging.info("Application shutting down - cleaning up resources")

        # Close hardware connections
        try:
            if hasattr(self.instrument, "close"):
                self.instrument.close()
        except Exception as e:
            logging.exception(f"Error closing instrument: {e}")

        try:
            if hasattr(self.acquisition, "close"):
                self.acquisition.close()
        except Exception as e:
            logging.exception(f"Error closing acquisition: {e}")

    def run(self, argv=None) -> int:
        """
        Create QApplication, initialize views, and start the event loop.

        :param argv: Command line arguments (defaults to sys.argv)
        :return: Application exit code
        """
        import sys

        if argv is None:
            argv = sys.argv

        # Create QApplication first
        app = QApplication(argv)

        # Now initialize views (requires QApplication to exist)
        self._initialize_views()

        # Start event loop
        return app.exec()
