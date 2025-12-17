from collections.abc import Callable
from typing import NotRequired, TypedDict

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QPushButton


class ToggleButtonState(TypedDict):
    """Configuration for a toggle button state."""

    label: str  # Required
    background: NotRequired[tuple[int, int, int] | None]
    foreground: NotRequired[tuple[int, int, int] | None]
    on_enter: NotRequired[Callable[[], None] | None]


class ToggleButton(QPushButton):
    """QPushButton that toggles between two states with configurable labels, colors, and callbacks."""

    def __init__(
        self,
        unchecked_state: ToggleButtonState | str,
        checked_state: ToggleButtonState | str,
        parent=None,
    ):
        """
        Initialize the toggle button with two configurable states.

        :param unchecked_state: Configuration for unchecked state (dict or string label)
        :type unchecked_state: ToggleButtonState | str
        :param checked_state: Configuration for checked state (dict or string label)
        :type checked_state: ToggleButtonState | str
        :param parent: Parent widget, defaults to None
        :type parent: QWidget, optional

        Example:
            # Simple usage with strings
            button = ToggleButton("Unchecked", "Checked")

            # Advanced usage with dicts
            button = ToggleButton(
                unchecked_state={
                    "label": "Open Window",
                    "background": (52, 152, 219),  # Blue
                    "foreground": (255, 255, 255),  # White
                    "on_enter": lambda: print("Entering unchecked state")
                },
                checked_state={
                    "label": "Close Window",
                    "background": (231, 76, 60),  # Red
                    "foreground": (255, 255, 255),  # White
                    "on_enter": lambda: print("Entering checked state")
                }
            )
        """
        super().__init__(parent)

        # Normalize states to dicts
        self.unchecked_state = self._normalize_state(unchecked_state)
        self.checked_state = self._normalize_state(checked_state)

        # Make button checkable and set initial state
        self.setCheckable(True)
        self.setChecked(False)

        # Apply initial state
        self._update_state(False)

        # Connect to toggled signal to update state
        self.toggled.connect(self._update_state)

    def _normalize_state(self, state: ToggleButtonState | str) -> ToggleButtonState:
        """
        Normalize state to dict format.

        :param state: State configuration (dict or string)
        :return: Normalized state dict
        """
        if isinstance(state, str):
            return {"label": state}
        return state

    def _update_state(self, checked: bool) -> None:
        """
        Update button appearance and execute callback based on checked state.

        :param checked: Whether button is checked
        :type checked: bool
        """
        state = self.checked_state if checked else self.unchecked_state

        # Update label
        self.setText(state["label"])

        # Update colors if specified
        bg = state.get("background")
        fg = state.get("foreground")

        if bg or fg:
            bg_str = f"rgb({bg[0]}, {bg[1]}, {bg[2]})" if bg else "none"
            fg_str = f"rgb({fg[0]}, {fg[1]}, {fg[2]})" if fg else "inherit"

            style = f"""
                QPushButton {{
                    background-color: {bg_str};
                    color: {fg_str};
                    font-weight: bold;
                    padding: 8px 16px;
                    border-radius: 4px;
                    border: 2px solid {bg_str};
                }}
                QPushButton:hover {{
                    border: 2px solid {'rgba(255, 255, 255, 0.3)' if bg else 'gray'};
                }}
            """
            self.setStyleSheet(style)

        # Execute on_enter callback if specified
        on_enter = state.get("on_enter")
        if on_enter:
            on_enter()
