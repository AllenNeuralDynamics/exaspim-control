"""LaunchPage - Session selection page for the stacked widget app."""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from exaspim_control._qtgui.assets import APP_ICON
from exaspim_control._qtgui.primitives import Button, Card, Colors, ComboBox, LineEdit, RadioButton
from exaspim_control.session import InstrumentTemplates, LaunchConfig, Session, SessionValues


class _StatusLabel(QLabel):
    """Small status indicator label."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._set_style(False)

    def _set_style(self, success: bool) -> None:
        color = Colors.SUCCESS if success else Colors.TEXT_MUTED
        self.setStyleSheet(f"""
            QLabel {{
                font-size: 11px;
                color: {color};
                padding-left: 24px;
            }}
        """)

    def set_found(self, found: bool, filename: str) -> None:
        self.setText(f"{'✓' if found else '✗'} {filename} {'found' if found else 'not found'}")
        self._set_style(found)


class LaunchPage(QWidget):
    """Session selection page.

    Emits launchRequested with LaunchConfig when user clicks Launch.
    Emits cancelRequested when user clicks Cancel.
    """

    launchRequested = pyqtSignal(LaunchConfig)
    cancelRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, *, initial_path: str | None = None):
        super().__init__(parent)
        self._initial_path = initial_path
        self._has_config = False
        self._has_state = False

        self._setup_ui()
        self._connect_signals()

        if initial_path:
            self._on_path_changed(initial_path)

    def _setup_ui(self) -> None:
        # Apply dark theme styling (primitives handle their own styling)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {Colors.BG_DARK};
            }}
            QLabel {{
                color: {Colors.TEXT};
            }}
        """)

        # Center content with constrained width
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Container for centered content
        container = QWidget()
        container.setMinimumWidth(500)
        container.setMaximumWidth(700)

        layout = QVBoxLayout(container)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 40, 24, 40)

        # Icon + Title
        if APP_ICON.exists():
            icon_label = QLabel()
            icon_label.setPixmap(QIcon(str(APP_ICON)).pixmap(48, 48))
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_label)

        title = QLabel("ExA-SPIM Control")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"""
            QLabel {{
                font-size: 18px;
                font-weight: 600;
                color: {Colors.TEXT_BRIGHT};
                padding: 4px 0px;
            }}
        """)
        layout.addWidget(title)

        layout.addSpacing(4)

        # Session Directory section
        dir_header = QLabel("Session Directory")
        dir_header.setStyleSheet(f"""
            QLabel {{
                font-size: 13px;
                font-weight: 600;
                color: {Colors.TEXT};
                padding: 4px 0px 8px 0px;
            }}
        """)
        layout.addWidget(dir_header)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)

        self._path_input = LineEdit(placeholder="Select a directory...")
        if self._initial_path:
            self._path_input.setText(self._initial_path)
        dir_row.addWidget(self._path_input, stretch=1)

        self._browse_btn = Button("Browse", variant="secondary")
        self._browse_btn.setFixedWidth(80)
        dir_row.addWidget(self._browse_btn)

        layout.addLayout(dir_row)
        layout.addSpacing(8)

        self._use_existing_radio = RadioButton("Use existing config")
        self._config_status = _StatusLabel()
        # Config Section

        copy_row = QHBoxLayout()
        copy_row.setSpacing(8)

        self._copy_from_radio = RadioButton("Copy from:")
        copy_row.addWidget(self._copy_from_radio)

        self._instrument_combo = ComboBox()
        self._instrument_combo.setMinimumWidth(200)
        copy_row.addWidget(self._instrument_combo, stretch=1)

        self._config_card = Card("Instrument Config", self._use_existing_radio, self._config_status, copy_row)

        self._config_group = QButtonGroup(self)
        self._config_group.addButton(self._use_existing_radio, 0)
        self._config_group.addButton(self._copy_from_radio, 1)

        self._config_card.setVisible(False)
        layout.addWidget(self._config_card)

        # State Section

        self._resume_radio = RadioButton("Resume previous")

        self._state_status = _StatusLabel()

        self._fresh_radio = RadioButton("Fresh start")

        fresh_hint = QLabel("Backs up existing state and starts clean")
        fresh_hint.setStyleSheet(f"""
            QLabel {{
                font-size: 11px;
                color: {Colors.TEXT_MUTED};
                padding-left: 24px;
            }}
        """)
        self._state_card = Card("Session State", self._resume_radio, self._state_status, self._fresh_radio, fresh_hint)

        self._state_group = QButtonGroup(self)
        self._state_group.addButton(self._resume_radio, 0)
        self._state_group.addButton(self._fresh_radio, 1)

        self._state_card.setVisible(False)
        layout.addWidget(self._state_card)

        layout.addStretch()

        # Button row
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 8, 0, 0)
        button_row.setSpacing(8)
        button_row.addStretch()

        self._cancel_btn = Button("Cancel", variant="secondary")
        button_row.addWidget(self._cancel_btn)

        self._launch_btn = Button("Launch", variant="primary")
        self._launch_btn.setEnabled(False)
        self._launch_btn.setDefault(True)
        button_row.addWidget(self._launch_btn)

        layout.addLayout(button_row)

        # Center the container
        outer_layout.addStretch()
        outer_layout.addWidget(container, alignment=Qt.AlignmentFlag.AlignCenter)
        outer_layout.addStretch()

        self._populate_instruments()

    def _populate_instruments(self) -> None:
        self._instrument_combo.clear()
        instruments = InstrumentTemplates.list()

        if not instruments:
            self._instrument_combo.addItem("No instruments found", None)
            return

        for name, is_valid in sorted(instruments.items()):
            if is_valid:
                self._instrument_combo.addItem(name, name)

    def _connect_signals(self) -> None:
        self._browse_btn.clicked.connect(self._on_browse)
        self._path_input.textChanged.connect(self._on_path_changed)
        self._config_group.buttonClicked.connect(self._on_config_choice_changed)
        self._state_group.buttonClicked.connect(self._update_launch_button)
        self._cancel_btn.clicked.connect(self.cancelRequested.emit)
        self._launch_btn.clicked.connect(self._on_launch)

    def _on_browse(self) -> None:
        current = self._path_input.text()
        start_dir = current if current and Path(current).exists() else ""

        path = QFileDialog.getExistingDirectory(
            self,
            "Select Session Directory",
            start_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if path:
            self._path_input.setText(path)

    def _on_path_changed(self, path: str) -> None:
        has_path = bool(path)
        self._config_card.setVisible(has_path)
        self._state_card.setVisible(has_path)

        if has_path:
            info = Session.inspect_directory(Path(path))
            self._has_config = info.has_config
            self._has_state = info.has_state

            self._config_status.set_found(self._has_config, SessionValues.CONFIG_FILENAME)
            self._use_existing_radio.setEnabled(self._has_config)

            if self._has_config:
                self._use_existing_radio.setChecked(True)
            else:
                self._copy_from_radio.setChecked(True)

            self._state_status.set_found(self._has_state, SessionValues.STATE_FILENAME)
            self._resume_radio.setEnabled(self._has_state)

            if self._has_state:
                self._resume_radio.setChecked(True)
            else:
                self._fresh_radio.setChecked(True)

        self._on_config_choice_changed()
        self._update_launch_button()

    def _on_config_choice_changed(self) -> None:
        use_existing = self._use_existing_radio.isChecked()
        self._instrument_combo.setEnabled(not use_existing)
        self._update_launch_button()

    def _update_launch_button(self) -> None:
        path = self._path_input.text()
        if not path:
            self._launch_btn.setEnabled(False)
            return

        if self._use_existing_radio.isChecked():
            config_valid = self._has_config
        else:
            config_valid = self._instrument_combo.currentData() is not None

        self._launch_btn.setEnabled(config_valid)

    def _on_launch(self) -> None:
        path = self._path_input.text()
        if not path:
            return

        if self._use_existing_radio.isChecked():
            instrument = SessionValues.EXISTING_CONFIG
        else:
            instrument = self._instrument_combo.currentData()
            if instrument is None:
                return

        fresh_state = self._fresh_radio.isChecked()

        config = LaunchConfig(
            session_dir=Path(path),
            instrument=instrument,
            fresh_state=fresh_state,
        )
        self.launchRequested.emit(config)

    def set_initial_path(self, path: str) -> None:
        """Set the initial session path (e.g., from CLI argument)."""
        self._path_input.setText(path)
