import contextlib
import inspect
import logging
import time
from collections.abc import Iterator

from napari.qt.threading import thread_worker
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from view.widgets.acquisition_widgets.volume_model import VolumeModel
from view.widgets.device_widget import DeviceWidget

from exaspim_control.build import build_object
from exaspim_control.config import ExASPIMConfig
from exaspim_control.instrument import ExASPIM
from exaspim_control.widgets.camera_widget import CameraWidget
from exaspim_control.widgets.filter_wheel_widget import FilterWheelWidget
from exaspim_control.widgets.flip_mount_widget import FlipMountWidget
from exaspim_control.widgets.laser_widget import LaserWidget
from exaspim_control.widgets.ni_widget import NIWidget
from exaspim_control.widgets.stage_widget import AxisWidget


class AcquisitionTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("Acquisition Tab")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        info = QLabel("This is where acquisition planning and operations UI will go.")
        info.setStyleSheet("color: #888; margin-bottom: 20px;")
        layout.addWidget(info)

        start_button = QPushButton("Start Acquisition")
        layout.addWidget(start_button)

        layout.addStretch()


class InstrumentUI[I: ExASPIM](QMainWindow):
    """Pure Qt alternative to napari-embedded InstrumentView.

    Layout:
    - Left: 3D visualization (top) + tile table (bottom)
    - Right: Tabbed panel (Instrument Control + Acquisition)
    - Each camera manages its own image display and optional napari viewer
    """

    def __init__(self, instrument: ExASPIM, window_title: str = "ExA-SPIM Control"):
        super().__init__()

        self._instrument = instrument

        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Convenient config maps

        # Property workers and threads
        self.property_workers = []  # list of property workers
        self._is_closing = False  # flag to signal workers to stop
        self.fov_positions_worker = None  # FOV positions worker

        # Livestream state (for channel selection)
        self.active_channel = None

        # Device widgets - create directly
        self.camera_widget = CameraWidget(self.instrument.camera)
        self.daq_widget = NIWidget(self.instrument.daq)
        self.fw_widgets = {uid: FilterWheelWidget(fw) for uid, fw in self.instrument.filter_wheels.items()}
        self.laser_widgets = {uid: LaserWidget(laser) for uid, laser in self.instrument.lasers.items()}
        self.axis_widgets = {uid: AxisWidget(axis) for uid, axis in self.instrument.focusing_axes.items()}
        self.flip_mount_widgets = {uid: FlipMountWidget(fm) for uid, fm in self.instrument.flip_mounts.items()}

        self.acq_tab = AcquisitionTab()

        # Set window title
        self.setWindowTitle(window_title)

        # Setup UI (tabs will now have device widgets available)
        self._setup_ui()

        # Setup device-specific functionality
        self._setup_daq_widgets()

        self.log.info("InstrumentUI initialized")

    @property
    def instrument(self) -> ExASPIM:
        return self._instrument

    @property
    def config(self) -> ExASPIMConfig:
        return self._instrument.cfg

    @property
    def channels(self):
        return self.config.channels

    def _calculate_fov_dimensions(self) -> tuple[float, float, float]:
        """Calculate FOV dimensions from camera properties and config rotation."""
        height_mm = self.instrument.camera.frame_height_mm
        width_mm = self.instrument.camera.frame_width_mm
        cam_rotation = self.config.globals.camera_rotation_deg
        return (height_mm, width_mm, 0) if cam_rotation in [-270, -90, 90, 270] else (width_mm, height_mm, 0)

    def _setup_ui(self) -> None:
        """Create the main UI layout."""
        # Central widget with horizontal splitter
        central = QWidget()
        main_layout = QHBoxLayout(central)

        # Main horizontal splitter: left (visualization) | right (controls)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # LEFT PANEL: Vertical splitter for 3D view + table
        left_panel = self._create_left_panel()
        main_splitter.addWidget(left_panel)

        # RIGHT PANEL: Tabbed interface
        right_panel = self._create_right_panel()
        main_splitter.addWidget(right_panel)

        # Set initial splitter sizes (60% left, 40% right)
        main_splitter.setSizes([600, 400])

        main_layout.addWidget(main_splitter)
        self.setCentralWidget(central)

        # Menu bar
        self._setup_menu_bar()

        self.log.info("UI layout created")

    def _create_left_panel(self) -> QWidget:
        """Create left panel: 3D visualization + tabbed bottom panel."""
        left_splitter = QSplitter(Qt.Orientation.Vertical)

        # TOP: VolumeModel (3D GL visualization)
        coordinate_plane = self.config.globals.coordinate_plane
        unit = self.config.globals.unit
        limits = (
            self.instrument.stage.x.limits_mm,
            self.instrument.stage.y.limits_mm,
            self.instrument.stage.z.limits_mm,
        )
        fov_dimensions = self._calculate_fov_dimensions()

        self.volume_model = VolumeModel(
            limits=limits,
            fov_dimensions=fov_dimensions,
            coordinate_plane=coordinate_plane,
            unit=unit,
        )

        # Combine volume model with its control widgets
        volume_container = QWidget()
        volume_layout = QGridLayout(volume_container)
        volume_layout.addWidget(self.volume_model, 0, 0, 3, 1)
        volume_layout.addWidget(self.volume_model.widgets, 3, 0, 1, 1)
        volume_layout.setContentsMargins(0, 0, 0, 0)

        left_splitter.addWidget(volume_container)

        # BOTTOM: Tabbed panel with Tile Grid and DAQ
        bottom_tabs = QTabWidget()
        bottom_tabs.setTabPosition(QTabWidget.TabPosition.South)  # Tabs on bottom

        # Tab 1: Tile Grid
        tile_grid_tab = QWidget()
        tile_grid_layout = QVBoxLayout(tile_grid_tab)
        tile_grid_placeholder = QLabel("Tile Grid - To be implemented in Step 10")
        tile_grid_placeholder.setStyleSheet("background-color: #3a3a3a; color: white; padding: 20px;")
        tile_grid_layout.addWidget(tile_grid_placeholder)
        bottom_tabs.addTab(tile_grid_tab, "Tile Grid")

        # Tab 2: DAQ
        daq_tab = self._create_daq_tab()
        bottom_tabs.addTab(daq_tab, "DAQ")

        left_splitter.addWidget(bottom_tabs)

        # Set initial sizes (70% 3D view, 30% bottom tabs)
        left_splitter.setSizes([700, 300])

        return left_splitter

    def _create_daq_tab(self) -> QWidget:
        """Create DAQ tab with DAQ widget, maximizing space."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)  # Remove margins to maximize space
        layout.setSpacing(0)  # Remove spacing between widgets

        if self.daq_widget:
            layout.addWidget(self.daq_widget, stretch=1)
        else:
            # Placeholder if no DAQ widget
            placeholder = QLabel("No DAQ device configured")
            placeholder.setStyleSheet("color: gray; padding: 20px;")
            layout.addWidget(placeholder)

        return tab

    def _create_right_panel(self) -> QTabWidget:
        """Create right panel: tabbed instrument/acquisition controls."""
        tabs = QTabWidget()

        # TAB 1: Instrument Control
        instrument_tab = self._create_instrument_tab()
        tabs.addTab(instrument_tab, "Instrument Control")

        # TAB 2: Acquisition
        tabs.addTab(self.acq_tab, "Acquisition")

        # Add channel selector to top-right corner of tab widget
        channel_selector = self._create_channel_selector_compact()
        tabs.setCornerWidget(channel_selector, Qt.Corner.TopRightCorner)

        return tabs

    def _create_instrument_tab(self) -> QWidget:
        """Create instrument control tab with device widgets."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Create scroll area for all device widgets
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Container for all device widgets
        container = QWidget()
        container_layout = QVBoxLayout(container)

        # Camera control (always visible)
        if self.camera_widget:
            camera_label = QLabel("<b>Camera</b>")
            container_layout.addWidget(camera_label)
            container_layout.addWidget(self.camera_widget)

        # Laser controls - stacked vertically (always visible)
        if self.laser_widgets:
            laser_label = QLabel("<b>Lasers</b>")
            container_layout.addWidget(laser_label)
            for laser_widget in self.laser_widgets.values():
                container_layout.addWidget(laser_widget)

        # Stage controls (combine all stage types) - collapsible group
        if self.axis_widgets:
            stage_group = self._create_device_group("Stages", self.axis_widgets)
            container_layout.addWidget(stage_group)

        # DAQ moved to left panel - no longer here

        # Filter wheel
        if self.fw_widgets:
            for uid, widget in self.fw_widgets.items():
                filter_label = QLabel(f"<b>Filter Wheel {uid}</b>")
                container_layout.addWidget(filter_label)
                container_layout.addWidget(widget)

        # Flip mounts - collapsible group
        if self.flip_mount_widgets:
            flip_group = self._create_device_group("Flip Mounts", self.flip_mount_widgets)
            container_layout.addWidget(flip_group)

        container_layout.addStretch()

        scroll.setWidget(container)
        layout.addWidget(scroll)

        return tab

    def _create_channel_selector(self) -> QWidget:
        """Create channel selector widget (with label)."""
        widget = QWidget()
        layout = QHBoxLayout()

        label = QLabel("Channel:")
        laser_combo_box = QComboBox(widget)
        laser_combo_box.addItems(self.channels.keys())
        laser_combo_box.currentTextChanged.connect(lambda value: self.change_channel(value))
        laser_combo_box.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        laser_combo_box.setCurrentIndex(0)  # initialize to first channel index
        self.laser_combo_box = laser_combo_box
        self.active_channel = laser_combo_box.currentText()  # initialize livestream channel

        layout.addWidget(label)
        layout.addWidget(laser_combo_box)
        layout.addStretch()
        widget.setLayout(layout)
        widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        return widget

    def _create_channel_selector_compact(self) -> QWidget:
        """Create compact channel selector widget (no label, for tab bar corner)."""
        laser_combo_box = QComboBox()
        laser_combo_box.addItems(self.channels.keys())
        laser_combo_box.currentTextChanged.connect(lambda value: self.change_channel(value))
        laser_combo_box.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        laser_combo_box.setCurrentIndex(0)  # initialize to first channel index
        self.laser_combo_box = laser_combo_box
        self.active_channel = laser_combo_box.currentText()  # initialize livestream channel

        return laser_combo_box

    def _create_device_group(self, title: str, widgets: dict) -> QGroupBox:
        """Create a collapsible group box for device widgets."""
        group = QGroupBox(title)
        group.setCheckable(True)  # Makes it collapsible
        group.setChecked(True)

        layout = QVBoxLayout()

        # Special handling for Stages - always show all axes directly
        if title == "Stages":
            # Stack all stage widgets vertically (no dropdown)
            for widget in widgets.values():
                layout.addWidget(widget)
        elif len(widgets) > 1:
            # Multiple devices: use combo box selector
            combo = QComboBox()
            combo.addItems(widgets.keys())
            layout.addWidget(combo)

            # Stack all widgets, show only selected
            for name, widget in widgets.items():
                widget.setVisible(name == combo.currentText())
                layout.addWidget(widget)

            combo.currentTextChanged.connect(lambda text: self._show_selected_widget(widgets, text))
        else:
            # Single device: just add it
            for widget in widgets.values():
                layout.addWidget(widget)

        group.setLayout(layout)
        return group

    def _show_selected_widget(self, widgets: dict, selected_name: str) -> None:
        """Show only the selected widget in a group."""
        for name, widget in widgets.items():
            widget.setVisible(name == selected_name)

    def change_channel(self, channel_name: str) -> None:
        """Change the current livestream channel - to be implemented."""
        self.active_channel = channel_name
        self.log.info(f"Channel changed to: {channel_name}")

    def _setup_daq_widgets(self) -> None:
        """Setup DAQ widget signal connections."""
        self.daq_widget.propertyChanged.connect(lambda _name, _value: self.write_waveforms(self.instrument.daq))
        self.daq_widget.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)

    def write_waveforms(self, daq: object) -> None:
        """Write waveforms to DAQ - placeholder for now."""
        # TODO: Implement in later step when needed

    def _setup_menu_bar(self) -> None:
        """Create menu bar."""
        # File menu
        if (file_menu := self.menuBar()) is not None:
            file_menu.addMenu("&File")
            # Save Config action
            save_config_action = QAction("Save &Config", self)
            save_config_action.triggered.connect(lambda: self.log.info("Save Config - To be implemented"))
            file_menu.addAction(save_config_action)

            # Exit action
            exit_action = QAction("E&xit", self)
            exit_action.triggered.connect(self.close)
            file_menu.addAction(exit_action)

    def _make_widget(self, device_name: str, device, device_type: str = "Device"):
        """Create widget for device, checking config for custom GUI class."""
        if device_name in self.config.widgets:
            widget = build_object(self.config.widgets[device_name])
        else:
            widget = DeviceWidget(type(device))

        if isinstance(widget, DeviceWidget):
            widget.propertyChanged.connect(lambda n, v: self.log.info(f"Property '{n}' changed to {v}"))

        widget.setWindowTitle(f"{device_type} {device_name}")
        return widget

    def update_property_value(self, value, device_widget, property_name: str) -> None:
        """Update property value in device widget."""
        with contextlib.suppress(RuntimeError, AttributeError):
            setattr(device_widget, property_name, value)  # setting attribute value will update widget

    @pyqtSlot(str)
    def device_property_changed(self, attr_name: str, device: object, widget) -> None:
        """
        pyqtSlot to signal when device widget has been changed.

        :param attr_name: name of attribute
        :param device: device object
        :param widget: widget object relating to device
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

    @thread_worker
    def create_device_property_worker(self, device: object, property_names: list[str]) -> Iterator:
        """
        Factory for device property monitoring workers.

        Creates a single worker that continuously polls all updating properties for a device.
        This is more efficient than creating one thread per property.
        Respects the _is_closing flag for clean shutdown.

        :param device: Device object to monitor
        :param property_names: List of property names to poll
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

            # Poll all properties for this device and yield each one
            for property_name in property_names:
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

    def close(self) -> bool:
        """Close operations and end threads."""
        self.log.info("Closing InstrumentUI")

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

        # Wait for all workers to finish with timeout
        for worker in self.property_workers:
            max_wait = 0.5  # seconds
            elapsed = 0.0
            while worker.is_running and elapsed < max_wait:
                time.sleep(0.02)
                elapsed += 0.02

        # Close instrument
        with contextlib.suppress(AttributeError):
            self.instrument.close()

        return super().close()
