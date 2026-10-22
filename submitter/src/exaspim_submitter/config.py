"""Load and validate the submitter TOML configuration."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

CONFIG_ENV_VAR = "EXASPIM_SUBMITTER_CONFIG"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "submitter_config.toml"


@dataclass(frozen=True)
class SubmitterConfig:
    """Hold every non-secret setting needed to build a submission request.

    Parameters
    ----------
    endpoint : str
        Base URL of aind-data-transfer-service.
    job_type : str
        Job type registered on the service.
    s3_bucket : str
        Service bucket key (e.g. ``open``).
    s3_bucket_name : str
        Bucket name that ``s3_bucket`` resolves to; used for the Neuroglancer asset path.
    user_email : str
        Email for job notifications.
    image : str
        Transformation container image.
    image_version : str
        aind-exaspim-data-transformation release tag.
    max_partitions : int
        Partitions for production (5x) datasets.
    screening_partitions : int
        Partitions for screening datasets.
    screening_max_bytes : int
        Datasets smaller than this run the screening pipeline.
    processing_speed_gb_per_hour : int
        Throughput used to estimate the job time limit.
    screening_pipeline_id : str
        Code Ocean screening pipeline ID.
    production_5x_pipeline_id : str
        Code Ocean production 5x pipeline ID.
    codeocean_mount : str
        Data asset mount name for the screening pipeline.
    neuroglancer_smartsheet_process : str
        5x pipeline process that writes the Neuroglancer link to Smartsheet.
    smartsheet_id : str
        Target Smartsheet ID.
    """

    endpoint: str
    job_type: str
    s3_bucket: str
    s3_bucket_name: str
    user_email: str
    image: str
    image_version: str
    max_partitions: int
    screening_partitions: int
    screening_max_bytes: int
    processing_speed_gb_per_hour: int
    screening_pipeline_id: str
    production_5x_pipeline_id: str
    codeocean_mount: str
    neuroglancer_smartsheet_process: str
    smartsheet_id: str


def resolve_config_path(explicit: Path | None = None) -> Path:
    """Return the config path from an argument, the environment, or the bundled default.

    Parameters
    ----------
    explicit : Path or None
        Path given on the command line; takes precedence.

    Returns
    -------
    Path
        Selected configuration file path.
    """
    if explicit is not None:
        return explicit
    env_value = os.environ.get(CONFIG_ENV_VAR)
    return Path(env_value) if env_value else DEFAULT_CONFIG_PATH


def load_config(path: Path) -> SubmitterConfig:
    """Read and validate a TOML configuration file.

    Parameters
    ----------
    path : Path
        TOML file to read.

    Returns
    -------
    SubmitterConfig
        Validated configuration.

    Raises
    ------
    ValueError
        If keys are missing or unknown, or values have the wrong type or are not positive.
    """
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    expected = {field.name: field.type for field in fields(SubmitterConfig)}
    missing = sorted(set(expected) - set(raw))
    unknown = sorted(set(raw) - set(expected))
    if missing or unknown:
        raise ValueError(f"Config {path}: missing keys {missing}, unknown keys {unknown}.")
    for name, type_name in expected.items():
        value = raw[name]
        if type_name == "int":
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"Config {path}: '{name}' must be a positive integer.")
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(f"Config {path}: '{name}' must be a non-empty string.")
    return SubmitterConfig(**raw)
