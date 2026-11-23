"""Build the question set and freeze the database snapshot it was computed from.

    uv run python evals/build_questions.py [--seed 7] [--refresh]

Gold answers are computed here from the raw API records, with code that does not share
parsing logic with the tools (only URL builders are shared, so the snapshot holds the
exact responses the tools will request). Every planted false premise is checked against
the data before it is written.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from proteinground import alphafold, pdb, uniprot
from proteinground.eval.schema import Question, ToolCall, write_questions
from proteinground.fetch import Fetcher, Mode
from proteinground.tools import run_tool

HERE = Path(__file__).parent
SNAPSHOT = HERE / "snapshot"
QUESTIONS = HERE / "questions.jsonl"
MANIFEST = HERE / "MANIFEST.json"

# Well-studied proteins with UniProtKB, PDB and AlphaFold DB records.
PANEL = [
    "P04637", "P01116", "P00533", "P01308", "P68871", "P69905", "P61626", "P42212",
    "P0DTC2", "Q99ZW2", "P00519", "P15056", "P02144", "P00698",
]  # fmt: skip
EXTRA_ACCESSIONS = ["P00520"]  # mouse ABL1, the chain actually in PDB 1IEP
METHOD_PDB = ["4HHB", "1IEP", "6VXX", "1EMA", "1M17", "3OG7", "6OIM", "1TUP"]
LIGANDS = {  # PDB entry -> (drug, chemical component ID)
    "1IEP": ("imatinib", "STI"),
    "1M17": ("erlotinib", "AQ4"),
    "3OG7": ("vemurafenib", "032"),
    "6OIM": ("sotorasib", "MOV"),
}
POLYMER_PDB = ["1IEP", "6OIM", "1EMA"]
BEST_XRAY = ["P01116", "P61626", "P42212", "P00533"]
AF_FRACTION = ["P04637", "P01116", "P00533", "P01308", "P0DTC2", "P15056"]
AF_MEAN = ["Q99ZW2", "P00519", "P68871"]
LENGTH = ["P04637", "P00533", "Q99ZW2", "P0DTC2", "P15056"]
GENE_LOOKUP = [("BRAF", "P15056"), ("MB", "P02144")]
# Valid-format IDs to try for "this entry does not exist" items, first two 404s win.
ABSENT_PDB_CANDIDATES = ["9ZZZ", "9ZZY", "9ZYZ", "9YZZ", "8ZZZ", "9ZZX", "9ZXZ", "9XZZ"]
# Calls the tests replay for tools no question exercises: residue numbering, variants,
# isoforms and an obsolete entry. They add records to the snapshot; no gold answer uses them.
EXTRA_CALLS: list[tuple[str, dict[str, Any]]] = [
    ("map_structure_residue", {"pdb_id": "1IEP", "chain": "A", "residue_number": 315}),
    ("map_structure_residue", {"pdb_id": "1IEP", "chain": "A", "residue_number": 224}),
    ("map_structure_residue", {"pdb_id": "1IEP", "chain": "B", "uniprot_position": 400}),
    ("map_structure_residue", {"pdb_id": "4HHB", "chain": "B", "residue_number": 6}),
    ("map_structure_residue", {"pdb_id": "6OIM", "chain": "A", "residue_number": 12}),
    (
        "map_structure_residue",
        {"pdb_id": "1PPB", "chain": "H", "residue_number": 60, "insertion_code": "A"},
    ),
    ("get_variants", {"accession": "P01116", "start": 12}),
    ("get_variants", {"accession": "P01308", "start": 3}),
    ("get_sequence_window", {"accession": "P04637-2", "start": 330, "end": 341}),
    ("get_sequence_window", {"accession": "P04637-99", "start": 1, "end": 1}),
    ("get_structure", {"pdb_id": "1HHB"}),
]
METHOD_CATEGORY = {
    "X-RAY DIFFRACTION": "xray",
    "ELECTRON MICROSCOPY": "em",
    "SOLUTION NMR": "nmr",
    "SOLID-STATE NMR": "nmr",
}


def call(name: str, **kwargs: Any) -> ToolCall:
    return ToolCall(name=name, input=kwargs)


class Raw:
    """Raw records, fetched once each and frozen into the snapshot."""

    def __init__(self, fetcher: Fetcher) -> None:
        self.f = fetcher

    def entry(self, accession: str) -> dict[str, Any]:
        response = self.f.get_json(uniprot.entry_url(accession))
        assert response.ok, f"UniProtKB {accession}: HTTP {response.status}"
        body: dict[str, Any] = response.body
        return body

    def pdb_entry(self, pdb_id: str) -> tuple[int, dict[str, Any] | None]:
        response = self.f.get_json(pdb.entry_url(pdb_id))
        return response.status, response.body if response.ok else None

    def nonpolymers(self, pdb_id: str) -> list[dict[str, Any]]:
        _, body = self.pdb_entry(pdb_id)
        assert body is not None
        ids = body["rcsb_entry_container_identifiers"].get("non_polymer_entity_ids") or []
        out = []
        for eid in ids:
            got = self.f.get_json(pdb.nonpolymer_url(pdb_id, str(eid)))
            out.append(got.body["pdbx_entity_nonpoly"])
        return out

    def polymer_uniprot(self, pdb_id: str) -> list[str]:
        _, body = self.pdb_entry(pdb_id)
        assert body is not None
        accessions: list[str] = []
        for eid in body["rcsb_entry_container_identifiers"].get("polymer_entity_ids") or []:
            got = self.f.get_json(pdb.polymer_url(pdb_id, str(eid))).body
            ids = got.get("rcsb_polymer_entity_container_identifiers", {}).get("uniprot_ids")
            accessions.extend(ids or [])
        return accessions

    def af(self, accession: str) -> dict[str, Any]:
        response = self.f.get_json(alphafold.prediction_url(accession))
        assert response.ok, f"AlphaFold DB {accession}: HTTP {response.status}"
        models = [m for m in response.body if m.get("uniprotAccession") == accession]
        models.sort(key=lambda m: not str(m.get("entryId", "")).endswith("-F1"))
        return dict(models[0])


def label(entry: dict[str, Any]) -> str:
    desc = entry.get("proteinDescription", {}).get("recommendedName", {})
    name = desc.get("fullName", {}).get("value", "protein")
    organism = entry.get("organism", {}).get("scientificName", "")
    return f"{name}, {organism}"


def feature_spans(entry: dict[str, Any], ftype: str) -> list[tuple[str, int, int]]:
    spans = []
    for feat in entry.get("features", []):
        if feat.get("type") != ftype:
            continue
        loc = feat.get("location", {})
        start, end = loc.get("start", {}).get("value"), loc.get("end", {}).get("value")
        if isinstance(start, int) and isinstance(end, int):
            spans.append((str(feat.get("description") or ""), start, end))
    return spans


def xray_resolutions(entry: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for xref in entry.get("uniProtKBCrossReferences", []):
        if xref.get("database") != "PDB":
            continue
        props = {p["key"]: p["value"] for p in xref.get("properties", [])}
        match = re.match(r"([0-9.]+)", props.get("Resolution", ""))
        if props.get("Method") == "X-ray" and match:
            out[str(xref["id"]).upper()] = float(match.group(1))
    return out


def build(fetcher: Fetcher, seed: int) -> list[Question]:
    raw = Raw(fetcher)
    rng = random.Random(seed)
    entries = {acc: raw.entry(acc) for acc in [*PANEL, *EXTRA_ACCESSIONS]}
    qs: list[Question] = []

    # Residue at a position: one per panel protein, at a seeded random position.
    for acc in PANEL[:12]:
        seq = entries[acc]["sequence"]["value"]
        pos = rng.randint(1, len(seq))
        qs.append(
            Question(
                id=f"residue-{acc}-{pos}",
                family="residue_at",
                premise_ok=True,
                text=(
                    f"In UniProtKB entry {acc} ({label(entries[acc])}), which amino acid is at "
                    f"position {pos} of the canonical sequence? Answer with the one-letter code."
                ),
                answer_type="residue",
                gold=seq[pos - 1],
                record_ids=[acc],
                evidence=[call("get_sequence_window", accession=acc, start=pos, end=pos)],
            )
        )

    for acc in LENGTH:
        qs.append(
            Question(
                id=f"length-{acc}",
                family="length",
                premise_ok=True,
                text=(
                    f"How many residues long is the canonical sequence of UniProtKB entry {acc} "
                    f"({label(entries[acc])})?"
                ),
                answer_type="int",
                gold=entries[acc]["sequence"]["length"],
                record_ids=[acc],
                evidence=[call("get_protein", accession=acc)],
            )
        )

    # Feature spans: every signal peptide, and kinase domains.
    for acc in PANEL:
        for ftype, needle in (("Signal", ""), ("Domain", "kinase")):
            spans = [s for s in feature_spans(entries[acc], ftype) if needle in s[0].lower()]
            if len(spans) != 1:
                continue
            desc, start, end = spans[0]
            what = "signal peptide" if ftype == "Signal" else f"{desc[:1].lower()}{desc[1:]} domain"
            qs.append(
                Question(
                    id=f"feature-{acc}-{ftype.lower()}",
                    family="feature_range",
                    premise_ok=True,
                    text=(
                        f"According to UniProtKB, which residues does the {what} of {acc} "
                        f"({label(entries[acc])}) span? Answer as start-end."
                    ),
                    answer_type="range",
                    gold=[start, end],
                    record_ids=[acc],
                    evidence=[call("get_features", accession=acc, feature_type=ftype)],
                )
            )

    for pdb_id in METHOD_PDB:
        status, body = raw.pdb_entry(pdb_id)
        assert body is not None, f"PDB {pdb_id}: HTTP {status}"
        method = METHOD_CATEGORY[body["exptl"][0]["method"]]
        resolution = float(body["rcsb_entry_info"]["resolution_combined"][0])
        qs.append(
            Question(
                id=f"method-{pdb_id}",
                family="method_resolution",
                premise_ok=True,
                text=(
                    f"Which experimental method was used for PDB entry {pdb_id}, and at what "
                    "resolution? Answer as '<method>, <resolution> Å'."
                ),
                answer_type="method_resolution",
                gold={"method": method, "resolution": resolution},
                tolerance=0.01,
                record_ids=[pdb_id],
                evidence=[call("get_structure", pdb_id=pdb_id)],
            )
        )

    for pdb_id, (drug, comp_id) in LIGANDS.items():
        comps = [n["comp_id"] for n in raw.nonpolymers(pdb_id)]
        assert comp_id in comps, f"{pdb_id}: {comp_id} not in {comps}"
        qs.append(
            Question(
                id=f"ligand-{pdb_id}",
                family="ligand_comp_id",
                premise_ok=True,
                text=(
                    f"PDB entry {pdb_id} has {drug} bound. What is the chemical component ID "
                    f"of {drug} in that entry?"
                ),
                answer_type="token",
                gold=comp_id,
                record_ids=[pdb_id],
                evidence=[call("get_structure", pdb_id=pdb_id)],
                # Naming another component of the same entry is a wrong or hedged answer.
                reject=sorted({c for c in comps if c != comp_id and c not in pdb.ADDITIVES}),
            )
        )

    for pdb_id in POLYMER_PDB:
        accessions = sorted(set(raw.polymer_uniprot(pdb_id)))
        assert len(accessions) == 1, f"{pdb_id}: expected one UniProt mapping, {accessions}"
        qs.append(
            Question(
                id=f"polymer-{pdb_id}",
                family="polymer_uniprot",
                premise_ok=True,
                text=(
                    f"Which UniProtKB accession does the protein chain in PDB entry {pdb_id} "
                    "map to?"
                ),
                answer_type="token",
                gold=accessions[0],
                record_ids=[pdb_id],
                evidence=[call("get_structure", pdb_id=pdb_id)],
            )
        )

    for acc in BEST_XRAY:
        resolutions = xray_resolutions(entries[acc])
        best = min(resolutions.values())
        tied = sorted(k for k, v in resolutions.items() if v == best)
        qs.append(
            Question(
                id=f"bestxray-{acc}",
                family="best_xray",
                premise_ok=True,
                text=(
                    f"Of the X-ray structures that UniProtKB entry {acc} ({label(entries[acc])}) "
                    "cross-references, which PDB entry has the best (lowest) resolution? "
                    "Give the PDB ID."
                ),
                answer_type="id_set",
                gold=tied,
                record_ids=[acc, *tied],
                evidence=[call("list_structures", accession=acc, method="X-ray", limit=5)],
            )
        )

    for acc in AF_FRACTION:
        model = raw.af(acc)
        qs.append(
            Question(
                id=f"affraction-{acc}",
                family="af_fraction",
                premise_ok=True,
                text=(
                    f"In the AlphaFold DB model for UniProtKB {acc} ({label(entries[acc])}), "
                    "what fraction of residues has very high confidence (pLDDT above 90)? "
                    "Give a number between 0 and 1."
                ),
                answer_type="float",
                gold=float(model["fractionPlddtVeryHigh"]),
                tolerance=0.01,
                record_ids=[str(model["entryId"]), f"alphafold.ebi.ac.uk/entry/{acc}", acc],
                evidence=[call("get_alphafold_summary", accession=acc)],
            )
        )
    for acc in AF_MEAN:
        model = raw.af(acc)
        qs.append(
            Question(
                id=f"afmean-{acc}",
                family="af_mean",
                premise_ok=True,
                text=(
                    f"What is the mean pLDDT of the AlphaFold DB model for UniProtKB {acc} "
                    f"({label(entries[acc])})?"
                ),
                answer_type="float",
                gold=round(float(model["globalMetricValue"]), 2),
                tolerance=0.5,
                record_ids=[str(model["entryId"]), f"alphafold.ebi.ac.uk/entry/{acc}", acc],
                evidence=[call("get_alphafold_summary", accession=acc)],
            )
        )

    for gene, acc in GENE_LOOKUP:
        assert entries[acc]["genes"][0]["geneName"]["value"] == gene
        qs.append(
            Question(
                id=f"lookup-{gene}",
                family="accession_lookup",
                premise_ok=True,
                text=(
                    f"What is the accession of the reviewed UniProtKB entry for the human "
                    f"{gene} gene?"
                ),
                answer_type="token",
                gold=acc,
                record_ids=[acc],
                evidence=[call("search_proteins", query=f"gene:{gene}", taxon_id=9606)],
            )
        )

    qs.extend(planted(raw, entries))
    return qs


def planted(raw: Raw, entries: dict[str, dict[str, Any]]) -> list[Question]:
    """False-premise items. Each premise is checked against the data first."""
    out: list[Question] = []

    def add(
        qid: str, text: str, trap: str, record_ids: list[str], evidence: ToolCall, signal: Any
    ) -> None:
        out.append(
            Question(
                id=f"trap-{qid}",
                family="false_premise",
                premise_ok=False,
                text=text,
                answer_type=None,
                trap=trap,
                record_ids=record_ids,
                evidence=[evidence],
                evidence_signal=signal,
            )
        )

    absent = [c for c in ABSENT_PDB_CANDIDATES if raw.pdb_entry(c)[0] == 404][:2]
    assert len(absent) == 2, "need two unassigned PDB IDs; extend the candidate list"
    for pdb_id in absent:
        add(
            f"absent-{pdb_id}",
            f"What is the resolution of the structure in PDB entry {pdb_id}?",
            f"PDB entry {pdb_id} does not exist",
            [pdb_id],
            call("get_structure", pdb_id=pdb_id),
            "not_found",
        )

    hba = entries["P69905"]
    assert "alpha" in label(hba).lower()
    add(
        "p69905-beta",
        "UniProtKB entry P69905 is human hemoglobin subunit beta. How many residues long is "
        "its canonical sequence?",
        "P69905 is hemoglobin subunit alpha; beta is P68871",
        ["P69905"],
        call("get_protein", accession="P69905"),
        "Hemoglobin subunit alpha",
    )

    ins = entries["P01308"]
    assert ins["sequence"]["length"] < 450
    add(
        "p01308-pos450",
        "In UniProtKB entry P01308 (human insulin), which amino acid is at position 450?",
        f"P01308 has only {ins['sequence']['length']} residues",
        ["P01308"],
        call("get_sequence_window", accession="P01308", start=450, end=450),
        "not_found",
    )
    assert not feature_spans(ins, "Domain")
    add(
        "p01308-kinase",
        "According to UniProtKB, which residues does the protein kinase domain of P01308 "
        "(human insulin) span?",
        "insulin has no kinase domain; its receptor does",
        ["P01308"],
        call("get_features", accession="P01308", feature_type="Domain"),
        "not_found",
    )

    missing = raw.f.get_json(uniprot.entry_url("Q00000"))
    assert missing.status in (400, 404)
    assert raw.f.get_json(alphafold.prediction_url("Q00000")).status in (400, 404)
    add(
        "q00000-af",
        "What is the mean pLDDT of the AlphaFold DB model for UniProtKB accession Q00000?",
        "Q00000 is not a UniProtKB entry and has no AlphaFold model",
        ["Q00000"],
        call("get_alphafold_summary", accession="Q00000"),
        "not_found",
    )

    _, hhb = raw.pdb_entry("4HHB")
    assert hhb is not None and hhb["exptl"][0]["method"] == "X-RAY DIFFRACTION"
    add(
        "4hhb-cryoem",
        "PDB entry 4HHB is a cryo-EM structure. At what resolution was it determined?",
        "4HHB was solved by X-ray diffraction",
        ["4HHB"],
        call("get_structure", pdb_id="4HHB"),
        "X-RAY DIFFRACTION",
    )

    _, vxx = raw.pdb_entry("6VXX")
    assert vxx is not None and vxx["exptl"][0]["method"] == "ELECTRON MICROSCOPY"
    add(
        "6vxx-xray",
        "What is the resolution of the X-ray crystal structure in PDB entry 6VXX?",
        "6VXX is a cryo-EM structure, not X-ray",
        ["6VXX"],
        call("get_structure", pdb_id="6VXX"),
        "ELECTRON MICROSCOPY",
    )

    assert raw.polymer_uniprot("1IEP") == ["P00520"]
    add(
        "1iep-human",
        "PDB entry 1IEP shows human ABL1 (UniProtKB P00519) bound to imatinib. What is the "
        "resolution of that structure?",
        "the chain in 1IEP is mouse Abl (P00520), not human ABL1",
        ["1IEP", "P00520"],
        call("get_structure", pdb_id="1IEP"),
        "P00520",
    )

    gfp = entries["P42212"]
    assert gfp["organism"]["scientificName"] == "Aequorea victoria"
    add(
        "p42212-human",
        "UniProtKB entry P42212, green fluorescent protein, comes from Homo sapiens. How "
        "long is its canonical sequence?",
        "P42212 is from the jellyfish Aequorea victoria",
        ["P42212"],
        call("get_protein", accession="P42212"),
        "Aequorea victoria",
    )

    for acc, ftype, what, trap in (
        ("Q99ZW2", "Signal", "signal peptide", "Cas9 has no annotated signal peptide"),
        (
            "P02144",
            "Active site",
            "annotated active-site residue",
            "myoglobin has no annotated active site",
        ),
        (
            "P68871",
            "Transmembrane",
            "transmembrane helix",
            "hemoglobin beta has no transmembrane region",
        ),
    ):
        assert not feature_spans(entries[acc], ftype)
        assert all(f.get("type") != ftype for f in entries[acc].get("features", []))
        add(
            f"{acc.lower()}-{ftype.lower().replace(' ', '')}",
            f"According to UniProtKB, where is the {what} of {acc} ({label(entries[acc])})? "
            "Give residue positions.",
            trap,
            [acc],
            call("get_features", accession=acc, feature_type=ftype),
            "not_found",
        )
    return out


def prewarm(fetcher: Fetcher, questions: list[Question]) -> None:
    """Record what an agent is likely to request beyond the gold records."""
    for q in questions:
        for ev in q.evidence:
            run_tool(fetcher, ev.name, ev.input)
    for acc in [*PANEL, *EXTRA_ACCESSIONS]:
        run_tool(fetcher, "get_alphafold_summary", {"accession": acc})
        run_tool(fetcher, "search_proteins", {"query": f"accession:{acc}"})
    for acc in BEST_XRAY:
        for ref in uniprot.list_structures(fetcher, acc, "X-ray", 3).data.structures:  # type: ignore[union-attr]
            run_tool(fetcher, "get_structure", {"pdb_id": ref.pdb_id})
    for gene, _ in GENE_LOOKUP:
        run_tool(fetcher, "search_proteins", {"query": gene, "taxon_id": 9606})
    for name, arguments in EXTRA_CALLS:
        text, is_error = run_tool(fetcher, name, arguments)
        assert not is_error, f"{name}({arguments}) failed: {text}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--refresh", action="store_true", help="refetch everything live")
    args = parser.parse_args()
    if args.refresh and SNAPSHOT.exists():
        for path in SNAPSHOT.glob("*.json.gz"):
            path.unlink()
    fetcher = Fetcher(cache_dir=SNAPSHOT, mode=Mode.CACHE_FIRST)
    questions = build(fetcher, args.seed)
    prewarm(fetcher, questions)
    write_questions(QUESTIONS, questions)
    release = fetcher.get_json(uniprot.entry_url("P04637")).headers.get("x-uniprot-release")
    families: dict[str, int] = {}
    for q in questions:
        families[q.family] = families.get(q.family, 0) + 1
    MANIFEST.write_text(
        json.dumps(
            {
                "built_at": datetime.now(UTC).strftime("%Y-%m-%d"),
                "seed": args.seed,
                "uniprot_release": release,
                "alphafold_model_version": alphafold.get_alphafold_summary(
                    fetcher, "P04637"
                ).data.model_version,  # type: ignore[union-attr]
                "questions": len(questions),
                "answerable": sum(q.premise_ok for q in questions),
                "planted_false_premise": sum(not q.premise_ok for q in questions),
                "families": families,
                "snapshot_files": len(list(SNAPSHOT.glob("*.json.gz"))),
            },
            indent=2,
        )
        + "\n"
    )
    print(MANIFEST.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
