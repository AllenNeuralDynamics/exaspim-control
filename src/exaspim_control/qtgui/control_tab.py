"""Control tab for instrument device controls."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from exaspim_control.qtgui.components import Card
from exaspim_control.qtgui.devices.axis_widget import AxisWidget
from exaspim_control.qtgui.devices.device_adapter import DeviceAdapter

if TYPE_CHECKING:
    from voxel.interfaces.axes import Axis

    from exaspim_control.qtgui.devices.camera_widget import CameraWidget
    from exaspim_control.qtgui.devices.laser_widget import LaserWidget


class ControlTab(QScrollArea):
    """Control tab with camera, lasers, stage, and focus controls.

    Layout:
    - Camera card
    - Laser cards
    - Stage card (X, Y, Z axis sliders)
    - Focus card (focus axis sliders)
    """

    stageLimitsChanged = pyqtSignal()  # Emitted when any stage axis limits change
    stageMovingChanged = pyqtSignal(bool)  # Emitted when any stage axis starts/stops moving

    def __init__(
        self,
        camera_widget: CameraWidget | None = None,
        camera_uid: str = "",
        laser_widgets: dict[str, LaserWidget] | None = None,
        stage_adapters: dict[str, DeviceAdapter[Axis]] | None = None,
        focusing_adapters: dict[str, DeviceAdapter[Axis]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        # Store stage axis widgets for external access
        self.stage_axis_widgets: dict[str, AxisWidget] = {}
        self._axis_moving_state: dict[str, bool] = {}

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Camera card
        if camera_widget:
            camera_card = Card(f"Camera: {camera_uid}", parent=container)
            camera_card.add_widget(camera_widget)
            layout.addWidget(camera_card)

        # Laser cards
        if laser_widgets:
            for uid, laser_widget in laser_widgets.items():
                laser_card = Card(f"Laser: {uid}", parent=container)
                laser_card.add_widget(laser_widget)
                layout.addWidget(laser_card)

        # Stage card
        if stage_adapters:
            stage_card = Card("Stage", parent=container)
            stage_container = QWidget(stage_card)
            stage_layout = QVBoxLayout(stage_container)
            stage_layout.setContentsMargins(0, 0, 0, 0)
            stage_layout.setSpacing(4)

            for name, adapter in stage_adapters.items():
                axis = adapter.device
                axis_widget = AxisWidget(
                    name.upper(),
                    adapter=adapter,
                    min_pos=axis.lower_limit_mm,
                    max_pos=axis.upper_limit_mm,
                    parent=stage_container,
                )
                axis_widget.limitsChanged.connect(self.stageLimitsChanged.emit)
                axis_widget.movingChanged.connect(lambda moving, n=name: self._on_axis_moving_changed(n, moving))
                self.stage_axis_widgets[name] = axis_widget
                self._axis_moving_state[name] = False
                stage_layout.addWidget(axis_widget)

            stage_card.add_widget(stage_container)
            layout.addWidget(stage_card)

        # Focus card
        if focusing_adapters:
            focus_card = Card("Focus", parent=container)
            focus_container = QWidget(focus_card)
            focus_layout = QVBoxLayout(focus_container)
            focus_layout.setContentsMargins(0, 0, 0, 0)
            focus_layout.setSpacing(4)

            for name, adapter in focusing_adapters.items():
                axis = adapter.device
                axis_widget = AxisWidget(
                    name,
                    adapter=adapter,
                    min_pos=axis.lower_limit_mm,
                    max_pos=axis.upper_limit_mm,
                    parent=focus_container,
                )
                focus_layout.addWidget(axis_widget)

            focus_card.add_widget(focus_container)
            layout.addWidget(focus_card)

        layout.addStretch()
        self.setWidget(container)

    def _on_axis_moving_changed(self, axis_name: str, is_moving: bool) -> None:
        """Handle axis movement change and emit aggregated signal."""
        self._axis_moving_state[axis_name] = is_moving
        any_moving = any(self._axis_moving_state.values())
        self.stageMovingChanged.emit(any_moving)
