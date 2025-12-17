"""Property widget using voxel.device PropertyInfo."""

from typing import Any, Literal

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from voxel.device import PropertyInfo

from exaspim_control.qtgui.components.input import (
    VCheckBox,
    VComboBox,
    VDoubleSpinBox,
    VLabel,
    VLineEdit,
    VSpinBox,
)


class PropertyWidget(QWidget):
    """Widget for a single device property.

    Creates appropriate input widget based on PropertyInfo metadata and
    the rich value types from voxel.device (DeliminatedFloat, EnumeratedString, etc).
    """

    valueChanged = pyqtSignal(str, object)

    def __init__(
        self,
        device: Any,
        info: PropertyInfo,
        label_position: Literal["H", "V"] | None = None,
        parent: QWidget | None = None,
    ):
        """Initialize property widget.

        :param device: Device instance to get property value from
        :param info: PropertyInfo from voxel.device
        :param label_position: "H" for horizontal, "V" for vertical, None for no label
        :param parent: Parent widget
        """
        super().__init__(parent)
        self._device = device
        self._info = info

        value = getattr(device, info.name)
        self._value_widget = self._create_value_widget(value)

        if label_position == "H":
            layout = QHBoxLayout(self)
            layout.addWidget(self._create_label())
            layout.addWidget(self._value_widget, stretch=1)
        elif label_position == "V":
            layout = QVBoxLayout(self)
            layout.addWidget(self._create_label())
            layout.addWidget(self._value_widget)
        else:
            layout = QHBoxLayout(self)
            layout.addWidget(self._value_widget)

        layout.setContentsMargins(0, 0, 0, 0)

    @property
    def info(self) -> PropertyInfo:
        """Get the PropertyInfo for this widget."""
        return self._info

    @property
    def value_widget(self) -> QWidget:
        """Get the underlying input widget."""
        return self._value_widget

    def _create_label(self) -> VLabel:
        """Create label from PropertyInfo."""
        text = self._info.label
        if self._info.units:
            text = f"{text} [{self._info.units}]"
        return VLabel(text)

    def _create_value_widget(self, value: Any) -> QWidget:
        """Create appropriate input widget based on value type and PropertyInfo."""
        info = self._info

        # Read-only → label
        if info.access == "ro":
            return self._create_label_widget(value)

        # Enumerated types (EnumeratedString, EnumeratedInt) → combobox
        if hasattr(value, "options") and value.options:
            return self._create_combobox(value)

        # Boolean → checkbox
        if info.dtype == "bool":
            return self._create_checkbox(value)

        # Deliminated types (DeliminatedFloat, DeliminatedInt) → spinbox
        if hasattr(value, "min_value") and hasattr(value, "max_value"):
            if info.dtype == "int":
                return self._create_spinbox(value)
            return self._create_double_spinbox(value)

        # Default: line edit
        return self._create_lineedit(value)

    def _create_label_widget(self, value: Any) -> VLabel:
        """Create read-only label."""
        text = str(value)
        if len(text) > 60:
            label = VLabel(text[:57] + "...")
            label.setToolTip(text)
            return label
        return VLabel(text)

    def _create_combobox(self, value: Any) -> VComboBox:
        """Create combobox for enumerated values."""
        combo = VComboBox()
        self._update_combobox_options(combo, value)
        combo.setCurrentText(str(value))
        combo.currentTextChanged.connect(
            lambda v: self.valueChanged.emit(self._info.name, v)
        )
        return combo

    def _update_combobox_options(self, combo: VComboBox, value: Any) -> None:
        """Update combobox options from enumerated value."""
        if not hasattr(value, "options") or not value.options:
            return
        new_options = [str(o) for o in value.options]
        current_options = [combo.itemText(i) for i in range(combo.count())]
        if new_options != current_options:
            current_text = combo.currentText()
            combo.clear()
            combo.addItems(new_options)
            if current_text in new_options:
                combo.setCurrentText(current_text)

    def _create_checkbox(self, value: Any) -> VCheckBox:
        """Create checkbox for boolean values."""
        checkbox = VCheckBox()
        checkbox.setChecked(bool(value))
        checkbox.toggled.connect(
            lambda v: self.valueChanged.emit(self._info.name, v)
        )
        return checkbox

    def _create_spinbox(self, value: Any) -> VSpinBox:
        """Create spinbox for deliminated integers."""
        spinbox = VSpinBox()
        self._update_spinbox_constraints(spinbox, value)
        spinbox.setValue(int(value))
        spinbox.valueChanged.connect(
            lambda v: self.valueChanged.emit(self._info.name, v)
        )
        return spinbox

    def _create_double_spinbox(self, value: Any) -> VDoubleSpinBox:
        """Create spinbox for deliminated floats."""
        spinbox = VDoubleSpinBox()
        self._update_spinbox_constraints(spinbox, value)
        spinbox.setValue(float(value))
        spinbox.valueChanged.connect(
            lambda v: self.valueChanged.emit(self._info.name, v)
        )
        return spinbox

    def _update_spinbox_constraints(self, spinbox: VSpinBox | VDoubleSpinBox, value: Any) -> None:
        """Update spinbox min/max/step from deliminated value."""
        if not hasattr(value, "min_value") or not hasattr(value, "max_value"):
            return
        is_int = isinstance(spinbox, VSpinBox)
        if value.min_value is not None:
            spinbox.setMinimum(int(value.min_value) if is_int else value.min_value)
        if value.max_value is not None:
            spinbox.setMaximum(int(value.max_value) if is_int else value.max_value)
        if hasattr(value, "step") and value.step is not None:
            spinbox.setSingleStep(int(value.step) if is_int else value.step)

    def _create_lineedit(self, value: Any) -> VLineEdit:
        """Create line edit for unconstrained values."""
        lineedit = VLineEdit()
        lineedit.setText(str(value))
        lineedit.editingFinished.connect(
            lambda: self.valueChanged.emit(self._info.name, lineedit.text())
        )
        return lineedit

    def set_value(self, value: Any) -> None:
        """Update widget with new value and constraints (from polling)."""
        widget = self._value_widget
        widget.blockSignals(True)

        if isinstance(widget, VLabel):
            text = str(value)
            if len(text) > 60:
                widget.setText(text[:57] + "...")
                widget.setToolTip(text)
            else:
                widget.setText(text)
        elif isinstance(widget, VSpinBox):
            self._update_spinbox_constraints(widget, value)
            widget.setValue(int(value))
        elif isinstance(widget, VDoubleSpinBox):
            self._update_spinbox_constraints(widget, value)
            widget.setValue(float(value))
        elif isinstance(widget, VComboBox):
            self._update_combobox_options(widget, value)
            widget.setCurrentText(str(value))
        elif isinstance(widget, VCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, VLineEdit):
            widget.setText(str(value))

        widget.blockSignals(False)

    def get_value(self) -> Any:
        """Get current value from widget."""
        widget = self._value_widget
        if isinstance(widget, VLabel):
            return widget.text()
        if isinstance(widget, (VSpinBox, VDoubleSpinBox)):
            return widget.value()
        if isinstance(widget, VComboBox):
            return widget.currentText()
        if isinstance(widget, VCheckBox):
            return widget.isChecked()
        if isinstance(widget, VLineEdit):
            return widget.text()
        return None
