import contextlib
import logging
import time

import napari
import numpy as np
from napari.qt.threading import thread_worker
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QPushButton, QSizePolicy, QStyle, QVBoxLayout, QWidget
from view.widgets.base_device_widget import create_widget
from view.widgets.device_widget import DeviceWidget
from voxel.devices.camera.base import BaseCamera


class CameraWidget(DeviceWidget):
    """Widget for handling camera properties and controls with card-style layout."""

    def __init__(self, camera: BaseCamera, advanced_user: bool = True):
        """
        Initialize the CameraWidget object.

        :param camera: Camera object
        :type camera: BaseCamera
        :param advanced_user: Whether the user is advanced, defaults to True
        :type advanced_user: bool, optional
        """
        # Determine updating properties for advanced mode
        updating_props = ["sensor_temperature_c", "mainboard_temperature_c"] if advanced_user else []

        # Store advanced_user before calling super()
        self.advanced_user = advanced_user

        # Initialize DeviceWidget with camera instance
        super().__init__(camera, updating_properties=updating_props)

        # Logging
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Napari viewer (lazy initialization - created when expand button clicked)
        self._napari_viewer = None

        # Livestream state
        self._is_livestreaming = False
        self._grab_frames_worker = None

        # Create custom layout after initialization
        self._setup_camera_layout()

    def _setup_default_layout(self):
        """Override to prevent auto-layout - we'll do custom layout."""

    def _setup_camera_layout(self):
        """Create custom camera layout."""
        # Create buttons
        self.live_button = self.create_live_button()
        self.snapshot_button = self.create_snapshot_button()
        self.alignment_button = self.create_alignment_button()
        self.crosshairs_button = self.create_crosshairs_button()
        self.expand_viewer_button = self.create_expand_viewer_button()

        # Connect button signals
        self.live_button.clicked.connect(self._toggle_livestream)
        self.snapshot_button.clicked.connect(self._take_snapshot)
        self.expand_viewer_button.toggled.connect(self._toggle_napari_viewer)

        # Create embedded image display
        self.image_label = QLabel()
        self.image_label.setMinimumSize(320, 240)
        self.image_label.setMaximumSize(640, 480)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("QLabel { background-color: black; color: white; }")
        self.image_label.setText("No Image")
        self.image_label.setScaledContents(False)

        # Get pixel_type widget
        if "pixel_type" in self.property_widgets:
            pixel_type_widget = self.property_widgets["pixel_type"].value_widget.widget
        else:
            pixel_type_widget = QWidget()  # Fallback

        picture_buttons = create_widget(
            "H",
            self.live_button,
            self.snapshot_button,
            self.alignment_button,
            self.crosshairs_button,
            self.expand_viewer_button,
            pixel_type_widget,
        )

        if self.advanced_user:  # format widgets better in advanced user mode
            # Get timing property widgets
            timing_props = ["exposure_time_ms", "frame_time_ms", "line_interval_us"]
            timing_widget_children = []

            for prop in timing_props:
                if prop in self.property_widgets:
                    pw = self.property_widgets[prop]
                    timing_widget_children.extend([pw.label, pw.value_widget])

                    # Disable if read-only or if line_interval_us
                    if pw.device_property.access == "ro" or prop == "line_interval_us":
                        pw.setEnabled(False)

            timing_widgets = create_widget("VH", *timing_widget_children)

            # Get width property widgets
            width_props = ["width_px", "width_offset_px", "image_width_px", "sensor_width_px"]
            width_widget_children = []

            for prop in width_props:
                if prop in self.property_widgets:
                    pw = self.property_widgets[prop]
                    width_widget_children.extend([pw.label, pw.value_widget])

                    # Disable if read-only
                    if pw.device_property.access == "ro":
                        pw.setEnabled(False)

            width_widget = create_widget("HV", *width_widget_children)

            # Get height property widgets
            height_props = ["height_px", "height_offset_px", "image_height_px", "sensor_height_px"]
            height_widget_children = []

            for prop in height_props:
                if prop in self.property_widgets:
                    pw = self.property_widgets[prop]
                    height_widget_children.extend([pw.label, pw.value_widget])

                    # Disable if read-only
                    if pw.device_property.access == "ro":
                        pw.setEnabled(False)

            height_widget = create_widget("HV", *height_widget_children)

            # combine timing, width, and height widgets
            roi_widget = create_widget("H", width_widget, height_widget)
            combined_widget = create_widget("V", timing_widgets, roi_widget)

            # Get pixel options widgets
            pixel_props = ["binning", "sampling_um_px", "readout_mode"]
            pixel_widget_children = []

            for prop in pixel_props:
                if prop in self.property_widgets:
                    pw = self.property_widgets[prop]
                    pixel_widget_children.extend([pw.label, pw.value_widget])

                    # Disable if read-only
                    if pw.device_property.access == "ro":
                        pw.setEnabled(False)

            pixel_widgets = create_widget("HV", *pixel_widget_children)

            # Get trigger widgets (flattened from nested trigger dict)
            trigger_widget_children = []
            trigger_props = ["trigger.mode", "trigger.source", "trigger.polarity"]
            trigger_labels = ["Trigger Mode", "Trigger Source", "Trigger Polarity"]

            for prop, label_text in zip(trigger_props, trigger_labels):
                if prop in self.property_widgets:
                    pw = self.property_widgets[prop]
                    # Update label text
                    pw.label.setText(f"{label_text}:")
                    trigger_widget_children.append(create_widget("H", pw.label, pw.value_widget))

            trigger_widget = create_widget("V", *trigger_widget_children) if trigger_widget_children else QWidget()

            # reformat pixel trigger widget
            pixel_trigger_widget = create_widget("H", pixel_widgets, trigger_widget)

            # Get temperature widgets
            temp_widgets = []
            if "sensor_temperature_c" in self.property_widgets:
                sensor_temp_widget = self.property_widgets["sensor_temperature_c"].value_widget.widget
                sensor_temp_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Maximum)
                sensor_temp_widget.setMinimumWidth(40)
                sensor_temp_widget.setMaximumWidth(40)
                temp_widgets.append(self.property_widgets["sensor_temperature_c"])

            if "mainboard_temperature_c" in self.property_widgets:
                mainboard_temp_widget = self.property_widgets["mainboard_temperature_c"].value_widget.widget
                mainboard_temp_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Maximum)
                mainboard_temp_widget.setMinimumWidth(40)
                mainboard_temp_widget.setMaximumWidth(40)
                temp_widgets.append(self.property_widgets["mainboard_temperature_c"])

            temperature_widget = create_widget("H", *temp_widgets) if temp_widgets else QWidget()

            # Build layout with tracked properties
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(picture_buttons)
            layout.addWidget(self.image_label)  # Add embedded image display
            layout.addWidget(combined_widget)
            layout.addWidget(pixel_trigger_widget)
            layout.addWidget(temperature_widget)

            # Add remaining properties we haven't manually laid out
            skip_props = {
                "pixel_type",
                "exposure_time_ms",
                "frame_time_ms",
                "line_interval_us",
                "width_px",
                "width_offset_px",
                "image_width_px",
                "sensor_width_px",
                "height_px",
                "height_offset_px",
                "image_height_px",
                "sensor_height_px",
                "binning",
                "sampling_um_px",
                "readout_mode",
                "trigger.mode",
                "trigger.source",
                "trigger.polarity",
                "sensor_temperature_c",
                "mainboard_temperature_c",
                "latest_frame",  # Exclude image property
            }
            remaining = self._layout_properties(skip=skip_props)
            layout.addWidget(remaining)
        else:  # Simple mode - just buttons
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)

            button_widget = create_widget("H", self.live_button, self.snapshot_button)
            layout.addWidget(button_widget)
            layout.addWidget(self.image_label)  # Add embedded image display

        # Set validator decimals for timing properties if they exist
        if "frame_time_ms" in self.property_widgets:
            frame_widget = self.property_widgets["frame_time_ms"].value_widget.widget
            if hasattr(frame_widget, "validator") and frame_widget.validator():
                if hasattr(frame_widget.validator(), "setDecimals"):
                    frame_widget.validator().setDecimals(2)

        if "exposure_time_ms" in self.property_widgets:
            exposure_widget = self.property_widgets["exposure_time_ms"].value_widget.widget
            if hasattr(exposure_widget, "validator") and exposure_widget.validator():
                if hasattr(exposure_widget.validator(), "setDecimals"):
                    exposure_widget.validator().setDecimals(2)

    def create_live_button(self) -> QPushButton:
        """
        Create the live button.

        :return: Live button
        :rtype: QPushButton
        """
        button = QPushButton("Live")
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        button.setIcon(icon)

        return button

    def create_snapshot_button(self) -> QPushButton:
        """
        Create the snapshot button.

        :return: Snapshot button
        :rtype: QPushButton
        """
        button = QPushButton("Snapshot")
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        button.setIcon(icon)
        return button

    def create_alignment_button(self) -> QPushButton:
        """
        Create the alignment button.

        :return: Alignment button
        :rtype: QPushButton
        """
        button = QPushButton("Alignment")
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ToolBarHorizontalExtensionButton)
        button.setIcon(icon)
        return button

    def create_crosshairs_button(self) -> QPushButton:
        """
        Create the crosshairs button.

        :return: Crosshairs button
        :rtype: QPushButton
        """
        button = QPushButton("Crosshair")
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DockWidgetCloseButton)
        button.setIcon(icon)
        return button

    def create_expand_viewer_button(self) -> QPushButton:
        """
        Create the expand viewer toggle button.

        :return: Expand viewer button
        :rtype: QPushButton
        """
        button = QPushButton("Expand Viewer")
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton)
        button.setIcon(icon)
        button.setCheckable(True)
        return button

    def _calculate_fov_dimensions(self) -> list:
        """Calculate FOV dimensions from camera properties."""
        fov_height_mm = self.device.fov_height_mm
        fov_width_mm = self.device.fov_width_mm

        # Adjust for camera rotation
        if self.camera_rotation_deg in [-270, -90, 90, 270]:
            fov_dimensions = [fov_height_mm, fov_width_mm, 0]
        else:
            fov_dimensions = [fov_width_mm, fov_height_mm, 0]

        return fov_dimensions

    def _toggle_livestream(self):
        """Toggle livestream on/off."""
        if self._is_livestreaming:
            self._stop_livestream()
        else:
            self._start_livestream()

    def _start_livestream(self):
        """Start livestream."""
        self.log.info("Starting livestream")
        self._is_livestreaming = True
        self.live_button.setText("Stop")
        self.live_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))

        # Create and start frame grabbing worker
        self._grab_frames_worker = self._frame_grabber()
        self._grab_frames_worker.yielded.connect(self._update_image)
        self._grab_frames_worker.start()

    def _stop_livestream(self):
        """Stop livestream."""
        self.log.info("Stopping livestream")
        self._is_livestreaming = False
        self.live_button.setText("Live")
        self.live_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

        # Stop frame grabbing worker
        if self._grab_frames_worker is not None:
            self._grab_frames_worker.quit()
            self._grab_frames_worker = None

    def _take_snapshot(self):
        """Take a single snapshot."""
        self.log.info("Taking snapshot")
        try:
            frame = self.device.latest_frame
            self._update_image(frame)

            # Update napari viewer if open
            if self._napari_viewer is not None and self._napari_viewer.window.isVisible():
                self._update_napari_viewer(frame)
        except Exception as e:
            self.log.error(f"Failed to take snapshot: {e}")

    @thread_worker
    def _frame_grabber(self):
        """Worker to continuously grab frames from camera."""
        self.log.debug("Frame grabber started")

        while self._is_livestreaming:
            try:
                frame = self.device.latest_frame
                yield frame
            except Exception as e:
                self.log.warning(f"Failed to grab frame: {e}")

            time.sleep(0.033)  # ~30 fps

        self.log.debug("Frame grabber stopped")

    def _update_image(self, frame: np.ndarray):
        """
        Update embedded image display with new frame.

        :param frame: Image frame (numpy array)
        """
        if frame is None or frame.size == 0:
            return

        try:
            # Normalize to 8-bit for display
            if frame.dtype != np.uint8:
                frame_min = frame.min()
                frame_max = frame.max()
                if frame_max > frame_min:
                    frame_normalized = ((frame - frame_min) / (frame_max - frame_min) * 255).astype(np.uint8)
                else:
                    frame_normalized = np.zeros_like(frame, dtype=np.uint8)
            else:
                frame_normalized = frame

            # Convert to QImage
            height, width = frame_normalized.shape[:2]
            if frame_normalized.ndim == 2:
                # Grayscale
                qimage = QImage(frame_normalized.data, width, height, width, QImage.Format.Format_Grayscale8)
            else:
                # RGB (if needed in future)
                bytes_per_line = 3 * width
                qimage = QImage(frame_normalized.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)

            # Convert to pixmap and scale to fit label
            pixmap = QPixmap.fromImage(qimage)
            scaled_pixmap = pixmap.scaled(
                self.image_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)

            # Update napari viewer if open
            if self._napari_viewer is not None and self._napari_viewer.window.isVisible():
                self._update_napari_viewer(frame)

        except Exception as e:
            self.log.error(f"Failed to update image: {e}")

    def _toggle_napari_viewer(self, checked: bool):
        """
        Toggle napari viewer window.

        :param checked: Whether expand button is checked
        """
        if checked:
            self._show_napari_viewer()
        else:
            self._hide_napari_viewer()

    def _show_napari_viewer(self):
        """Show napari viewer window."""
        if self._napari_viewer is None:
            self._create_napari_viewer()

        self._napari_viewer.window.show()
        self._napari_viewer.window.raise_()
        self._napari_viewer.window.activateWindow()
        self.log.info("Napari viewer shown")

    def _hide_napari_viewer(self):
        """Hide napari viewer window."""
        if self._napari_viewer is not None:
            self._napari_viewer.window.hide()
            self.log.info("Napari viewer hidden")

    def _create_napari_viewer(self):
        """Create napari viewer as separate window."""
        self.log.info("Creating napari viewer")

        self._napari_viewer = napari.Viewer(
            title=f"Camera: {self.device.__class__.__name__}", ndisplay=2, axis_labels=("x", "y")
        )

        # Setup viewer properties
        self._napari_viewer.scale_bar.visible = True
        self._napari_viewer.scale_bar.unit = "um"
        self._napari_viewer.scale_bar.position = "bottom_left"

        # Connect close event to uncheck expand button
        def on_napari_close(event):
            event.ignore()
            self._napari_viewer.window.hide()
            self.expand_viewer_button.setChecked(False)
            self.log.info("Napari viewer closed")

        self._napari_viewer.window._qt_window.closeEvent = on_napari_close

    def _update_napari_viewer(self, frame: np.ndarray):
        """
        Update napari viewer with new frame.

        :param frame: Image frame (numpy array)
        """
        if self._napari_viewer is None:
            return

        try:
            # Update or create layer
            if len(self._napari_viewer.layers) == 0:
                self._napari_viewer.add_image(frame, name="Camera")
            else:
                self._napari_viewer.layers[0].data = frame
        except Exception as e:
            self.log.error(f"Failed to update napari viewer: {e}")

    def closeEvent(self, event):
        """Clean up on widget close."""
        self.log.debug("CameraWidget closing")

        # Stop livestream
        if self._is_livestreaming:
            self._stop_livestream()

        # Close napari viewer
        if self._napari_viewer is not None:
            with contextlib.suppress(AttributeError, RuntimeError, TypeError):
                self._napari_viewer.close()

        # Call parent closeEvent
        super().closeEvent(event)
