"""Unified launcher window for session selection."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from exaspim_control.qtgui.assets import APP_ICON
from exaspim_control.qtgui.primitives.button import VButton
from exaspim_control.session.session import LaunchConfig, SessionLauncher

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
}

_DIALOG_STYLE = f"""
    QDialog {{
        background-color: {_COLORS["bg_dark"]};
    }}
    QLabel {{
        color: {_COLORS["text"]};
    }}
    QListWidget {{
        background-color: {_COLORS["bg_medium"]};
        color: {_COLORS["text"]};
        border: 1px solid {_COLORS["border"]};
        border-radius: 4px;
        font-size: 12px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 4px 8px;
        margin: 2px 4px;
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background-color: {_COLORS["accent"]};
        color: white;
    }}
    QListWidget::item:hover:!selected {{
        background-color: {_COLORS["bg_light"]};
    }}
    QListWidget::item:disabled {{
        color: {_COLORS["text_disabled"]};
        background-color: transparent;
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


# Special value for "Local" instrument option
LOCAL_INSTRUMENT = "__local__"


class LauncherWindow(_VDialog):
    """Unified session launcher dialog.

    Combines directory selection, instrument picking, and state options
    in a single dialog.
    """

    def __init__(self, parent: QWidget | None = None, *, initial_path: str | None = None):
        super().__init__(parent, title="ExA-SPIM Control")
        self.setMinimumSize(500, 520)
        self._launch_config: LaunchConfig | None = None
        self._initial_path = initial_path
        self._setup_ui()
        self._connect_signals()
        # Trigger path change handling if initial path provided
        if initial_path:
            self._on_path_changed(initial_path)
        else:
            self._update_instrument_list()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        # Icon + Title
        if APP_ICON.exists():
            icon_label = QLabel()
            icon_label.setPixmap(QIcon(str(APP_ICON)).pixmap(48, 48))
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_label)

        title = _DialogTitle("ExA-SPIM Control")
        layout.addWidget(title)

        layout.addSpacing(8)

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

        # Instrument section (hidden until path selected)
        self._instrument_section = QWidget()
        inst_layout = QVBoxLayout(self._instrument_section)
        inst_layout.setContentsMargins(0, 0, 0, 0)
        inst_layout.setSpacing(8)

        inst_header = _DialogHeader("Instrument")
        inst_layout.addWidget(inst_header)

        self._instrument_combo = QComboBox()
        self._instrument_combo.setMinimumHeight(32)
        inst_layout.addWidget(self._instrument_combo)

        self._instrument_section.setVisible(False)
        layout.addWidget(self._instrument_section)

        layout.addSpacing(8)

        # State options section (hidden until path selected)
        self._state_section = QWidget()
        state_layout_container = QVBoxLayout(self._state_section)
        state_layout_container.setContentsMargins(0, 0, 0, 0)
        state_layout_container.setSpacing(6)

        state_header = _DialogHeader("State")
        state_layout_container.addWidget(state_header)

        radio_row = QHBoxLayout()
        radio_row.setSpacing(16)

        self._reuse_radio = QRadioButton("Reuse state")
        self._clean_radio = QRadioButton("Clean state")
        self._reuse_radio.setChecked(True)

        self._state_group = QButtonGroup(self)
        self._state_group.addButton(self._reuse_radio)
        self._state_group.addButton(self._clean_radio)

        radio_row.addWidget(self._reuse_radio)
        radio_row.addWidget(self._clean_radio)
        radio_row.addStretch()

        state_layout_container.addLayout(radio_row)

        self._state_section.setVisible(False)
        layout.addWidget(self._state_section)

        layout.addStretch()

        # Button row
        button_row = _DialogButtonRow(align="right")
        self._cancel_btn = button_row.add_button(VButton("Cancel", variant="secondary"))
        self._launch_btn = button_row.add_button(VButton("Launch", variant="primary"))
        self._launch_btn.setEnabled(False)
        self._launch_btn.setDefault(True)
        layout.addWidget(button_row)

    def _connect_signals(self) -> None:
        self._browse_btn.clicked.connect(self._on_browse)
        self._path_input.textChanged.connect(self._on_path_changed)
        self._instrument_combo.currentIndexChanged.connect(self._on_instrument_changed)
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
        self._instrument_section.setVisible(has_path)
        self._state_section.setVisible(has_path)
        self._update_instrument_list()
        self._update_launch_button()

    def _update_instrument_list(self) -> None:
        """Refresh instrument dropdown based on current directory."""
        self._instrument_combo.clear()

        session_dir = Path(self._path_input.text()) if self._path_input.text() else None
        has_local_config = (
            session_dir is not None
            and session_dir.exists()
            and (session_dir / SessionLauncher.CONFIG_FILENAME).exists()
        )

        # Add "Local" option if config exists
        if has_local_config:
            self._instrument_combo.addItem("Local (resume session)", LOCAL_INSTRUMENT)

        # Add available instruments
        instruments = SessionLauncher.available_instruments()

        if not instruments and not has_local_config:
            self._instrument_combo.addItem("No instruments found", None)
            return

        for name, is_valid in sorted(instruments.items()):
            if is_valid:
                self._instrument_combo.addItem(name, name)
            # Skip invalid instruments in dropdown (cleaner than showing disabled)

    def _on_instrument_changed(self, _index: int) -> None:
        """Handle instrument selection change."""
        instrument_value = self._instrument_combo.currentData()
        is_local = instrument_value == LOCAL_INSTRUMENT

        # Enable/disable state radio based on selection
        self._reuse_radio.setEnabled(is_local)
        self._clean_radio.setEnabled(is_local)

        if not is_local:
            # Force clean state for non-local instruments
            self._clean_radio.setChecked(True)
        else:
            # Default to reuse for local
            self._reuse_radio.setChecked(True)

        self._update_launch_button()

    def _update_launch_button(self) -> None:
        """Update launch button enabled state."""
        path = self._path_input.text()
        instrument_value = self._instrument_combo.currentData()

        has_path = bool(path)
        has_valid_selection = instrument_value is not None

        self._launch_btn.setEnabled(has_path and has_valid_selection)

    def _on_launch(self) -> None:
        """Handle launch button click."""
        path = self._path_input.text()
        instrument_value = self._instrument_combo.currentData()

        if not path or instrument_value is None:
            return

        is_local = instrument_value == LOCAL_INSTRUMENT

        self._launch_config = LaunchConfig(
            session_dir=Path(path),
            instrument=None if is_local else instrument_value,
            clean_state=self._clean_radio.isChecked(),
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
            LaunchConfig with session_dir, instrument (None for local), and clean_state.
            Returns None if user cancelled.
        """
        dialog = cls(parent, initial_path=initial_path)
        if dialog.exec() == _VDialog.DialogCode.Accepted:
            return dialog.launch_config
        return None
