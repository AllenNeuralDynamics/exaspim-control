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

from napari.qt.threading import thread_worker
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from view.widgets.property_widget import PropertyWidget, extract_device_properties

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

    propertyChanged = pyqtSignal(str, object)  # (property_name, new_value)

    def __init__(self, device, updating_properties: list[str] | None = None):
        """
        Initialize device widget.

        :param device: Device instance to control
        :param updating_properties: List of properties that need real-time updates
        """
        super().__init__()
        self.device = device
        self.updating_properties = updating_properties or []
        self._is_closing = False
        self._workers = []

        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Extract device properties
        self.device_properties = extract_device_properties(device, updating_properties)

        # Create PropertyWidgets
        self.property_widgets = {}
        for dev_prop in self.device_properties:
            widget = PropertyWidget(dev_prop)
            widget.valueChanged.connect(self._on_property_changed)
            self.property_widgets[dev_prop.name] = widget

        # Setup layout (subclasses can override)
        self._setup_default_layout()

        # Start property workers
        self._create_property_workers()

    def _setup_default_layout(self):
        """
        Create default vertical layout with all properties.

        Subclasses can override this to prevent auto-layout and
        implement custom layouts instead.
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        for widget in self.property_widgets.values():
            layout.addWidget(widget)

    def _layout_properties(self, skip: set[str] | None = None) -> QWidget:
        """
        Create widget with remaining properties (for subclass custom layouts).

        This allows subclasses to manually lay out some properties, then
        call this method to automatically lay out the rest.

        Example:
            # Manually layout power slider
            layout = QVBoxLayout(self)
            layout.addWidget(self.property_widgets["power_setpoint_mw"])
            layout.addWidget(custom_slider)

            # Auto-layout everything else
            remaining = self._layout_properties(skip={"power_setpoint_mw"})
            layout.addWidget(remaining)

        :param skip: Set of property names to skip (already laid out manually)
        :return: QWidget container with vertical layout of remaining properties
        """
        skip = skip or set()
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        for name, widget in self.property_widgets.items():
            if name not in skip:
                layout.addWidget(widget)

        return container

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

        Updates corresponding PropertyWidget with new value.

        :param data: Tuple of (value, property_name)
        """
        value, name = data

        if name in self.property_widgets:
            # Update widget (blockSignals handled inside set_value)
            self.property_widgets[name].set_value(value)
        else:
            self.log.warning(f"Worker update for unknown property: {name}")

    def closeEvent(self, a0):
        """
        Clean up workers on widget close.

        Sets closing flag, waits for workers to finish, then terminates
        any that don't finish within timeout.

        :param a0: Close event
        """
        self.log.debug("DeviceWidget closing, stopping workers...")
        self._is_closing = True

        # Wait for workers to finish (with timeout)
        for i, worker in enumerate(self._workers):
            self.log.debug(f"Stopping worker {i + 1}/{len(self._workers)}")

            worker.quit()
            if not worker.wait(1000):  # 1 second timeout
                self.log.warning(f"Worker {i + 1} did not finish, terminating")
                worker.terminate()
            else:
                self.log.debug(f"Worker {i + 1} stopped cleanly")

        self.log.debug("All workers stopped")
        super().closeEvent(a0)
