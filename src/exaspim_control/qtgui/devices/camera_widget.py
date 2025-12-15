from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from exaspim_control.qtgui.components import VSpinBox
from exaspim_control.qtgui.devices.device_widget import DeviceWidget
from exaspim_control.qtgui.devices.property_widget import PropertyValueWidget

if TYPE_CHECKING:
    from voxel.devices.camera.base import BaseCamera


class CameraWidget(DeviceWidget):
    """Widget for handling camera properties and controls.

    Compact layout with settings, ROI size table, and status bar.
    Image display is handled separately by ImageViewer.
    """

    __SKIP_PROPS__: ClassVar[set[str]] = {
        "latest_frame",
        "frame_number",
        "binning",
        "pixel_type",
        "exposure_time_ms",
        "readout_mode",
        "width_px",
        "width_offset_px",
        "height_px",
        "height_offset_px",
        "image_width_px",
        "image_height_px",
        "sensor_width_px",
        "sensor_height_px",
        "sensor_temperature_c",
        "mainboard_temperature_c",
        "frame_time_ms",
        "line_interval_us",
        "sampling_um_px",
        "um_px",
        "frame_width_mm",
        "frame_height_mm",
        "trigger",
        "trigger.mode",
        "trigger.source",
        "trigger.polarity",
    }

    def __init__(self, camera: BaseCamera, advanced_user: bool = True, parent: QWidget | None = None):
        """Initialize the CameraWidget.

        :param camera: Camera device instance
        :param advanced_user: Whether to show advanced properties
        """
        updating_props = [
            "sensor_temperature_c",
            "mainboard_temperature_c",
            "frame_number",
            "width_px",
            "width_offset_px",
            "height_px",
            "height_offset_px",
            "image_width_px",
            "image_height_px",
            "binning",
            "pixel_type",
            "exposure_time_ms",
        ]
        self.advanced_user = advanced_user

        super().__init__(camera, updating_properties=updating_props, parent=parent)

        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Create UI widgets
        (
            self._sensor_width_label,
            self._sensor_height_label,
            self._roi_width_input,
            self._roi_height_input,
            self._offset_x_input,
            self._offset_y_input,
            self._image_width_label,
            self._image_height_label,
        ) = self._create_size_table_widgets()
        (
            self._frame_number_label,
            self._sensor_temp_value,
            self._board_temp_value,
        ) = self._create_status_labels()

        # Build and add layout
        self.main_layout.addLayout(self._build_layout())

    def _create_size_table_widgets(
        self,
    ) -> tuple[QLabel, QLabel, VSpinBox, VSpinBox, VSpinBox, VSpinBox, QLabel, QLabel]:
        """Create size table widgets (sensor labels, ROI inputs, offset inputs, image labels)."""
        ROW_HEIGHT = 26

        def make_value_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setStyleSheet("color: #ccc; font-size: 11px; border: none; background: transparent;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFixedHeight(ROW_HEIGHT)
            return label

        # Sensor labels (read-only)
        sensor_width = make_value_label(str(self.device.sensor_width_px))
        sensor_height = make_value_label(str(self.device.sensor_height_px))

        # ROI inputs
        roi_width = VSpinBox()
        roi_width.setRange(1, self.device.sensor_width_px)
        roi_width.setValue(self.device.width_px)
        roi_width.setFixedHeight(ROW_HEIGHT)
        roi_width.valueChanged.connect(lambda v: setattr(self.device, "width_px", v))

        roi_height = VSpinBox()
        roi_height.setRange(1, self.device.sensor_height_px)
        roi_height.setValue(self.device.height_px)
        roi_height.setFixedHeight(ROW_HEIGHT)
        roi_height.valueChanged.connect(lambda v: setattr(self.device, "height_px", v))

        # Offset inputs
        offset_x = VSpinBox()
        offset_x.setRange(0, self.device.sensor_width_px - 1)
        offset_x.setValue(self.device.width_offset_px)
        offset_x.setFixedHeight(ROW_HEIGHT)
        offset_x.valueChanged.connect(lambda v: setattr(self.device, "width_offset_px", v))

        offset_y = VSpinBox()
        offset_y.setRange(0, self.device.sensor_height_px - 1)
        offset_y.setValue(self.device.height_offset_px)
        offset_y.setFixedHeight(ROW_HEIGHT)
        offset_y.valueChanged.connect(lambda v: setattr(self.device, "height_offset_px", v))

        # Image labels (read-only)
        image_width = make_value_label(str(self.device.image_width_px))
        image_height = make_value_label(str(self.device.image_height_px))

        return sensor_width, sensor_height, roi_width, roi_height, offset_x, offset_y, image_width, image_height

    def _create_status_labels(self) -> tuple[QLabel, QLabel, QLabel]:
        """Create status bar value labels."""
        frame_label = QLabel("0")
        frame_label.setStyleSheet("color: #ccc; font-size: 10px; border: none;")

        sensor_temp = QLabel("-- °C")
        sensor_temp.setStyleSheet("color: #ccc; font-size: 10px; border: none;")

        board_temp = QLabel("-- °C")
        board_temp.setStyleSheet("color: #ccc; font-size: 10px; border: none;")

        return frame_label, sensor_temp, board_temp

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
        self._settings_widgets = []

        for label_text, prop_name in [
            ("Binning", "binning"),
            ("Pixel Type", "pixel_type"),
            ("Exposure (ms)", "exposure_time_ms"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(2)

            label = QLabel(label_text)
            label.setStyleSheet("color: #888; font-size: 10px;")
            col.addWidget(label)

            if prop_name in self.props:
                widget = PropertyValueWidget(self.props[prop_name])
                widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                # Connect to property change handler (was missing!)
                widget.valueChanged.connect(self._on_property_changed)
                col.addWidget(widget)
                # Store reference for enable/disable
                self._settings_widgets.append(widget)

            row.addLayout(col, stretch=1)

        return row

    def _build_size_table(self) -> QWidget:
        """Build size table using pre-created widgets."""
        ROW_HEIGHT = 26
        container = QWidget()

        grid = QGridLayout(container)
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(20)
        grid.setContentsMargins(0, 0, 0, 0)

        def make_row_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setStyleSheet("color: #aaa; font-size: 11px; border: none; background: transparent;")
            label.setFixedHeight(ROW_HEIGHT)
            return label

        def make_header(text: str) -> QLabel:
            label = QLabel(text)
            label.setStyleSheet(
                "color: #888; font-size: 10px; font-weight: bold; border: none; background: transparent;"
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

        # Sensor row
        grid.addWidget(make_row_label("Sensor"), 3, 0)
        grid.addWidget(self._sensor_width_label, 3, 1)
        grid.addWidget(self._sensor_height_label, 3, 2)

        # Image row
        grid.addWidget(make_row_label("Image"), 4, 0)
        grid.addWidget(self._image_width_label, 4, 1)
        grid.addWidget(self._image_height_label, 4, 2)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        return container

    def _build_status_bar(self) -> QFrame:
        """Build status bar using pre-created labels."""
        frame = QFrame()
        frame.setObjectName("statusBar")
        frame.setStyleSheet("""
            QFrame#statusBar {
                background-color: #252526;
                border-top: 1px solid #404040;
            }
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
            label.setStyleSheet("color: #888; font-size: 10px; border: none;")

            item_layout.addWidget(label)
            item_layout.addWidget(value_label)
            item_layout.addStretch()

            return container

        def make_separator() -> QFrame:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.VLine)
            sep.setFixedWidth(1)
            sep.setStyleSheet("background-color: #404040;")
            return sep

        layout.addWidget(make_status_item("Frame:", self._frame_number_label), stretch=1)
        layout.addWidget(make_separator())
        layout.addWidget(make_status_item("Sensor:", self._sensor_temp_value), stretch=1)
        layout.addWidget(make_separator())
        layout.addWidget(make_status_item("Board:", self._board_temp_value), stretch=1)

        return frame

    def set_acquisition_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable controls that shouldn't be changed during acquisition.

        Disables pixel_type, binning, exposure_time, and ROI controls during livestream
        to prevent crashes from dtype/buffer mismatches.

        :param enabled: True to enable controls, False to disable
        """
        # Disable settings row widgets (binning, pixel_type, exposure)
        if hasattr(self, "_settings_widgets"):
            for widget in self._settings_widgets:
                widget.setEnabled(enabled)

        # Disable ROI and offset inputs
        self._roi_width_input.setEnabled(enabled)
        self._roi_height_input.setEnabled(enabled)
        self._offset_x_input.setEnabled(enabled)
        self._offset_y_input.setEnabled(enabled)

    def update_status(self, prop_name: str, value) -> None:
        """Update status bar and ROI values from property polling."""
        if prop_name == "frame_number":
            self._frame_number_label.setText(str(value))
        elif prop_name == "sensor_temperature_c":
            if value is not None:
                self._sensor_temp_value.setText(f"{value:.1f} °C")
            else:
                self._sensor_temp_value.setText("-- °C")
        elif prop_name == "mainboard_temperature_c":
            if value is not None:
                self._board_temp_value.setText(f"{value:.1f} °C")
            else:
                self._board_temp_value.setText("-- °C")
        elif prop_name == "width_px":
            self._roi_width_input.blockSignals(True)
            self._roi_width_input.setValue(value)
            self._roi_width_input.blockSignals(False)
        elif prop_name == "height_px":
            self._roi_height_input.blockSignals(True)
            self._roi_height_input.setValue(value)
            self._roi_height_input.blockSignals(False)
        elif prop_name == "width_offset_px":
            self._offset_x_input.blockSignals(True)
            self._offset_x_input.setValue(value)
            self._offset_x_input.blockSignals(False)
        elif prop_name == "height_offset_px":
            self._offset_y_input.blockSignals(True)
            self._offset_y_input.setValue(value)
            self._offset_y_input.blockSignals(False)
        elif prop_name == "image_width_px":
            self._image_width_label.setText(str(value))
        elif prop_name == "image_height_px":
            self._image_height_label.setText(str(value))
