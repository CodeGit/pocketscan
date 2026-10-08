import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from pocketscan_api.ingest import main
from pocketscan_api.models import AnalysisRun, Job, JobProtein, Pocket, Protein, Status

# These tests call main() as the pipeline would, so it really commits.
# The committed_jobs fixture (conftest.py) empties the tables around each test.

pytestmark = pytest.mark.usefixtures("committed_jobs")


def make_committed_job(engine: Engine, *accessions: str) -> int:
    with Session(engine) as session:
        job = Job(request_key="k" * 64, analysis="fpocket")
        job.proteins = [JobProtein(accession=a) for a in accessions]
        session.add(job)
        session.commit()
        return job.id


def count(engine: Engine, model: type) -> int:
    with engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(model)) or 0


def job_protein(engine: Engine, job_id: int, accession: str) -> JobProtein:
    with Session(engine) as session:
        return session.scalars(
            select(JobProtein).filter_by(job_id=job_id, accession=accession)
        ).one()


def write_json(tmp_path: Path, body: dict[str, Any]) -> str:
    path = tmp_path / "result.json"
    path.write_text(json.dumps(body))
    return str(path)


def test_result_records_pockets_and_returns_zero(
    engine: Engine, tmp_path: Path, result_body: dict[str, Any]
) -> None:
    job_id = make_committed_job(engine, "P08100")
    path = write_json(tmp_path, result_body)

    code = main(["result", path, "--job-id", str(job_id), "--accession", "P08100"])

    assert code == 0
    assert count(engine, Pocket) == 2
    row = job_protein(engine, job_id, "P08100")
    assert row.status == Status.SUCCEEDED
    assert row.analysis_run_id is not None


def test_repeating_a_result_reports_a_cache_hit(
    engine: Engine,
    tmp_path: Path,
    result_body: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    job_id = make_committed_job(engine, "P08100")
    argv = ["result", write_json(tmp_path, result_body), "--job-id", str(job_id)]
    argv += ["--accession", "P08100"]

    assert main(argv) == 0
    assert "cache_hit=false" in capsys.readouterr().out
    assert main(argv) == 0
    assert "cache_hit=true" in capsys.readouterr().out
    assert count(engine, AnalysisRun) == 1


def test_malformed_json_is_rejected_and_writes_nothing(engine: Engine, tmp_path: Path) -> None:
    job_id = make_committed_job(engine, "P08100")
    path = tmp_path / "result.json"
    path.write_text("{not json")

    code = main(["result", str(path), "--job-id", str(job_id), "--accession", "P08100"])

    assert code != 0
    assert count(engine, Protein) == 0
    assert job_protein(engine, job_id, "P08100").status == Status.PENDING


def test_invalid_result_is_rejected_and_writes_nothing(
    engine: Engine, tmp_path: Path, result_body: dict[str, Any]
) -> None:
    job_id = make_committed_job(engine, "P08100")
    result_body["pockets"][1]["rank"] = 1  # duplicate rank
    path = write_json(tmp_path, result_body)

    code = main(["result", path, "--job-id", str(job_id), "--accession", "P08100"])

    assert code != 0
    assert count(engine, Protein) == 0


def test_unknown_accession_is_rejected_and_writes_nothing(
    engine: Engine, tmp_path: Path, result_body: dict[str, Any]
) -> None:
    job_id = make_committed_job(engine, "P08100")
    path = write_json(tmp_path, result_body)

    code = main(["result", path, "--job-id", str(job_id), "--accession", "Q00000"])

    assert code != 0
    assert count(engine, Protein) == 0


def test_fail_marks_the_protein_failed_with_the_error(engine: Engine) -> None:
    job_id = make_committed_job(engine, "P08100", "Q99999")

    code = main(
        ["fail", "--job-id", str(job_id), "--accession", "P08100", "--error", "model not found"]
    )

    assert code == 0
    failed = job_protein(engine, job_id, "P08100")
    assert (failed.status, failed.error) == (Status.FAILED, "model not found")
    assert job_protein(engine, job_id, "Q99999").status == Status.PENDING


def test_fail_for_an_unknown_accession_returns_non_zero(engine: Engine) -> None:
    job_id = make_committed_job(engine, "P08100")

    code = main(["fail", "--job-id", str(job_id), "--accession", "Q00000", "--error", "x"])

    assert code != 0
