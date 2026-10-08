import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from pocketscan_api.db import get_engine
from pocketscan_api.fingerprints import params_hash, sequence_hash
from pocketscan_api.models import (
    AnalysisRun,
    JobProtein,
    Pocket,
    Protein,
    Status,
    Structure,
)
from pocketscan_api.schemas import ResultIn


@dataclass(frozen=True)
class RecordOutcome:
    analysis_run_id: int
    cache_hit: bool


def insert_if_absent(
    session: Session,
    model: type[Any],
    values: dict[str, Any],
    key: tuple[str, ...],
) -> int:
    """Return the id of the row identified by `key`, inserting it if it doesn't exist.

    `key` names the columns of a unique constraint. ON CONFLICT DO NOTHING makes
    this safe when two workers race: one insert wins, the other gets no row back
    and reads the winner's.
    """
    stmt = (
        pg_insert(model)
        .values(**values)
        .on_conflict_do_nothing(index_elements=list(key))
        .returning(model.id)
    )
    row_id = session.scalar(stmt)
    if row_id is None:  # conflict: the row already exists
        row_id = session.scalar(select(model.id).filter_by(**{c: values[c] for c in key}))
    assert row_id is not None
    return row_id


def _get_job_protein(session: Session, job_id: int, accession: str) -> JobProtein:
    job_protein = session.scalars(
        select(JobProtein).filter_by(job_id=job_id, accession=accession)
    ).one_or_none()
    if job_protein is None:
        raise LookupError(f"job {job_id} has no protein {accession}")
    return job_protein


def mark_status(
    session: Session, job_id: int, accession: str, status: Status, error: str | None = None
) -> None:
    job_protein = _get_job_protein(session, job_id, accession)
    job_protein.status = status
    job_protein.error = error
    session.flush()


def record_result(session: Session, job_id: int, accession: str, result: ResultIn) -> RecordOutcome:
    job_protein = _get_job_protein(session, job_id, accession)  # before any write

    protein_id = insert_if_absent(
        session,
        Protein,
        {"seq_sha256": sequence_hash(result.sequence), "sequence": result.sequence},
        key=("seq_sha256",),
    )
    structure_id = insert_if_absent(
        session,
        Structure,
        {"protein_id": protein_id, **result.structure.model_dump()},
        key=("protein_id", "source", "source_version"),
    )
    run_id = insert_if_absent(
        session,
        AnalysisRun,
        {
            "structure_id": structure_id,
            "tool": result.run.tool,
            "tool_version": result.run.tool_version,
            "params_hash": params_hash(result.run.params),
            "params": result.run.params,
            "status": Status.PENDING,
        },
        key=("structure_id", "tool", "tool_version", "params_hash"),
    )
    run = session.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()

    cache_hit = run.status == Status.SUCCEEDED
    if not cache_hit:
        session.execute(delete(Pocket).where(Pocket.analysis_run_id == run.id))
        run.status = result.run.status
        run.output_gcs_uri = result.run.output_gcs_uri
        session.add_all(
            Pocket(analysis_run_id=run.id, **pocket.model_dump()) for pocket in result.pockets
        )

    job_protein.protein_id = protein_id
    job_protein.analysis_run_id = run.id
    job_protein.status = run.status
    job_protein.error = None
    session.flush()
    return RecordOutcome(analysis_run_id=run.id, cache_hit=cache_hit)


def run_result(args: argparse.Namespace) -> int:
    try:
        result = ResultIn.model_validate_json(args.path.read_text())
    except (OSError, ValidationError) as error:
        print(f"invalid result: {error}", file=sys.stderr)
        return 2

    with Session(get_engine()) as session:
        try:
            outcome = record_result(session, args.job_id, args.accession, result)
        except LookupError as error:
            print(error, file=sys.stderr)
            return 1
        session.commit()
    print(f"cache_hit={str(outcome.cache_hit).lower()} run={outcome.analysis_run_id}")
    return 0


def run_fail(args: argparse.Namespace) -> int:
    with Session(get_engine()) as session:
        try:
            mark_status(session, args.job_id, args.accession, Status.FAILED, args.error)
        except LookupError as error:
            print(error, file=sys.stderr)
            return 1
        session.commit()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pocketscan_api.ingest")
    commands = parser.add_subparsers(dest="command", required=True)

    result = commands.add_parser("result", help="records a completed analysis")
    result.add_argument("path", type=Path, help="result.json written by the pipeline")

    fail = commands.add_parser("fail", help="mark a protein job as failed")
    fail.add_argument("--error", required=True)

    for command in (result, fail):
        command.add_argument("--job-id", type=int, required=True)
        command.add_argument("--accession", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = run_result if args.command == "result" else run_fail
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
