import sys
from pathlib import Path
from typing import TypedDict

import click
from rich.console import Console
from rich.table import Table

from exaspim_control.app import ExASPIMApplication, Launcher

PROJECT_ROOT = Path(__file__).parent.parent.parent
INSTRUMENTS_DIR = PROJECT_ROOT / "instruments"

# UI Mode Toggle: Set to True to use new InstrumentUI, False for classic napari-embedded view
USE_NEW_UI = True


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
        msg = f"Instrument directory not found: {instrument_dir}"
        raise FileNotFoundError(msg)

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
        msg = f"Missing required files in {instrument_dir}: {', '.join(missing_files)}"
        raise FileNotFoundError(msg)

    return acquisition_yaml, instrument_yaml, gui_yaml


def run_instrument(instrument_name: str) -> None:
    """
    Launch the ExASPIM application for the specified instrument.

    :param instrument_name: Name of the instrument directory
    """
    instrument_dir = INSTRUMENTS_DIR / instrument_name

    try:
        # Create and run application (it handles QApplication creation)
        # Toggle between old and new UI based on USE_NEW_UI flag
        if USE_NEW_UI:
            console.print("[cyan]Using new InstrumentUI interface[/cyan]")
            app = Launcher(instrument_dir=instrument_dir, log_level="INFO")
        else:
            console.print("[cyan]Using classic napari-embedded interface[/cyan]")
            app = ExASPIMApplication(instrument_dir=instrument_dir, log_level="INFO")

        sys.exit(app.show(sys.argv))

    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)
    except (KeyboardInterrupt, SystemExit):
        raise  # Don't catch normal exit or Ctrl+C
    except BaseException as e:  # noqa: BLE001
        console.print(f"[red]Unexpected error: {e}[/red]")
        import traceback

        traceback.print_exc()
        sys.exit(1)


@click.command()
@click.option("--list", "-l", "show_list", is_flag=True, help="list all available instruments")
@click.argument("instrument_name", required=False)
def main(show_list: bool, instrument_name: str | None) -> None:
    if show_list:
        list_instruments()
    elif instrument_name:
        launch_instrument(instrument_name)
    else:
        console.print("[yellow]Usage:[/yellow]")
        console.print("  exaspim --list              list all available instruments")
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
        elif isinstance(missing_files, list) and missing_files:
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
    main()
