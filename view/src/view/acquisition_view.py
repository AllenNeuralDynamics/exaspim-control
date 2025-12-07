import importlib
import logging
import shutil
import time
from collections.abc import Callable
from datetime import datetime

import inflection
import numpy as np
from napari.qt import get_stylesheet
from napari.qt.threading import create_worker
from napari.settings import get_settings
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QWidget,
)
from voxel.acquisition import Acquisition
from voxel.instrument import Instrument

from view.widgets.acquisition_widgets.channel_plan_widget import ChannelPlanWidget
from view.widgets.acquisition_widgets.metadata_widget import MetadataWidget
from view.widgets.acquisition_widgets.volume_model import VolumeModel
from view.widgets.acquisition_widgets.volume_plan_widget import (
    GridFromEdges,
    GridRowsColumns,
    GridWidthHeight,
    VolumePlanWidget,
)
from view.widgets.base_device_widget import (
    BaseDeviceWidget,
    create_widget,
    label_maker,
    scan_for_properties,
)
from view.widgets.miscellaneous_widgets.q_dock_widget_title_bar import (
    QDockWidgetTitleBar,
)
from view.widgets.miscellaneous_widgets.q_scrollable_float_slider import (
    QScrollableFloatSlider,
)
from view.widgets.miscellaneous_widgets.q_scrollable_line_edit import (
    QScrollableLineEdit,
)


class AcquisitionView[I: Instrument](QWidget):
    """ "Class to act as a general acquisition view model to voxel instrument"""

    acquisitionEnded: pyqtSignal = pyqtSignal()
    acquisitionStarted: pyqtSignal = pyqtSignal(datetime)
    windowHidden: pyqtSignal = pyqtSignal()  # Emitted when window is hidden via close button

    def __init__(
        self,
        acquisition: Acquisition[I],
        config: dict,
        update_layer_callback: Callable,
        property_worker_factory: Callable,
        fov_positions_worker,
        parent=None,
    ):
        """
        :param acquisition: voxel acquisition object
        :param config: configuration dictionary
        :param update_layer_callback: callback(image, camera_name) for updating viewer layers
        :param property_worker_factory: factory function(device, property_name) for creating property workers
        :param fov_positions_worker: worker instance from InstrumentView that yields FOV positions
        :param parent: parent widget (for Qt lifecycle management)
        """

        super().__init__(parent)
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        config["acquisition_view"]["unit"] = "mm"
        self.setStyleSheet(get_stylesheet(get_settings().appearance.theme))
        self.acquisition = acquisition
        self.instrument = self.acquisition.instrument
        self.config = config
        self.coordinate_plane = self.config["acquisition_view"]["coordinate_plane"]
        self.unit = self.config["acquisition_view"]["unit"]
        self.update_layer_callback = update_layer_callback
        self.property_worker_factory = property_worker_factory
        self.property_workers = []

        # create workers for latest image taken by cameras
        for camera_name, camera in self.instrument.cameras.items():
            worker = self.property_worker_factory(camera, "latest_frame")
            worker.yielded.connect(lambda args, name=camera_name: self.update_acquisition_layer(args[0], name))
            worker.start()
            worker.pause()  # start and pause, so we can resume when acquisition starts and pause when over
            self.property_workers.append(worker)

        for device_name, operation_dictionary in self.acquisition.config["acquisition"]["operations"].items():
            for operation_name, operation_specs in operation_dictionary.items():
                self.create_operation_widgets(device_name, operation_name, operation_specs)

        # setup additional widgets
        self.metadata_widget = self.create_metadata_widget()
        self.acquisition_widget = self.create_acquisition_widget()
        self.start_button = self.create_start_button()
        self.stop_button = self.create_stop_button()

        # Connect FOV positions worker to volume widgets
        if fov_positions_worker is not None:
            fov_positions_worker.yielded.connect(lambda pos: setattr(self.volume_plan, "fov_position", list(pos)))
            fov_positions_worker.yielded.connect(lambda pos: setattr(self.volume_model, "fov_position", list(pos)))

        # Set up main window
        self.main_layout = QGridLayout()

        # Add start and stop button
        self.main_layout.addWidget(self.start_button, 0, 0, 1, 2)
        self.main_layout.addWidget(self.stop_button, 0, 2, 1, 2)

        # add volume widget
        self.main_layout.addWidget(self.acquisition_widget, 1, 0, 5, 3)

        # splitter for operation widgets
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        # create scroll wheel for metadata widget
        scroll = QScrollArea()
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.metadata_widget)
        scroll.setWindowTitle("Metadata")
        scroll.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        dock = QDockWidget(scroll.windowTitle(), self)
        dock.setWidget(scroll)
        dock.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        dock.setTitleBarWidget(QDockWidgetTitleBar(dock))
        dock.setMinimumHeight(25)
        splitter.addWidget(dock)

        # create dock widget for operations
        for i, operation in enumerate(["writer", "file_transfer", "process", "routine"]):
            if hasattr(self, f"{operation}_widgets"):
                stack = self.stack_device_widgets(operation)
                stack.setFixedWidth(self.metadata_widget.size().width() - 20)
                scroll = QScrollArea()
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                scroll.setWidget(stack)
                scroll.setFixedWidth(self.metadata_widget.size().width())
                dock = QDockWidget(stack.windowTitle())
                dock.setTitleBarWidget(QDockWidgetTitleBar(dock))
                dock.setWidget(scroll)
                dock.setMinimumHeight(25)
                setattr(self, f"{operation}_dock", dock)
                splitter.addWidget(dock)
        self.main_layout.addWidget(splitter, 1, 3)
        self.setLayout(self.main_layout)
        self.setWindowTitle("Acquisition View")
        self.show()

        # acquisition view constants for ExA-SPIM
        self.binning_levels = 2
        self.acquisition_thread = create_worker(self.acquisition.run)
        # Eventual threads
        self.grab_frames_worker = create_worker(lambda: None)  # dummy thread
        self.setWindowTitle("ExA-SPIM control")

        # Get display properties from config
        self.intensity_min = config.get("instrument_view", {}).get("properties", {}).get("intensity_min", 0)
        self.intensity_max = config.get("instrument_view", {}).get("properties", {}).get("intensity_max", 65535)
        self.camera_rotation = config.get("instrument_view", {}).get("properties", {}).get("camera_rotation_deg", 0)

        # Set app events
        app = QApplication.instance()
        # Config save removed from quit - now manual via File menu
        self.config_save_to = self.acquisition.config_path
        app.lastWindowClosed.connect(self.close)  # shut everything down when closing

    def stop_acquisition(self) -> None:
        """
        Stop the acquisition process.
        """
        self.acquisition_thread.quit()
        self.acquisition.stop_acquisition()

    def create_start_button(self) -> QPushButton:
        """
        Create the start button.

        :return: Start button
        :rtype: QPushButton
        """
        start = QPushButton("Start")
        start.clicked.connect(self.start_acquisition)
        start.setStyleSheet("background-color: #55a35d; color: black; border-radius: 10px;")
        return start

    def create_stop_button(self) -> QPushButton:
        """
        Create the stop button.

        :return: Stop button
        :rtype: QPushButton
        """
        stop = QPushButton("Stop")
        stop.clicked.connect(self.stop_acquisition)
        stop.setStyleSheet("background-color: #a3555b; color: black; border-radius: 10px;")
        stop.setDisabled(True)
        return stop

    def save_config_with_backup(self, backup_dir: str = "bak", config_prefix: str = "acquisition") -> None:
        """
        Save current acquisition configuration with timestamped backup.
        Creates a backup in config_dir/backup_dir/ folder before saving.
        Shows success/error dialogs to user.

        :param backup_dir: Name of backup directory (default: "bak")
        :param config_prefix: Prefix for backup filename (default: "acquisition")
        """
        try:
            # Get config directory and create backup folder
            config_dir = self.acquisition.config_path.parent
            bak_dir = config_dir / backup_dir
            bak_dir.mkdir(exist_ok=True)

            # Create timestamped backup filename
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_filename = f"{config_prefix}_{timestamp}.yaml"
            backup_path = bak_dir / backup_filename

            # Copy current config to backup

            if self.acquisition.config_path.exists():
                shutil.copy2(self.acquisition.config_path, backup_path)
                self.log.info(f"Backup created: {backup_path}")

            # Update and save current config
            self.acquisition.update_current_state_config()
            self.acquisition.save_config(self.config_save_to)
            self.log.info(f"Configuration saved to {self.config_save_to}")

            # Show success message (override in subclass for custom UI)
            self._show_save_success(backup_filename)

        except Exception as e:
            self.log.exception(f"Failed to save configuration: {e}")
            self._show_save_error(str(e))

    def _show_save_success(self, backup_filename: str) -> None:
        """
        Show save success feedback to user with QMessageBox dialog.

        :param backup_filename: Name of the backup file created
        """
        self.log.info(f"Config saved successfully with backup: {backup_filename}")
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Information)
        msgBox.setText(f"Acquisition configuration saved successfully.\n\nBackup: {backup_filename}")
        msgBox.setWindowTitle("Config Saved")
        msgBox.setStandardButtons(QMessageBox.Ok)
        msgBox.exec()

    def _show_save_error(self, error_message: str) -> None:
        """
        Show save error feedback to user with QMessageBox dialog.

        :param error_message: Error message to display
        """
        self.log.error(f"Failed to save config: {error_message}")
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Critical)
        msgBox.setText(f"Failed to save configuration:\n{error_message}")
        msgBox.setWindowTitle("Save Error")
        msgBox.setStandardButtons(QMessageBox.Ok)
        msgBox.exec()

    def start_acquisition(self) -> None:
        """
        Start acquisition and disable widgets
        """

        # add tiles to acquisition config
        self.update_tiles()

        # Note: Livestream stopping should be handled by application coordinator
        # Application should connect to acquisitionStarting pyqtSignal

        # write correct daq values if different from livestream
        for daq_name, daq in self.instrument.daqs.items():
            if daq_name in self.config["acquisition_view"].get("data_acquisition_tasks", {}):
                daq.tasks = self.config["acquisition_view"]["data_acquisition_tasks"][daq_name]["tasks"]

        # anchor grid in volume widget
        for anchor, widget in zip(self.volume_plan.anchor_widgets, self.volume_plan.grid_offset_widgets, strict=True):
            anchor.setChecked(True)
            widget.setDisabled(True)
        self.volume_plan.tile_table.setDisabled(True)
        self.channel_plan.setDisabled(True)

        # disable acquisition view. Can't disable whole thing so stop button can be functional
        self.start_button.setEnabled(False)
        self.metadata_widget.setEnabled(False)
        for operation in ["writer", "transfer", "process", "routine"]:
            if hasattr(self, f"{operation}_dock"):
                getattr(self, f"{operation}_dock").setDisabled(True)
        self.stop_button.setEnabled(True)

        # Note: Instrument view disable/enable should be handled by application coordinator

        # Start acquisition
        self.acquisition_thread = create_worker(self.acquisition.run)
        self.acquisition_thread.start()
        self.acquisition_thread.finished.connect(self.acquisition_ended)

        # start all workers
        for worker in self.property_workers:
            worker.resume()
            time.sleep(1)
        self.acquisitionStarted.emit(datetime.now())

    def acquisition_ended(self) -> None:
        """
        Re-enable UI's and threads after acquisition has ended
        """

        # enable acquisition view
        self.start_button.setEnabled(True)
        self.metadata_widget.setEnabled(True)
        for operation in ["writer", "transfer", "process", "routine"]:
            if hasattr(self, f"{operation}_dock"):
                getattr(self, f"{operation}_dock").setDisabled(False)
        self.stop_button.setEnabled(False)

        # write correct daq values if different from acquisition task
        for daq_name, daq in self.instrument.daqs.items():
            if daq_name in self.config["instrument_view"].get("livestream_tasks", {}):
                daq.tasks = self.config["instrument_view"]["livestream_tasks"][daq_name]["tasks"]

        # unanchor grid in volume widget
        # anchor grid in volume widget
        for anchor, widget in zip(self.volume_plan.anchor_widgets, self.volume_plan.grid_offset_widgets):
            anchor.setChecked(False)
            widget.setDisabled(False)
        self.volume_plan.tile_table.setDisabled(False)
        self.channel_plan.setDisabled(False)

        # Note: Instrument view enable should be handled by application coordinator
        # No longer directly accessing instrument_view here

        for worker in self.property_workers:
            worker.pause()

        self.acquisitionEnded.emit()

    def stack_device_widgets(self, device_type: str) -> QWidget:
        """
        Stack like device widgets in layout and hide/unhide with combo box
        :param device_type: type of device being stacked
        :return: widget containing all widgets pertaining to device type stacked ontop of each other
        """

        device_widgets = {
            f"{inflection.pluralize(device_type)} {device_name}": create_widget("V", **widgets)
            for device_name, widgets in getattr(self, f"{device_type}_widgets").items()
        }

        overlap_layout = QGridLayout()
        overlap_layout.addWidget(QWidget(), 1, 0)  # spacer widget
        for widget in device_widgets.values():
            widget.setVisible(False)
            overlap_layout.addWidget(widget, 2, 0)

        visible = QComboBox()
        visible.currentTextChanged.connect(lambda text: self.hide_devices(text, device_widgets))
        visible.addItems(device_widgets.keys())
        visible.setCurrentIndex(0)
        overlap_layout.addWidget(visible, 0, 0)

        overlap_widget = QWidget()
        overlap_widget.setWindowTitle(inflection.pluralize(device_type))
        overlap_widget.setLayout(overlap_layout)

        return overlap_widget

    @staticmethod
    def hide_devices(text: str, device_widgets: dict) -> None:
        """
        Hide device widget if not selected in combo box
        :param text: selected text of combo box
        :param device_widgets: dictionary of widget groups
        """

        for name, widget in device_widgets.items():
            if name != text:
                widget.setVisible(False)
            else:
                widget.setVisible(True)

    def create_metadata_widget(self) -> MetadataWidget:
        """
        Create custom widget for metadata in config
        :return: widget for metadata
        """

        metadata_widget = MetadataWidget(self.acquisition.metadata)
        metadata_widget.ValueChangedInside[str].connect(
            lambda name: setattr(self.acquisition.metadata, name, getattr(metadata_widget, name))
        )
        for widget in metadata_widget.property_widgets.values():
            widget.setToolTip("")  # reset tooltips
        metadata_widget.setWindowTitle("Metadata")
        return metadata_widget

    def create_acquisition_widget(self) -> QSplitter:
        """
        Create the acquisition widget.

        :raises KeyError: If the coordinate plane does not match instrument axes in tiling_stages
        :return: Acquisition widget
        :rtype: QSplitter
        """
        # find limits of all axes
        lim_dict = {}
        # add tiling stages
        for stage in self.instrument.tiling_stages.values():
            lim_dict.update({f"{stage.instrument_axis}": stage.limits_mm})
        # last axis should be scanning axis
        ((_scan_name, scan_stage),) = self.instrument.scanning_stages.items()
        lim_dict.update({f"{scan_stage.instrument_axis}": scan_stage.limits_mm})
        try:
            limits = [lim_dict[x.strip("-")] for x in self.coordinate_plane]
        except KeyError:
            raise KeyError("Coordinate plane must match instrument axes in tiling_stages") from None

        # TODO fix this, messy way to figure out FOV dimensions from camera properties
        first_camera_key = next(iter(self.instrument.cameras.keys()))
        camera = self.instrument.cameras[first_camera_key]
        fov_height_mm = camera.fov_height_mm
        fov_width_mm = camera.fov_width_mm
        camera_rotation = self.config["instrument_view"]["properties"].get("camera_rotation_deg", 0)
        if camera_rotation in [-270, -90, 90, 270]:
            fov_dimensions = [fov_height_mm, fov_width_mm, 0]
        else:
            fov_dimensions = [fov_width_mm, fov_height_mm, 0]

        acquisition_widget = QSplitter(Qt.Orientation.Vertical)
        acquisition_widget.setChildrenCollapsible(False)

        # create volume plan
        self.volume_plan = VolumePlanWidget(
            # instrument=self.instrument,
            limits=limits,
            fov_dimensions=fov_dimensions,
            coordinate_plane=self.coordinate_plane,
            unit=self.unit,
            default_overlap=(self.config["acquisition_view"].get("default_overlap", 15.0)),
            default_order=(self.config["acquisition_view"].get("default_tile_order", "row_wise")),
        )
        self.volume_plan.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        # create volume model
        self.volume_model = VolumeModel(
            limits=limits,
            fov_dimensions=fov_dimensions,
            coordinate_plane=self.coordinate_plane,
            unit=self.unit,
            **self.config["acquisition_view"]["acquisition_widgets"].get("volume_model", {}).get("init", {}),
        )
        # combine floating volume_model widget with glwindow
        combined_layout = QGridLayout()
        combined_layout.addWidget(self.volume_model, 0, 0, 3, 1)
        combined_layout.addWidget(self.volume_model.widgets, 3, 0, 1, 1)
        combined = QWidget()
        combined.setLayout(combined_layout)
        acquisition_widget.addWidget(create_widget("H", self.volume_plan, combined))

        # create channel plan
        self.channel_plan = ChannelPlanWidget(
            instrument=self.instrument,
            unit=self.unit,
            **self.config["acquisition_view"]["acquisition_widgets"].get("channel_plan", {}).get("init", {}),
        )
        # place volume_plan.tile_table and channel plan table side by side
        table_splitter = QSplitter(Qt.Orientation.Horizontal)
        table_splitter.setChildrenCollapsible(False)
        table_splitter.setHandleWidth(20)

        widget = QWidget()  # dummy widget to move tile_table down in layout
        widget.setMinimumHeight(25)
        table_splitter.addWidget(create_widget("V", widget, self.volume_plan.tile_table))
        table_splitter.addWidget(self.channel_plan)

        # format splitter handle. Must do after all widgets are added
        handle = table_splitter.handle(1)
        handle_layout = QHBoxLayout(handle)
        line = QFrame(handle)
        line.setStyleSheet("QFrame {border: 1px dotted grey;}")
        line.setFixedHeight(50)
        line.setFrameShape(QFrame.Shape.VLine)
        handle_layout.addWidget(line)

        # add tables to layout
        acquisition_widget.addWidget(table_splitter)

        # connect signals
        # Note: snapshotTaken and contrastChanged should be connected by application coordinator
        self.volume_model.fovHalt.connect(self.stop_stage)  # stop stage if halt button is pressed
        self.volume_model.fovMove.connect(self.move_stage)  # move stage to clicked coords
        self.volume_plan.valueChanged.connect(self.volume_plan_changed)
        self.channel_plan.channelAdded.connect(self.channel_plan_changed)
        self.channel_plan.channelChanged.connect(self.update_tiles)

        # TODO: This feels like a clunky connection. Works for now but could probably be improved
        self.volume_plan.header.startChanged.connect(lambda i: self.create_tile_list())
        self.volume_plan.header.stopChanged.connect(lambda i: self.create_tile_list())

        return acquisition_widget

    def channel_plan_changed(self, channel: str) -> None:
        """
        Handle channel being added to scan
        :param channel: channel added
        """

        tile_order = [[t.row, t.col] for t in self.volume_plan.value()]
        if len(tile_order) != 0:
            self.channel_plan.add_channel_rows(channel, tile_order)
        self.update_tiles()

    def volume_plan_changed(self, value: GridRowsColumns | GridFromEdges | GridWidthHeight) -> None:
        """
        Update channel plan and volume model when volume plan is changed
        :param value: new value from volume_plan
        """

        tile_volumes = self.volume_plan.scan_ends - self.volume_plan.scan_starts

        # update volume model
        self.volume_model.blockSignals(True)  # only trigger update once
        # self.volume_model.fov_dimensions = self.volume_plan.fov_dimensions
        self.volume_model.grid_coords = self.volume_plan.tile_positions
        self.volume_model.scan_volumes = tile_volumes
        self.volume_model.blockSignals(False)
        self.volume_model.tile_visibility = self.volume_plan.tile_visibility
        self.volume_model.set_path_pos([self.volume_model.grid_coords[t.row][t.col] for t in value])

        # update channel plan
        self.channel_plan.apply_all = self.volume_plan.apply_all
        self.channel_plan.tile_volumes = tile_volumes
        for ch in self.channel_plan.channels:
            self.channel_plan.add_channel_rows(ch, [[t.row, t.col] for t in value])
        self.update_tiles()

    def update_tiles(self) -> None:
        """
        Update config with the latest tiles
        """

        self.acquisition.config["acquisition"]["tiles"] = self.create_tile_list()

    def move_stage(self, fov_position: list[float]) -> None:
        """
        pyqtSlot for moving stage when fov_position is changed internally by grid_widget
        :param fov_position: new fov position to move to
        """
        scalar_coord_plane = [x.strip("-") for x in self.coordinate_plane]
        stage_names = {stage.instrument_axis: name for name, stage in self.instrument.tiling_stages.items()}
        # Move stages
        for axis, position in zip(scalar_coord_plane[:2], fov_position[:2]):
            self.instrument.tiling_stages[stage_names[axis]].move_absolute_mm(position, wait=False)
        ((_scan_name, scan_stage),) = self.instrument.scanning_stages.items()
        scan_stage.move_absolute_mm(fov_position[2], wait=False)

    def stop_stage(self) -> None:
        """
        pyqtSlot for stop stage
        """

        for stage in {
            **getattr(self.instrument, "scanning_stages", {}),
            **getattr(self.instrument, "tiling_stages", {}),
        }.values():  # combine stage
            stage.halt()

    def create_operation_widgets(self, device_name: str, operation_name: str, operation_specs: dict) -> None:
        """
        Create widgets based on operation dictionary attributes from instrument or acquisition
         :param operation_name: name of operation
         :param device_name: name of device correlating to operation
         :param operation_specs: dictionary describing set up of operation
        """

        operation_type = operation_specs["type"]
        operation = getattr(self.acquisition, inflection.pluralize(operation_type))[device_name][operation_name]

        specs = self.config["acquisition_view"]["operation_widgets"].get(device_name, {}).get(operation_name, {})
        if specs.get("type", "") == operation_type and "driver" in specs and "module" in specs:
            gui_class = getattr(importlib.import_module(specs["driver"]), specs["module"])
            gui = gui_class(operation, **specs.get("init", {}))  # device gets passed into widget
        else:
            properties = scan_for_properties(operation)
            gui = BaseDeviceWidget(type(operation), properties)  # create label

        # if gui is BaseDeviceWidget or inherits from it
        if isinstance(gui, BaseDeviceWidget):
            # Hook up widgets to device_property_changed
            gui.ValueChangedInside[str].connect(
                lambda value, op=operation, widget=gui: self.operation_property_changed(value, op, widget)
            )

            updating_props = specs.get("updating_properties", [])
            for prop_name in updating_props:
                descriptor = getattr(type(operation), prop_name)
                unit = getattr(descriptor, "unit", None)
                # if operation is percentage, change property widget to QProgressbar
                if unit in ["%", "percent", "percentage"]:
                    widget = getattr(gui, f"{prop_name}_widget")
                    progress_bar = QProgressBar()
                    progress_bar.setMaximum(100)
                    progress_bar.setMinimum(0)
                    widget.parentWidget().layout().replaceWidget(getattr(gui, f"{prop_name}_widget"), progress_bar)
                    widget.deleteLater()
                    setattr(gui, f"{prop_name}_widget", progress_bar)
                if not self.property_worker_factory:
                    raise ValueError("property_worker_factory is required but was not provided")
                worker = self.property_worker_factory(operation, prop_name)
                prop_widget = getattr(gui, f"{prop_name}_widget")
                worker.yielded.connect(lambda args, w=prop_widget: self.update_property_value(args[0], w))
                worker.start()
                worker.pause()  # start and pause, so we can resume when acquisition starts and pause when over
                self.property_workers.append(worker)

        # Add label to gui
        font = QFont()
        font.setBold(True)
        label = QLabel(operation_name)
        label.setFont(font)
        labeled = create_widget("V", label, gui)

        # add ui to widget dictionary
        if not hasattr(self, f"{operation_type}_widgets"):
            setattr(self, f"{operation_type}_widgets", {device_name: {}})
        elif not getattr(self, f"{operation_type}_widgets").get(device_name, False):
            getattr(self, f"{operation_type}_widgets")[device_name] = {}
        getattr(self, f"{operation_type}_widgets")[device_name][operation_name] = labeled

        # TODO: Do we need this?
        for subdevice_name, suboperation_dictionary in operation_specs.get("subdevices", {}).items():
            for (
                suboperation_name,
                suboperation_specs,
            ) in suboperation_dictionary.items():
                self.create_operation_widgets(subdevice_name, suboperation_name, suboperation_specs)

        labeled.setWindowTitle(f"{device_name} {operation_type} {operation_name}")
        labeled.show()

    def update_acquisition_layer(self, image: np.ndarray, camera_name: str) -> None:
        """
        Update the acquisition image layer in the viewer.

        :param image: Image array
        :type image: np.ndarray
        :param camera_name: Camera name
        :type camera_name: str
        """
        # Use parent class callback-based implementation
        if self.update_layer_callback and image is not None:
            self.update_layer_callback(image, camera_name)

    def update_property_value(self, value, widget) -> None:
        """
        Update stage position in stage widget
        :param widget: widget to update
        :param value: value to update with
        """

        try:
            if type(widget) in [QLineEdit, QScrollableLineEdit]:
                widget.setText(str(value))
            elif type(widget) in [
                QSpinBox,
                QDoubleSpinBox,
                QSlider,
                QScrollableFloatSlider,
            ]:
                widget.setValue(value)
            elif isinstance(widget, QComboBox):
                index = widget.findText(value)
                widget.setCurrentIndex(index)
            elif isinstance(widget, QProgressBar):
                widget.setValue(round(value))
        # Pass when window's closed or widget doesn't have position_mm_widget
        except (RuntimeError, AttributeError):
            pass

    @pyqtSlot(str)
    def operation_property_changed(self, attr_name: str, operation: object, widget) -> None:
        """
        pyqtSlot to pyqtSignal when operation widget has been changed
        :param widget: widget object relating to operation
        :param operation: operation object
        :param attr_name: name of attribute
        """

        name_lst = attr_name.split(".")
        self.log.debug(f"widget {attr_name} changed to {getattr(widget, name_lst[0])}")
        value = getattr(widget, name_lst[0])
        try:  # Make sure name is referring to same thing in UI and operation
            dictionary = getattr(operation, name_lst[0])
            for k in name_lst[1:]:
                dictionary = dictionary[k]
            setattr(operation, name_lst[0], value)
            self.log.info(f"Device changed to {getattr(operation, name_lst[0])}")
            # Update ui with new operation values that might have changed
            # WARNING: Infinite recursion might occur if operation property not set correctly
            for k in widget.property_widgets:
                if getattr(widget, k, False):
                    operation_value = getattr(operation, k)
                    setattr(widget, k, operation_value)

        except (KeyError, TypeError) as e:
            self.log.warning(f"{attr_name} can't be mapped into operation properties due to {e}")

    def create_tile_list(self) -> list:
        """
        Return a list of tiles for a scan
        :return: list of tiles
        """

        tiles = []
        tile_slice = slice(self.volume_plan.start, self.volume_plan.stop)
        value = self.volume_plan.value()
        sliced_value = list(value)[tile_slice]
        if self.channel_plan.channel_order.currentText() == "per Tile":
            for tile in sliced_value:
                for ch in self.channel_plan.channels:
                    tiles.append(self.write_tile(ch, tile))
        elif self.channel_plan.channel_order.currentText() == "per Volume":
            for ch in self.channel_plan.channels:
                for tile in sliced_value:
                    tiles.append(self.write_tile(ch, tile))
        return tiles

    def write_tile(self, channel: str, tile) -> dict:
        """
        Write dictionary describing tile parameters
        :param channel: channel the tile is in
        :param tile: tile object
        :return
        """

        row, column = tile.row, tile.col
        table_row = self.volume_plan.tile_table.findItems(str([row, column]), Qt.MatchExactly)[0].row()

        tile_dict = {
            "channel": channel,
            f"position_{self.unit}": {
                k[0]: self.volume_plan.tile_table.item(table_row, j + 1).data(Qt.EditRole)
                for j, k in enumerate(self.volume_plan.table_columns[1:-2])
            },
            "tile_number": table_row,
        }
        # load channel plan values
        for device_type, properties in self.channel_plan.properties.items():
            if device_type in self.channel_plan.possible_channels[channel]:
                for device_name in self.channel_plan.possible_channels[channel][device_type]:
                    tile_dict[device_name] = {}
                    for prop in properties:
                        column_name = label_maker(f"{device_name}_{prop}")
                        if getattr(self.channel_plan, column_name, None) is not None:
                            array = getattr(self.channel_plan, column_name)[channel]
                            input_type = self.channel_plan.column_data_types[column_name]
                            if input_type is not None:
                                tile_dict[device_name][prop] = input_type(array[row, column])
                            else:
                                tile_dict[device_name][prop] = array[row, column]
            else:
                column_name = label_maker(f"{device_type}")
                if getattr(self.channel_plan, column_name, None) is not None:
                    array = getattr(self.channel_plan, column_name)[channel]
                    input_type = self.channel_plan.column_data_types[column_name]
                    if input_type is not None:
                        tile_dict[device_type] = input_type(array[row, column])
                    else:
                        tile_dict[device_type] = array[row, column]

        for name in ["steps", "step_size", "prefix"]:
            array = getattr(self.channel_plan, name)[channel]
            tile_dict[name] = array[row, column]
        return tile_dict

    def closeEvent(self, event) -> None:
        """
        Override close event to hide instead of closing.

        When user clicks X button, window is hidden and can be reopened via toggle button.

        :param event: Close event
        """
        # User clicked X button - just hide the window
        event.ignore()
        self.hide()
        self.windowHidden.emit()
        self.log.info("Acquisition window hidden (not closed)")

    def close(self) -> bool:
        """
        Close operations and end threads.
        """
        # Workers are fully managed by InstrumentView - no local cleanup needed
        for device_name, operation_dictionary in self.acquisition.config["acquisition"]["operations"].items():
            for operation_name, operation_specs in operation_dictionary.items():
                operation_type = operation_specs["type"]
                operation = getattr(self.acquisition, inflection.pluralize(operation_type))[device_name][operation_name]
                try:
                    operation.close()
                except AttributeError:
                    self.log.debug(f"{device_name} {operation_name} does not have close function")
        self.acquisition.close()
        return True
