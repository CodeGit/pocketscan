#!/usr/bin/env python3
"""Turn fpocket output for one protein into a result.json for `pocketscan_api.ingest`.

fpocket supplies rank, score, volume and the atoms lining each pocket. This step adds
the structural context fpocket does not: mean solvent accessibility (Shrake-Rupley,
square angstroms per residue) and mean pLDDT (AlphaFold stores it in the B-factor
column) over the residues lining each pocket.

The output is validated against the API's ResultIn schema in the tests.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import fmean
from typing import Any

from Bio.PDB.MMCIFParser import MMCIFParser
from Bio.PDB.SASA import ShrakeRupley
from Bio.PDB.Structure import Structure

type ResidueKey = tuple[str, int]  # (chain id, residue number)
type ResidueMetrics = dict[ResidueKey, tuple[float, float]]  # key -> (SASA in A^2, pLDDT)
type PocketResidues = list[tuple[str, int, str]]  # (chain id, residue number, residue name)


def parse_info(path: Path) -> dict[int, dict[str, float]]:
    """Read score and volume for each pocket from fpocket's *_info.txt."""
    pockets: dict[int, dict[str, float]] = {}
    current: dict[str, float] | None = None
    for line in path.read_text().splitlines():
        header = re.match(r"Pocket (\d+) :", line)
        if header:
            current = pockets.setdefault(int(header.group(1)), {})
            continue
        label, separator, value = line.partition(":")
        if current is not None and separator:
            # Exact labels only: "Druggability Score" and "Volume score" are other fields.
            if label.strip() == "Score":
                current["score"] = float(value)
            elif label.strip() == "Volume":
                current["volume_a3"] = float(value)
    return pockets


def parse_pocket_residues(path: Path) -> PocketResidues:
    """Distinct residues with at least one atom lining the pocket, in file order.

    fpocket's pocketN_atm.cif has ATOM rows of the form
    `ATOM id element atom alt resname chain resnum ins x y z ...`.
    """
    residues: PocketResidues = []
    seen: set[ResidueKey] = set()
    for line in path.read_text().splitlines():
        if not line.startswith("ATOM"):
            continue
        fields = line.split()
        resname, chain, number = fields[5], fields[6], int(fields[7])
        if (chain, number) not in seen:
            seen.add((chain, number))
            residues.append((chain, number, resname))
    return residues


def residue_metrics(structure: Structure) -> ResidueMetrics:
    """SASA and pLDDT for every residue of the model."""
    ShrakeRupley().compute(structure, level="R")
    metrics: ResidueMetrics = {}
    for residue in structure[0].get_residues():
        plddt = fmean(atom.get_bfactor() for atom in residue)
        metrics[(residue.get_parent().id, residue.id[1])] = (residue.sasa, plddt)
    return metrics


def load_structure(path: Path) -> Structure:
    return MMCIFParser(QUIET=True).get_structure("model", str(path))


def build_pockets(
    info: dict[int, dict[str, float]], fpocket_dir: Path, metrics: ResidueMetrics
) -> list[dict[str, Any]]:
    pockets = []
    for rank in sorted(info):
        residues = parse_pocket_residues(fpocket_dir / "pockets" / f"pocket{rank}_atm.cif")
        known = [
            metrics[(chain, number)] for chain, number, _ in residues if (chain, number) in metrics
        ]
        pockets.append(
            {
                "rank": rank,
                "score": info[rank]["score"],
                "volume_a3": info[rank]["volume_a3"],
                "mean_sasa_a2": fmean(sasa for sasa, _ in known) if known else None,
                "mean_plddt": fmean(plddt for _, plddt in known) if known else None,
                "residues": [f"{chain}:{number}:{name}" for chain, number, name in residues],
            }
        )
    return pockets


def build_result(
    *,
    meta: dict[str, Any],
    model: Path,
    fpocket_dir: Path,
    tool_version: str,
    params: dict[str, Any],
    structure_uri: str,
    output_uri: str,
) -> dict[str, Any]:
    """The ResultIn-shaped dict for one protein."""
    (info_file,) = fpocket_dir.glob("*_info.txt")
    pockets = build_pockets(
        parse_info(info_file), fpocket_dir, residue_metrics(load_structure(model))
    )
    return {
        "sequence": meta["sequence"],
        "structure": {
            "source": meta["source"],
            "source_version": meta["source_version"],
            "gcs_uri": structure_uri,
        },
        "run": {
            "tool": "fpocket",
            "tool_version": tool_version,
            "params": params,
            "status": "succeeded",
            "output_gcs_uri": output_uri,
        },
        "pockets": pockets,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--meta", type=Path, required=True, help="meta.json from fetch_alphafold.py"
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--fpocket-dir", type=Path, required=True)
    parser.add_argument("--tool-version", required=True)
    parser.add_argument("--params", required=True, help="the fpocket parameters, as JSON")
    parser.add_argument("--structure-uri", required=True)
    parser.add_argument("--output-uri", required=True)
    parser.add_argument("--out", type=Path, default=Path("result.json"))
    args = parser.parse_args(argv)

    result = build_result(
        meta=json.loads(args.meta.read_text()),
        model=args.model,
        fpocket_dir=args.fpocket_dir,
        tool_version=args.tool_version,
        params=json.loads(args.params),
        structure_uri=args.structure_uri,
        output_uri=args.output_uri,
    )
    args.out.write_text(json.dumps(result, indent=2))
    print(f"wrote {len(result['pockets'])} pockets to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
