import time
from collections.abc import Iterator
from datetime import datetime

import numpy as np
from napari.qt.threading import create_worker, thread_worker
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QWidget,
)
from view.acquisition_view import AcquisitionView
from view.widgets.acquisition_widgets.channel_plan_widget import ChannelPlanWidget
from view.widgets.acquisition_widgets.volume_model import VolumeModel
from view.widgets.acquisition_widgets.volume_plan_widget import VolumePlanWidget
from view.widgets.base_device_widget import create_widget


class ExASPIMAcquisitionView(AcquisitionView):
    """Class for handling ExASPIM acquisition view."""

    acquisitionEnded: pyqtSignal = pyqtSignal()
    acquisitionStarted: pyqtSignal = pyqtSignal(datetime)

    def __init__(
        self,
        acquisition: object,
        config: dict,
        save_config_callback=None,
        update_layer_callback=None,
    ):
        """
        Initialize the ExASPIMAcquisitionView object.

        :param acquisition: Acquisition object
        :type acquisition: object
        :param config: Configuration dictionary
        :type config: dict
        :param save_config_callback: Callback function for saving acquisition config
        :type save_config_callback: callable, optional
        :param update_layer_callback: Callback for updating viewer layers
        :type update_layer_callback: callable, optional
        """
        config["acquisition_view"]["unit"] = "mm"
        super().__init__(
            acquisition=acquisition,
            config=config,
            save_config_callback=save_config_callback,
            update_layer_callback=update_layer_callback,
        )
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

        acquisition_widget = QSplitter(Qt.Vertical)
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
        self.volume_plan.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)

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
        table_splitter = QSplitter(Qt.Horizontal)
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
        line.setFrameShape(QFrame.VLine)
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

    @thread_worker
    def grab_property_value(self, device: object, property_name: str, widget) -> Iterator:
        """
        Grab value of property and yield
        :param device: device to grab property from
        :param property_name: name of property to get
        :param widget: corresponding device widget
        :return: value of property and widget to update
        """

        while True:  # best way to do this or have some sort of break?
            time.sleep(1.0)
            value = getattr(device, property_name)
            yield value, widget

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
        for anchor, widget in zip(self.volume_plan.anchor_widgets, self.volume_plan.grid_offset_widgets):
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

    def stop_acquisition(self) -> None:
        """
        Stop the acquisition process.
        """
        self.acquisition_thread.quit()
        self.acquisition.stop_acquisition()

    def acquisition_ended(self) -> None:
        """
        Handle the end of the acquisition process.
        """
        super().acquisition_ended()
        self.acquisitionEnded.emit()

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
