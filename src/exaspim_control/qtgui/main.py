import contextlib
import logging
from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QComboBox,
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
from voxel.preview import PreviewFrame

from exaspim_control.config import ExASPIMConfig
from exaspim_control.instrument import ExASPIM, Stage
from exaspim_control.qtgui.acq_task_widget import AcquisitionTaskWidget
from exaspim_control.qtgui.components import Card, VButton
from exaspim_control.qtgui.control_tab import ControlTab
from exaspim_control.qtgui.devices.camera_widget import CameraWidget
from exaspim_control.qtgui.devices.device_adapter import DeviceAdapter
from exaspim_control.qtgui.devices.filter_wheel_widget import FilterWheelWidget
from exaspim_control.qtgui.devices.laser_widget import LaserWidget
from exaspim_control.qtgui.devices_tab import DevicesTab
from exaspim_control.qtgui.experiment_tab import ExperimentTab
from exaspim_control.qtgui.live import LiveViewer
from exaspim_control.qtgui.volume import GridControls, VolumeGraphic, VolumeModel


class HaltStageButton(QPushButton):
    """Halt Stage button that changes color based on stage movement.

    - Gray when stage is idle
    - Red when stage is moving
    """

    def __init__(self, parent=None):
        super().__init__("Halt Stage", parent)
        self._is_moving = False
        self._apply_idle_style()

    def _apply_idle_style(self) -> None:
        """Apply gray idle style matching tab bar components."""
        self.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #d4d4d4;
                font-weight: bold;
                font-size: 11px;
                padding: 4px 12px;
                border: 1px solid #505050;
                border-radius: 3px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #4a4a4d;
                border-color: #606060;
            }
            QPushButton:pressed {
                background-color: #2d2d30;
            }
        """)

    def _apply_moving_style(self) -> None:
        """Apply red moving style."""
        self.setStyleSheet("""
            QPushButton {
                background-color: #c42b1c;
                color: white;
                font-weight: bold;
                font-size: 11px;
                padding: 4px 12px;
                border: 1px solid #d63a2b;
                border-radius: 3px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #d63a2b;
                border-color: #e64a3b;
            }
            QPushButton:pressed {
                background-color: #a52414;
            }
        """)

    def set_stage_moving(self, is_moving: bool) -> None:
        """Update button style based on stage movement state."""
        if is_moving != self._is_moving:
            self._is_moving = is_moving
            if is_moving:
                self._apply_moving_style()
            else:
                self._apply_idle_style()

    @property
    def is_stage_moving(self) -> bool:
        """Get current stage movement state."""
        return self._is_moving


class ActionsCard(QWidget):
    """Actions card with livestream controls."""

    # Signals
    liveClicked = pyqtSlot()
    snapshotClicked = pyqtSlot()
    crosshairsClicked = pyqtSlot(bool)
    haltClicked = pyqtSlot()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the actions card UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Style the card
        self.setStyleSheet("""
            ActionsCard {
                background-color: #2d2d30;
                border: 1px solid #404040;
                border-radius: 4px;
            }
        """)

        # Single row: Live, Snapshot, Crosshairs, Halt Stage
        self.live_button = VButton("Live", variant="secondary")
        layout.addWidget(self.live_button, stretch=1)

        self.snapshot_button = VButton("Snapshot", variant="secondary")
        layout.addWidget(self.snapshot_button, stretch=1)

        self.crosshairs_button = VButton("Crosshairs", variant="secondary")
        self.crosshairs_button.setCheckable(True)
        layout.addWidget(self.crosshairs_button, stretch=1)

        self.halt_button = HaltStageButton()
        layout.addWidget(self.halt_button, stretch=1)


class InstrumentUI[I: ExASPIM](QMainWindow):
    def __init__(self, instrument: I, window_title: str = "ExA-SPIM Control"):
        super().__init__()

        self._instrument = instrument

        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        self._is_closing = False  # flag to signal workers to stop

        # Livestream state
        self._is_livestreaming = False

        # Live viewer (embedded + expandable to napari)
        camera_rotation_deg = self.config.globals.camera_rotation_deg
        self.live_viewer = LiveViewer(
            title=f"Live: {self.instrument.camera.uid}",
            camera_rotation_deg=camera_rotation_deg,
            parent=self,  # Napari window will be child of main window
        )

        # Create device adapters for all devices
        self._adapters: dict[str, DeviceAdapter] = {}
        for name, device in self.instrument.devices.items():
            self._adapters[name] = DeviceAdapter(device, parent=self)

        # Start polling on adapters that have streaming properties
        for adapter in self._adapters.values():
            if adapter.streaming_properties:
                adapter.start_polling()

        # Device widgets for Instrument Control tab (using adapters)
        self.camera_widget = CameraWidget(self._adapters[self.instrument.camera.uid], parent=self)
        self.daq_widget = None
        self.fw_widgets = {
            uid: FilterWheelWidget(self._adapters[uid], parent=self) for uid in self.instrument.filter_wheels
        }
        self.laser_widgets = {uid: LaserWidget(self._adapters[uid], parent=self) for uid in self.instrument.lasers}

        # Volume visualization components
        # Create VolumeModel (shared reactive state for volume planning)
        self.volume_model = VolumeModel(
            coordinate_plane=list(self.config.globals.coordinate_plane),
            unit=self.config.globals.unit,
            fov_dimensions=list(self._calculate_fov_dimensions()),
            fov_position=[0.0, 0.0, 0.0],
            limits=self._get_stage_limits(self.instrument.stage),
            parent=self,
        )

        # Create VolumeGraphic (3D visualization) - subscribes to VolumeModel
        self.volume_graphic = VolumeGraphic(model=self.volume_model, parent=self)
        self.volume_graphic.fovHalt.connect(self._on_halt_stage)

        # Create GridControls (grid configuration controls + tile table) - reads/writes VolumeModel
        self.grid_controls = GridControls(
            model=self.volume_model,
            parent=self,
        )
        self._connect_grid_signals()

        # Devices tab - all devices as SimpleWidgets in accordions
        self.devices_tab = self._create_devices_tab()

        # Experiment tab with metadata
        self.experiment_tab = ExperimentTab(metadata=self.config.metadata, parent=self)

        # Acquisition task widget for waveform visualization
        self.acq_task_widget = AcquisitionTaskWidget(parent=self)

        # Actions card with control buttons
        self.actions_card = ActionsCard(parent=self)
        self._connect_actions_card_signals()

        # Channel selector (will be placed in left tab bar corner)
        self.channel_combo = self._create_profiles_combo()

        # Start acquisition button (will be placed in right tab bar corner)
        self.start_acq_button = self._create_start_button()

        # Set window title and icon
        self.setWindowTitle(window_title)
        icon_path = Path(__file__).parent / "voxel-logo.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Setup UI (tabs will now have device widgets available)
        self._setup_ui()

        self.log.info("InstrumentUI initialized")

    @staticmethod
    def _get_stage_limits(stage: Stage) -> list[list[float]]:
        return [
            [stage.x.lower_limit_mm, stage.x.upper_limit_mm],
            [stage.y.lower_limit_mm, stage.y.upper_limit_mm],
            [stage.z.lower_limit_mm, stage.z.upper_limit_mm],
        ]

    @property
    def instrument(self) -> ExASPIM:
        return self._instrument

    @property
    def config(self) -> ExASPIMConfig:
        return self._instrument.cfg

    @property
    def profiles(self):
        return self.config.profiles

    def _calculate_fov_dimensions(self) -> tuple[float, float, float]:
        magnification = self.config.globals.objective_magnification
        camera = self.instrument.camera

        # Physical FOV from frame area divided by magnification
        area = camera.frame_area_mm
        width_mm = area.x / magnification
        height_mm = area.y / magnification

        cam_rotation = self.config.globals.camera_rotation_deg
        if cam_rotation in [-270, -90, 90, 270]:
            return (height_mm, width_mm, 0)
        return (width_mm, height_mm, 0)

    def _connect_grid_signals(self) -> None:
        """Connect grid controls signals to volume graphic view settings."""
        self.grid_controls.showPathChanged.connect(self._on_show_path_changed)
        self.grid_controls.viewPlaneChanged.connect(self._on_view_plane_changed)

    def _on_show_path_changed(self, visible: bool) -> None:
        """Handle show path toggle."""
        self.volume_graphic.path.setVisible(visible)

    def _on_view_plane_changed(self, plane: str) -> None:
        """Handle view plane change."""
        coord = self.grid_controls.coordinate_plane
        plane_map = {
            "xy": (coord[0], coord[1]),
            "xz": (coord[0], coord[2]),
            "zy": (coord[2], coord[1]),
        }
        if plane in plane_map:
            self.volume_graphic.view_plane = plane_map[plane]

    def _connect_actions_card_signals(self) -> None:
        """Connect actions card signals to handlers."""
        self.actions_card.live_button.clicked.connect(self._toggle_livestream)
        self.actions_card.snapshot_button.clicked.connect(self._take_snapshot)
        self.actions_card.crosshairs_button.toggled.connect(self._toggle_crosshairs)
        self.actions_card.halt_button.clicked.connect(self._on_halt_stage)

    def _create_profiles_combo(self) -> QComboBox:
        combo = QComboBox(self)
        combo.addItems(list(self.profiles.keys()))
        combo.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #505050;
                border-radius: 3px;
                padding: 4px 8px;
                min-width: 100px;
                font-size: 11px;
            }
            QComboBox:hover {
                border-color: #606060;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #d4d4d4;
                margin-right: 5px;
            }
        """)
        combo.currentTextChanged.connect(self._on_profile_changed)
        return combo

    def _create_start_button(self) -> VButton:
        """Create Start Acquisition button for right tab bar."""
        button = VButton("Start Acquisition", variant="primary", parent=self)
        button.clicked.connect(self._start_acquisition)
        return button

    def _start_acquisition(self) -> None:
        """Start acquisition (placeholder)."""
        self.log.info("Start acquisition clicked")

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

        # Set initial splitter sizes (70% left, 30% right)
        main_splitter.setSizes([700, 300])

        main_layout.addWidget(main_splitter)
        self.setCentralWidget(central)

        # Menu bar
        self._setup_menu_bar()

        self.log.info("UI layout created")

    def _create_left_panel(self) -> QWidget:
        """Create left panel: VolumeGraphic + LiveViewer (top) + Tabbed bottom (Grid, Waveforms, etc.)."""
        left_splitter = QSplitter(Qt.Orientation.Vertical)

        # TOP ROW: VolumeGraphic + LiveViewer side by side (min 800px tall)
        top_row = QSplitter(Qt.Orientation.Horizontal)
        top_row.setMinimumHeight(400)

        # Left: VolumeGraphic (3D visualization)
        self.volume_graphic.setMinimumWidth(400)
        self.volume_graphic.setMinimumHeight(400)
        self.volume_graphic.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        top_row.addWidget(self.volume_graphic)

        # Right: LiveViewer (camera preview)
        self.live_viewer.setMinimumWidth(300)
        self.live_viewer.setMinimumHeight(400)
        self.live_viewer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        top_row.addWidget(self.live_viewer)

        # Set initial sizes (50% each)
        top_row.setSizes([500, 500])

        left_splitter.addWidget(top_row)

        # BOTTOM: Tabbed area with tab bar at bottom (min 600px tall)
        self.left_tabs = QTabWidget()
        self.left_tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.left_tabs.setMinimumHeight(600)
        self.left_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #404040;
                border-radius: 4px;
                background-color: #2d2d30;
            }
            QTabBar::tab {
                background-color: #252526;
                color: #888;
                border: 1px solid #404040;
                border-top: none;
                padding: 6px 12px;
                margin-right: 2px;
                border-bottom-left-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #2d2d30;
                color: #d4d4d4;
                border-top: 1px solid #2d2d30;
            }
            QTabBar::tab:hover:!selected {
                background-color: #333337;
            }
        """)

        # Add profiles combo to right corner of tab bar
        self.left_tabs.setCornerWidget(self.channel_combo, Qt.Corner.BottomRightCorner)

        # Grid tab - GridControls (tile table on left, controls on right)
        self.left_tabs.addTab(self.grid_controls, "Grid")

        # Waveforms tab - AcquisitionTaskWidget with refresh button
        waveforms_tab = self._create_waveforms_tab()
        self.left_tabs.addTab(waveforms_tab, "Waveforms")

        # DAQ tab (placeholder for now)
        daq_tab = self._create_daq_tab()
        self.left_tabs.addTab(daq_tab, "DAQ")

        # Filter Wheels tab
        filters_tab = self._create_filters_tab()
        self.left_tabs.addTab(filters_tab, "Filters")

        left_splitter.addWidget(self.left_tabs)

        # Set initial sizes (70% top row, 30% tabs)
        left_splitter.setSizes([700, 300])

        return left_splitter

    def _create_waveforms_tab(self) -> QWidget:
        """Create Waveforms tab with refresh button."""
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header with refresh button
        header = QWidget(tab)
        header.setStyleSheet("background-color: #252526;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.addStretch()

        refresh_btn = QPushButton("⟳ Refresh", header)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #505050;
                border-radius: 3px;
                padding: 4px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #4a4a4d;
            }
            QPushButton:pressed {
                background-color: #2d2d30;
            }
        """)
        refresh_btn.clicked.connect(self._refresh_waveforms)
        header_layout.addWidget(refresh_btn)

        layout.addWidget(header)
        layout.addWidget(self.acq_task_widget, stretch=1)

        return tab

    def _refresh_waveforms(self) -> None:
        """Refresh the waveforms display."""
        # If there's an active task, refresh from it
        if self.instrument._acq_task is not None:
            self.acq_task_widget.set_task(self.instrument._acq_task)
        self.acq_task_widget.refresh()

    def _create_daq_tab(self) -> QWidget:
        """Create DAQ tab with DAQ widget, maximizing space."""
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)  # Remove margins to maximize space
        layout.setSpacing(0)  # Remove spacing between widgets

        if self.daq_widget:
            layout.addWidget(self.daq_widget, stretch=1)
        else:
            # Placeholder if no DAQ widget
            placeholder = QLabel("No DAQ device configured", tab)
            placeholder.setStyleSheet("color: gray; padding: 20px;")
            layout.addWidget(placeholder)

        return tab

    def _create_filters_tab(self) -> QScrollArea:
        """Create Filter Wheels tab with all filter wheel widgets."""
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget(scroll)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        if self.fw_widgets:
            for uid, widget in self.fw_widgets.items():
                fw_card = Card(f"Filter Wheel: {uid}", parent=container)
                fw_card.add_widget(widget)
                layout.addWidget(fw_card)
        else:
            placeholder = QLabel("No filter wheels configured", container)
            placeholder.setStyleSheet("color: gray; padding: 20px;")
            layout.addWidget(placeholder)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _create_right_panel(self) -> QWidget:
        """Create right panel: actions card at top + tabs with anchors at bottom."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Actions card at top (fixed height)
        layout.addWidget(self.actions_card)

        # Tabs with tab bar at bottom (takes remaining space)
        self.right_tabs = QTabWidget()
        self.right_tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.right_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #404040;
                border-radius: 4px;
                background-color: #2d2d30;
            }
            QTabBar::tab {
                background-color: #252526;
                color: #888;
                border: 1px solid #404040;
                border-top: none;
                padding: 6px 12px;
                margin-right: 2px;
                border-bottom-left-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #2d2d30;
                color: #d4d4d4;
                border-top: 1px solid #2d2d30;
            }
            QTabBar::tab:hover:!selected {
                background-color: #333337;
            }
        """)

        # Add start button to right corner of tab bar
        self.right_tabs.setCornerWidget(self.start_acq_button, Qt.Corner.BottomRightCorner)

        # TAB 1: Devices (property browser for all devices)
        self.right_tabs.addTab(self.devices_tab, "Devices")

        # TAB 2: Control (primary device controls)
        # Get adapters for stage axes
        stage_adapters = {
            "x": self._adapters[self.instrument.stage.x.uid],
            "y": self._adapters[self.instrument.stage.y.uid],
            "z": self._adapters[self.instrument.stage.z.uid],
        }
        # Get adapters for focusing axes
        focusing_adapters = {name: self._adapters[axis.uid] for name, axis in self.instrument.focusing_axes.items()}

        self.control_tab = ControlTab(
            camera_widget=self.camera_widget,
            camera_uid=self.instrument.camera.uid,
            laser_widgets=self.laser_widgets,
            stage_adapters=stage_adapters,
            focusing_adapters=focusing_adapters,
        )

        def _update_limits() -> None:
            """Update VolumeModel with current stage limits.

            Reads limits from stage axes and propagates to VolumeModel,
            which notifies all subscribed widgets (GridControls, VolumeGraphic).
            """
            # VolumeModel will emit limitsChanged signal to update all widgets
            self.volume_model.limits = self._get_stage_limits(self.instrument.stage)

        self.control_tab.stageLimitsChanged.connect(_update_limits)
        self.control_tab.stageMovingChanged.connect(self._on_stage_moving_changed)
        self.right_tabs.addTab(self.control_tab, "Control")

        # TAB 3: Experiment
        self.right_tabs.addTab(self.experiment_tab, "Experiment")

        # Set Control tab as active on launch
        self.right_tabs.setCurrentIndex(1)

        layout.addWidget(self.right_tabs, stretch=1)

        return panel

    def _create_devices_tab(self) -> DevicesTab:
        """Create the Devices tab with all instrument devices organized in accordions."""
        adapters_by_type: dict[str, dict[str, DeviceAdapter]] = {}

        # Cameras
        if self.instrument.camera:
            adapters_by_type["Cameras"] = {self.instrument.camera.uid: self._adapters[self.instrument.camera.uid]}

        # Lasers
        if self.instrument.lasers:
            adapters_by_type["Lasers"] = {uid: self._adapters[uid] for uid in self.instrument.lasers}

        # Filter Wheels
        if self.instrument.filter_wheels:
            adapters_by_type["Filter Wheels"] = {uid: self._adapters[uid] for uid in self.instrument.filter_wheels}

        # Axes
        if self.instrument.axes:
            adapters_by_type["Axes"] = {uid: self._adapters[axis.uid] for uid, axis in self.instrument.axes.items()}

        return DevicesTab(adapters_by_type, parent=self)

    def _toggle_livestream(self) -> None:
        """Toggle livestream and update button state."""

        def _on_raw_frame(frame: np.ndarray, idx: int) -> None:
            """Send raw frame to napari viewer (already copied by PreviewGenerator)."""
            self.live_viewer.update_frame(frame)

        def _on_preview(frame: PreviewFrame) -> None:
            self.live_viewer.update_preview(frame)

        if self._is_livestreaming:
            self.instrument.stop_livestream()
            self._is_livestreaming = False
            self.actions_card.live_button.setText("Live")
            self.acq_task_widget.clear()
            self._set_camera_controls_enabled(True)
        else:
            self._set_camera_controls_enabled(False)
            self.live_viewer.reset()
            self.instrument.start_livestream(on_preview=_on_preview, raw_frame_sink=_on_raw_frame)
            self._is_livestreaming = True
            self.actions_card.live_button.setText("Stop")
            self._refresh_waveforms()

    def _set_camera_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable camera controls that shouldn't change during acquisition."""
        if self.camera_widget is not None:
            self.camera_widget.set_acquisition_controls_enabled(enabled)

    def _take_snapshot(self) -> None:
        """Take a single snapshot from the camera."""
        self.log.warning("Taking snapshot is not yet implemented.")

    def _toggle_crosshairs(self, checked: bool) -> None:
        """Toggle crosshairs overlay on live viewer."""
        self.log.info(f"Crosshairs {'enabled' if checked else 'disabled'}")
        # TODO: Implement crosshairs overlay on LiveViewer

    def _on_profile_changed(self, profile_name: str) -> None:
        """Handle profile change from actions card.

        Uses instrument.set_active_channel() which handles stopping livestream,
        switching hardware (lasers, filters), and restarting if was streaming.
        """
        self.instrument.update_active_profile(profile_name)
        self.log.info(f"Channel changed to: {profile_name}")

    def _on_halt_stage(self) -> None:
        """Handle halt stage button click."""
        self.log.warning("HALT STAGE triggered")
        self.instrument.stage.halt()

    def _on_stage_moving_changed(self, is_moving: bool) -> None:
        """Handle stage movement state change from axis widgets."""
        self.volume_model.is_moving = is_moving
        self.actions_card.halt_button.set_stage_moving(is_moving)

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

    def close(self) -> bool:
        self.log.info("Closing InstrumentUI")
        self._is_closing = True
        # Stop polling on all adapters
        for adapter in self._adapters.values():
            adapter.stop_polling()
        self.live_viewer.close()
        with contextlib.suppress(AttributeError):
            self.instrument.close()
        return super().close()
