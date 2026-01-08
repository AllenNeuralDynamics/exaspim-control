"""Spinner display component for loading indicators."""

import math

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

from exaspim_control._qtgui.primitives.colors import Colors


class Spinner(QWidget):
    """Animated loading spinner using custom painting.

    Displays a circular spinner with dots that fade to create a trail effect.

    Usage:
        spinner = Spinner(size=48)
        spinner.start()  # Begin animation

        # Later...
        spinner.stop()   # Stop animation

        # Custom color
        spinner = Spinner(size=32, color=Colors.SUCCESS)
    """

    def __init__(
        self,
        size: int = 48,
        color: str = Colors.ACCENT,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._size = size
        self._color = color
        self._angle = 0
        self._num_dots = 12
        self._dot_radius = max(2, size // 16)  # Scale dot size with spinner size

        self.setFixedSize(size, size)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        """Start the spinner animation."""
        self._timer.start(80)  # ~12.5 fps

    def stop(self) -> None:
        """Stop the spinner animation."""
        self._timer.stop()

    @property
    def is_running(self) -> bool:
        """Check if the spinner is currently animating."""
        return self._timer.isActive()

    def _advance(self) -> None:
        """Advance the spinner animation by one step."""
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, _event) -> None:
        """Paint the spinner dots with fading trail effect."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center_x = self._size / 2
        center_y = self._size / 2
        radius = (self._size - self._dot_radius * 2) / 2 - 4

        for i in range(self._num_dots):
            angle = math.radians(i * (360 / self._num_dots) + self._angle)
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)

            # Fade dots based on position (trail effect)
            alpha = int(255 * (i + 1) / self._num_dots)
            color = QColor(self._color)
            color.setAlpha(alpha)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(
                QRectF(
                    x - self._dot_radius,
                    y - self._dot_radius,
                    self._dot_radius * 2,
                    self._dot_radius * 2,
                )
            )
