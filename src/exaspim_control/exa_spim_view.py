import time
from datetime import datetime
from pathlib import Path
from typing import Iterator
import ruamel
import numpy as np
import inflection
from napari.qt.threading import thread_worker, create_worker
from napari.utils.events import Event
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
from qtpy.QtWidgets import QMessageBox
from qtpy.QtWidgets import QInputDialog
from qtpy.QtWidgets import QDialog, QDialogButtonBox

class TileCheckDialog(QDialog):
    def __init__(self, parent, tile_messages: list[str]):
        super().__init__(parent)

        self.tile_messages = tile_messages
        self.tile_index = 0

        self.setWindowTitle("Confirm ETL offsets and focus positions")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        self.label = QLabel()
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.label)

        nav_layout = QHBoxLayout()

        self.previous_button = QPushButton("← Previous")
        self.next_button = QPushButton("Next →")

        self.previous_button.clicked.connect(self.previous_tile)
        self.next_button.clicked.connect(self.next_tile)

        nav_layout.addWidget(self.previous_button)
        nav_layout.addWidget(self.next_button)

        layout.addLayout(nav_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Yes | QDialogButtonBox.No)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.update_tile_display()

    def update_tile_display(self):
        self.label.setText(
            f"Tile {self.tile_index + 1} of {len(self.tile_messages)}\n\n"
            f"{self.tile_messages[self.tile_index]}"
        )

        self.previous_button.setEnabled(self.tile_index > 0)
        self.next_button.setEnabled(self.tile_index < len(self.tile_messages) - 1)

    def previous_tile(self):
        if self.tile_index > 0:
            self.tile_index -= 1
            self.update_tile_display()

    def next_tile(self):
        if self.tile_index < len(self.tile_messages) - 1:
            self.tile_index += 1
            self.update_tile_display()


class NonAliasingRTRepresenter(ruamel.yaml.RoundTripRepresenter):
    """
    Custom representer for ruamel.yaml to ignore aliases.
    This class is used to ensure that YAML files do not contain aliases,
    which can cause issues with certain YAML parsers.
    It overrides the `ignore_aliases` method to always return True.
    This prevents ruamel.yaml from creating aliases for any data structures
    that it represents.

    :param ruamel: ruamel.yaml.RoundTripRepresenter
    :type ruamel: ruamel.yaml.RoundTripRepresenter
    """

    def ignore_aliases(self, data):
        return True


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

        # setup and connect viewer camera events
        self.viewer.window.qt_viewer.view.camera.reset()
        self.viewer_state = self.viewer.window.qt_viewer.view.camera.get_state()
        self.previous_layer = None
        self.viewer.camera.events.zoom.connect(self.camera_zoom)
        self.viewer.camera.events.center.connect(self.camera_position)

        # create cache for contrast limit values
        self.contrast_limits = dict()
        for key in self.channels.keys():
            self.contrast_limits[key] = [self.intensity_min, self.intensity_max]
        
        # initialize idle voltages from daq
        # self.instrument.daqs[list(self.instrument.daqs.keys())[0]].set_idle_voltages(self.livestream_channel)

    def setup_camera_widgets(self) -> None:
        """
        Set up camera widgets.
        """
        for camera_name, camera_widget in self.camera_widgets.items():

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

            # Add functionality to the edges button
            self.alignment_button = getattr(camera_widget, "alignment_button", QPushButton())
            self.alignment_button.setCheckable(True)
            self.alignment_button.released.connect(self.enable_alignment_mode)

            # Add functionality to the crosshairs button
            self.crosshairs_button = getattr(camera_widget, "crosshairs_button", QPushButton())
            self.crosshairs_button.setCheckable(True)

            self.alignment_button.setDisabled(True)  # disable alignment button
            self.crosshairs_button.setDisabled(True)  # disable crosshairs button

        stacked = self.stack_device_widgets("camera")
        self.viewer.window.add_dock_widget(stacked, area="right", name="Cameras", add_vertical_stretch=False)

    def setup_filter_wheel_widgets(self) -> None:
        """
        Set up filter wheel widgets.
        """
        stacked = self.stack_device_widgets("filter_wheel")
        self.filter_wheel_widget = stacked
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
        self.laser_widget = create_widget("V", *laser_widgets)
        self.laser_widget.layout().setSpacing(12)
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
        laser_combo_box.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        laser_combo_box.setCurrentIndex(0)  # initialize to first channel index
        self.laser_combo_box = laser_combo_box
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

    @thread_worker
    def grab_frames(self, camera_name: str, frames=float("inf")) -> Iterator[tuple[np.ndarray, str]]:
        """
        Grab frames from camera
        :param frames: how many frames to take
        :param camera_name: name of camera
        """

        i = 0
        while i < frames:  # while loop since frames can == inf
            time.sleep(0.5)
            multiscale = [self.instrument.cameras[camera_name].grab_frame()]
            for binning in range(1, self.resolution_levels):
                downsampled_frame = multiscale[-1][::2, ::2]
                multiscale.append(downsampled_frame)
            yield multiscale, camera_name
            i += 1

    def camera_position(self, event: Event):
        # store viewer state anytime camera moves and there is a layer
        if self.previous_layer in self.viewer.layers:
            self.viewer_state = self.viewer.window.qt_viewer.view.camera.get_state()

    def camera_zoom(self, event: Event):
        # store viewer state anytime camera zooms and there is a layer
        if self.previous_layer in self.viewer.layers:
            self.viewer_state = self.viewer.window.qt_viewer.view.camera.get_state()

    def viewer_contrast_limits(self, event: Event):
        # store viewer contrast limits anytime contrast limits change
        self.contrast_limits[self.livestream_channel] = self.viewer.layers[self.livestream_channel].contrast_limits

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
                    # only reset state if there is a previous layer, otherwise pass
                    if self.previous_layer:
                        self.viewer_state = self.viewer.window.qt_viewer.view.camera.set_state(self.viewer_state)
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
        Dissect the image and add to the viewer.

        :param args: Tuple containing image and camera name
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
                image = layer.data[0] if layer.multiscale else image.data
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
        self.instrument.cameras[camera_name].start(frames)

        for laser in self.channels[self.livestream_channel].get("lasers", []):
            self.log.info(f"Enabling laser {laser}")
            self.instrument.lasers[laser].enable()
            for child in self.laser_widget.children()[1::]:  # skip first child widget
                laser_name = child.children()[1].text()  # first child is label widget
                if laser != laser_name:
                    child.setDisabled(True)
                    child.children()[2].setDisabled(True)

        for filter in self.channels[self.livestream_channel].get("filters", []):
            self.log.info(f"Enabling filter {filter}")
            self.instrument.filters[filter].enable()

        # TODO fix this, messy way to figure out FOV dimensions from camera properties
        if hasattr(self.instrument, "indicator_lights"):
            first_indicator_light_key = list(self.instrument.indicator_lights.keys())[0]
            self.instrument.indicator_lights[first_indicator_light_key].enable()

        for daq_name, daq in self.instrument.daqs.items():
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

        self.filter_wheel_widget.setDisabled(True)  # disable filter wheel widget
        self.laser_combo_box.setDisabled(True)  # disable channel widget
        self.alignment_button.setDisabled(False)  # enable alignment button
        self.crosshairs_button.setDisabled(False)  # enable crosshairs button
        self.snapshot_button.setDisabled(True)  # disable crosshairs button

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
            # daq.set_idle_voltages(self.livestream_channel)

        for laser in self.channels[self.livestream_channel].get("lasers", []):
            for child in self.laser_widget.children()[1::]:  # skip first child widget
                laser_name = child.children()[1].text()  # first child is label widget
                if laser != laser_name:
                    child.setDisabled(False)
                    child.children()[2].setDisabled(False)

        # TODO fix this, messy way to figure out FOV dimensions from camera properties
        if hasattr(self.instrument, "indicator_lights"):
            first_indicator_light_key = list(self.instrument.indicator_lights.keys())[0]
            self.instrument.indicator_lights[first_indicator_light_key].disable()

        self.filter_wheel_widget.setDisabled(False)  # enable filter wheel widget
        self.laser_combo_box.setDisabled(False)
        self.alignment_button.setDisabled(True)  # disable alignment button
        self.alignment_button.setChecked(False)
        self.crosshairs_button.setDisabled(True)  # disable crosshairs button
        self.crosshairs_button.setChecked(False)
        self.snapshot_button.setDisabled(False)  # enable crosshairs button

    def close(self) -> None:
        """
        Close instruments and end threads
        """

        for worker in self.property_workers:
            worker.quit()
            while worker.is_running:
                time.sleep(0.1)
        for worker in self.property_workers:
            while worker.is_running:
                time.sleep(0.1)
        self.grab_frames_worker.quit()
        while self.grab_frames_worker.is_running:
            time.sleep(0.1)
        for device_name, device_specs in self.instrument.config["instrument"]["devices"].items():
            device_type = device_specs["type"]
            device = getattr(self.instrument, inflection.pluralize(device_type))[device_name]
            try:
                device.close()
            except AttributeError:
                self.log.debug(f"{device_name} does not have close function")
        self.instrument.close()


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
        # Eventual threads
        self.grab_frames_worker = create_worker(lambda: None)  # dummy thread
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
            instrument=self.instrument,
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

            # for binning in range(0, self.binning_levels):
            #     image = self.instrument_view.downsampler.run(image)

            # calculate centroid of image
            pixel_size_um = self.instrument.cameras[camera_name].sampling_um_px
            y_center_um = image.shape[0] // 2 * pixel_size_um
            x_center_um = image.shape[1] // 2 * pixel_size_um

            layer_name = f"acquisition"
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

    def save_acquisition(self) -> None:
        """
        Save a tile configuration to a YAML file.
        """

        # create YAML handler with non-aliasing representer
        yaml = ruamel.yaml.YAML()
        yaml.Representer = NonAliasingRTRepresenter

        # save daq tasks to config
        daq = self.instrument.daqs[list(self.instrument.daqs.keys())[0]]
        self.acquisition.config["acquisition"]["daq"] = daq.tasks

        # save the tile configuration to the YAML file
        with open(f"{self.acquisition.metadata.acquisition_name}_tiles.yaml", "w") as file:
            yaml.dump(self.acquisition.config, file)

    def start_acquisition(self) -> None:
        """
        Start acquisition and disable widgets
        """

        if not self.brain_orientation_selected():
            return
        if not self.chamber_immersion_selected():
            return
        if not self.experimenter_selected():
            return
        if not self.subject_id_selected():
            return
        # if not self.round_z_mm_check():
        #     return
        # if not self.filter_check():
        #     return
        # if not self.step_size_check():
        #     return
        # if not self.laser_power_check():
        #     return
        # if not self.flip_mount_check():
        #     return
        # if not self.file_transfer_check():
        #     return
        # if not self.etl_and_focus_check():
        #     return
        
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

    def brain_orientation_selected(self) -> bool:
        orientation = getattr(self.acquisition.metadata, "brain_orientation", None)

        if orientation is None or orientation == "":
            QMessageBox.warning(
                self,
                "Brain orientation required",
                "Please select a brain orientation before starting acquisition.",
            )
            return False

        return True

    def chamber_immersion_selected(self) -> bool:
        chamber_immersion = getattr(self.acquisition.metadata, "chamber_immersion", None)

        if chamber_immersion["medium"] is "None" or chamber_immersion["medium"] == "None":
            QMessageBox.warning(
                self,
                "Chamber immersion medium required",
                "Please select a chamber immersion medium before starting acquisition.",
            )
            return False

        return True

    def experimenter_selected(self) -> bool:
        experimenter = getattr(self.acquisition.metadata, "experimenter_full_name", "None")

        if experimenter is "None" or experimenter == "None":
            QMessageBox.warning(
                self,
                "Experimenter full name required",
                "Please select an experimenter full name before starting acquisition.",
            )
            return False

        return True

    def subject_id_selected(self) -> bool:
        subject_id = getattr(self.acquisition.metadata, "subject_id", "None")
        if subject_id is "None" or subject_id == "None":
            QMessageBox.warning(
                self,
                "Subject ID required",
                "Please select a subject ID before starting acquisition.",
            )
            return False

        return True

    def round_z_mm_check(self) -> bool:
        camera, camera_name = self.acquisition._grab_first(
            self.instrument.cameras
        )

        binning = int(camera.binning)

        expected_round_z_by_binning = {
            1: 2048,
            2: 1024,
            4: 512,
            8: 256,
        }

        if binning not in expected_round_z_by_binning:
            return True

        expected_round_z_mm = expected_round_z_by_binning[binning]

        incorrect_tiles = []

        for tile_index, tile in enumerate(
            self.acquisition.config["acquisition"]["tiles"],
            start=1,
        ):
            round_z_mm = int(tile["round_z_mm"])

            if round_z_mm != expected_round_z_mm:
                incorrect_tiles.append(
                    (tile_index, tile, round_z_mm)
                )

        if not incorrect_tiles:
            return True

        tile_text = "\n".join(
            [
                f"Tile {tile_index}: {current_value} → {expected_round_z_mm}"
                for tile_index, tile, current_value in incorrect_tiles
            ]
        )

        response = QMessageBox.question(
            self,
            "Incorrect round_z_mm values detected",
            (
                f"Camera binning is set to {binning}.\n\n"
                f"The following tiles have incorrect round_z_mm values:\n\n"
                f"{tile_text}\n\n"
                f"Would you like to automatically update them?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if response == QMessageBox.No:
            return False

        for tile_index, tile, current_value in incorrect_tiles:
            tile["round_z_mm"] = expected_round_z_mm

            self.log.info(
                f"[round_z_mm corrected] "
                f"Tile {tile_index}: "
                f"{current_value} -> {expected_round_z_mm}"
            )

        return True

    def filter_check(self) -> bool:
        required_filters_by_channel = {
            "488": "LP488",
            "561": "BP620/50",
        }

        incorrect_tiles = []

        for tile_index, tile in enumerate(
            self.acquisition.config["acquisition"]["tiles"],
            start=1,
        ):
            channel = str(tile["channel"])

            if channel not in required_filters_by_channel:
                continue

            required_filter = required_filters_by_channel[channel]

            filter_key = None
            filter_value = None

            # Find the filter wheel entry in the tile dictionary.
            for key, value in tile.items():
                if "filter" in key.lower():
                    filter_key = key
                    filter_value = value
                    break

            if filter_value != required_filter and filter_value is not None:
                incorrect_tiles.append(
                    (
                        tile_index,
                        tile,
                        filter_key,
                        filter_value,
                        required_filter,
                    )
                )

        if not incorrect_tiles:
            return True

        tile_text = "\n".join(
            [
                (
                    f"Tile {tile_index}: "
                    f"{current_value} → {required_filter}"
                )
                for (
                    tile_index,
                    tile,
                    filter_key,
                    current_value,
                    required_filter,
                ) in incorrect_tiles
            ]
        )

        response = QMessageBox.question(
            self,
            "Potentially incorrect filter selection detected",
            (
                "Some channels have potentially incorrect filter selections.\n\n"
                "The following tiles may have incorrect filters:\n\n"
                f"{tile_text}\n\n"
                "Would you like to automatically update them?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if response == QMessageBox.No:
            return False

        for (
            tile_index,
            tile,
            filter_key,
            current_value,
            required_filter,
        ) in incorrect_tiles:

            if filter_key is not None:
                tile[filter_key] = required_filter

            self.log.info(
                f"[filter corrected] "
                f"Tile {tile_index}: "
                f"{current_value} -> {required_filter}"
            )

        return True

    def step_size_check(self) -> bool:
        camera, camera_name = self.acquisition._grab_first(
            self.instrument.cameras
        )

        binning = int(camera.binning)

        default_step_size = self.config["acquisition_view"]['acquisition_widgets']["channel_plan"]["init"]["properties"]["default_step_size"]

        required_step_size_by_binning = {
            1: default_step_size,
            2: 2 * default_step_size,
            4: 4 * default_step_size,
            8: 8 * default_step_size,
        }

        if binning not in required_step_size_by_binning:
            return True

        required_step_size = required_step_size_by_binning[binning]

        incorrect_tiles = []

        for tile_index, tile in enumerate(
            self.acquisition.config["acquisition"]["tiles"],
            start=1,
        ):
            current_step_size = float(tile["step_size"])

            if current_step_size != required_step_size:
                incorrect_tiles.append(
                    (
                        tile_index,
                        tile,
                        current_step_size,
                    )
                )

        if not incorrect_tiles:
            return True

        tile_text = "\n".join(
            [
                (
                    f"Tile {tile_index}: "
                    f"{current_value} → {required_step_size}"
                )
                for (
                    tile_index,
                    tile,
                    current_value,
                ) in incorrect_tiles
            ]
        )

        response = QMessageBox.question(
            self,
            "Incorrect step size detected",
            (
                f"Camera binning is set to {binning}.\n\n"
                f"The following tiles may have incorrect step sizes:\n\n"
                f"{tile_text}\n\n"
                f"Would you like to automatically update them?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if response == QMessageBox.No:
            return False

        for (
            tile_index,
            tile,
            current_value,
        ) in incorrect_tiles:

            tile["step_size"] = required_step_size

            self.log.info(
                f"[step_size corrected] "
                f"Tile {tile_index}: "
                f"{current_value} -> {required_step_size}"
            )

        return True

    def laser_power_check(self) -> bool:
        camera, camera_name = self.acquisition._grab_first(self.instrument.cameras)
        binning = int(camera.binning)

        incorrect_tiles = []

        for tile_index, tile in enumerate(
            self.acquisition.config["acquisition"]["tiles"],
            start=1,
        ):
            channel = str(tile["channel"])

            channel_config = self.instrument.channels[channel]
            laser_names = channel_config.get("lasers", [])

            if len(laser_names) == 0:
                continue

            laser_name = laser_names[0]
            laser = self.instrument.lasers[laser_name]
            max_laser_power = float(laser.max_power)

            for key, value in tile.items():
                laser_power = None
                laser_power_key = None

                # Case 1: scalar tile entry, e.g. tile["laser_power"] = 1000
                if not isinstance(value, dict):
                    key_lower = key.lower()

                    if "laser" in key_lower and "power" in key_lower:
                        try:
                            laser_power = float(value)
                            laser_power_key = key
                        except (TypeError, ValueError):
                            continue

                # Case 2: nested device dictionary,
                # e.g. tile["488nm_laser"]["power_setpoint_mw"] = 1000
                else:
                    for nested_key, nested_value in value.items():
                        if nested_key == "power_setpoint_mw":
                            try:
                                laser_power = float(nested_value)
                                laser_power_key = (key, nested_key)
                            except (TypeError, ValueError):
                                continue

                if laser_power is None:
                    continue

                if binning == 1 and laser_power != max_laser_power:
                    incorrect_tiles.append(
                        (
                            tile_index,
                            tile,
                            laser_power_key,
                            laser_power,
                            max_laser_power,
                            "binning_1",
                        )
                    )

                elif binning > 1 and laser_power >= max_laser_power:
                    incorrect_tiles.append(
                        (
                            tile_index,
                            tile,
                            laser_power_key,
                            laser_power,
                            max_laser_power,
                            "binning_gt_1",
                        )
                    )

        if not incorrect_tiles:
            return True

        tile_text = "\n".join(
            [
                (
                    f"Tile {tile_index}: "
                    f"{laser_power_key} = {current_value}, "
                    f"max = {max_laser_power}"
                )
                for (
                    tile_index,
                    tile,
                    laser_power_key,
                    current_value,
                    max_laser_power,
                    mode,
                ) in incorrect_tiles
            ]
        )

        first_mode = incorrect_tiles[0][5]
        first_current_value = incorrect_tiles[0][3]
        first_max_laser_power = incorrect_tiles[0][4]

        if first_mode == "binning_1":
            title = "Laser power differs from max power"
            message = (
                "Camera binning is set to 1.\n\n"
                "The following laser powers are not set to their channel laser max power:\n\n"
                f"{tile_text}\n\n"
                "Do you want to continue with a non-max laser power?"
            )

            desired_power, ok = QInputDialog.getDouble(
                self,
                title,
                message + "\n\nEnter desired laser power:",
                first_current_value,
                0,
                first_max_laser_power,
                2,
            )

        else:
            title = "Laser power should be below max power"
            message = (
                f"Camera binning is set to {binning}.\n\n"
                "For binning > 1, laser power should be less than the channel laser max power.\n\n"
                f"{tile_text}\n\n"
                "Enter desired laser power below max power:"
            )

            desired_power, ok = QInputDialog.getDouble(
                self,
                title,
                message,
                min(first_current_value, first_max_laser_power - 1),
                0,
                first_max_laser_power - 1,
                2,
            )

        if not ok:
            return False

        if first_mode == "binning_gt_1" and desired_power >= first_max_laser_power:
            QMessageBox.warning(
                self,
                "Invalid laser power",
                f"Laser power should be less than {first_max_laser_power} when binning > 1.",
            )
            return False

        for (
            tile_index,
            tile,
            laser_power_key,
            current_value,
            max_laser_power,
            mode,
        ) in incorrect_tiles:
            if mode == "binning_gt_1" and desired_power >= max_laser_power:
                QMessageBox.warning(
                    self,
                    "Invalid laser power",
                    (
                        f"Tile {tile_index} uses a laser with max power {max_laser_power}.\n"
                        f"The requested value {desired_power} is not less than that max power."
                    ),
                )
                return False

            if isinstance(laser_power_key, tuple):
                parent_key, nested_key = laser_power_key
                tile[parent_key][nested_key] = desired_power
            else:
                tile[laser_power_key] = desired_power

            self.log.info(
                f"[laser power updated] "
                f"Tile {tile_index}: "
                f"{laser_power_key}: {current_value} -> {desired_power} "
                f"(channel laser max = {max_laser_power})"
            )

        return True

    def flip_mount_check(self) -> bool:
        tiles = self.acquisition.config["acquisition"]["tiles"]

        if not tiles:
            return True

        x_positions = [
            float(tile["position_mm"]["x"])
            for tile in tiles
        ]

        mean_x_position = sum(x_positions) / len(x_positions)

        incorrect_tiles = []

        for tile_index, tile in enumerate(tiles, start=1):
            x_position = float(tile["position_mm"]["x"])

            if x_position < mean_x_position:
                required_position = "left"
            elif x_position > mean_x_position:
                required_position = "right"
            else:
                continue

            flip_mount_key = None
            flip_mount_position = None

            for key, value in tile.items():
                if "flip" in key.lower() and "mount" in key.lower():
                    flip_mount_key = key

                    if isinstance(value, dict) and "position" in value:
                        flip_mount_position = value["position"]
                    else:
                        flip_mount_position = value

                    break

            if flip_mount_key is None:
                continue

            if flip_mount_position != required_position:
                incorrect_tiles.append(
                    (
                        tile_index,
                        tile,
                        flip_mount_key,
                        flip_mount_position,
                        required_position,
                        x_position,
                    )
                )

        if not incorrect_tiles:
            return True

        tile_text = "\n".join(
            [
                (
                    f"Tile {tile_index}: "
                    f"x = {x_position:.3f}, "
                    f"{current_value} → {required_position}"
                )
                for (
                    tile_index,
                    tile,
                    flip_mount_key,
                    current_value,
                    required_position,
                    x_position,
                ) in incorrect_tiles
            ]
        )

        response = QMessageBox.question(
            self,
            "Incorrect flip mount positions detected",
            (
                f"Mean x position is {mean_x_position:.3f} mm.\n\n"
                "Tiles with x positions less than the mean must use flip mount position 'left'.\n"
                "Tiles with x positions greater than the mean must use flip mount position 'right'.\n\n"
                "The following tiles have incorrect flip mount positions:\n\n"
                f"{tile_text}\n\n"
                "Would you like to automatically update them?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if response == QMessageBox.No:
            return False

        for (
            tile_index,
            tile,
            flip_mount_key,
            current_value,
            required_position,
            x_position,
        ) in incorrect_tiles:

            value = tile[flip_mount_key]

            if isinstance(value, dict) and "position" in value:
                value["position"] = required_position
            else:
                tile[flip_mount_key] = required_position

            self.log.info(
                f"[flip_mount corrected] "
                f"Tile {tile_index}: "
                f"x={x_position:.3f}, "
                f"{current_value} -> {required_position}"
            )

        return True

    def file_transfer_check(self) -> bool:
        if getattr(self.acquisition, "file_transfers", None):
            return True

        response = QMessageBox.warning(
            self,
            "No file transfer configured",
            (
                "No file transfer is configured for this acquisition.\n\n"
                "Acquisition data may only be saved locally.\n\n"
                "Do you want to continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        return response == QMessageBox.Yes

    def etl_and_focus_check(self) -> bool:
        tiles = self.acquisition.config["acquisition"]["tiles"]

        if not tiles:
            return True

        daq = self.instrument.daqs[list(self.instrument.daqs.keys())[0]]

        tile_messages = []

        for tile_index, tile in enumerate(tiles, start=1):
            channel = tile.get("channel", "unknown")

            lines = []
            lines.append(f"Channel: {channel}")

            for stage_name in self.instrument.focusing_stages.keys():
                if stage_name not in tile:
                    continue

                stage_tile_settings = tile[stage_name]

                if not isinstance(stage_tile_settings, dict):
                    continue

                if "position_mm" in stage_tile_settings:
                    lines.append(
                        f"Focusing stage {stage_name}: "
                        f"{stage_tile_settings['position_mm']} mm"
                    )

            for lens_name in ["left tunable lens", "right tunable lens"]:
                try:
                    offset_value = (
                        daq.tasks["ao_task"]
                        ["ports"][lens_name]
                        ["parameters"]["offset_volts"]
                        ["channels"][channel]
                    )

                    lines.append(
                        f"{lens_name} offset_volts: {offset_value}"
                    )

                except KeyError:
                    lines.append(
                        f"{lens_name} offset_volts: not found"
                    )

            tile_messages.append("\n".join(lines))

        dialog = TileCheckDialog(
            parent=self,
            tile_messages=tile_messages,
        )

        return dialog.exec_() == QDialog.Accepted
