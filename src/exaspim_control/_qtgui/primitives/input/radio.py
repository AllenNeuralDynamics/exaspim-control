"""RadioButton input component."""

from PyQt6.QtWidgets import QRadioButton, QWidget

from exaspim_control._qtgui.primitives.colors import Colors


class RadioButton(QRadioButton):
    """Styled radio button with consistent dark theme appearance.

    Usage:
        radio1 = RadioButton("Option 1")
        radio2 = RadioButton("Option 2")

        # With button group
        group = QButtonGroup()
        group.addButton(radio1, 0)
        group.addButton(radio2, 1)
    """

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self._apply_style()

    def _apply_style(self) -> None:
        """Apply consistent styling."""
        self.setStyleSheet(f"""
            QRadioButton {{
                color: {Colors.TEXT};
                font-size: 12px;
                spacing: 8px;
            }}
            QRadioButton:disabled {{
                color: {Colors.TEXT_DISABLED};
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid {Colors.BORDER_LIGHT};
                background-color: {Colors.BG_MEDIUM};
            }}
            QRadioButton::indicator:checked {{
                background-color: {Colors.ACCENT};
                border-color: {Colors.ACCENT};
            }}
            QRadioButton::indicator:disabled {{
                border-color: {Colors.BORDER};
                background-color: {Colors.BG_DARK};
            }}
        """)
