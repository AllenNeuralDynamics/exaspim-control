"""Laser widget with three-layer power visualization."""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from voxel.interfaces.laser import SpimLaser

from exaspim_control.qtgui.components import VToggle
from exaspim_control.qtgui.components.chip import Chip
from exaspim_control.qtgui.devices.device_adapter import DeviceAdapter
from exaspim_control.qtgui.utils import darken_color, hex_to_rgb, rgb_to_hex, wavelength_to_hex


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
    """Widget for laser control with three-layer power visualization.

    Uses composition with DeviceAdapter rather than inheritance.

    Layout:
    - Row 1: Enable/Disable toggle + ON/OFF label + Power chip (actual)
    - Row 2: [Progress bar + Setpoint indicator + Command slider] + Link checkbox
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

        # Track states
        self._is_enabled = device.is_enabled
        self._is_linked = True  # Start linked (command follows setpoint)
        self._slider_scale = 1000

        # Create UI
        self._create_header_widgets()
        self._create_power_track()
        self._create_status_bar()

        # Initialize toggle state
        if self._is_enabled:
            self._enable_toggle.setChecked(True)
            self._enable_label.setText("ON")
            self._enable_label.setStyleSheet(f"color: {self.laser_color}; font-size: 11px; font-weight: bold;")

        # Build layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._build_layout())

        # Connect to adapter property updates (thread-safe via Qt signal)
        adapter.propertyUpdated.connect(self._on_property_update)

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

    def _create_header_widgets(self) -> None:
        """Create header row widgets."""
        self._enable_toggle = VToggle(
            setter=self._on_enable_changed,
            checked_color=self.laser_color,
        )

        self._enable_label = QLabel("OFF")
        self._enable_label.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        self._enable_label.setMinimumWidth(30)

        self._power_chip = PowerChip(self.device.power_mw, color=self.laser_color_dark)

    def _create_power_track(self) -> None:
        """Create the three-layer power track widget."""
        self._track_widget = QWidget()
        self._track_widget.setFixedHeight(24)

        # Progress bar (bottom) - shows actual power
        self._progress_bar = QProgressBar(self._track_widget)
        self._progress_bar.setRange(0, self._slider_scale)
        self._progress_bar.setValue(self._power_to_slider(self.device.power_mw))
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #2d2d30;
                border: 1px solid #505050;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {self.laser_color};
                border-radius: 3px;
            }}
        """)

        # Setpoint indicator slider (middle) - wider, semi-transparent, tracks device setpoint
        self._setpoint_indicator = QSlider(Qt.Orientation.Horizontal, self._track_widget)
        self._setpoint_indicator.setRange(0, self._slider_scale)
        self._setpoint_indicator.setValue(self._power_to_slider(self.device.power_setpoint_mw))
        self._setpoint_indicator.setEnabled(False)  # Always disabled, just shows position
        self._setpoint_indicator.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: transparent;
                height: 8px;
            }}
            QSlider::handle:horizontal {{
                background: {self.laser_color};
                opacity: 0.5;
                border: none;
                width: 8px;
                height: 20px;
                margin: -6px 0;
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: transparent;
            }}
            QSlider::add-page:horizontal {{
                background: transparent;
            }}
        """)

        # Command slider (top) - thin white bar when enabled, hidden when disabled
        self._command_slider = QSlider(Qt.Orientation.Horizontal, self._track_widget)
        self._command_slider.setRange(0, self._slider_scale)
        self._command_slider.setValue(self._power_to_slider(self.device.power_setpoint_mw))
        self._command_slider.setEnabled(False)  # Start disabled (linked)
        self._update_command_slider_style(enabled=False)
        self._command_slider.sliderReleased.connect(self._on_command_released)

        # Free checkbox (unchecked = linked/disabled, checked = free/enabled)
        self._link_checkbox = QCheckBox()
        self._link_checkbox.setChecked(False)  # Start unchecked (linked)
        self._link_checkbox.setToolTip(
            "Check to enable slider for adjusting power.\nUncheck to lock slider to setpoint."
        )
        self._link_checkbox.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
            }}
            QCheckBox::indicator:unchecked {{
                background-color: #3c3c3c;
                border: 1px solid #505050;
                border-radius: 2px;
            }}
            QCheckBox::indicator:checked {{
                background-color: {self.laser_color};
                border: 1px solid {self.laser_color};
                border-radius: 2px;
            }}
        """)
        self._link_checkbox.toggled.connect(self._on_link_toggled)

    def _create_status_bar(self) -> None:
        """Create status bar widgets."""
        self._status_bar = QFrame()
        self._status_bar.setObjectName("laserStatusBar")
        self._status_bar.setStyleSheet("""
            QFrame#laserStatusBar {
                background-color: #252526;
                border-top: 1px solid #404040;
            }
        """)

        layout = QHBoxLayout(self._status_bar)
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

    def _build_layout(self) -> QVBoxLayout:
        """Build the widget layout."""
        layout = QVBoxLayout()
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

        # Row 2: Power track + link checkbox
        power_row = QHBoxLayout()
        power_row.setSpacing(8)
        power_row.addWidget(self._track_widget, stretch=1)
        power_row.addWidget(self._link_checkbox)
        layout.addLayout(power_row)

        # Row 3: Status bar
        layout.addWidget(self._status_bar)

        return layout

    def resizeEvent(self, a0) -> None:
        """Handle resize to position track layers."""
        super().resizeEvent(a0)
        if hasattr(self, "_track_widget"):
            w = self._track_widget.width()
            h = self._track_widget.height()
            # Progress bar centered
            self._progress_bar.setGeometry(0, (h - 8) // 2, w, 8)
            # Setpoint indicator covers track
            self._setpoint_indicator.setGeometry(0, 0, w, h)
            # Command slider on top
            self._command_slider.setGeometry(0, 0, w, h)

    def _power_to_slider(self, power_mw: float) -> int:
        """Convert power to slider value."""
        if self.max_power_mw == 0:
            return 0
        ratio = power_mw / self.max_power_mw
        return int(ratio * self._slider_scale)

    def _slider_to_power(self, slider_value: int) -> float:
        """Convert slider value to power."""
        ratio = slider_value / self._slider_scale
        return ratio * self.max_power_mw

    def _update_command_slider_style(self, enabled: bool) -> None:
        """Update command slider style based on enabled state."""
        if enabled:
            # Thin tall white bar when enabled
            self._command_slider.setStyleSheet("""
                QSlider::groove:horizontal {
                    background: transparent;
                    height: 8px;
                }
                QSlider::handle:horizontal {
                    background: #ffffff;
                    border: none;
                    width: 2px;
                    height: 22px;
                    margin: -7px 0;
                    border-radius: 1px;
                }
                QSlider::handle:horizontal:hover {
                    background: #ffffff;
                    width: 3px;
                }
                QSlider::sub-page:horizontal {
                    background: transparent;
                }
                QSlider::add-page:horizontal {
                    background: transparent;
                }
            """)
        else:
            # Hidden thumb when disabled
            self._command_slider.setStyleSheet("""
                QSlider::groove:horizontal {
                    background: transparent;
                    height: 8px;
                }
                QSlider::handle:horizontal {
                    background: transparent;
                    border: none;
                    width: 0px;
                    height: 0px;
                }
                QSlider::sub-page:horizontal {
                    background: transparent;
                }
                QSlider::add-page:horizontal {
                    background: transparent;
                }
            """)

    def _on_link_toggled(self, checked: bool) -> None:
        """Handle free checkbox toggle."""
        self._is_linked = not checked
        if checked:
            self._command_slider.setEnabled(True)
            self._update_command_slider_style(enabled=True)
        else:
            self._command_slider.setEnabled(False)
            self._update_command_slider_style(enabled=False)
            self._command_slider.blockSignals(True)
            self._command_slider.setValue(self._setpoint_indicator.value())
            self._command_slider.blockSignals(False)

    def _on_command_released(self) -> None:
        """Handle command slider release - commit to device."""
        if self._is_linked:
            return

        power = self._slider_to_power(self._command_slider.value())
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
            self._progress_bar.setValue(self._power_to_slider(value))
            self._power_chip.set_power(value)

        elif prop_name == "power_setpoint_mw":
            slider_val = self._power_to_slider(value)
            self._setpoint_indicator.setValue(slider_val)

            if self._is_linked:
                self._command_slider.blockSignals(True)
                self._command_slider.setValue(slider_val)
                self._command_slider.blockSignals(False)

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

    def closeEvent(self, a0) -> None:
        """Clean up on close."""
        # Qt automatically disconnects signals when objects are destroyed
        super().closeEvent(a0)
