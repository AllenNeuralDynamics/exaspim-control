"""Consolidated color palette for the ExA-SPIM Control application.

This module provides a consistent set of colors used throughout the UI.
All colors follow a dark theme inspired by VS Code's dark+ theme.

Usage:
    from exaspim_control._qtgui.primitives.colors import Colors

    widget.setStyleSheet(f"background-color: {Colors.BG_DARK};")
"""


class Colors:
    """Application color palette.

    Naming convention:
    - BG_* : Background colors (dark to light)
    - BORDER_* : Border colors
    - TEXT_* : Text colors
    - ACCENT_* : Accent/highlight colors
    - STATUS_* : Status indicator colors
    """

    # Backgrounds (dark to light)
    BG_DARK = "#1e1e1e"  # Main background
    BG_MEDIUM = "#252526"  # Cards, panels
    BG_LIGHT = "#2d2d30"  # Elevated surfaces, hover states

    # Borders
    BORDER = "#3c3c3c"  # Default border
    BORDER_LIGHT = "#4a4a4a"  # Subtle borders
    BORDER_FOCUS = "#505050"  # Focused input borders

    # Text
    TEXT = "#d4d4d4"  # Primary text
    TEXT_BRIGHT = "#ffffff"  # Emphasized text
    TEXT_MUTED = "#888888"  # Secondary/hint text
    TEXT_DISABLED = "#6e6e6e"  # Disabled text

    # Accent (primary action color)
    ACCENT = "#3a6ea5"  # Primary accent (blue)
    ACCENT_HOVER = "#4a7eb5"  # Accent hover state
    ACCENT_BRIGHT = "#0078d4"  # Bright accent for active states

    # Status colors
    SUCCESS = "#4ec9b0"  # Success/valid (teal)
    WARNING = "#ffb74d"  # Warning (orange)
    ERROR = "#f44336"  # Error/danger (red)
    ERROR_BRIGHT = "#ff1744"  # Critical error

    # Interactive states
    HOVER = "#4a4a4d"  # Generic hover background
    PRESSED = "#2d2d30"  # Pressed state
    SELECTED = "#0078d4"  # Selected item background
