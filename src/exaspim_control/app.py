"""ExASPIM Control application launcher."""

import logging
import sys
import traceback

import click
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from rich.console import Console
from voxel.utils import configure_logging

# from rich.logging import RichHandler
from exaspim_control._qtgui import ExASPIMUI
from exaspim_control._qtgui.assets import APP_ICON
from exaspim_control._qtgui.launcher import LauncherWindow
from exaspim_control.session import Session

configure_logging(logging.INFO)

logger = logging.getLogger(__name__)
console = Console()

# Windows taskbar icon fix: set AppUserModelID before creating any Qt windows
# This ensures Windows groups all application windows together with the correct icon
if sys.platform == "win32":
    import ctypes

    APP_ID = "aind.exaspim-control.1.0"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


@click.command()
@click.argument("session_path", required=False, type=click.Path())
def main(session_path: str | None) -> None:
    """Launch ExASPIM Control.

    SESSION_PATH: Optional path to session directory (pre-fills launcher).
    """
    try:
        # Create single QApplication
        app = QApplication(sys.argv)
        if APP_ICON.exists():
            app.setWindowIcon(QIcon(str(APP_ICON)))

        # Show launcher (with optional pre-filled path from CLI)
        launch_config = LauncherWindow.get_launch_config(initial_path=session_path)
        if launch_config is None:
            console.print("[yellow]No session selected. Exiting.[/yellow]")
            return

        # Launch session (handles file logging setup)
        session = Session.launch(launch_config)

        ui = ExASPIMUI(session=session)
        ui.showMaximized()
        if APP_ICON.exists():
            app.setWindowIcon(QIcon(str(APP_ICON)))

        app.aboutToQuit.connect(lambda: _on_quit(session))
        sys.exit(app.exec())

    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        traceback.print_exc()
        sys.exit(1)


def _on_quit(session: Session) -> None:
    """Handle application shutdown."""
    logger.info("Application shutting down")
    try:
        session.close()
    except Exception:
        logger.exception("Error closing session")


if __name__ == "__main__":
    main()
