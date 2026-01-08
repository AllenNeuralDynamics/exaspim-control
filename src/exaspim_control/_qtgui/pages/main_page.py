"""MainPage - Main application content widget for the stacked widget app."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from exaspim_control._qtgui.model import InstrumentModel
from exaspim_control._qtgui.primitives import Button, Colors, ComboBox, Grid, TabWidget
from exaspim_control._qtgui.widgets.device_explorer import DevicesExplorer
from exaspim_control._qtgui.widgets.devices.filter_wheel import FilterWheelWidget
from exaspim_control._qtgui.widgets.frame_task_panel import FrameTaskPanel
from exaspim_control._qtgui.widgets.live_viewer import LiveViewer
from exaspim_control._qtgui.widgets.log_viewer import LogViewer
from exaspim_control._qtgui.widgets.metadata_editor import MetadataEditor
from exaspim_control._qtgui.widgets.primary_controls import PrimaryControls
from exaspim_control._qtgui.widgets.session_planner import SessionPlanner
from exaspim_control._qtgui.widgets.volume_graphic import VolumeGraphic
from exaspim_control.instrument.instrument import Instrument, InstrumentMode

if TYPE_CHECKING:
    from collections.abc import Sequence

    from exaspim_control.session import Session


class _Tab:
    """Declarative tab definition."""

    def __init__(self, name: str, widget: QWidget):
        self.name = name
        self.widget = widget


class _ActionsCard(QWidget):
    """Actions card with acquisition controls.

    Layout: [▼Profile] [Live] [Snapshot] [Start Acquisition]
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

        self._live_button.clicked.connect(self.liveClicked.emit)
        self._snapshot_button.clicked.connect(self.snapshotClicked.emit)
        self._start_button.clicked.connect(self.startAcquisitionClicked.emit)
        self._profiles_combo.currentTextChanged.connect(self.profileChanged.emit)

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.setStyleSheet(f"""
            _ActionsCard {{
                background-color: {Colors.BG_LIGHT};
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
            }}
        """)

        self._profiles_combo = ComboBox(items=list(self._profile_names))
        layout.addWidget(self._profiles_combo)

        self._live_button = Button("Start Preview", variant="secondary")
        layout.addWidget(self._live_button, stretch=1)

        self._snapshot_button = Button("Snapshot", variant="secondary")
        layout.addWidget(self._snapshot_button, stretch=1)

        self._start_button = Button("Start Acquisition", variant="primary")
        layout.addWidget(self._start_button, stretch=1)

    def update_mode(self, mode: InstrumentMode) -> None:
        """Update preview button based on instrument mode."""
        if mode == InstrumentMode.IDLE:
            self._live_button.setText("Start Preview")
            self._live_button.setEnabled(True)
        elif mode == InstrumentMode.PREVIEW:
            self._live_button.setText("Stop Preview")
            self._live_button.setEnabled(True)
        elif mode == InstrumentMode.ACQUISITION:
            self._live_button.setText("Acquiring...")
            self._live_button.setEnabled(False)


class _HaltStageButton(Button):
    """Halt Stage button with reactive styling based on stage movement.

    Uses Button primitive with variant switching between 'secondary' (idle)
    and 'danger' (stage moving).
    """

    def __init__(self, model: InstrumentModel, parent: QWidget | None = None):
        super().__init__("Halt Stage", variant="secondary", parent=parent)
        self._model = model

        self.clicked.connect(self._on_clicked)
        model.stageMovingChanged.connect(self._on_stage_moving_changed)

    def _on_clicked(self) -> None:
        self._model.halt_stage()

    def _on_stage_moving_changed(self, is_moving: bool) -> None:
        self.variant = "danger" if is_moving else "secondary"


class MainPage(QWidget):
    """Main application content page.

    Contains all the UI from ExASPIMUI but as a QWidget for stacked widget use.
    Emits sessionSaveRequested and closeRequested for the outer QMainWindow to handle.
    """

    sessionSaveRequested = pyqtSignal()
    closeRequested = pyqtSignal()

    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)

        self._session = session
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        self._is_closing = False

        # Create all child widgets
        self._create_widgets()
        self._setup_ui()
        self._connect_signals()

        self.log.info("MainPage initialized")

    @property
    def instrument(self) -> Instrument:
        return self._session.instrument

    @property
    def session(self) -> Session:
        return self._session

    @property
    def model(self) -> InstrumentModel:
        return self._model

    def _create_widgets(self) -> None:
        """Create all child widgets."""
        # Live viewer (lightweight embedded preview)
        self.live_viewer = LiveViewer(
            camera_rotation_deg=self.instrument.cfg.globals.camera_rotation_deg,
            parent=self,
        )

        # Instrument model (wraps all adapters + reactive stage state)
        self._model = InstrumentModel(self.instrument, parent=self)
        self._model.start_polling()

        # Sync FOV dimensions to plan
        self._model.fovDimensionsChanged.connect(self._sync_fov_to_plan)
        self._sync_fov_to_plan(self._model.fov_dimensions)

        # Actions card
        self._actions_card = _ActionsCard(
            model=self._model,
            profile_names=self._model.profile_names,
            parent=self,
        )

        # Connect mode changes to update UI
        self._model.modeChanged.connect(self._actions_card.update_mode)

        self._halt_stage_button = _HaltStageButton(model=self._model, parent=self)

        # Device widgets
        self._primary_controls = PrimaryControls(model=self._model, parent=self)
        self._fw_widgets = {uid: FilterWheelWidget(fw, parent=self) for uid, fw in self._model.filter_wheels.items()}

        self._volume_graphic = VolumeGraphic(model=self._model, plan=self._session.state.plan, parent=self)

        self._planner = SessionPlanner(model=self._model, plan=self._session.state.plan, parent=self)
        self._planner.planChanged.connect(self._volume_graphic.refresh)

        self._frame_task_panel = FrameTaskPanel(model=self._model, parent=self)
        self._devices_explorer = DevicesExplorer(model=self._model, parent=self)
        self._metadata_editor = MetadataEditor(session=self._session, parent=self)

        # Log viewer
        self._log_viewer = LogViewer(parent=self)
        self._log_viewer.install_handler("")

        # Define tabs
        self._left_bottom_tabs = [
            _Tab("Grid", self._planner),
            _Tab("Waveforms", self._frame_task_panel),
            _Tab("Filters", Grid(*self._fw_widgets.values(), columns=2)),
            _Tab("Logs", self._log_viewer),
        ]

        self._right_tabs = [
            _Tab("Experiment", self._metadata_editor),
            _Tab("Control", self._primary_controls),
            _Tab("Devices", self._devices_explorer),
        ]

    def _setup_ui(self) -> None:
        """Create the main UI layout."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Main horizontal splitter: left (visualization) | right (controls)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(self._setup_left_panel())
        main_splitter.addWidget(self._setup_right_panel())
        main_splitter.setSizes([700, 300])

        main_layout.addWidget(main_splitter)

    def _connect_signals(self) -> None:
        """Connect widget signals to handlers."""
        self._actions_card.liveClicked.connect(self._toggle_preview)
        self._actions_card.snapshotClicked.connect(self._take_snapshot)
        self._actions_card.startAcquisitionClicked.connect(self._start_acquisition)
        self._actions_card.profileChanged.connect(self._on_profile_changed)

    def _setup_left_panel(self) -> QWidget:
        """Create left panel: VolumeGraphic + LiveViewer (top) + Tabbed bottom."""
        left_splitter = QSplitter(Qt.Orientation.Vertical)

        # TOP ROW: VolumeGraphic + LiveViewer side by side
        top_row = QSplitter(Qt.Orientation.Horizontal)
        top_row.setMinimumHeight(400)

        self._volume_graphic.setMinimumWidth(400)
        # self._volume_graphic.setMinimumHeight(200)
        self._volume_graphic.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        top_row.addWidget(self._volume_graphic)

        self.live_viewer.setMinimumWidth(400)
        # self.live_viewer.setMinimumHeight(400)
        self.live_viewer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        top_row.addWidget(self.live_viewer)
        top_row.setSizes([500, 500])

        left_splitter.addWidget(top_row)

        # BOTTOM: Tabbed area with tab bar at bottom
        self.left_tabs = TabWidget(position="bottom")
        self.left_tabs.setMinimumHeight(400)

        for tab in self._left_bottom_tabs:
            self.left_tabs.addTab(tab.widget, tab.name)

        left_splitter.addWidget(self.left_tabs)
        left_splitter.setSizes([500, 500])

        return left_splitter

    def _setup_right_panel(self) -> QWidget:
        """Create right panel: actions card at top + tabs with anchors at bottom."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._actions_card)

        self.right_tabs = TabWidget(position="bottom")
        self.right_tabs.setCornerWidget(self._halt_stage_button, Qt.Corner.BottomRightCorner)

        for tab in self._right_tabs:
            self.right_tabs.addTab(tab.widget, tab.name)

        self.right_tabs.setCurrentIndex(1)
        layout.addWidget(self.right_tabs, stretch=1)

        return panel

    def _sync_fov_to_plan(self, dims: list[float]) -> None:
        """Sync FOV dimensions from stage model to acquisition plan."""
        self._session.state.plan.fov_width = dims[0]
        self._session.state.plan.fov_height = dims[1]

    def _start_acquisition(self) -> None:
        """Start acquisition (placeholder)."""
        self.log.info("Start acquisition clicked")

    def _toggle_preview(self) -> None:
        """Toggle preview mode based on current instrument mode."""
        if self._model.mode == InstrumentMode.PREVIEW:
            self._model.stop_preview()
        elif self._model.mode == InstrumentMode.IDLE:
            self.live_viewer.reset()
            self._model.start_preview(
                on_preview=self.live_viewer.update_preview,
                raw_frame_sink=lambda frame, _idx: self.live_viewer.update_frame(frame),
            )

    def _take_snapshot(self) -> None:
        """Take a single snapshot from the camera."""
        self._model.take_snapshot()

    def _on_profile_changed(self, profile_name: str) -> None:
        """Handle profile change from actions card."""
        self._model.set_active_profile(profile_name)

    def save_session(self) -> None:
        """Save session state."""
        self._session.save_state()
        self.log.info(f"Session saved to {self._session.state_path}")

    def cleanup(self) -> None:
        """Clean up resources before closing."""
        self.log.info("Cleaning up MainPage")
        self._is_closing = True
        self._model.stop_polling()
        self.live_viewer.close()
