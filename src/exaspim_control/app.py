import logging
import sys
import traceback
from datetime import datetime
from logging import FileHandler
from pathlib import Path
from typing import Self

import click
from PyQt6.QtWidgets import QApplication
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from exaspim_control.gui import InstrumentUI
from exaspim_control.instrument import ExASPIM

root_logger = logging.getLogger()
rich_handler = RichHandler(
    rich_tracebacks=True,
    markup=True,
    show_time=True,
    show_level=True,
    show_path=True,
)
root_logger.addHandler(rich_handler)

logger = logging.getLogger(__name__)


class Launcher:
    INSTRUMENTS_DIR = Path(__file__).parent.parent.parent / "instruments"

    def __init__(self, config_path: Path):
        self.config_path = config_path

        # File handler
        log_dir = config_path.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        self.log_filename = log_dir / f"output_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
        fmt = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
        file_handler = FileHandler(self.log_filename, "w")
        file_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt="%Y-%m-%d,%H:%M:%S"))
        root_logger.addHandler(file_handler)

        logger.info(f"Starting ExASPIM Control for instrument: {self.config_path.parent.name}")

        self.instrument = ExASPIM(config_path=self.config_path)

        # View will be created in show() after QApplication is instantiated
        self.instrument_ui = None

    def _cleanup(self) -> None:
        logger.info("Application shutting down - cleaning up resources")
        try:
            self.instrument.close()
        except Exception as e:
            logger.exception(f"Error closing instrument: {e}")

    def show(self, argv=None) -> int:
        """Create QApplication, initialize views, and start the event loop."""
        if argv is None:
            argv = sys.argv

        app = QApplication(argv)
        app.aboutToQuit.connect(self._cleanup)

        self.instrument_ui = InstrumentUI(instrument=self.instrument)

        # Show the main window
        self.instrument_ui.show()

        # Start event loop
        return app.exec()

    @classmethod
    def from_name(cls, instrument_name: str) -> Self:
        available = cls.get_available_instruments()
        if available[instrument_name]:
            config_path = cls.INSTRUMENTS_DIR / instrument_name / "exaspim.yaml"
            return cls(config_path=config_path)
        available_str = ", ".join(f"{name}: {is_valid}" for name, is_valid in available.items())
        msg = f"Attempting to launch an invalid instrument. Dir: {cls.INSTRUMENTS_DIR} Instruments: {available_str}"
        raise RuntimeError(msg)

    @classmethod
    def get_available_instruments(cls) -> dict[str, bool]:
        if not cls.INSTRUMENTS_DIR.exists():
            logger.error(f"Instruments dir: {cls.INSTRUMENTS_DIR} does not exist")
            return {}

        instruments = {}
        for item in cls.INSTRUMENTS_DIR.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                instruments[item.name] = (item / "exaspim.yaml").exists()
        return instruments


console = Console()


@click.command()
@click.option("--list", "-l", "show_list", is_flag=True, help="list all available instruments")
@click.argument("instrument_name", required=False)
def main(show_list: bool, instrument_name: str | None) -> None:
    instruments = Launcher.get_available_instruments()
    if not instruments:
        console.print("[yellow]No instruments found in the instruments/ directory.[/yellow]")
        return
    if show_list:
        table = Table(title="Available ExASPIM Instruments")
        table.add_column("Instrument", style="cyan", no_wrap=True)
        table.add_column("Status", style="green")

        for name, is_valid in sorted(instruments.items()):
            status_display = "[green]✓ Valid[/green]" if is_valid else "[red]✗ Invalid[/red]"
            table.add_row(name, status_display)

        console.print(table)

        if valid_instruments := [name for name, is_valid in instruments.items() if is_valid]:
            console.print("\n[bold]To launch an instrument:[/bold] exaspim <instrument_name>")
            console.print(f"[dim]Example:[/dim] exaspim {valid_instruments[0]}")

    elif instrument_name:
        if instrument_name not in instruments or not instruments[instrument_name]:
            console.print(f"[red]Error: Instrument '{instrument_name}' not found.[/red]")
            console.print("\n[bold]Available instruments:[/bold]")
            for name in sorted(instruments.keys()):
                console.print(f"  - {name}")
            console.print("\n[dim]Use 'exaspim --list' to see detailed status.[/dim]")
            return

        console.print(f"[green]Starting ExASPIM for instrument: {instrument_name}[/green]")

        try:
            app = Launcher.from_name(instrument_name)
            sys.exit(app.show(sys.argv))

        except FileNotFoundError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)
        except (KeyboardInterrupt, SystemExit):
            raise  # Don't catch normal exit or Ctrl+C
        except BaseException as e:
            console.print(f"[red]Unexpected error: {e}[/red]")

            traceback.print_exc()
            sys.exit(1)
    else:
        console.print("[yellow]Usage:[/yellow]")
        console.print("  exaspim --list              list all available instruments")
        console.print("  exaspim <instrument_name>   Launch a specific instrument")
        console.print("\n[dim]Example:[/dim] exaspim beta1")


if __name__ == "__main__":
    main()
