"""Axis position widget with progress bar and slider overlay."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from exaspim_control.qtgui.devices.device_adapter import DeviceAdapter

if TYPE_CHECKING:
    from voxel.interfaces.axes import Axis


class AxisWidget(QWidget):
    """Compact axis control widget with position display and move command slider.

    Uses composition with DeviceAdapter rather than inheritance.

    Layout: [Label] [====progress+slider====] [value mm] [link checkbox]

    The progress bar shows actual position, the slider overlay is for commanding moves.
    When "linked", the slider follows the position. Unlink to command moves.
    """

    positionChanged = pyqtSignal(float)
    limitsChanged = pyqtSignal(float, float)  # (min, max) emitted when limits change
    movingChanged = pyqtSignal(bool)

    def __init__(
        self,
        name: str,
        adapter: DeviceAdapter[Axis],
        min_pos: float = 0.0,
        max_pos: float = 100.0,
        unit: str = "mm",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize axis widget.

        :param name: Display name for the axis
        :param adapter: DeviceAdapter for the axis device
        :param min_pos: Minimum position value
        :param max_pos: Maximum position value
        :param unit: Unit label (e.g., "mm")
        :param parent: Parent widget
        """
        super().__init__(parent)
        self._adapter = adapter
        self._name = name
        self._min_pos = min_pos
        self._max_pos = max_pos
        self._unit = unit
        self._slider_scale = 1000  # Slider/progress use int, scale for precision
        self._is_linked = True  # Start linked (slider follows position)
        self._is_moving = False

        self.log = logging.getLogger(f"{__name__}.{name}")

        # Setup UI
        self._setup_ui()
        self._connect_signals()

        # Connect to adapter property updates (thread-safe via Qt signal)
        adapter.propertyUpdated.connect(self._on_property_update)

        # Initialize from axis
        self._refresh()

    @property
    def device(self) -> Axis:
        """Get the axis device."""
        return self._adapter.device

    @property
    def axis(self) -> Axis:
        """Get the axis device (alias for device)."""
        return self._adapter.device

    def _setup_ui(self) -> None:
        """Set up the custom UI with progress bar and slider overlay."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        container = QWidget()
        row_layout = QHBoxLayout(container)
        row_layout.setContentsMargins(0, 2, 0, 2)
        row_layout.setSpacing(8)

        # Name label (chip-style)
        self._name_label = QLabel(self._name)
        self._name_label.setFixedWidth(100)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_label.setStyleSheet("""
            QLabel {
                background-color: #3c3c3c;
                color: #d4d4d4;
                padding: 2px 8px;
                border-radius: 3px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        row_layout.addWidget(self._name_label)

        # Stacked progress bar + slider
        self._track_widget = self._create_track_widget()
        row_layout.addWidget(self._track_widget, stretch=1)

        # Value label
        self._value_label = QLabel("0.00")
        self._value_label.setFixedWidth(60)
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._value_label.setStyleSheet("""
            QLabel {
                color: #d4d4d4;
                font-size: 11px;
                font-family: monospace;
            }
        """)
        row_layout.addWidget(self._value_label)

        # Unit label
        unit_label = QLabel(self._unit)
        unit_label.setFixedWidth(20)
        unit_label.setStyleSheet("color: #888; font-size: 10px;")
        row_layout.addWidget(unit_label)

        # Free checkbox (unchecked = linked/disabled, checked = free/enabled)
        self._link_checkbox = QCheckBox()
        self._link_checkbox.setChecked(False)  # Start unchecked (linked)
        self._link_checkbox.setToolTip(
            "Check to enable slider for commanding moves.\nUncheck to lock slider to position."
        )
        self._link_checkbox.setStyleSheet("""
            QCheckBox {
                spacing: 0px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
            }
            QCheckBox::indicator:unchecked {
                background-color: #3c3c3c;
                border: 1px solid #505050;
                border-radius: 2px;
            }
            QCheckBox::indicator:checked {
                background-color: #0078d4;
                border: 1px solid #0078d4;
                border-radius: 2px;
            }
        """)
        row_layout.addWidget(self._link_checkbox)

        layout.addWidget(container)

    def _create_track_widget(self) -> QWidget:
        """Create the stacked progress bar + slider widget."""
        track = QWidget()
        track.setFixedHeight(20)

        # Progress bar (shows actual position) - child of track
        self._progress_bar = QProgressBar(track)
        self._progress_bar.setRange(0, self._slider_scale)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #2d2d30;
                border: 1px solid #505050;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
                border-radius: 3px;
            }
        """)

        # Slider (for commanding moves) - transparent, overlaid on progress bar
        self._slider = QSlider(Qt.Orientation.Horizontal, track)
        self._slider.setRange(0, self._slider_scale)
        self._slider.setValue(0)
        self._slider.setEnabled(False)  # Start disabled since we start linked
        self._slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: transparent;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #e0e0e0;
                border: 1px solid #888;
                width: 3px;
                height: 16px;
                margin: -4px 0;
                border-radius: 1px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffffff;
                border-color: #aaa;
            }
            QSlider::handle:horizontal:disabled {
                background: #505050;
                border-color: #404040;
            }
            QSlider::sub-page:horizontal {
                background: transparent;
            }
            QSlider::add-page:horizontal {
                background: transparent;
            }
        """)

        return track

    def resizeEvent(self, a0) -> None:
        """Handle resize to keep progress bar and slider aligned."""
        super().resizeEvent(a0)
        if hasattr(self, "_track_widget"):
            w = self._track_widget.width()
            h = self._track_widget.height()
            # Progress bar centered vertically
            self._progress_bar.setGeometry(0, (h - 8) // 2, w, 8)
            # Slider covers full track
            self._slider.setGeometry(0, 0, w, h)

    def _connect_signals(self) -> None:
        """Connect widget signals."""
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._link_checkbox.toggled.connect(self._on_link_toggled)

    def _on_link_toggled(self, checked: bool) -> None:
        """Handle free checkbox toggle. Checked = free/enabled, Unchecked = linked/disabled."""
        self._is_linked = not checked  # Invert: checked means free (not linked)
        if checked:
            # Free mode: enable slider for commanding
            self._slider.setEnabled(True)
        else:
            # Linked mode: sync slider to current position and disable
            self._slider.setEnabled(False)
            pos = self._progress_bar.value()
            self._slider.blockSignals(True)
            self._slider.setValue(pos)
            self._slider.blockSignals(False)

    def _slider_to_position(self, slider_value: int) -> float:
        """Convert slider value to position."""
        ratio = slider_value / self._slider_scale
        return self._min_pos + ratio * (self._max_pos - self._min_pos)

    def _position_to_slider(self, position: float) -> int:
        """Convert position to slider value."""
        if self._max_pos == self._min_pos:
            return 0
        ratio = (position - self._min_pos) / (self._max_pos - self._min_pos)
        return int(ratio * self._slider_scale)

    def _on_slider_changed(self, value: int) -> None:
        """Update tooltip when slider moves (shows target position)."""
        if not self._is_linked:
            position = self._slider_to_position(value)
            self._slider.setToolTip(f"Target: {position:.2f} {self._unit}")

    def _on_slider_released(self) -> None:
        """Move axis when slider is released (only when unlinked)."""
        if self._is_linked:
            return

        position = self._slider_to_position(self._slider.value())
        self.positionChanged.emit(position)

        try:
            self.device.move_abs(position)
            self.log.debug(f"Moving {self._name} to {position:.2f} {self._unit}")
        except Exception:
            self.log.exception(f"Failed to move {self._name}")

    def _on_property_update(self, prop_name: str, value: Any) -> None:
        """Handle property updates from adapter polling."""
        if prop_name == "position_mm":
            self._update_position_display(value)
        elif prop_name == "limits_mm":
            if value and len(value) == 2:
                new_min, new_max = value
                if new_min != self._min_pos or new_max != self._max_pos:
                    self.set_range(new_min, new_max)
                    self.limitsChanged.emit(new_min, new_max)
        elif prop_name == "is_moving":
            if value != self._is_moving:
                self._is_moving = value
                self.movingChanged.emit(value)

    def _update_position_display(self, position: float) -> None:
        """Update progress bar and value label with actual position."""
        slider_val = self._position_to_slider(position)

        # Update progress bar (always shows actual position)
        self._progress_bar.setValue(slider_val)

        # Update value label
        self._value_label.setText(f"{position:.2f}")

        # If linked, slider follows position
        if self._is_linked:
            self._slider.blockSignals(True)
            self._slider.setValue(slider_val)
            self._slider.blockSignals(False)

    def _refresh(self) -> None:
        """Refresh position from axis."""
        try:
            position = self.device.position_mm
            self._update_position_display(position)
        except Exception:
            self.log.exception(f"Failed to read {self._name} position")

    def set_position(self, position: float) -> None:
        """Set the displayed position (without moving axis)."""
        self._update_position_display(position)

    def set_range(self, min_pos: float, max_pos: float) -> None:
        """Set the position range."""
        self._min_pos = min_pos
        self._max_pos = max_pos

    def closeEvent(self, a0) -> None:
        """Clean up on close."""
        # Qt automatically disconnects signals when objects are destroyed
        super().closeEvent(a0)
