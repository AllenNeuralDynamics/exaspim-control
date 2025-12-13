from PyQt6.QtWidgets import QFrame, QVBoxLayout, QWidget


class Card(QFrame):
    """A card-style container widget similar to React's <Card> component.

    Usage:
        card = Card()
        card.add_widget(my_widget)

    Or with layout:
        card = Card()
        card.layout().addWidget(widget1)
        card.layout().addWidget(widget2)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._apply_card_style()

    def add_widget(self, widget: QWidget) -> None:
        if layout := self.layout():
            layout.addWidget(widget)

    def _setup_ui(self) -> None:
        """Setup the card's internal layout."""
        # Create a vertical layout by default
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)  # Inner padding
        self.setLayout(layout)

    def _apply_card_style(self) -> None:
        """Apply card-style appearance."""
        self.setStyleSheet("""
            Card {
                background-color: #2d2d30;
                border: 1px solid #3e3e42;
                border-radius: 6px;
                margin: 2px;
            }
        """)


class CardWidget(QWidget):
    """A card-style container widget that uses QWidget as base (for non-frame use cases).

    Usage:
        card = CardWidget()
        card.add_widget(my_widget)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._apply_card_style()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)  # Inner padding
        self.setLayout(layout)

    def add_widget(self, widget: QWidget) -> None:
        if layout := self.layout():
            layout.addWidget(widget)

    def _apply_card_style(self) -> None:
        self.setStyleSheet("""
            CardWidget {
                background-color: #2d2d30;
                border: 1px solid #3e3e42;
                border-radius: 6px;
                margin: 2px;
            }
        """)
