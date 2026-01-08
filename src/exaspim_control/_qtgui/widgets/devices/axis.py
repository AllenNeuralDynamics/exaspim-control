"""Axis position widget using LockableSlider primitive."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from exaspim_control._qtgui.primitives import Chip, Label, LockableSlider

if TYPE_CHECKING:
    from voxel.interfaces.axes import Axis

    from exaspim_control._qtgui.model import DeviceAdapter


class AxisWidget(QWidget):
    """Compact axis control widget with position display and move command slider.

    Uses LockableSlider primitive for the 3-layer track visualization:
    - Actual: current position (progress bar)
    - Target: move destination (colored indicator)
    - Input: user command (white handle when unlocked)

    Layout: [Label] [====LockableSlider====] [value] [unit]
    """

    limitsChanged = pyqtSignal(float, float)  # (min, max) emitted when limits change

    def __init__(
        self,
        name: str,
        adapter: DeviceAdapter[Axis],
        min_pos: float = 0.0,
        max_pos: float = 100.0,
        unit: str = "mm",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize axis widget.

        :param name: Display name for the axis
        :param adapter: DeviceAdapter for the axis device
        :param min_pos: Minimum position value
        :param max_pos: Maximum position value
        :param unit: Unit label (e.g., "mm")
        :param parent: Parent widget
        """
        super().__init__(parent)
        self._adapter = adapter
        self._name = name
        self._min_pos = min_pos
        self._max_pos = max_pos
        self._unit = unit

        self.log = logging.getLogger(f"{__name__}.{name}")

        # Create widgets
        self._name_chip = self._create_name_chip()
        self._track = LockableSlider(
            min_value=min_pos,
            max_value=max_pos,
            color="#0078d4",
        )
        self._value_label = self._create_value_label()
        self._unit_label = self._create_unit_label()

        # Setup UI and connect signals
        self._setup_ui()
        self._connect_signals()

        # Initialize from axis
        self._refresh()

    @property
    def device(self) -> Axis:
        """Get the axis device."""
        return self._adapter.device

    @property
    def axis(self) -> Axis:
        """Get the axis device (alias for device)."""
        return self._adapter.device

    def _create_name_chip(self) -> Chip:
        """Create the axis name chip."""
        chip = Chip(self._name, color="#3c3c3c", border_color="#505050")
        chip.setFixedWidth(100)
        return chip

    def _create_value_label(self) -> Label:
        """Create the position value label."""
        label = Label("0.00", variant="value")
        label.setFixedWidth(60)
        return label

    def _create_unit_label(self) -> Label:
        """Create the unit label."""
        label = Label(self._unit, variant="muted")
        label.setFixedWidth(20)
        return label

    def _setup_ui(self) -> None:
        """Set up the widget layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        layout.addWidget(self._name_chip)
        layout.addWidget(self._track, stretch=1)
        layout.addWidget(self._value_label)
        layout.addWidget(self._unit_label)

    def _connect_signals(self) -> None:
        """Connect widget signals."""
        # Track input released -> move axis
        self._track.inputReleased.connect(self._on_move_requested)

        # Adapter property updates -> update track
        self._adapter.propertyUpdated.connect(self._on_property_update)

    def _on_move_requested(self, position: float) -> None:
        """Handle user move request from track slider."""
        try:
            self.device.move_abs(position)
            # Set target to the commanded position
            self._track.setTarget(position)
            self.log.debug(f"Moving {self._name} to {position:.2f} {self._unit}")
        except Exception:
            self.log.exception(f"Failed to move {self._name}")

    def _on_property_update(self, prop_name: str, value: Any) -> None:
        """Handle property updates from adapter polling."""
        if prop_name == "position_mm":
            self._track.setActual(value)
            self._value_label.setText(f"{value:.2f}")
            # For axis, when stationary, target == actual
            # (target is only different during movement)
            self._track.setTarget(value)

        elif prop_name == "lower_limit_mm":
            if value != self._min_pos:
                self._min_pos = value
                self._track.setRange(self._min_pos, self._max_pos)
                self.limitsChanged.emit(self._min_pos, self._max_pos)

        elif prop_name == "upper_limit_mm":
            if value != self._max_pos:
                self._max_pos = value
                self._track.setRange(self._min_pos, self._max_pos)
                self.limitsChanged.emit(self._min_pos, self._max_pos)

    def _refresh(self) -> None:
        """Refresh position from axis."""
        try:
            position = self.device.position_mm
            self._track.setActual(position)
            self._track.setTarget(position)
            self._value_label.setText(f"{position:.2f}")
        except Exception:
            self.log.exception(f"Failed to read {self._name} position")

    def set_position(self, position: float) -> None:
        """Set the displayed position (without moving axis)."""
        self._track.setActual(position)
        self._track.setTarget(position)
        self._value_label.setText(f"{position:.2f}")

    def set_range(self, min_pos: float, max_pos: float) -> None:
        """Set the position range."""
        self._min_pos = min_pos
        self._max_pos = max_pos
        self._track.setRange(min_pos, max_pos)
