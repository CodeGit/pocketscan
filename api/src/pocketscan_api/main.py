from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response, status
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from pocketscan_api.db import get_session
from pocketscan_api.job_status import derive_job_status
from pocketscan_api.models import Job, JobProtein
from pocketscan_api.request_keys import compute_request_key
from pocketscan_api.schemas import JobCreate, JobOut, JobProteinOut

app = FastAPI(title="pocketscan", version="0.1.0")
type SessionDep = Annotated[Session, Depends(get_session)]


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
