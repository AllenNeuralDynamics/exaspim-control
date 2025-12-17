"""Generic device widget with auto-generated form layout."""

from typing import Any

from PyQt6.QtWidgets import QFormLayout, QWidget

from exaspim_control.qtgui.components.input import VLabel
from exaspim_control.qtgui.devices.device_adapter import DeviceAdapter
from exaspim_control.qtgui.devices.property_widget import PropertyWidget


class DeviceWidget(QWidget):
    """Auto-generated form UI for any device via DeviceAdapter.

    Creates a QFormLayout with labeled PropertyWidgets for each device property.
    Subscribes to the adapter for property updates.
    """

    def __init__(self, adapter: DeviceAdapter, parent: QWidget | None = None):
        """Initialize device widget.

        :param adapter: DeviceAdapter providing device interface
        :param parent: Parent widget
        """
        super().__init__(parent)
        self._adapter = adapter
        self._property_widgets: dict[str, PropertyWidget] = {}

        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        for name, info in adapter.properties.items():
            prop_widget = PropertyWidget(adapter.device, info)
            prop_widget.valueChanged.connect(self._on_value_changed)
            self._property_widgets[name] = prop_widget

            label_text = info.label
            if info.units:
                label_text = f"{label_text} [{info.units}]"
            layout.addRow(VLabel(label_text), prop_widget.value_widget)

        adapter.propertyUpdated.connect(self._on_property_update)

    @property
    def adapter(self) -> DeviceAdapter:
        """Get the device adapter."""
        return self._adapter

    def _on_value_changed(self, name: str, value: Any) -> None:
        """Handle value change from a PropertyWidget."""
        self._adapter.set_property(name, value)

    def _on_property_update(self, name: str, value: Any) -> None:
        """Handle property update from adapter polling."""
        if name in self._property_widgets:
            self._property_widgets[name].set_value(value)

    def closeEvent(self, a0) -> None:
        """Clean up on close."""
        # Qt automatically disconnects signals when objects are destroyed
        super().closeEvent(a0)
