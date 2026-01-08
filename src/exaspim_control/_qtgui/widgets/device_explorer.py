"""DevicesExplorer - Accordion-based explorer for all instrument devices."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from exaspim_control._qtgui.primitives import Colors, IconButton, Separator
from exaspim_control._qtgui.primitives.containers import AccordionCard
from exaspim_control._qtgui.widgets.devices.base import DeviceWidget

if TYPE_CHECKING:
    from collections.abc import Callable

    from exaspim_control._qtgui.model import DeviceAdapter, InstrumentModel


def _create_refresh_button(on_click: Callable[[], None]) -> IconButton:
    """Create a small refresh button for accordion headers."""
    btn = IconButton(text="↻", size=22)
    btn.setToolTip("Refresh")
    btn.clicked.connect(on_click)
    return btn


class SectionHeader(QWidget):
    """Simple section header/divider for grouping devices by type."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 6)
        layout.setSpacing(8)

        label = QLabel(title)
        label.setStyleSheet(f"""
            QLabel {{
                color: {Colors.TEXT_MUTED};
                font-size: 11px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(label)

        line = Separator(orientation="horizontal", color=Colors.BORDER_FOCUS)
        layout.addWidget(line, stretch=1)


class DevicesExplorer(QWidget):
    """Accordion-based explorer showing all instrument devices.

    Displays all instrument devices as DeviceWidgets, organized by device type.
    Uses section headers for device types and flat accordions for each device.

    Example layout:
        ─── Lasers ─────────────────────
        [▾] laser_488                [↻]
            └── DeviceWidget
        [▸] laser_561                [↻]

        ─── Axes ───────────────────────
        [▾] x_axis                   [↻]
            └── DeviceWidget
    """

    def __init__(self, model: InstrumentModel, parent: QWidget | None = None):
        super().__init__(parent)
        self._model = model
        self._device_widgets: dict[str, DeviceWidget] = {}
        self._accordions: dict[str, AccordionCard] = {}
        self._setup_ui()

    def _build_adapters_by_type(self) -> dict[str, dict[str, DeviceAdapter]]:
        """Build adapters grouped by device type from model."""
        adapters_by_type: dict[str, dict[str, DeviceAdapter]] = {}

        if self._model.camera:
            adapters_by_type["Cameras"] = {self._model.camera.device.uid: self._model.camera}

        if self._model.lasers:
            adapters_by_type["Lasers"] = self._model.lasers

        if self._model.filter_wheels:
            adapters_by_type["Filter Wheels"] = self._model.filter_wheels

        if self._model.axes:
            adapters_by_type["Axes"] = self._model.axes

        return adapters_by_type

    def _setup_ui(self) -> None:
        """Setup the UI with scroll area, section headers, and flat accordions."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget(scroll)
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(2)
        container_layout.setContentsMargins(8, 8, 8, 8)

        adapters_by_type = self._build_adapters_by_type()

        for device_type, adapters in adapters_by_type.items():
            if not adapters:
                continue

            # Section header for device type
            container_layout.addWidget(SectionHeader(device_type, parent=container))

            # Flat accordion for each device
            for device_id, adapter in adapters.items():
                widget = DeviceWidget(adapter, parent=container)
                self._device_widgets[f"{device_type}.{device_id}"] = widget

                refresh_btn = _create_refresh_button(adapter.refresh)
                section = AccordionCard(
                    device_id,
                    widget,
                    expanded=False,
                    action_widgets=[refresh_btn],
                    parent=container,
                )
                self._accordions[f"{device_type}.{device_id}"] = section
                container_layout.addWidget(section)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

    def get_device_widget(self, device_type: str, device_id: str) -> DeviceWidget | None:
        """Get the DeviceWidget for a specific device."""
        return self._device_widgets.get(f"{device_type}.{device_id}")

    @property
    def device_widgets(self) -> dict[str, DeviceWidget]:
        """Get all device widgets."""
        return self._device_widgets.copy()
