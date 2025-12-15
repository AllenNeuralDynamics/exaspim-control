"""Self-contained device widget with automatic property management.

This module provides a QWidget-based device control widget that:
1. Automatically scans device properties
2. Creates appropriate input widgets
3. Manages property update workers
4. Handles cleanup on close
5. Supports custom layouts via subclassing
"""

import logging
import time
from typing import ClassVar, Literal

from napari.qt.threading import thread_worker
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QVBoxLayout, QWidget

from exaspim_control.qtgui.components.input import VLabel
from exaspim_control.qtgui.devices.property_widget import (
    PropertyWidget,
    extract_device_properties,
    label_maker,
)

logger = logging.getLogger(__name__)


class DeviceWidget(QWidget):
    """Self-contained device control widget.

    This widget automatically:
    - Scans device properties and creates input widgets
    - Manages property update worker threads
    - Handles bidirectional data flow (widget ↔ device)
    - Provides cleanup on close

    Subclasses can customize layout by:
    1. Override _setup_default_layout() to prevent auto-layout
    2. Manually arrange property_widgets as needed
    3. Call _layout_properties(skip={...}) for remaining properties

    Example subclass:
        class LaserWidget(DeviceWidget):
            def __init__(self, laser, color="blue"):
                super().__init__(laser, updating_properties=["power_mw", "temperature_c"])
                self._add_custom_slider()

            def _setup_default_layout(self):
                pass  # Don't auto-layout, we'll do it custom

            def _add_custom_slider(self):
                # Custom layout with slider
                layout = QVBoxLayout(self)
                layout.addWidget(self.property_widgets["power_setpoint_mw"])
                layout.addWidget(custom_slider)

                # Layout remaining properties
                remaining = self._layout_properties(skip={"power_setpoint_mw"})
                layout.addWidget(remaining)
    """

    __SKIP_PROPS__: ClassVar[set[str]] = set()

    propertyChanged = pyqtSignal(str, object)  # (property_name, new_value)

    def __init__(self, device, updating_properties: list[str] | None = None, parent: QWidget | None = None):
        """
        Initialize device widget.

        :param device: Device instance to control
        :param updating_properties: List of properties that need real-time updates
        """
        super().__init__(parent=parent)
        self.device = device
        self.updating_properties = updating_properties or []
        self._is_closing = False
        self._workers = []

        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Extract device properties
        self.props = extract_device_properties(device, updating_properties)

        # Create PropertyWidgets
        self.property_widgets = {}
        for dev_prop_name, dev_prop in self.props.items():
            widget = PropertyWidget(dev_prop)
            widget.valueChanged.connect(self._on_property_changed)
            self.property_widgets[dev_prop_name] = widget

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # Start property workers
        self._create_property_workers()

        self.propertyChanged.connect(lambda n, v: self.log.info(f"Property '{n}' changed to {v}"))

    def _default_layout(self) -> QVBoxLayout:
        """
        Create default vertical layout with all properties.

        Subclasses can override this to prevent auto-layout and
        implement custom layouts instead.
        """
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        for dev_prop_name, widget in self.property_widgets.items():
            if dev_prop_name not in self.__SKIP_PROPS__:
                layout.addWidget(widget)

        return layout

    def _on_property_changed(self, name: str, value):
        """
        Handle property value change from widget.

        Writes value back to device and emits signal.

        :param name: Property name
        :param value: New value
        """
        try:
            # Handle nested properties (dot notation)
            if "." in name:
                self._set_nested_property(name, value)
            else:
                setattr(self.device, name, value)

            self.propertyChanged.emit(name, value)
            self.log.debug(f"Property '{name}' set to {value}")

        except Exception:
            self.log.exception(f"Failed to set {name} = {value}")

    def _set_nested_property(self, name: str, value):
        """
        Set nested property using dot notation.

        Example: "trigger.mode" → device.trigger["mode"] = value

        :param name: Dot-notation property path
        :param value: Value to set
        """
        parts = name.split(".")
        obj = self.device

        # Navigate to parent
        for part in parts[:-1]:
            # Check if it's a list index
            obj = obj[int(part)] if part.isdigit() else getattr(obj, part)

        # Set final value
        final_key = parts[-1]
        if final_key.isdigit():
            obj[int(final_key)] = value
        elif isinstance(obj, dict):
            obj[final_key] = value
        else:
            setattr(obj, final_key, value)

    def _create_property_workers(self):
        """
        Create worker threads for properties that need real-time updates.

        Only creates workers for properties marked with updating=True.
        One worker polls all updating properties together.
        """
        if not self.updating_properties:
            self.log.debug("No updating properties, skipping worker creation")
            return

        self.log.debug(f"Creating property worker for: {self.updating_properties}")

        worker = self._property_worker(self.updating_properties)
        worker.yielded.connect(self._on_worker_update)
        worker.start()
        self._workers.append(worker)

    @thread_worker
    def _property_worker(self, property_names: list[str]):
        """
        Worker thread to poll device properties.

        Runs continuously until widget closes, polling properties every 500ms.

        :param property_names: List of property names to poll
        :yield: Tuple of (value, property_name)
        """
        self.log.debug(f"Property worker started for {property_names}")

        while not self._is_closing:
            # Sleep in small increments to allow responsive shutdown
            for _ in range(5):  # 5 * 100ms = 500ms total
                if self._is_closing:
                    self.log.debug("Property worker stopping (closing flag set)")
                    return
                time.sleep(0.1)

            # Poll all properties
            for prop_name in property_names:
                if self._is_closing:
                    return

                try:
                    # Handle nested properties
                    if "." in prop_name:
                        value = self._get_nested_property(prop_name)
                    else:
                        value = getattr(self.device, prop_name)

                    yield (value, prop_name)

                except (AttributeError, KeyError, TypeError, RuntimeError) as e:
                    self.log.warning(f"Failed to read {prop_name}: {e}")

        self.log.debug("Property worker finished")

    def _get_nested_property(self, name: str):
        """
        Get nested property using dot notation.

        Example: "trigger.mode" → device.trigger["mode"]

        :param name: Dot-notation property path
        :return: Property value
        """
        parts = name.split(".")
        obj = self.device

        for part in parts:
            if part.isdigit():
                obj = obj[int(part)]
            elif isinstance(obj, dict):
                obj = obj[part]
            else:
                obj = getattr(obj, part)

        return obj

    def _on_worker_update(self, data):
        """
        Handle property update from worker thread.

        Updates corresponding PropertyWidget with new value and calls
        update_status() hook for subclass custom UI updates.

        :param data: Tuple of (value, property_name)
        """
        # Guard against updates after widget is closing/deleted
        if self._is_closing:
            return

        try:
            value, name = data

            if name in self.property_widgets:
                # Update widget (blockSignals handled inside set_value)
                self.property_widgets[name].set_value(value)

            # Call subclass hook for custom UI updates (status bars, chips, etc.)
            self.update_status(name, value)
        except RuntimeError:
            # Widget was deleted during update - ignore silently
            pass

    def update_status(self, prop_name: str, value) -> None:
        """
        Hook for subclasses to update custom UI elements.

        Called whenever a worker-polled property updates. Subclasses override
        this to update status labels, chips, formatted displays, etc.

        :param prop_name: Name of the property that changed
        :param value: New value of the property
        """

    def refresh(self) -> None:
        """
        Refresh all property values from the device.

        Reads current values for all properties and updates the widgets.
        Useful for manual refresh when not using continuous polling.
        """
        for prop_name, prop_widget in self.property_widgets.items():
            try:
                if "." in prop_name:
                    value = self._get_nested_property(prop_name)
                else:
                    value = getattr(self.device, prop_name)

                prop_widget.set_value(value)
                self.update_status(prop_name, value)

            except (AttributeError, KeyError, TypeError, RuntimeError) as e:
                self.log.warning(f"Failed to refresh {prop_name}: {e}")

    def stop_workers(self) -> None:
        """
        Stop all worker threads and wait for them to finish.

        Call this before closing the application to ensure clean shutdown.
        """
        if self._is_closing:
            return  # Already stopping

        self.log.debug("Stopping workers...")
        self._is_closing = True

        for i, worker in enumerate(self._workers):
            try:
                worker.quit()

                # Wait for worker to finish with timeout
                max_wait = 0.5  # seconds
                elapsed = 0.0
                while worker.is_running and elapsed < max_wait:
                    time.sleep(0.05)
                    elapsed += 0.05

                if worker.is_running:
                    self.log.warning(f"Worker {i + 1} did not finish within timeout")

            except (RuntimeError, AttributeError):
                pass  # Worker already stopped or deleted

        self.log.debug("All workers stopped")

    def closeEvent(self, a0):
        """Clean up workers on widget close."""
        self.stop_workers()
        super().closeEvent(a0)


class SimpleWidget(DeviceWidget):
    """Simple device widget with form layout.

    Displays all device properties in a clean form layout:
    - Labels on the left
    - Input widgets on the right
    - Uses VLabel for consistent styling
    """

    def __init__(
        self,
        device,
        updating_properties: list[str] | None = None,
        layout_style: Literal["form", "vertical"] = "form",
    ):
        """
        Initialize simple widget.

        :param device: Device instance to control
        :param updating_properties: List of properties that need real-time updates
        :param layout_style: "form" for label-value pairs, "vertical" for stacked
        """
        super().__init__(device, updating_properties)

        if layout_style == "form":
            self.main_layout.addLayout(self._form_layout())
        else:
            self.main_layout.addLayout(self._default_layout())

    def _form_layout(self) -> QFormLayout:
        """
        Create form layout with labels on left, values on right.

        Uses VLabel for styled labels and extracts just the value widget
        from each PropertyWidget.
        """
        layout = QFormLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        for dev_prop_name, prop_widget in self.property_widgets.items():
            if dev_prop_name not in self.__SKIP_PROPS__:
                # Get the leaf name for display (e.g., "mode" from "trigger.mode")
                leaf_name = dev_prop_name.split(".")[-1]
                label_text = label_maker(leaf_name)

                # Add unit if present
                if prop_widget.device_property.unit:
                    label_text = f"{label_text} [{prop_widget.device_property.unit}]"

                # Create styled label and add row
                label = VLabel(label_text)
                layout.addRow(label, prop_widget.value_widget)

        return layout
