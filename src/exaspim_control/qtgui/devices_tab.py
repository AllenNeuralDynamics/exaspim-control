"""Devices tab - property browser for all instrument devices."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from exaspim_control.qtgui.components.accordion import AccordionSection
from exaspim_control.qtgui.devices.device_widget import SimpleWidget


class DevicesTab(QWidget):
    """Tab showing all devices organized in accordions.

    Displays all instrument devices as SimpleWidgets, organized by device type.
    Uses nested accordions for device types with multiple devices, or a single
    accordion section for device types with only one device.

    Each device accordion has a refresh button to manually refresh property values.

    Example layout with multiple devices:
        [Lasers] ---------------------- [▾]  (group header)
            [laser_488] ---------- [⟳] [▾]
                └── SimpleWidget
            [laser_561] ---------- [⟳] [▾]
                └── SimpleWidget

    Example layout with single device:
        [Cameras: camera_0] ------ [⟳] [▾]
            └── SimpleWidget
    """

    def __init__(
        self,
        devices_by_type: dict[str, dict[str, object]],
        parent: QWidget | None = None,
    ):
        """
        Initialize the Devices tab.

        :param devices_by_type: Dict mapping device type name to dict of {device_id: device}
                               Example: {"Cameras": {"cam_0": camera_obj},
                                        "Lasers": {"488": laser1, "561": laser2}}
        :param parent: Parent widget
        """
        super().__init__(parent)
        self._devices_by_type = devices_by_type
        self._device_widgets: dict[str, SimpleWidget] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the tab UI with scroll area and accordions."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area for all content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        # Container for accordions
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(8)
        container_layout.setContentsMargins(8, 8, 8, 8)

        # Create accordion for each device type
        for device_type, devices in self._devices_by_type.items():
            if not devices:
                continue

            if len(devices) == 1:
                # Single device - no nesting, use "Type: device_id" as title
                device_id, device = next(iter(devices.items()))
                title = f"{device_type}: {device_id}"

                widget = SimpleWidget(device)
                self._device_widgets[f"{device_type}.{device_id}"] = widget

                # Single device gets refresh button
                section = AccordionSection(
                    title, widget, expanded=True, on_refresh=widget.refresh
                )
                container_layout.addWidget(section)
            else:
                # Multiple devices - nested accordions
                type_accordion = self._create_device_type_accordion(device_type, devices)
                container_layout.addWidget(type_accordion)

        container_layout.addStretch()

        scroll.setWidget(container)
        layout.addWidget(scroll)

    def _create_device_type_accordion(self, device_type: str, devices: dict[str, object]) -> AccordionSection:
        """Create an accordion section for a device type with multiple devices.

        :param device_type: Name of the device type (e.g., "Lasers")
        :param devices: Dict of {device_id: device_object}
        :return: AccordionSection containing nested device accordions
        """
        # Container for nested device accordions
        inner_container = QWidget()
        inner_layout = QVBoxLayout(inner_container)
        inner_layout.setSpacing(4)
        inner_layout.setContentsMargins(0, 4, 0, 4)  # No left indentation

        # Create accordion for each device
        for device_id, device in devices.items():
            widget = SimpleWidget(device)
            self._device_widgets[f"{device_type}.{device_id}"] = widget

            # Each device gets a refresh button
            device_section = AccordionSection(
                device_id, widget, expanded=False, on_refresh=widget.refresh
            )
            inner_layout.addWidget(device_section)

        # Wrap in outer accordion section for the device type (styled as group)
        return AccordionSection(device_type, inner_container, expanded=True, is_group=True)

    def get_device_widget(self, device_type: str, device_id: str) -> SimpleWidget | None:
        """Get the SimpleWidget for a specific device.

        :param device_type: Device type name
        :param device_id: Device ID
        :return: SimpleWidget or None if not found
        """
        return self._device_widgets.get(f"{device_type}.{device_id}")

    def refresh_all(self) -> None:
        """Refresh all device widgets."""
        for widget in self._device_widgets.values():
            widget.refresh()

    @property
    def device_widgets(self) -> dict[str, SimpleWidget]:
        """Get all device widgets."""
        return self._device_widgets.copy()
