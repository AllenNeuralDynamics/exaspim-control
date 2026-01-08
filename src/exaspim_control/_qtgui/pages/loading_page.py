"""LoadingPage - Session initialization page with progress indicator and logs."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from exaspim_control._qtgui.primitives import Button, Colors, Spinner
from exaspim_control._qtgui.widgets.log_viewer import LogViewer


class LoadingPage(QWidget):
    """Loading page with spinner, status text, and log viewer.

    Emits cancelRequested when user clicks Cancel.
    """

    cancelRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {Colors.BG_DARK};
            }}
            QLabel {{
                color: {Colors.TEXT};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header with spinner and status
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(16)

        self._spinner = Spinner(size=32)
        header_layout.addWidget(self._spinner)

        self._status_label = QLabel("Initializing session...")
        self._status_label.setStyleSheet(f"""
            QLabel {{
                font-size: 14px;
                font-weight: 600;
                color: {Colors.TEXT};
            }}
        """)
        header_layout.addWidget(self._status_label)
        header_layout.addStretch()

        self._cancel_btn = Button("Cancel", variant="secondary")
        self._cancel_btn.clicked.connect(self.cancelRequested.emit)
        header_layout.addWidget(self._cancel_btn)

        layout.addWidget(header)

        # Log viewer takes up most space
        self._log_viewer = LogViewer()
        self._log_viewer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._log_viewer, stretch=1)

    def start(self) -> None:
        """Start the loading page (start spinner, install log handler)."""
        self._spinner.start()
        self._log_viewer.install_handler()  # Capture root logger

    def stop(self) -> None:
        """Stop the loading page (stop spinner, remove log handler)."""
        self._spinner.stop()
        self._log_viewer.remove_handler()

    def set_status(self, message: str) -> None:
        """Update the status message."""
        self._status_label.setText(message)

    def set_error(self, message: str) -> None:
        """Display an error status."""
        self._status_label.setText(f"Error: {message}")
        self._status_label.setStyleSheet(f"""
            QLabel {{
                font-size: 14px;
                font-weight: 600;
                color: {Colors.ERROR};
            }}
        """)
        self._spinner.stop()

    @property
    def log_viewer(self) -> LogViewer:
        """Access the log viewer for external configuration."""
        return self._log_viewer
