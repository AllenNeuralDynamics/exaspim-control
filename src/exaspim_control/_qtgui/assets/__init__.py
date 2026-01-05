"""Asset paths for icons and images."""

from pathlib import Path

_ASSETS_DIR = Path(__file__).parent

# Application icon
APP_ICON = _ASSETS_DIR / "voxel-logo.png"

# UI icons
ICON_ARROW_LEFT = _ASSETS_DIR / "arrow-left.svg"
ICON_ARROW_RIGHT = _ASSETS_DIR / "arrow-right.svg"
ICON_REFRESH = _ASSETS_DIR / "refresh.svg"

__all__ = [
    "APP_ICON",
    "ICON_ARROW_LEFT",
    "ICON_ARROW_RIGHT",
    "ICON_REFRESH",
]
