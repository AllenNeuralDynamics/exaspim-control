"""OpenGL path item with arrow at endpoint."""

import numpy as np
from PyQt6.QtGui import QColor
from pyqtgraph.opengl import GLLinePlotItem


class GLPathItem(GLLinePlotItem):
    """GLLinePlotItem subclass that draws an arrow at the end of the path.

    Used to visualize acquisition paths with a gradient from start to end color.
    """

    def __init__(self, parentItem=None, **kwds):
        super().__init__(parentItem)

        self.arrow_size_percent = kwds.get("arrow_size", 6.0)
        self.arrow_aspect_ratio = kwds.get("arrow_aspect_ratio", 4)
        self.path_start_color = kwds.get("path_start_color", "magenta")
        self.path_end_color = kwds.get("path_end_color", "green")
        self.width = kwds.get("width", 1)

    def setData(self, **kwds):
        """Set path data with automatic arrow generation at endpoint."""
        kwds["width"] = self.width

        if "pos" in kwds:
            path = kwds["pos"]
            # Draw end arrow based on last line segment direction
            if len(path) > 1:
                vector = path[-1] - path[-2]
                if vector[1] > 0:
                    arrow_size = abs(vector[1]) * self.arrow_size_percent / 100
                    x = np.array([
                        path[-1, 0] - arrow_size,
                        path[-1, 0] + arrow_size,
                        path[-1, 0],
                        path[-1, 0] - arrow_size,
                    ])
                    y = np.array([
                        path[-1, 1],
                        path[-1, 1],
                        path[-1, 1] + arrow_size * self.arrow_aspect_ratio,
                        path[-1, 1],
                    ])
                    z = np.array([path[-1, 2], path[-1, 2], path[-1, 2], path[-1, 2]])
                elif vector[1] < 0:
                    arrow_size = abs(vector[1]) * self.arrow_size_percent / 100
                    x = np.array([
                        path[-1, 0] + arrow_size,
                        path[-1, 0] - arrow_size,
                        path[-1, 0],
                        path[-1, 0] + arrow_size,
                    ])
                    y = np.array([
                        path[-1, 1],
                        path[-1, 1],
                        path[-1, 1] - arrow_size * self.arrow_aspect_ratio,
                        path[-1, 1],
                    ])
                    z = np.array([path[-1, 2], path[-1, 2], path[-1, 2], path[-1, 2]])
                elif vector[0] < 0:
                    arrow_size = abs(vector[0]) * self.arrow_size_percent / 100
                    x = np.array([
                        path[-1, 0],
                        path[-1, 0],
                        path[-1, 0] - arrow_size * self.arrow_aspect_ratio,
                        path[-1, 0],
                    ])
                    y = np.array([
                        path[-1, 1] + arrow_size,
                        path[-1, 1] - arrow_size,
                        path[-1, 1],
                        path[-1, 1] + arrow_size,
                    ])
                    z = np.array([path[-1, 2], path[-1, 2], path[-1, 2], path[-1, 2]])
                else:
                    arrow_size = abs(vector[0]) * self.arrow_size_percent / 100
                    x = np.array([
                        path[-1, 0],
                        path[-1, 0],
                        path[-1, 0] + arrow_size * self.arrow_aspect_ratio,
                        path[-1, 0],
                    ])
                    y = np.array([
                        path[-1, 1] - arrow_size,
                        path[-1, 1] + arrow_size,
                        path[-1, 1],
                        path[-1, 1] - arrow_size,
                    ])
                    z = np.array([path[-1, 2], path[-1, 2], path[-1, 2], path[-1, 2]])
                xyz = np.transpose(np.array([x, y, z]))
                kwds["pos"] = np.concatenate((path, xyz), axis=0)

            # Create gradient colors from start to end
            num_tiles = len(path)
            path_gradient = np.zeros((num_tiles, 4))
            for tile in range(num_tiles):
                start = QColor(self.path_start_color).getRgbF()
                end = QColor(self.path_end_color).getRgbF()
                path_gradient[tile, :] = (num_tiles - tile) / num_tiles * np.array(start) + (
                    tile / num_tiles
                ) * np.array(end)
            colors = np.repeat([path_gradient[-1, :]], repeats=4, axis=0)
            kwds["color"] = np.concatenate((path_gradient, colors), axis=0)

        super().setData(**kwds)
