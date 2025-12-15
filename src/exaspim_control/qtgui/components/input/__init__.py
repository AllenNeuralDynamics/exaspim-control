"""Generic input widgets for device control."""

from exaspim_control.qtgui.components.input.button import VButton, VIconButton
from exaspim_control.qtgui.components.input.checkbox import VCheckBox, VSwitch
from exaspim_control.qtgui.components.input.input_group import FlowDirection, create_input_group
from exaspim_control.qtgui.components.input.label import LiveValueLabel, VLabel
from exaspim_control.qtgui.components.input.number import VDoubleSpinBox, VNumberInput, VSpinBox
from exaspim_control.qtgui.components.input.select import VComboBox, VSelect
from exaspim_control.qtgui.components.input.text import VLineEdit, VTextInput
from exaspim_control.qtgui.components.input.toggle import VToggle

__all__ = [
    # Button
    "VButton",
    "VIconButton",
    # Checkbox
    "VCheckBox",
    "VSwitch",
    # Label
    "LiveValueLabel",
    "VLabel",
    # Number
    "VNumberInput",
    "VSpinBox",
    "VDoubleSpinBox",
    # Select
    "VComboBox",
    "VSelect",
    # Text
    "VLineEdit",
    "VTextInput",
    # Toggle
    "VToggle",
    # Layout
    "FlowDirection",
    "create_input_group",
]
