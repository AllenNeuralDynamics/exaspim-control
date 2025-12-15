import contextlib
import inspect
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

from exaspim_control.build import build_object
from exaspim_control.config import ExASPIMConfig
from exaspim_control.instrument import ExASPIM
from exaspim_control.qtgui.acq_task_widget import AcquisitionTaskWidget
from exaspim_control.qtgui.components import Card, VButton
from exaspim_control.qtgui.control_tab import ControlTab
from exaspim_control.qtgui.devices.camera_widget import CameraWidget
from exaspim_control.qtgui.devices.device_widget import SimpleWidget
from exaspim_control.qtgui.devices.filter_wheel_widget import FilterWheelWidget
from exaspim_control.qtgui.devices.laser_widget import LaserWidget
from exaspim_control.qtgui.devices_tab import DevicesTab
from exaspim_control.qtgui.experiment_tab import ExperimentTab
from exaspim_control.qtgui.live import LiveViewer
from exaspim_control.qtgui.volume import GridControlsWidget, TileTable, VolumeGraphic, VolumeModel


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
    """Pure Qt alternative to napari-embedded InstrumentView.

    Layout:
    - Left Panel (70%):
        - Top: VolumeModel + LiveViewer (side by side)
        - Bottom: Tabbed area (TileTable, Waveforms, DAQ) with tab bar at bottom
    - Right Panel (30%):
        - Top: Actions Card (channel selector, acquisition, livestream controls)
        - Middle: Tab content (Instrument, Devices, Acquisition)
        - Bottom: Tab anchors
    """

    def __init__(self, instrument: ExASPIM, window_title: str = "ExA-SPIM Control"):
        super().__init__()

        self._instrument = instrument

        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        self._is_closing = False  # flag to signal workers to stop

        # Livestream state
        self.active_channel = None
        self._is_livestreaming = False

        # Live viewer (embedded + expandable to napari)
        self.live_viewer = LiveViewer(
            title=f"Live: {self.instrument.camera.uid}",
            parent=self,  # Napari window will be child of main window
        )

        # Device widgets for Instrument Control tab
        self.camera_widget = CameraWidget(self.instrument.camera, parent=self)
        self.daq_widget = None
        self.fw_widgets = {uid: FilterWheelWidget(fw, parent=self) for uid, fw in self.instrument.filter_wheels.items()}
        self.laser_widgets = {uid: LaserWidget(laser, parent=self) for uid, laser in self.instrument.lasers.items()}

        # Volume visualization components
        coordinate_plane = self.config.globals.coordinate_plane
        unit = self.config.globals.unit
        limits = [
            list(self.instrument.stage.x.limits_mm),
            list(self.instrument.stage.y.limits_mm),
            list(self.instrument.stage.z.limits_mm),
        ]
        fov_dimensions = list(self._calculate_fov_dimensions())

        # Create VolumeModel (shared reactive state for volume planning)
        self.volume_model = VolumeModel(
            coordinate_plane=list(coordinate_plane),
            unit=unit,
            fov_dimensions=fov_dimensions,
            fov_position=[0.0, 0.0, 0.0],
            limits=limits,
            parent=self,
        )

        # Create VolumeGraphic (3D visualization) - subscribes to VolumeModel
        self.volume_graphic = VolumeGraphic(model=self.volume_model, parent=self)
        self.volume_graphic.fovHalt.connect(self._on_halt_stage)

        # Create TileTable (tile configuration table) - subscribes to VolumeModel
        self.tile_table = TileTable(
            model=self.volume_model,
            parent=self,
        )

        # Create GridControlsWidget (grid configuration controls) - reads/writes VolumeModel
        self.grid_controls = GridControlsWidget(
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

        # Actions card with control buttons (channel/start moved to tab bars)
        self.actions_card = ActionsCard(parent=self)
        self._connect_actions_card_signals()

        # Channel selector (will be placed in left tab bar corner)
        self.channel_combo = self._create_channel_combo()

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
        """Calculate FOV dimensions from camera frame size and objective magnification.

        FOV = camera_frame_mm / magnification

        The camera's frame_width_mm = um_px * roi_width_px / 1000 (binning cancels out).
        If um_px is the physical pixel size, we divide by magnification to get true FOV.
        """
        magnification = self.config.globals.objective_magnification

        # Get sensor-referenced dimensions from camera (ROI size * um_px)
        height_mm = self.instrument.camera.frame_height_mm
        width_mm = self.instrument.camera.frame_width_mm

        # Apply objective magnification to get actual FOV
        height_mm = height_mm / magnification
        width_mm = width_mm / magnification

        cam_rotation = self.config.globals.camera_rotation_deg
        return (height_mm, width_mm, 0) if cam_rotation in [-270, -90, 90, 270] else (width_mm, height_mm, 0)

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

    def _update_limits(self) -> None:
        """Update VolumeModel with current stage limits.

        Reads limits from stage axes and propagates to VolumeModel,
        which notifies all subscribed widgets (GridControlsWidget, TileTable, VolumeGraphic).
        """
        limits = [
            list(self.instrument.stage.x.limits_mm),
            list(self.instrument.stage.y.limits_mm),
            list(self.instrument.stage.z.limits_mm),
        ]
        # VolumeModel will emit limitsChanged signal to update all widgets
        self.volume_model.limits = limits

    def _connect_actions_card_signals(self) -> None:
        """Connect actions card signals to handlers."""
        self.actions_card.live_button.clicked.connect(self._toggle_livestream)
        self.actions_card.snapshot_button.clicked.connect(self._take_snapshot)
        self.actions_card.crosshairs_button.toggled.connect(self._toggle_crosshairs)
        self.actions_card.halt_button.clicked.connect(self._on_halt_stage)

    def _create_channel_combo(self) -> QComboBox:
        """Create channel selector combo box for left tab bar."""
        combo = QComboBox()
        combo.addItems(list(self.channels.keys()))
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
        combo.currentTextChanged.connect(self._on_channel_changed)
        return combo

    def _create_start_button(self) -> VButton:
        """Create Start Acquisition button for right tab bar."""
        button = VButton("Start Acquisition", variant="primary")
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
        """Create left panel: VolumeGraphic + LiveViewer (top) + Tabbed bottom (TileTable)."""
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

        # Add channel combo to right corner of tab bar
        self.left_tabs.setCornerWidget(self.channel_combo, Qt.Corner.BottomRightCorner)

        # Grid tab - GridControlsWidget (first tab)
        grid_tab = QScrollArea()
        grid_tab.setWidgetResizable(True)
        grid_tab.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        grid_tab.setFrameShape(QScrollArea.Shape.NoFrame)
        grid_tab.setWidget(self.grid_controls)
        self.left_tabs.addTab(grid_tab, "Grid")

        # TileTable tab - TileTable widget includes its own apply_all checkbox
        self.left_tabs.addTab(self.tile_table, "TileTable")

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

        # Set initial sizes (70% top row, 30% tile table)
        left_splitter.setSizes([700, 300])

        return left_splitter

    def _create_waveforms_tab(self) -> QWidget:
        """Create Waveforms tab with refresh button."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header with refresh button
        header = QWidget()
        header.setStyleSheet("background-color: #252526;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.addStretch()

        refresh_btn = QPushButton("⟳ Refresh")
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

    def _create_filters_tab(self) -> QScrollArea:
        """Create Filter Wheels tab with all filter wheel widgets."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        if self.fw_widgets:
            for uid, widget in self.fw_widgets.items():
                fw_card = Card(f"Filter Wheel: {uid}")
                fw_card.add_widget(widget)
                layout.addWidget(fw_card)
        else:
            placeholder = QLabel("No filter wheels configured")
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
        self.control_tab = ControlTab(
            camera_widget=self.camera_widget,
            camera_uid=self.instrument.camera.uid,
            laser_widgets=self.laser_widgets,
            stage=self.instrument.stage,
            focusing_axes=self.instrument.focusing_axes,
        )
        self.control_tab.stageLimitsChanged.connect(self._update_limits)
        self.right_tabs.addTab(self.control_tab, "Control")

        # TAB 3: Experiment
        self.right_tabs.addTab(self.experiment_tab, "Experiment")

        # Set Control tab as active on launch
        self.right_tabs.setCurrentIndex(1)

        layout.addWidget(self.right_tabs, stretch=1)

        return panel

    def _create_devices_tab(self) -> DevicesTab:
        """Create the Devices tab with all instrument devices organized in accordions."""
        devices_by_type: dict[str, dict[str, object]] = {}

        # Cameras
        if self.instrument.camera:
            devices_by_type["Cameras"] = {"camera": self.instrument.camera}

        # Lasers
        if self.instrument.lasers:
            devices_by_type["Lasers"] = dict(self.instrument.lasers)

        # Filter Wheels
        if self.instrument.filter_wheels:
            devices_by_type["Filter Wheels"] = dict(self.instrument.filter_wheels)

        # Stages / Axes
        if self.instrument.axes:
            devices_by_type["Axes"] = dict(self.instrument.axes)

        # Flip Mounts
        if self.instrument.flip_mounts:
            devices_by_type["Flip Mounts"] = dict(self.instrument.flip_mounts)

        return DevicesTab(devices_by_type, parent=self)

    def _toggle_livestream(self) -> None:
        """Toggle livestream and update button state."""
        if self._is_livestreaming:
            self.instrument.stop_livestream()
            self._is_livestreaming = False
            self.actions_card.live_button.setText("Live")
            # Clear acquisition task widget
            self.acq_task_widget.clear()
            # Re-enable camera controls
            self._set_camera_controls_enabled(True)
        else:
            # Disable camera controls during acquisition to prevent dtype/buffer issues
            self._set_camera_controls_enabled(False)
            # Prepare viewer for new acquisition (clear layers for fresh dtype)
            self.live_viewer.prepare_for_acquisition()
            # Start livestream
            self.instrument.start_livestream(on_frame=self._on_frame)
            self._is_livestreaming = True
            self.actions_card.live_button.setText("Stop")
            # Update acquisition task widget with active task
            if self.instrument._acq_task is not None:
                self.acq_task_widget.set_task(self.instrument._acq_task)

    def _set_camera_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable camera controls that shouldn't change during acquisition.

        :param enabled: True to enable controls, False to disable
        """
        if self.camera_widget is not None:
            self.camera_widget.set_acquisition_controls_enabled(enabled)

    def _on_frame(self, frame: np.ndarray) -> None:
        """Send frame to live viewer."""
        self.live_viewer.update_frame(frame)

    def _take_snapshot(self) -> None:
        """Take a single snapshot from the camera."""
        self.log.info("Taking snapshot")
        try:
            frame = self.instrument.camera.latest_frame
            self.live_viewer.update_frame(frame)
        except Exception:
            self.log.exception("Failed to take snapshot")

    def _toggle_crosshairs(self, checked: bool) -> None:
        """Toggle crosshairs overlay on live viewer."""
        self.log.info(f"Crosshairs {'enabled' if checked else 'disabled'}")
        # TODO: Implement crosshairs overlay on LiveViewer

    def _on_channel_changed(self, channel_name: str) -> None:
        """Handle channel change from actions card.

        Uses instrument.set_active_channel() which handles stopping livestream,
        switching hardware (lasers, filters), and restarting if was streaming.
        """
        self.active_channel = channel_name
        self.instrument.set_active_channel(channel_name)
        self.log.info(f"Channel changed to: {channel_name}")

    def _on_halt_stage(self) -> None:
        """Handle halt stage button click."""
        self.log.warning("HALT STAGE triggered")
        # TODO: Implement actual stage halt logic
        # self.instrument.stage.halt()

    def set_stage_moving(self, is_moving: bool) -> None:
        """Update UI to reflect stage movement state.

        :param is_moving: True if stage is currently moving
        """
        self.actions_card.halt_button.set_stage_moving(is_moving)

    # def _setup_daq_widgets(self) -> None:
    #     """Setup DAQ widget signal connections."""
    #     self.daq_widget.propertyChanged.connect(lambda _name, _value: self.write_waveforms(self.instrument.daq))
    #     self.daq_widget.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)

    # def write_waveforms(self, daq: object) -> None:
    #     """Write waveforms to DAQ - placeholder for now."""
    #     # TODO: Implement in later step when needed

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
            widget = SimpleWidget(type(device))
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

    def close(self) -> bool:
        """Close operations and end threads."""
        self.log.info("Closing InstrumentUI")

        self._is_closing = True

        # Stop all device widget workers first (waits for them to finish)
        for widget in [self.camera_widget, *self.fw_widgets.values(), *self.laser_widgets.values()]:
            if widget is not None and hasattr(widget, "stop_workers"):
                widget.stop_workers()

        # Stop axis widget workers from control tab
        if hasattr(self, "control_tab") and self.control_tab is not None:
            for widget in self.control_tab.findChildren(QWidget):
                if hasattr(widget, "stop_workers"):
                    widget.stop_workers()

        # Close live viewer
        self.live_viewer.close()

        # Close instrument (now safe - all workers stopped)
        with contextlib.suppress(AttributeError):
            self.instrument.close()

        return super().close()
