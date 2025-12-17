"""Devices tab - property browser for all instrument devices."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from exaspim_control.qtgui.components.accordion import AccordionSection
from exaspim_control.qtgui.devices.device_adapter import DeviceAdapter
from exaspim_control.qtgui.devices.device_widget import DeviceWidget


class DevicesTab(QWidget):
    """Tab showing all devices organized in accordions.

    Displays all instrument devices as DeviceWidgets, organized by device type.
    Uses nested accordions for device types with multiple devices, or a single
    accordion section for device types with only one device.

    Example layout with multiple devices:
        [Lasers] ---------------------- [▾]  (group header)
            [laser_488] ---------- [▾]
                └── DeviceWidget
            [laser_561] ---------- [▾]
                └── DeviceWidget

    Example layout with single device:
        [Cameras: camera_0] ------ [▾]
            └── DeviceWidget
    """

    def __init__(
        self,
        adapters_by_type: dict[str, dict[str, DeviceAdapter]],
        parent: QWidget | None = None,
    ):
        """Initialize the Devices tab.

        :param adapters_by_type: Dict mapping device type name to dict of {device_id: adapter}
                               Example: {"Cameras": {"cam_0": adapter},
                                        "Lasers": {"488": adapter1, "561": adapter2}}
        :param parent: Parent widget
        """
        super().__init__(parent)
        self._adapters_by_type = adapters_by_type
        self._device_widgets: dict[str, DeviceWidget] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the tab UI with scroll area and accordions."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area for all content
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        # Container for accordions
        container = QWidget(scroll)
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(8)
        container_layout.setContentsMargins(8, 8, 8, 8)

        # Create accordion for each device type
        for device_type, adapters in self._adapters_by_type.items():
            if not adapters:
                continue

            if len(adapters) == 1:
                # Single device - no nesting, use "Type: device_id" as title
                device_id, adapter = next(iter(adapters.items()))
                title = f"{device_type}: {device_id}"

                widget = DeviceWidget(adapter, parent=container)
                self._device_widgets[f"{device_type}.{device_id}"] = widget

                # Single device accordion
                section = AccordionSection(title, widget, expanded=True, parent=container)
                container_layout.addWidget(section)
            else:
                # Multiple devices - nested accordions
                type_accordion = self._create_device_type_accordion(device_type, adapters, container)
                container_layout.addWidget(type_accordion)

        container_layout.addStretch()

        scroll.setWidget(container)
        layout.addWidget(scroll)

    def _create_device_type_accordion(
        self, device_type: str, adapters: dict[str, DeviceAdapter], parent: QWidget
    ) -> AccordionSection:
        """Create an accordion section for a device type with multiple devices.

        :param device_type: Name of the device type (e.g., "Lasers")
        :param adapters: Dict of {device_id: adapter}
        :param parent: Parent widget
        :return: AccordionSection containing nested device accordions
        """
        # Container for nested device accordions
        inner_container = QWidget(parent)
        inner_layout = QVBoxLayout(inner_container)
        inner_layout.setSpacing(4)
        inner_layout.setContentsMargins(0, 4, 0, 4)  # No left indentation

        # Create accordion for each device
        for device_id, adapter in adapters.items():
            widget = DeviceWidget(adapter, parent=inner_container)
            self._device_widgets[f"{device_type}.{device_id}"] = widget

            # Each device gets its own accordion
            device_section = AccordionSection(device_id, widget, expanded=False, parent=inner_container)
            inner_layout.addWidget(device_section)

        # Wrap in outer accordion section for the device type (styled as group)
        return AccordionSection(device_type, inner_container, expanded=True, is_group=True, parent=parent)

    def get_device_widget(self, device_type: str, device_id: str) -> DeviceWidget | None:
        """Get the DeviceWidget for a specific device.

        :param device_type: Device type name
        :param device_id: Device ID
        :return: DeviceWidget or None if not found
        """
        return self._device_widgets.get(f"{device_type}.{device_id}")

    @property
    def device_widgets(self) -> dict[str, DeviceWidget]:
        """Get all device widgets."""
        return self._device_widgets.copy()
