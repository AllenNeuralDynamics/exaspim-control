"""Unified launcher window for session selection."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from exaspim_control._qtgui.assets import APP_ICON
from exaspim_control._qtgui.primitives.button import VButton
from exaspim_control.session import InstrumentTemplates, LaunchConfig, Session, SessionValues

# Dark theme colors
_COLORS = {
    "bg_dark": "#1e1e1e",
    "bg_medium": "#252526",
    "bg_light": "#2d2d30",
    "border": "#3c3c3c",
    "border_light": "#4a4a4a",
    "text": "#d4d4d4",
    "text_muted": "#888888",
    "text_disabled": "#6e6e6e",
    "accent": "#3a6ea5",
    "accent_hover": "#4a7eb5",
    "success": "#4ec9b0",
}

_DIALOG_STYLE = f"""
    QDialog {{
        background-color: {_COLORS["bg_dark"]};
    }}
    QLabel {{
        color: {_COLORS["text"]};
    }}
    QLineEdit {{
        background-color: {_COLORS["bg_medium"]};
        color: {_COLORS["text"]};
        border: 1px solid {_COLORS["border"]};
        border-radius: 4px;
        padding: 8px 12px;
        font-size: 12px;
    }}
    QLineEdit:focus {{
        border-color: {_COLORS["accent"]};
    }}
    QLineEdit:disabled {{
        color: {_COLORS["text_disabled"]};
        background-color: {_COLORS["bg_dark"]};
    }}
    QRadioButton {{
        color: {_COLORS["text"]};
        font-size: 12px;
        spacing: 8px;
    }}
    QRadioButton:disabled {{
        color: {_COLORS["text_disabled"]};
    }}
    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 8px;
        border: 2px solid {_COLORS["border_light"]};
        background-color: {_COLORS["bg_medium"]};
    }}
    QRadioButton::indicator:checked {{
        background-color: {_COLORS["accent"]};
        border-color: {_COLORS["accent"]};
    }}
    QRadioButton::indicator:disabled {{
        border-color: {_COLORS["border"]};
        background-color: {_COLORS["bg_dark"]};
    }}
    QComboBox {{
        background-color: {_COLORS["bg_medium"]};
        color: {_COLORS["text"]};
        border: 1px solid {_COLORS["border"]};
        border-radius: 4px;
        padding: 6px 12px;
        font-size: 12px;
        min-height: 20px;
    }}
    QComboBox:disabled {{
        color: {_COLORS["text_disabled"]};
        background-color: {_COLORS["bg_dark"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {_COLORS["bg_medium"]};
        color: {_COLORS["text"]};
        border: 1px solid {_COLORS["border"]};
        selection-background-color: {_COLORS["accent"]};
    }}
"""


class _VDialog(QDialog):
    """Base dialog with dark theme styling."""

    def __init__(self, parent: QWidget | None = None, title: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(_DIALOG_STYLE)


class _DialogHeader(QLabel):
    """Styled header label for dialogs."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setMinimumHeight(28)
        self.setStyleSheet(f"""
            QLabel {{
                font-size: 13px;
                font-weight: 600;
                color: {_COLORS["text"]};
                padding: 4px 0px 8px 0px;
            }}
        """)


class _DialogTitle(QLabel):
    """Large title for launcher dialogs."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(32)
        self.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: 600;
                color: #ffffff;
                padding: 4px 0px;
            }
        """)


class _DialogButtonRow(QWidget):
    """Horizontal button row for dialog actions."""

    def __init__(self, parent: QWidget | None = None, align: str = "right"):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 8, 0, 0)
        self._layout.setSpacing(8)

        if align in ("right", "center"):
            self._layout.addStretch()

    def add_button(self, button: VButton) -> VButton:
        """Add a button to the row."""
        self._layout.addWidget(button)
        return button


class _SectionCard(QFrame):
    """Card container for a section with border."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            _SectionCard {{
                background-color: {_COLORS["bg_medium"]};
                border: 1px solid {_COLORS["border"]};
                border-radius: 6px;
            }}
        """)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 12)
        self._layout.setSpacing(8)

        # Section title
        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: 12px;
                font-weight: 600;
                color: {_COLORS["text"]};
            }}
        """)
        self._layout.addWidget(title_label)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


class _StatusLabel(QLabel):
    """Small status indicator label."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QLabel {{
                font-size: 11px;
                color: {_COLORS["text_muted"]};
                padding-left: 24px;
            }}
        """)

    def set_found(self, found: bool, filename: str) -> None:
        if found:
            self.setText(f"✓ {filename} found")
            self.setStyleSheet(f"""
                QLabel {{
                    font-size: 11px;
                    color: {_COLORS["success"]};
                    padding-left: 24px;
                }}
            """)
        else:
            self.setText(f"✗ {filename} not found")
            self.setStyleSheet(f"""
                QLabel {{
                    font-size: 11px;
                    color: {_COLORS["text_muted"]};
                    padding-left: 24px;
                }}
            """)


class LauncherWindow(_VDialog):
    """Unified session launcher dialog.

    Two-section design with independent Config and State choices.
    """

    def __init__(self, parent: QWidget | None = None, *, initial_path: str | None = None):
        super().__init__(parent, title="ExA-SPIM Control")
        self.setMinimumSize(520, 480)
        self._launch_config: LaunchConfig | None = None
        self._initial_path = initial_path
        self._has_config = False
        self._has_state = False
        self._setup_ui()
        self._connect_signals()

        # Trigger initial state if path provided
        if initial_path:
            self._on_path_changed(initial_path)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        # Icon + Title
        if APP_ICON.exists():
            icon_label = QLabel()
            icon_label.setPixmap(QIcon(str(APP_ICON)).pixmap(48, 48))
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_label)

        title = _DialogTitle("ExA-SPIM Control")
        layout.addWidget(title)

        layout.addSpacing(4)

        # Session Directory section
        dir_header = _DialogHeader("Session Directory")
        layout.addWidget(dir_header)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)

        self._path_input = QLineEdit()
        self._path_input.setPlaceholderText("Select a directory...")
        if self._initial_path:
            self._path_input.setText(self._initial_path)
        dir_row.addWidget(self._path_input, stretch=1)

        self._browse_btn = VButton("Browse", variant="secondary")
        self._browse_btn.setFixedWidth(80)
        dir_row.addWidget(self._browse_btn)

        layout.addLayout(dir_row)

        layout.addSpacing(8)

        # ═══════════════════════════════════════════════════════════════
        # Config Section
        # ═══════════════════════════════════════════════════════════════
        self._config_card = _SectionCard("Instrument Config")

        # Use existing radio
        self._use_existing_radio = QRadioButton("Use existing config")
        self._config_card.add_widget(self._use_existing_radio)

        self._config_status = _StatusLabel()
        self._config_card.add_widget(self._config_status)

        # Copy from radio + combo
        copy_row = QHBoxLayout()
        copy_row.setSpacing(8)

        self._copy_from_radio = QRadioButton("Copy from:")
        copy_row.addWidget(self._copy_from_radio)

        self._instrument_combo = QComboBox()
        self._instrument_combo.setMinimumWidth(200)
        copy_row.addWidget(self._instrument_combo, stretch=1)

        self._config_card.add_layout(copy_row)

        # Config button group
        self._config_group = QButtonGroup(self)
        self._config_group.addButton(self._use_existing_radio, 0)
        self._config_group.addButton(self._copy_from_radio, 1)

        self._config_card.setVisible(False)
        layout.addWidget(self._config_card)

        # ═══════════════════════════════════════════════════════════════
        # State Section
        # ═══════════════════════════════════════════════════════════════
        self._state_card = _SectionCard("Session State")

        # Resume radio
        self._resume_radio = QRadioButton("Resume previous")
        self._state_card.add_widget(self._resume_radio)

        self._state_status = _StatusLabel()
        self._state_card.add_widget(self._state_status)

        # Fresh start radio
        self._fresh_radio = QRadioButton("Fresh start")
        self._state_card.add_widget(self._fresh_radio)

        fresh_hint = QLabel("Backs up existing state and starts clean")
        fresh_hint.setStyleSheet(f"""
            QLabel {{
                font-size: 11px;
                color: {_COLORS["text_muted"]};
                padding-left: 24px;
            }}
        """)
        self._state_card.add_widget(fresh_hint)

        # State button group
        self._state_group = QButtonGroup(self)
        self._state_group.addButton(self._resume_radio, 0)
        self._state_group.addButton(self._fresh_radio, 1)

        self._state_card.setVisible(False)
        layout.addWidget(self._state_card)

        layout.addStretch()

        # Button row
        button_row = _DialogButtonRow(align="right")
        self._cancel_btn = button_row.add_button(VButton("Cancel", variant="secondary"))
        self._launch_btn = button_row.add_button(VButton("Launch", variant="primary"))
        self._launch_btn.setEnabled(False)
        self._launch_btn.setDefault(True)
        layout.addWidget(button_row)

        # Populate instrument combo
        self._populate_instruments()

    def _populate_instruments(self) -> None:
        """Populate instrument dropdown with available templates."""
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
        self._cancel_btn.clicked.connect(self.reject)
        self._launch_btn.clicked.connect(self._on_launch)

    def _on_browse(self) -> None:
        """Open directory picker."""
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
        """Handle directory path changes."""
        has_path = bool(path)
        self._config_card.setVisible(has_path)
        self._state_card.setVisible(has_path)

        if has_path:
            # Inspect directory
            info = Session.inspect_directory(Path(path))
            self._has_config = info.has_config
            self._has_state = info.has_state

            # Update config section
            self._config_status.set_found(self._has_config, SessionValues.CONFIG_FILENAME)
            self._use_existing_radio.setEnabled(self._has_config)

            if self._has_config:
                self._use_existing_radio.setChecked(True)
            else:
                self._copy_from_radio.setChecked(True)

            # Update state section
            self._state_status.set_found(self._has_state, SessionValues.STATE_FILENAME)
            self._resume_radio.setEnabled(self._has_state)

            if self._has_state:
                self._resume_radio.setChecked(True)
            else:
                self._fresh_radio.setChecked(True)

        self._on_config_choice_changed()
        self._update_launch_button()

    def _on_config_choice_changed(self) -> None:
        """Handle config radio button changes."""
        use_existing = self._use_existing_radio.isChecked()
        self._instrument_combo.setEnabled(not use_existing)
        self._update_launch_button()

    def _update_launch_button(self) -> None:
        """Update launch button enabled state."""
        path = self._path_input.text()
        if not path:
            self._launch_btn.setEnabled(False)
            return

        # Check config choice is valid
        if self._use_existing_radio.isChecked():
            config_valid = self._has_config
        else:
            config_valid = self._instrument_combo.currentData() is not None

        # State choice is always valid (fresh start is always available)
        self._launch_btn.setEnabled(config_valid)

    def _on_launch(self) -> None:
        """Handle launch button click."""
        path = self._path_input.text()
        if not path:
            return

        # Determine instrument value
        if self._use_existing_radio.isChecked():
            instrument = SessionValues.EXISTING_CONFIG
        else:
            instrument = self._instrument_combo.currentData()
            if instrument is None:
                return

        # Determine state
        fresh_state = self._fresh_radio.isChecked()

        self._launch_config = LaunchConfig(
            session_dir=Path(path),
            instrument=instrument,
            fresh_state=fresh_state,
        )
        self.accept()

    @property
    def launch_config(self) -> LaunchConfig | None:
        """Get the launch configuration after dialog is accepted."""
        return self._launch_config

    @classmethod
    def get_launch_config(
        cls,
        parent: QWidget | None = None,
        *,
        initial_path: str | None = None,
    ) -> LaunchConfig | None:
        """Show launcher and return launch configuration.

        Args:
            parent: Parent widget for the dialog.
            initial_path: Pre-fill session directory path (e.g., from CLI argument).

        Returns:
            LaunchConfig if user accepted, None if cancelled.
        """
        dialog = cls(parent, initial_path=initial_path)
        if dialog.exec() == _VDialog.DialogCode.Accepted:
            return dialog.launch_config
        return None
