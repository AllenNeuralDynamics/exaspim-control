"""Session: runtime session with live instrument and automatic persistence."""

import json
import logging
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from exaspim_control.instrument.instrument import Instrument
from exaspim_control.state import SessionState

logger = logging.getLogger(__name__)


@dataclass
class LaunchConfig:
    """Configuration for launching a session."""

    session_dir: Path
    instrument: str = "_existing_"  # Use SessionValues.EXISTING_CONFIG or instrument name
    fresh_state: bool = False  # If True, backup existing state and start fresh


@dataclass
class DirectoryInfo:
    """What exists in a session directory."""

    has_config: bool
    has_state: bool
    config_path: Path
    state_path: Path


class SessionError(Exception):
    """Session-related errors."""


class SessionValues:
    """Shared constants for session management."""

    CONFIG_FILENAME = "exaspim.yaml"
    STATE_FILENAME = "exaspim.state.json"
    INSTRUMENTS_DIR = Path(__file__).parent.parent.parent / "instruments"
    EXISTING_CONFIG = "_existing_"  # Sentinel for using existing config


class InstrumentTemplates:
    """Manages instrument configuration templates.

    Provides access to pre-configured instrument templates that can be
    copied to session directories.
    """

    @classmethod
    def list(cls) -> dict[str, bool]:
        """List available instrument templates.

        Returns:
            Dict mapping instrument name to whether it has a valid config file.
        """
        if not SessionValues.INSTRUMENTS_DIR.exists():
            logger.warning(f"Instruments directory not found: {SessionValues.INSTRUMENTS_DIR}")
            return {}

        instruments = {}
        for item in SessionValues.INSTRUMENTS_DIR.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                instruments[item.name] = (item / SessionValues.CONFIG_FILENAME).exists()
        return instruments

    @classmethod
    def exists(cls, name: str) -> bool:
        """Check if an instrument template exists with valid config.

        Args:
            name: Instrument name.

        Returns:
            True if instrument exists and has a config file.
        """
        available = cls.list()
        return available.get(name, False)

    @classmethod
    def get_config_path(cls, name: str) -> Path:
        """Get path to an instrument's config file.

        Args:
            name: Instrument name.

        Returns:
            Path to the instrument's config file.

        Raises:
            KeyError: If instrument not found or has no config.
        """
        if not cls.exists(name):
            msg = f"Instrument template not found: {name}"
            raise KeyError(msg)
        return SessionValues.INSTRUMENTS_DIR / name / SessionValues.CONFIG_FILENAME

    @classmethod
    def copy_config(cls, name: str, dest_dir: Path) -> Path:
        """Copy instrument config to destination directory.

        Args:
            name: Instrument name.
            dest_dir: Destination directory.

        Returns:
            Path to the copied config file.

        Raises:
            KeyError: If instrument not found or has no config.
        """
        src = cls.get_config_path(name)  # Raises KeyError if not found
        dest_dir.mkdir(parents=True, exist_ok=True)
        dst = dest_dir / SessionValues.CONFIG_FILENAME
        shutil.copy2(src, dst)
        logger.info(f"Copied instrument config: {name} -> {dst}")
        return dst


class Session:
    """Runtime session with live instrument and automatic persistence."""

    AUTOSAVE_INTERVAL_SEC = 30

    def __init__(self, session_dir: Path | str):
        """Initialize session.

        Loads existing state if found, otherwise creates fresh state.

        Args:
            session_dir: Path to session directory containing exaspim.yaml.
        """
        self._session_dir = Path(session_dir)
        self._setup_file_logging(log_dir=self._session_dir / "logs")

        self._state: SessionState = self._load_state(self.state_path)
        self._instrument: Instrument = Instrument(config_path=self.config_path)

        # Autosave state
        self._running = True
        self._save_lock = threading.Lock()

        # Start autosave thread
        self._autosave_thread = threading.Thread(
            target=self._autosave_loop,
            daemon=True,
            name="session-autosave",
        )
        self._autosave_thread.start()

    # ===== Properties =====
    @property
    def directory(self) -> Path:
        return self._session_dir

    @property
    def config_path(self) -> Path:
        return self._session_dir / SessionValues.CONFIG_FILENAME

    @property
    def state_path(self) -> Path:
        return self._session_dir / SessionValues.STATE_FILENAME

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def instrument(self) -> Instrument:
        return self._instrument

    # ===== Autosave =====

    def _autosave_loop(self) -> None:
        """Background thread that periodically saves state."""
        while self._running:
            time.sleep(self.AUTOSAVE_INTERVAL_SEC)
            if self._running:
                with self._save_lock:
                    self._save_state_internal()

    def _save_state_internal(self) -> None:
        """Internal save implementation (no locking)."""
        self._state.touch()
        self._session_dir.mkdir(parents=True, exist_ok=True)

        try:
            with self.state_path.open("w") as f:
                json.dump(self._state.model_dump(mode="json"), f, indent=2, default=str)
            logger.debug(f"Saved session state to {self.state_path}")
        except Exception:
            logger.exception("Failed to save state")

    def save_state(self) -> None:
        """Manually trigger state save."""
        with self._save_lock:
            self._save_state_internal()

    # ===== Lifecycle =====

    def close(self) -> None:
        """Stop autosave, save final state, and close instrument."""
        logger.info(f"Closing session: {self._session_dir}")

        self._running = False
        self.save_state()

        if self._instrument is not None:
            try:
                self._instrument.close()
            except Exception:
                logger.exception("Error closing instrument")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @classmethod
    def inspect_directory(cls, session_dir: Path | str) -> DirectoryInfo:
        """Check what config/state files exist in a directory.

        Args:
            session_dir: Directory path to inspect.

        Returns:
            DirectoryInfo with has_config, has_state, and file paths.
        """
        directory = Path(session_dir)
        config_path = directory / SessionValues.CONFIG_FILENAME
        state_path = directory / SessionValues.STATE_FILENAME

        return DirectoryInfo(
            has_config=config_path.exists(),
            has_state=state_path.exists(),
            config_path=config_path,
            state_path=state_path,
        )

    @classmethod
    def launch(cls, cfg: LaunchConfig) -> Self:
        """Create and launch a session from configuration.

        This is the primary way to create a Session. It handles:
        - Copying instrument config if needed
        - Backing up state if fresh_state requested
        - Creating the session directory if needed

        Args:
            cfg: Launch configuration with:
                - session_dir: Target directory for session
                - instrument: Instrument name to copy config from,
                    or "_existing_" to use existing config
                - fresh_state: If True, backup and reset state

        Returns:
            Initialized Session ready for use.

        Raises:
            SessionError: If config is missing or instrument not found.
        """
        session_dir = Path(cfg.session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)

        # Handle state first (before any config changes)
        if cfg.fresh_state:
            cls._backup_state_file(session_dir)

        # Handle config
        if cfg.instrument != SessionValues.EXISTING_CONFIG:
            try:
                InstrumentTemplates.copy_config(cfg.instrument, session_dir)
            except KeyError as e:
                raise SessionError(str(e)) from e
        else:
            config_path = session_dir / SessionValues.CONFIG_FILENAME
            if not config_path.exists():
                msg = f"No {SessionValues.CONFIG_FILENAME} in {session_dir}."
                raise SessionError(msg)

        logger.info(f"Launching session: {session_dir}")
        return cls(session_dir)

    @staticmethod
    def _load_state(state_path: Path) -> SessionState:
        """Load session state from JSON file.

        Args:
            state_path: Path to state file.

        Returns:
            SessionState loaded from file, or fresh state if file missing/corrupt.
        """
        logger.info(f"Loading session state from {state_path}")
        if not state_path.exists():
            logger.info("No state file found, creating new state")
            return SessionState()

        try:
            with state_path.open("r") as f:
                data = json.load(f)
            return SessionState.model_validate(data)
        except Exception as e:
            logger.warning(f"Failed to load state file: {e}")
            # Backup corrupt file
            backup_path = state_path.with_suffix(".json.corrupt")
            try:
                shutil.copy2(state_path, backup_path)
                logger.info(f"Backed up corrupt state to {backup_path}")
            except Exception:
                logger.exception("Failed to backup corrupt state file")
            return SessionState()

    @classmethod
    def _backup_state_file(cls, session_dir: Path) -> None:
        """Backup existing state file if it exists."""
        state_path = session_dir / SessionValues.STATE_FILENAME
        if state_path.exists():
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = state_path.with_suffix(f".{timestamp}.backup.json")
            shutil.copy2(state_path, backup_path)
            state_path.unlink()
            logger.info(f"Backed up state file to {backup_path}")

    @staticmethod
    def _setup_file_logging(log_dir: Path) -> None:
        """Set up file logging in session's logs directory."""
        log_dir.mkdir(exist_ok=True)

        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        log_file = log_dir / f"session_{timestamp}.log"

        fmt = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
        file_handler = logging.FileHandler(log_file, mode="w")
        file_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt="%Y-%m-%d,%H:%M:%S"))

        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)

        logger.info(f"File logging enabled: {log_file}")
