"""Unified live viewer for camera frames - embeddable or expandable to napari window."""

from __future__ import annotations

import logging
import time

import napari
import numpy as np
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)


class LiveViewer(QWidget):
    """Unified live viewer that can display inline or expand to napari window.

    When collapsed: Shows frames in an embedded QLabel with expand button overlay.
    When expanded: Opens a napari viewer window for full-featured viewing.

    Thread-safe: update_frame() can be called from any thread.
    """

    # Decimation factor for embedded preview display
    # E.g., 4 means use every 4th pixel (151MP -> ~9.4MP)
    PREVIEW_DECIMATION = 4

    expandToggled = pyqtSignal(bool)
    _frameReceived = pyqtSignal(object)  # Internal signal for thread-safe frame updates

    def __init__(
        self,
        title: str = "Live Viewer",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._title = title
        self._parent = parent  # Parent for napari window
        self._is_closing = False
        self._is_expanded = False
        self._frame_times: list[float] = []
        self._aspect_ratio = 4 / 3
        self._is_processing = False  # Flag to drop frames if still processing

        # Connect frame signal to slot (ensures updates happen on main thread)
        self._frameReceived.connect(self._process_frame)

        # Embedded view widgets
        self._image_label = self._create_image_label()
        self._expand_button = self._create_expand_button()
        self._fps_label = self._create_fps_label()

        # Build layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._image_label)

        self.setStyleSheet("background-color: black;")
        self.setMinimumSize(300, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Napari viewer (created lazily when first expanded)
        self._napari_viewer: napari.Viewer | None = None

    def _create_image_label(self) -> QLabel:
        """Create the embedded image display label."""
        label = QLabel(self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("background-color: black; color: #888;")
        label.setText("No Image")
        label.setScaledContents(False)
        return label

    def _create_expand_button(self) -> QPushButton:
        """Create the expand button overlay."""
        button = QPushButton(self)
        button.setCheckable(True)
        button.setFixedSize(28, 28)
        button.setToolTip("Expand to napari viewer")

        # Use standard fullscreen icon
        if (style := QApplication.style()) is not None:
            button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))

        button.setStyleSheet("""
            QPushButton {
                background-color: rgba(60, 60, 60, 180);
                border: 1px solid rgba(80, 80, 80, 180);
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(80, 80, 80, 200);
            }
            QPushButton:checked {
                background-color: rgba(0, 120, 212, 200);
                border-color: rgba(0, 140, 232, 200);
            }
        """)
        button.toggled.connect(self._on_expand_toggled)
        return button

    def _create_fps_label(self) -> QLabel:
        """Create the FPS display label overlay."""
        label = QLabel("-- FPS", self)
        label.setStyleSheet("""
            QLabel {
                color: #00ff00;
                background-color: rgba(0, 0, 0, 150);
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumWidth(60)
        label.adjustSize()
        return label

    def resizeEvent(self, a0) -> None:
        """Position overlay widgets when resized."""
        super().resizeEvent(a0)

        # Position expand button in top-right corner
        margin = 8
        btn_size = self._expand_button.sizeHint()
        self._expand_button.move(
            self.width() - btn_size.width() - margin,
            margin,
        )

        # Position FPS label in bottom-left corner
        fps_size = self._fps_label.sizeHint()
        self._fps_label.move(
            margin,
            self.height() - fps_size.height() - margin,
        )

    def _on_expand_toggled(self, checked: bool) -> None:
        """Handle expand button toggle."""
        self._is_expanded = checked
        if checked:
            self._show_napari_viewer()
        else:
            self._hide_napari_viewer()
        self.expandToggled.emit(checked)

    def set_expand_checked(self, checked: bool) -> None:
        """Set expand button state (for external sync)."""
        self._expand_button.blockSignals(True)
        self._expand_button.setChecked(checked)
        self._expand_button.blockSignals(False)
        self._is_expanded = checked

    def _create_napari_viewer(self) -> None:
        """Create napari viewer as child window of main window."""
        self.log.info("Creating napari viewer")

        self._napari_viewer = napari.Viewer(
            title=self._title,
            ndisplay=2,
            axis_labels=("x", "y"),
            show=False,
        )
        self._napari_viewer.scale_bar.visible = True
        self._napari_viewer.scale_bar.unit = "um"
        self._napari_viewer.scale_bar.position = "bottom_left"

        qt_window = self._napari_viewer.window._qt_window

        # Set parent so napari closes when main window closes
        if self._parent is not None:
            qt_window.setParent(self._parent)
            # Re-apply window flags to keep it as a separate window (not embedded)
            qt_window.setWindowFlags(qt_window.windowFlags() | Qt.WindowType.Window)

        # Custom close event - hide instead of close, uncheck expand button
        original_close = qt_window.closeEvent

        def on_close(event):
            if self._is_closing:
                original_close(event)
                return
            event.ignore()
            qt_window.hide()
            self._is_expanded = False
            self._expand_button.blockSignals(True)
            self._expand_button.setChecked(False)
            self._expand_button.blockSignals(False)
            self.expandToggled.emit(False)
            self.log.info("Napari viewer hidden")

        qt_window.closeEvent = on_close

    def _show_napari_viewer(self) -> None:
        """Show napari viewer window."""
        if self._napari_viewer is None:
            self._create_napari_viewer()

        qt_window = self._napari_viewer.window._qt_window
        qt_window.show()
        qt_window.raise_()
        qt_window.activateWindow()
        self.log.info("Napari viewer shown")

    def _hide_napari_viewer(self) -> None:
        """Hide napari viewer window."""
        if self._napari_viewer is not None:
            self._napari_viewer.window._qt_window.hide()
            self.log.info("Napari viewer hidden")

    def is_expanded(self) -> bool:
        """Check if napari viewer is currently visible."""
        if self._napari_viewer is None:
            return False
        return self._napari_viewer.window._qt_window.isVisible()

    def set_aspect_ratio(self, width: int, height: int) -> None:
        """Set the aspect ratio based on image dimensions."""
        if height > 0:
            self._aspect_ratio = width / height

    def heightForWidth(self, width: int) -> int:
        """Calculate height for given width to maintain aspect ratio."""
        return int(width / self._aspect_ratio)

    def hasHeightForWidth(self) -> bool:
        """Indicate that this widget maintains aspect ratio."""
        return True

    def sizeHint(self) -> QSize:
        """Return preferred size maintaining aspect ratio."""
        width = 400
        height = int(width / self._aspect_ratio)
        return QSize(width, height)

    def update_frame(self, frame: np.ndarray) -> None:
        """Update both embedded display and napari viewer with new frame.

        Thread-safe: Can be called from any thread. The actual GUI update
        is marshalled to the main thread via Qt signal.

        Drops frames if the display is still processing the previous one
        to prevent queue buildup.

        :param frame: Frame data as numpy array
        """
        if frame is None or frame.size == 0:
            return

        # Drop frame if still processing previous one (prevents queue buildup)
        if self._is_processing:
            return

        # Emit signal to process frame on main thread
        # Make a copy to avoid issues if the source buffer is reused
        self._frameReceived.emit(frame.copy())

    def _process_frame(self, frame: np.ndarray) -> None:
        """Process frame on main thread (slot for _frameReceived signal)."""
        self._is_processing = True
        try:
            # Calculate FPS
            now = time.time()
            self._frame_times.append(now)
            self._frame_times = self._frame_times[-10:]

            if len(self._frame_times) >= 2:
                elapsed = self._frame_times[-1] - self._frame_times[0]
                if elapsed > 0:
                    fps = (len(self._frame_times) - 1) / elapsed
                    self._fps_label.setText(f"{fps:.1f} FPS")

            # Update embedded display
            self._update_embedded_display(frame)

            # Update napari viewer if expanded
            if self._is_expanded and self._napari_viewer is not None:
                self._update_napari_viewer(frame)
        finally:
            self._is_processing = False

    def _update_embedded_display(self, frame: np.ndarray) -> None:
        """Update the embedded QLabel display with decimated frame."""
        try:
            # Set aspect ratio from original frame dimensions
            orig_height, orig_width = frame.shape[:2]
            self.set_aspect_ratio(orig_width, orig_height)

            # Decimate frame for preview (fast - simple slicing)
            d = self.PREVIEW_DECIMATION
            preview = frame[::d, ::d]
            height, width = preview.shape[:2]

            # Normalize to uint8 if needed
            if preview.dtype != np.uint8:
                frame_min = preview.min()
                frame_max = preview.max()
                if frame_max > frame_min:
                    frame_normalized = ((preview - frame_min) / (frame_max - frame_min) * 255).astype(np.uint8)
                else:
                    frame_normalized = np.zeros_like(preview, dtype=np.uint8)
            else:
                frame_normalized = preview

            # Create QImage - MUST call .copy() because QImage constructor takes a pointer
            # to the bytes data, and tobytes() creates a temporary that gets GC'd
            if frame_normalized.ndim == 2:
                qimage = QImage(
                    frame_normalized.tobytes(),
                    width,
                    height,
                    width,
                    QImage.Format.Format_Grayscale8,
                ).copy()  # copy() makes QImage own its data
            else:
                bytes_per_line = 3 * width
                qimage = QImage(
                    frame_normalized.tobytes(),
                    width,
                    height,
                    bytes_per_line,
                    QImage.Format.Format_RGB888,
                ).copy()  # copy() makes QImage own its data

            # Scale and display (FastTransformation since preview is already small)
            pixmap = QPixmap.fromImage(qimage)
            scaled = pixmap.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self._image_label.setPixmap(scaled)

        except Exception:
            self.log.exception("Failed to update embedded display")

    def _update_napari_viewer(self, frame: np.ndarray) -> None:
        """Update napari viewer with new frame.

        Handles dtype changes (e.g., mono16→mono8) gracefully by
        removing and re-adding the layer when needed.
        """
        if self._napari_viewer is None:
            return

        try:
            if len(self._napari_viewer.layers) == 0:
                self._napari_viewer.add_image(frame, name="Camera")
            else:
                layer = self._napari_viewer.layers[0]
                # Check if dtype changed - if so, remove and re-add layer
                # This prevents vispy/OpenGL crashes from dtype mismatch
                if layer.data.dtype != frame.dtype:
                    self.log.info(f"Frame dtype changed from {layer.data.dtype} to {frame.dtype}, recreating layer")
                    self._napari_viewer.layers.clear()
                    self._napari_viewer.add_image(frame, name="Camera")
                else:
                    layer.data = frame
        except Exception:
            self.log.exception("Failed to update napari viewer")

    def prepare_for_acquisition(self) -> None:
        """Prepare viewer for new acquisition.

        Clears napari layers to ensure fresh layer creation with correct dtype.
        Call this before starting livestream to prevent dtype mismatch crashes.
        """
        if self._napari_viewer is not None and len(self._napari_viewer.layers) > 0:
            self.log.info("Clearing napari layers for new acquisition")
            self._napari_viewer.layers.clear()

        # Reset FPS counter
        self._frame_times.clear()
        self._fps_label.setText("-- FPS")

    def close(self) -> None:
        """Close the viewer permanently."""
        self._is_closing = True
        if self._napari_viewer is not None:
            try:
                self._napari_viewer.close()
            except Exception:
                self.log.exception("Error closing napari viewer")
