"""Build eval v2: draw long-tail proteins by seed, write the questions, freeze the snapshot.

    uv run python evals/v2/build_questions.py [--seed 11] [--refresh]

Nothing here is hand-picked. Each stratum is a UniProtKB search (STRATA below); proteins
are drawn from it with a seeded random number generator and kept when they pass a stated
acceptance rule. The search pages the draw read are kept in evals/v2/pools/, so the draw
can be repeated offline.

Gold answers are computed here from the raw records: UniProtKB JSON, the RCSB REST
records for entries, polymer entities, chain instances and removed entries, and the
AlphaFold DB prediction record. The tools read chains and entities through RCSB GraphQL
and parse everything with their own code; only URL builders are shared, so the snapshot
holds the exact responses the tools will request. `proteinground-eval check-gold` then
confirms that the tools reach every gold answer. Every planted false premise is checked
against the data before it is written.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from proteinground import alphafold, pdb, uniprot
from proteinground.eval.schema import AnswerType, Question, ToolCall, write_questions
from proteinground.fetch import Fetcher, Mode
from proteinground.tools import run_tool

HERE = Path(__file__).parent
SNAPSHOT = HERE / "snapshot"
POOLS = HERE / "pools"
QUESTIONS = HERE / "questions.jsonl"
MANIFEST = HERE / "MANIFEST.json"

# Organisms left out of every stratum: the ones a model has read most about.
MODEL_ORGANISMS = {
    9606: "Homo sapiens",
    10090: "Mus musculus",
    10116: "Rattus norvegicus",
    559292: "Saccharomyces cerevisiae S288C",
    83333: "Escherichia coli K-12",
    3702: "Arabidopsis thaliana",
    7227: "Drosophila melanogaster",
    6239: "Caenorhabditis elegans",
    7955: "Danio rerio",
    9913: "Bos taurus",
    284812: "Schizosaccharomyces pombe 972h-",
    224308: "Bacillus subtilis 168",
}
NOT_MODEL = " ".join(f"NOT (organism_id:{taxon})" for taxon in MODEL_ORGANISMS)
MIN_LENGTH, MAX_LENGTH = 80, 800
MAX_ENTITIES = 12  # entries with more polymer entities are skipped (one REST call each)
MAX_LENGTH_DRAWS = 600


def _score(*scores: int) -> str:
    return "(" + " OR ".join(f"annotation_score:{s}" for s in scores) + ")"


@dataclass(frozen=True)
class Stratum:
    name: str
    query: str
    quota: int
    method: str  # "length": two-stage draw for a large pool; "list": the whole pool
    needs: str  # acceptance rule, see accept()
    why: str


STRATA = [
    Stratum(
        "rev_pdb",
        f"(reviewed:true) AND (database:pdb) AND {_score(1, 2, 3)} {NOT_MODEL}",
        12,
        "length",
        "chain",
        "reviewed, annotation score 3 or lower, with a PDB structure",
    ),
    Stratum(
        "rev_af",
        f"(reviewed:true) AND (database:alphafolddb) AND NOT (database:pdb) AND {_score(1)} "
        f"{NOT_MODEL}",
        7,
        "length",
        "alphafold",
        "reviewed, annotation score 1, no PDB structure, an AlphaFold DB model",
    ),
    Stratum(
        "unrev_pdb",
        f"(reviewed:false) AND (database:pdb) AND {_score(1, 2)} {NOT_MODEL}",
        7,
        "length",
        "chain",
        "unreviewed (TrEMBL), annotation score 2 or lower, with a PDB structure",
    ),
    Stratum(
        "unrev_af",
        f"(reviewed:false) AND (database:alphafolddb) AND NOT (database:pdb) AND "
        f"{_score(1, 2)} AND (existence:1) {NOT_MODEL}",
        4,
        "length",
        "alphafold",
        "unreviewed (TrEMBL), evidence at protein level, no PDB structure, an AlphaFold DB model",
    ),
    Stratum(
        "isoform",
        f"(reviewed:true) AND (cc_ap:*) AND {_score(1, 2, 3)} {NOT_MODEL}",
        4,
        "list",
        "isoform",
        "reviewed, annotation score 3 or lower, with described isoforms",
    ),
    Stratum(
        "mutagenesis",
        f"(reviewed:true) AND (ft_mutagen:*) AND (database:pdb) AND {_score(1, 2, 3, 4)} "
        f"{NOT_MODEL}",
        5,
        "list",
        "variant",
        "reviewed, annotation score 4 or lower, with mutagenesis records and a PDB structure",
    ),
    Stratum(
        "peptidase_s1",
        f'(reviewed:true) AND (family:"peptidase S1 family") AND (database:pdb) {NOT_MODEL}',
        4,
        "list",
        "insertion",
        "reviewed peptidase S1 family with a PDB structure: the family where structures "
        "carry insertion codes (chymotrypsin numbering)",
    ),
]

METHOD_CATEGORY = {
    "X-RAY DIFFRACTION": "xray",
    "ELECTRON MICROSCOPY": "em",
    "SOLUTION NMR": "nmr",
    "SOLID-STATE NMR": "nmr",
}
THREE = {
    "A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln", "E": "Glu",
    "G": "Gly", "H": "His", "I": "Ile", "L": "Leu", "K": "Lys", "M": "Met", "F": "Phe",
    "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp", "Y": "Tyr", "V": "Val",
}  # fmt: skip
# Feature types asked about, most specific first, and how the question names them.
FEATURE_WORDS = [
    ("Signal", "signal peptide"),
    ("Transit peptide", "transit peptide"),
    ("Propeptide", "propeptide"),
    ("Transmembrane", "transmembrane segment"),
    ("Domain", "domain"),
    ("Zinc finger", "zinc finger"),
    ("Coiled coil", "coiled coil"),
]
# Features asked about on proteins that do not have them (the planted twin of the above).
ABSENT_FEATURES = [
    ("Signal", "signal peptide"),
    ("Transmembrane", "transmembrane segment"),
    ("Propeptide", "propeptide"),
]
# How many items each family may hold. Fewer are written when the drawn proteins do not
# supply that many; main() fails if the totals fall outside the preregistered shape.
QUOTA = {
    "residue_at": 20,
    "isoform_residue": 6,
    "length": 8,
    "feature_range": 10,
    "method_resolution": 12,
    "ligand_comp_id": 6,
    "polymer_uniprot": 8,
    "best_xray": 6,
    "af_fraction": 10,
    "af_mean": 6,
    "accession_lookup": 5,
    "structure_numbering": 10,
    "structure_residue": 6,
    "modelled_residue": 6,
    "insertion_code": 6,
    "engineered_mutation": 6,
    "variant_lookup": 6,
    "obsolete_replacement": 6,
}
PLANTED_QUOTA = {
    "absent_pdb": 2,
    "absent_accession": 2,
    "past_end": 4,
    "absent_feature": 4,
    "wrong_wild_type": 5,
    "author_number_as_uniprot": 4,
    "unmodelled_residue": 6,
    "no_difference": 3,
    "isoform_missing": 4,
    "obsolete_no_successor": 2,
}
MIN_QUESTIONS = 150
PLANTED_SHARE = (0.17, 0.23)


def call(name: str, **kwargs: Any) -> ToolCall:
    return ToolCall(name=name, input=kwargs)


def rng_for(seed: int, *parts: object) -> random.Random:
    """One generator per decision, so a change in one family does not reshuffle the rest."""
    return random.Random(":".join(str(p) for p in (seed, *parts)))


# Raw records


def length_page_url(query: str, length: int) -> str:
    params = {
        "fields": "accession,length",
        "format": "json",
        "query": f"{query} AND (length:[{length} TO {length}])",
        "size": "500",
        "sort": "accession asc",
    }
    return f"{uniprot.BASE}/search?{urlencode(params)}"


def stream_url(query: str) -> str:
    params = {"fields": "accession", "format": "json", "query": query, "sort": "accession asc"}
    return f"{uniprot.BASE}/stream?{urlencode(params)}"


def isoforms_url(accession: str) -> str:
    return f"{uniprot.BASE}/{accession}.json?fields=accession,cc_alternative_products"


def instance_url(pdb_id: str, asym_id: str) -> str:
    return f"{pdb.BASE}/polymer_entity_instance/{pdb_id}/{asym_id}"


REMOVED_IDS_URL = "https://data.rcsb.org/rest/v1/holdings/removed/entry_ids"


def removed_url(pdb_id: str) -> str:
    return f"https://data.rcsb.org/rest/v1/holdings/removed/{pdb_id}"


class Raw:
    """Raw records, fetched once each and frozen into the snapshot."""

    def __init__(self, fetcher: Fetcher) -> None:
        self.f = fetcher

    def _body(self, url: str) -> tuple[int, Any]:
        response = self.f.get_json(url)
        return response.status, response.body if response.ok else None

    def entry(self, accession: str) -> dict[str, Any] | None:
        _, body = self._body(uniprot.entry_url(accession))
        if not isinstance(body, dict) or body.get("entryType") == "Inactive":
            return None
        return body

    def variants(self, accession: str) -> dict[str, Any]:
        status, body = self._body(uniprot.variants_url(accession))
        assert isinstance(body, dict), f"UniProtKB variants {accession}: HTTP {status}"
        return body

    def isoform_ids(self, accession: str) -> list[str]:
        """Isoform IDs UniProtKB describes for this entry, the displayed one included."""
        _, body = self._body(isoforms_url(accession))
        ids: list[str] = []
        for comment in (body or {}).get("comments", []):
            if comment.get("commentType") != "ALTERNATIVE PRODUCTS":
                continue
            for isoform in comment.get("isoforms", []):
                if isoform.get("isoformSequenceStatus") in ("Displayed", "Described"):
                    ids.extend(str(i) for i in isoform.get("isoformIds", [])[:1])
        return ids

    def isoform_sequence(self, isoform_id: str) -> tuple[int, str | None]:
        status, body = self._body(uniprot.isoform_url(isoform_id))
        value = (body or {}).get("sequence", {}).get("value")
        return status, str(value) if value else None

    def search(self, query: str, taxon_id: int) -> list[str]:
        _, body = self._body(uniprot.search_url(query, taxon_id, True, 5))
        return [str(r.get("primaryAccession")) for r in (body or {}).get("results", [])]

    def pdb_entry(self, pdb_id: str) -> tuple[int, dict[str, Any] | None]:
        status, body = self._body(pdb.entry_url(pdb_id))
        return status, body if isinstance(body, dict) else None

    def holdings(self, pdb_id: str) -> tuple[int, dict[str, Any]]:
        status, body = self._body(pdb.holdings_url(pdb_id))
        combined = (body or {}).get("rcsb_repository_holdings_combined", {})
        return status, dict(combined)

    def removed(self, pdb_id: str) -> dict[str, Any]:
        _, body = self._body(removed_url(pdb_id))
        return dict((body or {}).get("rcsb_repository_holdings_removed", {}))

    def polymer_entities(self, pdb_id: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
        ids = entry["rcsb_entry_container_identifiers"].get("polymer_entity_ids") or []
        out = []
        for entity_id in ids:
            _, body = self._body(pdb.polymer_url(pdb_id, str(entity_id)))
            assert isinstance(body, dict), f"{pdb_id} entity {entity_id} did not load"
            out.append(body)
        return out

    def nonpolymers(self, pdb_id: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
        ids = entry["rcsb_entry_container_identifiers"].get("non_polymer_entity_ids") or []
        out = []
        for entity_id in ids:
            _, body = self._body(pdb.nonpolymer_url(pdb_id, str(entity_id)))
            assert isinstance(body, dict), f"{pdb_id} ligand entity {entity_id} did not load"
            out.append(dict(body["pdbx_entity_nonpoly"]))
        return out

    def instance(self, pdb_id: str, asym_id: str) -> dict[str, Any] | None:
        _, body = self._body(instance_url(pdb_id, asym_id))
        return body if isinstance(body, dict) else None

    def af(self, accession: str) -> dict[str, Any] | None:
        """The accession's AlphaFold DB model, when it has exactly one.

        An accession with several models has several mean pLDDT values, so a question
        about "the model" would have more than one answer.
        """
        status, body = self._body(alphafold.prediction_url(accession))
        if status != 200 or not isinstance(body, list):
            return None
        models = [m for m in body if m.get("uniprotAccession") == accession]
        return dict(models[0]) if len(models) == 1 else None


# Proteins and chains, parsed from the raw records


@dataclass(frozen=True)
class Site:
    """One residue of a deposited chain that RCSB aligns to the UniProtKB sequence."""

    author: str  # author residue number, with any insertion code
    letter: str  # residue in the deposited construct
    position: int  # UniProtKB position
    canonical: str | None  # canonical residue at that position
    observed: bool

    @property
    def number(self) -> int | None:
        return int(self.author) if re.fullmatch(r"-?\d+", self.author) else None

    @property
    def insertion(self) -> tuple[int, str] | None:
        match = re.fullmatch(r"(-?\d+)([A-Za-z])", self.author)
        return (int(match.group(1)), match.group(2)) if match else None


@dataclass(frozen=True)
class Chain:
    pdb_id: str
    chain: str  # author chain ID
    sites: list[Site]


@dataclass
class Protein:
    accession: str
    stratum: str
    entry: dict[str, Any]
    chains: list[Chain] = field(default_factory=list)

    @property
    def sequence(self) -> str:
        return str(self.entry["sequence"]["value"])

    @property
    def name(self) -> str:
        desc = self.entry.get("proteinDescription", {})
        recommended = desc.get("recommendedName", {}).get("fullName", {}).get("value")
        submitted = [s.get("fullName", {}).get("value") for s in desc.get("submissionNames", [])]
        return str(recommended or next((s for s in submitted if s), "protein"))

    @property
    def organism(self) -> str:
        return str(self.entry.get("organism", {}).get("scientificName", ""))

    @property
    def taxon(self) -> int:
        return int(self.entry.get("organism", {}).get("taxonId", 0))

    @property
    def label(self) -> str:
        return f"{self.name}, {self.organism}"

    @property
    def reviewed(self) -> bool:
        return "unreviewed" not in str(self.entry.get("entryType", "")).lower()

    @property
    def gene(self) -> str | None:
        for gene in self.entry.get("genes", []):
            value = gene.get("geneName", {}).get("value")
            if value:
                return str(value)
        return None

    def xrefs(self) -> list[dict[str, str]]:
        out = []
        for xref in self.entry.get("uniProtKBCrossReferences", []):
            if xref.get("database") == "PDB":
                props = {p["key"]: p["value"] for p in xref.get("properties", [])}
                out.append({"id": str(xref["id"]).upper(), **props})
        return sorted(out, key=lambda x: x["id"])

    def features(self, ftype: str) -> list[tuple[str, int, int]]:
        """Features of one type whose two ends UniProtKB states exactly."""
        spans = []
        for feat in self.entry.get("features", []):
            if feat.get("type") != ftype:
                continue
            start, end = feat.get("location", {}).get("start", {}), feat["location"].get("end", {})
            exact = start.get("modifier") == "EXACT" and end.get("modifier") == "EXACT"
            if exact and isinstance(start.get("value"), int) and isinstance(end.get("value"), int):
                spans.append((str(feat.get("description") or ""), start["value"], end["value"]))
        return spans

    def has_feature(self, ftype: str) -> bool:
        return any(f.get("type") == ftype for f in self.entry.get("features", []))


def read_chain(raw: Raw, pdb_id: str, protein: Protein) -> Chain | None:
    """The first chain of this entry that is aligned to the protein and nothing else.

    Returns None when the entry cannot give a clean numbering item: too many entities, a
    chain aligned to more than one UniProtKB entry, repeated author numbers, an author
    chain ID shared by two polymers, or no record of which residues were modelled.
    """
    _, entry = raw.pdb_entry(pdb_id)
    if entry is None:
        return None
    entity_ids = entry["rcsb_entry_container_identifiers"].get("polymer_entity_ids") or []
    if not entity_ids or len(entity_ids) > MAX_ENTITIES:
        return None
    entities = raw.polymer_entities(pdb_id, entry)
    author_ids = [
        a
        for e in entities
        for a in e["rcsb_polymer_entity_container_identifiers"].get("auth_asym_ids") or []
    ]
    for entity in entities:
        aligned = [
            a
            for a in entity.get("rcsb_polymer_entity_align") or []
            if str(a.get("reference_database_name", "")).lower() == "uniprot"
        ]
        if not aligned or {a.get("reference_database_accession") for a in aligned} != {
            protein.accession
        }:
            continue
        asym_ids = entity["rcsb_polymer_entity_container_identifiers"].get("asym_ids") or []
        if not asym_ids:
            continue
        instance = raw.instance(pdb_id, sorted(asym_ids, key=lambda a: (len(a), a))[0])
        if instance is None or "rcsb_polymer_instance_feature" not in instance:
            continue
        ids = instance["rcsb_polymer_entity_instance_container_identifiers"]
        numbering = [str(n) for n in ids.get("auth_to_entity_poly_seq_mapping") or []]
        letters = re.sub(r"\s+", "", entity["entity_poly"].get("pdbx_seq_one_letter_code_can", ""))
        author_chain = str(ids.get("auth_asym_id") or "")
        if (
            not numbering
            or len(numbering) != len(letters)
            or len(set(numbering)) != len(numbering)
            or author_ids.count(author_chain) != 1
        ):
            continue
        unobserved: set[int] = set()
        for feature in instance["rcsb_polymer_instance_feature"]:
            if feature.get("type") != "UNOBSERVED_RESIDUE_XYZ":
                continue
            for span in feature.get("feature_positions") or []:
                first = int(span["beg_seq_id"])
                unobserved.update(range(first, int(span.get("end_seq_id") or first) + 1))
        sites = []
        for align in aligned:
            for region in align.get("aligned_regions") or []:
                begin, ref, length = (
                    int(region["entity_beg_seq_id"]),
                    int(region["ref_beg_seq_id"]),
                    int(region["length"]),
                )
                for offset in range(length):
                    seq_id, position = begin + offset, ref + offset
                    if not 1 <= seq_id <= len(letters):
                        continue
                    canonical = (
                        protein.sequence[position - 1]
                        if 1 <= position <= len(protein.sequence)
                        else None
                    )
                    sites.append(
                        Site(
                            author=numbering[seq_id - 1],
                            letter=letters[seq_id - 1],
                            position=position,
                            canonical=canonical,
                            observed=seq_id not in unobserved,
                        )
                    )
        if sites:
            return Chain(pdb_id=pdb_id, chain=author_chain, sites=sites)
    return None


def read_chains(raw: Raw, protein: Protein, seed: int, want: int, tries: int) -> list[Chain]:
    """Up to `want` usable chains, from PDB entries tried in a seeded random order."""
    ids = [x["id"] for x in protein.xrefs()]
    rng_for(seed, "chains", protein.accession).shuffle(ids)
    chains: list[Chain] = []
    for pdb_id in ids[:tries]:
        chain = read_chain(raw, pdb_id, protein)
        if chain is not None:
            chains.append(chain)
        if len(chains) == want:
            break
    return chains


def clean_substitutions(raw: Raw, protein: Protein) -> list[tuple[str, int, str, str]]:
    """(kind, position, wild type, replacement) for positions with exactly one record.

    Only single-residue substitutions on the canonical sequence with one replacement
    count, so the question has one answer.
    """
    by_position: dict[int, list[tuple[str, int, str, str]]] = {}
    crowded: set[int] = set()
    for feat in raw.variants(protein.accession).get("features", []):
        if feat.get("type") not in ("Mutagenesis", "Natural variant"):
            continue
        location = feat.get("location", {})
        start, end = location.get("start", {}).get("value"), location.get("end", {}).get("value")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        crowded.update(range(start, end + 1) if start != end else ())
        change = feat.get("alternativeSequence") or {}
        original = str(change.get("originalSequence") or "")
        alternatives = [str(a) for a in change.get("alternativeSequences") or []]
        on_canonical = str(location.get("sequence") or protein.accession) == protein.accession
        usable = (
            start == end
            and on_canonical
            and len(original) == 1
            and len(alternatives) == 1
            and len(alternatives[0]) == 1
            and original in THREE
            and alternatives[0] in THREE
            and start <= len(protein.sequence)
            and protein.sequence[start - 1] == original
        )
        by_position.setdefault(start, []).append(
            (str(feat["type"]), start, original, alternatives[0]) if usable else ("", start, "", "")
        )
    return [
        records[0]
        for position, records in sorted(by_position.items())
        if len(records) == 1 and records[0][0] and position not in crowded
    ]


# The draw


def draw(pools: Fetcher, stratum: Stratum, seed: int) -> Iterator[str]:
    """Accessions of one stratum in seeded random order.

    A pool small enough to list is listed whole and shuffled. A large pool is drawn in two
    stages: a random sequence length, then a random entry among those of that length. That
    samples lengths evenly rather than entries evenly, which is stated in the
    preregistration; it is the only way to draw at random from a search that pages by cursor.
    """
    rng = rng_for(seed, "draw", stratum.name)
    if stratum.method == "list":
        body = pools.get_json(stream_url(stratum.query)).body
        accessions = sorted({str(r["primaryAccession"]) for r in body["results"]})
        rng.shuffle(accessions)
        yield from accessions
        return
    seen: set[str] = set()
    for _ in range(MAX_LENGTH_DRAWS):
        length = rng.randint(MIN_LENGTH, MAX_LENGTH)
        body = pools.get_json(length_page_url(stratum.query, length)).body
        accessions = sorted({str(r["primaryAccession"]) for r in body["results"]} - seen)
        if not accessions:
            continue
        chosen = rng.choice(accessions)
        seen.add(chosen)
        yield chosen


def accept(raw: Raw, protein: Protein, stratum: Stratum, seed: int) -> str | None:
    """None when the protein can carry its stratum's questions, else why it was passed over."""
    if not MIN_LENGTH <= len(protein.sequence) <= MAX_LENGTH:
        return f"length {len(protein.sequence)} outside {MIN_LENGTH}-{MAX_LENGTH}"
    if stratum.needs == "alphafold":
        model = raw.af(protein.accession)
        if model is None or model.get("fractionPlddtVeryHigh") is None:
            return "no AlphaFold DB model"
        return None
    if stratum.needs == "isoform":
        differing = differing_isoforms(raw, protein)
        return None if differing else "no described isoform that differs from the canonical"
    if stratum.needs == "variant":
        if not clean_substitutions(raw, protein):
            return "no position with exactly one single-residue substitution record"
        protein.chains = read_chains(raw, protein, seed, want=2, tries=5)
        return None
    protein.chains = read_chains(raw, protein, seed, want=2, tries=6)
    if not protein.chains:
        return "no PDB entry with a chain aligned cleanly to this accession"
    if stratum.needs == "insertion" and not any(
        s.insertion and s.observed for c in protein.chains for s in c.sites
    ):
        return "no modelled residue with an insertion code in the chains tried"
    return None


def differing_isoforms(raw: Raw, protein: Protein) -> list[tuple[str, str]]:
    """(isoform ID, sequence) for described isoforms whose sequence is not the canonical one."""
    out = []
    for isoform_id in raw.isoform_ids(protein.accession):
        status, sequence = raw.isoform_sequence(isoform_id)
        if status == 200 and sequence and sequence != protein.sequence:
            out.append((isoform_id, sequence))
    return out


def draw_panel(
    raw: Raw, pools: Fetcher, seed: int
) -> tuple[list[Protein], dict[str, dict[str, Any]]]:
    panel: list[Protein] = []
    log: dict[str, dict[str, Any]] = {}
    taken: set[str] = set()
    for stratum in STRATA:
        kept: list[str] = []
        passed_over: list[dict[str, str]] = []
        for accession in draw(pools, stratum, seed):
            if accession in taken:
                continue
            taken.add(accession)
            entry = raw.entry(accession)
            if entry is None or str(entry.get("primaryAccession")) != accession:
                passed_over.append({"accession": accession, "why": "entry did not load"})
                continue
            protein = Protein(accession, stratum.name, entry)
            reason = accept(raw, protein, stratum, seed)
            if reason:
                passed_over.append({"accession": accession, "why": reason})
                continue
            panel.append(protein)
            kept.append(accession)
            if len(kept) == stratum.quota:
                break
        assert len(kept) == stratum.quota, f"{stratum.name}: drew {len(kept)} of {stratum.quota}"
        log[stratum.name] = {
            "what": stratum.why,
            "query": stratum.query,
            "method": stratum.method,
            "drawn": kept,
            "passed_over": passed_over,
        }
    return panel, log


def interleave(panel: list[Protein]) -> list[Protein]:
    """One protein from each stratum in turn, so no family leans on a single stratum."""
    by_stratum = [[p for p in panel if p.stratum == s.name] for s in STRATA]
    out: list[Protein] = []
    for index in range(max(len(group) for group in by_stratum)):
        out.extend(group[index] for group in by_stratum if index < len(group))
    return out


# Questions


class Writer:
    """Collects questions, holding each family to its quota."""

    def __init__(self) -> None:
        self.questions: list[Question] = []
        self.counts: dict[str, int] = {}
        self.planted_counts: dict[str, int] = {}
        self.ticks: dict[str, int] = {}

    def tick(self, name: str) -> int:
        """How many times this has been asked before: a counter for taking turns."""
        self.ticks[name] = self.ticks.get(name, 0) + 1
        return self.ticks[name] - 1

    def full(self, family: str) -> bool:
        return self.counts.get(family, 0) >= QUOTA[family]

    def planted_full(self, kind: str) -> bool:
        return self.planted_counts.get(kind, 0) >= PLANTED_QUOTA[kind]

    def add(
        self,
        family: str,
        qid: str,
        text: str,
        answer_type: AnswerType,
        gold: Any,
        record_ids: list[str],
        evidence: ToolCall,
        tolerance: float | None = None,
        reject: list[str] | None = None,
    ) -> None:
        assert not self.full(family), family
        self.counts[family] = self.counts.get(family, 0) + 1
        self.questions.append(
            Question(
                id=qid,
                family=family,
                premise_ok=True,
                text=text,
                answer_type=answer_type,
                gold=gold,
                tolerance=tolerance,
                record_ids=record_ids,
                evidence=[evidence],
                reject=reject or [],
            )
        )

    def plant(
        self,
        kind: str,
        qid: str,
        text: str,
        trap: str,
        record_ids: list[str],
        evidence: ToolCall,
        signal: Any,
        correction: tuple[AnswerType, Any] | None = None,
    ) -> None:
        """Add a planted item. `correction` is an answer that itself corrects the premise:
        giving it counts as catching the item, the same as saying it cannot be answered."""
        assert not self.planted_full(kind), kind
        self.planted_counts[kind] = self.planted_counts.get(kind, 0) + 1
        self.questions.append(
            Question(
                id=f"trap-{qid}",
                family=f"false_premise.{kind}",  # the report's family table lists each kind
                premise_ok=False,
                text=text,
                answer_type=correction[0] if correction else None,
                gold=correction[1] if correction else None,
                trap=trap,
                record_ids=record_ids,
                evidence=[evidence],
                evidence_signal=signal,
            )
        )


def residue_text(acc: str, label: str, pos: int) -> str:
    return (
        f"In UniProtKB entry {acc} ({label}), which amino acid is at position {pos} of the "
        "canonical sequence? Answer with the one-letter code."
    )


def length_text(acc: str, label: str) -> str:
    return f"How many residues long is the canonical sequence of UniProtKB entry {acc} ({label})?"


def feature_text(acc: str, label: str, what: str) -> str:
    return (
        f"According to UniProtKB, which residues does the {what} of {acc} ({label}) span? "
        "Answer as start-end."
    )


def method_text(pdb_id: str) -> str:
    return (
        f"Which experimental method was used for PDB entry {pdb_id}, and at what resolution? "
        "Answer as '<method>, <resolution> Å'."
    )


def isoform_text(isoform_id: str, label: str, pos: int) -> str:
    return (
        f"In UniProtKB isoform {isoform_id} ({label}), which amino acid is at position {pos}, "
        "numbered on that isoform's own sequence? Answer with the one-letter code."
    )


def numbering_text(pdb_id: str, chain: str, number: int, acc: str, label: str) -> str:
    return (
        f"In PDB entry {pdb_id}, chain {chain}, which position of UniProtKB {acc} ({label}) "
        f"does author residue number {number} correspond to? Answer with the position number "
        "only."
    )


def modelled_text(pdb_id: str, chain: str, number: int) -> str:
    return (
        f"In PDB entry {pdb_id}, which amino acid is modelled at author residue number "
        f"{number} of chain {chain}, with coordinates in the deposited model? Answer with the "
        "one-letter code."
    )


def same_number_text(pdb_id: str, chain: str, number: int, acc: str, label: str) -> str:
    return (
        f"In PDB entry {pdb_id}, chain {chain}, author residue number {number} is also "
        f"position {number} of UniProtKB {acc} ({label}). Which amino acid is it? Answer with "
        "the one-letter code."
    )


def difference_text(pdb_id: str, chain: str, position: int, acc: str, label: str) -> str:
    return (
        f"The protein in chain {chain} of PDB entry {pdb_id} differs from the UniProtKB "
        f"canonical sequence of {acc} ({label}) at UniProtKB position {position}. Give the "
        "difference in the form G12C: the UniProtKB residue, the position, then the residue "
        "in the structure."
    )


def variant_text(kind: str, residue: str, pos: int, acc: str, label: str) -> str:
    record = "mutagenesis record" if kind == "Mutagenesis" else "natural variant"
    return (
        f"UniProtKB annotates a {record} at {THREE[residue]}{pos} of {acc} ({label}). Which "
        "substitution does it describe? Answer in the form G12C."
    )


def obsolete_text(pdb_id: str) -> str:
    return (
        f"PDB entry {pdb_id} has been removed from the archive as obsolete. Which PDB entry "
        "superseded it? Give the PDB ID."
    )


def sequence_families(w: Writer, raw: Raw, proteins: list[Protein], seed: int) -> None:
    for p in proteins:
        acc, seq = p.accession, p.sequence
        if not w.full("residue_at"):
            pos = rng_for(seed, "residue", acc).randint(1, len(seq))
            w.add(
                "residue_at",
                f"residue-{acc}-{pos}",
                residue_text(acc, p.label, pos),
                "residue",
                seq[pos - 1],
                [acc],
                call("get_sequence_window", accession=acc, start=pos, end=pos),
            )
        elif not w.full("length"):
            w.add(
                "length",
                f"length-{acc}",
                length_text(acc, p.label),
                "int",
                len(seq),
                [acc],
                call("get_protein", accession=acc),
            )
    for p in proteins:
        if w.full("feature_range"):
            break
        for ftype, word in FEATURE_WORDS:
            spans = p.features(ftype)
            if len(spans) != 1 or len([f for f in p.entry["features"] if f["type"] == ftype]) != 1:
                continue
            desc, start, end = spans[0]
            what = word
            if ftype == "Domain":
                if not desc or ";" in desc:
                    continue
                what = desc if desc.lower().endswith("domain") else f"{desc} domain"
            w.add(
                "feature_range",
                f"feature-{p.accession}-{ftype.lower().replace(' ', '')}",
                feature_text(p.accession, p.label, what),
                "range",
                [start, end],
                [p.accession],
                call("get_features", accession=p.accession, feature_type=ftype),
            )
            break
    for p in proteins:
        if w.full("accession_lookup"):
            break
        gene = p.gene
        if not p.reviewed or not gene or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,11}", gene):
            continue
        if raw.search(f"gene:{gene}", p.taxon) != [p.accession]:
            continue  # the gene name does not single out this entry in its organism
        w.add(
            "accession_lookup",
            f"lookup-{p.accession}",
            f"What is the accession of the reviewed UniProtKB entry for the {gene} gene of "
            f"{p.organism}?",
            "token",
            p.accession,
            [p.accession],
            call("search_proteins", query=f"gene:{gene}", taxon_id=p.taxon),
        )


def isoform_families(w: Writer, raw: Raw, proteins: list[Protein], seed: int) -> None:
    for p in proteins:
        if p.stratum != "isoform":
            continue
        canonical = p.sequence
        differing = differing_isoforms(raw, p)
        rng = rng_for(seed, "isoform", p.accession)
        for isoform_id, sequence in differing[:2]:
            if w.full("isoform_residue"):
                break
            # A position where reading the canonical sequence would give the wrong residue.
            telling = [
                i + 1 for i, aa in enumerate(sequence) if i >= len(canonical) or canonical[i] != aa
            ]
            if not telling:
                continue  # the isoform is a truncation: every residue it has matches
            pos = rng.choice(telling)
            w.add(
                "isoform_residue",
                f"isoform-{isoform_id}-{pos}",
                isoform_text(isoform_id, p.label, pos),
                "residue",
                sequence[pos - 1],
                [isoform_id, p.accession],
                call("get_sequence_window", accession=isoform_id, start=pos, end=pos),
            )
        if w.planted_full("isoform_missing"):
            continue
        shorter = [(i, s) for i, s in differing if len(s) < len(canonical)]
        if shorter and w.planted_counts.get("isoform_missing", 0) % 2 == 0:
            # A position the canonical sequence has and this shorter isoform does not.
            isoform_id, sequence = shorter[0]
            pos = rng.randint(len(sequence) + 1, len(canonical))
            w.plant(
                "isoform_missing",
                f"isoform-{isoform_id}-{pos}",
                isoform_text(isoform_id, p.label, pos),
                f"isoform {isoform_id} has only {len(sequence)} residues; the canonical "
                f"sequence has {len(canonical)}",
                [isoform_id, p.accession],
                call("get_sequence_window", accession=isoform_id, start=pos, end=pos),
                "not_found",
            )
            continue
        known = raw.isoform_ids(p.accession)
        missing = f"{p.accession}-{len(known) + rng.randint(2, 4)}"
        status, _ = raw.isoform_sequence(missing)
        assert status in (404, 410), f"{missing}: expected no such isoform, HTTP {status}"
        pos = rng.randint(1, min(len(canonical), MIN_LENGTH))
        w.plant(
            "isoform_missing",
            f"isoform-{missing}-{pos}",
            isoform_text(missing, p.label, pos),
            f"UniProtKB describes {len(known)} isoforms of {p.accession}; {missing} is not one",
            [missing, p.accession],
            call("get_sequence_window", accession=missing, start=pos, end=pos),
            "not_found",
        )


def structure_families(w: Writer, raw: Raw, proteins: list[Protein], seed: int) -> None:
    for p in proteins:
        xrefs = p.xrefs()
        resolutions = {}
        for x in xrefs:
            match = re.match(r"([0-9.]+)", x.get("Resolution", ""))
            if x.get("Method") == "X-ray" and match:
                resolutions[x["id"]] = float(match.group(1))
        if len(resolutions) >= 2 and not w.full("best_xray"):
            best = min(resolutions.values())
            tied = sorted(k for k, v in resolutions.items() if v == best)
            w.add(
                "best_xray",
                f"bestxray-{p.accession}",
                f"Of the X-ray structures that UniProtKB entry {p.accession} ({p.label}) "
                "cross-references, which PDB entry has the best (lowest) resolution? Give the "
                "PDB ID.",
                "id_set",
                tied,
                [p.accession, *tied],
                call("list_structures", accession=p.accession, method="X-ray", limit=5),
            )
        for chain in p.chains:
            entry_families(w, raw, p, chain.pdb_id)


def entry_families(w: Writer, raw: Raw, p: Protein, pdb_id: str) -> None:
    """Items about one PDB entry as a whole: method, mapped accession, bound ligand."""
    status, entry = raw.pdb_entry(pdb_id)
    assert entry is not None, f"PDB {pdb_id}: HTTP {status}"
    methods = [str(e.get("method")) for e in entry.get("exptl", [])]
    resolutions = entry.get("rcsb_entry_info", {}).get("resolution_combined") or []
    measured = len(methods) == 1 and methods[0] in METHOD_CATEGORY and bool(resolutions)
    if measured and not w.full("method_resolution"):
        w.add(
            "method_resolution",
            f"method-{pdb_id}",
            method_text(pdb_id),
            "method_resolution",
            {"method": METHOD_CATEGORY[methods[0]], "resolution": float(resolutions[0])},
            [pdb_id],
            call("get_structure", pdb_id=pdb_id),
            tolerance=0.01,
        )
    entities = raw.polymer_entities(pdb_id, entry)
    # Every polymer in the entry is a protein chain mapped to this accession and no other.
    one_protein = all(
        "polypeptide" in str(e["entity_poly"].get("type", "")).lower()
        and (e["rcsb_polymer_entity_container_identifiers"].get("uniprot_ids") or [])
        == [p.accession]
        for e in entities
    )
    if one_protein and not w.full("polymer_uniprot"):
        chains = [
            a
            for e in entities
            for a in e["rcsb_polymer_entity_container_identifiers"].get("auth_asym_ids") or []
        ]
        asked = "do the protein chains" if len(chains) > 1 else "does the protein chain"
        w.add(
            "polymer_uniprot",
            f"polymer-{pdb_id}",
            f"Which UniProtKB accession {asked} in PDB entry {pdb_id} map to?",
            "token",
            p.accession,
            [pdb_id, p.accession],
            call("get_structure", pdb_id=pdb_id),
        )
    ligands = [n for n in raw.nonpolymers(pdb_id, entry) if n.get("comp_id")]
    real = [n for n in ligands if n["comp_id"] not in pdb.ADDITIVES]
    if len(real) == 1 and real[0].get("name") and not w.full("ligand_comp_id"):
        comp_id, name = str(real[0]["comp_id"]), str(real[0]["name"])
        if comp_id.upper() not in re.findall(r"[A-Z0-9]+", name.upper()):
            w.add(
                "ligand_comp_id",
                f"ligand-{pdb_id}",
                f'PDB entry {pdb_id} has a ligand recorded as "{name}" bound. What is the '
                "chemical component ID of that ligand in the entry?",
                "token",
                comp_id,
                [pdb_id],
                call("get_structure", pdb_id=pdb_id),
            )


def numbering_families(w: Writer, proteins: list[Protein], seed: int) -> None:
    """Author numbering against UniProtKB numbering, one chain at a time."""
    for round_index in (0, 1):  # every protein's first chain before any second chain
        for p in proteins:
            if round_index < len(p.chains):
                chain_items(w, p, p.chains[round_index], seed)


def chain_items(w: Writer, p: Protein, chain: Chain, seed: int) -> None:
    acc, pdb_id, cid = p.accession, chain.pdb_id, chain.chain
    ids = [pdb_id, acc]

    def pick(what: str, sites: list[Site]) -> Site:
        return rng_for(seed, "chain", pdb_id, cid, what).choice(sites)

    modelled = [s for s in chain.sites if s.observed and s.letter == s.canonical]
    plain = [s for s in modelled if s.number is not None]
    shifted = [s for s in plain if s.number != s.position]
    same = [s for s in plain if s.number == s.position]
    inserted = [s for s in modelled if s.insertion]
    missing = [s for s in chain.sites if not s.observed and s.number is not None]
    differing = [
        s
        for s in chain.sites
        if s.observed
        and s.canonical
        and s.letter != s.canonical
        and s.letter in THREE
        and s.canonical in THREE
    ]

    if inserted and not w.full("insertion_code"):
        site = pick("insertion", inserted)
        assert site.insertion is not None
        number, code = site.insertion
        lookup = call(
            "map_structure_residue",
            pdb_id=pdb_id,
            chain=cid,
            residue_number=number,
            insertion_code=code,
        )
        if w.counts.get("insertion_code", 0) % 2 == 0:
            w.add(
                "insertion_code",
                f"insertion-{pdb_id}-{cid}-{site.author}-residue",
                f"In PDB entry {pdb_id}, chain {cid}, which amino acid is residue {site.author} "
                f"(author numbering, with insertion code {code})? Answer with the one-letter "
                "code.",
                "residue",
                site.letter,
                ids,
                lookup,
            )
        else:
            w.add(
                "insertion_code",
                f"insertion-{pdb_id}-{cid}-{site.author}-position",
                f"In PDB entry {pdb_id}, chain {cid}, residue {site.author} (author numbering, "
                f"with insertion code {code}): which position of UniProtKB {acc} ({p.label}) "
                "does it correspond to? Answer with the position number only.",
                "position",
                site.position,
                ids,
                lookup,
            )

    if differing and not w.full("engineered_mutation"):
        site = pick("difference", differing)
        w.add(
            "engineered_mutation",
            f"difference-{pdb_id}-{cid}-{site.position}",
            difference_text(pdb_id, cid, site.position, acc, p.label),
            "mutation",
            f"{site.canonical}{site.position}{site.letter}",
            ids,
            call("map_structure_residue", pdb_id=pdb_id, chain=cid, uniprot_position=site.position),
        )
    elif not differing and modelled and not w.planted_full("no_difference"):
        site = pick("no difference", modelled)
        w.plant(
            "no_difference",
            f"difference-{pdb_id}-{cid}-{site.position}",
            difference_text(pdb_id, cid, site.position, acc, p.label),
            f"chain {cid} of {pdb_id} has {site.letter} at UniProtKB position {site.position}, "
            f"the same as the canonical sequence of {acc}",
            ids,
            call("map_structure_residue", pdb_id=pdb_id, chain=cid, uniprot_position=site.position),
            {"data": {"uniprot_position": site.position, "matches_uniprot": True}},
        )

    if shifted:
        # Author number N is not UniProtKB position N, and the two residues differ.
        telling = [
            s
            for s in shifted
            if s.number is not None
            and s.number >= 1
            and (s.number > len(p.sequence) or p.sequence[s.number - 1] != s.letter)
        ]
        # Every third chain with shifted numbering carries the planted twin instead.
        plant = w.tick("shifted") % 3 == 2 or w.full("structure_numbering")
        if telling and plant and not w.planted_full("author_number_as_uniprot"):
            site = pick("same number", telling)
            assert site.number is not None
            there = (
                f"position {site.number} of {acc} is {p.sequence[site.number - 1]}"
                if site.number <= len(p.sequence)
                else f"{acc} has only {len(p.sequence)} residues"
            )
            w.plant(
                "author_number_as_uniprot",
                f"samenumber-{pdb_id}-{cid}-{site.number}",
                same_number_text(pdb_id, cid, site.number, acc, p.label),
                f"author residue {site.number} of chain {cid} is {site.letter} and maps to "
                f"UniProtKB position {site.position}; {there}",
                ids,
                call("map_structure_residue", pdb_id=pdb_id, chain=cid, residue_number=site.number),
                {"data": {"author_residue": str(site.number), "uniprot_position": site.position}},
            )
        elif not w.full("structure_numbering"):
            site = pick("numbering", shifted)
            assert site.number is not None
            w.add(
                "structure_numbering",
                f"numbering-{pdb_id}-{cid}-{site.number}",
                numbering_text(pdb_id, cid, site.number, acc, p.label),
                "position",
                site.position,
                ids,
                call("map_structure_residue", pdb_id=pdb_id, chain=cid, residue_number=site.number),
            )
    elif same and not w.full("structure_residue"):
        site = pick("same number", same)
        assert site.number is not None
        w.add(
            "structure_residue",
            f"samenumber-{pdb_id}-{cid}-{site.number}",
            same_number_text(pdb_id, cid, site.number, acc, p.label),
            "residue",
            site.letter,
            ids,
            call("map_structure_residue", pdb_id=pdb_id, chain=cid, residue_number=site.number),
        )

    if plain and not w.full("modelled_residue"):
        site = pick("modelled", plain)
        assert site.number is not None
        w.add(
            "modelled_residue",
            f"modelled-{pdb_id}-{cid}-{site.number}",
            modelled_text(pdb_id, cid, site.number),
            "residue",
            site.letter,
            ids,
            call("map_structure_residue", pdb_id=pdb_id, chain=cid, residue_number=site.number),
        )

    if missing and not w.planted_full("unmodelled_residue"):
        site = pick("unmodelled", missing)
        assert site.number is not None
        w.plant(
            "unmodelled_residue",
            f"modelled-{pdb_id}-{cid}-{site.number}",
            modelled_text(pdb_id, cid, site.number),
            f"residue {site.number} of chain {cid} is in the construct of {pdb_id} but has no "
            "coordinates: no amino acid is modelled there",
            ids,
            call("map_structure_residue", pdb_id=pdb_id, chain=cid, residue_number=site.number),
            {"data": {"author_residue": str(site.number), "observed": False}},
        )


def variant_families(w: Writer, raw: Raw, proteins: list[Protein], seed: int) -> None:
    for p in proteins:
        records = clean_substitutions(raw, p) if p.reviewed else []
        if not records:
            continue
        rng = rng_for(seed, "variant", p.accession)
        rng.shuffle(records)
        acc = p.accession
        if not w.full("variant_lookup"):
            kind, pos, original, replacement = records.pop()
            w.add(
                "variant_lookup",
                f"variant-{acc}-{original}{pos}{replacement}",
                variant_text(kind, original, pos, acc, p.label),
                "mutation",
                f"{original}{pos}{replacement}",
                [acc],
                call("get_variants", accession=acc, start=pos),
            )
        if records and not w.planted_full("wrong_wild_type"):
            kind, pos, original, replacement = records.pop()
            wrong = rng.choice(sorted(set(THREE) - {original, replacement}))
            w.plant(
                "wrong_wild_type",
                f"variant-{acc}-{wrong}{pos}",
                variant_text(kind, wrong, pos, acc, p.label),
                f"position {pos} of {acc} is {THREE[original]}, not {THREE[wrong]}; the record "
                f"there is {original}{pos}{replacement}",
                [acc],
                call("get_variants", accession=acc, start=pos),
                {
                    "data": {
                        "reference": [
                            {
                                "position": pos,
                                "one_letter": original,
                                "three_letter": THREE[original],
                            }
                        ]
                    }
                },
                correction=("mutation", f"{original}{pos}{replacement}"),
            )


def alphafold_families(w: Writer, raw: Raw, proteins: list[Protein]) -> None:
    # The AlphaFold strata first; the rest of the panel fills what is left.
    ordered = sorted(proteins, key=lambda p: p.stratum not in ("rev_af", "unrev_af"))
    for p in ordered:
        acc = p.accession
        model = raw.af(acc)
        if model is None or model.get("fractionPlddtVeryHigh") is None:
            continue
        ids = [str(model["entryId"]), f"alphafold.ebi.ac.uk/entry/{acc}", acc]
        if not w.full("af_fraction"):
            w.add(
                "af_fraction",
                f"affraction-{acc}",
                f"In the AlphaFold DB model for UniProtKB {acc} ({p.label}), what fraction of "
                "residues has very high confidence (pLDDT above 90)? Give a number between 0 "
                "and 1.",
                "float",
                float(model["fractionPlddtVeryHigh"]),
                ids,
                call("get_alphafold_summary", accession=acc),
                tolerance=0.01,
            )
        elif not w.full("af_mean") and model.get("globalMetricValue") is not None:
            w.add(
                "af_mean",
                f"afmean-{acc}",
                f"What is the mean pLDDT of the AlphaFold DB model for UniProtKB {acc} "
                f"({p.label})?",
                "float",
                round(float(model["globalMetricValue"]), 2),
                ids,
                call("get_alphafold_summary", accession=acc),
                tolerance=0.5,
            )


def obsolete_families(w: Writer, raw: Raw, pools: Fetcher, seed: int) -> None:
    """Removed PDB entries, drawn by seed from the archive's list of them."""
    removed = sorted(str(i) for i in pools.get_json(REMOVED_IDS_URL).body)
    rng_for(seed, "obsolete").shuffle(removed)
    for old in removed[:400]:
        if w.full("obsolete_replacement") and w.planted_full("obsolete_no_successor"):
            break
        if not pdb.PDB_ID_RE.match(old):
            continue
        record = raw.removed(old)
        successors = [str(s).upper() for s in record.get("id_codes_replaced_by") or []]
        _, combined = raw.holdings(old)
        latest = str(combined.get("id_code_replaced_by_latest") or "").upper()
        # Status OBS only: a theoretical model moved to another archive is "removed" too,
        # but it was never made obsolete and has no removal record.
        if combined.get("status_code") != "OBS" or not record or raw.pdb_entry(old)[0] != 404:
            continue
        if len(successors) == 1 and successors[0] == latest and not w.full("obsolete_replacement"):
            if raw.pdb_entry(latest)[1] is None:
                continue  # the successor is itself gone
            w.add(
                "obsolete_replacement",
                f"obsolete-{old}",
                obsolete_text(old),
                "id_set",
                [latest],
                [old, latest],
                call("get_structure", pdb_id=old),
            )
        elif not successors and not latest and not w.planted_full("obsolete_no_successor"):
            w.plant(
                "obsolete_no_successor",
                f"obsolete-{old}",
                obsolete_text(old),
                f"{old} was removed from the archive and nothing superseded it",
                [old],
                call("get_structure", pdb_id=old),
                {"note_contains": "has no replacement"},
            )


def planted_lookups(w: Writer, raw: Raw, proteins: list[Protein], seed: int) -> None:
    """The planted twins of the simple lookup families."""
    rng = rng_for(seed, "planted")
    while not w.planted_full("absent_pdb"):
        pdb_id = str(rng.randint(1, 9)) + "".join(
            rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(3)
        )
        if raw.pdb_entry(pdb_id)[0] != 404 or raw.holdings(pdb_id)[0] != 404:
            continue  # released, on hold or removed: only an ID the archive never issued counts
        w.plant(
            "absent_pdb",
            f"absent-{pdb_id}",
            method_text(pdb_id),
            f"the PDB archive has no entry {pdb_id}",
            [pdb_id],
            call("get_structure", pdb_id=pdb_id),
            "not_found",
        )
    while not w.planted_full("absent_accession"):
        fake = (
            rng.choice("OPQ")
            + rng.choice("0123456789")
            + "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(3))
            + rng.choice("0123456789")
        )
        missing = raw.f.get_json(uniprot.entry_url(fake)).status == 404
        if not missing or raw.f.get_json(alphafold.prediction_url(fake)).status != 404:
            continue
        # These two cannot carry "(name, organism)" as their answerable twins do.
        if w.planted_counts.get("absent_accession", 0) == 0:
            text = f"What is the mean pLDDT of the AlphaFold DB model for UniProtKB {fake}?"
            lookup = call("get_alphafold_summary", accession=fake)
        else:
            text = f"How many residues long is the canonical sequence of UniProtKB entry {fake}?"
            lookup = call("get_protein", accession=fake)
        w.plant(
            "absent_accession",
            f"absent-{fake}",
            text,
            f"{fake} is not a UniProtKB entry and has no AlphaFold DB model",
            [fake],
            lookup,
            "not_found",
        )
    asked = {q.id for q in w.questions}
    spare = [p for p in proteins if f"length-{p.accession}" not in asked]
    for p in reversed(spare):  # the far end of the panel, away from the answerable items
        acc = p.accession
        if not w.planted_full("past_end"):
            pos = len(p.sequence) + rng.randint(1, 25)
            w.plant(
                "past_end",
                f"residue-{acc}-{pos}",
                residue_text(acc, p.label, pos),
                f"{acc} has only {len(p.sequence)} residues",
                [acc],
                call("get_sequence_window", accession=acc, start=pos, end=pos),
                "not_found",
            )
        elif not w.planted_full("absent_feature"):
            absent = [(t, word) for t, word in ABSENT_FEATURES if not p.has_feature(t)]
            if not absent:
                continue
            ftype, word = absent[w.planted_counts.get("absent_feature", 0) % len(absent)]
            w.plant(
                "absent_feature",
                f"feature-{acc}-{ftype.lower().replace(' ', '')}",
                feature_text(acc, p.label, word),
                f"UniProtKB annotates no {word} on {acc}",
                [acc],
                call("get_features", accession=acc, feature_type=ftype),
                "not_found",
            )


def build(raw: Raw, pools: Fetcher, seed: int) -> tuple[list[Question], list[Protein], Any]:
    panel, log = draw_panel(raw, pools, seed)
    proteins = interleave(panel)
    w = Writer()
    sequence_families(w, raw, proteins, seed)
    isoform_families(w, raw, proteins, seed)
    structure_families(w, raw, proteins, seed)
    numbering_families(w, proteins, seed)
    variant_families(w, raw, proteins, seed)
    alphafold_families(w, raw, proteins)
    obsolete_families(w, raw, pools, seed)
    planted_lookups(w, raw, proteins, seed)
    ligand_ids = {str(q.gold) for q in w.questions if q.family == "ligand_comp_id"}
    for q in w.questions:
        if q.family == "ligand_comp_id":
            q.reject = sorted(ligand_ids - {str(q.gold)})
    ids = [q.id for q in w.questions]
    assert len(set(ids)) == len(ids), "duplicate question IDs"
    return w.questions, proteins, {"strata": log, "planted_kinds": w.planted_counts}


def prewarm(fetcher: Fetcher, raw: Raw, questions: list[Question], proteins: list[Protein]) -> None:
    """Record what an agent is likely to request beyond the evidence calls."""

    def warm(name: str, **arguments: Any) -> None:
        text, is_error = run_tool(fetcher, name, arguments)
        assert not is_error, f"{name}({arguments}) failed: {text}"

    for q in questions:
        for ev in q.evidence:
            warm(ev.name, **ev.input)
    by_accession = {p.accession: p for p in proteins}
    for q in questions:
        if q.family != "accession_lookup":
            continue
        p = by_accession[str(q.gold)]
        species = " ".join(p.organism.split()[:2])
        for arguments in (
            {"query": f"gene:{p.gene}"},
            {"query": str(p.gene), "taxon_id": p.taxon},
            {"query": f"gene:{p.gene} AND organism_id:{p.taxon}"},
            {"query": f'gene:{p.gene} AND organism_name:"{species}"'},
            {"query": f"{p.gene} {species}"},
        ):
            run_tool(fetcher, "search_proteins", arguments)  # a miss here is not a failure
    structures: set[str] = set()
    for p in proteins:
        acc = p.accession
        warm("get_protein", accession=acc)
        warm("get_variants", accession=acc, start=1)
        warm("get_alphafold_summary", accession=acc)
        warm("search_proteins", query=f"accession:{acc}", reviewed_only=p.reviewed)
        for isoform_id in raw.isoform_ids(acc) if p.stratum == "isoform" else []:
            warm("get_sequence_window", accession=isoform_id, start=1, end=1)
        ranked = uniprot.list_structures(fetcher, acc, None, 3)
        structures.update(ref.pdb_id for ref in (ranked.data.structures if ranked.data else []))
        structures.update(c.pdb_id for c in p.chains)
    for q in questions:
        structures.update(r for r in q.record_ids if pdb.PDB_ID_RE.match(r))
    for pdb_id in sorted(structures):
        text, is_error = run_tool(fetcher, "get_structure", {"pdb_id": pdb_id})
        assert not is_error, f"get_structure({pdb_id}) failed: {text}"
        data = json.loads(text).get("data") or {}
        polymers = data.get("polymer_entities", [])
        # Every chain an agent may ask to map, and the UniProtKB entries they align to.
        for chain_id in sorted({c for e in polymers for c in e.get("chains", [])})[:8]:
            run_tool(
                fetcher,
                "map_structure_residue",
                {"pdb_id": pdb_id, "chain": chain_id, "residue_number": 1},
            )
        for accession in sorted({a for e in polymers for a in e.get("uniprot_accessions", [])})[:6]:
            run_tool(fetcher, "get_protein", {"accession": accession})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--refresh", action="store_true", help="refetch everything live")
    args = parser.parse_args()
    if args.refresh:
        for folder in (SNAPSHOT, POOLS):
            for path in folder.glob("*.json.gz"):
                path.unlink()
    fetcher = Fetcher(cache_dir=SNAPSHOT, mode=Mode.CACHE_FIRST)
    pools = Fetcher(cache_dir=POOLS, mode=Mode.CACHE_FIRST)
    raw = Raw(fetcher)
    questions, proteins, log = build(raw, pools, args.seed)
    prewarm(fetcher, raw, questions, proteins)

    planted = sum(not q.premise_ok for q in questions)
    share = planted / len(questions)
    assert len(questions) >= MIN_QUESTIONS, f"only {len(questions)} questions"
    assert PLANTED_SHARE[0] <= share <= PLANTED_SHARE[1], f"planted share {share:.3f}"
    write_questions(QUESTIONS, questions)
    families: dict[str, int] = {}
    for q in questions:
        if q.premise_ok:
            families[q.family] = families.get(q.family, 0) + 1
    first = proteins[0].accession
    release = fetcher.get_json(uniprot.entry_url(first)).headers.get("x-uniprot-release")
    versions = sorted(
        {
            int(m["latestVersion"])
            for p in proteins
            if (m := raw.af(p.accession)) is not None and m.get("latestVersion") is not None
        }
    )
    MANIFEST.write_text(
        json.dumps(
            {
                "built_at": datetime.now(UTC).strftime("%Y-%m-%d"),
                "seed": args.seed,
                "uniprot_release": release,
                "alphafold_model_versions": versions,
                "questions": len(questions),
                "answerable": len(questions) - planted,
                "planted_false_premise": planted,
                "planted_share": round(share, 3),
                "families": families,
                "planted_kinds": log["planted_kinds"],
                "proteins": len(proteins),
                "reviewed": sum(p.reviewed for p in proteins),
                "unreviewed": sum(not p.reviewed for p in proteins),
                "organisms": len({p.organism for p in proteins}),
                "excluded_organisms": MODEL_ORGANISMS,
                "length_range": [MIN_LENGTH, MAX_LENGTH],
                "strata": log["strata"],
                "snapshot_files": len(list(SNAPSHOT.glob("*.json.gz"))),
                "pool_files": len(list(POOLS.glob("*.json.gz"))),
            },
            indent=2,
        )
        + "\n"
    )
    summary = json.loads(MANIFEST.read_text())
    summary["strata"] = {
        k: f"{len(v['drawn'])} drawn, {len(v['passed_over'])} passed over"
        for k, v in summary["strata"].items()
    }
    del summary["excluded_organisms"]
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
