"""Laser widget using VLockableSlider primitive."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from exaspim_control.qtgui.primitives import VToggle
from exaspim_control.qtgui.primitives.chip import Chip
from exaspim_control.qtgui.primitives.input import VLockableSlider
from exaspim_control.qtgui.utils import darken_color, hex_to_rgb, rgb_to_hex, wavelength_to_hex

if TYPE_CHECKING:
    from voxel.interfaces.laser import SpimLaser

    from exaspim_control.qtgui.model import DeviceAdapter


class PowerChip(Chip):
    """Chip displaying actual power."""

    def __init__(self, power_mw: float, color: str = "#3c3c3c", parent: QWidget | None = None) -> None:
        super().__init__(
            text=f"{power_mw:.1f} mW",
            color=color,
            border_color="#505050",
            parent=parent,
        )

    def set_power(self, power_mw: float) -> None:
        """Update the displayed power value."""
        self.setText(f"{power_mw:.1f} mW")


class LaserWidget(QWidget):
    """Widget for laser control using VLockableSlider primitive.

    Uses VLockableSlider for the 3-layer power visualization:
    - Actual: current power (progress bar)
    - Target: device setpoint (colored indicator)
    - Input: user command (white handle when unlocked)

    Layout:
    - Row 1: Enable/Disable toggle + ON/OFF label + Power chip (actual)
    - Row 2: VLockableSlider
    - Row 3: Status bar with temperature (left) and wavelength (right)
    """

    propertyChanged = pyqtSignal(str, object)

    def __init__(self, adapter: DeviceAdapter[SpimLaser], parent: QWidget | None = None) -> None:
        """Initialize the LaserWidget.

        :param adapter: DeviceAdapter for the laser device
        :param parent: Parent widget
        """
        super().__init__(parent)
        self._adapter = adapter
        self.log = logging.getLogger(f"{__name__}.{adapter.device.uid}")

        # Get device properties
        device = adapter.device
        self.wavelength_nm = device.wavelength
        self.laser_color = wavelength_to_hex(self.wavelength_nm)
        self.max_power_mw = self._get_max_power(device)

        # Calculate color variants
        rgb = hex_to_rgb(self.laser_color)
        self.laser_color_dark = rgb_to_hex(*darken_color(*rgb, factor=0.6))

        # Track state
        self._is_enabled = device.is_enabled

        # Create widgets
        self._enable_toggle = VToggle(
            setter=self._on_enable_changed,
            checked_color=self.laser_color,
        )
        self._enable_label = self._create_enable_label()
        self._power_chip = PowerChip(device.power_mw, color=self.laser_color_dark)
        self._track = VLockableSlider(
            min_value=0.0,
            max_value=self.max_power_mw,
            color=self.laser_color,
        )
        self._status_bar = self._create_status_bar()

        # Initialize toggle state
        if self._is_enabled:
            self._enable_toggle.setChecked(True)
            self._enable_label.setText("ON")
            self._enable_label.setStyleSheet(f"color: {self.laser_color}; font-size: 11px; font-weight: bold;")

        # Initialize track values
        self._track.setActual(device.power_mw)
        self._track.setTarget(device.power_setpoint_mw)

        # Build layout and connect signals
        self._setup_ui()
        self._connect_signals()

    def _get_max_power(self, device: SpimLaser) -> float:
        """Get max power from device property constraints."""
        power_setpoint = getattr(device, "power_setpoint_mw", None)
        if power_setpoint is not None and hasattr(power_setpoint, "max_value"):
            return power_setpoint.max_value or 110.0
        return 110.0

    @property
    def device(self) -> SpimLaser:
        """Get the laser device."""
        return self._adapter.device

    def _create_enable_label(self) -> QLabel:
        """Create the ON/OFF label."""
        label = QLabel("OFF")
        label.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        label.setMinimumWidth(30)
        return label

    def _create_status_bar(self) -> QFrame:
        """Create status bar with temperature and wavelength."""
        frame = QFrame()
        frame.setObjectName("laserStatusBar")
        frame.setStyleSheet("""
            QFrame#laserStatusBar {
                background-color: #252526;
                border-top: 1px solid #404040;
            }
        """)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Temperature (left)
        temp_label = QLabel("Temp:")
        temp_label.setStyleSheet("color: #888; font-size: 10px; border: none;")
        layout.addWidget(temp_label)

        self._temp_value_label = QLabel("-- °C")
        self._temp_value_label.setStyleSheet("color: #ccc; font-size: 10px; border: none;")
        layout.addWidget(self._temp_value_label)

        layout.addStretch()

        # Wavelength (right)
        wavelength_label = QLabel(f"{self.wavelength_nm} nm")
        wavelength_label.setStyleSheet(f"color: {self.laser_color}; font-size: 10px; font-weight: bold; border: none;")
        layout.addWidget(wavelength_label)

        return frame

    def _setup_ui(self) -> None:
        """Build the widget layout."""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # Row 1: Toggle + label + power chip
        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        header_row.addWidget(self._enable_toggle)
        header_row.addWidget(self._enable_label)
        header_row.addStretch()
        header_row.addWidget(self._power_chip)
        layout.addLayout(header_row)

        # Row 2: Power track
        layout.addWidget(self._track)

        # Row 3: Status bar
        layout.addWidget(self._status_bar)

    def _connect_signals(self) -> None:
        """Connect widget signals."""
        # Track input released -> set power
        self._track.inputReleased.connect(self._on_power_requested)

        # Adapter property updates -> update display
        self._adapter.propertyUpdated.connect(self._on_property_update)

    def _on_power_requested(self, power: float) -> None:
        """Handle user power request from track slider."""
        self.device.power_setpoint_mw = power
        self.propertyChanged.emit("power_setpoint_mw", power)

    def _on_enable_changed(self, enabled: bool) -> None:
        """Handle enable/disable toggle."""
        if enabled:
            self.device.enable()
            self._is_enabled = True
            self._enable_label.setText("ON")
            self._enable_label.setStyleSheet(f"color: {self.laser_color}; font-size: 11px; font-weight: bold;")
        else:
            self.device.disable()
            self._is_enabled = False
            self._enable_label.setText("OFF")
            self._enable_label.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")

    def _on_property_update(self, prop_name: str, value: Any) -> None:
        """Handle property updates from adapter polling."""
        if prop_name == "power_mw":
            self._track.setActual(value)
            self._power_chip.set_power(value)

        elif prop_name == "power_setpoint_mw":
            self._track.setTarget(value)

        elif prop_name == "temperature_c":
            if value is not None:
                self._temp_value_label.setText(f"{value:.1f} °C")
            else:
                self._temp_value_label.setText("-- °C")

        elif prop_name == "is_enabled" and value != self._is_enabled:
            self._is_enabled = value
            self._enable_toggle.blockSignals(True)
            self._enable_toggle.setChecked(value)
            self._enable_toggle.blockSignals(False)
            if value:
                self._enable_label.setText("ON")
                self._enable_label.setStyleSheet(f"color: {self.laser_color}; font-size: 11px; font-weight: bold;")
            else:
                self._enable_label.setText("OFF")
                self._enable_label.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
