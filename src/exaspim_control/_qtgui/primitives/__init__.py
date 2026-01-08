"""Reusable UI primitives for the ExA-SPIM Control application.

Design System Structure:
    primitives/
    ├── colors.py           # Design tokens
    ├── containers/         # Card, AccordionCard
    ├── buttons/            # Button, IconButton
    ├── display/            # Label, Chip
    ├── input/              # LineEdit, ComboBox, SpinBox, Toggle, etc.
    └── layout/             # HStack, VStack, Grid, Field, FormBuilder
"""

# Design tokens
from exaspim_control._qtgui.primitives.colors import Colors

# Buttons
from exaspim_control._qtgui.primitives.buttons import Button, IconButton

# Containers
from exaspim_control._qtgui.primitives.containers import AccordionCard, Card, TabWidget

# Display
from exaspim_control._qtgui.primitives.display import Chip, Label, Separator, Spinner

# Inputs
from exaspim_control._qtgui.primitives.input import (
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    LineEdit,
    LockableSlider,
    NumberInput,
    RadioButton,
    Select,
    SpinBox,
    Switch,
    TextInput,
    Toggle,
)

# Layout
from exaspim_control._qtgui.primitives.layout import (
    Field,
    FormBuilder,
    Grid,
    HStack,
    InfoRow,
    VStack,
)

__all__ = [
    "AccordionCard",
    "Button",
    "Card",
    "CheckBox",
    "Chip",
    "Colors",
    "ComboBox",
    "DoubleSpinBox",
    "Field",
    "FormBuilder",
    "Grid",
    "HStack",
    "IconButton",
    "InfoRow",
    "Label",
    "LineEdit",
    "LockableSlider",
    "NumberInput",
    "RadioButton",
    "Select",
    "Separator",
    "SpinBox",
    "Spinner",
    "Switch",
    "TabWidget",
    "TextInput",
    "Toggle",
    "VStack",
]
