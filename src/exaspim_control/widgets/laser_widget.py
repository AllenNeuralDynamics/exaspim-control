import importlib

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout
from view.widgets.base_device_widget import create_widget
from view.widgets.device_widget import DeviceWidget
from view.widgets.miscellaneous_widgets.q_scrollable_float_slider import QScrollableFloatSlider
from voxel.devices.laser.base import BaseLaser


class LaserWidget(DeviceWidget):
    """Widget for handling laser properties and controls with card-style layout."""

    def __init__(self, laser: BaseLaser, color: str = "blue", advanced_user: bool = True):
        """
        Initialize the LaserWidget object.

        :param laser: Laser object
        :type laser: BaseLaser
        :param color: Color of the slider, defaults to "blue"
        :type color: str, optional
        :param advanced_user: Whether the user is advanced, defaults to True
        :type advanced_user: bool, optional
        """
        # Determine updating properties based on advanced_user
        updating_props = ["power_mw", "temperature_c"] if advanced_user else []

        # Store references before calling super().__init__
        self.slider_color = color
        self.advanced_user = advanced_user

        # Initialize DeviceWidget with device instance
        super().__init__(laser, updating_properties=updating_props)

        # Get max power from property descriptor
        self.max_power_mw = getattr(type(laser).power_setpoint_mw, "maximum", 110)

        # Add custom power slider layout
        self._add_custom_power_slider()

    def _setup_default_layout(self):
        """Override to prevent auto-layout - we'll do custom layout."""
        pass

    def _add_custom_power_slider(self) -> None:
        """
        Add a power slider to the widget with custom layout.
        """
        # Get the actual input widgets from PropertyWidgets
        setpoint_widget = self.property_widgets["power_setpoint_mw"].value_widget.widget
        power_widget = self.property_widgets["power_mw"].value_widget.widget
        temperature_widget = self.property_widgets["temperature_c"].value_widget.widget

        # Configure validators if present
        if hasattr(setpoint_widget, "validator") and setpoint_widget.validator():
            if hasattr(setpoint_widget.validator(), "setRange"):
                setpoint_widget.validator().setRange(0.0, self.max_power_mw, decimals=2)
        if hasattr(power_widget, "validator") and power_widget.validator():
            if hasattr(power_widget.validator(), "setRange"):
                power_widget.validator().setRange(0.0, self.max_power_mw, decimals=2)

        # Configure power widget (read-only)
        power_widget.setEnabled(False)
        power_widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        power_widget.setMinimumWidth(60)
        power_widget.setMaximumWidth(60)

        # Configure setpoint widget
        if hasattr(setpoint_widget, "validator") and setpoint_widget.validator():
            setpoint_widget.validator().fixup = self.power_slider_fixup
        setpoint_widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        setpoint_widget.setMinimumWidth(60)
        setpoint_widget.setMaximumWidth(60)

        # Create slider
        slider = QScrollableFloatSlider(orientation=Qt.Orientation.Horizontal)
        slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Calculate slider colors
        hsv_active_color = list(QColor(self.slider_color).getHsv())
        hsv_active_color = [c if c is not None else 0 for c in hsv_active_color]
        active_color = QColor.fromHsv(*map(int, hsv_active_color)).name()

        hsv_inactive_color = hsv_active_color.copy()
        hsv_inactive_color[2] = int(hsv_inactive_color[2]) // 4
        inactive_color = QColor.fromHsv(*map(int, hsv_inactive_color)).name()

        hsv_border_color = hsv_active_color.copy()
        hsv_border_color[2] = 100
        hsv_border_color[1] = 100
        border_color = QColor.fromHsv(*map(int, hsv_border_color)).name()

        hsv_handle_color = hsv_active_color.copy()
        hsv_handle_color[2] = 128
        hsv_handle_color[1] = 64
        handle_color = QColor.fromHsv(*map(int, hsv_handle_color)).name()

        slider.setStyleSheet(
            f"QSlider::groove:horizontal {{background: {inactive_color}; border: 2px solid {border_color};height: 10px;border-radius: 6px;}}"
            f"QSlider::handle:horizontal {{background-color: {handle_color}; width: 16px; height: 14px; "
            f"line-height: 14px; margin-top: -4px; margin-bottom: -4px; border-radius: 0px; }}"
            f"QSlider::sub-page:horizontal {{background: {active_color};border: 2px solid {border_color};"
            f"height: 10px;border-radius: 6px;}}"
        )

        slider.setMinimum(0)
        slider.setMaximum(int(self.max_power_mw))
        slider.setValue(int(self.device.power_setpoint_mw))

        # Connect slider to setpoint widget
        if hasattr(setpoint_widget, "setText"):
            slider.sliderMoved.connect(lambda: setpoint_widget.setText(str(slider.value())))
        if hasattr(setpoint_widget, "editingFinished"):
            setpoint_widget.editingFinished.connect(lambda: slider.setValue(round(float(setpoint_widget.text()))))

        # Connect slider to device
        slider.sliderReleased.connect(lambda: setattr(self.device, "power_setpoint_mw", float(slider.value())))
        slider.sliderReleased.connect(lambda: self.propertyChanged.emit("power_setpoint_mw", float(slider.value())))

        # Configure temperature widget
        temperature_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Maximum)
        temperature_widget.setMinimumWidth(50)
        temperature_widget.setMaximumWidth(50)

        # Store slider reference
        self.power_slider = slider

        # Create custom layout
        power_row = create_widget("H", QLabel("Setpoint:"), setpoint_widget, QLabel("Power:"), power_widget)
        temp_row = create_widget("H", QLabel("Temperature:"), temperature_widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(power_row)
        layout.addWidget(slider)
        layout.addWidget(temp_row)

        # Add remaining properties (skip the ones we manually laid out)
        if self.advanced_user:
            remaining = self._layout_properties(skip={"power_setpoint_mw", "power_mw", "temperature_c"})
            layout.addWidget(remaining)

    def power_slider_fixup(self, value: str) -> None:
        """
        Fix the power slider value.

        :param value: Value to fix
        :type value: str
        """
        setpoint_widget = self.property_widgets["power_setpoint_mw"].value_widget.widget
        setpoint_widget.setText(str(self.max_power_mw))
        if hasattr(setpoint_widget, "editingFinished"):
            setpoint_widget.editingFinished.emit()
