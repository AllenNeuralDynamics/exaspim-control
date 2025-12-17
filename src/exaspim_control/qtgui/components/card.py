from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class Card(QFrame):
    """A card-style container widget with optional title.

    Usage:
        card = Card("Camera")
        card.add_widget(camera_widget)

    Or without title:
        card = Card()
        card.add_widget(my_widget)
    """

    def __init__(self, title: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._title = title

        # Create UI widgets (factory methods return them)
        self._title_label, self._content, self._content_layout = self._create_widgets()

        # Build layout
        self._build_layout()
        self._apply_card_style()

    def _create_widgets(self) -> tuple[QLabel, QWidget, QVBoxLayout]:
        """Create card widgets (title label and content area)."""
        # Title label (always created, visibility controlled)
        title_label = QLabel(self._title or "", self)
        title_label.setObjectName("cardTitle")
        title_label.setVisible(self._title is not None)

        # Content area
        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        return title_label, content, content_layout

    def _build_layout(self) -> None:
        """Build the card's layout using pre-created widgets."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(self._title_label)
        layout.addWidget(self._content)

    def add_widget(self, widget: QWidget) -> None:
        """Add a widget to the card's content area."""
        self._content_layout.addWidget(widget)

    def _apply_card_style(self) -> None:
        """Apply card-style appearance."""
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


class CardWidget(QWidget):
    """A card-style container widget that uses QWidget as base.

    Usage:
        card = CardWidget("Settings")
        card.add_widget(my_widget)
    """

    def __init__(self, title: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._title = title

        # Create UI widgets (factory methods return them)
        self._title_label, self._content, self._content_layout = self._create_widgets()

        # Build layout
        self._build_layout()
        self._apply_card_style()

    def _create_widgets(self) -> tuple[QLabel, QWidget, QVBoxLayout]:
        """Create card widgets (title label and content area)."""
        # Title label (always created, visibility controlled)
        title_label = QLabel(self._title or "", self)
        title_label.setObjectName("cardWidgetTitle")
        title_label.setVisible(self._title is not None)

        # Content area
        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        return title_label, content, content_layout

    def _build_layout(self) -> None:
        """Build the card's layout using pre-created widgets."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(self._title_label)
        layout.addWidget(self._content)

    def add_widget(self, widget: QWidget) -> None:
        """Add a widget to the card's content area."""
        self._content_layout.addWidget(widget)

    def _apply_card_style(self) -> None:
        self.setStyleSheet("""
            CardWidget {
                background-color: #252526;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
            }
            #cardWidgetTitle {
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
