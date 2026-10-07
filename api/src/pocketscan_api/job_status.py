from collections.abc import Iterable

from pocketscan_api.models import Status


def derive_job_status(statuses: Iterable[Status]) -> Status:
    """Derive the overall job status from the statuses of individual proteins."""
    unique__statuses = set(statuses)
    if unique__statuses <= {Status.PENDING}:
        return Status.PENDING
    if unique__statuses <= {Status.SUCCEEDED, Status.FAILED}:
        return Status.FAILED if unique__statuses == {Status.FAILED} else Status.SUCCEEDED
    return Status.RUNNING
