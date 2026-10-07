import pytest

from pocketscan_api.job_status import derive_job_status
from pocketscan_api.models import Status

P, R, S, F = Status.PENDING, Status.RUNNING, Status.SUCCEEDED, Status.FAILED


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], P),
        ([P, P], P),
        ([R, P], R),
        ([S, P], R),
        ([F, P], R),
        ([R, F], R),
        ([S, S], S),
        ([S, F], S),
        ([F, F], F),
    ],
)
def test_job_status_is_derived_from_proteins(statuses: list[Status], expected: Status) -> None:
    assert derive_job_status(statuses) is expected
