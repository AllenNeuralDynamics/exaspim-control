"""OpenGL shaded box item for 3D visualization."""

import numpy as np
from OpenGL.GL import GL_LINES, glBegin, glColor4f, glEnd, glLineWidth, glVertex3f
from PyQt6.QtGui import QColor
from pyqtgraph.opengl import GLMeshItem


class GLShadedBoxItem(GLMeshItem):
    """GLMeshItem subclass that draws a shaded rectangular box with outline.

    Used to visualize tiles, FOV, and stage limits in 3D space.
    """

    def __init__(
        self,
        pos: np.ndarray,
        size: np.ndarray,
        color: str = "cyan",
        width: float = 1,
        opacity: float = 1,
        *args,
        **kwargs,
    ):
        """Initialize shaded box item.

        :param pos: Position of box corner (3D array)
        :param size: Size of box [x, y, z]
        :param color: Color name or RGB values
        :param width: Line width for outline
        :param opacity: Face opacity (0-1)
        """
        self._size = size
        self._width = width
        self._opacity = opacity
        self._color = color
        colors = np.array([self._convert_color(color) for i in range(12)])

        self._pos = pos
        self._vertexes, self._faces = self._create_box(pos, size)

        super().__init__(
            vertexes=self._vertexes,
            faces=self._faces,
            faceColors=colors,
            drawEdges=True,
            edgeColor=(0, 0, 0, 1),
            *args,
            **kwargs,
        )

    def _create_box(self, pos: np.ndarray, size: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Create box vertex and face arrays.

        :param pos: Position of upper right corner
        :param size: Box dimensions [x, y, z]
        :return: Tuple of (vertexes, faces) arrays
        """
        nCubes = np.prod(pos.shape[:-1])
        cubeVerts = np.mgrid[0:2, 0:2, 0:2].reshape(3, 8).transpose().reshape(1, 8, 3)
        cubeFaces = np.array([
            [0, 1, 2], [3, 2, 1],
            [4, 5, 6], [7, 6, 5],
            [0, 1, 4], [5, 4, 1],
            [2, 3, 6], [7, 6, 3],
            [0, 2, 4], [6, 4, 2],
            [1, 3, 5], [7, 5, 3],
        ]).reshape(1, 12, 3)
        size = size.reshape((nCubes, 1, 3))
        pos = pos.reshape((nCubes, 1, 3))
        vertexes = (cubeVerts * size + pos)[0]
        faces = (cubeFaces + (np.arange(nCubes) * 8).reshape(nCubes, 1, 1))[0]

        return vertexes, faces

    def color(self) -> str | list[float]:
        """Get box color."""
        return self._color

    def setColor(self, c: str | list[float]) -> None:
        """Set box color."""
        self._color = self._convert_color(c) if isinstance(c, str) else c
        colors = np.array([self._color for i in range(12)])
        self.setMeshData(vertexes=self._vertexes, faces=self._faces, faceColors=colors)

    def _convert_color(self, color: str | list[float]) -> list[float]:
        """Convert color name to RGBA values."""
        if isinstance(color, str):
            rgbf = list(QColor(color).getRgbF())
            alpha = rgbf[3] if rgbf[3] is not None else 1.0
            return [rgbf[0] or 0.0, rgbf[1] or 0.0, rgbf[2] or 0.0, self._opacity * alpha]
        return color

    def size(self) -> np.ndarray:
        """Get box size."""
        return self._size

    def setSize(self, x: float, y: float, z: float) -> None:
        """Set box size."""
        self._size = np.array([x, y, z])
        self._vertexes, self._faces = self._create_box(self._pos, self._size)
        colors = np.array([self._convert_color(self._color) for i in range(12)])
        self.setMeshData(vertexes=self._vertexes, faces=self._faces, faceColors=colors)

    def setData(self, pos: np.ndarray | None = None, size: np.ndarray | None = None) -> None:
        """Set box position and/or size.

        :param pos: New position (optional)
        :param size: New size (optional)
        """
        if pos is not None:
            self._pos = pos
        if size is not None:
            self._size = size
        self._vertexes, self._faces = self._create_box(self._pos, self._size)
        colors = np.array([self._convert_color(self._color) for i in range(12)])
        self.setMeshData(vertexes=self._vertexes, faces=self._faces, faceColors=colors)

    def opacity(self) -> float:
        """Get box opacity."""
        return self._opacity

    def setOpacity(self, opacity: float) -> None:
        """Set box face opacity."""
        self._opacity = opacity
        colors = np.array([self._convert_color(self._color) for i in range(12)])
        self.setMeshData(vertexes=self._vertexes, faces=self._faces, faceColors=colors)

    def paint(self) -> None:
        """Paint box with outline."""
        super().paint()

        self.setupGLState()
        glLineWidth(self._width)

        glBegin(GL_LINES)
        glColor4f(*self._convert_color(self._color))

        x, y, z = [self._pos[0, 0, i] + x for i, x in enumerate(self.size())]
        x_pos, y_pos, z_pos = self._pos[0, 0, :]

        # Draw all 12 edges of the box
        glVertex3f(x_pos, y_pos, z_pos)
        glVertex3f(x_pos, y_pos, z)
        glVertex3f(x, y_pos, z_pos)
        glVertex3f(x, y_pos, z)
        glVertex3f(x_pos, y, z_pos)
        glVertex3f(x_pos, y, z)
        glVertex3f(x, y, z_pos)
        glVertex3f(x, y, z)

        glVertex3f(x_pos, y_pos, z_pos)
        glVertex3f(x_pos, y, z_pos)
        glVertex3f(x, y_pos, z_pos)
        glVertex3f(x, y, z_pos)
        glVertex3f(x_pos, y_pos, z)
        glVertex3f(x_pos, y, z)
        glVertex3f(x, y_pos, z)
        glVertex3f(x, y, z)

        glVertex3f(x_pos, y_pos, z_pos)
        glVertex3f(x, y_pos, z_pos)
        glVertex3f(x_pos, y, z_pos)
        glVertex3f(x, y, z_pos)
        glVertex3f(x_pos, y_pos, z)
        glVertex3f(x, y_pos, z)
        glVertex3f(x_pos, y, z)
        glVertex3f(x, y, z)

        glEnd()
