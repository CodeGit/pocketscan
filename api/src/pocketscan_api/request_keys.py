import hashlib
import json
import re

# UniProt's documented accession format.
ACCESSION_PATTERN = re.compile(
    r"[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2}"
)
MAX_ACCESSIONS = 100


def normalise_accessions(accessions: list[str]) -> list[str]:
    """Strip, uppercase, validate, de-duplicate and sort."""
    cleaned = {accession.strip().upper() for accession in accessions}
    if not cleaned:
        raise ValueError("At least one accession is required")
    if len(cleaned) > MAX_ACCESSIONS:
        raise ValueError(f"At most {MAX_ACCESSIONS} accessions per job")
    invalid = sorted(a for a in cleaned if not ACCESSION_PATTERN.fullmatch(a))
    if invalid:
        raise ValueError(f"Not valid UniProt accessions: {', '.join(invalid)}")
    return sorted(cleaned)


def compute_request_key(analysis: str, accessions: list[str]) -> str:
    """A stable identity for a request, so repeats map to the same job."""
    canonical = json.dumps(
        {"analysis": analysis.strip().lower(), "accessions": normalise_accessions(accessions)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
