import logging
from collections.abc import Callable

from PyQt6.QtWidgets import QComboBox, QVBoxLayout, QWidget

from exaspim_control._qtgui.primitives.colors import Colors


class VComboBox(QComboBox):
    """A styled combobox with convenient constructor parameters.

    Usage:
        VComboBox()
        VComboBox(items=["Option A", "Option B"])
        VComboBox(items=["Red", "Green", "Blue"], value="Green")
    """

    def __init__(
        self,
        items: list[str] | None = None,
        value: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        if items:
            self.addItems(items)
        if value is not None:
            self.setCurrentText(value)
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply consistent styling to the combobox."""
        self.setStyleSheet(f"""
            QComboBox {{
                background-color: {Colors.BG_MEDIUM};
                color: {Colors.TEXT};
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                min-height: 20px;
            }}
            QComboBox:hover {{
                border-color: {Colors.BORDER_LIGHT};
            }}
            QComboBox:focus {{
                border-color: {Colors.ACCENT};
            }}
            QComboBox:disabled {{
                color: {Colors.TEXT_DISABLED};
                background-color: {Colors.BG_DARK};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {Colors.BG_MEDIUM};
                color: {Colors.TEXT};
                border: 1px solid {Colors.BORDER};
                selection-background-color: {Colors.ACCENT};
            }}
        """)


class VSelect(QWidget):
    """A simple select widget with just a styled combobox."""

    def __init__(
        self,
        options: list[str],
        getter: Callable[[], str] | None = None,
        setter: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent=parent)
        self.options = options
        self.getter = getter
        self.setter = setter
        self.log = logging.getLogger(f"VSelect[{id(self)}]")
        self._setup_ui()

    @property
    def widget(self) -> QWidget:
        """Get the underlying widget for this input component."""
        return self

    def _setup_ui(self):
        """Set up the user interface with just a combobox."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # No margins, let parent control spacing
        layout.setSpacing(0)

        # Create styled combobox
        self.combobox = VComboBox()
        self.combobox.addItems(self.options)

        # Connect callback if provided
        if self.setter:
            self.combobox.currentTextChanged.connect(self._on_selection_changed)

        # Set initial value from getter if provided
        if self.getter:
            try:
                initial_value = self.getter()
                if initial_value in self.options:
                    self.combobox.setCurrentText(initial_value)
            except Exception:
                self.log.exception("Error getting initial value")
                # If getter fails, just continue without setting value

        layout.addWidget(self.combobox)

        self.setLayout(layout)

    def _on_selection_changed(self, text: str):
        """Handle combobox selection changes."""
        if self.setter:
            self.setter(text)

    def get_current_selection(self) -> str:
        """Get the currently selected option."""
        return self.combobox.currentText()

    def set_current_selection(self, text: str):
        """Set the currently selected option."""
        index = self.combobox.findText(text)
        if index >= 0:
            self.combobox.setCurrentIndex(index)

    def update_options(self, options: list[str]):
        """Update the available options in the combobox."""
        self.options = options
        current_text = self.combobox.currentText()
        self.combobox.clear()
        self.combobox.addItems(options)

        # Try to restore the previous selection if it still exists
        index = self.combobox.findText(current_text)
        if index >= 0:
            self.combobox.setCurrentIndex(index)
