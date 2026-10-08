import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pocketscan_api.db import Base
from pocketscan_api.models import Job, JobProtein, Status

BODY = {"analysis": "fpocket", "accessions": ["Q9Y6K9", "P08100"]}


def count(session: Session, model: type[Base]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_first_post_creates_the_job(client: TestClient) -> None:
    response = client.post("/jobs", json=BODY)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert [p["accession"] for p in body["proteins"]] == ["P08100", "Q9Y6K9"]
    assert len(body["request_key"]) == 64
    assert response.headers["location"] == f"/jobs/{body['id']}"


def test_repeat_post_returns_the_existing_job(client: TestClient, session: Session) -> None:
    first = client.post("/jobs", json=BODY)
    again = client.post("/jobs", json={"accessions": [" p08100", "q9y6k9", "P08100"]})
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert count(session, Job) == 1
    assert count(session, JobProtein) == 2


def test_different_accessions_make_a_different_job(client: TestClient) -> None:
    first = client.post("/jobs", json=BODY)
    other = client.post("/jobs", json={"accessions": ["P08100"]})
    assert other.status_code == 201
    assert other.json()["id"] != first.json()["id"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"accessions": []},
        {"accessions": ["nope"]},
        {"analysis": "unknown", "accessions": ["P08100"]},
    ],
)
def test_bad_requests_are_rejected(client: TestClient, body: dict) -> None:
    assert client.post("/jobs", json=body).status_code == 422


def test_get_job_returns_what_post_returned(client: TestClient) -> None:
    created = client.post("/jobs", json=BODY).json()
    fetched = client.get(f"/jobs/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_get_unknown_job_is_404(client: TestClient) -> None:
    response = client.get("/jobs/999999")
    assert response.status_code == 404
    # FastAPI's own message for a missing route is "Not Found", so this only
    # passes when get_job raises the 404 itself.
    assert response.json() == {"detail": "job not found"}


def test_job_status_is_derived_from_protein_statuses(client: TestClient, session: Session) -> None:
    created = client.post("/jobs", json=BODY).json()
    first, second = session.scalars(select(JobProtein).order_by(JobProtein.accession)).all()
    first.status, second.status = Status.SUCCEEDED, Status.FAILED
    session.flush()

    body = client.get(f"/jobs/{created['id']}").json()
    assert body["status"] == "succeeded"
    assert [p["status"] for p in body["proteins"]] == ["succeeded", "failed"]
