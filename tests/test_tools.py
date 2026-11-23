"""Tool behaviour against the frozen snapshot: no network."""

from __future__ import annotations

import json

import pytest

from proteinground import alphafold, pdb, uniprot
from proteinground.alphafold import low_confidence_regions
from proteinground.fetch import Fetcher
from proteinground.tools import TOOLS, anthropic_tool_defs, run_tool


def test_protein_summary_carries_its_source(offline: Fetcher) -> None:
    result = uniprot.get_protein(offline, "p04637 ")
    assert result.found and result.data is not None
    assert (result.data.gene, result.data.length, result.data.organism) == (
        "TP53",
        393,
        "Homo sapiens",
    )
    assert result.sources[0].url == "https://www.uniprot.org/uniprotkb/P04637/entry"
    assert result.sources[0].release == "2026_04"


def test_sequence_window_numbers_every_residue(offline: Fetcher) -> None:
    result = uniprot.get_sequence_window(offline, "P04637", 173, 177)
    assert result.data is not None
    assert [(r.position, r.one_letter) for r in result.data.residues] == [
        (173, "V"),
        (174, "R"),
        (175, "R"),
        (176, "C"),
        (177, "P"),
    ]
    assert result.data.residues[2].three_letter == "Arg"


def test_sequence_window_refuses_positions_past_the_end(offline: Fetcher) -> None:
    result = uniprot.get_sequence_window(offline, "P01308", 450, 450)
    assert not result.found and result.note is not None and "110 residues" in result.note


def test_sequence_window_caps_and_clips(offline: Fetcher) -> None:
    capped = uniprot.get_sequence_window(offline, "P04637", 1, 200)
    assert capped.data is not None and capped.data.end == 50 and "capped" in (capped.note or "")
    clipped = uniprot.get_sequence_window(offline, "P01308", 100, 120)
    assert clipped.data is not None and clipped.data.end == 110


def test_missing_feature_type_is_not_found_with_alternatives(offline: Fetcher) -> None:
    result = uniprot.get_features(offline, "P01308", "Domain")
    assert not result.found
    assert result.note is not None and "Signal" in result.note


def test_features_filter_by_type(offline: Fetcher) -> None:
    result = uniprot.get_features(offline, "P00533", "domain")
    assert result.found and result.data is not None
    assert [(f.start, f.end) for f in result.data.features] == [(712, 979)]


def test_structures_sorted_best_resolution_first(offline: Fetcher) -> None:
    result = uniprot.list_structures(offline, "P01116", "X-ray", 5)
    assert result.data is not None
    resolutions = [s.resolution_angstrom for s in result.data.structures]
    assert resolutions == sorted(r for r in resolutions if r is not None)
    assert result.data.total > result.data.returned == 5


def test_structure_entry_maps_chains_and_ligands(offline: Fetcher) -> None:
    result = pdb.get_structure(offline, "1iep")
    assert result.found and result.data is not None
    assert result.data.polymer_entities[0].uniprot_accessions == ["P00520"]
    ligands = {lig.comp_id: lig.name for lig in result.data.ligands}
    assert "STI" in ligands
    assert "additive" in (ligands.get("CL") or "")


def test_absent_and_malformed_ids_are_not_found(offline: Fetcher) -> None:
    assert not pdb.get_structure(offline, "9ZYZ").found
    malformed = pdb.get_structure(offline, "hemoglobin")
    assert not malformed.found and "not a four-character" in (malformed.note or "")
    assert not uniprot.get_protein(offline, "not-an-accession").found
    assert not uniprot.get_protein(offline, "Q00000").found


def test_alphafold_summary(offline: Fetcher) -> None:
    result = alphafold.get_alphafold_summary(offline, "P04637")
    assert result.found and result.data is not None
    bands = (
        result.data.fraction_very_high
        + result.data.fraction_confident
        + result.data.fraction_low
        + result.data.fraction_very_low
    )
    assert abs(bands - 1.0) < 0.01
    assert result.sources[0].record_id == "AF-P04637-F1"
    assert all(r.end - r.start + 1 >= 10 for r in result.data.low_confidence_regions)


def test_low_confidence_regions_edges() -> None:
    numbers = list(range(1, 31))
    scores = [30.0] * 10 + [80.0] * 5 + [40.0] * 9 + [80.0] + [20.0] * 5
    regions = low_confidence_regions(numbers, scores)
    assert [(r.start, r.end) for r in regions] == [(1, 10)]
    assert [(r.start, r.end) for r in low_confidence_regions(numbers, [10.0] * 30)] == [(1, 30)]


def test_run_tool_reports_bad_input_as_tool_errors(offline: Fetcher) -> None:
    text, is_error = run_tool(offline, "get_sequence_window", {"accession": "P04637"})
    assert is_error and "invalid arguments" in text
    text, is_error = run_tool(offline, "get_protein", {"accession": "P04637", "extra": 1})
    assert is_error
    text, is_error = run_tool(offline, "no_such_tool", {})
    assert is_error and "unknown tool" in text


def test_run_tool_returns_compact_json(offline: Fetcher) -> None:
    text, is_error = run_tool(offline, "get_protein", {"accession": "P69905"})
    payload = json.loads(text)
    assert not is_error and payload["data"]["protein_name"] == "Hemoglobin subunit alpha"


def test_tool_defs_match_registry() -> None:
    defs = anthropic_tool_defs()
    assert [d["name"] for d in defs] == list(TOOLS)
    for d in defs:
        assert d["input_schema"]["type"] == "object"
        assert d["input_schema"].get("additionalProperties") is False


def test_unsupported_feature_type_is_not_reported_as_absent(offline: Fetcher) -> None:
    result = uniprot.get_features(offline, "P04637", "Natural variant")
    assert not result.found
    assert result.note is not None and "says nothing about whether" in result.note


def test_glycosylation_is_retrieved(offline: Fetcher) -> None:
    result = uniprot.get_features(offline, "P0DTC2", "Glycosylation")
    assert result.found and result.data is not None and len(result.data.features) > 5


def test_alphafold_not_found_still_cites_what_was_checked(offline: Fetcher) -> None:
    result = alphafold.get_alphafold_summary(offline, "Q00000")
    assert not result.found and result.sources[0].record_id == "Q00000"


def test_run_tool_turns_unexpected_errors_into_tool_errors(
    offline: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object) -> None:
        raise KeyError("primaryAccession")

    monkeypatch.setattr(uniprot, "get_protein", boom)
    text, is_error = run_tool(offline, "get_protein", {"accession": "P04637"})
    assert is_error and "unexpected KeyError" in text
