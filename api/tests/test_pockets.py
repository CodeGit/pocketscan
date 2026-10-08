import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pocketscan_api.ingest import mark_status, record_result
from pocketscan_api.models import Status
from pocketscan_api.schemas import ResultIn

ACCESSIONS = ["P08100", "Q9Y6K9"]


@pytest.fixture
def second_result_body(result_body: dict[str, Any]) -> dict[str, Any]:
    """A different protein: other sequence, other scores, and no null SASA."""
    body = copy.deepcopy(result_body)
    body["sequence"] = "MTTTTTTTTTTTTTT"
    body["pockets"][0].update(score=0.7, volume_a3=300.0, mean_sasa_a2=10.0, mean_plddt=60.0)
    body["pockets"][1].update(score=0.2, volume_a3=90.0, mean_sasa_a2=35.0, mean_plddt=88.0)
    return body


@pytest.fixture
def job_id(
    client: TestClient,
    session: Session,
    result_body: dict[str, Any],
    second_result_body: dict[str, Any],
) -> int:
    """A job with both proteins analysed. P08100 has the first body, Q9Y6K9 the second."""
    job = client.post("/jobs", json={"accessions": ACCESSIONS}).json()
    record_result(session, job["id"], "P08100", ResultIn(**result_body))
    record_result(session, job["id"], "Q9Y6K9", ResultIn(**second_result_body))
    return job["id"]


def pockets(client: TestClient, job_id: int, **params: str | float) -> list[dict[str, Any]]:
    response = client.get(f"/jobs/{job_id}/pockets", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def keys(rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    return [(row["accession"], row["rank"]) for row in rows]


def test_default_order_is_rank_then_accession(client: TestClient, job_id: int) -> None:
    rows = pockets(client, job_id)

    assert keys(rows) == [("P08100", 1), ("Q9Y6K9", 1), ("P08100", 2), ("Q9Y6K9", 2)]
    assert rows[0] == {
        "accession": "P08100",
        "rank": 1,
        "score": 0.9,
        "volume_a3": 410.5,
        "mean_sasa_a2": 22.1,
        "mean_plddt": 91.3,
        "residues": ["A:12:LEU", "A:13:GLY"],
    }


def test_sort_by_score_descending_across_proteins(client: TestClient, job_id: int) -> None:
    rows = pockets(client, job_id, sort="score", order="desc")

    assert [row["score"] for row in rows] == [0.9, 0.7, 0.4, 0.2]


def test_null_values_sort_last_in_both_directions(client: TestClient, job_id: int) -> None:
    for order in ("asc", "desc"):
        rows = pockets(client, job_id, sort="mean_sasa_a2", order=order)
        assert rows[-1]["mean_sasa_a2"] is None  # P08100 rank 2 has no SASA


def test_filters_narrow_the_rows(client: TestClient, job_id: int) -> None:
    assert keys(pockets(client, job_id, min_score=0.5, sort="score", order="desc")) == [
        ("P08100", 1),
        ("Q9Y6K9", 1),
    ]
    assert keys(pockets(client, job_id, min_volume_a3=400)) == [("P08100", 1)]
    assert keys(pockets(client, job_id, min_mean_plddt=85, sort="score", order="desc")) == [
        ("P08100", 1),
        ("Q9Y6K9", 2),
    ]


def test_accession_filter_is_case_insensitive(client: TestClient, job_id: int) -> None:
    rows = pockets(client, job_id, accession="q9y6k9")

    assert keys(rows) == [("Q9Y6K9", 1), ("Q9Y6K9", 2)]


def test_limit_and_offset_page_through_a_stable_order(client: TestClient, job_id: int) -> None:
    everything = keys(pockets(client, job_id))

    assert keys(pockets(client, job_id, limit=3)) == everything[:3]
    assert keys(pockets(client, job_id, limit=3, offset=3)) == everything[3:]


def test_only_succeeded_proteins_contribute_pockets(
    client: TestClient, session: Session, job_id: int
) -> None:
    mark_status(session, job_id, "Q9Y6K9", Status.FAILED, error="boom")

    assert {row["accession"] for row in pockets(client, job_id)} == {"P08100"}


def test_job_with_nothing_analysed_has_an_empty_list(client: TestClient) -> None:
    job = client.post("/jobs", json={"accessions": ["P08100"]}).json()

    assert pockets(client, job["id"]) == []


def test_unknown_job_is_404(client: TestClient) -> None:
    response = client.get("/jobs/999999/pockets")

    assert response.status_code == 404
    assert response.json() == {"detail": "job not found"}


@pytest.mark.parametrize(
    "params",
    [{"sort": "nope"}, {"order": "sideways"}, {"limit": 0}, {"limit": 1001}, {"offset": -1}],
)
def test_bad_query_parameters_are_rejected(
    client: TestClient, job_id: int, params: dict[str, Any]
) -> None:
    assert client.get(f"/jobs/{job_id}/pockets", params=params).status_code == 422
