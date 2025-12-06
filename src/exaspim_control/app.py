import logging
import sys
from datetime import datetime
from logging import FileHandler
from pathlib import Path, WindowsPath
from typing import TypedDict

import click
import numpy as np
from qtpy.QtWidgets import QApplication
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from ruamel.yaml import YAML

from exaspim_control.exa_spim_acquisition import ExASPIMAcquisition
from exaspim_control.exa_spim_instrument import ExASPIM
from exaspim_control.exa_spim_view import ExASPIMAcquisitionView, ExASPIMInstrumentView
from exaspim_control.metadata_launch import MetadataLaunch

PROJECT_ROOT = Path(__file__).parent.parent.parent
INSTRUMENTS_DIR = PROJECT_ROOT / "instruments"


class InstrumentInfo(TypedDict):
    valid: bool
    missing_files: list[str]


console = Console()


def get_available_instruments() -> dict[str, dict[str, bool | list[str]]]:
    if not INSTRUMENTS_DIR.exists():
        return {}

    instruments = {}
    required_files = ["acquisition.yaml", "instrument.yaml", "gui_config.yaml"]

    for item in INSTRUMENTS_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            missing_files = []
            for required_file in required_files:
                if not (item / required_file).exists():
                    missing_files.append(required_file)

            instruments[item.name] = {"valid": len(missing_files) == 0, "missing_files": missing_files}

    return instruments


def get_instrument_config_files(instrument_name: str) -> tuple[Path, Path, Path]:
    instrument_dir = INSTRUMENTS_DIR / instrument_name

    if not instrument_dir.exists():
        raise FileNotFoundError(f"Instrument directory not found: {instrument_dir}")

    acquisition_yaml = instrument_dir / "acquisition.yaml"
    instrument_yaml = instrument_dir / "instrument.yaml"
    gui_yaml = instrument_dir / "gui_config.yaml"

    missing_files = []
    if not instrument_yaml.exists():
        missing_files.append("instrument.yaml")
    if not acquisition_yaml.exists():
        missing_files.append("acquisition.yaml")
    if not gui_yaml.exists():
        missing_files.append("gui_config.yaml")

    if missing_files:
        raise FileNotFoundError(f"Missing required files in {instrument_dir}: {', '.join(missing_files)}")

    return acquisition_yaml, instrument_yaml, gui_yaml


def run_instrument(instrument_name: str) -> None:
    try:
        ACQUISITION_YAML, INSTRUMENT_YAML, GUI_YAML = get_instrument_config_files(instrument_name)
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    logger = logging.getLogger()
    logging.getLogger().handlers.clear()
    logger.setLevel(logging.DEBUG)

    instrument_dir = INSTRUMENTS_DIR / instrument_name
    log_filename = instrument_dir / f"output_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"

    fmt = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
    datefmt = "%Y-%m-%d,%H:%M:%S"
    log_formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    file_handler = FileHandler(log_filename, "w")
    file_handler.setLevel("INFO")
    file_handler.setFormatter(log_formatter)

    rich_handler = RichHandler(
        rich_tracebacks=True,
        markup=True,
        show_time=True,
        show_level=True,
        show_path=False,
    )
    rich_handler.setLevel("INFO")

    logger.addHandler(file_handler)
    logger.addHandler(rich_handler)

    logger.info(f"Starting ExASPIM Control for instrument: {instrument_name}")
    logger.info(f"Configuration files loaded from: {instrument_dir}")

    app = QApplication(sys.argv)

    yaml = YAML()
    yaml.representer.add_representer(np.int64, lambda obj, val: obj.represent_int(int(val)))
    yaml.representer.add_representer(np.int32, lambda obj, val: obj.represent_int(int(val)))
    yaml.representer.add_representer(np.str_, lambda obj, val: obj.represent_str(str(val)))
    yaml.representer.add_representer(np.float64, lambda obj, val: obj.represent_float(float(val)))
    yaml.representer.add_representer(Path, lambda obj, val: obj.represent_str(str(val)))
    yaml.representer.add_representer(WindowsPath, lambda obj, val: obj.represent_str(str(val)))

    instrument = ExASPIM(config_filename=str(INSTRUMENT_YAML), yaml_handler=yaml, log_level="INFO")
    acquisition = ExASPIMAcquisition(
        instrument=instrument,
        config_filename=str(ACQUISITION_YAML),
        yaml_handler=yaml,
        log_level="INFO",
    )
    instrument_view = ExASPIMInstrumentView(instrument, GUI_YAML, log_level="INFO")
    acquisition_view = ExASPIMAcquisitionView(acquisition, instrument_view)

    MetadataLaunch(
        instrument=instrument,
        acquisition=acquisition,
        instrument_view=instrument_view,
        acquisition_view=acquisition_view,
        log_filename=str(log_filename),
    )

    sys.exit(app.exec())


@click.command()
@click.option("--list", "-l", "show_list", is_flag=True, help="List all available instruments")
@click.argument("instrument_name", required=False)
def cli(show_list: bool, instrument_name: str | None) -> None:
    if show_list:
        list_instruments()
    elif instrument_name:
        launch_instrument(instrument_name)
    else:
        console.print("[yellow]Usage:[/yellow]")
        console.print("  exaspim --list              List all available instruments")
        console.print("  exaspim <instrument_name>   Launch a specific instrument")
        console.print("\n[dim]Example:[/dim] exaspim beta1")


def list_instruments() -> None:
    instruments = get_available_instruments()

    if not instruments:
        console.print("[yellow]No instruments found in the instruments/ directory.[/yellow]")
        return

    table = Table(title="Available ExASPIM Instruments")
    table.add_column("Instrument", style="cyan", no_wrap=True)
    table.add_column("Status", style="green")

    for name, info in sorted(instruments.items()):
        is_valid = info["valid"]
        missing_files = info["missing_files"]

        if is_valid:
            status_display = "[green]✓ Valid[/green]"
        else:
            if isinstance(missing_files, list) and missing_files:
                missing_list = ", ".join(missing_files)
                status_display = f"[red]✗ Missing: {missing_list}[/red]"
            else:
                status_display = "[red]✗ Invalid[/red]"

        table.add_row(name, status_display)

    console.print(table)

    valid_instruments = [name for name, info in instruments.items() if info["valid"]]
    if valid_instruments:
        console.print("\n[bold]To launch an instrument:[/bold] exaspim <instrument_name>")
        console.print(f"[dim]Example:[/dim] exaspim {valid_instruments[0]}")


def launch_instrument(instrument_name: str) -> None:
    instruments = get_available_instruments()

    if instrument_name not in instruments:
        console.print(f"[red]Error: Instrument '{instrument_name}' not found.[/red]")
        console.print("\n[bold]Available instruments:[/bold]")
        for name in sorted(instruments.keys()):
            console.print(f"  - {name}")
        console.print("\n[dim]Use 'exaspim --list' to see detailed status.[/dim]")
        return

    if not instruments[instrument_name]["valid"]:
        missing_files_list = instruments[instrument_name]["missing_files"]
        console.print(f"[red]Error: Instrument '{instrument_name}' is missing required configuration files:[/red]")
        if isinstance(missing_files_list, list):
            for missing in missing_files_list:
                console.print(f"  - {missing}")
        return

    console.print(f"[green]Starting ExASPIM for instrument: {instrument_name}[/green]")
    run_instrument(instrument_name)


if __name__ == "__main__":
    cli()
