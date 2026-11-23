"""Numbering, variants, isoforms and "why is it missing": offline against the snapshot."""

from __future__ import annotations

import json

import pytest

from proteinground import alphafold, pdb, uniprot
from proteinground.fetch import Fetcher
from proteinground.tools import run_tool


def test_author_numbering_maps_to_uniprot_and_back(offline: Fetcher) -> None:
    forward = pdb.map_structure_residue(offline, "1iep", "A", residue_number=315)
    assert forward.found and forward.data is not None
    assert (forward.data.uniprot_accession, forward.data.uniprot_position) == ("P00520", 315)
    assert (forward.data.structure_residue, forward.data.matches_uniprot) == ("T", True)
    assert forward.data.observed is True and forward.data.organism == "Mus musculus"
    assert {s.database for s in forward.sources} == {"RCSB PDB", "UniProtKB"}

    back = pdb.map_structure_residue(offline, "1IEP", "B", uniprot_position=400)
    assert back.data is not None and (back.data.author_residue, back.data.chain) == ("400", "B")


def test_numbering_offset_is_not_assumed_away(offline: Fetcher) -> None:
    """The sickle-cell residue: Glu6 in every textbook, position 7 in UniProtKB."""
    result = pdb.map_structure_residue(offline, "4HHB", "B", residue_number=6)
    assert result.data is not None
    assert (result.data.uniprot_accession, result.data.uniprot_position) == ("P68871", 7)
    assert result.data.structure_residue == result.data.uniprot_residue == "E"
    assert (
        result.data.coverage[0].author_start == "1" and result.data.coverage[0].uniprot_start == 2
    )


def test_insertion_codes_are_part_of_the_residue_number(offline: Fetcher) -> None:
    result = pdb.map_structure_residue(offline, "1PPB", "H", residue_number=60, insertion_code="A")
    assert result.data is not None
    assert (result.data.author_residue, result.data.uniprot_position) == ("60A", 410)
    assert result.data.label_asym_id == "B"  # the mmCIF chain ID differs from the author's


def test_engineered_mutation_is_flagged_not_hidden(offline: Fetcher) -> None:
    """6OIM is KRAS G12C: the structure has Cys where the canonical sequence has Gly."""
    result = pdb.map_structure_residue(offline, "6OIM", "A", residue_number=12)
    assert result.data is not None
    assert (result.data.structure_residue, result.data.uniprot_residue) == ("C", "G")
    assert result.data.matches_uniprot is False
    assert result.note is not None and "structure has C where P01116 has G at 12" in result.note


def test_unmodelled_and_unaligned_residues_say_so(offline: Fetcher) -> None:
    result = pdb.map_structure_residue(offline, "1IEP", "A", residue_number=224)
    assert result.found and result.data is not None
    assert result.data.observed is False and result.data.uniprot_position is None
    assert result.note is not None and "no coordinates" in result.note


def test_missing_residue_or_chain_names_what_exists(offline: Fetcher) -> None:
    residue = pdb.map_structure_residue(offline, "1IEP", "A", residue_number=50)
    assert not residue.found and "runs 223 to 515" in (residue.note or "")
    outside = pdb.map_structure_residue(offline, "1IEP", "A", uniprot_position=100)
    assert not outside.found and "covers P00520 229-515" in (outside.note or "")
    chain = pdb.map_structure_residue(offline, "1IEP", "Z", residue_number=315)
    assert not chain.found and "chains: A, B" in (chain.note or "")


def test_mapping_needs_exactly_one_direction(offline: Fetcher) -> None:
    for arguments in (
        {"pdb_id": "1IEP", "chain": "A"},
        {"pdb_id": "1IEP", "chain": "A", "residue_number": 315, "uniprot_position": 315},
    ):
        text, is_error = run_tool(offline, "map_structure_residue", arguments)
        assert is_error and "exactly one" in text


def test_obsolete_entry_names_its_replacement(offline: Fetcher) -> None:
    result = pdb.get_structure(offline, "1HHB")
    assert not result.found
    assert result.note is not None and "obsolete" in result.note and "4HHB" in result.note


def test_unreleased_entry_is_not_called_nonexistent(offline: Fetcher) -> None:
    result = pdb.get_structure(offline, "9ZYZ")
    assert not result.found
    assert result.note is not None and "deposited but is not released" in result.note


def test_variants_check_a_mutation_string(offline: Fetcher) -> None:
    result = uniprot.get_variants(offline, "P01116", 12)
    assert result.found and result.data is not None
    assert [(r.position, r.one_letter) for r in result.data.reference] == [(12, "G")]
    changes = {c for v in result.data.variants for c in v.changes}
    assert {"G12C", "G12D", "G12V"} <= changes
    assert all(v.start == 12 for v in result.data.variants)
    assert any("rs121913530" in v.dbsnp for v in result.data.variants)


def test_no_annotated_variant_is_not_proof_of_absence(offline: Fetcher) -> None:
    result = uniprot.get_variants(offline, "P01308", 3)
    assert result.found and result.data is not None  # the position exists, so it is an answer
    assert result.data.variants == [] and result.data.natural_variants_in_entry > 0
    assert result.note is not None and "not evidence that a variant does not occur" in result.note
    assert not uniprot.get_variants(offline, "P01308", 450).found


def test_isoform_sequences_use_their_own_numbering(offline: Fetcher) -> None:
    result = uniprot.get_sequence_window(offline, "P04637-2", 330, 341)
    assert result.found and result.data is not None
    assert (result.data.accession, result.data.sequence_length) == ("P04637-2", 341)
    assert result.note is not None and "numbered on isoform P04637-2" in result.note
    assert result.sources[0].record_id == "P04637-2"
    assert not uniprot.get_sequence_window(offline, "P04637-99", 1, 1).found


def test_isoform_and_entry_name_inputs_get_a_next_step(offline: Fetcher) -> None:
    isoform = uniprot.get_features(offline, "P04637-2")
    assert not isoform.found and "call this tool with P04637" in (isoform.note or "")
    name = uniprot.get_protein(offline, "P53_HUMAN")
    assert not name.found and "search_proteins" in (name.note or "")
    assert "isoform ID" in (alphafold.get_alphafold_summary(offline, "P04637-2").note or "")


@pytest.mark.parametrize(
    ("typed", "canonical"),
    [
        ("Signal peptide", "Signal"),
        ("signal peptides", "Signal"),
        ("SIGNAL", "Signal"),
        ("disulfide bonds", "Disulfide bond"),
        ("Disulfide", "Disulfide bond"),
        ("ACT_SITE", "Active site"),
        ("ft_transmem", "Transmembrane"),
        ("transmembrane helix", "Transmembrane"),
        ("cross-link", "Cross-link"),
        ("crosslinks", "Cross-link"),
        ("glycosylation sites", "Glycosylation"),
        ("domains", "Domain"),
        ("DNA-binding", "DNA binding"),
    ],
)
def test_common_feature_names_resolve(typed: str, canonical: str) -> None:
    assert uniprot.resolve_feature_type(typed) == canonical


def test_unknown_feature_names_do_not_resolve() -> None:
    assert uniprot.resolve_feature_type("phosphorylation") is None
    assert uniprot.resolve_feature_type("variants") is None


def test_feature_alias_reaches_the_record(offline: Fetcher) -> None:
    result = uniprot.get_features(offline, "P01308", "signal peptide")
    assert result.found and result.data is not None
    assert result.data.requested_type == "Signal"
    assert [(f.start, f.end) for f in result.data.features] == [(1, 24)]


def test_variant_names_point_to_the_variant_tool(offline: Fetcher) -> None:
    result = uniprot.get_features(offline, "P04637", "mutagenesis")
    assert not result.found and "get_variants" in (result.note or "")


def test_features_at_a_position(offline: Fetcher) -> None:
    result = uniprot.get_features(offline, "P04637", position=273)
    assert result.found and result.data is not None
    assert "DNA binding" in {f.type for f in result.data.features}
    assert all(
        f.start is not None and f.end is not None and f.start <= 273 <= f.end
        for f in result.data.features
    )
    beyond = uniprot.get_features(offline, "P04637", position=900)
    assert not beyond.found and "393 residues" in (beyond.note or "")


def test_a_disulfide_does_not_cover_the_residues_between_its_cysteines(offline: Fetcher) -> None:
    bonds = uniprot.get_features(offline, "P01308", "Disulfide bond")
    assert bonds.data is not None
    first = bonds.data.features[0]
    assert first.start is not None and first.end is not None and first.end - first.start > 2
    between = uniprot.get_features(offline, "P01308", "disulfide", position=first.start + 1)
    assert not between.found
    at_cysteine = uniprot.get_features(offline, "P01308", "disulfide", position=first.start)
    assert at_cysteine.found


def test_alphafold_confidence_for_a_region(offline: Fetcher) -> None:
    result = alphafold.get_alphafold_summary(offline, "P04637", 100, 290)
    assert result.data is not None and result.data.window is not None
    window = result.data.window
    assert window.residues == 191 and window.mean_plddt > 90 > window.min_plddt
    assert result.data.mean_plddt is not None and window.mean_plddt > result.data.mean_plddt
    outside = alphafold.get_alphafold_summary(offline, "P04637", 500, 510)
    assert outside.data is not None and outside.data.window is None
    assert "no residues in 500-510" in (outside.note or "")


def test_new_tools_run_through_the_registry(offline: Fetcher) -> None:
    text, is_error = run_tool(offline, "get_variants", {"accession": "P01116", "start": 12})
    assert not is_error and json.loads(text)["data"]["reference"][0]["one_letter"] == "G"
    text, is_error = run_tool(
        offline, "map_structure_residue", {"pdb_id": "4HHB", "chain": "B", "residue_number": 6}
    )
    assert not is_error and json.loads(text)["data"]["uniprot_position"] == 7
