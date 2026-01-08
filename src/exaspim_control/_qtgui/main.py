"""ExASPIM Control Application with stacked widget navigation.

The application flows through three pages:
1. LaunchPage - Session directory and instrument selection
2. LoadingPage - Session initialization with progress and logs
3. MainPage - Main application content (controls, viewers, etc.)
"""

from __future__ import annotations

import contextlib
import logging
from concurrent.futures import ThreadPoolExecutor
from enum import IntEnum

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPalette
from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget
from voxel.utils import configure_logging

from exaspim_control._qtgui.assets import APP_ICON
from exaspim_control._qtgui.pages import LaunchPage, LoadingPage, MainPage, NapariWindow
from exaspim_control._qtgui.primitives import Colors
from exaspim_control.session import LaunchConfig, Session


class Page(IntEnum):
    """Page indices for the stacked widget."""

    LAUNCH = 0
    LOADING = 1
    MAIN = 2


class _SessionLoader(QObject):
    """Background loader for Session initialization.

    Emits signals for thread-safe communication with the UI.
    """

    finished = pyqtSignal(Session)  # Emitted with initialized session
    failed = pyqtSignal(str)  # Emitted with error message
    progress = pyqtSignal(str)  # Status updates

    def __init__(self, config: LaunchConfig, parent: QObject | None = None):
        super().__init__(parent)
        self._config = config
        self._session: Session | None = None

    def load(self) -> None:
        """Load the session (called from thread pool)."""
        try:
            self.progress.emit("Launching session...")
            self._session = Session.launch(self._config)
            self.finished.emit(self._session)
        except Exception as e:
            self.failed.emit(str(e))


class ExASPIMApp(QMainWindow):
    """Main application window with stacked page navigation.

    Manages the flow: LaunchPage → LoadingPage → MainPage
    """

    def __init__(self, initial_path: str | None = None):
        super().__init__()

        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        self._session: Session | None = None
        self._main_page: MainPage | None = None
        self._napari_window: NapariWindow | None = None
        self._napari_action: QAction | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)

        # Stacked widget for page navigation
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # Create pages
        self._launch_page = LaunchPage(initial_path=initial_path)
        self._loading_page = LoadingPage()
        # MainPage is created after session initialization

        # Add pages to stack
        self._stack.addWidget(self._launch_page)  # Index 0
        self._stack.addWidget(self._loading_page)  # Index 1
        # MainPage added at index 2 when created

        # Connect signals
        self._launch_page.launchRequested.connect(self._on_launch_requested)
        self._launch_page.cancelRequested.connect(self.close)
        self._loading_page.cancelRequested.connect(self._on_loading_cancelled)

        # Setup window
        self._setup_window()

        self.log.info("ExASPIMApp initialized")

    def _setup_window(self) -> None:
        """Configure main window properties."""
        self.setWindowTitle("ExA-SPIM Control")
        self.setMinimumSize(1200, 800)

        if APP_ICON.exists():
            self.setWindowIcon(QIcon(str(APP_ICON)))

        # Start with launch page styling (dark)
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {Colors.BG_DARK};
            }}
        """)

    def _setup_menu_bar(self) -> None:
        """Create menu bar (called after session is loaded)."""
        menu_bar = self.menuBar()
        if menu_bar is None:
            return

        # File menu
        file_menu = menu_bar.addMenu("&File")
        if file_menu is not None:
            # Save Session action
            save_action = QAction("&Save Session", self)
            save_action.setShortcut("Ctrl+S")
            save_action.triggered.connect(self._on_save_session)
            file_menu.addAction(save_action)

            file_menu.addSeparator()

            # Exit action
            exit_action = QAction("E&xit", self)
            exit_action.setShortcut("Ctrl+Q")
            exit_action.triggered.connect(self.close)
            file_menu.addAction(exit_action)

        # View menu
        view_menu = menu_bar.addMenu("&View")
        if view_menu is not None:
            # Napari viewer action
            self._napari_action = QAction("Open &Napari Viewer", self)
            self._napari_action.setShortcut("Ctrl+N")
            self._napari_action.setCheckable(True)
            self._napari_action.triggered.connect(self._on_toggle_napari)
            view_menu.addAction(self._napari_action)

    def _on_launch_requested(self, config: LaunchConfig) -> None:
        """Handle launch request from LaunchPage."""
        self.log.info(f"Launch requested: {config}")

        # Switch to loading page
        self._stack.setCurrentIndex(Page.LOADING)
        self._loading_page.start()
        self._loading_page.set_status(f"Initializing session from {config.session_dir}...")

        # Start background loading
        self._loader = _SessionLoader(config, parent=self)
        self._loader.finished.connect(self._on_session_loaded)
        self._loader.failed.connect(self._on_session_load_failed)
        self._loader.progress.connect(self._loading_page.set_status)

        self._executor.submit(self._loader.load)

    def _on_session_loaded(self, session: Session) -> None:
        """Handle successful session initialization."""
        self.log.info(f"Session loaded: {session.directory}")

        self._session = session
        self._loading_page.set_status("Creating UI...")

        # Create main page with the session
        # Use QTimer to ensure we're on the main thread
        QTimer.singleShot(0, self._create_main_page)

    def _create_main_page(self) -> None:
        """Create and show the main page."""
        if self._session is None:
            return

        try:
            self._main_page = MainPage(session=self._session, parent=self)
            self._stack.addWidget(self._main_page)

            # Stop loading page
            self._loading_page.stop()

            # Setup menu bar now that we have a session
            self._setup_menu_bar()

            # Switch to main page
            self._stack.setCurrentIndex(Page.MAIN)

            # Update window title
            self.setWindowTitle(f"ExA-SPIM Control - {self._session.directory.name}")

            self.log.info("Switched to main page")

        except Exception as e:
            self.log.exception("Failed to create main page")
            self._on_session_load_failed(str(e))

    def _on_session_load_failed(self, error: str) -> None:
        """Handle session initialization failure."""
        self.log.error(f"Session load failed: {error}")
        self._loading_page.set_error(error)
        # Stay on loading page so user can see the error and logs

    def _on_loading_cancelled(self) -> None:
        """Handle cancel during loading."""
        self.log.info("Loading cancelled")
        self._loading_page.stop()
        self._stack.setCurrentIndex(Page.LAUNCH)

        # Clean up any partial session
        if self._session is not None:
            with contextlib.suppress(Exception):
                self._session.close()
            self._session = None

    def _on_save_session(self) -> None:
        """Save session state."""
        if self._main_page is not None:
            self._main_page.save_session()

    def _on_toggle_napari(self, checked: bool) -> None:
        """Toggle napari viewer visibility."""
        if checked:
            self._open_napari()
        else:
            self._close_napari()

    def _open_napari(self) -> None:
        """Open/show the napari viewer (creates on first call)."""
        if self._main_page is None or self._session is None:
            return

        if self._napari_window is None:
            # Create napari window (lazy initialization)
            self._napari_window = NapariWindow(
                title=f"Live: {self._session.instrument.camera.uid}",
                image_rotation_deg=-self._session.instrument.cfg.globals.camera_rotation_deg,
                parent=self,
            )
            # Connect frame routing from LiveViewer
            self._main_page.live_viewer.frameReceived.connect(
                self._napari_window.update_frame
            )
            # Sync menu checkbox with napari visibility
            self._napari_window.visibilityChanged.connect(self._on_napari_visibility_changed)
            self.log.info("Napari window created")

        self._napari_window.show()

    def _close_napari(self) -> None:
        """Hide the napari viewer."""
        if self._napari_window is not None:
            self._napari_window.hide()

    def _on_napari_visibility_changed(self, visible: bool) -> None:
        """Sync menu checkbox when napari visibility changes externally."""
        if self._napari_action is not None:
            self._napari_action.blockSignals(True)
            self._napari_action.setChecked(visible)
            self._napari_action.blockSignals(False)

    def closeEvent(self, a0) -> None:
        """Handle window close."""
        self.log.info("Closing ExASPIMApp")

        # Close napari window
        if self._napari_window is not None:
            self._napari_window.close()
            self._napari_window = None

        # Cleanup main page
        if self._main_page is not None:
            self._main_page.cleanup()

        # Close session
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                self.log.exception("Error closing session")

        # Shutdown executor
        self._executor.shutdown(wait=False)

        super().closeEvent(a0)


def run_app(initial_path: str | None = None) -> int:
    """Run the ExA-SPIM Control application.

    Args:
        initial_path: Optional initial session directory path

    Returns:
        Exit code
    """
    # Configure logging with Rich handler for console output
    configure_logging(logging.INFO)

    app = QApplication([])
    app.setStyle("Fusion")

    # Apply dark palette using design system tokens
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(Colors.BG_DARK))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(Colors.TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(Colors.BG_LIGHT))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(Colors.BG_MEDIUM))
    palette.setColor(QPalette.ColorRole.Text, QColor(Colors.TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(Colors.BORDER))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(Colors.TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(Colors.ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(Colors.TEXT_BRIGHT))
    app.setPalette(palette)

    window = ExASPIMApp(initial_path=initial_path)
    window.showMaximized()

    return app.exec()
