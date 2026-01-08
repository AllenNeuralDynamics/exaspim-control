"""ExASPIM Control application launcher."""

import sys

import click

from exaspim_control._qtgui.main import run_app

# Windows taskbar icon fix: set AppUserModelID before creating any Qt windows
# This ensures Windows groups all application windows together with the correct icon
# if sys.platform == "win32":
#     import ctypes

#     APP_ID = "aind.exaspim-control.1.0"
#     ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


@click.command()
@click.argument("session_path", required=False, type=click.Path())
def main(session_path: str | None) -> None:
    """Launch ExASPIM Control.

    SESSION_PATH: Optional path to session directory (pre-fills launcher).
    """

    sys.exit(run_app(initial_path=session_path))


if __name__ == "__main__":
    main()
