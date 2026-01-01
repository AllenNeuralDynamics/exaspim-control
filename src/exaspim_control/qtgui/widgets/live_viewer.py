"""Unified live viewer for camera frames - embeddable or expandable to napari window."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import napari
import numpy as np
from napari.utils.transforms import Affine
from PyQt6.QtCore import QByteArray, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from exaspim_control.qtgui.primitives.input import VIconButton, VLabel

if TYPE_CHECKING:
    from voxel.preview import PreviewFrame


class LiveViewer(QWidget):
    """Live viewer with embedded preview and optional napari window for full-res."""

    expandToggled = pyqtSignal(bool)
    _frameReceived = pyqtSignal(object)  # Internal signal for thread-safe frame updates
    _previewReceived = pyqtSignal(object)  # Internal signal for pre-processed preview frames

    def __init__(
        self,
        title: str = "Live Viewer",
        camera_rotation_deg: float = 0.0,
        parent: QWidget | None = None,
    ):
        """Initialize LiveViewer.

        :param title: Window title for napari viewer
        :param camera_rotation_deg: Camera rotation in degrees (0, 90, -90, 180, etc.)
            Used to rotate displayed frames to match physical stage orientation.
        :param parent: Parent widget
        """
        super().__init__(parent)
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._title = title
        self._parent = parent
        self._image_rotation_deg = -camera_rotation_deg
        self._is_closing = False
        self._frame_times: list[float] = []

        # Connect frame signals to slots (ensures updates happen on main thread)
        self._frameReceived.connect(self._process_frame)
        self._previewReceived.connect(self._process_preview)

        # Store last histogram for future UI controls
        self._last_histogram: list[int] | None = None

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

        # Create napari viewer (hidden initially)
        self._napari_viewer = napari.Viewer(title=self._title, ndisplay=2, axis_labels=("x", "y"), show=False)
        self._setup_napari_viewer()

    @property
    def napari_window(self):
        return self._napari_viewer.window._qt_window  # noqa: SLF001

    @property
    def is_expanded(self) -> bool:
        return self.napari_window.isVisible()

    def update_frame(self, frame: np.ndarray) -> None:
        """Update napari viewer with raw frame (for full-res viewing).

        Note: The frame is already copied by PreviewGenerator, so no copy is needed here.
        """
        if frame is None or frame.size == 0:
            return
        self._frameReceived.emit(frame)

    def update_preview(self, preview: PreviewFrame) -> None:
        """Update embedded display with pre-processed preview frame."""
        if preview is None:
            return
        self._previewReceived.emit(preview)

    def reset(self) -> None:
        self._frame_times.clear()
        self._fps_label.setText("-- FPS")

    def close(self) -> bool:
        self._is_closing = True
        if self._napari_viewer is not None:
            try:
                self._napari_viewer.close()
            except Exception:
                self.log.exception("Error closing napari viewer")
        return True

    def sizeHint(self) -> QSize:
        return QSize(400, 300)

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

    def _create_image_label(self) -> QLabel:
        """Create the embedded image display label."""
        label = QLabel(self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("background-color: black; color: #888;")
        label.setText("No Image")
        label.setScaledContents(False)
        return label

    def _create_expand_button(self) -> VIconButton:
        """Create the expand button overlay."""
        button = VIconButton(
            standard_icon="SP_TitleBarMaxButton",
            variant="overlay",
            parent=self,
        )
        button.setCheckable(True)
        button.setToolTip("Expand to napari viewer")
        button.toggled.connect(self._on_expand_toggled)
        return button

    def _create_fps_label(self) -> VLabel:
        """Create the FPS display label overlay."""
        label = VLabel("-- FPS", variant="overlay", parent=self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumWidth(60)
        label.adjustSize()
        return label

    def _setup_napari_viewer(self) -> None:
        """Create napari viewer as child window of main window."""
        self.log.info("Creating napari viewer")

        # Configure scale bar but keep hidden until viewer is shown (avoids vispy font warning)
        self._napari_viewer.scale_bar.unit = "um"
        self._napari_viewer.scale_bar.position = "bottom_left"

        # Set parent so napari closes when main window closes
        if self._parent is not None:
            self.napari_window.setParent(self._parent)
            # Re-apply window flags to keep it as a separate window (not embedded)
            self.napari_window.setWindowFlags(self.napari_window.windowFlags() | Qt.WindowType.Window)

        # Custom close event - hide instead of close, uncheck expand button
        original_close = self.napari_window.closeEvent

        def on_close(event):
            if self._is_closing:
                original_close(event)
                return
            event.ignore()
            self.napari_window.hide()
            self._expand_button.blockSignals(True)
            self._expand_button.setChecked(False)
            self._expand_button.blockSignals(False)
            self.expandToggled.emit(False)
            self.log.info("Napari viewer hidden")

        self.napari_window.closeEvent = on_close

    def _process_frame(self, frame: np.ndarray) -> None:
        """Process raw frame for napari viewer."""
        if self.is_expanded and self._napari_viewer is not None:
            try:
                if len(self._napari_viewer.layers) == 0:
                    layer = self._napari_viewer.add_image(frame, name="Camera")
                    if self._image_rotation_deg != 0:
                        layer.affine = _create_center_rotation_affine(self._image_rotation_deg, frame.shape)  # pyright: ignore[reportAttributeAccessIssue]
                layer = self._napari_viewer.layers[0]
                layer.data = frame
            except Exception:
                self.log.exception("Failed to update napari viewer")

    def _process_preview(self, preview: PreviewFrame) -> None:
        try:
            now = time.time()
            self._frame_times.append(now)
            self._frame_times = self._frame_times[-10:]

            if len(self._frame_times) >= 2:
                elapsed = self._frame_times[-1] - self._frame_times[0]
                if elapsed > 0:
                    fps = (len(self._frame_times) - 1) / elapsed
                    self._fps_label.setText(f"{fps:.1f} FPS")

            if preview.info.histogram is not None:
                self._last_histogram = preview.info.histogram

            pixmap = QPixmap()
            if not pixmap.loadFromData(QByteArray(preview.data)):
                self.log.warning("Failed to decode preview image data")
                return

            # Apply rotation if needed (same rotation as napari viewer)
            if self._image_rotation_deg != 0:
                transform = QTransform().rotate(self._image_rotation_deg)
                pixmap = pixmap.transformed(transform, Qt.TransformationMode.FastTransformation)

            scaled = pixmap.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self._image_label.setPixmap(scaled)

        except Exception:
            self.log.exception("Failed to process preview frame")

    def _on_expand_toggled(self, checked: bool) -> None:
        """Handle expand button toggle."""
        self._napari_viewer.scale_bar.visible = checked
        if checked:
            self.napari_window.show()
            self.napari_window.raise_()
            self.napari_window.activateWindow()
            self.log.info("Napari viewer shown")
        else:
            self.napari_window.hide()
            self.log.info("Napari viewer hidden")
        self.expandToggled.emit(checked)


def _create_center_rotation_affine(image_rotation_deg, shape: tuple[int, ...]) -> Affine:
    """Create affine transform for rotation around image center."""
    h, w = shape[:2]
    cy, cx = h / 2, w / 2
    theta = np.radians(image_rotation_deg)
    cos_t, sin_t = np.cos(theta), np.sin(theta)

    # Rotation around center: translate to origin, rotate, translate back
    # Combined into single affine matrix (column vector convention)
    # Translation compensates for rotation around origin to make it appear as center rotation
    ty = cy - (cy * cos_t - cx * sin_t)
    tx = cx - (cy * sin_t + cx * cos_t)

    matrix = np.array(
        [
            [cos_t, -sin_t, ty],
            [sin_t, cos_t, tx],
            [0, 0, 1],
        ]
    )
    return Affine(affine_matrix=matrix)
