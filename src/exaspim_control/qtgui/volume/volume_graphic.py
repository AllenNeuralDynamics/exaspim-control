"""VolumeGraphic - 3D visualization widget for acquisition grid.

This widget displays the configured acquisition grid in 3D space.
It subscribes to VolumeModel signals to update the visualization.
"""

from math import radians, sqrt, tan

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMatrix4x4, QQuaternion, QVector3D
from PyQt6.QtWidgets import QCheckBox, QMessageBox, QWidget
from pyqtgraph import makeRGBA
from pyqtgraph.opengl import GLImageItem
from scipy import spatial

from exaspim_control.qtgui.misc.gl_ortho_view_widget import GLOrthoViewWidget
from exaspim_control.qtgui.misc.gl_path_item import GLPathItem
from exaspim_control.qtgui.misc.gl_shaded_box_item import GLShadedBoxItem

from .volume_model import VolumeModel


class VolumeGraphic(GLOrthoViewWidget):
    """Widget to display configured acquisition grid.

    Note that x and y refer to the tiling dimensions and z is the scanning dimension.
    This widget subscribes to VolumeModel signals to update the visualization.
    """

    fovMove = pyqtSignal(list)
    fovHalt = pyqtSignal()

    def __init__(
        self,
        model: VolumeModel,
        fov_color: str = "yellow",
        fov_line_width: int = 2,
        fov_opacity: float = 0.15,
        path_line_width: int = 2,
        path_arrow_size: float = 6.0,
        path_arrow_aspect_ratio: int = 4,
        path_start_color: str = "yellow",
        path_end_color: str = "green",
        active_tile_color: str = "cyan",
        active_tile_opacity: float = 0.075,
        dual_active_tile_color: str = "magenta",
        dual_active_tile_opacity: float = 0.075,
        inactive_tile_color: str = "red",
        inactive_tile_opacity: float = 0.025,
        tile_line_width: int = 2,
        limits_line_width: int = 2,
        limits_color: str = "white",
        limits_opacity: float = 0.1,
        parent: QWidget | None = None,
    ):
        """Initialize VolumeGraphic.

        :param model: VolumeModel instance containing shared state
        :param fov_color: FOV box color
        :param fov_line_width: Width of FOV outline
        :param fov_opacity: Opacity of FOV face (0-1)
        :param path_line_width: Width of path line
        :param path_arrow_size: Size of arrow at path end (% of FOV)
        :param path_arrow_aspect_ratio: Aspect ratio of arrow
        :param path_start_color: Start color of path gradient
        :param path_end_color: End color of path gradient
        :param active_tile_color: Color of tiles when FOV is within grid
        :param active_tile_opacity: Opacity of active tiles (0-1)
        :param dual_active_tile_color: Color of dual-sided active tiles
        :param dual_active_tile_opacity: Opacity of dual-sided active tiles
        :param inactive_tile_color: Color of tiles when FOV is outside grid
        :param inactive_tile_opacity: Opacity of inactive tiles (0-1)
        :param tile_line_width: Width of tile outlines
        :param limits_line_width: Width of limits box outline
        :param limits_color: Color of limits box
        :param limits_opacity: Opacity of limits box (0-1)
        """
        super().__init__(rotationMethod="quaternion", parent=parent)

        # Store reference to shared model
        self._model = model

        # Initialize attributes from model
        self.unit = model.unit
        self.coordinate_plane = model.coordinate_plane_clean
        self.polarity = model.polarity
        self.fov_dimensions = [*model.fov_dimensions[:2], 0]  # add 0 in scanning dim
        self.fov_position = list(model.fov_position)
        self.view_plane = (self.coordinate_plane[0], self.coordinate_plane[1])

        # Grid state (updated from model)
        self.scan_volumes = np.zeros([1, 1])
        self.grid_coords = np.zeros([1, 1, 3])
        self.start_tile_coord = np.zeros([1, 1, 3])
        self.end_tile_coord = np.zeros([1, 1, 3])
        self.grid_box_items = []
        self.tile_visibility = np.array([[True]])

        # Tile aesthetic properties
        self.dual_sided = model.dual_sided
        self.active_tile_color = active_tile_color
        self.active_tile_opacity = active_tile_opacity
        self.dual_active_tile_color = dual_active_tile_color
        self.dual_active_tile_opacity = dual_active_tile_opacity
        self.inactive_tile_color = inactive_tile_color
        self.inactive_tile_opacity = inactive_tile_opacity
        self.tile_line_width = tile_line_width

        # Limits aesthetic properties
        limits = model.limits
        if not limits or limits == [[float("-inf"), float("inf")] for _ in range(3)]:
            limits = [[float("-inf"), float("inf")] for _ in range(3)]
        self._limits = limits
        self.limits_line_width = limits_line_width
        self.limits_color = limits_color
        self.limits_opacity = limits_opacity

        # Path visualization
        self.path = GLPathItem(
            width=path_line_width,
            arrow_size=path_arrow_size,
            arrow_aspect_ratio=path_arrow_aspect_ratio,
            path_start_color=path_start_color,
            path_end_color=path_end_color,
        )
        self.addItem(self.path)

        # FOV images dictionary
        self.fov_images = {}

        # Initialize FOV visualization
        self.fov_view = GLShadedBoxItem(
            width=fov_line_width,
            pos=np.array([[self.fov_position]]),
            size=np.array(self.fov_dimensions),
            color=fov_color,
            opacity=fov_opacity,
            glOptions="additive",
        )
        self.fov_view.setTransform(
            QMatrix4x4(
                1,
                0,
                0,
                self.fov_position[0] * self.polarity[0],
                0,
                1,
                0,
                self.fov_position[1] * self.polarity[1],
                0,
                0,
                1,
                self.fov_position[2] * self.polarity[2],
                0,
                0,
                0,
                1,
            )
        )
        self.addItem(self.fov_view)

        # Add limits box if finite limits provided
        self._limits_box = None
        self._update_limits_box()

        # Connect model signals
        self._model.fovPositionChanged.connect(self._on_fov_position_changed)
        self._model.fovDimensionsChanged.connect(self._on_fov_dimensions_changed)
        self._model.limitsChanged.connect(self._on_limits_changed)
        self._model.tilesChanged.connect(self._on_tiles_changed)

        self.resized.connect(self._update_opts)
        self._update_opts()

    def _update_limits_box(self) -> None:
        """Update or create the limits box visualization."""
        limits = self._limits
        if limits == [[float("-inf"), float("inf")] for _ in range(3)]:
            if self._limits_box is not None:
                self.removeItem(self._limits_box)
                self._limits_box = None
            return

        size = [((max(limits[i]) - min(limits[i])) + self.fov_dimensions[i]) for i in range(3)]
        pos = np.array(
            [
                [
                    [
                        min([x * self.polarity[0] for x in limits[0]]),
                        min([y * self.polarity[1] for y in limits[1]]),
                        min([z * self.polarity[2] for z in limits[2]]),
                    ]
                ]
            ]
        )

        if self._limits_box is not None:
            self._limits_box.setData(pos=pos, size=np.array(size))
        else:
            self._limits_box = GLShadedBoxItem(
                width=self.limits_line_width,
                pos=pos,
                size=np.array(size),
                color=self.limits_color,
                opacity=self.limits_opacity,
                glOptions="additive",
            )
            self.addItem(self._limits_box)

    def _on_fov_position_changed(self, position: list) -> None:
        """Handle FOV position change from model."""
        self.fov_position = list(position)
        self._update_model("fov_position")

    def _on_fov_dimensions_changed(self, dimensions: list) -> None:
        """Handle FOV dimensions change from model."""
        self.fov_dimensions = [*dimensions[:2], 0]
        self._update_model("fov_dimensions")

    def _on_limits_changed(self, limits: list) -> None:
        """Handle limits change from model."""
        self._limits = [list(lim) for lim in limits]
        self._update_limits_box()
        self._update_opts()

    def _on_tiles_changed(self) -> None:
        """Handle tile changes from model."""
        # Update local state from model
        self.grid_coords = self._model.tile_positions
        self.scan_volumes = self._model.scan_volumes
        self.tile_visibility = self._model.tile_visibility
        self.dual_sided = self._model.dual_sided

        # Update path visualization
        path_coords = self._model.path_coords
        if path_coords:
            self.set_path_pos(path_coords)

        # Trigger full grid update
        self._update_model("grid_coords")

    def _update_model(self, attribute_name: str) -> None:
        """Update visualization based on attribute change.

        :param attribute_name: Name of attribute that changed
        """
        # Update color of tiles based on z position
        flat_coords = self.grid_coords.reshape([-1, 3])
        flat_dims = self.scan_volumes.flatten()
        coords = np.concatenate(
            (
                flat_coords,
                [[x, y, (z + sz)] for (x, y, z), sz in zip(flat_coords, flat_dims)],
            )
        )
        extrema = [
            [min(coords[:, 0]), max(coords[:, 0])],
            [min(coords[:, 1]), max(coords[:, 1])],
            [min(coords[:, 2]), max(coords[:, 2])],
        ]

        # Determine if FOV is within grid
        in_grid = not any(pos > pos_max or pos < pos_min for (pos_min, pos_max), pos in zip(extrema, self.fov_position))

        # Determine middle x coordinate
        center_line = np.mean(coords[:, 0])

        if attribute_name == "fov_position":
            # Update FOV position
            self.fov_view.setTransform(
                QMatrix4x4(
                    1,
                    0,
                    0,
                    self.fov_position[0] * self.polarity[0],
                    0,
                    1,
                    0,
                    self.fov_position[1] * self.polarity[1],
                    0,
                    0,
                    1,
                    self.fov_position[2] * self.polarity[2],
                    0,
                    0,
                    0,
                    1,
                )
            )
            color = self.grid_box_items[0].color() if len(self.grid_box_items) != 0 else None
            if (not in_grid and color != self.inactive_tile_color) or (in_grid and color != self.active_tile_color):
                box_ind = 0
                for box in self.grid_box_items:
                    if in_grid:
                        new_color = (
                            self.active_tile_color
                            if coords[box_ind, 0] < center_line or not self.dual_sided
                            else self.dual_active_tile_color
                        )
                    else:
                        new_color = self.inactive_tile_color
                    box.setColor(new_color)
                    box_ind += 1
        else:
            self.fov_view.setSize(x=self.fov_dimensions[0], y=self.fov_dimensions[1], z=0.0)

            # Faster to remove every box than parse which ones have changes
            for box in self.grid_box_items:
                self.removeItem(box)
            self.grid_box_items = []

            total_rows = len(self.grid_coords)
            total_columns = len(self.grid_coords[0])

            for row in range(total_rows):
                for column in range(total_columns):
                    coord = [x * pol for x, pol in zip(self.grid_coords[row][column], self.polarity)]
                    size = [*self.fov_dimensions[:2], self.scan_volumes[row, column]]

                    # Determine color
                    if in_grid:
                        color = (
                            self.active_tile_color
                            if coord[0] < center_line or not self.dual_sided
                            else self.dual_active_tile_color
                        )
                        opacity = (
                            self.active_tile_opacity
                            if coord[0] < center_line or not self.dual_sided
                            else self.dual_active_tile_opacity
                        )
                    else:
                        color = self.inactive_tile_color
                        opacity = self.inactive_tile_opacity

                    # Scale opacity for viewing
                    if self.view_plane == (self.coordinate_plane[2], self.coordinate_plane[1]):
                        opacity = opacity / total_columns
                    elif self.view_plane != (self.coordinate_plane[0], self.coordinate_plane[1]):
                        opacity = opacity / total_rows

                    box = GLShadedBoxItem(
                        width=self.tile_line_width,
                        pos=np.array([[coord]]),
                        size=np.array(size),
                        color=color,
                        opacity=opacity,
                        glOptions="additive",
                    )
                    box.setVisible(self.tile_visibility[row, column])
                    self.addItem(box)
                    self.grid_box_items.append(box)

        self._update_opts()

    def toggle_view_plane(self, button) -> None:
        """Update view plane optics.

        :param button: Button pressed to change view
        """
        view_plane = tuple(x for x in button.text() if x.isalpha())
        self.view_plane = view_plane
        self._update_model("view_plane")

    def set_path_pos(self, coord_order: list) -> None:
        """Set the position of path in correct order.

        :param coord_order: Ordered list of coords for path
        """
        path = np.array(
            [
                [((coord[i] * pol) + (0.5 * fov)) for i, fov, pol in zip([0, 1, 2], self.fov_dimensions, self.polarity)]
                for coord in coord_order
            ]
        )
        self.path.setData(pos=path)

    def add_fov_image(self, image: np.ndarray, levels: list[float]) -> None:
        """Add image to model assuming image has same FOV dimensions and orientation.

        :param image: NumPy array of image to display
        :param levels: Levels for passed in image
        """
        image_rgba = makeRGBA(image, levels=levels)
        image_rgba[0][:, :, 3] = 200

        gl_image = GLImageItem(image_rgba[0], glOptions="additive")
        x, y, z = self.fov_position
        gl_image.setTransform(
            QMatrix4x4(
                self.fov_dimensions[0] / image.shape[0],
                0,
                0,
                x * self.polarity[0],
                0,
                self.fov_dimensions[1] / image.shape[1],
                0,
                y * self.polarity[1],
                0,
                0,
                1,
                z * self.polarity[2],
                0,
                0,
                0,
                1,
            )
        )
        self.addItem(gl_image)
        self.fov_images[image.tobytes()] = gl_image

        if self.view_plane != (self.coordinate_plane[0], self.coordinate_plane[1]):
            gl_image.setVisible(False)

    def adjust_glimage_contrast(self, image: np.ndarray, contrast_levels: list[float]) -> None:
        """Adjust image contrast levels.

        :param image: NumPy array key in fov_images
        :param contrast_levels: Levels for passed in image
        """
        if image.tobytes() in self.fov_images:
            glimage = self.fov_images[image.tobytes()]
            self.removeItem(glimage)
            self.add_fov_image(image, contrast_levels)

    def toggle_fov_image_visibility(self, visible: bool) -> None:
        """Toggle visibility of all FOV images.

        :param visible: Whether FOV images should be visible
        """
        for image in self.fov_images.values():
            image.setVisible(visible)

    def _update_opts(self) -> None:
        """Update view of widget.

        Note: x/y notation refers to horizontal/vertical dimensions of grid view.
        """
        view_plane = self.view_plane
        view_pol = [
            self.polarity[self.coordinate_plane.index(view_plane[0])],
            self.polarity[self.coordinate_plane.index(view_plane[1])],
        ]
        coords = self.grid_coords.reshape([-1, 3])
        dimensions = self.scan_volumes.flatten()

        # Set rotation
        root = sqrt(2.0) / 2.0
        if view_plane == (self.coordinate_plane[0], self.coordinate_plane[1]):
            self.opts["rotation"] = QQuaternion(-1, 0, 0, 0)
        else:
            self.opts["rotation"] = (
                QQuaternion(-root, 0, -root, 0)
                if view_plane == (self.coordinate_plane[2], self.coordinate_plane[1])
                else QQuaternion(-root, root, 0, 0)
            )
            # Take into account end of tile and difference in size if z included
            coords = np.concatenate(
                (
                    coords,
                    [[x, y, (z + sz)] for (x, y, z), sz in zip(coords, dimensions)],
                )
            )

        extrema = {
            f"{self.coordinate_plane[0]}_min": min(coords[:, 0]),
            f"{self.coordinate_plane[0]}_max": max(coords[:, 0]),
            f"{self.coordinate_plane[1]}_min": min(coords[:, 1]),
            f"{self.coordinate_plane[1]}_max": max(coords[:, 1]),
            f"{self.coordinate_plane[2]}_min": min(coords[:, 2]),
            f"{self.coordinate_plane[2]}_max": max(coords[:, 2]),
        }

        fov = dict(zip(self.coordinate_plane, self.fov_dimensions))
        pos = dict(zip(self.coordinate_plane, self.fov_position))
        distances = {
            self.coordinate_plane[0] + self.coordinate_plane[1]: [
                sqrt((pos[view_plane[0]] - x) ** 2 + (pos[view_plane[1]] - y) ** 2) for x, y, z in coords
            ],
            self.coordinate_plane[0] + self.coordinate_plane[2]: [
                sqrt((pos[view_plane[0]] - x) ** 2 + (pos[view_plane[1]] - z) ** 2) for x, y, z in coords
            ],
            self.coordinate_plane[2] + self.coordinate_plane[1]: [
                sqrt((pos[view_plane[0]] - z) ** 2 + (pos[view_plane[1]] - y) ** 2) for x, y, z in coords
            ],
        }
        max_index = distances["".join(view_plane)].index(max(distances["".join(view_plane)], key=abs))
        furthest_tile = {
            self.coordinate_plane[0]: coords[max_index][0],
            self.coordinate_plane[1]: coords[max_index][1],
            self.coordinate_plane[2]: coords[max_index][2],
        }
        center = {}

        # Horizontal sizing
        x = view_plane[0]
        if extrema[f"{x}_min"] <= pos[x] <= extrema[f"{x}_max"] or abs(furthest_tile[x] - pos[x]) < abs(
            extrema[f"{x}_max"] - extrema[f"{x}_min"]
        ):
            center[x] = (((extrema[f"{x}_min"] + extrema[f"{x}_max"]) / 2) + (fov[x] / 2 * view_pol[0])) * view_pol[0]
            horz_dist = (
                ((extrema[f"{x}_max"] - extrema[f"{x}_min"]) + (fov[x] * 2)) / 2 * tan(radians(self.opts["fov"]))
            )
        else:
            center[x] = (((pos[x] + furthest_tile[x]) / 2) + (fov[x] / 2 * view_pol[0])) * view_pol[0]
            horz_dist = (abs(pos[x] - furthest_tile[x]) + (fov[x] * 2)) / 2 * tan(radians(self.opts["fov"]))

        # Vertical sizing
        y = view_plane[1]
        scaling = self.size().width() / self.size().height()
        if extrema[f"{y}_min"] <= pos[y] <= extrema[f"{y}_max"] or abs(furthest_tile[y] - pos[y]) < abs(
            extrema[f"{y}_max"] - extrema[f"{y}_min"]
        ):
            center[y] = (((extrema[f"{y}_min"] + extrema[f"{y}_max"]) / 2) + (fov[y] / 2 * view_pol[1])) * view_pol[1]
            vert_dist = (
                ((extrema[f"{y}_max"] - extrema[f"{y}_min"]) + (fov[y] * 2))
                / 2
                * tan(radians(self.opts["fov"]))
                * scaling
            )
        else:
            center[y] = (((pos[y] + furthest_tile[y]) / 2) + (fov[y] / 2 * view_pol[1])) * view_pol[1]
            vert_dist = (abs(pos[y] - furthest_tile[y]) + (fov[y] * 2)) / 2 * tan(radians(self.opts["fov"])) * scaling

        # In ortho mode it scales properly with x1200
        self.opts["distance"] = horz_dist * 1200 if horz_dist > vert_dist else vert_dist * 1200

        self.opts["center"] = QVector3D(
            center.get(self.coordinate_plane[0], 0),
            center.get(self.coordinate_plane[1], 0),
            center.get(self.coordinate_plane[2], 0),
        )

        self.update()

    def move_fov_query(self, new_fov_pos: list[float]) -> tuple[int, bool]:
        """Show message box asking if user wants to move FOV position.

        :param new_fov_pos: Position to move the FOV to
        :return: User reply and whether to move to nearest tile
        """
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Icon.Question)
        msgBox.setText(
            f"Do you want to move the field of view from "
            f"{[round(float(x), 2) for x in self.fov_position]} [{self.unit}] to "
            f"{[round(float(x), 2) for x in new_fov_pos]} [{self.unit}]?"
        )
        msgBox.setWindowTitle("Moving FOV")
        msgBox.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)

        checkbox = QCheckBox("Move to nearest tile")
        checkbox.setChecked(True)
        msgBox.setCheckBox(checkbox)

        return msgBox.exec(), checkbox.isChecked()

    def delete_fov_image_query(self, fov_image_pos: list[float]) -> int:
        """Show message box asking if user wants to delete FOV image.

        :param fov_image_pos: Coordinates of FOV image
        :return: User reply
        """
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Icon.Question)
        msgBox.setText(f"Do you want to delete image at {fov_image_pos} [{self.unit}]?")
        msgBox.setWindowTitle("Deleting FOV Image")
        msgBox.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)

        return msgBox.exec()

    def mousePressEvent(self, event) -> None:
        """Handle mouse press to allow FOV movement.

        :param event: QMouseEvent
        """
        plane = list(self.view_plane) + [ax for ax in self.coordinate_plane if ax not in self.view_plane]
        view_pol = [
            self.polarity[self.coordinate_plane.index(plane[0])],
            self.polarity[self.coordinate_plane.index(plane[1])],
            self.polarity[self.coordinate_plane.index(plane[2])],
        ]

        # Translate mouse click to view widget coordinate plane
        horz_dist = (self.opts["distance"] / tan(radians(self.opts["fov"]))) / 1200
        vert_dist = (
            self.opts["distance"] / tan(radians(self.opts["fov"])) * (self.size().height() / self.size().width())
        ) / 1200
        horz_scale = (event.position().x() * 2 * horz_dist) / self.size().width()
        vert_scale = (event.position().y() * 2 * vert_dist) / self.size().height()

        fov = dict(zip(self.coordinate_plane, self.fov_dimensions))
        pos = dict(zip(self.coordinate_plane, self.fov_position))

        center = {
            self.coordinate_plane[0]: self.opts["center"].x(),
            self.coordinate_plane[1]: self.opts["center"].y(),
            self.coordinate_plane[2]: self.opts["center"].z(),
        }
        h_ax = self.view_plane[0]
        v_ax = self.view_plane[1]

        new_pos = {
            plane[0]: ((center[h_ax] - horz_dist + horz_scale) - 0.5 * fov[plane[0]]) * view_pol[0],
            plane[1]: ((center[v_ax] + vert_dist - vert_scale) - 0.5 * fov[plane[1]]) * view_pol[1],
            plane[2]: pos[plane[2]] * view_pol[2],
        }
        move_to = [new_pos[ax] for ax in self.coordinate_plane]

        if event.button() == Qt.MouseButton.LeftButton:
            return_value, checkbox = self.move_fov_query(move_to)

            if return_value == QMessageBox.StandardButton.Ok:
                if not checkbox:  # Move to exact location
                    pos = move_to
                else:  # Move to nearest tile
                    flattened = self.grid_coords.reshape([-1, 3])
                    tree = spatial.KDTree(flattened)
                    _distance, index = tree.query(move_to)
                    tile = flattened[index]
                    pos = [tile[0], tile[1], tile[2]]
                self.fovMove.emit(pos)
            else:
                return

        elif event.button() == Qt.MouseButton.RightButton:
            delete_key = None
            for key, image in self.fov_images.items():
                coords = [image.transform()[i, 3] for i in range(3)]
                if (
                    coords[0] - self.fov_dimensions[0] <= coords[0] <= coords[0] + self.fov_dimensions[0]
                    and coords[1] - self.fov_dimensions[1] <= coords[1] <= coords[1] + self.fov_dimensions[1]
                ):
                    return_value = self.delete_fov_image_query(coords)
                    if return_value == QMessageBox.StandardButton.Ok:
                        self.removeItem(image)
                        delete_key = key
                    break
            if delete_key is not None:
                del self.fov_images[delete_key]

    def mouseMoveEvent(self, event):
        """Override mouseMoveEvent so user can't change view."""

    def wheelEvent(self, event):
        """Override wheelEvent so user can't change view."""

    def keyPressEvent(self, event):
        """Override keyPressEvent so user can't change view."""

    def keyReleaseEvent(self, event):
        """Override keyReleaseEvent so user can't change view."""
