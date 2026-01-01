"""Icon button primitive for toolbar and overlay use."""

from typing import Literal

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QPushButton, QStyle, QWidget


class VIconButton(QPushButton):
    """A compact icon-only button for toolbars and overlays.

    Supports checkable state with distinct checked styling.
    Semi-transparent background suitable for overlaying on content.

    Usage:
        # With standard icon
        btn = VIconButton(standard_icon="SP_TitleBarMaxButton")
        btn.setCheckable(True)

        # With custom icon
        btn = VIconButton(icon=my_icon)

        # With text fallback (if no icon)
        btn = VIconButton(text="⟳")
    """

    def __init__(
        self,
        text: str = "",
        icon: QIcon | None = None,
        standard_icon: str | None = None,
        size: int = 28,
        variant: Literal["overlay", "toolbar"] = "overlay",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the icon button.

        :param text: Fallback text if no icon provided
        :param icon: Custom QIcon to display
        :param standard_icon: Name of QStyle.StandardPixmap (e.g., "SP_TitleBarMaxButton")
        :param size: Button size in pixels (square)
        :param variant: Visual style - "overlay" for semi-transparent, "toolbar" for solid
        :param parent: Parent widget
        """
        super().__init__(parent)
        self._variant = variant
        self._size = size

        # Set icon or text
        if icon is not None:
            self.setIcon(icon)
        elif standard_icon is not None:
            self._set_standard_icon(standard_icon)
        elif text:
            self.setText(text)

        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

    def _set_standard_icon(self, icon_name: str) -> None:
        """Set icon from QStyle.StandardPixmap name."""
        if (style := self.style()) is not None:
            pixmap = getattr(QStyle.StandardPixmap, icon_name, None)
            if pixmap is not None:
                self.setIcon(style.standardIcon(pixmap))

    def _apply_style(self) -> None:
        """Apply style based on variant."""
        if self._variant == "overlay":
            self.setStyleSheet("""
                QPushButton {
                    background-color: rgba(60, 60, 60, 180);
                    border: 1px solid rgba(80, 80, 80, 180);
                    border-radius: 4px;
                    color: #d4d4d4;
                }
                QPushButton:hover {
                    background-color: rgba(80, 80, 80, 200);
                }
                QPushButton:pressed {
                    background-color: rgba(40, 40, 40, 200);
                }
                QPushButton:checked {
                    background-color: rgba(0, 120, 212, 200);
                    border-color: rgba(0, 140, 232, 200);
                }
            """)
        else:  # toolbar
            self.setStyleSheet("""
                QPushButton {
                    background-color: #3c3c3c;
                    border: 1px solid #505050;
                    border-radius: 4px;
                    color: #d4d4d4;
                }
                QPushButton:hover {
                    background-color: #4a4a4a;
                }
                QPushButton:pressed {
                    background-color: #2d2d2d;
                }
                QPushButton:checked {
                    background-color: #0078d4;
                    border-color: #0088e4;
                }
            """)

    def setVariant(self, variant: Literal["overlay", "toolbar"]) -> None:
        """Change the visual variant."""
        self._variant = variant
        self._apply_style()
