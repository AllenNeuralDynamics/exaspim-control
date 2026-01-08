"""LogViewer widget for displaying application logs."""

from __future__ import annotations

import contextlib
import logging
from typing import ClassVar

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCharFormat
from PyQt6.QtWidgets import (
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from exaspim_control._qtgui.primitives import Button, Colors


class QtLogHandler(logging.Handler, QObject):
    """Logging handler that emits Qt signals for thread-safe log display.

    Connects to QCoreApplication.aboutToQuit to clean up before Qt destroys
    C++ objects, preventing atexit errors from Qt/Python cleanup ordering.
    """

    logReceived = pyqtSignal(str, int)  # message, level

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)
        fmt = "%(asctime)s.%(msecs)03d %(levelname)-5s %(name)s: %(message)s"
        self.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
        self._attached_logger: logging.Logger | None = None

        # Connect to app quit signal - fires BEFORE Qt destroys objects
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._on_app_quit)

    def _on_app_quit(self) -> None:
        """Clean up when app is about to quit (before Qt destroys objects)."""
        self.close()

    def attach_to_logger(self, logger: logging.Logger) -> None:
        """Attach this handler to a logger (tracks for cleanup)."""
        self._attached_logger = logger
        logger.addHandler(self)

    def detach_from_logger(self) -> None:
        """Detach this handler from its logger."""
        if self._attached_logger is not None:
            with contextlib.suppress(Exception):
                self._attached_logger.removeHandler(self)
            self._attached_logger = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.logReceived.emit(msg, record.levelno)
        except RuntimeError:
            # Qt object already deleted - detach silently
            self.detach_from_logger()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        """Override close to detach from logger first."""
        self.detach_from_logger()
        super().close()


class LogViewer(QWidget):
    """Widget for viewing application logs with color-coded levels.

    Features:
    - Auto-scrolling log display
    - Color-coded log levels (DEBUG, INFO, WARNING, ERROR)
    - Clear button
    - Installs a logging handler to capture logs

    Usage:
        viewer = LogViewer()
        viewer.install_handler()  # Capture root logger
        # or
        viewer.install_handler("exaspim_control")  # Capture specific logger
    """

    # Colors for different log levels (using design system tokens)
    LEVEL_COLORS: ClassVar[dict[int, str]] = {
        logging.DEBUG: Colors.TEXT_MUTED,
        logging.INFO: Colors.TEXT,
        logging.WARNING: Colors.WARNING,
        logging.ERROR: Colors.ERROR,
        logging.CRITICAL: Colors.ERROR_BRIGHT,
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._handler: QtLogHandler | None = None
        self._max_lines = 1000  # Prevent unbounded growth

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Log text area
        self._text_edit = QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont(QFont("Consolas", 9))
        self._text_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {Colors.BG_DARK};
                color: {Colors.TEXT};
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
            }}
        """)
        self._text_edit.setMaximumBlockCount(self._max_lines)
        layout.addWidget(self._text_edit)

        # Floating clear button (positioned in resizeEvent)
        self._clear_button = Button(text="✕", variant="overlay", parent=self)
        self._clear_button.setToolTip("Clear logs")
        self._clear_button.clicked.connect(self.clear)

    def resizeEvent(self, a0) -> None:
        """Position floating button when resized."""
        super().resizeEvent(a0)
        margin = 8
        btn_size = self._clear_button.size()
        self._clear_button.move(
            self.width() - btn_size.width() - margin,
            self.height() - btn_size.height() - margin,
        )

    def install_handler(self, logger_name: str = "") -> None:
        """Install the Qt log handler on the specified logger.

        Args:
            logger_name: Name of the logger to capture. Empty string for root logger.
        """
        if self._handler is not None:
            self.remove_handler()

        self._handler = QtLogHandler()
        self._handler.logReceived.connect(self._append_log)

        logger = logging.getLogger(logger_name)
        self._handler.attach_to_logger(logger)

    def remove_handler(self) -> None:
        """Remove the Qt log handler from the logger."""
        if self._handler is not None:
            self._handler.detach_from_logger()
            self._handler = None

    def clear(self) -> None:
        """Clear all log entries."""
        self._text_edit.clear()

    def _append_log(self, message: str, level: int) -> None:
        """Append a log entry with appropriate color."""
        color = self.LEVEL_COLORS.get(level, self.LEVEL_COLORS[logging.INFO])

        # Create colored text format
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))

        # Append with color
        cursor = self._text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(message + "\n", fmt)

        # Auto-scroll to bottom
        if (scrollbar := self._text_edit.verticalScrollBar()) is not None:
            scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, a0) -> None:
        """Clean up handler on close."""
        self.remove_handler()
        super().closeEvent(a0)
