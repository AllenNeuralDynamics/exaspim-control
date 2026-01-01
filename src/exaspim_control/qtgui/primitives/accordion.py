"""Accordion component for collapsible sections."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class AccordionCard(QWidget):
    """A collapsible card with header and expandable content.

    Layout:
        ┌─────────────────────────────────────────┐
        │ ▾  Title                    [actions]   │  ← header
        ├─────────────────────────────────────────┤
        │   Content widget                        │  ← content (when expanded)
        └─────────────────────────────────────────┘

    Usage:
        card = AccordionCard("Settings", settings_widget)

        # With action widgets (e.g., refresh button, reset button)
        card = AccordionCard(
            "Device",
            widget,
            action_widgets=[refresh_btn, reset_btn],
        )
    """

    toggled = pyqtSignal(bool)  # Emits True when expanded, False when collapsed

    def __init__(
        self,
        title: str,
        content: QWidget | None = None,
        expanded: bool = True,
        action_widgets: list[QWidget] | None = None,
        parent: QWidget | None = None,
    ):
        """Initialize accordion card.

        :param title: Section title
        :param content: Content widget
        :param expanded: Initial expanded state
        :param action_widgets: Optional list of action widgets (buttons) for header
        :param parent: Parent widget
        """
        super().__init__(parent)
        self._title = title
        self._expanded = expanded
        self._action_widgets = action_widgets or []
        self._content_widget: QWidget | None = None

        self._setup_ui()

        if content is not None:
            self.set_content(content)

        # Set initial state
        self._update_state()

    def _setup_ui(self) -> None:
        """Setup the accordion card UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 4)  # Small bottom margin between cards

        # Card container (holds both header and content)
        self._card = QFrame(self)
        self._card.setObjectName("accordionCard")
        card_layout = QVBoxLayout(self._card)
        card_layout.setSpacing(0)
        card_layout.setContentsMargins(0, 0, 0, 0)

        # Header (clickable)
        self._header = QFrame(self._card)
        self._header.setObjectName("accordionHeader")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.mousePressEvent = self._on_header_click

        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(8)

        # Arrow indicator
        self._arrow_label = QLabel(self._header)
        self._arrow_label.setObjectName("accordionArrow")
        self._arrow_label.setFixedWidth(12)
        self._arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self._arrow_label)

        # Title label
        self._title_label = QLabel(self._title, self._header)
        self._title_label.setObjectName("accordionTitle")
        header_layout.addWidget(self._title_label)

        # Stretch to push actions to right
        header_layout.addStretch()

        # Action widgets
        for widget in self._action_widgets:
            widget.setParent(self._header)
            header_layout.addWidget(widget)

        card_layout.addWidget(self._header)

        # Content area
        self._content_area = QFrame(self._card)
        self._content_area.setObjectName("accordionContent")
        self._content_layout = QVBoxLayout(self._content_area)
        self._content_layout.setContentsMargins(12, 8, 12, 12)
        self._content_layout.setSpacing(0)

        card_layout.addWidget(self._content_area)

        layout.addWidget(self._card)

        self._apply_styles()

    def _on_header_click(self, event) -> None:
        """Handle header click - toggle unless clicking action widgets."""
        if event is not None:
            click_pos = event.pos()
            for widget in self._action_widgets:
                if widget.geometry().contains(click_pos):
                    return  # Let widget handle it
        self.toggle()

    def _apply_styles(self) -> None:
        """Apply styling to the accordion card."""
        self.setStyleSheet("""
            /* Card container */
            #accordionCard {
                background-color: #2d2d30;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
            }

            /* Header */
            #accordionHeader {
                background-color: transparent;
                border: none;
                border-top-left-radius: 3px;
                border-top-right-radius: 3px;
            }
            #accordionHeader:hover {
                background-color: rgba(255, 255, 255, 0.03);
            }

            /* Title */
            #accordionTitle {
                color: #d4d4d4;
                font-size: 12px;
                font-weight: 500;
            }

            /* Arrow indicator */
            #accordionArrow {
                color: #808080;
                font-size: 10px;
            }

            /* Content area */
            #accordionContent {
                background-color: transparent;
                border: none;
                border-top: 1px solid #3c3c3c;
            }
        """)

    def _update_state(self) -> None:
        """Update visual state based on expanded/collapsed."""
        # Update arrow
        arrow = "▼" if self._expanded else "▶"
        self._arrow_label.setText(arrow)

        # Show/hide content
        self._content_area.setVisible(self._expanded)

        # Update border radius - when collapsed, all corners rounded
        # When expanded, only top corners rounded (content continues below)
        if self._expanded:
            self._header.setStyleSheet("""
                #accordionHeader {
                    border-bottom-left-radius: 0px;
                    border-bottom-right-radius: 0px;
                }
            """)
        else:
            self._header.setStyleSheet("""
                #accordionHeader {
                    border-bottom-left-radius: 3px;
                    border-bottom-right-radius: 3px;
                }
            """)

    def set_content(self, widget: QWidget) -> None:
        """Set the content widget for this section."""
        if self._content_widget is not None:
            self._content_layout.removeWidget(self._content_widget)
            self._content_widget.setParent(None)

        self._content_widget = widget
        self._content_layout.addWidget(widget)

    def toggle(self) -> None:
        """Toggle the expanded/collapsed state."""
        self._expanded = not self._expanded
        self._update_state()
        self.toggled.emit(self._expanded)

    def expand(self) -> None:
        """Expand the section."""
        if not self._expanded:
            self.toggle()

    def collapse(self) -> None:
        """Collapse the section."""
        if self._expanded:
            self.toggle()

    def is_expanded(self) -> bool:
        """Return whether the section is expanded."""
        return self._expanded

    @property
    def title(self) -> str:
        """Get the section title."""
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        """Set the section title."""
        self._title = value
        self._title_label.setText(value)
