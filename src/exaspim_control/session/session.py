"""Session: runtime session with live instrument and automatic persistence."""

import json
import logging
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from exaspim_control.config import InstrumentConfig
from exaspim_control.instrument import Instrument
from exaspim_control.session.plan import AcqPlan
from exaspim_control.session.state import SessionState

logger = logging.getLogger(__name__)


class SessionError(Exception):
    """Session-related errors."""


class Session:
    """Runtime session with live instrument and automatic persistence.

    Session automatically saves state periodically and when closed.
    Use SessionLauncher to create or open sessions.
    """

    CONFIG_FILENAME = "exaspim.yaml"
    STATE_FILENAME = "exaspim.state.json"
    AUTOSAVE_INTERVAL_SEC = 30

    def __init__(self, session_dir: Path | str):
        """Initialize session.

        Loads existing state if found, otherwise creates fresh state.

        Args:
            session_dir: Path to session directory containing exaspim.yaml.
        """
        self._session_dir = Path(session_dir)
        self._state: SessionState = self._load_state()
        self._config: InstrumentConfig = InstrumentConfig.from_yaml(self.config_path)
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
    def session_dir(self) -> Path:
        return self._session_dir

    @property
    def config_path(self) -> Path:
        return self._session_dir / self.CONFIG_FILENAME

    @property
    def state_path(self) -> Path:
        return self._session_dir / self.STATE_FILENAME

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def plan(self) -> AcqPlan:
        return self._state.plan

    @property
    def instrument(self) -> Instrument:
        return self._instrument

    def _load_state(self) -> SessionState:
        """Load state from file if exists, otherwise create new."""
        logger.info(f"Loading session state from {self.state_path}")
        if not self.state_path.exists():
            logger.info("No state file found, creating new state")
            return SessionState()

        try:
            with self.state_path.open("r") as f:
                data = json.load(f)
            return SessionState.model_validate(data)
        except Exception as e:
            logger.warning(f"Failed to load state file: {e}")
            # Backup corrupt file
            backup_path = self.state_path.with_suffix(".json.corrupt")
            try:
                shutil.copy2(self.state_path, backup_path)
                logger.info(f"Backed up corrupt state to {backup_path}")
            except Exception:
                logger.exception("Failed to backup corrupt state file")
            return SessionState()

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

    def save_now(self) -> None:
        """Force immediate save (alias for save_state)."""
        self.save_state()

    # ===== Lifecycle =====

    def close(self) -> None:
        """Stop autosave, save final state, and close instrument."""
        logger.info(f"Closing session: {self._session_dir}")

        # Stop autosave thread
        self._running = False

        # Final save
        self.save_state()

        # Close instrument
        if self._instrument is not None:
            try:
                self._instrument.close()
            except Exception:
                logger.exception("Error closing instrument")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


@dataclass
class LaunchConfig:
    """Configuration for launching a session."""

    session_dir: Path
    instrument: str | None = None  # None means use local config
    clean_state: bool = False


class SessionLauncher:
    """Handles session discovery, creation, and launch.

    Responsibilities:
    - List available instruments
    - Launch sessions (create new or open existing)
    - Set up file logging in session directory
    - Handle clean state scenarios (backup old state)
    """

    CONFIG_FILENAME = "exaspim.yaml"
    STATE_FILENAME = "exaspim.state.json"
    INSTRUMENTS_DIR = Path(__file__).parent.parent.parent.parent / "instruments"

    @classmethod
    def available_instruments(cls) -> dict[str, bool]:
        """Returns {name: has_config} for instruments in instruments/ directory."""
        if not cls.INSTRUMENTS_DIR.exists():
            logger.warning(f"Instruments directory not found: {cls.INSTRUMENTS_DIR}")
            return {}

        instruments = {}
        for item in cls.INSTRUMENTS_DIR.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                instruments[item.name] = (item / cls.CONFIG_FILENAME).exists()
        return instruments

    @classmethod
    def launch(cls, cfg: LaunchConfig) -> Session:
        """Launch a session from configuration.

        Args:
            cfg: Launch configuration specifying session directory and options.
                - If cfg.instrument is None: opens existing session (config must exist)
                - If cfg.instrument is set: creates session from instrument template

        Returns:
            Initialized Session with file logging configured.

        Raises:
            SessionError: If session cannot be created or opened.
        """
        session_dir = Path(cfg.session_dir)

        # Handle clean state before anything else
        if cfg.clean_state:
            cls._backup_state_file(session_dir)

        if cfg.instrument is not None:
            # Create new session from instrument template
            cls._create_from_instrument(cfg.instrument, session_dir)
        else:
            # Open existing session - validate config exists
            cls._validate_existing_session(session_dir)

        # Set up file logging before creating session
        cls._setup_file_logging(session_dir)

        logger.info(f"Launching session: {session_dir}")
        return Session(session_dir)

    @classmethod
    def _create_from_instrument(cls, instrument_name: str, session_dir: Path) -> None:
        """Prepare session directory from instrument template."""
        available = cls.available_instruments()
        if instrument_name not in available:
            msg = f"Unknown instrument: {instrument_name}"
            raise SessionError(msg)
        if not available[instrument_name]:
            msg = f"Instrument '{instrument_name}' has no {cls.CONFIG_FILENAME}"
            raise SessionError(msg)

        session_dir.mkdir(parents=True, exist_ok=True)

        # Copy instrument config
        src = cls.INSTRUMENTS_DIR / instrument_name / cls.CONFIG_FILENAME
        dst = session_dir / cls.CONFIG_FILENAME
        shutil.copy2(src, dst)
        logger.info(f"Copied instrument config from {src} to {dst}")

    @classmethod
    def _validate_existing_session(cls, session_dir: Path) -> None:
        """Validate that session directory has required config."""
        if not session_dir.exists():
            msg = f"Session directory not found: {session_dir}"
            raise SessionError(msg)

        config_path = session_dir / cls.CONFIG_FILENAME
        if not config_path.exists():
            msg = f"No {cls.CONFIG_FILENAME} in {session_dir}. Specify an instrument to create a new session."
            raise SessionError(msg)

    @classmethod
    def _setup_file_logging(cls, session_dir: Path) -> None:
        """Set up file logging in session's logs directory."""
        log_dir = session_dir / "logs"
        log_dir.mkdir(exist_ok=True)

        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        log_file = log_dir / f"session_{timestamp}.log"

        fmt = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
        file_handler = logging.FileHandler(log_file, mode="w")
        file_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt="%Y-%m-%d,%H:%M:%S"))

        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)

        logger.info(f"File logging enabled: {log_file}")

    @classmethod
    def _backup_state_file(cls, session_dir: Path) -> None:
        """Backup existing state file if it exists."""
        state_path = session_dir / cls.STATE_FILENAME
        if state_path.exists():
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = state_path.with_suffix(f".{timestamp}.backup.json")
            shutil.copy2(state_path, backup_path)
            state_path.unlink()
            logger.info(f"Backed up state file to {backup_path}")
