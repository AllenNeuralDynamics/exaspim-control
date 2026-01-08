"""Page components for the stacked widget application.

Pages:
- LaunchPage: Session directory and instrument selection
- LoadingPage: Initialization progress with spinner and logs
- MainPage: Main application content (controls, viewers, etc.)
- NapariWindow: Standalone napari viewer (lazy-initialized)
"""

from exaspim_control._qtgui.pages.launch_page import LaunchPage
from exaspim_control._qtgui.pages.loading_page import LoadingPage
from exaspim_control._qtgui.pages.main_page import MainPage
from exaspim_control._qtgui.pages.napari_window import NapariWindow

__all__ = ["LaunchPage", "LoadingPage", "MainPage", "NapariWindow"]
