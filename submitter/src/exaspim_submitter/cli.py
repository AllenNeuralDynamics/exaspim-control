"""Command-line entry point that submits one ExaSPIM transformation job.

Exit codes: ``0`` accepted by the service (or dry run), ``1`` service rejected or
request failed, ``2`` invalid input or configuration (nothing was sent).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from datetime import datetime
from glob import glob
from pathlib import Path

import requests
from aind_codeocean_pipeline_monitor.models import CaptureSettings, PipelineMonitorSettings
from aind_data_schema_models.modalities import Modality
from aind_data_transfer_service.models.core import SubmitJobRequestV2, Task, UploadJobConfigsV2
from codeocean.computation import DataAssetsRunParam, PipelineProcessParams, RunParams

from exaspim_submitter.config import SubmitterConfig, load_config, resolve_config_path

_DATETIME = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})")
_REQUEST_TIMEOUT_SECONDS = 60
_TIMEOUT_BUFFER_MINUTES = 2 * 60
_TIMEOUT_VARIABILITY = 2


def discover_ims_files(source: str) -> list[str]:
    """Return sorted ``.ims`` paths found anywhere under ``source``.

    Parameters
    ----------
    source : str
        Locally readable dataset folder.

    Returns
    -------
    list of str
        Sorted file paths.

    Raises
    ------
    FileNotFoundError
        If no ``.ims`` files exist.
    """
    files = sorted(glob(os.path.join(source, "**", "*.ims"), recursive=True))
    if not files:
        raise FileNotFoundError(f"No .ims files found under {source}")
    return files


def estimate_timeout_minutes(total_gb: float, speed_gb_per_hour: int) -> int:
    """Estimate the job time limit in minutes from data volume.

    Parameters
    ----------
    total_gb : float
        Dataset size in GiB.
    speed_gb_per_hour : int
        Expected processing throughput.

    Returns
    -------
    int
        Time limit including variability and a fixed buffer.
    """
    hours = total_gb / speed_gb_per_hour
    return int(hours * 60 * _TIMEOUT_VARIABILITY + _TIMEOUT_BUFFER_MINUTES)


def parse_acq_datetime(path: str) -> datetime:
    """Extract the ``YYYY-MM-DD_HH-MM-SS`` acquisition datetime from ``path``.

    Parameters
    ----------
    path : str
        Dataset path containing the timestamp.

    Returns
    -------
    datetime
        Naive acquisition datetime.

    Raises
    ------
    ValueError
        If no timestamp is present.
    """
    match = _DATETIME.search(path)
    if not match:
        raise ValueError(f"Could not find a YYYY-MM-DD_HH-MM-SS datetime in: {path}")
    return datetime.fromisoformat(f"{match.group(1)}T{match.group(2).replace('-', ':')}")


def derive_subject_id(path: str) -> str:
    """Return a best-effort subject ID from the dataset folder name.

    Parameters
    ----------
    path : str
        Dataset path.

    Returns
    -------
    str
        Subject ID.
    """
    basename = os.path.basename(os.path.normpath(path))
    if "_" not in basename:
        return basename
    return basename.split("_")[1] if "ExaSPIM" in basename else basename.split("_")[0]


def _pipeline_settings(
    config: SubmitterConfig, is_screening: bool, s3_asset_path: str
) -> dict[str, object]:
    """Build the Code Ocean pipeline task for a screening or production dataset."""
    if is_screening:
        monitor = PipelineMonitorSettings(
            run_params=RunParams(
                pipeline_id=config.screening_pipeline_id,
                data_assets=[DataAssetsRunParam(id="", mount=config.codeocean_mount)],
            ),
            capture_settings=CaptureSettings(tags=["exaSPIM", "RAW"]),
        )
    else:
        monitor = PipelineMonitorSettings(
            run_params=RunParams(
                pipeline_id=config.production_5x_pipeline_id,
                processes=[
                    PipelineProcessParams(
                        name=config.neuroglancer_smartsheet_process,
                        parameters=[s3_asset_path, config.smartsheet_id],
                    )
                ],
            ),
        )
    return {
        "skip_task": False,
        "job_settings": {
            "pipeline_monitor_settings": monitor.model_dump(mode="json", exclude_none=True)
        },
    }


def build_payload(
    config: SubmitterConfig,
    source: str,
    remote_source: str,
    project_name: str,
    subject_id: str | None = None,
    single_tile_upload: bool = False,
) -> dict[str, object]:
    """Build the JSON body for ``/api/v2/submit_jobs``.

    Parameters
    ----------
    config : SubmitterConfig
        Validated configuration.
    source : str
        Locally readable folder used to discover and size ``.ims`` files.
    remote_source : str
        The same folder as seen by the transfer service (``/allen/...``).
    project_name : str
        Project name for the upload job.
    subject_id : str or None
        Subject ID; derived from ``remote_source`` when ``None``.
    single_tile_upload : bool
        Process only the first tile (integration testing).

    Returns
    -------
    dict
        JSON-serializable submit request.
    """
    subject_id = subject_id or derive_subject_id(remote_source)
    acq_datetime = parse_acq_datetime(remote_source)
    ims_files = discover_ims_files(source)
    total_bytes = sum(os.path.getsize(path) for path in ims_files)
    is_screening = total_bytes < config.screening_max_bytes
    partitions = config.screening_partitions if is_screening else config.max_partitions
    timeout_min = estimate_timeout_minutes(
        total_bytes / 1024**3, config.processing_speed_gb_per_hour
    )
    s3_asset_path = (
        f"s3://{config.s3_bucket_name}/{subject_id}_{acq_datetime:%Y-%m-%d_%H-%M-%S}/SPIM/"
    )
    print(
        f"Tiles: {len(ims_files)}  Size: {total_bytes / 1024**3:,.1f} GiB  "
        f"Partitions: {partitions}  Timeout: {timeout_min} min  Screening: {is_screening}"
    )
    task = Task(
        image=config.image,
        image_version=config.image_version,
        image_resources={
            "array": f"0-{partitions - 1}",
            "time_limit": {"set": True, "number": timeout_min},
            "comment": "RETRY 2",
        },
        job_settings={
            "input_source": remote_source,
            "num_of_partitions": partitions,
            "dask_workers": 1,
            "use_tensorstore": True,
            "single_tile_upload": single_tile_upload,
        },
    )
    tasks = {
        "modality_transformation_settings": {Modality.SPIM.abbreviation: task},
        "check_s3_folder_exists": {"skip_task": True},
        "final_check_s3_folder_exist": {"skip_task": True},
        "check_metadata_files": {"skip_task": True},
        "gather_preliminary_metadata": {"skip_task": False},
        "register_data_asset": {"skip_task": False},
        "get_codeocean_asset_id": {"skip_task": False},
        "run_codeocean_pipeline": {"skip_task": False},
        "remove_source_folders": {"skip_task": False},
        "codeocean_pipeline_settings": {
            Modality.SPIM.abbreviation: _pipeline_settings(config, is_screening, s3_asset_path)
        },
    }
    upload_job = UploadJobConfigsV2(
        job_type=config.job_type,
        s3_bucket=config.s3_bucket,
        project_name=project_name,
        modalities=[Modality.SPIM],
        subject_id=subject_id,
        acq_datetime=acq_datetime,
        user_email=config.user_email,
        email_notification_types=["all"],
        tasks=tasks,
    )
    request = SubmitJobRequestV2(upload_jobs=[upload_job], user_email=config.user_email)
    return request.model_dump(mode="json", exclude_none=True)


def submit(config: SubmitterConfig, payload: dict[str, object]) -> int:
    """POST the payload once and return a process exit code.

    Parameters
    ----------
    config : SubmitterConfig
        Validated configuration providing the endpoint.
    payload : dict
        Submit request body.

    Returns
    -------
    int
        ``0`` if the service accepted the job, otherwise ``1``.
    """
    url = f"{config.endpoint}/api/v2/submit_jobs"
    try:
        response = requests.post(url=url, json=payload, timeout=_REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        print(f"Request failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(f"Status  : {response.status_code}")
    print(f"Response: {response.text}")
    if not response.ok:
        return 1
    print(f"Review your job at {config.endpoint}/jobs/")
    return 0


def _parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(description="Submit an ExaSPIM IMS-to-Zarr upload job.")
    parser.add_argument("input_folder", help="Locally readable folder containing .ims files.")
    parser.add_argument(
        "--remote-source",
        default=None,
        help="Same folder as seen by the service (/allen/...). Defaults to input_folder.",
    )
    parser.add_argument("--project-name", default="Single Neuron Reconstructions")
    parser.add_argument("--subject-id", default=None, help="Derived from the folder if omitted.")
    parser.add_argument("--single-tile", action="store_true", help="Process only the first tile.")
    parser.add_argument("--config", type=Path, default=None, help="Path to the TOML config.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the request and do not submit."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Parameters
    ----------
    argv : sequence of str or None
        Arguments; ``sys.argv[1:]`` when ``None``.

    Returns
    -------
    int
        Process exit code.
    """
    args = _parser().parse_args(argv)
    try:
        config = load_config(resolve_config_path(args.config))
        payload = build_payload(
            config,
            source=args.input_folder,
            remote_source=args.remote_source or args.input_folder,
            project_name=args.project_name,
            subject_id=args.subject_id,
            single_tile_upload=args.single_tile,
        )
    except (OSError, ValueError) as error:
        print(f"Invalid input: {error}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0
    return submit(config, payload)


if __name__ == "__main__":  # pragma: no cover - script entry guard; main() is tested directly
    sys.exit(main())
