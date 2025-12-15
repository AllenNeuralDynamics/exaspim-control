import logging
from collections.abc import Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel, QWidget


class VLabel(QLabel):
    """A styled label component with consistent styling."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent=parent)
        self._apply_styles()

    def _apply_styles(self):
        """Apply subtle styling to the label."""
        style = """
            QLabel {
                font-size: 11px;
                font-weight: normal;
                color: #a0a0a0;
            }
        """
        self.setStyleSheet(style)


class LiveValueLabel[T: str | int | float]:
    """Atomic component for displaying a polled read-only value with optional prefix/suffix.

    Uses a simple QTimer for polling instead of complex binding infrastructure.
    """

    def __init__(
        self,
        getter: Callable[[], T],
        prefix: str = "",
        suffix: str = "",
        format_func: Callable[[T], str] | None = None,
        poll_interval: int = 1000,
        parent: QWidget | None = None,
    ):
        self._getter = getter
        self._prefix = prefix
        self._suffix = suffix
        self._format_func = format_func or str
        self.log = logging.getLogger(f"LiveLabel[{id(self)}]")

        # Create the label widget
        self._label = VLabel(parent=parent)

        # Simple QTimer for polling
        self._timer = QTimer(parent)
        self._timer.timeout.connect(self.update_value)
        self._timer.setInterval(poll_interval)

        # Initial update
        self.update_value()

    @property
    def widget(self) -> VLabel:
        """Access to the underlying VLabel widget for layout and styling."""
        return self._label

    @property
    def text(self) -> str:
        """Get the current text of the label."""
        return self._label.text()

    def update_value(self):
        """Update the displayed value by polling the getter."""
        try:
            raw_value = self._getter()
            formatted_value = self._format_func(raw_value)
            display_text = f"{self._prefix}{formatted_value}{self._suffix}"
            self._label.setText(display_text)
        except Exception as e:
            self.log.exception("Error updating label value")
            self._label.setText(f"{self._prefix}Error: {e}{self._suffix}")

    def start_polling(self):
        """Start polling."""
        self._timer.start()

    def stop_polling(self):
        """Stop polling."""
        self._timer.stop()

    def refresh(self):
        """Immediately update the value (same as update_value)."""
        self.update_value()

    # Forward common QLabel methods for convenience
    def setAlignment(self, alignment) -> None:
        """Set the alignment of the label."""
        self._label.setAlignment(alignment)

    def setStyleSheet(self, style: str) -> None:
        """Set the style sheet of the label."""
        self._label.setStyleSheet(style)

    def setFont(self, font) -> None:
        """Set the font of the label."""
        self._label.setFont(font)
