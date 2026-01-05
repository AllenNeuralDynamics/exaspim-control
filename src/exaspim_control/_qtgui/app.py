import logging
from collections.abc import Callable, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from exaspim_control._qtgui.model import InstrumentModel
from exaspim_control._qtgui.primitives import Grid, VButton
from exaspim_control._qtgui.widgets.device_explorer import DevicesExplorer
from exaspim_control._qtgui.widgets.devices.filter_wheel import FilterWheelWidget
from exaspim_control._qtgui.widgets.frame_task_panel import FrameTaskPanel
from exaspim_control._qtgui.widgets.live_viewer import LiveViewer
from exaspim_control._qtgui.widgets.metadata_editor import MetadataEditor
from exaspim_control._qtgui.widgets.primary_controls import PrimaryControls
from exaspim_control._qtgui.widgets.session_planner import SessionPlanner
from exaspim_control._qtgui.widgets.volume_graphic import VolumeGraphic
from exaspim_control.instrument.instrument import Instrument
from exaspim_control.session import Session

# Shared stylesheet for bottom-positioned tab widgets
TAB_WIDGET_STYLE = """
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
"""


class Tab:
    def __init__(self, name: str, widget: QWidget | None = None):
        self.name = name
        if widget is None:
            widget = QLabel("Not Available")
            widget.setStyleSheet("color: #666; padding: 20px;")
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._widget = widget

    @property
    def widget(self) -> QWidget:
        return self._widget


class ProfilesCombo(QComboBox):
    def __init__(self, items: Sequence[str], on_select: Callable, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.addItems(items)
        self.setStyleSheet("""
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
        self.currentTextChanged.connect(on_select)


class ActionsCard(QWidget):
    """Actions card with acquisition controls.

    Layout: [▼Profile] [Live] [Snapshot] [Start Acquisition]

    Encapsulates profile selection and camera/acquisition actions.
    """

    liveClicked = pyqtSignal()
    snapshotClicked = pyqtSignal()
    startAcquisitionClicked = pyqtSignal()
    profileChanged = pyqtSignal(str)

    def __init__(
        self,
        model: InstrumentModel,
        profile_names: Sequence[str],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._model = model
        self._profile_names = profile_names
        self._setup_ui()

        # Wire internal signals
        self._live_button.clicked.connect(self.liveClicked.emit)
        self._snapshot_button.clicked.connect(self.snapshotClicked.emit)
        self._start_button.clicked.connect(self.startAcquisitionClicked.emit)
        self._profiles_combo.currentTextChanged.connect(self.profileChanged.emit)

    def _setup_ui(self) -> None:
        """Setup the actions card UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.setStyleSheet("""
            ActionsCard {
                background-color: #2d2d30;
                border: 1px solid #404040;
                border-radius: 4px;
            }
        """)

        # Profile selector
        self._profiles_combo = ProfilesCombo(self._profile_names, lambda _: None)
        self._profiles_combo.currentTextChanged.disconnect()  # Remove dummy connection
        layout.addWidget(self._profiles_combo)

        # Preview controls
        self._live_button = VButton("Live", variant="secondary")
        layout.addWidget(self._live_button, stretch=1)

        self._snapshot_button = VButton("Snapshot", variant="secondary")
        layout.addWidget(self._snapshot_button, stretch=1)

        # Acquisition control
        self._start_button = VButton("Start Acquisition", variant="primary")
        layout.addWidget(self._start_button, stretch=1)

    def set_live_streaming(self, is_streaming: bool) -> None:
        """Update Live button text based on streaming state."""
        self._live_button.setText("Stop" if is_streaming else "Live")


class HaltStageButton(QPushButton):
    """Halt Stage button with reactive styling based on stage movement."""

    def __init__(self, model: InstrumentModel, parent: QWidget | None = None):
        super().__init__("Halt Stage", parent)
        self._model = model
        self._apply_idle_style()

        self.clicked.connect(self._on_clicked)
        model.stageMovingChanged.connect(self._on_stage_moving_changed)

    def _on_clicked(self) -> None:
        """Handle click - halt stage."""
        self._model.halt_stage()

    def _on_stage_moving_changed(self, is_moving: bool) -> None:
        """Update style based on stage movement."""
        if is_moving:
            self._apply_moving_style()
        else:
            self._apply_idle_style()

    def _apply_idle_style(self) -> None:
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
            QPushButton:hover { background-color: #4a4a4d; border-color: #606060; }
            QPushButton:pressed { background-color: #2d2d30; }
        """)

    def _apply_moving_style(self) -> None:
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
            QPushButton:hover { background-color: #d63a2b; border-color: #e64a3b; }
            QPushButton:pressed { background-color: #a52414; }
        """)


class ExASPIMUI(QMainWindow):
    def __init__(self, session: Session, window_title: str = "ExA-SPIM Control"):
        super().__init__()

        self._session = session

        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        self._is_closing = False  # flag to signal workers to stop

        # Livestream state
        self._is_livestreaming = False

        # Live viewer (embedded + expandable to napari)
        self.live_viewer = LiveViewer(
            title=f"Live: {self.instrument.camera.uid}",
            camera_rotation_deg=self.instrument.cfg.globals.camera_rotation_deg,
            parent=self,  # Napari window will be child of main window
        )

        # Create InstrumentModel (wraps all adapters + reactive stage state)
        self._model = InstrumentModel(self.instrument, parent=self)
        self._model.start_polling()

        # Sync FOV dimensions to plan (camera settings → grid calculations)
        self._model.fovDimensionsChanged.connect(self._sync_fov_to_plan)
        self._sync_fov_to_plan(self._model.fov_dimensions)  # sync initial value

        self._actions_card = ActionsCard(
            model=self._model,
            profile_names=self._model.profile_names,
            parent=self,
        )
        self._actions_card.liveClicked.connect(self._toggle_livestream)
        self._actions_card.snapshotClicked.connect(self._take_snapshot)
        self._actions_card.startAcquisitionClicked.connect(self._start_acquisition)
        self._actions_card.profileChanged.connect(self._on_profile_changed)

        self._halt_stage_button = HaltStageButton(model=self._model, parent=self)

        # Device widgets
        self._primary_controls = PrimaryControls(model=self._model, parent=self)
        self._fw_widgets = {uid: FilterWheelWidget(fw, parent=self) for uid, fw in self._model.filter_wheels.items()}

        self._volume_graphic = VolumeGraphic(model=self._model, plan=self._session.state.plan, parent=self)

        self._planner = SessionPlanner(model=self._model, plan=self._session.state.plan, parent=self)
        self._planner.planChanged.connect(self._volume_graphic.refresh)

        self._frame_task_panel = FrameTaskPanel(model=self._model, parent=self)

        self._devices_explorer = DevicesExplorer(model=self._model, parent=self)

        # Metadata editor (edits session.state.metadata)
        self._metadata_editor = MetadataEditor(session=self._session, parent=self)

        self._left_bottom_tabs = [
            Tab("Grid", self._planner),
            Tab("Waveforms", self._frame_task_panel),
            Tab(
                "Filters",
                Grid(*self._fw_widgets.values(), columns=2),
            ),
        ]

        self._right_tabs = [
            Tab("Experiment", self._metadata_editor),
            Tab("Control", self._primary_controls),
            Tab("Devices", self._devices_explorer),
        ]

        self._setup_ui()

        self.setWindowTitle(window_title)

        self.log.info("InstrumentUI initialized")

    @property
    def instrument(self) -> Instrument:
        return self._session.instrument

    def _sync_fov_to_plan(self, dims: list[float]) -> None:
        """Sync FOV dimensions from stage model to acquisition plan."""
        self._session.state.plan.fov_width = dims[0]
        self._session.state.plan.fov_height = dims[1]

    ############################### Setup UI ###############################

    def _setup_ui(self) -> None:
        """Create the main UI layout."""
        # Central widget with horizontal splitter
        central = QWidget()
        main_layout = QHBoxLayout(central)

        # Main horizontal splitter: left (visualization) | right (controls)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # LEFT PANEL: Vertical splitter for 3D view + table
        main_splitter.addWidget(self._setup_left_panel())

        # RIGHT PANEL: Tabbed interface
        main_splitter.addWidget(self._setup_right_panel())

        # Set initial splitter sizes (70% left, 30% right)
        main_splitter.setSizes([700, 300])

        main_layout.addWidget(main_splitter)
        self.setCentralWidget(central)

        # Menu bar
        self._setup_menu_bar()

        self.log.info("UI layout created")

    def _setup_left_panel(self) -> QWidget:
        """Create left panel: VolumeGraphic + LiveViewer (top) + Tabbed bottom (Grid, Waveforms, etc.)."""
        left_splitter = QSplitter(Qt.Orientation.Vertical)

        # TOP ROW: VolumeGraphic + LiveViewer side by side (min 800px tall)
        top_row = QSplitter(Qt.Orientation.Horizontal)
        top_row.setMinimumHeight(400)

        # Left: VolumeGraphic (3D visualization)
        self._volume_graphic.setMinimumWidth(400)
        self._volume_graphic.setMinimumHeight(400)
        self._volume_graphic.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        top_row.addWidget(self._volume_graphic)

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
        self.left_tabs.setStyleSheet(TAB_WIDGET_STYLE)

        # Add all bottom tabs from declarative list
        for tab in self._left_bottom_tabs:
            self.left_tabs.addTab(tab.widget, tab.name)

        left_splitter.addWidget(self.left_tabs)

        # Set initial sizes (70% top row, 30% tabs)
        left_splitter.setSizes([700, 300])

        return left_splitter

    def _setup_right_panel(self) -> QWidget:
        """Create right panel: actions card at top + tabs with anchors at bottom."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Actions card at top (fixed height)
        layout.addWidget(self._actions_card)

        # Tabs with tab bar at bottom (takes remaining space)
        self.right_tabs = QTabWidget()
        self.right_tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.right_tabs.setStyleSheet(TAB_WIDGET_STYLE)

        # Add halt stage button to right corner of tab bar
        self.right_tabs.setCornerWidget(self._halt_stage_button, Qt.Corner.BottomRightCorner)

        # Add all right tabs from declarative list
        for tab in self._right_tabs:
            self.right_tabs.addTab(tab.widget, tab.name)

        self.right_tabs.setCurrentIndex(1)

        layout.addWidget(self.right_tabs, stretch=1)

        return panel

    def _setup_menu_bar(self) -> None:
        """Create menu bar."""

        def _on_save_session() -> None:
            """Manually save session state."""
            self._session.save_state()
            self.log.info(f"Session saved to {self._session.state_path}")

        # File menu
        if (file_menu := self.menuBar()) is not None:
            file_menu.addMenu("&File")

            # Save Session action
            save_session_action = QAction("&Save Session", self)
            save_session_action.triggered.connect(_on_save_session)
            file_menu.addAction(save_session_action)

            # Exit action
            exit_action = QAction("E&xit", self)
            exit_action.triggered.connect(self.close)
            file_menu.addAction(exit_action)

    ############################### Functionality ###############################

    def _start_acquisition(self) -> None:
        """Start acquisition (placeholder)."""
        self.log.info("Start acquisition clicked")

    def _toggle_livestream(self) -> None:
        """Toggle livestream and update button state."""
        if self._is_livestreaming:
            self._model.stop_streaming()
            self._is_livestreaming = False
            self._actions_card.set_live_streaming(False)
        else:
            self.live_viewer.reset()
            self._model.start_streaming(
                on_preview=self.live_viewer.update_preview,
                raw_frame_sink=lambda frame, _idx: self.live_viewer.update_frame(frame),
            )
            self._is_livestreaming = True
            self._actions_card.set_live_streaming(True)

    def _take_snapshot(self) -> None:
        """Take a single snapshot from the camera."""
        self._model.take_snapshot()

    def _on_profile_changed(self, profile_name: str) -> None:
        """Handle profile change from actions card."""
        self._model.set_active_profile(profile_name)

    def close(self) -> bool:
        self.log.info("Closing InstrumentUI")
        self._is_closing = True
        self._model.stop_polling()
        self.live_viewer.close()
        # Note: Session.close() handles instrument cleanup, called by Launcher._on_quit()
        return super().close()
