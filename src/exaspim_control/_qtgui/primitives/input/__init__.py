"""Generic input widgets for device control."""

from exaspim_control._qtgui.primitives.input.boolean import VCheckBox, VSwitch, VToggle
from exaspim_control._qtgui.primitives.input.icon_button import VIconButton
from exaspim_control._qtgui.primitives.input.label import VLabel, VValueLabel
from exaspim_control._qtgui.primitives.input.number import VDoubleSpinBox, VNumberInput, VSpinBox
from exaspim_control._qtgui.primitives.input.options import VComboBox, VSelect
from exaspim_control._qtgui.primitives.input.slider import VLockableSlider
from exaspim_control._qtgui.primitives.input.status_badge import VStatusBadge
from exaspim_control._qtgui.primitives.input.text import VLineEdit, VTextInput

__all__ = [
    "VCheckBox",
    "VComboBox",
    "VDoubleSpinBox",
    "VIconButton",
    "VLabel",
    "VLineEdit",
    "VLockableSlider",
    "VNumberInput",
    "VSelect",
    "VSpinBox",
    "VStatusBadge",
    "VSwitch",
    "VTextInput",
    "VToggle",
    "VValueLabel",
]
