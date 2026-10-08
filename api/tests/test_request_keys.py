import pytest

from pocketscan_api.request_keys import MAX_ACCESSIONS, compute_request_key


def test_key_ignores_order_case_whitespace_and_duplicates() -> None:
    one = compute_request_key("fpocket", ["P08100", "Q9Y6K9"])
    two = compute_request_key(" FPOCKET ", [" q9y6k9", "p08100", "P08100"])
    assert one == two


def test_key_changes_with_analysis_or_accessions() -> None:
    base = compute_request_key("fpocket", ["P08100"])
    assert base != compute_request_key("other", ["P08100"])
    assert base != compute_request_key("fpocket", ["P08100", "Q9Y6K9"])


@pytest.mark.parametrize(
    "accessions",
    [
        [],
        ["not-an-accession"],
        ["P08100", "12345"],
        [f"P{n:05d}" for n in range(MAX_ACCESSIONS + 1)],
    ],
)
def test_bad_batches_are_rejected(accessions: list[str]) -> None:
    with pytest.raises(ValueError):
        compute_request_key("fpocket", accessions)
