#!/usr/bin/env python3
"""Download the AlphaFold model for a UniProt accession.

Writes model.cif and meta.json (sequence, source, source_version) to the current
directory. Exits non-zero if AlphaFold has no model for the accession.
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

API = "https://alphafold.ebi.ac.uk/api/prediction/{accession}"


def pick_entry(entries: list[dict[str, Any]], accession: str) -> dict[str, Any]:
    """The prediction for exactly this accession (the API can also list isoforms)."""
    for entry in entries:
        if entry.get("uniprotAccession") == accession:
            return entry
    raise LookupError(f"AlphaFold has no model for {accession}")


def meta_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "accession": entry["uniprotAccession"],
        "sequence": entry["sequence"],
        "source": "alphafold",
        "source_version": f"v{entry['latestVersion']}",
        "cif_url": entry["cifUrl"],
    }


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 (fixed https URLs)
        return response.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accession")
    args = parser.parse_args(argv)

    try:
        entries = json.loads(download(API.format(accession=args.accession)))
        meta = meta_from_entry(pick_entry(entries, args.accession))
        Path("model.cif").write_bytes(download(meta["cif_url"]))
    except (LookupError, OSError, ValueError) as error:  # urllib errors are OSErrors
        print(f"fetch failed for {args.accession}: {error}", file=sys.stderr)
        return 1
    Path("meta.json").write_text(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
