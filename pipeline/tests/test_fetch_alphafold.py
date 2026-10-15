from pathlib import Path
from typing import Any

import fetch_alphafold
import pytest

ENTRY: dict[str, Any] = {
    "uniprotAccession": "P08100",
    "sequence": "MNGTEGPNFYVPFSNATGVV",
    "latestVersion": 6,
    "cifUrl": "https://alphafold.ebi.ac.uk/files/AF-P08100-F1-model_v6.cif",
}


def test_pick_entry_returns_the_exact_accession_not_an_isoform() -> None:
    isoform = {**ENTRY, "uniprotAccession": "P08100-2"}

    assert fetch_alphafold.pick_entry([isoform, ENTRY], "P08100") is ENTRY


def test_pick_entry_raises_when_alphafold_has_no_model() -> None:
    with pytest.raises(LookupError):
        fetch_alphafold.pick_entry([], "P08100")


def test_meta_records_the_sequence_and_model_version() -> None:
    assert fetch_alphafold.meta_from_entry(ENTRY) == {
        "accession": "P08100",
        "sequence": "MNGTEGPNFYVPFSNATGVV",
        "source": "alphafold",
        "source_version": "v6",
        "cif_url": ENTRY["cifUrl"],
    }


def test_main_writes_model_and_meta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_download(url: str) -> bytes:
        return (
            b'[{"uniprotAccession": "P08100", "sequence": "MNG", "latestVersion": 6, "cifUrl": "u"}]'
            if "api" in url
            else b"data_model"
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fetch_alphafold, "download", fake_download)

    assert fetch_alphafold.main(["P08100"]) == 0
    assert (tmp_path / "model.cif").read_bytes() == b"data_model"
    assert (tmp_path / "meta.json").exists()


def test_main_fails_cleanly_for_an_unknown_accession(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fetch_alphafold, "download", lambda url: b"[]")

    assert fetch_alphafold.main(["Q00000"]) == 1
    assert not (tmp_path / "model.cif").exists()
