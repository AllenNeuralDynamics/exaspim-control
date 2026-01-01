"""Label primitives with consistent styling variants."""

from typing import ClassVar, Literal

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

LabelVariant = Literal["default", "title", "section", "value", "muted", "overlay"]


class VLabel(QLabel):
    """A styled label component with variant support.

    Variants:
    - default: Standard gray text (11px)
    - title: Bold, larger text for headings (14px)
    - section: Bold, muted text for section headers (11px)
    - value: Monospace text for displaying values (11px)
    - muted: Lighter gray for secondary text (10px)
    - overlay: Green on transparent background for HUD overlays

    Usage:
        VLabel("Status")  # default
        VLabel("Camera Settings", variant="title")
        VLabel("Waveforms", variant="section")
        VLabel("123.45", variant="value")
        VLabel("60 FPS", variant="overlay")
    """

    STYLES: ClassVar[dict[LabelVariant, str]] = {
        "default": """
            QLabel {
                font-size: 11px;
                color: #a0a0a0;
            }
        """,
        "title": """
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #d4d4d4;
            }
        """,
        "section": """
            QLabel {
                font-size: 11px;
                font-weight: bold;
                color: #888888;
            }
        """,
        "value": """
            QLabel {
                font-size: 11px;
                font-family: monospace;
                color: #d4d4d4;
            }
        """,
        "muted": """
            QLabel {
                font-size: 10px;
                color: #888888;
            }
        """,
        "overlay": """
            QLabel {
                font-size: 11px;
                font-weight: bold;
                color: #00ff00;
                background-color: rgba(0, 0, 0, 150);
                padding: 2px 6px;
                border-radius: 3px;
            }
        """,
    }

    def __init__(self, text: str = "", variant: LabelVariant = "default", parent: QWidget | None = None) -> None:
        super().__init__(text, parent=parent)
        self._variant: LabelVariant = variant
        self._apply_style()

    @property
    def variant(self) -> LabelVariant:
        return self._variant

    @variant.setter
    def variant(self, variant: LabelVariant) -> None:
        self._variant = variant
        self._apply_style()

    def _apply_style(self) -> None:
        """Apply style based on current variant."""
        self.setStyleSheet(self.STYLES[self._variant])


class VValueLabel(VLabel):
    """Convenience class for value display labels.

    Pre-configured with monospace font, right alignment, and fixed width.

    Usage:
        VValueLabel("0.00", width=60)
        VValueLabel("--", width=80, unit="mm")
    """

    def __init__(
        self,
        text: str = "--",
        width: int = 60,
        unit: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        display_text = f"{text} {unit}" if unit else text
        super().__init__(display_text, variant="value", parent=parent)
        self.setFixedWidth(width)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._unit = unit

    def setValue(self, text: str) -> None:
        """Update the value text."""
        display_text = f"{text} {self._unit}" if self._unit else text
        self.setText(display_text)
