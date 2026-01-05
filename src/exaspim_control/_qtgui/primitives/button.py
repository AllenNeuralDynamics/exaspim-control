"""Button components with consistent styling."""

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QPushButton, QWidget


class VButton(QPushButton):
    """A styled button component with consistent appearance.

    Supports primary (default) and secondary variants.

    Usage:
        btn = VButton("Click Me")
        btn = VButton("Submit", variant="primary")
        btn = VButton("Cancel", variant="secondary")
        btn = VButton("Danger", variant="danger")
    """

    def __init__(
        self,
        text: str = "",
        variant: str = "secondary",
        icon: QIcon | None = None,
        checkable: bool = False,
        parent: QWidget | None = None,
    ):
        """
        Initialize VButton.

        :param text: Button text
        :param variant: Style variant - "primary", "secondary", or "danger"
        :param icon: Optional icon
        :param checkable: Whether button is checkable (toggle)
        :param parent: Parent widget
        """
        super().__init__(text, parent)
        self._variant = variant

        if icon is not None:
            self.setIcon(icon)

        if checkable:
            self.setCheckable(True)

        self._apply_style()

        # Update style on toggle if checkable
        if checkable:
            self.toggled.connect(self._on_toggled)

    def _apply_style(self) -> None:
        """Apply styling based on variant."""
        if self._variant == "primary":
            self._apply_primary_style()
        elif self._variant == "danger":
            self._apply_danger_style()
        else:
            self._apply_secondary_style()

    def _apply_secondary_style(self) -> None:
        """Apply secondary (default) button style."""
        self.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #d4d4d4;
                font-size: 11px;
                padding: 6px 12px;
                border: 1px solid #505050;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #4a4a4d;
                border-color: #606060;
            }
            QPushButton:pressed {
                background-color: #2d2d30;
            }
            QPushButton:checked {
                background-color: #0078d4;
                color: white;
                border-color: #0078d4;
            }
            QPushButton:checked:hover {
                background-color: #1084d8;
            }
            QPushButton:disabled {
                background-color: #2d2d30;
                color: #666;
                border-color: #404040;
            }
        """)

    def _apply_primary_style(self) -> None:
        """Apply primary button style (accent color)."""
        self.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                font-size: 11px;
                padding: 6px 12px;
                border: 1px solid #0078d4;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1084d8;
                border-color: #1084d8;
            }
            QPushButton:pressed {
                background-color: #006cc1;
            }
            QPushButton:checked {
                background-color: #005a9e;
                border-color: #005a9e;
            }
            QPushButton:disabled {
                background-color: #404040;
                color: #666;
                border-color: #404040;
            }
        """)

    def _apply_danger_style(self) -> None:
        """Apply danger button style (red)."""
        self.setStyleSheet("""
            QPushButton {
                background-color: #c42b1c;
                color: white;
                font-size: 11px;
                padding: 6px 12px;
                border: 1px solid #d63a2b;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #d63a2b;
                border-color: #e64a3b;
            }
            QPushButton:pressed {
                background-color: #a52414;
            }
            QPushButton:disabled {
                background-color: #404040;
                color: #666;
                border-color: #404040;
            }
        """)

    def _on_toggled(self, checked: bool) -> None:
        """Handle toggle state change for checkable buttons."""
        # Style already handled by :checked pseudo-selector

    @property
    def variant(self) -> str:
        """Get button variant."""
        return self._variant

    @variant.setter
    def variant(self, value: str) -> None:
        """Set button variant and update style."""
        self._variant = value
        self._apply_style()


class VIconButton(QPushButton):
    """A small icon-only button with minimal styling.

    Good for overlay buttons or compact toolbars.

    Usage:
        btn = VIconButton(some_icon)
        btn = VIconButton(some_icon, size=24)
    """

    def __init__(
        self,
        icon: QIcon | None = None,
        size: int = 28,
        parent: QWidget | None = None,
    ):
        """
        Initialize VIconButton.

        :param icon: Button icon
        :param size: Button size in pixels
        :param parent: Parent widget
        """
        super().__init__(parent)
        self._size = size

        if icon is not None:
            self.setIcon(icon)

        self.setFixedSize(size, size)
        self._apply_style()

    def _apply_style(self) -> None:
        """Apply icon button styling."""
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(60, 60, 60, 0.8);
                color: #fefefe;
                border: 1px solid rgba(80, 80, 80, 0.8);
                border-radius: {self._size // 2}px;
                padding: 4px;
            }}
            QPushButton:hover {{
                background-color: rgba(74, 74, 77, 0.9);
                border-color: rgba(96, 96, 96, 0.9);
            }}
            QPushButton:pressed {{
                background-color: rgba(45, 45, 48, 0.9);
            }}
            QPushButton:checked {{
                background-color: rgba(0, 120, 212, 0.9);
                border-color: rgba(0, 120, 212, 0.9);
            }}
        """)
