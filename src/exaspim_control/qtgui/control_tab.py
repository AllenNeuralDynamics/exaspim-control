"""Control tab for instrument device controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from exaspim_control.qtgui.components import Card
from exaspim_control.qtgui.devices.axis_widget import AxisWidget

if TYPE_CHECKING:
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

    def __init__(
        self,
        camera_widget: CameraWidget | None = None,
        camera_uid: str = "",
        laser_widgets: dict[str, LaserWidget] | None = None,
        stage: Any = None,
        focusing_axes: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        # Store stage axis widgets for external access
        self.stage_axis_widgets: dict[str, AxisWidget] = {}

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Camera card
        if camera_widget:
            camera_card = Card(f"Camera: {camera_uid}")
            camera_card.add_widget(camera_widget)
            layout.addWidget(camera_card)

        # Laser cards
        if laser_widgets:
            for uid, laser_widget in laser_widgets.items():
                laser_card = Card(f"Laser: {uid}")
                laser_card.add_widget(laser_widget)
                layout.addWidget(laser_card)

        # Stage card
        if stage:
            stage_card = Card("Stage")
            stage_container = QWidget()
            stage_layout = QVBoxLayout(stage_container)
            stage_layout.setContentsMargins(0, 0, 0, 0)
            stage_layout.setSpacing(4)

            for name, axis in [("X", stage.x), ("Y", stage.y), ("Z", stage.z)]:
                limits = axis.limits_mm
                axis_widget = AxisWidget(name, axis=axis, min_pos=limits[0], max_pos=limits[1])
                axis_widget.limitsChanged.connect(self.stageLimitsChanged.emit)
                self.stage_axis_widgets[name.lower()] = axis_widget
                stage_layout.addWidget(axis_widget)

            stage_card.add_widget(stage_container)
            layout.addWidget(stage_card)

        # Focus card
        if focusing_axes:
            focus_card = Card("Focus")
            focus_container = QWidget()
            focus_layout = QVBoxLayout(focus_container)
            focus_layout.setContentsMargins(0, 0, 0, 0)
            focus_layout.setSpacing(4)

            for name, axis in focusing_axes.items():
                limits = axis.limits_mm
                axis_widget = AxisWidget(name, axis=axis, min_pos=limits[0], max_pos=limits[1])
                focus_layout.addWidget(axis_widget)

            focus_card.add_widget(focus_container)
            layout.addWidget(focus_card)

        layout.addStretch()
        self.setWidget(container)
