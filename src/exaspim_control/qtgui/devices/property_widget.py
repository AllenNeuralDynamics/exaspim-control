"""Property-based widget components for declarative device UI generation.

This module provides a declarative approach to creating device control UIs by:
1. Extracting property metadata from device instances
2. Creating appropriate input widgets based on property characteristics
3. Handling bidirectional data flow between widgets and devices
"""

import dataclasses
import enum
import inspect
import json
import logging
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal

import inflection
from pydantic import BaseModel
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from exaspim_control.qtgui.components.input import (
    VCheckBox,
    VComboBox,
    VDoubleSpinBox,
    VLabel,
    VLineEdit,
    VSpinBox,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Complex value formatting utilities
# ============================================================================


def _is_complex_value(value: Any) -> bool:
    """Check if value is a complex type that needs special formatting.

    :param value: Value to check
    :return: True if value is a dataclass, pydantic model, dict, or list
    """
    if value is None:
        return False

    # Check for dataclass
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return True

    # Check for pydantic model (v1 and v2)
    value_type = type(value)
    if hasattr(value_type, "model_fields") or hasattr(value_type, "__fields__"):
        return True

    # Check for dict or list with content
    if isinstance(value, dict) and len(value) > 0:
        return True
    if isinstance(value, (list, tuple)) and len(value) > 2:
        return True

    return False


def _value_to_dict(value: Any) -> Any:
    """Convert complex value to a JSON-serializable dict.

    :param value: Value to convert
    :return: Dict representation or original value
    """
    if value is None:
        return None

    # Dataclass
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)

    if isinstance(value, BaseModel):
        return value.model_dump()

    # Already a dict/list
    if isinstance(value, (dict, list, tuple)):
        return value

    return value


def _format_complex_value(value: Any, indent: int = 2) -> str:
    """Format a complex value as indented JSON-like string.

    :param value: Value to format
    :param indent: Indentation level
    :return: Formatted string
    """
    try:
        dict_value = _value_to_dict(value)
        return json.dumps(dict_value, indent=indent, default=str)
    except (TypeError, ValueError):
        # Fallback to repr if JSON serialization fails
        return repr(value)


def _summarize_complex_value(value: Any, max_length: int = 50) -> str:
    """Create a short summary of a complex value.

    :param value: Value to summarize
    :param max_length: Maximum length of summary
    :return: Short summary string
    """
    value_type = type(value).__name__

    # Dataclass or pydantic - show type and field count
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = dataclasses.fields(value)
        return f"{value_type}({len(fields)} fields)"

    if isinstance(value, BaseModel):
        value = value.model_dump()

    # Dict - show key count
    if isinstance(value, dict):
        return f"dict({len(value)} items)"

    # List/tuple - show length
    if isinstance(value, (list, tuple)):
        type_name = "list" if isinstance(value, list) else "tuple"
        return f"{type_name}({len(value)} items)"

    # Fallback - truncate repr
    text = str(value)
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


# ============================================================================
# Utility functions (previously from view.widgets.base_device_widget)
# ============================================================================


def label_maker(string: str) -> str:
    """Convert underscore-separated variable names to human-readable labels.

    Capitalizes words and formats known units in brackets.

    :param string: Variable name to convert (e.g., "power_mw", "exposure_time_ms")
    :return: Formatted label (e.g., "Power [mW]", "Exposure Time [ms]")
    """
    possible_units = [
        "mm",
        "um",
        "px",
        "mW",
        "W",
        "ms",
        "C",
        "V",
        "us",
        "s",
        "uL",
        "min",
        "g",
        "mL",
    ]
    label = string.split("_")
    label = [word.capitalize() for word in label]

    for i, word in enumerate(label):
        for unit in possible_units:
            if unit.lower() == word.lower():
                label[i] = f"[{unit}]"

    return " ".join(label)


def scan_for_properties(device: object) -> dict[str, Any]:
    """Scan for properties with setters and getters in class and return dictionary.

    :param device: Object to scan through for properties
    :return: Dictionary of property names to their current values
    """
    prop_dict = {}
    for attr_name in dir(device):
        # Skip private/internal properties (starting with _)
        if attr_name.startswith("_"):
            continue
        try:
            attr = getattr(type(device), attr_name, None)
            if isinstance(attr, property) or isinstance(inspect.unwrap(attr), property):
                prop_dict[attr_name] = getattr(device, attr_name, None)
        except ValueError:
            # Some attributes in processes raise ValueError if not started
            pass

    return prop_dict


def create_widget(struct: str, *args, **kwargs) -> QWidget:
    """Create a horizontal or vertical layout populated with widgets.

    :param struct: Layout type - "H" for horizontal, "V" for vertical,
                   or two-char combo like "VH" for nested layouts
    :param args: Widgets to add to layout
    :param kwargs: Named widgets to add to layout
    :return: QWidget containing the layout
    """
    from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout

    layouts = {"H": QHBoxLayout, "V": QVBoxLayout}
    widget = QWidget()

    if struct in {"V", "H"}:
        layout = layouts[struct]()
        for arg in [*kwargs.values(), *args]:
            try:
                layout.addWidget(arg)
            except TypeError:
                layout.addLayout(arg)
        layout.setContentsMargins(0, 0, 0, 0)
        widget.setLayout(layout)
        return widget

    # Handle nested layouts (e.g., "VH", "HV")
    bin0 = {}
    bin1 = {}
    j = 0
    for v in [*kwargs.values(), *args]:
        bin0[str(v)] = v
        j += 1
        if j == 2:
            j = 0
            bin1[str(v)] = create_widget(struct=struct[0], **bin0)
            bin0 = {}
    return create_widget(struct=struct[1], **bin1)


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


def inspect_prop(device, prop_name, prop_value, updating: bool = False) -> DeviceProperty:
    # Get property descriptor from device class
    prop_descriptor = getattr(type(device), prop_name.split(".")[0], None)

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
    value_type = type(prop_value)

    # Check for options (enums, lists from driver)
    # Get device driver module for checking options/enums
    options = None
    try:
        if (device_driver := import_module(type(device).__module__)) and access == "rw":
            options = _check_driver_variables(device_driver, prop_name)
    except (ImportError, AttributeError):
        pass

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
    return DeviceProperty(
        name=prop_name,
        value=prop_value,
        access=access,
        value_type=value_type,
        unit=unit,
        minimum=min_val,
        maximum=max_val,
        step=step_val,
        options=options,
        updating=updating,
    )


def extract_device_properties(device, updating_properties: list[str] | None = None) -> dict[str, DeviceProperty]:
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
    device_properties: dict[str, DeviceProperty] = {}

    for prop_name, prop_value in properties_dict.items():
        # Flatten nested properties first
        flattened = _flatten_property(prop_name, prop_value)

        for flat_name, flat_value in flattened:
            device_properties[prop_name] = inspect_prop(
                device=device,
                prop_name=flat_name,
                prop_value=flat_value,
                updating=flat_name in updating_properties,
            )

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


def make_property_label(device_property: DeviceProperty) -> VLabel:
    """Create a styled label for a device property.

    Formats property names using label_maker() and appends unit in brackets.

    Example output: "Power [mW]:", "Temperature [°C]:", "Position [mm]:"

    :param device_property: DeviceProperty containing name and unit
    :return: VLabel with formatted text
    """
    # Extract leaf name (for nested properties like "trigger.mode")
    leaf_name = device_property.name.split(".")[-1]

    # Format label with unit
    formatted_name = label_maker(leaf_name)
    unit_str = f" [{device_property.unit}]" if device_property.unit else ""
    label_text = f"{formatted_name}{unit_str}:"

    return VLabel(label_text)


class ComplexValueWidget(QWidget):
    """Widget for displaying complex values (dataclasses, pydantic models, dicts).

    Shows a compact summary with an expand button to reveal the full formatted content.
    """

    def __init__(self, value: Any, parent: QWidget | None = None):
        super().__init__(parent)
        self._value = value
        self._expanded = False

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the collapsible UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Header row with summary and expand button
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        # Summary label
        self._summary_label = VLabel(_summarize_complex_value(self._value))
        self._summary_label.setStyleSheet("color: #888; font-size: 11px;")
        header_layout.addWidget(self._summary_label, stretch=1)

        # Expand/collapse button
        self._expand_btn = QPushButton("▶")
        self._expand_btn.setFixedSize(20, 20)
        self._expand_btn.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #888;
                border: 1px solid #505050;
                border-radius: 3px;
                font-size: 8px;
            }
            QPushButton:hover {
                background-color: #4a4a4d;
                color: #ccc;
            }
        """)
        self._expand_btn.clicked.connect(self._toggle_expand)
        header_layout.addWidget(self._expand_btn)

        layout.addWidget(header)

        # Expandable content area
        self._content = QPlainTextEdit()
        self._content.setReadOnly(True)
        self._content.setPlainText(_format_complex_value(self._value))
        self._content.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #404040;
                border-radius: 3px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10px;
            }
        """)
        self._content.setMaximumHeight(600)
        self._content.setVisible(False)
        layout.addWidget(self._content)

        # Set tooltip with full content
        self._summary_label.setToolTip(_format_complex_value(self._value))

    def _toggle_expand(self) -> None:
        """Toggle expanded/collapsed state."""
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._expand_btn.setText("▼" if self._expanded else "▶")

    def set_value(self, value: Any) -> None:
        """Update the displayed value."""
        self._value = value
        self._summary_label.setText(_summarize_complex_value(value))
        self._content.setPlainText(_format_complex_value(value))
        self._summary_label.setToolTip(_format_complex_value(value))


class PropertyValueWidget(QWidget):
    """Factory widget that creates appropriate input based on property metadata.

    Uses styled V* components from components.input:
    - VLabel (read-only simple values)
    - ComplexValueWidget (read-only dataclasses, pydantic models, dicts)
    - VComboBox (has options list)
    - VCheckBox (bool type)
    - VSpinBox (int with min/max)
    - VDoubleSpinBox (float with min/max)
    - VLineEdit (unconstrained)

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

        :return: Appropriate styled widget
        """
        prop = self.device_property

        # Complex values (dataclasses, pydantic, dicts) → CollapsibleWidget
        if _is_complex_value(prop.value):
            return self._create_complex_value_widget()

        # Read-only properties → VLabel
        if prop.access == "ro":
            return self._create_label()

        # Properties with options → VComboBox
        if prop.options:
            return self._create_combobox()

        # Boolean properties → VCheckBox
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

    def _create_complex_value_widget(self) -> ComplexValueWidget:
        """Create collapsible widget for complex values (dataclasses, pydantic, dicts)."""
        return ComplexValueWidget(self.device_property.value)

    def _create_label(self) -> VLabel:
        """Create read-only styled label."""
        value = self.device_property.value
        text = str(value)
        # Truncate long strings and add tooltip
        if len(text) > 60:
            label = VLabel(text[:57] + "...")
            label.setToolTip(text)
            return label
        return VLabel(text)

    def _create_spinbox(self) -> VSpinBox:
        """Create styled integer spinbox with constraints."""
        spinbox = VSpinBox()
        min_val = self.device_property.minimum if self.device_property.minimum is not None else spinbox.minimum()
        max_val = self.device_property.maximum if self.device_property.maximum is not None else spinbox.maximum()
        step_val = self.device_property.step if self.device_property.step is not None else 1
        spinbox.setMinimum(int(min_val))
        spinbox.setMaximum(int(max_val))
        spinbox.setSingleStep(int(step_val))
        spinbox.setValue(int(self.device_property.value))
        spinbox.valueChanged.connect(lambda v: self.valueChanged.emit(self.device_property.name, v))
        return spinbox

    def _create_double_spinbox(self) -> VDoubleSpinBox:
        """Create styled float spinbox with constraints."""
        spinbox = VDoubleSpinBox()
        spinbox.setDecimals(2)
        min_val = self.device_property.minimum if self.device_property.minimum is not None else spinbox.minimum()
        max_val = self.device_property.maximum if self.device_property.maximum is not None else spinbox.maximum()
        step_val = self.device_property.step if self.device_property.step is not None else 0.1
        spinbox.setMinimum(min_val)
        spinbox.setMaximum(max_val)
        spinbox.setSingleStep(step_val)
        spinbox.setValue(self.device_property.value)
        spinbox.valueChanged.connect(lambda v: self.valueChanged.emit(self.device_property.name, v))
        return spinbox

    def _create_combobox(self) -> VComboBox:
        """Create styled combobox with options."""
        combo = VComboBox()
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

    def _create_checkbox(self) -> VCheckBox:
        """Create styled checkbox for boolean values."""
        checkbox = VCheckBox()
        checkbox.setChecked(self.device_property.value)
        checkbox.toggled.connect(lambda v: self.valueChanged.emit(self.device_property.name, v))
        return checkbox

    def _create_lineedit(self) -> VLineEdit:
        """Create styled text input."""
        lineedit = VLineEdit()
        lineedit.setText(str(self.device_property.value))
        lineedit.editingFinished.connect(lambda: self.valueChanged.emit(self.device_property.name, self._parse_value()))
        return lineedit

    def _parse_value(self) -> Any:
        """Parse text from VLineEdit to appropriate type."""
        if isinstance(self.widget, VLineEdit):
            text = self.widget.text()
            value_type = self.device_property.value_type

            try:
                if value_type is int:
                    return int(text)
                if value_type is float:
                    return float(text)
            except ValueError:
                logger.warning(f"Failed to parse '{text}' as {value_type.__name__}")
                return self.device_property.value
            else:
                return text

        return self.device_property.value

    def set_value(self, value: Any):
        """
        Update widget value (typically called by property worker).

        :param value: New value to display
        """
        if isinstance(self.widget, ComplexValueWidget):
            self.widget.set_value(value)
        elif isinstance(self.widget, VLabel):
            text = str(value)
            if len(text) > 60:
                self.widget.setText(text[:57] + "...")
                self.widget.setToolTip(text)
            else:
                self.widget.setText(text)
        elif isinstance(self.widget, VSpinBox):
            self.widget.blockSignals(True)
            self.widget.setValue(int(value))
            self.widget.blockSignals(False)
        elif isinstance(self.widget, VDoubleSpinBox):
            self.widget.blockSignals(True)
            self.widget.setValue(float(value))
            self.widget.blockSignals(False)
        elif isinstance(self.widget, VComboBox):
            self.widget.blockSignals(True)
            self.widget.setCurrentText(str(value))
            self.widget.blockSignals(False)
        elif isinstance(self.widget, VCheckBox):
            self.widget.blockSignals(True)
            self.widget.setChecked(bool(value))
            self.widget.blockSignals(False)
        elif isinstance(self.widget, VLineEdit):
            self.widget.blockSignals(True)
            self.widget.setText(str(value))
            self.widget.blockSignals(False)

    def get_value(self) -> Any:
        """
        Get current widget value.

        :return: Current value from widget
        """
        if isinstance(self.widget, VLabel):
            return self.widget.text()
        if isinstance(self.widget, (VSpinBox, VDoubleSpinBox)):
            return self.widget.value()
        if isinstance(self.widget, VComboBox):
            return self.widget.currentText()
        if isinstance(self.widget, VCheckBox):
            return self.widget.isChecked()
        if isinstance(self.widget, VLineEdit):
            return self._parse_value()

        return None


class PropertyWidget(QWidget):
    """Complete property widget combining label and input value.

    Horizontal layout: [VLabel] [PropertyValueWidget]

    Forwards valueChanged signals from PropertyValueWidget.
    """

    valueChanged = pyqtSignal(str, object)  # (property_name, new_value)

    def __init__(self, device_property: DeviceProperty):
        """
        Initialize property widget.

        :param device_property: DeviceProperty containing all metadata
        """
        super().__init__()
        self.device_property = device_property

        self.label = make_property_label(device_property)
        self.value_widget = PropertyValueWidget(device_property)

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
