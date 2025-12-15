"""Accordion component for collapsible sections."""

from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class AccordionSection(QWidget):
    """A single collapsible section with a clickable header and content area.

    Layout: [Title] ---stretch--- [Refresh btn] [▾]

    Usage:
        section = AccordionSection("Settings", settings_widget)
        section.toggle()  # Expand/collapse programmatically

        # With refresh callback
        section = AccordionSection("Device", widget, on_refresh=device.refresh)
    """

    toggled = pyqtSignal(bool)  # Emits True when expanded, False when collapsed
    refreshRequested = pyqtSignal()

    def __init__(
        self,
        title: str,
        content: QWidget | None = None,
        expanded: bool = True,
        on_refresh: Callable[[], None] | None = None,
        is_group: bool = False,
        parent: QWidget | None = None,
    ):
        """
        Initialize accordion section.

        :param title: Section title
        :param content: Content widget
        :param expanded: Initial expanded state
        :param on_refresh: Optional callback for refresh button click
        :param is_group: If True, style as a group header (visual distinction)
        :param parent: Parent widget
        """
        super().__init__(parent)
        self._title = title
        self._expanded = expanded
        self._on_refresh = on_refresh
        self._is_group = is_group
        self._content_widget: QWidget | None = None

        self._setup_ui()

        if content is not None:
            self.set_content(content)

        # Set initial state without animation
        self._update_toggle_icon()
        if not expanded:
            self._content_area.setVisible(False)

    def _setup_ui(self) -> None:
        """Setup the accordion section UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header (clickable)
        self._header = QFrame()
        self._header.setObjectName("accordionGroupHeader" if self._is_group else "accordionHeader")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)

        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(8)

        # Title label (clicking this toggles)
        self._title_label = QLabel(self._title)
        self._title_label.setObjectName("accordionGroupTitle" if self._is_group else "accordionTitle")
        self._title_label.mousePressEvent = lambda _: self.toggle()
        header_layout.addWidget(self._title_label)

        # Stretch to push buttons to right
        header_layout.addStretch()

        # Refresh button (optional)
        if self._on_refresh is not None:
            self._refresh_btn = QPushButton("⟳")
            self._refresh_btn.setObjectName("accordionRefreshBtn")
            self._refresh_btn.setFixedSize(20, 20)
            self._refresh_btn.setToolTip("Refresh")
            self._refresh_btn.clicked.connect(self._on_refresh_clicked)
            header_layout.addWidget(self._refresh_btn)

        # Arrow indicator
        self._arrow_label = QLabel()
        self._arrow_label.setObjectName("accordionArrow")
        self._arrow_label.setFixedWidth(16)
        self._arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._arrow_label.mousePressEvent = lambda _: self.toggle()
        header_layout.addWidget(self._arrow_label)

        layout.addWidget(self._header)

        # Content area (simple widget container, no scroll)
        self._content_area = QWidget()
        self._content_area.setObjectName("accordionContent")
        self._content_layout = QVBoxLayout(self._content_area)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.setSpacing(0)

        layout.addWidget(self._content_area)

        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply styling to the accordion section."""
        self.setStyleSheet("""
            /* Regular accordion header */
            #accordionHeader {
                background-color: transparent;
                border: none;
                border-bottom: 1px solid #3a3a3a;
            }
            #accordionHeader:hover {
                background-color: rgba(255, 255, 255, 0.03);
            }
            #accordionTitle {
                color: #d0d0d0;
                font-size: 11px;
                font-weight: 500;
            }

            /* Group accordion header (visual distinction) */
            #accordionGroupHeader {
                background-color: #2a2a2a;
                border: none;
                border-bottom: 1px solid #3a3a3a;
                border-radius: 3px 3px 0 0;
            }
            #accordionGroupHeader:hover {
                background-color: #323232;
            }
            #accordionGroupTitle {
                color: #e0e0e0;
                font-size: 11px;
                font-weight: 600;
            }

            /* Arrow indicator */
            #accordionArrow {
                color: #808080;
                font-size: 10px;
            }

            /* Refresh button */
            #accordionRefreshBtn {
                background-color: transparent;
                border: none;
                border-radius: 3px;
                color: #808080;
                font-size: 12px;
                padding: 0;
            }
            #accordionRefreshBtn:hover {
                background-color: rgba(255, 255, 255, 0.1);
                color: #d0d0d0;
            }
            #accordionRefreshBtn:pressed {
                background-color: rgba(255, 255, 255, 0.15);
            }

            /* Content area */
            #accordionContent {
                background-color: transparent;
                border: none;
            }
        """)

    def _update_toggle_icon(self) -> None:
        """Update arrow indicator."""
        arrow = "▾" if self._expanded else "▸"
        self._arrow_label.setText(arrow)

    def _on_refresh_clicked(self) -> None:
        """Handle refresh button click."""
        if self._on_refresh:
            self._on_refresh()
        self.refreshRequested.emit()

    def set_content(self, widget: QWidget) -> None:
        """Set the content widget for this section."""
        # Remove old content if any
        if self._content_widget is not None:
            self._content_layout.removeWidget(self._content_widget)
            self._content_widget.setParent(None)

        self._content_widget = widget
        self._content_layout.addWidget(widget)

    def toggle(self) -> None:
        """Toggle the expanded/collapsed state."""
        self._expanded = not self._expanded
        self._update_toggle_icon()
        self._content_area.setVisible(self._expanded)
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


class Accordion(QWidget):
    """Container for multiple collapsible AccordionSection widgets.

    Usage:
        accordion = Accordion()
        accordion.add_section("General", general_widget)
        accordion.add_section("Advanced", advanced_widget, expanded=False)

    With exclusive mode (only one section open at a time):
        accordion = Accordion(exclusive=True)
    """

    def __init__(self, exclusive: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._exclusive = exclusive
        self._sections: list[AccordionSection] = []

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the accordion container."""
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(0)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def add_section(
        self,
        title: str,
        content: QWidget,
        expanded: bool = True,
        on_refresh: Callable[[], None] | None = None,
        is_group: bool = False,
    ) -> AccordionSection:
        """Add a new collapsible section to the accordion.

        :param title: Section header title
        :param content: Widget to show in the section
        :param expanded: Whether the section starts expanded
        :param on_refresh: Optional callback for refresh button
        :param is_group: Style as group header
        :return: The created AccordionSection
        """
        section = AccordionSection(title, content, expanded, on_refresh, is_group)
        self._sections.append(section)

        if self._exclusive:
            section.toggled.connect(lambda exp, s=section: self._on_section_toggled(s, exp))

        self._layout.addWidget(section)
        return section

    def _on_section_toggled(self, toggled_section: AccordionSection, expanded: bool) -> None:
        """Handle section toggle in exclusive mode."""
        if expanded and self._exclusive:
            for section in self._sections:
                if section is not toggled_section and section.is_expanded():
                    section.collapse()

    def expand_all(self) -> None:
        """Expand all sections."""
        for section in self._sections:
            section.expand()

    def collapse_all(self) -> None:
        """Collapse all sections."""
        for section in self._sections:
            section.collapse()

    def sections(self) -> list[AccordionSection]:
        """Get all sections."""
        return self._sections.copy()

    def add_stretch(self) -> None:
        """Add stretch at the end to push sections to top."""
        self._layout.addStretch()
