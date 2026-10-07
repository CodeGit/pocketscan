import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pocketscan_api.models import AnalysisRun, Job, JobProtein, Protein, Status, Structure

EXPECTED_TABLES = {"job", "job_protein", "protein", "structure", "analysis_run", "pocket"}


def make_job(session: Session, request_key: str) -> Job:
    job = Job(request_key=request_key, analysis="fpocket")
    session.add(job)
    session.flush()
    return job


def make_structure(session: Session) -> Structure:
    protein = Protein(seq_sha256="a" * 64, sequence="MKV")
    session.add(protein)
    session.flush()
    structure = Structure(
        protein_id=protein.id,
        source="alphafold",
        source_version="v6",
        gcs_uri="gs://example/AF-P08100-F1-model_v6.cif",
    )
    session.add(structure)
    session.flush()
    return structure


def test_migrations_create_the_six_tables(engine: Engine) -> None:
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_models_match_migrations(engine: Engine, alembic_cfg: Config) -> None:
    """Fails if a model changed without a migration (alembic check)."""
    command.check(alembic_cfg)


def test_request_key_is_unique(session: Session) -> None:
    make_job(session, "k1")
    session.add(Job(request_key="k1", analysis="fpocket"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_accession_is_unique_within_a_job(session: Session) -> None:
    job = Job(request_key="k2", analysis="fpocket")
    job.proteins = [JobProtein(accession="P08100"), JobProtein(accession="P08100")]
    session.add(job)
    with pytest.raises(IntegrityError):
        session.flush()


def test_job_protein_status_defaults_to_pending(session: Session) -> None:
    job = Job(request_key="k3", analysis="fpocket")
    job_protein = JobProtein(accession="P08100")
    job.proteins = [job_protein]
    session.add(job)
    session.flush()
    session.refresh(job_protein)
    assert job_protein.status is Status.PENDING


def test_database_rejects_an_unknown_status(session: Session) -> None:
    job = make_job(session, "k4")
    with pytest.raises(IntegrityError):
        session.execute(
            text("INSERT INTO job_protein (job_id, accession, status) VALUES (:id, 'P1', 'bogus')"),
            {"id": job.id},
        )


def test_analysis_run_cache_key(session: Session) -> None:
    structure = make_structure(session)
    run = {"structure_id": structure.id, "tool": "fpocket", "params_hash": "h1", "params": {}}

    session.add(AnalysisRun(tool_version="4.0+4bb0d84", **run))
    session.flush()
    # A tool upgrade is a different run, not a cache hit.
    session.add(AnalysisRun(tool_version="4.1+abcdef0", **run))
    session.flush()
    # The same tool version and parameters again is rejected.
    session.add(AnalysisRun(tool_version="4.0+4bb0d84", **run))
    with pytest.raises(IntegrityError):
        session.flush()
