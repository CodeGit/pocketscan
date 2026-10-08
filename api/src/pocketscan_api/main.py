from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from pocketscan_api.db import get_session
from pocketscan_api.job_status import derive_job_status
from pocketscan_api.models import Job, JobProtein, Pocket, Status
from pocketscan_api.request_keys import compute_request_key
from pocketscan_api.schemas import JobCreate, JobOut, JobProteinOut, PocketOut

app = FastAPI(title="pocketscan", version="0.1.0")
type SessionDep = Annotated[Session, Depends(get_session)]

type PocketSort = Literal["rank", "score", "volume_a3", "mean_sasa_a2", "mean_plddt"]
POCKET_SORT_COLUMNS = {
    "rank": Pocket.rank,
    "score": Pocket.score,
    "volume_a3": Pocket.volume_a3,
    "mean_sasa_a2": Pocket.mean_sasa_a2,
    "mean_plddt": Pocket.mean_plddt,
}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Does not touch the database."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(session: SessionDep) -> dict[str, str]:
    """Readiness: the database is reachable."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="database unavailable") from error
    return {"status": "ready"}


def job_to_out(job: Job) -> JobOut:
    proteins = sorted(job.proteins, key=lambda p: p.accession)
    return JobOut(
        id=job.id,
        request_key=job.request_key,
        analysis=job.analysis,
        created_at=job.created_at,
        status=derive_job_status(protein.status for protein in proteins),
        proteins=[JobProteinOut.model_validate(protein) for protein in proteins],
    )


@app.post("/jobs", response_model=JobOut)
def create_job(payload: JobCreate, response: Response, session: SessionDep) -> JobOut:
    request_key = compute_request_key(payload.analysis, payload.accessions)
    insert_id = session.execute(
        insert(Job)
        .values(request_key=request_key, analysis=payload.analysis)
        .on_conflict_do_nothing(
            index_elements=[Job.request_key]
        )  # ensure only request_key conflicts are ignored
        .returning(Job.id)
    ).scalar_one_or_none()

    if insert_id is not None:
        session.add_all(JobProtein(job_id=insert_id, accession=a) for a in payload.accessions)
    session.commit()

    job = session.scalars(
        select(Job).where(Job.request_key == request_key).options(selectinload(Job.proteins))
    ).one()

    if insert_id is not None:
        response.status_code = status.HTTP_201_CREATED
        response.headers["Location"] = f"/jobs/{job.id}"
    else:
        response.status_code = status.HTTP_200_OK
    return job_to_out(job)


@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, session: SessionDep) -> JobOut:
    job = session.scalars(
        select(Job).where(Job.id == job_id).options(selectinload(Job.proteins))
    ).one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job_to_out(job)


@app.get("/jobs/{job_id}/pockets", response_model=list[PocketOut])
def list_pockets(
    job_id: int,
    session: SessionDep,
    accession: str | None = None,
    min_score: float | None = None,
    min_volume_a3: float | None = None,
    min_mean_plddt: float | None = None,
    sort: PocketSort = "rank",
    order: Literal["asc", "desc"] = "asc",
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PocketOut]:
    """Pockets for the job's succeeded proteins, sorted and filtered in the database.

    Proteins that are still pending, running or failed have no pockets to show.
    Ties on the sort column fall back to accession then rank, so paging is stable.
    """
    if session.get(Job, job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")

    stmt = (
        select(
            JobProtein.accession,
            Pocket.rank,
            Pocket.score,
            Pocket.volume_a3,
            Pocket.mean_sasa_a2,
            Pocket.mean_plddt,
            Pocket.residues,
        )
        .join(Pocket, Pocket.analysis_run_id == JobProtein.analysis_run_id)
        .where(JobProtein.job_id == job_id, JobProtein.status == Status.SUCCEEDED)
    )
    if accession is not None:
        stmt = stmt.where(JobProtein.accession == accession.strip().upper())
    if min_score is not None:
        stmt = stmt.where(Pocket.score >= min_score)
    if min_volume_a3 is not None:
        stmt = stmt.where(Pocket.volume_a3 >= min_volume_a3)
    if min_mean_plddt is not None:
        stmt = stmt.where(Pocket.mean_plddt >= min_mean_plddt)

    column = POCKET_SORT_COLUMNS[sort]
    direction = column.asc() if order == "asc" else column.desc()
    stmt = (
        stmt.order_by(direction.nulls_last(), JobProtein.accession, Pocket.rank)
        .limit(limit)
        .offset(offset)
    )
    return [PocketOut(**row) for row in session.execute(stmt).mappings()]
