import time
from datetime import datetime
from pathlib import Path
from typing import Iterator

import numpy as np
from napari.qt.threading import thread_worker, create_worker
from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from view.acquisition_view import AcquisitionView
from view.instrument_view import InstrumentView
from view.widgets.acquisition_widgets.channel_plan_widget import ChannelPlanWidget
from view.widgets.acquisition_widgets.volume_model import VolumeModel
from view.widgets.acquisition_widgets.volume_plan_widget import VolumePlanWidget
from view.widgets.base_device_widget import create_widget, disable_button
from voxel.processes.downsample.gpu.gputools.rank_downsample_2d import GPUToolsRankDownSample2D


class ExASPIMInstrumentView(InstrumentView):
    """Class for handling ExASPIM instrument view."""

    def __init__(self, instrument: object, config_path: Path, log_level: str = "INFO"):
        """
        Initialize the ExASPIMInstrumentView object.

        :param instrument: Instrument object
        :type instrument: object
        :param config_path: Configuration path
        :type config_path: Path
        :param log_level: Logging level, defaults to "INFO"
        :type log_level: str, optional
        """
        self.flip_mount_widgets = {}
        super().__init__(instrument, config_path, log_level)
        # other setup taken care of in base instrumentview class
        self.setup_flip_mount_widgets()

        # viewer constants for ExA-SPIM
        self.viewer.title = "ExA-SPIM control"
        self.intensity_min = self.config["instrument_view"]["properties"]["intensity_min"]
        if self.intensity_min < 0 or self.intensity_min > 65535:
            raise ValueError("intensity min must be between 0 and 65535")
        self.intensity_max = self.config["instrument_view"]["properties"]["intensity_max"]
        if self.intensity_max < self.intensity_min or self.intensity_max > 65535:
            raise ValueError("intensity max must be between intensity min and 65535")
        self.camera_rotation = self.config["instrument_view"]["properties"]["camera_rotation_deg"]
        if self.camera_rotation not in [0, 90, 180, 270, 360, -90, -180, -270]:
            raise ValueError("camera rotation must be 0, 90, 180, 270, -90, -180, -270")
        self.resolution_levels = self.config["instrument_view"]["properties"]["resolution_levels"]
        if self.resolution_levels < 1 or self.resolution_levels > 10:
            raise ValueError("resolution levels must be between 1 and 10")
        self.alignment_roi_size = self.config["instrument_view"]["properties"]["alignment_roi_size"]
        if self.alignment_roi_size < 2 or self.alignment_roi_size > 1024:
            raise ValueError("alignment roi size must be between 2 and 1024")
        self.viewer.scale_bar.visible = True
        self.viewer.scale_bar.unit = "um"
        self.viewer.scale_bar.position = "bottom_left"
        self.viewer.text_overlay.visible = True
        self.viewer.window._qt_viewer.canvas._scene_canvas.measure_fps(callback=self.update_fps)
        self.downsampler = GPUToolsRankDownSample2D(binning=2, rank=-2, data_type="uint16")

    def setup_camera_widgets(self) -> None:
        """
        Set up camera widgets.
        """
        for camera_name, camera_widget in self.camera_widgets.items():

            # Add functionality to snapshot button
            snapshot_button = getattr(camera_widget, "snapshot_button", QPushButton())
            snapshot_button.pressed.connect(
                lambda button=snapshot_button: disable_button(button)
            )  # disable to avoid spamming
            snapshot_button.pressed.connect(lambda camera=camera_name: self.setup_live(camera, 1))

            # Add functionality to live button
            live_button = getattr(camera_widget, "live_button", QPushButton())
            live_button.pressed.connect(lambda button=live_button: disable_button(button))  # disable to avoid spamming
            live_button.pressed.connect(lambda camera=camera_name: self.setup_live(camera))
            live_button.pressed.connect(lambda camera=camera_name: self.toggle_live_button(camera))

            # Add functionality to the edges button
            self.alignment_button = getattr(camera_widget, "alignment_button", QPushButton())
            self.alignment_button.setCheckable(True)
            self.alignment_button.released.connect(self.enable_alignment_mode)

            # Add functionality to the crosshairs button
            self.crosshairs_button = getattr(camera_widget, "crosshairs_button", QPushButton())
            self.crosshairs_button.setCheckable(True)

        stacked = self.stack_device_widgets("camera")
        self.viewer.window.add_dock_widget(stacked, area="right", name="Cameras", add_vertical_stretch=False)

    def setup_filter_wheel_widgets(self) -> None:
        """
        Set up filter wheel widgets.
        """
        stacked = self.stack_device_widgets("filter_wheel")
        self.viewer.window.add_dock_widget(stacked, area="right", name="Filter Wheels")

    def setup_stage_widgets(self) -> None:
        """
        Set up stage widgets.
        """
        stage_widgets = []
        for name, widget in {
            **self.tiling_stage_widgets,
            **self.scanning_stage_widgets,
            **self.focusing_stage_widgets,
        }.items():
            label = QLabel()
            layout = QVBoxLayout()
            layout.addWidget(create_widget("H", label, widget))
            stage_widgets.append(layout)

        stage_axes_widget = create_widget("V", *stage_widgets)
        stage_axes_widget.setContentsMargins(0, 0, 0, 0)
        stage_axes_widget.layout().setSpacing(6)

        stage_scroll = QScrollArea()
        stage_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        stage_scroll.setWidget(stage_axes_widget)
        self.viewer.window.add_dock_widget(stage_axes_widget, area="left", name="Stages")

    def setup_flip_mount_widgets(self) -> None:
        """
        Set up flip mount widgets.
        """
        stacked = self.stack_device_widgets("flip_mount")
        self.viewer.window.add_dock_widget(stacked, area="right", name="Flip Mounts")

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
        laser_widget = create_widget("V", *laser_widgets)
        laser_widget.layout().setSpacing(12)
        self.viewer.window.add_dock_widget(laser_widget, area="bottom", name="Lasers")

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
        laser_combo_box.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        laser_combo_box.setCurrentIndex(0)  # initialize to first channel index
        self.livestream_channel = laser_combo_box.currentText()  # initialize livestream channel
        layout.addWidget(label)
        layout.addWidget(laser_combo_box)
        widget.setLayout(layout)
        widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)
        self.viewer.window.add_dock_widget(widget, area="bottom", name="Channels")

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
        for filter in self.channels[self.livestream_channel].get("filters", []):
            self.log.info(f"Enabling filter {filter}")
            self.instrument.filters[filter].enable()

    def update_fps(self, fps: float) -> None:
        """
        Update the frames per second (FPS) display.

        :param fps: Frames per second
        :type fps: float
        """
        self.viewer.text_overlay.text = f"{fps:1.1f} fps"

    def update_layer(self, args: tuple, snapshot: bool = False) -> None:
        """
        Update the image layer in the viewer.

        :param args: Tuple containing image and camera name
        :type args: tuple
        :param snapshot: Whether the image is a snapshot, defaults to False
        :type snapshot: bool, optional
        """

        (image, camera_name) = args

        # calculate centroid of image
        pixel_size_um = self.instrument.cameras[camera_name].sampling_um_px
        y_center_um = image.shape[0] // 2 * pixel_size_um
        x_center_um = image.shape[1] // 2 * pixel_size_um

        if image is not None:
            _ = self.viewer.layers
            # add crosshairs to image
            if self.crosshairs_button.isChecked():
                image[image.shape[0] // 2 - 1 : image.shape[0] // 2 + 1, :] = 1 << 16 - 1
                image[:, image.shape[1] // 2 - 1 : image.shape[1] // 2 + 1] = 1 << 16 - 1
            multiscale = [image]
            for binning in range(1, self.resolution_levels):
                # downsampled_frame = self.downsampler.run(multiscale[-1])
                downsampled_frame = multiscale[-1][::2, ::2]
                # add crosshairs to image
                if self.crosshairs_button.isChecked():
                    downsampled_frame[downsampled_frame.shape[0] // 2 - 1 : downsampled_frame.shape[0] // 2 + 1, :] = (
                        1 << 16 - 1
                    )
                    downsampled_frame[:, downsampled_frame.shape[1] // 2 - 1 : downsampled_frame.shape[1] // 2 + 1] = (
                        1 << 16 - 1
                    )
                multiscale.append(downsampled_frame)
            layer_name = (
                f"{camera_name} {self.livestream_channel}"
                if not snapshot
                else f"{camera_name} {self.livestream_channel} snapshot"
            )
            if layer_name in self.viewer.layers and not snapshot:
                layer = self.viewer.layers[layer_name]
                layer.data = multiscale
                layer.scale = (pixel_size_um, pixel_size_um)
                layer.translate = (-x_center_um, y_center_um)
            else:
                # Add image to a new layer if layer doesn't exist yet or image is snapshot
                layer = self.viewer.add_image(
                    multiscale,
                    name=layer_name,
                    contrast_limits=(self.intensity_min, self.intensity_max),
                    scale=(pixel_size_um, pixel_size_um),
                    translate=(-x_center_um, y_center_um),
                    rotate=self.camera_rotation,
                )
                layer.mouse_drag_callbacks.append(self.save_image)
                if snapshot:  # emit signal if snapshot
                    self.snapshotTaken.emit(np.rot90(multiscale[-3], k=2), layer.contrast_limits)
                    layer.events.contrast_limits.connect(
                        lambda event: self.contrastChanged.emit(np.rot90(layer.data[-3], k=2), layer.contrast_limits)
                    )

    def dissect_image(self, args: tuple) -> None:
        """
        Dissect the image and add to the viewer.

        :param args: Tuple containing image and camera name
        :type args: tuple
        """
        (image, camera_name) = args

        # calculate centroid of image
        pixel_size_um = self.instrument.cameras[camera_name].sampling_um_px
        y_center_um = image.shape[0] // 2 * pixel_size_um
        x_center_um = image.shape[1] // 2 * pixel_size_um

        if image is not None:
            # Dissect image and add to viewer
            alignment_roi = self.alignment_roi_size
            combined_roi = np.zeros((alignment_roi * 3, alignment_roi * 3))
            # top left corner
            top_left = image[0:alignment_roi, 0:alignment_roi]
            combined_roi[0:alignment_roi, 0:alignment_roi] = top_left
            # top right corner
            top_right = image[0:alignment_roi, -alignment_roi:]
            combined_roi[0:alignment_roi, alignment_roi * 2 : alignment_roi * 3] = top_right
            # bottom left corner
            bottom_left = image[-alignment_roi:, 0:alignment_roi]
            combined_roi[alignment_roi * 2 : alignment_roi * 3, 0:alignment_roi] = bottom_left
            # bottom right corner
            bottom_right = image[-alignment_roi:, -alignment_roi:]
            combined_roi[alignment_roi * 2 : alignment_roi * 3, alignment_roi * 2 : alignment_roi * 3] = bottom_right
            # center left
            center_left = image[
                round((image.shape[0] / 2) - alignment_roi / 2) : round((image.shape[0] / 2) + alignment_roi / 2),
                0:alignment_roi,
            ]
            combined_roi[alignment_roi : alignment_roi * 2, 0:alignment_roi] = center_left
            # center right
            center_right = image[
                round((image.shape[0] / 2) - alignment_roi / 2) : round((image.shape[0] / 2) + alignment_roi / 2),
                -alignment_roi:,
            ]
            combined_roi[alignment_roi : alignment_roi * 2, alignment_roi * 2 : alignment_roi * 3] = center_right
            # center top
            center_top = image[
                0:alignment_roi,
                round((image.shape[1] / 2) - alignment_roi / 2) : round((image.shape[1] / 2) + alignment_roi / 2),
            ]
            combined_roi[0:alignment_roi, alignment_roi : alignment_roi * 2] = center_top
            # center bottom
            center_bottom = image[
                -alignment_roi:,
                round((image.shape[1] / 2) - alignment_roi / 2) : round((image.shape[1] / 2) + alignment_roi / 2),
            ]
            combined_roi[alignment_roi * 2 : alignment_roi * 3, alignment_roi : alignment_roi * 2] = center_bottom
            # center roi
            center = image[
                round((image.shape[0] / 2) - alignment_roi / 2) : round((image.shape[0] / 2) + alignment_roi / 2),
                round((image.shape[1] / 2) - alignment_roi / 2) : round((image.shape[1] / 2) + alignment_roi / 2),
            ]
            combined_roi[alignment_roi : alignment_roi * 2, alignment_roi : alignment_roi * 2] = center

            # add crosshairs to image
            combined_roi[alignment_roi - 2 : alignment_roi + 2, :] = 1 << 16 - 1
            combined_roi[alignment_roi * 2 - 2 : alignment_roi * 2 + 2, :] = 1 << 16 - 1
            combined_roi[:, alignment_roi - 2 : alignment_roi + 2] = 1 << 16 - 1
            combined_roi[:, alignment_roi * 2 - 2 : alignment_roi * 2 + 2] = 1 << 16 - 1

            layer_name = f"{camera_name} {self.livestream_channel} Alignment"
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

    def dismantle_live(self, camera_name: str) -> None:
        """
        Dismantle live view for the specified camera.

        :param camera_name: Camera name
        :type camera_name: str
        """
        self.instrument.cameras[camera_name].abort()
        for _, daq in self.instrument.daqs.items():
            # wait for daq tasks to finish - prevents devices from stopping in
            # unsafe state, i.e. lasers still on
            daq.co_task.stop()
            # sleep to allow last ao to play with 10% buffer
            time.sleep(1.0 / daq.co_frequency_hz * 1.1)
            # stop the ao task
            daq.ao_task.stop()
            # close the tasks
            daq.co_task.close()
            daq.ao_task.close()


class ExASPIMAcquisitionView(AcquisitionView):
    """Class for handling ExASPIM acquisition view."""

    acquisitionEnded = Signal()
    acquisitionStarted = Signal((datetime,))

    def __init__(self, acquisition: object, instrument_view: ExASPIMInstrumentView):
        """
        Initialize the ExASPIMAcquisitionView object.

        :param acquisition: Acquisition object
        :type acquisition: object
        :param instrument_view: Instrument view object
        :type instrument_view: ExASPIMInstrumentView
        """
        instrument_view.config["acquisition_view"]["unit"] = "mm"
        super().__init__(acquisition=acquisition, instrument_view=instrument_view)
        # acquisition view constants for ExA-SPIM
        self.binning_levels = 2
        self.acquisition_thread = create_worker(self.acquisition.run)
        self.setWindowTitle("ExA-SPIM control")

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
        for name, stage in self.instrument.tiling_stages.items():
            lim_dict.update({f"{stage.instrument_axis}": stage.limits_mm})
        # last axis should be scanning axis
        ((scan_name, scan_stage),) = self.instrument.scanning_stages.items()
        lim_dict.update({f"{scan_stage.instrument_axis}": scan_stage.limits_mm})
        try:
            limits = [lim_dict[x.strip("-")] for x in self.coordinate_plane]
        except KeyError:
            raise KeyError("Coordinate plane must match instrument axes in tiling_stages")

        # TODO fix this, messy way to figure out FOV dimensions from camera properties
        first_camera_key = list(self.instrument.cameras.keys())[0]
        camera = self.instrument.cameras[first_camera_key]
        fov_height_mm = camera.fov_height_mm
        fov_width_mm = camera.fov_width_mm
        camera_rotation = (
            self.config["instrument_view"]["properties"]["camera_rotation_deg"]
            if "camera_rotation_deg" in self.config["instrument_view"]["properties"]
            else 0
        )
        if camera_rotation in [-270, -90, 90, 270]:
            fov_dimensions = [fov_height_mm, fov_width_mm, 0]
        else:
            fov_dimensions = [fov_width_mm, fov_height_mm, 0]

        acquisition_widget = QSplitter(Qt.Vertical)
        acquisition_widget.setChildrenCollapsible(False)

        # create volume plan
        self.volume_plan = VolumePlanWidget(
            limits=limits,
            fov_dimensions=fov_dimensions,
            coordinate_plane=self.coordinate_plane,
            unit=self.unit,
            default_overlap=(
                self.config["acquisition_view"]["default_overlap"]
                if "default_overlap" in self.config["acquisition_view"]
                else 15.0
            ),
            default_order=(
                self.config["acquisition_view"]["default_tile_order"]
                if "default_tile_order" in self.config["acquisition_view"]
                else "row_wise"
            ),
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
            instrument_view=self.instrument_view,
            channels=self.instrument.config["instrument"]["channels"],
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
        self.instrument_view.snapshotTaken.connect(self.volume_model.add_fov_image)  # connect snapshot signal
        self.instrument_view.contrastChanged.connect(
            self.volume_model.adjust_glimage_contrast
        )  # connect snapshot adjusted
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

        if image is not None:

            for binning in range(0, self.binning_levels):
                image = self.instrument_view.downsampler.run(image)

            # calculate centroid of image
            pixel_size_um = self.instrument.cameras[camera_name].sampling_um_px * 2**self.binning_levels
            y_center_um = image.shape[0] // 2 * pixel_size_um
            x_center_um = image.shape[1] // 2 * pixel_size_um

            layer_name = f"{camera_name} acquisition"
            if layer_name in self.instrument_view.viewer.layers:
                layer = self.instrument_view.viewer.layers[layer_name]
                layer.data = image
                layer.scale = (pixel_size_um, pixel_size_um)
                layer.translate = (-x_center_um, y_center_um)
            else:
                layer = self.instrument_view.viewer.add_image(
                    image,
                    name=layer_name,
                    contrast_limits=(self.instrument_view.intensity_min, self.instrument_view.intensity_max),
                    scale=(pixel_size_um, pixel_size_um),
                    translate=(-x_center_um, y_center_um),
                    rotate=self.instrument_view.camera_rotation,
                )

    def start_acquisition(self) -> None:
        """
        Start acquisition and disable widgets
        """

        # add tiles to acquisition config
        self.update_tiles()

        if self.instrument_view.grab_frames_worker.is_running:  # stop livestream if running
            self.instrument_view.grab_frames_worker.quit()

        # write correct daq values if different from livestream
        for daq_name, daq in self.instrument.daqs.items():
            if daq_name in self.config["acquisition_view"].get("data_acquisition_tasks", {}).keys():
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
        # disable instrument view
        self.instrument_view.setDisabled(True)

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
