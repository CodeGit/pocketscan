import hashlib
import json
from typing import Any


def sequence_hash(sequence: str) -> str:
    """Use hashed, cleaned, and uppercase sequence to identify proteins"""
    cleaned = "".join(sequence.split()).upper()
    return hashlib.sha256(cleaned.encode()).hexdigest()


def params_hash(params: dict[str, Any]) -> str:
    """Identity of a parameter set, for the analysis_run cache key."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
