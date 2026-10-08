from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from pocketscan_api.ingest import RecordOutcome, record_result
from pocketscan_api.main import app
from pocketscan_api.models import AnalysisRun, Job, JobProtein, Pocket, Protein, Structure
from pocketscan_api.schemas import ResultIn

WORKERS = 8


def post_when_everyone_is_ready(barrier: Barrier, body: dict[str, list[str]]) -> tuple[int, int]:
    """One thread: its own client and its own database session, released together."""
    with TestClient(app) as client:
        barrier.wait()
        response = client.post("/jobs", json=body)
    return response.status_code, response.json()["id"]


def test_concurrent_identical_requests_create_exactly_one_job(
    engine: Engine, committed_jobs: None
) -> None:
    body = {"accessions": ["P08100", "Q9Y6K9"]}
    barrier = Barrier(WORKERS)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(
            pool.map(lambda _: post_when_everyone_is_ready(barrier, body), range(WORKERS))
        )

    # Exactly one request created the job; every other one got the existing job back.
    assert sorted(status for status, _ in results) == [200] * (WORKERS - 1) + [201]
    assert len({job_id for _, job_id in results}) == 1

    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Job)) == 1
        assert connection.scalar(select(func.count()).select_from(JobProtein)) == 2


def record_when_everyone_is_ready(
    engine: Engine, barrier: Barrier, job_id: int, accession: str, body: dict[str, Any]
) -> RecordOutcome:
    """One worker: its own session, committing for real, released together."""
    with Session(engine) as session:
        barrier.wait()
        outcome = record_result(session, job_id, accession, ResultIn(**body))
        session.commit()
    return outcome


def test_concurrent_identical_results_are_stored_once(
    engine: Engine, committed_jobs: None, result_body: dict[str, Any]
) -> None:
    """Eight proteins in one job finish together with the same sequence and run.

    Exactly one worker should do the work; the other seven should see its
    committed run and report a cache hit, with no duplicate rows and no errors.
    """
    accessions = [f"P{n:05d}" for n in range(WORKERS)]
    with Session(engine) as session:
        job = Job(request_key="k" * 64, analysis="fpocket")
        job.proteins = [JobProtein(accession=a) for a in accessions]
        session.add(job)
        session.commit()
        job_id = job.id
    barrier = Barrier(WORKERS)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        outcomes = list(
            pool.map(
                lambda accession: record_when_everyone_is_ready(
                    engine, barrier, job_id, accession, result_body
                ),
                accessions,
            )
        )

    assert sorted(outcome.cache_hit for outcome in outcomes) == [False] + [True] * (WORKERS - 1)
    assert len({outcome.analysis_run_id for outcome in outcomes}) == 1

    with engine.connect() as connection:
        for model, expected in [(Protein, 1), (Structure, 1), (AnalysisRun, 1), (Pocket, 2)]:
            assert connection.scalar(select(func.count()).select_from(model)) == expected
        linked = connection.scalar(
            select(func.count())
            .select_from(JobProtein)
            .where(JobProtein.analysis_run_id == outcomes[0].analysis_run_id)
        )
        assert linked == WORKERS
