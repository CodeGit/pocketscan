import json
from pathlib import Path
from typing import Any

import analyse
import pytest
from Bio.PDB.PDBParser import PDBParser
from pocketscan_api.schemas import ResultIn

FIXTURES = Path(__file__).parent / "fixtures"
MODEL = FIXTURES / "model.cif"
FPOCKET_DIR = FIXTURES / "fpocket"

META = {
    "accession": "P08100",
    "sequence": "MNGTEGPNFYVPFSNATGVV",
    "source": "alphafold",
    "source_version": "v6",
}
PARAMS = {"min_alpha_sphere_radius": 3.4, "max_alpha_sphere_radius": 6.2, "min_alpha_spheres": 15}


@pytest.fixture(scope="module")
def result() -> dict[str, Any]:
    return analyse.build_result(
        meta=META,
        model=MODEL,
        fpocket_dir=FPOCKET_DIR,
        tool_version="4.0+4bb0d84",
        params=PARAMS,
        structure_uri="file:///results/P08100/model.cif",
        output_uri="file:///results/P08100/model_out",
    )


def test_parse_info_reads_score_and_volume_not_the_lookalike_fields() -> None:
    info = analyse.parse_info(FPOCKET_DIR / "model_info.txt")

    assert sorted(info) == [1, 2, 3]
    assert info[1] == {"score": 0.136, "volume_a3": 603.489}
    assert info[2] == {"score": 0.049, "volume_a3": 84.536}


def test_parse_pocket_residues_are_distinct_and_in_file_order() -> None:
    residues = analyse.parse_pocket_residues(FPOCKET_DIR / "pockets" / "pocket1_atm.cif")

    assert residues[:2] == [("A", 207, "MET"), ("A", 208, "PHE")]
    assert len({(chain, number) for chain, number, _ in residues}) == len(residues)


TINY_PDB = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 90.00           N
ATOM      2  CA  ALA A   1       1.450   0.000   0.000  1.00 90.00           C
ATOM      3  N   GLY A   2       2.000   1.300   0.000  1.00 50.00           N
ATOM      4  CA  GLY A   2       3.400   1.400   0.000  1.00 50.00           C
END
"""


def test_residue_metrics_take_plddt_from_the_bfactor_and_give_each_residue_a_sasa(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tiny.pdb"
    path.write_text(TINY_PDB)
    structure = PDBParser(QUIET=True).get_structure("tiny", str(path))

    metrics = analyse.residue_metrics(structure)

    assert set(metrics) == {("A", 1), ("A", 2)}
    assert metrics[("A", 1)][1] == pytest.approx(90.0)
    assert metrics[("A", 2)][1] == pytest.approx(50.0)
    assert all(sasa > 0 for sasa, _ in metrics.values())


def test_result_has_one_entry_per_pocket_in_rank_order(result: dict[str, Any]) -> None:
    assert [pocket["rank"] for pocket in result["pockets"]] == [1, 2, 3]
    first = result["pockets"][0]
    assert (first["score"], first["volume_a3"]) == (0.136, 603.489)
    assert first["residues"][:2] == ["A:207:MET", "A:208:PHE"]


def test_pocket_context_values_are_physically_plausible(result: dict[str, Any]) -> None:
    for pocket in result["pockets"]:
        assert pocket["mean_sasa_a2"] is not None and 0 < pocket["mean_sasa_a2"] < 300
        assert pocket["mean_plddt"] is not None and 0 <= pocket["mean_plddt"] <= 100


def test_result_carries_provenance_and_the_cache_key_inputs(result: dict[str, Any]) -> None:
    assert result["sequence"] == META["sequence"]
    assert result["structure"] == {
        "source": "alphafold",
        "source_version": "v6",
        "gcs_uri": "file:///results/P08100/model.cif",
    }
    assert result["run"]["tool"] == "fpocket"
    assert result["run"]["tool_version"] == "4.0+4bb0d84"
    assert result["run"]["params"] == PARAMS
    assert result["run"]["status"] == "succeeded"


def test_result_is_accepted_by_the_apis_schema(result: dict[str, Any]) -> None:
    """The contract between the pipeline and ingest: if this fails, RECORD would too."""
    parsed = ResultIn.model_validate(result)

    assert len(parsed.pockets) == 3


def test_cli_writes_result_json(tmp_path: Path) -> None:
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META))
    out = tmp_path / "result.json"

    code = analyse.main(
        [
            "--meta", str(meta),
            "--model", str(MODEL),
            "--fpocket-dir", str(FPOCKET_DIR),
            "--tool-version", "4.0+4bb0d84",
            "--params", json.dumps(PARAMS),
            "--structure-uri", "file:///m.cif",
            "--output-uri", "file:///out",
            "--out", str(out),
        ]
    )  # fmt: skip

    assert code == 0
    ResultIn.model_validate_json(out.read_text())
