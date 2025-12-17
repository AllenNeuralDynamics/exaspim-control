"""Filter wheel widget with visual wheel graphic."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from exaspim_control.qtgui.components.wheel import WheelGraphic
from exaspim_control.qtgui.devices.device_adapter import DeviceAdapter

if TYPE_CHECKING:
    from voxel.interfaces.axes import DiscreteAxis


class FilterWheelWidget(QWidget):
    """Widget for controlling filter wheel devices.

    Uses composition with DeviceAdapter rather than inheritance.

    Displays a visual wheel graphic and polls position to keep UI in sync
    with device state.
    """

    def __init__(
        self,
        adapter: DeviceAdapter[DiscreteAxis],
        hues: dict[str, int | float] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the FilterWheelWidget.

        :param adapter: DeviceAdapter for the filter wheel device
        :param hues: Optional mapping of filter labels to hue values (0-360)
        """
        super().__init__(parent)
        self._adapter = adapter
        self.log = logging.getLogger(f"{__name__}.{adapter.device.uid}")

        # Hue mapping for filter colors
        self._hues: dict[str, float | int] = {
            "500LP": 230,  # blue (240 degrees)
            "535/70m": 200,
            "575LP": 170,
            "620/60BP": 120,  # green (120 degrees)
            "655LP": 0,  # red (0 degrees)
            "Multiband": 100,
        }
        if hues is not None:
            self._hues.update(hues)

        # Create UI widgets (factory methods return them)
        self._graphic, self._status_label = self._create_wheel_widgets()
        self._left_btn, self._right_btn, self._reset_btn = self._create_control_widgets()

        # Build layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._build_layout())

        # Sync graphic to current device position BEFORE connecting signal
        # to avoid triggering device.move() during initialization
        self._sync_graphic_to_device()

        # Now connect signal - user clicks will trigger device movement
        self._graphic.selected_changed.connect(self._on_user_select)

        # Connect to adapter property updates (thread-safe via Qt signal)
        adapter.propertyUpdated.connect(self._on_property_update)

    @property
    def device(self) -> DiscreteAxis:
        """Get the filter wheel device."""
        return self._adapter.device

    def _create_wheel_widgets(self) -> tuple[WheelGraphic, QLabel]:
        """Create wheel graphic and status label."""
        device = self.device
        graphic = WheelGraphic(
            num_slots=device.slot_count,
            assignments=device.labels,
            hue_mapping=self._hues,
        )

        status_label = QLabel("Hover over circles to see labels, click to select")

        return graphic, status_label

    def _create_control_widgets(self) -> tuple[QPushButton, QPushButton, QPushButton]:
        """Create control buttons (left, right, reset)."""
        left_btn = QPushButton("◀")
        left_btn.setToolTip("Spin left")
        left_btn.clicked.connect(self._graphic.step_to_next)

        right_btn = QPushButton("▶")
        right_btn.setToolTip("Spin right")
        right_btn.clicked.connect(self._graphic.step_to_previous)

        reset_btn = QPushButton("⟳")
        reset_btn.setToolTip("Reset wheel rotation")
        reset_btn.clicked.connect(self._graphic.reset_rotation)

        return left_btn, right_btn, reset_btn

    def _build_layout(self) -> QVBoxLayout:
        """Build the complete filter wheel layout using pre-created widgets."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Wheel graphic
        layout.addWidget(self._graphic)

        # Control buttons
        controls_layout = QVBoxLayout()
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Row 1 - Step controls
        row_1 = QHBoxLayout()
        row_1.addWidget(self._left_btn)
        row_1.addStretch()
        row_1.addWidget(self._right_btn)
        controls_layout.addLayout(row_1)

        # Row 2 - Status and Reset
        row_2 = QHBoxLayout()
        row_2.addWidget(self._status_label)
        row_2.addStretch()
        row_2.addWidget(self._reset_btn)
        controls_layout.addLayout(row_2)

        layout.addLayout(controls_layout)

        return layout

    def _sync_graphic_to_device(self) -> None:
        """Sync the wheel graphic to the current device position."""
        try:
            current_pos = self.device.position
            self._graphic.selected_slot = current_pos
        except Exception:
            self.log.exception("Failed to sync graphic to device position")

    def _on_user_select(self) -> None:
        """Handle user selecting a slot on the wheel graphic."""
        if (slot := self._graphic.selected_slot) is not None:
            self.device.move(slot)

    def _on_property_update(self, prop_name: str, value: Any) -> None:
        """Handle property updates from adapter polling."""
        if prop_name == "position":
            # Only update if position actually changed (avoid visual glitches)
            if self._graphic.selected_slot != value:
                self._graphic.selected_slot = value

    def closeEvent(self, a0) -> None:
        """Clean up on close."""
        # Qt automatically disconnects signals when objects are destroyed
        super().closeEvent(a0)
