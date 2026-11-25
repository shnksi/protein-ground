"""Numbering, variants, isoforms and "why is it missing": offline against the snapshot."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from proteinground import alphafold, pdb, uniprot
from proteinground.fetch import Fetcher, InvalidInputError, Mode
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


def test_list_structures_resolves_method_aliases_and_rejects_unknown(offline: Fetcher) -> None:
    em = uniprot.list_structures(offline, "P04637", method="cryo-EM")
    assert em.found and em.data is not None and all(s.method == "EM" for s in em.data.structures)
    xray = uniprot.list_structures(offline, "P04637", method="X-RAY DIFFRACTION")
    assert (
        xray.found
        and xray.data is not None
        and all(s.method == "X-ray" for s in xray.data.structures)
    )
    unknown = uniprot.list_structures(offline, "P04637", method="microED")
    assert not unknown.found
    assert unknown.note is not None and "not a recognised PDB method" in unknown.note
    assert "X-ray" in unknown.note


def test_isoform_numbered_variants_and_features_do_not_collide_with_canonical() -> None:
    body: dict[str, Any] = {
        "primaryAccession": "P04637",
        "sequence": {"value": "M" * 20},
        "features": [
            {
                "type": "Natural variant",
                "location": {"start": {"value": 10}, "end": {"value": 10}, "sequence": "P04637-2"},
                "alternativeSequence": {"originalSequence": "A", "alternativeSequences": ["V"]},
                "description": "isoform-specific",
            },
            {
                "type": "Domain",
                "location": {"start": {"value": 5}, "end": {"value": 15}, "sequence": "P04637-2"},
                "description": "isoform domain",
            },
        ],
    }
    f = Fetcher(
        None,
        Mode.LIVE,
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))),
    )
    variants = uniprot.get_variants(f, "P04637", 10)
    assert variants.found and variants.data is not None and variants.data.variants == []
    assert variants.note is not None and "isoform-numbered variant" in variants.note
    features = uniprot.get_features(f, "P04637", position=10)
    assert not features.found
    assert features.note is not None and "isoform-numbered feature" in features.note


def test_alphafold_selects_covering_fragment_for_long_proteins() -> None:
    models = [
        {
            "uniprotAccession": "Q8WZ42",
            "entryId": "AF-Q8WZ42-F1",
            "latestVersion": 6,
            "uniprotStart": 1,
            "uniprotEnd": 1400,
            "globalMetricValue": 70.0,
            "fractionPlddtVeryHigh": 0.4,
            "fractionPlddtConfident": 0.3,
            "fractionPlddtLow": 0.2,
            "fractionPlddtVeryLow": 0.1,
            "plddtDocUrl": "https://alphafold.ebi.ac.uk/files/AF-Q8WZ42-F1-confidence.json",
        },
        {
            "uniprotAccession": "Q8WZ42",
            "entryId": "AF-Q8WZ42-F2",
            "latestVersion": 6,
            "uniprotStart": 201,
            "uniprotEnd": 1600,
            "globalMetricValue": 85.0,
            "fractionPlddtVeryHigh": 0.6,
            "fractionPlddtConfident": 0.2,
            "fractionPlddtLow": 0.1,
            "fractionPlddtVeryLow": 0.1,
            "plddtDocUrl": "https://alphafold.ebi.ac.uk/files/AF-Q8WZ42-F2-confidence.json",
        },
    ]

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/Q8WZ42"):
            return httpx.Response(200, json=models)
        if "F2-confidence" in url:
            return httpx.Response(
                200,
                json={"residueNumber": list(range(201, 1601)), "confidenceScore": [91.0] * 1400},
            )
        return httpx.Response(
            200, json={"residueNumber": list(range(1, 1401)), "confidenceScore": [70.0] * 1400}
        )

    f = Fetcher(None, Mode.LIVE, httpx.Client(transport=httpx.MockTransport(handle)))
    auto = alphafold.get_alphafold_summary(f, "Q8WZ42", start=1500, end=1550)
    assert auto.found and auto.data is not None
    assert auto.data.model_id == "AF-Q8WZ42-F2"
    assert auto.data.window is not None and auto.data.window.residues == 51
    assert auto.data.other_models == ["AF-Q8WZ42-F1"]

    explicit = alphafold.get_alphafold_summary(f, "Q8WZ42", model_id="af-q8wz42-f2")
    assert explicit.found and explicit.data is not None and explicit.data.model_id == "AF-Q8WZ42-F2"

    missing = alphafold.get_alphafold_summary(f, "Q8WZ42", model_id="AF-Q8WZ42-F99")
    assert not missing.found and "AF-Q8WZ42-F2" in (missing.note or "")


def test_alphafold_isoform_only_entry_names_models_and_accepts_model_id() -> None:
    models = [
        {
            "uniprotAccession": "P11532-9",
            "entryId": "AF-P11532-9-F1",
            "latestVersion": 6,
            "uniprotStart": 1,
            "uniprotEnd": 525,
            "globalMetricValue": 82.5,
            "fractionPlddtVeryHigh": 0.5,
            "fractionPlddtConfident": 0.3,
            "fractionPlddtLow": 0.1,
            "fractionPlddtVeryLow": 0.1,
        }
    ]
    f = Fetcher(
        None,
        Mode.LIVE,
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=models))),
    )
    canonical = alphafold.get_alphafold_summary(f, "P11532")
    assert not canonical.found and "AF-P11532-9-F1" in (canonical.note or "")
    chosen = alphafold.get_alphafold_summary(f, "P11532", model_id="AF-P11532-9-F1")
    assert chosen.found and chosen.data is not None and chosen.data.model_id == "AF-P11532-9-F1"


def test_low_confidence_regions_splits_on_numbering_gaps() -> None:
    numbers = [1, 2, 3, 4, 5, 20, 21, 22, 23, 24]
    scores = [30.0] * 10
    assert alphafold.low_confidence_regions(numbers, scores, min_len=6) == []


def test_lowercase_insertion_code_and_r_factors_and_search_hint(offline: Fetcher) -> None:
    mapped = pdb.map_structure_residue(offline, "1PPB", "H", residue_number=60, insertion_code="a")
    assert mapped.found and mapped.data is not None and mapped.data.author_residue == "60A"

    structure = pdb.get_structure(offline, "1IEP")
    assert structure.found and structure.data is not None
    assert structure.data.r_free is not None and 0.1 < structure.data.r_free < 0.4
    assert structure.data.r_work is not None and 0.1 < structure.data.r_work < 0.4

    empty_search = Fetcher(
        None,
        Mode.LIVE,
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"results": []}))
        ),
    )
    with pytest.raises(InvalidInputError, match="empty"):
        uniprot.search(empty_search, "   ")
    no_hits = uniprot.search(empty_search, "obscure_protein", reviewed_only=True)
    assert not no_hits.found and "reviewed_only=False" in (no_hits.note or "")


def test_fusion_chain_can_be_disambiguated_by_uniprot_accession() -> None:
    chain = pdb._Chain(
        author_id="A",
        asym_id="A",
        entity_id="1",
        description="fusion",
        organism="Homo sapiens",
        mutation=None,
        numbering=["1", "2", "3", "4"],
        sequence="MACK",
        segments=[pdb._Segment("P11111", 1, 10, 2), pdb._Segment("P22222", 3, 10, 2)],
        unobserved=[],
    )
    ambiguous = pdb._locate(chain, "1ABC", None, 10)
    assert isinstance(ambiguous, str) and "uniprot_accession" in ambiguous
    resolved = pdb._locate(chain, "1ABC", None, 10, "p22222")
    assert not isinstance(resolved, str) and resolved[0] == 3 and resolved[1] is not None
    assert resolved[1].accession == "P22222"
