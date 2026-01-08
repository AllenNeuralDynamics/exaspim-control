"""Input widgets for user data entry."""

from exaspim_control._qtgui.primitives.input.boolean import (
    VCheckBox as CheckBox,
    VSwitch as Switch,
    VToggle as Toggle,
)
from exaspim_control._qtgui.primitives.input.number import (
    VDoubleSpinBox as DoubleSpinBox,
    VNumberInput as NumberInput,
    VSpinBox as SpinBox,
)
from exaspim_control._qtgui.primitives.input.options import (
    VComboBox as ComboBox,
    VSelect as Select,
)
from exaspim_control._qtgui.primitives.input.radio import RadioButton
from exaspim_control._qtgui.primitives.input.slider import LockableSlider
from exaspim_control._qtgui.primitives.input.text import (
    VLineEdit as LineEdit,
    VTextInput as TextInput,
)

# Backwards compatibility aliases (deprecated)
VCheckBox = CheckBox
VSwitch = Switch
VToggle = Toggle
VDoubleSpinBox = DoubleSpinBox
VNumberInput = NumberInput
VSpinBox = SpinBox
VComboBox = ComboBox
VSelect = Select
VLockableSlider = LockableSlider
VLineEdit = LineEdit
VTextInput = TextInput

__all__ = [
    # New names
    "CheckBox",
    "ComboBox",
    "DoubleSpinBox",
    "LineEdit",
    "LockableSlider",
    "NumberInput",
    "RadioButton",
    "Select",
    "SpinBox",
    "Switch",
    "TextInput",
    "Toggle",
    # Backwards compatibility (deprecated)
    "VCheckBox",
    "VComboBox",
    "VDoubleSpinBox",
    "VLineEdit",
    "VLockableSlider",
    "VNumberInput",
    "VSelect",
    "VSpinBox",
    "VSwitch",
    "VTextInput",
    "VToggle",
]
