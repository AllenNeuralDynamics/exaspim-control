"""Property-based widget components for declarative device UI generation.

This module provides a declarative approach to creating device control UIs by:
1. Extracting property metadata from device instances
2. Creating appropriate input widgets based on property characteristics
3. Handling bidirectional data flow between widgets and devices
"""

import enum
import logging
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal

import inflection
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QDoubleValidator, QIntValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)
from view.widgets.base_device_widget import label_maker, scan_for_properties

logger = logging.getLogger(__name__)


@dataclass
class DeviceProperty:
    """Declarative property descriptor for device properties.

    This dataclass contains all metadata needed to create an appropriate
    input widget for a device property, including constraints, units, and
    whether the property needs real-time updates.

    Example:
        DeviceProperty(
            name="power_mw",
            value=100.0,
            access="rw",
            value_type=float,
            unit="mW",
            minimum=0.0,
            maximum=200.0,
            step=0.1,
            updating=True
        )
    """

    name: str  # Property name (e.g., "power_mw" or "trigger.mode" for nested)
    value: Any  # Current value
    access: Literal["ro", "rw"]  # Read-only or read-write
    value_type: type  # int, float, str, bool
    unit: str | None = None  # e.g., "mW", "mm", "°C"
    minimum: float | None = None  # Min constraint (for spinboxes)
    maximum: float | None = None  # Max constraint (for spinboxes)
    step: float | None = None  # Step size (for spinboxes)
    options: list | dict | None = None  # Options for ComboBox
    updating: bool = False  # Whether this property needs a worker thread


def extract_device_properties(device, updating_properties: list[str] | None = None) -> list[DeviceProperty]:
    """
    Extract DeviceProperty objects from a device instance.

    Scans all properties on the device, extracts metadata from property
    decorators, and creates DeviceProperty descriptors for UI generation.

    Process:
    1. Scan device for all properties using scan_for_properties()
    2. For each property, extract metadata from @DeliminatedProperty decorator
    3. Determine access mode (ro/rw) based on setter presence
    4. Flatten nested dicts/lists to dot notation
    5. Check device driver for enum/option values
    6. Mark properties in updating_properties list for worker threads

    :param device: Device instance to extract properties from
    :param updating_properties: List of property names that need real-time updates
    :return: List of DeviceProperty objects
    """
    updating_properties = updating_properties or []
    properties_dict = scan_for_properties(device)
    device_type = type(device)

    # Get device driver module for checking options/enums
    try:
        device_driver = import_module(device_type.__module__)
    except (ImportError, AttributeError):
        device_driver = None

    device_properties = []

    for prop_name, prop_value in properties_dict.items():
        # Flatten nested properties first
        flattened = _flatten_property(prop_name, prop_value)

        for flat_name, flat_value in flattened:
            # Get property descriptor from device class
            prop_descriptor = getattr(device_type, flat_name.split(".")[0], None)

            # Extract metadata from @DeliminatedProperty decorator
            unit = getattr(prop_descriptor, "unit", None)
            minimum = getattr(prop_descriptor, "minimum", None)
            maximum = getattr(prop_descriptor, "maximum", None)
            step = getattr(prop_descriptor, "step", None)

            # Resolve callable min/max (some properties use lambdas)
            if callable(minimum):
                try:
                    minimum = minimum(device)
                except (TypeError, ValueError):
                    minimum = None
            if callable(maximum):
                try:
                    maximum = maximum(device)
                except (TypeError, ValueError):
                    maximum = None

            # Determine access mode
            has_setter = getattr(prop_descriptor, "fset", None) is not None
            access = "rw" if has_setter else "ro"

            # Determine value type
            value_type = type(flat_value)

            # Check for options (enums, lists from driver)
            options = None
            if device_driver and access == "rw":
                options = _check_driver_variables(device_driver, flat_name)

            # Ensure minimum, maximum, and step are float or None
            def to_float_or_none(val):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None

            min_val = to_float_or_none(minimum)
            max_val = to_float_or_none(maximum)
            step_val = to_float_or_none(step)

            # Create DeviceProperty
            dev_prop = DeviceProperty(
                name=flat_name,
                value=flat_value,
                access=access,
                value_type=value_type,
                unit=unit,
                minimum=min_val,
                maximum=max_val,
                step=step_val,
                options=options,
                updating=flat_name in updating_properties,
            )

            device_properties.append(dev_prop)

    return device_properties


def _flatten_property(name: str, value: Any, parent_path: str = "") -> list[tuple[str, Any]]:
    """
    Recursively flatten nested dicts/lists to dot notation.

    Examples:
        trigger = {"mode": "external", "polarity": "rising"}
        → [("trigger.mode", "external"), ("trigger.polarity", "rising")]

        roi = [100, 200]
        → [("roi.0", 100), ("roi.1", 200)]

    :param name: Property name
    :param value: Property value
    :param parent_path: Parent path for nested properties
    :return: List of (flat_name, value) tuples
    """
    current_path = f"{parent_path}.{name}" if parent_path else name

    # Handle dict
    if isinstance(value, dict) and not isinstance(value, enum.EnumMeta):
        flattened = []
        for k, v in value.items():
            flattened.extend(_flatten_property(k, v, current_path))
        return flattened

    # Handle list
    if isinstance(value, list):
        flattened = []
        for i, v in enumerate(value):
            flattened.extend(_flatten_property(str(i), v, current_path))
        return flattened

    # Base case: return as-is
    return [(current_path, value)]


def _check_driver_variables(device_driver, prop_name: str) -> list | dict | None:
    """
    Check device driver for option lists/enums for a property.

    Searches for matching variables in the device driver module that
    might define valid options for a property (e.g., MODULATION_MODES).

    :param device_driver: Device driver module
    :param prop_name: Property name to search for
    :return: Options dict/list or None
    """
    driver_vars = device_driver.__dict__
    search_name = inflection.pluralize(prop_name.replace(".", "_"))

    for variable in driver_vars:
        # Match plural form of property name
        if search_name.lower() in variable.lower():
            var_value = driver_vars[variable]

            # Return dict or list of options
            if isinstance(var_value, (dict, list)):
                return var_value

            # Handle enum
            if isinstance(var_value, enum.EnumMeta):
                return {item.name: item.value for item in var_value}  # type: ignore

    return None


class PropertyLabel(QLabel):
    """Label widget for property names with optional unit display.

    Formats property names using label_maker() and appends unit in brackets.

    Example output: "Power [mW]:", "Temperature [°C]:", "Position [mm]:"
    """

    def __init__(self, device_property: DeviceProperty):
        """
        Initialize property label.

        :param device_property: DeviceProperty containing name and unit
        """
        # Extract leaf name (for nested properties like "trigger.mode")
        leaf_name = device_property.name.split(".")[-1]

        # Format label with unit
        formatted_name = label_maker(leaf_name)
        unit_str = f" [{device_property.unit}]" if device_property.unit else ""
        label_text = f"{formatted_name}{unit_str}:"

        super().__init__(label_text)


class PropertyValue(QWidget):
    """Factory widget that creates appropriate input based on property metadata.

    Creates one of:
    - QLabel (read-only)
    - QComboBox (has options list)
    - QCheckBox (bool type)
    - QSpinBox (int with min/max)
    - QDoubleSpinBox (float with min/max)
    - QLineEdit (unconstrained)

    Emits valueChanged signal when user modifies the value.
    """

    valueChanged = pyqtSignal(str, object)  # (property_name, new_value)

    def __init__(self, device_property: DeviceProperty):
        """
        Initialize property value widget.

        :param device_property: DeviceProperty containing metadata
        """
        super().__init__()
        self.device_property = device_property
        self.widget = self._create_widget()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.widget)

    def _create_widget(self) -> QWidget:
        """
        Determine and create appropriate widget type based on property metadata.

        :return: Appropriate Qt widget
        """
        prop = self.device_property

        # Read-only properties → QLabel
        if prop.access == "ro":
            return self._create_label()

        # Properties with options → QComboBox
        if prop.options:
            return self._create_combobox()

        # Boolean properties → QCheckBox
        if prop.value_type is bool:
            return self._create_checkbox()

        # Numeric properties with constraints → SpinBox
        if prop.minimum is not None and prop.maximum is not None:
            if prop.value_type is int or (isinstance(prop.value, int) and not isinstance(prop.value, bool)):
                return self._create_spinbox()
            if prop.value_type is float or isinstance(prop.value, float):
                return self._create_double_spinbox()

        # Default: editable text field
        return self._create_lineedit()

    def _create_label(self) -> QLabel:
        """Create read-only label."""
        return QLabel(str(self.device_property.value))

    def _create_spinbox(self) -> QSpinBox:
        """Create integer spinbox with constraints."""
        spinbox = QSpinBox()
        min_val = self.device_property.minimum if self.device_property.minimum is not None else spinbox.minimum()
        max_val = self.device_property.maximum if self.device_property.maximum is not None else spinbox.maximum()
        step_val = self.device_property.step if self.device_property.step is not None else 1
        spinbox.setMinimum(int(min_val))
        spinbox.setMaximum(int(max_val))
        spinbox.setSingleStep(int(step_val))
        spinbox.setValue(int(self.device_property.value))
        spinbox.valueChanged.connect(lambda v: self.valueChanged.emit(self.device_property.name, v))
        return spinbox

    def _create_double_spinbox(self) -> QDoubleSpinBox:
        """Create float spinbox with constraints."""
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(2)  # Default 2 decimal places
        min_val = self.device_property.minimum if self.device_property.minimum is not None else spinbox.minimum()
        max_val = self.device_property.maximum if self.device_property.maximum is not None else spinbox.maximum()
        step_val = self.device_property.step if self.device_property.step is not None else 0.1
        spinbox.setMinimum(min_val)
        spinbox.setMaximum(max_val)
        spinbox.setSingleStep(step_val)
        spinbox.setValue(self.device_property.value)
        spinbox.valueChanged.connect(lambda v: self.valueChanged.emit(self.device_property.name, v))
        return spinbox

    def _create_combobox(self) -> QComboBox:
        """Create combobox with options."""
        combo = QComboBox()
        options = self.device_property.options

        # Handle empty or None options
        if not options:
            combo.setEnabled(False)
            return combo

        # If options is a dict, keys may be int or str
        if isinstance(options, dict):
            key_map = {str(k): k for k in options}
            combo.addItems(list(key_map.keys()))
        else:
            key_map = {str(x): x for x in options}
            combo.addItems(list(key_map.keys()))

        combo.setCurrentText(str(self.device_property.value))

        def on_change(v):
            # Map back to original type (int or str)
            self.valueChanged.emit(self.device_property.name, key_map[v])

        combo.currentTextChanged.connect(on_change)
        return combo

    def _create_checkbox(self) -> QCheckBox:
        """Create checkbox for boolean values."""
        checkbox = QCheckBox()
        checkbox.setChecked(self.device_property.value)
        checkbox.toggled.connect(lambda v: self.valueChanged.emit(self.device_property.name, v))
        return checkbox

    def _create_lineedit(self) -> QLineEdit:
        """Create text input with optional validation."""
        lineedit = QLineEdit(str(self.device_property.value))

        # Add validator based on type
        if self.device_property.value_type is int:
            validator = QIntValidator()
            lineedit.setValidator(validator)
        elif self.device_property.value_type is float:
            validator = QDoubleValidator()
            validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            validator.setDecimals(2)
            lineedit.setValidator(validator)

        lineedit.editingFinished.connect(lambda: self.valueChanged.emit(self.device_property.name, self._parse_value()))
        return lineedit

    def _parse_value(self) -> Any:
        """Parse text from QLineEdit to appropriate type."""
        if isinstance(self.widget, QLineEdit):
            text = self.widget.text()
            value_type = self.device_property.value_type

            try:
                if value_type is int:
                    return int(text)
                if value_type is float:
                    return float(text)
            except ValueError:
                logger.warning(f"Failed to parse '{text}' as {value_type.__name__}")
                return self.device_property.value  # Return original value
            else:
                return text

        return self.device_property.value

    def set_value(self, value: Any):
        """
        Update widget value (typically called by property worker).

        :param value: New value to display
        """
        if isinstance(self.widget, QLabel):
            self.widget.setText(str(value))
        elif isinstance(self.widget, QSpinBox):
            self.widget.blockSignals(True)
            self.widget.setValue(int(value))
            self.widget.blockSignals(False)
        elif isinstance(self.widget, QDoubleSpinBox):
            self.widget.blockSignals(True)
            self.widget.setValue(float(value))
            self.widget.blockSignals(False)
        elif isinstance(self.widget, QComboBox):
            self.widget.blockSignals(True)
            self.widget.setCurrentText(str(value))
            self.widget.blockSignals(False)
        elif isinstance(self.widget, QCheckBox):
            self.widget.blockSignals(True)
            self.widget.setChecked(bool(value))
            self.widget.blockSignals(False)
        elif isinstance(self.widget, QLineEdit):
            self.widget.blockSignals(True)
            self.widget.setText(str(value))
            self.widget.blockSignals(False)

    def get_value(self) -> Any:
        """
        Get current widget value.

        :return: Current value from widget
        """
        if isinstance(self.widget, QLabel):
            return self.widget.text()
        if isinstance(self.widget, (QSpinBox, QDoubleSpinBox)):
            return self.widget.value()
        if isinstance(self.widget, QComboBox):
            return self.widget.currentText()
        if isinstance(self.widget, QCheckBox):
            return self.widget.isChecked()
        if isinstance(self.widget, QLineEdit):
            return self._parse_value()

        return None


class PropertyWidget(QWidget):
    """Complete property widget combining label and input value.

    Horizontal layout: [PropertyLabel] [PropertyValue]

    Forwards valueChanged signals from PropertyValue.
    """

    valueChanged = pyqtSignal(str, object)  # (property_name, new_value)

    def __init__(self, device_property: DeviceProperty):
        """
        Initialize property widget.

        :param device_property: DeviceProperty containing all metadata
        """
        super().__init__()
        self.device_property = device_property

        self.label = PropertyLabel(device_property)
        self.value_widget = PropertyValue(device_property)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        layout.addWidget(self.value_widget)

        # Forward valueChanged signal
        self.value_widget.valueChanged.connect(self.valueChanged)

    def set_value(self, value: Any):
        """
        Update value (typically from property worker).

        :param value: New value
        """
        self.value_widget.set_value(value)

    def get_value(self) -> Any:
        """
        Get current value.

        :return: Current value
        """
        return self.value_widget.get_value()

    def setEnabled(self, a0: bool):
        """
        Enable or disable the value widget.

        :param a0: Whether widget should be enabled
        """
        self.value_widget.setEnabled(a0)
        super().setEnabled(a0)
