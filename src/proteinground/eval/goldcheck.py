"""Checks that every gold answer can be reached through the tools.

Gold answers are computed from raw database records by separate code (evals/build_questions.py).
This check runs each question's evidence calls through the tools and confirms the tool
output settles the item: the gold value for answerable items, found=false or a
contradicting value for planted ones. A tool bug therefore fails here instead of grading
itself correct.
"""

from __future__ import annotations

import json
from typing import Any

from proteinground.eval.schema import Question
from proteinground.fetch import Fetcher
from proteinground.tools import run_tool


def _outputs(fetcher: Fetcher, question: Question) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for call in question.evidence:
        text, is_error = run_tool(fetcher, call.name, call.input)
        if is_error:
            raise AssertionError(f"{question.id}: {call.name} errored: {text}")
        outputs.append(json.loads(text))
    return outputs


def _contains(obj: Any, value: Any) -> bool:
    if obj == value:
        return True
    if isinstance(obj, dict):
        return any(_contains(v, value) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains(v, value) for v in obj)
    if isinstance(obj, str) and isinstance(value, str):
        return obj.upper() == value.upper()
    if isinstance(obj, float) and isinstance(value, float):
        return abs(obj - value) < 1e-9
    return False


_METHOD = {
    "X-RAY DIFFRACTION": "xray",
    "ELECTRON MICROSCOPY": "em",
    "SOLUTION NMR": "nmr",
    "SOLID-STATE NMR": "nmr",
}


def _settles(family: str, question: Question, data: Any) -> bool:
    """Does this tool payload carry the gold value in the field that answers the item?"""
    gold = question.gold
    rows = data if isinstance(data, list) else []
    record = data if isinstance(data, dict) else {}
    if family == "residue_at":
        pos = question.evidence[0].input["start"]
        return any(
            r.get("position") == pos and r.get("one_letter") == gold
            for r in record.get("residues", [])
        )
    if family == "length":
        return bool(record.get("length") == gold)
    if family == "feature_range":
        return any([f.get("start"), f.get("end")] == list(gold) for f in record.get("features", []))
    if family == "method_resolution":
        methods = {_METHOD.get(m) for m in record.get("methods", [])}
        return gold["method"] in methods and record.get("resolution_angstrom") == gold["resolution"]
    if family == "ligand_comp_id":
        return any(lig.get("comp_id") == gold for lig in record.get("ligands", []))
    if family == "polymer_uniprot":
        return any(
            gold in p.get("uniprot_accessions", []) for p in record.get("polymer_entities", [])
        )
    if family == "best_xray":
        structures = record.get("structures", [])
        return bool(structures) and structures[0].get("pdb_id") in gold
    if family == "af_fraction":
        return bool(record.get("fraction_very_high") == gold)
    if family == "af_mean":
        return bool(record.get("mean_plddt") == gold)
    if family == "accession_lookup":
        return any(hit.get("accession") == gold for hit in rows)
    asked = question.evidence[0].input
    if family == "isoform_residue":
        return record.get("accession") == asked["accession"] and any(
            r.get("position") == asked["start"] and r.get("one_letter") == gold
            for r in record.get("residues", [])
        )
    if family in (
        "structure_numbering",
        "structure_residue",
        "insertion_code",
        "modelled_residue",
    ):
        author = f"{asked['residue_number']}{asked.get('insertion_code') or ''}"
        if record.get("author_residue") != author or record.get("observed") is not True:
            return False
        if question.answer_type == "residue":
            return bool(record.get("structure_residue") == gold)
        return bool(
            record.get("uniprot_position") == gold
            and record.get("uniprot_accession") in question.record_ids
        )
    if family == "engineered_mutation":
        change = (
            f"{record.get('uniprot_residue')}{record.get('uniprot_position')}"
            f"{record.get('structure_residue')}"
        )
        return record.get("matches_uniprot") is False and change == gold
    if family == "variant_lookup":
        return any(gold in v.get("changes", []) for v in record.get("variants", []))
    raise AssertionError(f"{question.id}: no gold check for family {family!r}")


def _shows(output: dict[str, Any], expected: dict[str, Any]) -> bool:
    """A structured signal: named fields of the payload, or words in the not-found note.

    {"data": {...}} needs found=true and every listed field to hold that value;
    {"note_contains": "..."} needs found=false and the phrase in the note.
    """
    if "note_contains" in expected:
        note = str(output.get("note") or "")
        return output.get("found") is False and str(expected["note_contains"]) in note
    data = output.get("data")
    fields = expected.get("data")
    return (
        output.get("found") is True
        and isinstance(data, dict)
        and isinstance(fields, dict)
        and all(_contains(data.get(key), value) for key, value in fields.items())
    )


def check(fetcher: Fetcher, question: Question) -> str | None:
    """Return None when the tools settle the item, else a reason."""
    outputs = _outputs(fetcher, question)
    if question.premise_ok and question.family == "obsolete_replacement":
        # The successor is named in the not-found note, not in a data field.
        wanted = {f"superseded by {pdb_id}" for pdb_id in question.gold}
        if any(
            o.get("found") is False and any(w in str(o.get("note") or "") for w in wanted)
            for o in outputs
        ):
            return None
        return f"the not-found note does not name the successor {question.gold!r}"
    if not question.premise_ok:
        expected = question.evidence_signal
        if expected == "not_found":
            return (
                None
                if any(not o.get("found", True) for o in outputs)
                else ("expected found=false from the evidence call")
            )
        if isinstance(expected, dict):
            return (
                None
                if any(_shows(o, expected) for o in outputs)
                else f"evidence does not show {expected!r}"
            )
        return (
            None
            if any(_contains(o, expected) for o in outputs)
            else (f"evidence does not show {expected!r}")
        )
    if any(_settles(question.family, question, o.get("data")) for o in outputs):
        return None
    return f"tool output does not carry gold {question.gold!r} in the answering field"
