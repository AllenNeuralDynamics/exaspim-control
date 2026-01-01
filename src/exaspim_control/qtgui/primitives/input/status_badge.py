"""Status badge primitive for state indicators."""

from typing import Literal

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

StatusType = Literal["idle", "running", "error", "warning", "success", "pending"]


class VStatusBadge(QLabel):
    """A colored status indicator badge.

    Predefined status types with appropriate colors:
    - idle: Gray
    - running: Green
    - error: Red
    - warning: Orange
    - success: Green
    - pending: Blue

    Usage:
        badge = VStatusBadge()
        badge.setStatus("running")

        # Or with initial status
        badge = VStatusBadge(status="idle")
    """

    STATUS_STYLES: dict[str, tuple[str, str, str]] = {
        # status: (background_color, text_color, display_text)
        "idle": ("#616161", "#ffffff", "Idle"),
        "running": ("#2e7d32", "#ffffff", "Running"),
        "error": ("#c62828", "#ffffff", "Error"),
        "warning": ("#f57c00", "#ffffff", "Warning"),
        "success": ("#2e7d32", "#ffffff", "Success"),
        "pending": ("#1565c0", "#ffffff", "Pending"),
    }

    def __init__(
        self,
        status: StatusType = "idle",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._status: StatusType = "idle"
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedWidth(80)
        self.setStatus(status)

    def setStatus(self, status: StatusType) -> None:
        """Update the status display."""
        self._status = status
        bg_color, text_color, display_text = self.STATUS_STYLES.get(status, self.STATUS_STYLES["idle"])
        self.setText(display_text)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                color: {text_color};
                font-size: 11px;
                font-weight: bold;
                padding: 2px 8px;
                border-radius: 3px;
            }}
        """)

    def status(self) -> StatusType:
        """Get the current status."""
        return self._status

    def setStatusText(self, status: StatusType, text: str) -> None:
        """Set status with custom display text."""
        self._status = status
        bg_color, text_color, _ = self.STATUS_STYLES.get(status, self.STATUS_STYLES["idle"])
        self.setText(text)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                color: {text_color};
                font-size: 11px;
                font-weight: bold;
                padding: 2px 8px;
                border-radius: 3px;
            }}
        """)
