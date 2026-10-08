from typing import Any

import pytest
from pydantic import ValidationError

from pocketscan_api.models import JobProtein, Status
from pocketscan_api.schemas import JobCreate, JobProteinOut, ResultIn


def test_request_is_normalised() -> None:
    job = JobCreate(accessions=[" q9y6k9", "P08100", "P08100"])
    assert job.accessions == ["P08100", "Q9Y6K9"]
    assert job.analysis == "fpocket"


def test_unknown_analysis_is_rejected() -> None:
    with pytest.raises(ValidationError):
        JobCreate(analysis="nope", accessions=["P08100"])


def test_invalid_accession_is_rejected() -> None:
    with pytest.raises(ValidationError):
        JobCreate(accessions=["not-an-accession"])


def test_job_protein_out_reads_from_an_orm_object() -> None:
    row = JobProtein(accession="P08100", status=Status.FAILED, error="model not found")
    out = JobProteinOut.model_validate(row)
    assert (out.accession, out.status, out.error) == ("P08100", Status.FAILED, "model not found")


def test_result_body_parses(result_body: dict[str, Any]) -> None:
    result = ResultIn(**result_body)
    assert result.run.status == Status.SUCCEEDED
    assert [p.rank for p in result.pockets] == [1, 2]


def test_duplicate_pocket_ranks_are_rejected(result_body: dict[str, Any]) -> None:
    result_body["pockets"][1]["rank"] = 1
    with pytest.raises(ValidationError):
        ResultIn(**result_body)
