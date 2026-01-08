"""Camera widget with ROI controls and status display."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from exaspim_control._qtgui.model import DeviceAdapter
from exaspim_control._qtgui.primitives import Button, Colors, Separator, SpinBox
from exaspim_control._qtgui.widgets.devices.base import PropertyWidget

if TYPE_CHECKING:
    from voxel.interfaces.camera import SpimCamera


class CameraWidget(QWidget):
    """Widget for handling camera properties and controls.

    Uses composition with DeviceAdapter rather than inheritance.

    Compact layout with settings, ROI size table, and status bar.
    ROI edits are staged until user clicks "Apply ROI" for atomic updates.
    """

    def __init__(self, adapter: DeviceAdapter[SpimCamera], parent: QWidget | None = None) -> None:
        """Initialize the CameraWidget.

        :param adapter: DeviceAdapter for the camera device
        """
        super().__init__(parent)
        self._adapter = adapter
        self.log = logging.getLogger(f"{__name__}.{adapter.device.uid}")

        # Track staged ROI values (not yet applied)
        self._staged_roi: dict[str, int] = {}
        self._roi_dirty = False

        # Create UI widgets
        self._create_size_table_widgets()
        self._create_status_labels()

        # Build layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._build_layout())

        # Initialize from current device state
        self._sync_roi_from_device()

        # Connect to adapter property updates (thread-safe via Qt signal)
        adapter.propertyUpdated.connect(self._on_property_update)

    @property
    def device(self) -> SpimCamera:
        """Get the camera device."""
        return self._adapter.device

    def _create_size_table_widgets(self) -> None:
        """Create size table widgets (sensor labels, ROI inputs, frame labels)."""
        ROW_HEIGHT = 26
        device = self.device
        region = device.frame_region

        def make_value_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setStyleSheet(f"color: {Colors.TEXT}; font-size: 11px; border: none; background: transparent;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFixedHeight(ROW_HEIGHT)
            return label

        # Sensor labels (read-only)
        self._sensor_width_label = make_value_label(str(device.sensor_size_px.x))
        self._sensor_height_label = make_value_label(str(device.sensor_size_px.y))

        # ROI inputs (staged, applied on button click)
        self._roi_width_input = SpinBox()
        self._roi_width_input.setRange(region.width.min_value or 1, region.width.max_value or device.sensor_size_px.x)
        self._roi_width_input.setSingleStep(region.width.step or 1)
        self._roi_width_input.setValue(int(region.width))
        self._roi_width_input.setFixedHeight(ROW_HEIGHT)
        self._roi_width_input.valueChanged.connect(lambda v: self._stage_roi_change("width", v))

        self._roi_height_input = SpinBox()
        self._roi_height_input.setRange(
            region.height.min_value or 1, region.height.max_value or device.sensor_size_px.y
        )
        self._roi_height_input.setSingleStep(region.height.step or 1)
        self._roi_height_input.setValue(int(region.height))
        self._roi_height_input.setFixedHeight(ROW_HEIGHT)
        self._roi_height_input.valueChanged.connect(lambda v: self._stage_roi_change("height", v))

        # Offset inputs
        self._offset_x_input = SpinBox()
        self._offset_x_input.setRange(region.x.min_value or 0, region.x.max_value or device.sensor_size_px.x)
        self._offset_x_input.setSingleStep(region.x.step or 1)
        self._offset_x_input.setValue(int(region.x))
        self._offset_x_input.setFixedHeight(ROW_HEIGHT)
        self._offset_x_input.valueChanged.connect(lambda v: self._stage_roi_change("x", v))

        self._offset_y_input = SpinBox()
        self._offset_y_input.setRange(region.y.min_value or 0, region.y.max_value or device.sensor_size_px.y)
        self._offset_y_input.setSingleStep(region.y.step or 1)
        self._offset_y_input.setValue(int(region.y))
        self._offset_y_input.setFixedHeight(ROW_HEIGHT)
        self._offset_y_input.valueChanged.connect(lambda v: self._stage_roi_change("y", v))

        # Frame size labels (read-only, shows size after binning)
        frame_size = device.frame_size_px
        self._frame_width_label = make_value_label(str(frame_size.x))
        self._frame_height_label = make_value_label(str(frame_size.y))

        # Apply ROI button
        self._apply_roi_btn = Button("Apply ROI", variant="secondary")
        self._apply_roi_btn.setEnabled(False)
        self._apply_roi_btn.clicked.connect(self._apply_staged_roi)

    def _create_status_labels(self) -> None:
        """Create status bar value labels."""
        self._frame_number_label = QLabel("0")
        self._frame_number_label.setStyleSheet(f"color: {Colors.TEXT}; font-size: 10px; border: none;")

        self._frame_rate_label = QLabel("-- fps")
        self._frame_rate_label.setStyleSheet(f"color: {Colors.TEXT}; font-size: 10px; border: none;")

        self._data_rate_label = QLabel("-- MB/s")
        self._data_rate_label.setStyleSheet(f"color: {Colors.TEXT}; font-size: 10px; border: none;")

    def _build_layout(self) -> QVBoxLayout:
        """Build the complete camera widget layout."""
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # Row 1: Quick settings
        layout.addLayout(self._build_settings_row())

        # Row 2: Size table
        layout.addWidget(self._build_size_table())

        # Row 3: Status bar
        layout.addWidget(self._build_status_bar())

        return layout

    def _build_settings_row(self) -> QHBoxLayout:
        """Build settings row with property inputs."""
        row = QHBoxLayout()
        row.setSpacing(12)

        # Store references to settings widgets for enable/disable during acquisition
        self._settings_widgets: list[QWidget] = []

        for label_text, prop_name in [
            ("Binning", "binning"),
            ("Pixel Format", "pixel_format"),
            ("Exposure (ms)", "exposure_time_ms"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(2)

            label = QLabel(label_text)
            label.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 10px;")
            col.addWidget(label)

            if prop_name in self._adapter.properties:
                info = self._adapter.properties[prop_name]
                widget = PropertyWidget(self.device, info)
                widget.valueChanged.connect(self._on_value_changed)
                col.addWidget(widget)
                self._settings_widgets.append(widget)

            row.addLayout(col, stretch=1)

        return row

    def _build_size_table(self) -> QWidget:
        """Build size table with ROI inputs and apply button."""
        ROW_HEIGHT = 26
        container = QWidget()

        grid = QGridLayout(container)
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(20)
        grid.setContentsMargins(0, 0, 0, 0)

        def make_row_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setStyleSheet(f"color: {Colors.TEXT}; font-size: 11px; border: none; background: transparent;")
            label.setFixedHeight(ROW_HEIGHT)
            return label

        def make_header(text: str) -> QLabel:
            label = QLabel(text)
            label.setStyleSheet(
                f"color: {Colors.TEXT_MUTED}; font-size: 10px; font-weight: bold; border: none; background: transparent;"
            )
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFixedHeight(ROW_HEIGHT)
            return label

        # Headers
        grid.addWidget(QLabel(""), 0, 0)
        grid.addWidget(make_header("Width"), 0, 1)
        grid.addWidget(make_header("Height"), 0, 2)

        # ROI row
        grid.addWidget(make_row_label("ROI"), 1, 0)
        grid.addWidget(self._roi_width_input, 1, 1)
        grid.addWidget(self._roi_height_input, 1, 2)

        # Offset row
        grid.addWidget(make_row_label("Offset"), 2, 0)
        grid.addWidget(self._offset_x_input, 2, 1)
        grid.addWidget(self._offset_y_input, 2, 2)

        # Sensor row (read-only)
        grid.addWidget(make_row_label("Sensor"), 3, 0)
        grid.addWidget(self._sensor_width_label, 3, 1)
        grid.addWidget(self._sensor_height_label, 3, 2)

        # Frame row (read-only, after binning)
        grid.addWidget(make_row_label("Frame"), 4, 0)
        grid.addWidget(self._frame_width_label, 4, 1)
        grid.addWidget(self._frame_height_label, 4, 2)

        # Apply button row
        grid.addWidget(self._apply_roi_btn, 5, 0, 1, 3)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        return container

    def _build_status_bar(self) -> QFrame:
        """Build status bar with streaming info."""
        frame = QFrame()
        frame.setObjectName("statusBar")
        frame.setStyleSheet(f"""
            QFrame#statusBar {{
                background-color: {Colors.BG_LIGHT};
                border-top: 1px solid {Colors.HOVER};
            }}
        """)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        def make_status_item(label_text: str, value_label: QLabel) -> QWidget:
            container = QWidget()
            item_layout = QHBoxLayout(container)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(4)

            label = QLabel(label_text)
            label.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 10px; border: none;")

            item_layout.addWidget(label)
            item_layout.addWidget(value_label)
            item_layout.addStretch()

            return container

        def make_separator() -> Separator:
            return Separator(orientation="vertical", color=Colors.HOVER)

        layout.addWidget(make_status_item("Frame:", self._frame_number_label), stretch=1)
        layout.addWidget(make_separator())
        layout.addWidget(make_status_item("Rate:", self._frame_rate_label), stretch=1)
        layout.addWidget(make_separator())
        layout.addWidget(make_status_item("Data:", self._data_rate_label), stretch=1)

        return frame

    def _stage_roi_change(self, field: str, value: int) -> None:
        """Stage a ROI field change (not applied until Apply button clicked)."""
        self._staged_roi[field] = value
        self._roi_dirty = True
        self._apply_roi_btn.setEnabled(True)

    def _apply_staged_roi(self) -> None:
        """Apply staged ROI changes to device atomically."""
        if not self._roi_dirty:
            return

        try:
            # Apply staged frame region values
            self.device.update_frame_region(
                x=self._staged_roi.get("x"),
                y=self._staged_roi.get("y"),
                width=self._staged_roi.get("width"),
                height=self._staged_roi.get("height"),
            )
            self._staged_roi.clear()
            self._roi_dirty = False
            self._apply_roi_btn.setEnabled(False)
            self.log.debug("Applied frame region changes")
            # Sync UI with actual applied values (may have been coerced)
            self._sync_roi_from_device()
        except Exception:
            self.log.exception("Failed to apply frame region")

    def _sync_roi_from_device(self) -> None:
        """Sync ROI inputs from device (e.g., after applying or on init)."""
        region = self.device.frame_region
        frame_size = self.device.frame_size_px

        # Block signals to avoid re-triggering staged changes
        for widget in [self._roi_width_input, self._roi_height_input, self._offset_x_input, self._offset_y_input]:
            widget.blockSignals(True)

        self._roi_width_input.setValue(int(region.width))
        self._roi_height_input.setValue(int(region.height))
        self._offset_x_input.setValue(int(region.x))
        self._offset_y_input.setValue(int(region.y))

        for widget in [self._roi_width_input, self._roi_height_input, self._offset_x_input, self._offset_y_input]:
            widget.blockSignals(False)

        # Update frame size labels
        self._frame_width_label.setText(str(frame_size.x))
        self._frame_height_label.setText(str(frame_size.y))

    def _on_value_changed(self, name: str, value: Any) -> None:
        """Handle value change from a PropertyWidget."""
        self._adapter.set_property(name, value)
        # Binning affects frame size, so refresh
        if name == "binning":
            self._sync_roi_from_device()

    def set_acquisition_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable controls that shouldn't be changed during acquisition.

        Disables pixel_format, binning, exposure_time, and ROI controls during livestream
        to prevent crashes from dtype/buffer mismatches.

        :param enabled: True to enable controls, False to disable
        """
        # Disable settings row widgets (binning, pixel_format, exposure)
        for widget in self._settings_widgets:
            widget.setEnabled(enabled)

        # Disable ROI and offset inputs
        self._roi_width_input.setEnabled(enabled)
        self._roi_height_input.setEnabled(enabled)
        self._offset_x_input.setEnabled(enabled)
        self._offset_y_input.setEnabled(enabled)
        self._apply_roi_btn.setEnabled(enabled and self._roi_dirty)

    def _on_property_update(self, prop_name: str, value: Any) -> None:
        """Handle property updates from adapter polling."""
        if prop_name == "stream_info" and value is not None:
            # StreamInfo contains frame_index, frame_rate_fps, data_rate_mbs
            self._frame_number_label.setText(str(value.frame_index))
            self._frame_rate_label.setText(f"{value.frame_rate_fps:.1f} fps")
            self._data_rate_label.setText(f"{value.data_rate_mbs:.1f} MB/s")
        elif prop_name == "frame_region":
            # Frame region changed externally, sync if no staged changes
            if not self._roi_dirty:
                self._sync_roi_from_device()
        elif prop_name == "frame_size_px":
            self._frame_width_label.setText(str(value.x))
            self._frame_height_label.setText(str(value.y))

    def closeEvent(self, a0) -> None:
        """Clean up on close."""
        # Qt automatically disconnects signals when objects are destroyed
        super().closeEvent(a0)
