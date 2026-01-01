from typing import Literal

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class Card(QFrame):
    """Titled card container with vertical or horizontal content flow.

    Usage:
        # Vertical (default)
        Card("Subject",
            Field("Subject ID", self._subject_id),
            Field("Notes", self._notes),
        )

        # Horizontal
        Card("Chamber",
            Field("Medium", self._medium),
            Field("Index", self._index),
            flow="horizontal",
        )

        # Untitled
        Card(None, self._widget)
    """

    def __init__(
        self,
        title: str | None,
        *widgets: QWidget,
        flow: Literal["vertical", "horizontal"] = "vertical",
        spacing: int = 8,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._title = title

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 10)
        main_layout.setSpacing(6)

        # Title label
        self._title_label = QLabel(title or "")
        self._title_label.setObjectName("cardTitle")
        self._title_label.setVisible(title is not None)
        main_layout.addWidget(self._title_label)

        # Content layout (vertical or horizontal)
        content = QWidget()
        if flow == "horizontal":
            content_layout = QHBoxLayout(content)
        else:
            content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(spacing)

        for w in widgets:
            content_layout.addWidget(w)

        main_layout.addWidget(content)

        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            Card {
                background-color: #252526;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
            }
            #cardTitle {
                font-size: 12px;
                font-weight: 600;
                color: #cccccc;
                padding-bottom: 4px;
                border-bottom: 1px solid #3c3c3c;
            }
        """)

    @property
    def title(self) -> str | None:
        return self._title

    @title.setter
    def title(self, value: str | None) -> None:
        self._title = value
        self._title_label.setText(value or "")
        self._title_label.setVisible(value is not None)
