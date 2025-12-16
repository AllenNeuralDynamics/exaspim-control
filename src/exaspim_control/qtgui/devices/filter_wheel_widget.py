from typing import ClassVar

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from voxel.devices.filterwheel.base import VoxelFilterWheel

from exaspim_control.qtgui.components.wheel import WheelGraphic
from exaspim_control.qtgui.devices.device_widget import DeviceWidget


class FilterWheelWidget(DeviceWidget):
    """Widget for controlling filter wheel devices.

    Displays a visual wheel graphic and polls position to keep UI in sync
    with device state.
    """

    # Properties handled in custom wheel graphic layout
    __SKIP_PROPS__: ClassVar[set[str]] = {
        "position",
        "label",
        "is_moving",
        "slot_count",
        "labels",
    }

    def __init__(
        self, filter_wheel: VoxelFilterWheel, hues: dict[str, int | float] | None = None, parent: QWidget | None = None
    ) -> None:
        """Initialize the FilterWheelWidget.

        :param filter_wheel: Filter wheel device instance
        :param hues: Optional mapping of filter labels to hue values (0-360)
        """
        # Poll position to keep wheel graphic in sync with device
        super().__init__(filter_wheel, updating_properties=["position", "is_moving"], parent=parent)

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

        # Build and add layout
        self.main_layout.addLayout(self._build_layout())

        # Sync graphic to current device position BEFORE connecting signal
        # to avoid triggering device.move() during initialization
        self._sync_graphic_to_device()

        # Now connect signal - user clicks will trigger device movement
        self._graphic.selected_changed.connect(self._on_user_select)

    def _create_wheel_widgets(self) -> tuple[WheelGraphic, QLabel]:
        """Create wheel graphic and status label."""
        graphic = WheelGraphic(
            num_slots=self.device.slot_count,
            assignments=self.device.labels,
            hue_mapping=self._hues,
        )
        # Note: selected_changed signal is connected in __init__ after _sync_graphic_to_device()

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

    def update_status(self, prop_name: str, value) -> None:
        """Update wheel graphic when device position changes."""
        if prop_name == "position":
            # Only update if position actually changed (avoid visual glitches)
            if self._graphic.selected_slot != value:
                self._graphic.selected_slot = value
