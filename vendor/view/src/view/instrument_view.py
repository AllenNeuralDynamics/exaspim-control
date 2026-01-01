import contextlib
import datetime
import importlib
import inspect
import logging
import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import inflection
import napari
import numpy as np
import tifffile
from napari.layers import Image
from napari.qt.threading import create_worker, thread_worker
from napari.utils.theme import get_theme
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from ruyaml import YAML
from voxel._archive.acquisition import Acquisition
from voxel._archive.instrument import Instrument
from voxel.processes.downsample.gpu.gputools.rank_downsample_2d import GPUToolsRankDownSample2D

from view.acquisition_view import AcquisitionView
from view.metadata_launch import MetadataLaunch
from view.ui import ToggleButton
from view.widgets.base_device_widget import (
    BaseDeviceWidget,
    create_widget,
    disable_button,
    pathGet,
    scan_for_properties,
)


class InstrumentView[I: Instrument](QWidget):
    """ "Class to act as a general instrument view model to voxel instrument"""

    snapshotTaken = pyqtSignal(np.ndarray, list)
    contrastChanged = pyqtSignal(np.ndarray, list)

    def __init__(
        self,
        acquisition: Acquisition[I],
        gui_config_path: Path,
        log_filename: str | None = None,
        viewer_title: str = "Instrument Control",
    ):
        """
        :param acquisition: voxel acquisition object containing the instrument
        :param gui_config_path: path to gui config yaml
        :param log_filename: path to log file for metadata coordination
        :param viewer_title: title for the napari viewer window
        """
        super().__init__()

        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        self._acquisition = acquisition
        self.log_filename = log_filename

        # Acquisition view will be created later via _initialize_acquisition_view
        self.acquisition_view = None
        self.metadata_launch = None

        # Eventual threads
        self.grab_frames_worker = create_worker(lambda: None)  # dummy thread
        self.property_workers = []  # list of property workers
        self._is_closing = False  # flag to signal workers to stop
        self.fov_positions_worker = None  # FOV positions worker managed here

        # Eventual attributes
        self.livestream_channel = None
        self.snapshot = False  # flag to pyqtSignal snapshot has been taken

        self.gui_config_path = gui_config_path
        self.config = YAML().load(gui_config_path)

        # Convenient config maps
        self.channels = self.instrument.config["instrument"]["channels"]

        # Setup napari window
        self.viewer = napari.Viewer(title=viewer_title, ndisplay=2, axis_labels=("x", "y"))

        # Initialize viewer properties from config
        self.intensity_min = self.config["instrument_view"]["properties"].get("intensity_min", 0)
        if self.intensity_min < 0 or self.intensity_min > 65535:
            raise ValueError("intensity min must be between 0 and 65535")
        self.intensity_max = self.config["instrument_view"]["properties"].get("intensity_max", 65535)
        if self.intensity_max < self.intensity_min or self.intensity_max > 65535:
            raise ValueError("intensity max must be between intensity min and 65535")
        self.camera_rotation = self.config["instrument_view"]["properties"].get("camera_rotation_deg", 0)
        if self.camera_rotation not in [0, 90, 180, 270, 360, -90, -180, -270]:
            raise ValueError("camera rotation must be 0, 90, 180, 270, -90, -180, -270")
        self.resolution_levels = self.config["instrument_view"]["properties"].get("resolution_levels", 1)
        if self.resolution_levels < 1 or self.resolution_levels > 10:
            raise ValueError("resolution levels must be between 1 and 10")
        self.alignment_roi_size = self.config["instrument_view"]["properties"].get("alignment_roi_size", 128)
        if self.alignment_roi_size < 2 or self.alignment_roi_size > 1024:
            raise ValueError("alignment roi size must be between 2 and 1024")

        # Setup viewer display properties
        self.viewer.scale_bar.visible = True
        self.viewer.scale_bar.unit = "um"
        self.viewer.scale_bar.position = "bottom_left"
        self.viewer.text_overlay.visible = True

        # Initialize viewer state for camera management
        self.previous_layer = None
        self.saved_camera_center = None
        self.saved_camera_zoom = None
        self.viewer.camera.events.zoom.connect(self.camera_zoom)
        self.viewer.camera.events.center.connect(self.camera_position)

        # Cache canvas reference to avoid deprecated qt_viewer access
        # Access through _qt_window (internal but stable) instead of deprecated qt_viewer
        self._canvas = self.viewer.window._qt_window._qt_viewer.canvas  # noqa: SLF001
        self._canvas._scene_canvas.measure_fps(callback=self.update_fps)  # noqa: SLF001

        self.downsampler = GPUToolsRankDownSample2D(binning=2, rank=-2, data_type="uint16")

        # Create and start FOV positions worker - runs continuously until shutdown
        self.fov_positions_worker = self.create_stage_position_worker()
        self.fov_positions_worker.start()

        # Create cache for contrast limit values
        self.contrast_limits = {}
        for key in self.channels:
            self.contrast_limits[key] = [self.intensity_min, self.intensity_max]

        # Add File menu with Save Config option
        self.setup_file_menu()

        # setup daq with livestreaming tasks
        self.setup_daqs()

        # Eventual widget groups
        self.laser_widgets = {}
        self.daq_widgets = {}
        self.camera_widgets = {}
        self.scanning_stage_widgets = {}
        self.tiling_stage_widgets = {}
        self.focusing_stage_widgets = {}
        self.filter_wheel_widgets = {}
        self.flip_mount_widgets = {}
        self.joystick_widgets = {}

        # Set up instrument widgets
        for device_name, device_specs in self.instrument.config["instrument"]["devices"].items():
            self.create_device_widgets(device_name, device_specs)

        # setup widget additional functionalities
        self.setup_camera_widgets()
        self.setup_channel_widget()
        self.setup_stage_widgets()
        self.setup_laser_widgets()
        self.setup_daq_widgets()
        self.setup_flip_mount_widgets()
        self.setup_filter_wheel_widgets()

        # add undocked widget so everything closes together
        self.add_undocked_widgets()

        # Set app events
        app = QApplication.instance()

        self._initialize_acquisition_view()

        self.config_save_to = self.instrument.config_path
        if isinstance(app, QApplication):
            app.lastWindowClosed.connect(self.close)

    @property
    def instrument(self) -> I:
        return self._acquisition.instrument

    def _initialize_acquisition_view(self) -> None:
        """
        Initialize acquisition view and metadata coordination.

        This must be called after QApplication is instantiated.
        Creates acquisition_view internally and sets up all signal coordination.
        """

        # Create acquisition view with self as parent for automatic lifecycle management
        self.acquisition_view = AcquisitionView(
            acquisition=self._acquisition,
            config=self.config,
            update_layer_callback=self._update_acquisition_layer,
            property_worker_factory=self.create_property_worker,
            fov_positions_worker=self.fov_positions_worker,
            parent=self,
        )

        # Set as a top-level window (not embedded) while keeping parent for lifecycle
        self.acquisition_view.setWindowFlag(Qt.WindowType.Window)

        # Hide it initially - will be shown via toggle button
        self.acquisition_view.hide()

        # Connect signal coordination
        self._connect_acquisition_view_signals()

        # Create metadata coordinator
        self.metadata_launch = MetadataLaunch(
            instrument=self.instrument,
            acquisition=self._acquisition,
            instrument_view=self,
            acquisition_view=self.acquisition_view,
            log_filename=self.log_filename,
        )

        # Add toggle button to show/hide acquisition window
        self._setup_acquisition_toggle_button()

    def _connect_acquisition_view_signals(self) -> None:
        """Connect signals between instrument view and acquisition view."""
        if not self.acquisition_view:
            return

        # Connect snapshot and contrast signals to volume model
        if hasattr(self.acquisition_view, "volume_model"):
            self.snapshotTaken.connect(self.acquisition_view.volume_model.add_fov_image)
            self.contrastChanged.connect(self.acquisition_view.volume_model.adjust_glimage_contrast)

        # Connect acquisition lifecycle signals
        self.acquisition_view.acquisitionStarted.connect(self._on_acquisition_started)
        self.acquisition_view.acquisitionEnded.connect(self._on_acquisition_ended)

        # Connect window hidden signal to update toggle button state
        self.acquisition_view.windowHidden.connect(self._on_acquisition_window_hidden)

    def _on_acquisition_started(self, start_time) -> None:
        """
        Handle acquisition start - stop livestream and disable instrument view.

        :param start_time: Datetime when acquisition started
        """
        # Stop livestream if running
        if self.grab_frames_worker.is_running:
            self.log.info("Stopping livestream for acquisition")
            self.grab_frames_worker.quit()

        # Disable instrument view during acquisition
        self.setDisabled(True)
        self.log.info("Instrument view disabled during acquisition")

    def _on_acquisition_ended(self) -> None:
        """Handle acquisition end - re-enable instrument view."""
        # Re-enable instrument view after acquisition
        self.setDisabled(False)
        self.log.info("Instrument view re-enabled after acquisition")

    def _on_acquisition_window_hidden(self) -> None:
        """Handle acquisition window being hidden - update toggle button state."""
        # Don't update UI if we're shutting down
        if self._is_closing:
            return

        if self.acquisition_toggle_button and self.acquisition_toggle_button.isChecked():
            self.acquisition_toggle_button.setChecked(False)
            self.log.info("Toggle button unchecked after window closed")

    def _setup_acquisition_toggle_button(self) -> None:
        """Add toggle button to show/hide acquisition window in bottom-right with muted colors."""
        # Create toggle button with muted blue/red colors
        self.acquisition_toggle_button = ToggleButton(
            unchecked_state={
                "label": "Open Acquisition Window",
                "background": (96, 125, 139),  # Muted slate blue
                "foreground": (255, 255, 255),  # White text
            },
            checked_state={
                "label": "Minimize Acquisition Window",
                "background": (169, 68, 66),  # Muted red
                "foreground": (255, 255, 255),  # White text
            },
        )

        # Connect to show/hide acquisition view
        self.acquisition_toggle_button.toggled.connect(self._toggle_acquisition_window)

        # Add to File menu
        file_menu = self.viewer.window.file_menu
        file_menu.addSeparator()

        # Create a widget action to add the button to the menu
        button_action = QAction("Acquisition Window", self.viewer.window._qt_window)  # noqa: SLF001
        button_action.triggered.connect(self.acquisition_toggle_button.toggle)
        file_menu.addAction(button_action)

        # Add the button as a dock widget in right area (will be at bottom of right side)
        self.viewer.window.add_dock_widget(self.acquisition_toggle_button, area="right", name="Acquisition Control")

    def _toggle_acquisition_window(self, checked: bool) -> None:
        """
        Show or hide acquisition window based on toggle state.

        :param checked: Whether button is checked (True = show, False = hide)
        """
        if self.acquisition_view:
            if checked:
                self.acquisition_view.show()
                self.log.info("Acquisition window opened")
            else:
                self.acquisition_view.hide()
                self.log.info("Acquisition window minimized")

    def _update_acquisition_layer(self, image: np.ndarray, camera_name: str) -> None:
        """
        Update the acquisition image layer in the instrument viewer.

        :param image: Image array to display
        :param camera_name: Name of camera
        """
        if self.viewer is None:
            return

        pixel_size_um = self.instrument.cameras[camera_name].sampling_um_px
        y_center_um = image.shape[0] // 2 * pixel_size_um
        x_center_um = image.shape[1] // 2 * pixel_size_um

        layer_name = "acquisition"
        if layer_name in self.viewer.layers:
            layer = self.viewer.layers[layer_name]
            layer.data = image
            layer.scale = np.array([pixel_size_um, pixel_size_um])
            layer.translate = np.array([-x_center_um, y_center_um])
        else:
            # Get config values for display
            intensity_min = self.config.get("instrument_view", {}).get("properties", {}).get("intensity_min", 0)
            intensity_max = self.config.get("instrument_view", {}).get("properties", {}).get("intensity_max", 65535)
            camera_rotation = self.config.get("instrument_view", {}).get("properties", {}).get("camera_rotation_deg", 0)

            layer = self.viewer.add_image(
                image,
                name=layer_name,
                contrast_limits=(intensity_min, intensity_max),
                scale=(pixel_size_um, pixel_size_um),
                translate=(-x_center_um, y_center_um),
                rotate=camera_rotation,
            )

    @thread_worker
    def create_property_worker(self, device: object, property_name: str) -> Iterator:
        """
        Factory for property monitoring workers.

        Creates a worker that continuously polls a device property.
        Respects the _is_closing flag for clean shutdown.

        :param device: Device object to monitor
        :param property_name: Name of property to poll
        :return: Iterator yielding (value, property_name) tuples
        """
        # Use shorter sleep intervals to check _is_closing more frequently
        sleep_interval = 0.1  # 100ms intervals
        iterations = 5  # 5 * 100ms = 500ms total

        while not self._is_closing:
            # Sleep in small chunks so we can exit quickly
            for _ in range(iterations):
                if self._is_closing:
                    return
                time.sleep(sleep_interval)

            if self._is_closing:
                return

            try:
                value = getattr(device, property_name)
            except ValueError:  # Some devices may return invalid data temporarily
                value = None
            except (RuntimeError, AttributeError):
                # Device closed during shutdown - exit gracefully
                return

            if self._is_closing:
                return

            yield value, property_name

    @thread_worker
    def create_stage_position_worker(self) -> Iterator:
        """
        Factory for stage position monitoring worker.

        Polls all tiling and scanning stages and aggregates their positions.
        Respects the _is_closing flag for clean shutdown.

        :return: Iterator yielding (x, y, z) position tuples
        """
        coordinate_plane = self._acquisition.config.get("acquisition_view", {}).get(
            "coordinate_plane", ["-X", "Y", "Z"]
        )
        scalar_coord_plane = [x.strip("-") for x in coordinate_plane]
        sleep_interval = 0.1  # 100ms intervals

        while not self._is_closing:
            fov_pos = [0.0, 0.0, 0.0]

            for stage in {
                **self.instrument.tiling_stages,
                **self.instrument.scanning_stages,
            }.values():
                if self._is_closing:
                    return

                if stage.instrument_axis in scalar_coord_plane:
                    index = scalar_coord_plane.index(stage.instrument_axis)
                    try:
                        pos = stage.position_mm
                        if pos is not None:
                            fov_pos[index] = pos
                    except ValueError:  # Some stages may return invalid data temporarily
                        pass
                    except (RuntimeError, AttributeError):
                        return  # Exit if device closed during shutdown

            if self._is_closing:
                return

            yield (fov_pos[0], fov_pos[1], fov_pos[2])
            time.sleep(sleep_interval)

    @property
    def filter_wheel_widget(self):
        # return first
        return next(iter(self.filter_wheel_widgets.values()))

    def camera_position(self, _event) -> None:
        """Store viewer state anytime camera moves and there is a layer."""
        if self.previous_layer in self.viewer.layers:
            self.saved_camera_center = self.viewer.camera.center
            self.saved_camera_zoom = self.viewer.camera.zoom

    def camera_zoom(self, _event) -> None:
        """Store viewer state anytime camera zooms and there is a layer."""
        if self.previous_layer in self.viewer.layers:
            self.saved_camera_center = self.viewer.camera.center
            self.saved_camera_zoom = self.viewer.camera.zoom

    def viewer_contrast_limits(self, _event) -> None:
        """Store viewer contrast limits anytime contrast limits change."""
        if self.livestream_channel in self.viewer.layers:
            self.contrast_limits[self.livestream_channel] = self.viewer.layers[self.livestream_channel].contrast_limits

    def setup_file_menu(self) -> None:
        """
        Add File menu with Save Config option.
        Subclasses can override to customize menu setup.
        """
        # Access napari's file menu
        file_menu = self.viewer.window.file_menu

        # Add separator before our custom actions
        file_menu.addSeparator()

        # Add Save Config action
        save_config_action = QAction("Save Config", self.viewer.window._qt_window)  # noqa: SLF001
        save_config_action.triggered.connect(self.save_config_with_backup)
        file_menu.addAction(save_config_action)

        # Add Save Acquisition Config action (calls acquisition_view's save method)
        save_acq_config_action = QAction("Save Acquisition Config", self.viewer.window._qt_window)  # noqa: SLF001
        save_acq_config_action.triggered.connect(self._save_acquisition_config)
        file_menu.addAction(save_acq_config_action)

    def _save_acquisition_config(self) -> None:
        """Save acquisition config by calling acquisition_view's save method."""
        if self.acquisition_view:
            self.acquisition_view.save_config_with_backup()

    def save_config_with_backup(self, backup_dir: str = "bak", config_prefix: str = "instrument") -> None:
        """
        Save current instrument configuration with timestamped backup.
        Creates a backup in config_dir/backup_dir/ folder before saving.
        Shows success/error dialogs to user.

        :param backup_dir: Name of backup directory (default: "bak")
        :param config_prefix: Prefix for backup filename (default: "instrument")
        """
        try:
            # Get config directory and create backup folder
            config_dir = self.instrument.config_path.parent
            bak_dir = config_dir / backup_dir
            bak_dir.mkdir(exist_ok=True)

            # Create timestamped backup filename
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_filename = f"{config_prefix}_{timestamp}.yaml"
            backup_path = bak_dir / backup_filename

            # Copy current config to backup
            if self.instrument.config_path.exists():
                shutil.copy2(self.instrument.config_path, backup_path)
                self.log.info(f"Backup created: {backup_path}")

            # Update and save current config
            self.instrument.update_current_state_config()
            self.instrument.save_config(self.config_save_to)
            self.log.info(f"Configuration saved to {self.config_save_to}")

            # Show success message (override in subclass for custom UI)
            self._show_save_success(backup_filename)

        except Exception as e:
            self.log.exception("Failed to save configuration")
            self._show_save_error(str(e))

    def _show_save_success(self, backup_filename: str) -> None:
        """
        Show save success feedback to user with QMessageBox dialog.

        :param backup_filename: Name of the backup file created
        """
        self.log.info(f"Config saved successfully with backup: {backup_filename}")
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Icon.Information)
        msgBox.setText(f"Configuration saved successfully.\n\nBackup: {backup_filename}")
        msgBox.setWindowTitle("Config Saved")
        msgBox.setStandardButtons(QMessageBox.StandardButton.Ok)
        msgBox.exec()

    def _show_save_error(self, error_message: str) -> None:
        """
        Show save error feedback to user with QMessageBox dialog.

        :param error_message: Error message to display
        """
        self.log.error(f"Failed to save config: {error_message}")
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Icon.Critical)
        msgBox.setText(f"Failed to save configuration:\n{error_message}")
        msgBox.setWindowTitle("Save Error")
        msgBox.setStandardButtons(QMessageBox.StandardButton.Ok)
        msgBox.exec()

    def setup_daqs(self) -> None:
        """
        Initialize daqs with livestreaming tasks if different from data acquisition tasks
        """

        for daq_name, daq in self.instrument.daqs.items():
            if daq_name in self.config["instrument_view"].get("livestream_tasks", {}):
                daq.tasks = self.config["instrument_view"]["livestream_tasks"][daq_name]["tasks"]
                # Make sure if there is a livestreaming task, there is a corresponding data acquisition task:
                if not self.config["acquisition_view"].get("data_acquisition_tasks", {}).get(daq_name, False):
                    self.log.error(
                        f"Daq {daq_name} has a livestreaming task but no corresponding data acquisition "
                        f"task in instrument yaml."
                    )
                    raise ValueError

    def setup_stage_widgets(self) -> None:
        """
        Arrange stage position and joystick widget
        """

        stage_widgets = []
        for widget in {
            **self.tiling_stage_widgets,
            **self.scanning_stage_widgets,
            **self.focusing_stage_widgets,
        }.values():
            label = QLabel()
            frame = QFrame()
            layout = QVBoxLayout()
            layout.addWidget(create_widget("H", label, widget))
            frame.setLayout(layout)
            border_color = get_theme(self.viewer.theme).foreground
            frame.setStyleSheet(f".QFrame {{ border:1px solid {border_color}; }} ")
            stage_widgets.append(frame)

        stage_axes_widget = create_widget("V", *stage_widgets)
        stage_axes_widget.setContentsMargins(0, 0, 0, 0)
        stage_axes_widget.layout().setSpacing(0)

        stage_scroll = QScrollArea()
        stage_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        stage_scroll.setWidget(stage_axes_widget)
        self.viewer.window.add_dock_widget(stage_scroll, area="left", name="Stages")

        joystick_scroll = QScrollArea()
        joystick_scroll.setWidget(self.stack_device_widgets("joystick"))
        self.viewer.window.add_dock_widget(joystick_scroll, area="left", name="Joystick")

    def setup_laser_widgets(self) -> None:
        """
        Setup laser widgets.
        """
        laser_widgets = []
        for name, widget in self.laser_widgets.items():
            label = QLabel(name)
            layout = QVBoxLayout()
            layout.addWidget(create_widget("H", label, widget))
            laser_widgets.append(layout)
        self.laser_widget = create_widget("V", *laser_widgets)
        if (laser_layout := self.laser_widget.layout()) is not None:
            laser_layout.setSpacing(12)
        self.viewer.window.add_dock_widget(self.laser_widget, area="bottom", name="Lasers")

    def setup_channel_widget(self) -> None:
        """
        Create widget to select which laser to livestream with.
        """
        widget = QWidget()
        layout = QVBoxLayout()
        label = QLabel("Active Channel")
        laser_combo_box = QComboBox(widget)
        laser_combo_box.addItems(self.channels.keys())
        laser_combo_box.currentTextChanged.connect(lambda value: self.change_channel(value))
        laser_combo_box.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        laser_combo_box.setCurrentIndex(0)  # initialize to first channel index
        self.laser_combo_box = laser_combo_box
        self.livestream_channel = laser_combo_box.currentText()  # initialize livestream channel
        layout.addWidget(label)
        layout.addWidget(laser_combo_box)
        widget.setLayout(layout)
        widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)
        self.viewer.window.add_dock_widget(widget, area="bottom", name="Channels")

    def setup_daq_widgets(self) -> None:
        """
        Setup saving to config if widget is from device-widget repo
        """

        for daq_name, daq_widget in self.daq_widgets.items():
            # if daq_widget is BaseDeviceWidget or inherits from it, update waveforms when gui is changed
            if isinstance(daq_widget, BaseDeviceWidget):
                daq_widget.ValueChangedInside[str].connect(
                    lambda _value, daq=self.instrument.daqs[daq_name]: self.write_waveforms(daq)
                )
                daq_widget.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
                # update tasks if livestreaming task is different from data acquisition task
                if daq_name in self.config["instrument_view"].get("livestream_tasks", {}):
                    daq_widget.ValueChangedInside[str].connect(
                        lambda attr, widget=daq_widget, daq_name=daq_name: self.update_config_waveforms(
                            widget, daq_name, attr
                        )
                    )

        stacked = self.stack_device_widgets("daq")
        self.viewer.window.add_dock_widget(stacked, area="right", name="DAQs", add_vertical_stretch=False)

    def setup_flip_mount_widgets(self) -> None:
        """
        Set up flip mount widgets.
        """
        stacked = self.stack_device_widgets("flip_mount")
        self.viewer.window.add_dock_widget(stacked, area="right", name="Flip Mounts")

    def stack_device_widgets(self, device_type: str) -> QWidget:
        """
        Stack like device widgets in layout and hide/unhide with combo box
        :param device_type: type of device being stacked
        :return: widget containing all widgets pertaining to device type stacked ontop of each other
        """

        device_widgets = getattr(self, f"{device_type}_widgets")
        overlap_layout = QGridLayout()
        overlap_layout.addWidget(QWidget(), 1, 0)  # spacer widget
        for widget in device_widgets.values():
            widget.setVisible(False)
            overlap_layout.addWidget(widget, 2, 0)

        visible = QComboBox()
        visible.currentTextChanged.connect(lambda text: self.hide_devices(text, device_type))
        visible.addItems(device_widgets.keys())
        visible.setCurrentIndex(0)
        overlap_layout.addWidget(visible, 0, 0)

        overlap_widget = QWidget()
        overlap_widget.setLayout(overlap_layout)

        return overlap_widget

    def hide_devices(self, text: str, device_type: str) -> None:
        """
        Hide device widget if not selected in combo box
        :param text: selected text of combo box
        :param device_type: type of device related to combo box
        """

        device_widgets = getattr(self, f"{device_type}_widgets")
        for name, widget in device_widgets.items():
            if name != text:
                widget.setVisible(False)
            else:
                widget.setVisible(True)

    def write_waveforms(self, daq) -> None:
        """
        Write waveforms if livestreaming is on
        :param daq: daq object
        """

        if self.grab_frames_worker.is_running:  # if currently livestreaming
            if daq.ao_task is not None:
                daq.generate_waveforms("ao", self.livestream_channel)
                daq.write_ao_waveforms(rereserve_buffer=False)
            if daq.do_task is not None:
                daq.generate_waveforms("do", self.livestream_channel)
                daq.write_do_waveforms(rereserve_buffer=False)

    def update_config_waveforms(self, daq_widget, daq_name: str, attr_name: str) -> None:
        """
        If waveforms are changed in gui, apply changes to livestream_tasks and data_acquisition_tasks if
        applicable
        :param daq_widget: widget pertaining to daq object
        :param daq_name: name of daq
        :param attr_name: waveform attribute to update
        """

        path = attr_name.split(".")
        value = getattr(daq_widget, attr_name)
        self.log.debug(f"{daq_name} {attr_name} changed to {getattr(daq_widget, path[0])}")

        # update livestream_task
        self.config["instrument_view"]["livestream_tasks"][daq_name]["tasks"] = daq_widget.tasks

        # update data_acquisition_tasks if value correlates
        key = path[-1]
        dictionary = pathGet(
            self.config["acquisition_view"]["data_acquisition_tasks"][daq_name],
            path[:-1],
        )
        if key not in dictionary:
            self.log.warning(
                f"Key '{key}' not found in dictionary, Path {attr_name} can't be mapped into data "
                f"acquisition tasks so changes will not be reflected in acquisition"
            )

        dictionary[key] = value
        self.log.info(
            f"Data acquisition tasks parameters updated to "
            f"{self.config['acquisition_view']['data_acquisition_tasks'][daq_name]}"
        )

    def setup_filter_wheel_widgets(self):
        """
        Stack filter wheels
        """

        stacked = self.stack_device_widgets("filter_wheel")
        self.viewer.window.add_dock_widget(stacked, area="bottom", name="Filter Wheels")

    def setup_camera_widgets(self):
        """
        Setup live view and snapshot button
        """

        for camera_name, camera_widget in self.camera_widgets.items():
            # Set size policy to contract to contents
            camera_widget.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)

            # Add functionality to snapshot button
            self.snapshot_button = getattr(camera_widget, "snapshot_button", QPushButton())
            self.snapshot_button.pressed.connect(
                lambda button=self.snapshot_button: disable_button(button)
            )  # disable to avoid spamming
            self.snapshot_button.pressed.connect(lambda camera=camera_name: self.setup_live(camera, 1))

            # Add functionality to live button
            live_button = getattr(camera_widget, "live_button", QPushButton())
            live_button.pressed.connect(lambda button=live_button: disable_button(button))  # disable to avoid spamming
            live_button.pressed.connect(lambda camera=camera_name: self.setup_live(camera))
            live_button.pressed.connect(lambda camera=camera_name: self.toggle_live_button(camera))

            # Add functionality to the alignment button (edges button)
            self.alignment_button = getattr(camera_widget, "alignment_button", QPushButton())
            self.alignment_button.setCheckable(True)
            self.alignment_button.released.connect(self.enable_alignment_mode)

            # Add functionality to the crosshairs button
            self.crosshairs_button = getattr(camera_widget, "crosshairs_button", QPushButton())
            self.crosshairs_button.setCheckable(True)

            self.alignment_button.setDisabled(True)  # disable alignment button
            self.crosshairs_button.setDisabled(True)  # disable crosshairs button

        stacked = self.stack_device_widgets("camera")
        camera_scroll = QScrollArea()
        camera_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        camera_scroll.setWidget(stacked)
        self.viewer.window.add_dock_widget(camera_scroll, area="right", name="Cameras", add_vertical_stretch=False)

    def toggle_live_button(self, camera_name: str) -> None:
        """
        Toggle text and functionality of live button when pressed
        :param camera_name: name of camera to set up
        """

        live_button = getattr(self.camera_widgets[camera_name], "live_button", QPushButton())
        live_button.pressed.disconnect()
        if live_button.text() == "Live":
            live_button.setText("Stop")
            style = live_button.style()
            if style is not None:
                stop_icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaStop)
                live_button.setIcon(stop_icon)
            live_button.pressed.connect(self.grab_frames_worker.quit)
        else:
            live_button.setText("Live")
            style = live_button.style()
            if style is not None:
                start_icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
                live_button.setIcon(start_icon)
            live_button.pressed.connect(lambda _camera=camera_name: self.setup_live(camera_name))

        live_button.pressed.connect(lambda button=live_button: disable_button(button))
        live_button.pressed.connect(lambda _camera=camera_name: self.toggle_live_button(camera_name))

    def setup_live(self, camera_name: str, frames=float("inf")) -> None:
        """
        Set up for either livestream or snapshot
        :param camera_name: name of camera to set up
        :param frames: how many frames to take
        """

        layer_list = self.viewer.layers
        layer_name = self.livestream_channel

        # check if switching channels
        if layer_list and layer_name not in layer_list:
            self.viewer.layers.clear()

        if self.grab_frames_worker.is_running:
            if frames == 1:  # create snapshot layer with the latest image
                layer = self.viewer.layers[f"{camera_name} {self.livestream_channel}"]
                image = layer.data[0] if layer.multiscale else layer.data
                self.update_layer((image, camera_name), snapshot=True)
            return

        self.grab_frames_worker = self.grab_frames(camera_name, frames)

        if frames == 1:  # pass in optional argument that this image is a snapshot
            self.grab_frames_worker.yielded.connect(lambda args: self.update_layer(args, snapshot=True))
        else:
            self.grab_frames_worker.yielded.connect(lambda args: self.update_layer(args))

        self.grab_frames_worker.finished.connect(lambda: self.dismantle_live(camera_name))
        self.grab_frames_worker.start()

        self.instrument.cameras[camera_name].prepare()
        # Only convert to int if frames is finite, otherwise pass 0 for continuous
        frame_count = int(frames) if frames != float("inf") else None
        self.instrument.cameras[camera_name].start(frame_count)

        for laser in self.channels[self.livestream_channel].get("lasers", []):
            self.log.info(f"Enabling laser {laser}")
            self.instrument.lasers[laser].enable()
            # Disable other laser widgets during live (if laser_widget exists)
            if hasattr(self, "laser_widget"):
                for child in self.laser_widget.children()[1:]:  # skip first child widget
                    laser_name = child.children()[1].text()  # first child is label widget
                    if laser != laser_name:
                        child.setDisabled(True)
                        child.children()[2].setDisabled(True)

        for filter_device in self.channels[self.livestream_channel].get("filters", []):
            self.log.info(f"Enabling filter {filter_device}")
            self.instrument.filters[filter_device].enable()

        # Enable indicator lights if available
        for light in self.instrument.indicator_lights.values():
            light.enable()

        for daq in self.instrument.daqs.values():
            if daq.tasks.get("ao_task", None) is not None:
                daq.add_task("ao")
                daq.generate_waveforms("ao", self.livestream_channel)
                daq.write_ao_waveforms()
            if daq.tasks.get("do_task", None) is not None:
                daq.add_task("do")
                daq.generate_waveforms("do", self.livestream_channel)
                daq.write_do_waveforms()
            if daq.tasks.get("co_task", None) is not None:
                pulse_count = daq.tasks["co_task"]["timing"].get("pulse_count", None)
                daq.add_task("co", pulse_count)

            daq.start()

        # Manage widget states during live streaming
        if hasattr(self, "filter_wheel_widget"):
            self.filter_wheel_widget.setDisabled(True)
        if hasattr(self, "laser_combo_box"):
            self.laser_combo_box.setDisabled(True)
        if hasattr(self, "alignment_button"):
            self.alignment_button.setDisabled(False)
        if hasattr(self, "crosshairs_button"):
            self.crosshairs_button.setDisabled(False)
        if hasattr(self, "snapshot_button"):
            self.snapshot_button.setDisabled(True)

    def dismantle_live(self, camera_name: str) -> None:
        """
        Safely shut down live
        :param camera_name: name of camera to shut down live
        """

        self.instrument.cameras[camera_name].abort()
        for daq in self.instrument.daqs.values():
            # wait for daq tasks to finish - prevents devices from stopping in
            # unsafe state, i.e. lasers still on
            if hasattr(daq, "co_task") and daq.co_task is not None:
                daq.co_task.stop()
                # sleep to allow last ao to play with 10% buffer
                if hasattr(daq, "co_frequency_hz"):
                    time.sleep(1.0 / daq.co_frequency_hz * 1.1)
                # stop the ao task
                if hasattr(daq, "ao_task") and daq.ao_task is not None:
                    daq.ao_task.stop()
                # close the tasks
                daq.co_task.close()
                if hasattr(daq, "ao_task") and daq.ao_task is not None:
                    daq.ao_task.close()
            else:
                daq.stop()

        for laser_name in self.channels[self.livestream_channel].get("lasers", []):
            self.instrument.lasers[laser_name].disable()
            # Re-enable laser widgets after live (if laser_widget exists)
            if hasattr(self, "laser_widget"):
                for child in self.laser_widget.children()[1:]:  # skip first child widget
                    child_laser_name = child.children()[1].text()  # first child is label widget
                    if laser_name != child_laser_name:
                        child.setDisabled(False)
                        child.children()[2].setDisabled(False)

        # Disable indicator lights if available
        for light in self.instrument.indicator_lights.values():
            light.disable()

        # Re-enable widgets after live streaming
        if hasattr(self, "filter_wheel_widget"):
            self.filter_wheel_widget.setDisabled(False)
        if hasattr(self, "laser_combo_box"):
            self.laser_combo_box.setDisabled(False)
        if hasattr(self, "alignment_button"):
            self.alignment_button.setDisabled(True)
            self.alignment_button.setChecked(False)
        if hasattr(self, "crosshairs_button"):
            self.crosshairs_button.setDisabled(True)
            self.crosshairs_button.setChecked(False)
        if hasattr(self, "snapshot_button"):
            self.snapshot_button.setDisabled(False)

    @thread_worker
    def grab_frames(self, camera_name: str, frames=float("inf")) -> Iterator[tuple[list[np.ndarray], str]]:
        """
        Grab frames from camera with multiscale pyramid
        :param frames: how many frames to take
        :param camera_name: name of camera
        """

        i = 0
        while i < frames:  # while loop since frames can == inf
            time.sleep(0.5)
            multiscale = [self.instrument.cameras[camera_name].grab_frame()]
            for _ in range(1, self.resolution_levels):
                downsampled_frame = multiscale[-1][::2, ::2]
                multiscale.append(downsampled_frame)
            yield multiscale, camera_name
            i += 1

    def update_layer(self, args: tuple, snapshot: bool = False) -> None:
        """
        Update the image layer in the viewer with multiscale support.

        :param args: tuple containing image and camera name
        :type args: tuple
        :param snapshot: Whether the image is a snapshot, defaults to False
        :type snapshot: bool, optional
        """

        (image, camera_name) = args

        # calculate centroid of image
        pixel_size_um = self.instrument.cameras[camera_name].sampling_um_px
        y_center_um = image[0].shape[0] // 2 * pixel_size_um
        x_center_um = image[0].shape[1] // 2 * pixel_size_um

        layer_list = self.viewer.layers

        if image is not None:
            layer_name = self.livestream_channel if not snapshot else f"{self.livestream_channel} snapshot"
            if not snapshot:
                if layer_name in layer_list:
                    layer = layer_list[layer_name]
                    layer.data = image
                    layer.scale = (pixel_size_um, pixel_size_um)
                    layer.translate = (-x_center_um, y_center_um)
                else:
                    contrast_limits = self.contrast_limits[self.livestream_channel]
                    layer = self.viewer.add_image(
                        image,
                        name=layer_name,
                        contrast_limits=(contrast_limits[0], contrast_limits[1]),
                        scale=(pixel_size_um, pixel_size_um),
                        translate=(-x_center_um, y_center_um),
                        rotate=self.camera_rotation,
                    )
                    # connect contrast limits event
                    layer.events.contrast_limits.connect(self.viewer_contrast_limits)
                    # only reset camera state if there is a previous layer, otherwise pass
                    if self.previous_layer and self.saved_camera_center is not None:
                        self.viewer.camera.center = self.saved_camera_center
                        if self.saved_camera_zoom is not None:
                            self.viewer.camera.zoom = self.saved_camera_zoom
                    # update previous layer name
                    self.previous_layer = layer_name
                    layer.mouse_drag_callbacks.append(self.save_image)
                for layer in layer_list:
                    if layer.name == layer_name:
                        layer.selected = True
                        layer.visible = True
                    else:
                        layer.selected = False
                        layer.visible = False
            else:
                layer = self.viewer.add_image(
                    image[-1],
                    name=layer_name,
                    contrast_limits=(self.intensity_min, self.intensity_max),
                    scale=(
                        pixel_size_um * 2 ** (self.resolution_levels - 1),
                        pixel_size_um * 2 ** (self.resolution_levels - 1),
                    ),
                    translate=(-x_center_um, y_center_um),
                    rotate=self.camera_rotation,
                )
                self.snapshotTaken.emit(np.copy(np.rot90(image[-1], k=2)), layer.contrast_limits)
                layer.selected = False
                layer.visible = False

    def dissect_image(self, args: tuple) -> None:
        """
        Dissect the image and add to the viewer for alignment mode.

        :param args: tuple containing image and camera name
        :type args: tuple
        """
        (image, camera_name) = args

        # calculate centroid of image
        pixel_size_um = self.instrument.cameras[camera_name].sampling_um_px
        y_center_um = image[0].shape[0] // 2 * pixel_size_um
        x_center_um = image[1].shape[1] // 2 * pixel_size_um

        if image is not None:
            # Dissect image and add to viewer
            alignment_roi = self.alignment_roi_size
            combined_roi = np.zeros((alignment_roi * 3, alignment_roi * 3))
            # top left corner
            top_left = image[0][0:alignment_roi, 0:alignment_roi]
            combined_roi[0:alignment_roi, 0:alignment_roi] = top_left
            # top right corner
            top_right = image[0][0:alignment_roi, -alignment_roi:]
            combined_roi[0:alignment_roi, alignment_roi * 2 : alignment_roi * 3] = top_right
            # bottom left corner
            bottom_left = image[0][-alignment_roi:, 0:alignment_roi]
            combined_roi[alignment_roi * 2 : alignment_roi * 3, 0:alignment_roi] = bottom_left
            # bottom right corner
            bottom_right = image[0][-alignment_roi:, -alignment_roi:]
            combined_roi[alignment_roi * 2 : alignment_roi * 3, alignment_roi * 2 : alignment_roi * 3] = bottom_right
            # center left
            center_left = image[0][
                round((image[0].shape[0] / 2) - alignment_roi / 2) : round((image[0].shape[0] / 2) + alignment_roi / 2),
                0:alignment_roi,
            ]
            combined_roi[alignment_roi : alignment_roi * 2, 0:alignment_roi] = center_left
            # center right
            center_right = image[0][
                round((image[0].shape[0] / 2) - alignment_roi / 2) : round((image[0].shape[0] / 2) + alignment_roi / 2),
                -alignment_roi:,
            ]
            combined_roi[alignment_roi : alignment_roi * 2, alignment_roi * 2 : alignment_roi * 3] = center_right
            # center top
            center_top = image[0][
                0:alignment_roi,
                round((image[0].shape[1] / 2) - alignment_roi / 2) : round((image[0].shape[1] / 2) + alignment_roi / 2),
            ]
            combined_roi[0:alignment_roi, alignment_roi : alignment_roi * 2] = center_top
            # center bottom
            center_bottom = image[0][
                -alignment_roi:,
                round((image[0].shape[1] / 2) - alignment_roi / 2) : round((image[0].shape[1] / 2) + alignment_roi / 2),
            ]
            combined_roi[alignment_roi * 2 : alignment_roi * 3, alignment_roi : alignment_roi * 2] = center_bottom
            # center roi
            center = image[0][
                round((image[0].shape[0] / 2) - alignment_roi / 2) : round((image[0].shape[0] / 2) + alignment_roi / 2),
                round((image[0].shape[1] / 2) - alignment_roi / 2) : round((image[0].shape[1] / 2) + alignment_roi / 2),
            ]
            combined_roi[alignment_roi : alignment_roi * 2, alignment_roi : alignment_roi * 2] = center

            # add crosshairs to image
            combined_roi[alignment_roi - 2 : alignment_roi + 2, :] = 1 << 16 - 1
            combined_roi[alignment_roi * 2 - 2 : alignment_roi * 2 + 2, :] = 1 << 16 - 1
            combined_roi[:, alignment_roi - 2 : alignment_roi + 2] = 1 << 16 - 1
            combined_roi[:, alignment_roi * 2 - 2 : alignment_roi * 2 + 2] = 1 << 16 - 1

            layer_name = f"{self.livestream_channel} alignment"
            if layer_name in self.viewer.layers:
                layer = self.viewer.layers[layer_name]
                layer.data = combined_roi
            else:
                layer = self.viewer.add_image(
                    combined_roi,
                    name=layer_name,
                    contrast_limits=(self.intensity_min, self.intensity_max),
                    scale=(pixel_size_um, pixel_size_um),
                    translate=(-x_center_um, y_center_um),
                    rotate=self.camera_rotation,
                )

    def enable_alignment_mode(self) -> None:
        """
        Enable alignment mode.
        """
        if not self.grab_frames_worker.is_running:
            return

        self.viewer.layers.clear()

        if self.alignment_button.isChecked():
            self.grab_frames_worker.yielded.disconnect()
            self.grab_frames_worker.yielded.connect(self.dissect_image)
        else:
            self.grab_frames_worker.yielded.disconnect()
            self.grab_frames_worker.yielded.connect(self.update_layer)

    @staticmethod
    def save_image(layer: Image, event: QMouseEvent) -> None:
        """
        Save image in viewer by right-clicking viewer
        :param layer: layer that was pressed
        :param event: mouse event
        """

        if event.button == 2:  # Left click
            image = layer.data[0] if layer.multiscale else layer.data
            fname = QFileDialog()
            folder = fname.getSaveFileName(
                directory=str(
                    Path(__file__).parent.resolve()
                    / Path(rf"\{layer.name}_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.tiff")
                )
            )
            if folder[0] != "":  # user pressed cancel
                tifffile.imwrite(f"{folder[0]}.tiff", image, imagej=True)

    def change_channel(self, channel: str) -> None:
        """
        Change the livestream channel.

        :param channel: Name of the channel
        :type channel: str
        """
        if self.grab_frames_worker.is_running:  # livestreaming is going
            for old_laser_name in self.channels[self.livestream_channel].get("lasers", []):
                self.log.info(f"Disabling laser {old_laser_name}")
                self.instrument.lasers[old_laser_name].disable()
            for daq_name, daq in self.instrument.daqs.items():
                self.log.info(f"Writing new waveforms for {daq_name}")
                self.write_waveforms(daq)
            for new_laser_name in self.channels[channel].get("lasers", []):
                self.log.info(f"Enabling laser {new_laser_name}")
                self.instrument.lasers[new_laser_name].enable()
        self.livestream_channel = channel
        # change filter
        for filter_device in self.channels[self.livestream_channel].get("filters", []):
            self.log.info(f"Enabling filter {filter_device}")
            self.instrument.filters[filter_device].enable()

    def update_fps(self, fps: float) -> None:
        """
        Update the frames per second (FPS) display.

        :param fps: Frames per second
        :type fps: float
        """
        self.viewer.text_overlay.text = f"{fps:1.1f} fps"

    def create_device_widgets(self, device_name: str, device_specs: dict) -> None:
        """
        Create widgets based on device dictionary attributes from instrument or acquisition
         :param device_name: name of device
         :param device_specs: dictionary dictating how device should be set up
        """

        device_type = device_specs["type"]
        device = getattr(self.instrument, inflection.pluralize(device_type))[device_name]

        specs = self.config["instrument_view"]["device_widgets"].get(device_name, {})
        if specs != {} and specs.get("type", "") == device_type:
            gui_class = getattr(importlib.import_module(specs["driver"]), specs["module"])
            gui = gui_class(device, **specs.get("init", {}))  # device gets passed into widget
        else:
            properties = scan_for_properties(device)
            gui = BaseDeviceWidget(type(device), properties)

        # if gui is BaseDeviceWidget or inherits from it,
        # hook up widgets to device_property_changed when user changes value
        if isinstance(gui, BaseDeviceWidget):
            gui.ValueChangedInside[str].connect(
                lambda value, dev=device, widget=gui: self.device_property_changed(value, dev, widget)
            )

            updating_props = specs.get("updating_properties", [])
            for prop_name in updating_props:
                worker = self.create_property_worker(device, prop_name)  # pyright: ignore[reportCallIssue]
                # Worker yields (value, property_name), we need (value, widget, property_name)
                worker.yielded.connect(lambda args, w=gui: self.update_property_value(args[0], w, args[1]))
                worker.start()
                self.property_workers.append(worker)

        # add ui to widget dictionary
        if not hasattr(self, f"{device_type}_widgets"):
            setattr(self, f"{device_type}_widgets", {})
        getattr(self, f"{device_type}_widgets")[device_name] = gui

        for subdevice_name, subdevice_specs in device_specs.get("subdevices", {}).items():
            # if device has subdevice, create and pass on same Lock()
            self.create_device_widgets(subdevice_name, subdevice_specs)

        gui.setWindowTitle(f"{device_type} {device_name}")

    def update_property_value(self, value, device_widget, property_name: str) -> None:
        """
        Update stage position in stage widget
        :param device_widget: widget of entire device that is the parent of property widget
        :param value: value to update with
        :param property_name: name of property to set
        """
        with contextlib.suppress(RuntimeError, AttributeError):
            setattr(device_widget, property_name, value)  # setting attribute value will update widget

    @pyqtSlot(str)
    def device_property_changed(self, attr_name: str, device: object, widget) -> None:
        """
        pyqtSlot to pyqtSignal when device widget has been changed
        :param widget: widget object relating to device
        :param device: device object
        :param attr_name: name of attribute
        """

        name_lst = attr_name.split(".")
        self.log.debug(f"widget {attr_name} changed to {getattr(widget, name_lst[0])}")
        value = getattr(widget, name_lst[0])
        try:  # Make sure name is referring to same thing in UI and device
            dictionary = getattr(device, name_lst[0])
            for k in name_lst[1:]:
                dictionary = dictionary[k]

            # attempt to pass in correct value of correct type
            descriptor = getattr(type(device), name_lst[0])
            fset = descriptor.fset
            input_type = list(inspect.signature(fset).parameters.values())[-1].annotation
            if input_type != inspect.Parameter.empty:
                setattr(device, name_lst[0], input_type(value))
            else:
                setattr(device, name_lst[0], value)

            self.log.info(f"Device changed to {getattr(device, name_lst[0])}")
            # Update ui with new device values that might have changed
            # WARNING: Infinite recursion might occur if device property not set correctly
            for k in widget.property_widgets:
                if getattr(widget, k, False):
                    device_value = getattr(device, k)
                    setattr(widget, k, device_value)

        except (KeyError, TypeError):
            self.log.warning(f"{attr_name} can't be mapped into device properties")

    def add_undocked_widgets(self) -> None:
        """
        Add undocked widget so all windows close when closing napari viewer
        """

        widgets = []
        for key, dictionary in self.__dict__.items():
            if "_widgets" in key:
                widgets.extend(dictionary.values())
        for widget in widgets:
            if widget not in self.viewer.window._qt_window.findChildren(type(widget)):  # noqa: SLF001
                undocked_widget = self.viewer.window.add_dock_widget(widget, name=widget.windowTitle())
                undocked_widget.setFloating(True)
                # hide widget if empty property widgets
                if getattr(widget, "property_widgets", False) == {}:
                    undocked_widget.setVisible(False)

    def setDisabled(self, a0: bool) -> None:
        """
        Enable/disable viewer
        :param a0: boolean specifying whether to disable
        """

        widgets = []
        for key, dictionary in self.__dict__.items():
            if "_widgets" in key:
                widgets.extend(dictionary.values())
        for widget in widgets:
            with contextlib.suppress(AttributeError):
                widget.setDisabled(a0)

    def closeEvent(self, a0) -> None:
        """
        Handle window close event to ensure proper cleanup
        """
        self.close()
        if a0 is not None:
            a0.accept()

    def close(self) -> bool:
        """
        Close instruments and end threads
        """
        # Set the flag FIRST so workers stop yielding immediately
        self._is_closing = True

        # Quit all workers - they will check _is_closing flag and stop yielding
        for worker in self.property_workers:
            with contextlib.suppress(AttributeError, RuntimeError, TypeError):
                worker.quit()

        # Quit FOV positions worker
        if self.fov_positions_worker is not None:
            with contextlib.suppress(AttributeError, RuntimeError, TypeError):
                self.fov_positions_worker.quit()

        with contextlib.suppress(AttributeError, RuntimeError, TypeError):
            self.grab_frames_worker.quit()

        # Wait for all workers to finish with timeout
        for worker in self.property_workers:
            max_wait = 0.5  # seconds
            elapsed = 0.0
            while worker.is_running and elapsed < max_wait:
                time.sleep(0.02)
                elapsed += 0.02

        max_wait = 0.5
        elapsed = 0.0
        while self.grab_frames_worker.is_running and elapsed < max_wait:
            time.sleep(0.02)
            elapsed += 0.02

        # acquisition_view will close itself via the closing signal (no need to call close here)

        # Close devices
        for device_name, device_specs in self.instrument.config["instrument"]["devices"].items():
            device_type = device_specs["type"]
            device = getattr(self.instrument, inflection.pluralize(device_type))[device_name]
            try:
                device.close()
            except AttributeError:
                self.log.debug(f"{device_name} does not have close function")
        self.instrument.close()

        return super().close()
