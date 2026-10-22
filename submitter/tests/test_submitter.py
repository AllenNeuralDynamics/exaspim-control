import json
from pathlib import Path

import pytest
import requests

from exaspim_submitter import cli
from exaspim_submitter.config import (
    CONFIG_ENV_VAR,
    DEFAULT_CONFIG_PATH,
    load_config,
    resolve_config_path,
)

DATASET = "exaSPIM_730903_2026-09-01_16-55-09"


@pytest.fixture
def config():
    return load_config(DEFAULT_CONFIG_PATH)


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    source = tmp_path / DATASET / "exaSPIM"
    source.mkdir(parents=True)
    for index in range(2):
        (source / f"tile_{index}.ims").write_bytes(b"x" * 1024)
    return source


def _write_config(tmp_path: Path, **overrides) -> Path:
    text = DEFAULT_CONFIG_PATH.read_text()
    lines = [line for line in text.splitlines() if line.split("=")[0].strip() not in overrides]
    lines += [
        f"{key} = {json.dumps(value)}" for key, value in overrides.items() if value is not None
    ]
    path = tmp_path / "config.toml"
    path.write_text("\n".join(lines))
    return path


def test_default_config_is_valid(config):
    assert config.image_version
    assert config.screening_pipeline_id != config.production_5x_pipeline_id


@pytest.mark.parametrize(
    "overrides",
    [{"image_version": None}, {"max_partitions": 0}, {"max_partitions": "8"},
     {"endpoint": " "}, {"extra_key": "x"}],
)
def test_invalid_config_rejected(tmp_path, overrides):
    with pytest.raises(ValueError):
        load_config(_write_config(tmp_path, **overrides))


def test_resolve_config_path(monkeypatch, tmp_path):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    assert resolve_config_path() == DEFAULT_CONFIG_PATH
    monkeypatch.setenv(CONFIG_ENV_VAR, str(tmp_path / "env.toml"))
    assert resolve_config_path() == tmp_path / "env.toml"
    assert resolve_config_path(tmp_path / "arg.toml") == tmp_path / "arg.toml"


def test_derive_subject_id():
    assert cli.derive_subject_id("/a/ExaSPIM_123_x") == "123"
    assert cli.derive_subject_id("/a/123_x") == "123"
    assert cli.derive_subject_id("/a/plain") == "plain"


def test_parse_acq_datetime_requires_timestamp():
    with pytest.raises(ValueError):
        cli.parse_acq_datetime("/no/timestamp")


def test_discover_requires_ims(tmp_path):
    with pytest.raises(FileNotFoundError):
        cli.discover_ims_files(str(tmp_path))


def test_estimate_timeout():
    assert cli.estimate_timeout_minutes(0, 8200) == 120
    assert cli.estimate_timeout_minutes(8200, 8200) == 240


def _co_settings(payload):
    tasks = payload["upload_jobs"][0]["tasks"]
    return tasks["codeocean_pipeline_settings"]["SPIM"]["job_settings"][
        "pipeline_monitor_settings"
    ]


def test_screening_payload_uses_remote_source(config, dataset):
    remote = f"/allen/aind/stage/exaSPIM/{DATASET}/exaSPIM"
    payload = cli.build_payload(config, str(dataset), remote, "Project", subject_id="730903")
    job = payload["upload_jobs"][0]
    transform = job["tasks"]["modality_transformation_settings"]["SPIM"]
    assert job["subject_id"] == "730903"
    assert transform["job_settings"]["input_source"] == remote
    assert transform["image_version"] == config.image_version
    assert transform["job_settings"]["num_of_partitions"] == config.screening_partitions
    assert _co_settings(payload)["run_params"]["pipeline_id"] == config.screening_pipeline_id


def test_production_payload(config, dataset, tmp_path):
    big = load_config(_write_config(tmp_path, screening_max_bytes=1))
    payload = cli.build_payload(big, str(dataset), str(dataset), "Project", subject_id="s1")
    run_params = _co_settings(payload)["run_params"]
    assert run_params["pipeline_id"] == config.production_5x_pipeline_id
    assert run_params["processes"][0]["parameters"][0].startswith(
        f"s3://{config.s3_bucket_name}/s1_2026-09-01_16-55-09/"
    )


def test_main_dry_run_does_not_post(dataset, monkeypatch, capsys):
    monkeypatch.setattr(cli.requests, "post", pytest.fail)
    assert cli.main([str(dataset), "--dry-run"]) == 0
    assert '"upload_jobs"' in capsys.readouterr().out


def test_main_invalid_input(tmp_path):
    assert cli.main([str(tmp_path)]) == 2


class _Response:
    def __init__(self, ok):
        self.ok = ok
        self.status_code = 200 if ok else 400
        self.text = "{}"


@pytest.mark.parametrize("ok, code", [(True, 0), (False, 1)])
def test_main_submits(dataset, monkeypatch, ok, code):
    calls = []
    monkeypatch.setattr(
        cli.requests, "post", lambda **kwargs: calls.append(kwargs) or _Response(ok)
    )
    assert cli.main([str(dataset)]) == code
    assert calls[0]["url"].endswith("/api/v2/submit_jobs")
    assert calls[0]["timeout"] > 0


def test_submit_network_error(config, monkeypatch):
    def fail(**_):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(cli.requests, "post", fail)
    assert cli.submit(config, {}) == 1
