"""TabWidget container component."""

from typing import Literal

from PyQt6.QtWidgets import QTabWidget, QWidget

from exaspim_control._qtgui.primitives.colors import Colors


class TabWidget(QTabWidget):
    """Styled tab widget with configurable tab position.

    Usage:
        # Bottom tabs (default)
        tabs = TabWidget()
        tabs.addTab(widget1, "Tab 1")
        tabs.addTab(widget2, "Tab 2")

        # Top tabs
        tabs = TabWidget(position="top")

        # With corner widget
        tabs = TabWidget()
        tabs.setCornerWidget(button, Qt.Corner.BottomRightCorner)
    """

    def __init__(
        self,
        position: Literal["top", "bottom"] = "bottom",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._position = position

        if position == "bottom":
            self.setTabPosition(QTabWidget.TabPosition.South)
        else:
            self.setTabPosition(QTabWidget.TabPosition.North)

        self._apply_style()

    def _apply_style(self) -> None:
        """Apply design system styling."""
        if self._position == "bottom":
            self.setStyleSheet(f"""
                QTabWidget::pane {{
                    border: 1px solid {Colors.BORDER};
                    border-radius: 4px;
                    background-color: {Colors.BG_LIGHT};
                }}
                QTabBar::tab {{
                    background-color: {Colors.BG_MEDIUM};
                    color: {Colors.TEXT_MUTED};
                    border: 1px solid {Colors.BORDER};
                    border-top: none;
                    padding: 6px 12px;
                    margin-right: 2px;
                    border-bottom-left-radius: 4px;
                    border-bottom-right-radius: 4px;
                }}
                QTabBar::tab:selected {{
                    background-color: {Colors.BG_LIGHT};
                    color: {Colors.TEXT};
                    border-top: 1px solid {Colors.BG_LIGHT};
                }}
                QTabBar::tab:hover:!selected {{
                    background-color: {Colors.HOVER};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QTabWidget::pane {{
                    border: 1px solid {Colors.BORDER};
                    border-radius: 4px;
                    background-color: {Colors.BG_LIGHT};
                }}
                QTabBar::tab {{
                    background-color: {Colors.BG_MEDIUM};
                    color: {Colors.TEXT_MUTED};
                    border: 1px solid {Colors.BORDER};
                    border-bottom: none;
                    padding: 6px 12px;
                    margin-right: 2px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                }}
                QTabBar::tab:selected {{
                    background-color: {Colors.BG_LIGHT};
                    color: {Colors.TEXT};
                    border-bottom: 1px solid {Colors.BG_LIGHT};
                }}
                QTabBar::tab:hover:!selected {{
                    background-color: {Colors.HOVER};
                }}
            """)
