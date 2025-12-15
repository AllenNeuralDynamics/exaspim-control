import logging
from collections.abc import Callable

from PyQt6.QtWidgets import QDoubleSpinBox, QSpinBox, QVBoxLayout, QWidget


class VSpinBox(QSpinBox):
    """A simple spinbox - uses Qt defaults."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)


class VDoubleSpinBox(QDoubleSpinBox):
    """A simple double spinbox - uses Qt defaults."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)


class VNumberInput[T: int | float](QWidget):
    """A functional number input widget that wraps VSpinBox/VDoubleSpinBox.

    Automatically selects the appropriate widget type based on the initial value:
    - int values create a VSpinBox
    - float values create a VDoubleSpinBox

    Uses simple getter/setter pattern like other V* widgets.
    """

    def __init__(
        self,
        getter: Callable[[], T],
        setter: Callable[[T], None],
        *,
        min_value: T | None = None,
        max_value: T | None = None,
        step: T | None = None,
        decimals: int = 2,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.getter = getter
        self.setter = setter
        self.log = logging.getLogger(f"VNumberInput[{id(self)}]")

        self._setup_ui(min_value, max_value, step, decimals)

    def _setup_ui(
        self,
        min_value: T | None,
        max_value: T | None,
        step: T | None,
        decimals: int,
    ) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Get initial value to determine widget type
        try:
            initial_value = self.getter()
        except Exception:
            self.log.exception("Error getting initial value")
            initial_value = 0

        # Create appropriate spinbox based on value type
        if isinstance(initial_value, float) and not isinstance(initial_value, bool):
            self._spinbox: VSpinBox | VDoubleSpinBox = VDoubleSpinBox()
            self._spinbox.setDecimals(decimals)
            self._spinbox.setRange(
                float(min_value) if min_value is not None else -1e9,
                float(max_value) if max_value is not None else 1e9,
            )
            if step is not None:
                self._spinbox.setSingleStep(float(step))
            self._spinbox.setValue(float(initial_value))
        else:
            self._spinbox = VSpinBox()
            self._spinbox.setRange(
                int(min_value) if min_value is not None else -1000000,
                int(max_value) if max_value is not None else 1000000,
            )
            if step is not None:
                self._spinbox.setSingleStep(int(step))
            self._spinbox.setValue(int(initial_value))

        # Connect value changed signal to setter
        self._spinbox.valueChanged.connect(self._on_value_changed)

        layout.addWidget(self._spinbox)

    def _on_value_changed(self, value: int | float) -> None:
        """Handle value change events."""
        if self.setter:
            self.setter(value)

    @property
    def widget(self) -> VSpinBox | VDoubleSpinBox:
        """Access to the underlying spinbox widget for layout and styling."""
        return self._spinbox

    def value(self) -> T:
        """Get the current value."""
        return self._spinbox.value()

    def setValue(self, value: T) -> None:
        """Set the value."""
        self._spinbox.blockSignals(True)
        if isinstance(self._spinbox, VDoubleSpinBox):
            self._spinbox.setValue(float(value))
        else:
            self._spinbox.setValue(int(value))
        self._spinbox.blockSignals(False)

    def refresh(self) -> None:
        """Refresh value from getter."""
        try:
            value = self.getter()
            self.setValue(value)
        except Exception:
            self.log.exception("Error refreshing value")

    # Forward common spinbox methods for convenience
    def setRange(self, min_val: T, max_val: T) -> None:
        """Set the range of the spinbox."""
        if isinstance(self._spinbox, VDoubleSpinBox):
            self._spinbox.setRange(float(min_val), float(max_val))
        else:
            self._spinbox.setRange(int(min_val), int(max_val))

    def setSuffix(self, suffix: str) -> None:
        """Set the suffix of the spinbox."""
        self._spinbox.setSuffix(suffix)

    def setPrefix(self, prefix: str) -> None:
        """Set the prefix of the spinbox."""
        self._spinbox.setPrefix(prefix)

    def setSingleStep(self, step: T) -> None:
        """Set the single step of the spinbox."""
        if isinstance(self._spinbox, VDoubleSpinBox):
            self._spinbox.setSingleStep(float(step))
        else:
            self._spinbox.setSingleStep(int(step))

    def setDecimals(self, decimals: int) -> None:
        """Set the number of decimal places (VDoubleSpinBox only)."""
        if isinstance(self._spinbox, VDoubleSpinBox):
            self._spinbox.setDecimals(decimals)

    def is_double_spinbox(self) -> bool:
        """Check if this is using a VDoubleSpinBox."""
        return isinstance(self._spinbox, VDoubleSpinBox)
