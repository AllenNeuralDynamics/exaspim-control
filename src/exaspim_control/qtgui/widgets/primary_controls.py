"""PrimaryControls - Self-contained widget for primary device controls."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from exaspim_control.qtgui.primitives.card import Card
from exaspim_control.qtgui.widgets.devices.axis import AxisWidget
from exaspim_control.qtgui.widgets.devices.camera import CameraWidget
from exaspim_control.qtgui.widgets.devices.laser import LaserWidget

if TYPE_CHECKING:
    from exaspim_control.qtgui.model import InstrumentModel


class PrimaryControls(QScrollArea):
    """Self-contained widget for primary device controls.

    Creates and manages device widgets internally. Subscribes to
    InstrumentModel.streamingChanged to reactively enable/disable
    camera acquisition controls.

    Layout:
    - Camera card
    - Laser cards
    - Stage card
    - Focus card

    Signals:
        limitsChanged: Emitted when stage limits change (for VolumeGraphic)
    """

    limitsChanged = pyqtSignal()

    def __init__(self, model: InstrumentModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model

        # Create widgets internally (private)
        self._camera_widget = CameraWidget(model.camera, parent=self)
        self._laser_widgets = {uid: LaserWidget(adapter, parent=self) for uid, adapter in model.lasers.items()}
        self._stage_widgets = self._create_stage_widgets()
        self._focusing_widgets = self._create_focusing_widgets()

        # Setup UI
        self._setup_ui()

        # Subscribe to streaming state for reactive camera control enable/disable
        model.streamingChanged.connect(self._on_streaming_changed)

    def _create_stage_widgets(self) -> dict[str, AxisWidget]:
        """Create axis widgets for stage axes."""
        widgets = {}
        for name, adapter in self._model.stage_adapters.items():
            axis = adapter.device
            widget = AxisWidget(
                name.upper(),
                adapter=adapter,
                min_pos=axis.lower_limit_mm,
                max_pos=axis.upper_limit_mm,
                unit=self._model.unit,
                parent=self,
            )
            widget.limitsChanged.connect(self._on_limits_changed)
            widgets[name] = widget
        return widgets

    def _create_focusing_widgets(self) -> dict[str, AxisWidget]:
        """Create axis widgets for focusing axes."""
        widgets = {}
        for name, adapter in self._model.focusing_axes.items():
            axis = adapter.device
            widgets[name] = AxisWidget(
                name,
                adapter=adapter,
                min_pos=axis.lower_limit_mm,
                max_pos=axis.upper_limit_mm,
                parent=self,
            )
        return widgets

    def _setup_ui(self) -> None:
        """Setup the scrollable layout with device cards."""
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Camera card
        camera_uid = self._model.camera.device.uid
        layout.addWidget(Card(f"Camera: {camera_uid}", self._camera_widget, parent=container))

        # Laser cards
        for uid, laser_widget in self._laser_widgets.items():
            layout.addWidget(Card(f"Laser: {uid}", laser_widget, parent=container))

        # Stage card
        layout.addWidget(Card("Stage", *self._stage_widgets.values(), spacing=4, parent=container))

        # Focus card (if there are focusing axes)
        if self._focusing_widgets:
            layout.addWidget(Card("Focus", *self._focusing_widgets.values(), spacing=4, parent=container))

        layout.addStretch()
        self.setWidget(container)

    def _on_limits_changed(self, _min: float, _max: float) -> None:
        """Handle stage axis limits change - emit signal for listeners."""
        # stage_limits property reads directly from devices, just notify listeners
        self._model.stageLimitsChanged.emit(self._model.stage_limits)
        self.limitsChanged.emit()

    def _on_streaming_changed(self, is_streaming: bool) -> None:
        """Enable/disable camera acquisition controls based on streaming state."""
        self._camera_widget.set_acquisition_controls_enabled(not is_streaming)
