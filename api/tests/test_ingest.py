from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pocketscan_api.ingest import mark_status, record_result
from pocketscan_api.models import (
    AnalysisRun,
    Job,
    JobProtein,
    Pocket,
    Protein,
    Status,
    Structure,
)
from pocketscan_api.schemas import ResultIn


def make_job(session: Session, *accessions: str) -> Job:
    job = Job(request_key="k" * 64, analysis="fpocket")
    job.proteins = [JobProtein(accession=a) for a in accessions]
    session.add(job)
    session.flush()
    return job


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def link(session: Session, job: Job, accession: str) -> JobProtein:
    """Re-read a job_protein row, since ingest may write behind the ORM's back."""
    session.expire_all()
    return session.scalars(
        select(JobProtein).where(JobProtein.job_id == job.id, JobProtein.accession == accession)
    ).one()


def test_record_result_stores_facts_and_links_the_job_protein(
    session: Session, result_body: dict[str, Any]
) -> None:
    job = make_job(session, "P08100")

    outcome = record_result(session, job.id, "P08100", ResultIn(**result_body))

    assert outcome.cache_hit is False
    assert count(session, Protein) == 1
    assert count(session, Structure) == 1
    assert count(session, AnalysisRun) == 1
    assert count(session, Pocket) == 2
    jp = link(session, job, "P08100")
    assert jp.status == Status.SUCCEEDED
    assert jp.error is None
    assert jp.protein_id is not None
    assert jp.analysis_run_id == outcome.analysis_run_id


def test_repeated_result_is_a_cache_hit_and_adds_nothing(
    session: Session, result_body: dict[str, Any]
) -> None:
    job = make_job(session, "P08100")
    first = record_result(session, job.id, "P08100", ResultIn(**result_body))

    second = record_result(session, job.id, "P08100", ResultIn(**result_body))

    assert second.cache_hit is True
    assert second.analysis_run_id == first.analysis_run_id
    assert count(session, AnalysisRun) == 1
    assert count(session, Pocket) == 2


def test_same_sequence_under_another_accession_reuses_everything(
    session: Session, result_body: dict[str, Any]
) -> None:
    job = make_job(session, "P08100", "Q99999")
    first = record_result(session, job.id, "P08100", ResultIn(**result_body))

    second = record_result(session, job.id, "Q99999", ResultIn(**result_body))

    assert second.cache_hit is True
    assert second.analysis_run_id == first.analysis_run_id
    assert count(session, Protein) == 1
    assert count(session, Structure) == 1
    assert count(session, AnalysisRun) == 1
    assert link(session, job, "Q99999").analysis_run_id == first.analysis_run_id


def test_tool_upgrade_creates_a_new_run_and_keeps_the_old_one(
    session: Session, result_body: dict[str, Any]
) -> None:
    job = make_job(session, "P08100")
    old = record_result(session, job.id, "P08100", ResultIn(**result_body))

    result_body["run"]["tool_version"] = "5.0+deadbee"
    new = record_result(session, job.id, "P08100", ResultIn(**result_body))

    assert new.cache_hit is False
    assert new.analysis_run_id != old.analysis_run_id
    assert count(session, Protein) == 1
    assert count(session, Structure) == 1
    assert count(session, AnalysisRun) == 2
    assert count(session, Pocket) == 4
    assert link(session, job, "P08100").analysis_run_id == new.analysis_run_id


def test_failed_run_is_replaced_by_a_retry_not_duplicated(
    session: Session, result_body: dict[str, Any]
) -> None:
    job = make_job(session, "P08100")
    failed_body = {**result_body, "pockets": [], "run": {**result_body["run"], "status": "failed"}}
    failed = record_result(session, job.id, "P08100", ResultIn(**failed_body))
    assert link(session, job, "P08100").status == Status.FAILED
    assert count(session, Pocket) == 0

    retry = record_result(session, job.id, "P08100", ResultIn(**result_body))

    assert retry.cache_hit is False  # a failure is never a cache hit
    assert retry.analysis_run_id == failed.analysis_run_id
    assert count(session, AnalysisRun) == 1
    assert count(session, Pocket) == 2
    run = session.get(AnalysisRun, retry.analysis_run_id)
    assert run is not None
    session.refresh(run)
    assert run.status == Status.SUCCEEDED
    assert link(session, job, "P08100").status == Status.SUCCEEDED


def test_unknown_accession_raises_lookup_error(
    session: Session, result_body: dict[str, Any]
) -> None:
    job = make_job(session, "P08100")

    with pytest.raises(LookupError):
        record_result(session, job.id, "Q00000", ResultIn(**result_body))

    assert count(session, Protein) == 0  # nothing written before the check


def test_mark_status_sets_status_and_error(session: Session) -> None:
    job = make_job(session, "P08100", "Q99999")

    mark_status(session, job.id, "P08100", Status.FAILED, error="AlphaFold model not found")

    jp = link(session, job, "P08100")
    assert jp.status == Status.FAILED
    assert jp.error == "AlphaFold model not found"
    assert link(session, job, "Q99999").status == Status.PENDING  # siblings untouched
