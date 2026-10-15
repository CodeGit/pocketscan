from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pocketscan_api.config import Settings, get_settings
from pocketscan_api.ingest import mark_status, record_result
from pocketscan_api.models import Status
from pocketscan_api.schemas import ResultIn

CIF = b"data_model\n#\n"


@pytest.fixture
def structure_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "structures"
    root.mkdir()
    monkeypatch.setenv("POCKETSCAN_LOCAL_STRUCTURE_ROOT", str(root))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


def make_job(
    client: TestClient, session: Session, result_body: dict[str, Any], gcs_uri: str
) -> int:
    job = client.post("/jobs", json={"accessions": ["P08100"]}).json()
    result_body["structure"]["gcs_uri"] = gcs_uri
    record_result(session, job["id"], "P08100", ResultIn(**result_body))
    return job["id"]


def test_serves_the_stored_file(
    client: TestClient, session: Session, result_body: dict[str, Any], structure_root: Path
) -> None:
    model = structure_root / "model.cif"
    model.write_bytes(CIF)
    job_id = make_job(client, session, result_body, model.as_uri())

    response = client.get(f"/jobs/{job_id}/structures/p08100")  # case-insensitive

    assert response.status_code == 200
    assert response.content == CIF
    assert response.headers["content-type"] == "chemical/x-mmcif"


def test_refuses_a_file_outside_the_root(
    client: TestClient,
    session: Session,
    result_body: dict[str, Any],
    structure_root: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "secret.cif"
    outside.write_bytes(CIF)
    job_id = make_job(client, session, result_body, outside.as_uri())

    assert client.get(f"/jobs/{job_id}/structures/P08100").status_code == 404


def test_refuses_file_uris_when_no_root_is_configured(
    client: TestClient,
    session: Session,
    result_body: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "model.cif"
    model.write_bytes(CIF)
    job_id = make_job(client, session, result_body, model.as_uri())
    # Set it explicitly, so a root in the shell or in api/.env cannot leak into this test.
    unconfigured = get_settings().model_copy(update={"local_structure_root": None})
    monkeypatch.setattr("pocketscan_api.main.get_settings", lambda: unconfigured)

    assert isinstance(unconfigured, Settings)
    assert client.get(f"/jobs/{job_id}/structures/P08100").status_code == 404


def test_gs_uris_are_not_served_yet(
    client: TestClient, session: Session, result_body: dict[str, Any], structure_root: Path
) -> None:
    job_id = make_job(client, session, result_body, "gs://bucket/model.cif")

    assert client.get(f"/jobs/{job_id}/structures/P08100").status_code == 501


def test_failed_or_unknown_proteins_have_no_structure(
    client: TestClient, session: Session, result_body: dict[str, Any], structure_root: Path
) -> None:
    model = structure_root / "model.cif"
    model.write_bytes(CIF)
    job_id = make_job(client, session, result_body, model.as_uri())
    mark_status(session, job_id, "P08100", Status.FAILED, error="boom")

    assert client.get(f"/jobs/{job_id}/structures/P08100").status_code == 404
    assert client.get(f"/jobs/{job_id}/structures/Q00000").status_code == 404
    assert client.get("/jobs/999999/structures/P08100").status_code == 404
