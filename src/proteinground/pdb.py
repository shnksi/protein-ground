"""RCSB PDB client: entry metadata, entities, ligands and residue numbering.

The entry itself comes from the REST Data API, where a 404 is an honest "no such released
entry". Its entities come from one GraphQL request instead of one REST call per entity,
and residue mapping reads one chain the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from proteinground import uniprot
from proteinground.fetch import (
    Fetcher,
    InvalidInputError,
    MalformedRecordError,
    OfflineMissError,
    RejectedRequestError,
    Response,
    UpstreamError,
    raise_if_rejected,
)
from proteinground.models import (
    ChainCoverage,
    Cited,
    Ligand,
    PolymerEntity,
    ResidueMapping,
    Source,
    StructureEntry,
)

BASE = "https://data.rcsb.org/rest/v1/core"
HOLDINGS = "https://data.rcsb.org/rest/v1/holdings/status"
GRAPHQL = "https://data.rcsb.org/graphql"
PDB_ID_RE = re.compile(r"^[1-9][A-Z0-9]{3}$")
_ASYM_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")
MAX_POLYMERS = 100
MAX_LIGANDS = 40
# Common crystallisation additives vs metal ions that may be catalytic/structural cofactors.
# Both stay in the ligand list, flagged so an agent does not mistake glycerol for a drug
# or blindly dismiss a catalytic zinc or magnesium ion.
METAL_IONS = frozenset({"ZN", "MG", "CA", "MN", "FE", "CU"})
ADDITIVES = frozenset(
    {"HOH", "SO4", "PO4", "GOL", "EDO", "CL", "NA", "K", "ACT", "PEG",
     "DMS", "FMT", "IOD", "BR", "NO3", "MPD", "TRS", "EPE", "MES"}
)  # fmt: skip
# The query text is part of the cache key: editing it means re-recording the snapshot.
_ENTITIES_QUERY = (
    '{entry(entry_id:"%s"){rcsb_id '
    "polymer_entities{"
    "rcsb_polymer_entity_container_identifiers{entity_id uniprot_ids} "
    "rcsb_polymer_entity{pdbx_description pdbx_mutation} "
    "entity_poly{rcsb_entity_polymer_type rcsb_sample_sequence_length} "
    "rcsb_entity_source_organism{ncbi_scientific_name ncbi_taxonomy_id} "
    "polymer_entity_instances{"
    "rcsb_polymer_entity_instance_container_identifiers{asym_id auth_asym_id}}} "
    "nonpolymer_entities{"
    "rcsb_nonpolymer_entity_container_identifiers{entity_id auth_asym_ids} "
    "pdbx_entity_nonpoly{comp_id name}}}}"
)
_CHAIN_QUERY = (
    '{polymer_entity_instance(entry_id:"%s",asym_id:"%s"){'
    "rcsb_polymer_entity_instance_container_identifiers{"
    "asym_id auth_asym_id entity_id auth_to_entity_poly_seq_mapping} "
    "rcsb_polymer_instance_feature{type feature_positions{beg_seq_id end_seq_id}} "
    "polymer_entity{"
    "rcsb_polymer_entity{pdbx_description pdbx_mutation} "
    "entity_poly{pdbx_seq_one_letter_code_can} "
    "rcsb_entity_source_organism{ncbi_scientific_name} "
    "rcsb_polymer_entity_align{reference_database_name reference_database_accession "
    "aligned_regions{entity_beg_seq_id ref_beg_seq_id length}}}}}"
)


def entry_url(pdb_id: str) -> str:
    return f"{BASE}/entry/{pdb_id}"


def polymer_url(pdb_id: str, entity_id: str) -> str:
    """REST record for one polymer entity. The eval's gold answers are computed from it."""
    return f"{BASE}/polymer_entity/{pdb_id}/{entity_id}"


def nonpolymer_url(pdb_id: str, entity_id: str) -> str:
    """REST record for one ligand entity. The eval's gold answers are computed from it."""
    return f"{BASE}/nonpolymer_entity/{pdb_id}/{entity_id}"


def holdings_url(pdb_id: str) -> str:
    return f"{HOLDINGS}/{pdb_id}"


def entities_url(pdb_id: str) -> str:
    return f"{GRAPHQL}?{urlencode({'query': _ENTITIES_QUERY % pdb_id})}"


def chain_url(pdb_id: str, asym_id: str) -> str:
    return f"{GRAPHQL}?{urlencode({'query': _CHAIN_QUERY % (pdb_id, asym_id)})}"


def source(pdb_id: str, response: Response) -> Source:
    return Source(
        database="RCSB PDB",
        record_id=pdb_id,
        url=f"https://www.rcsb.org/structure/{pdb_id}",
        retrieved_at=response.retrieved_at,
    )


def _date(value: Any) -> str | None:
    return str(value)[:10] if value else None


def _id_key(value: str) -> tuple[int, str]:
    return (len(value), value)


def _graphql(fetcher: Fetcher, url: str, what: str) -> dict[str, Any]:
    """Run one GraphQL query. An error in the reply is a rejected request, not "no data"."""
    response = fetcher.get_json(url)
    raise_if_rejected(response, what)
    body = response.body
    if response.status != 200 or not isinstance(body, dict):
        raise UpstreamError(f"{what}: HTTP {response.status} from the RCSB GraphQL API")
    if body.get("errors"):
        raise RejectedRequestError(
            f"{what}: RCSB PDB rejected the query ({response.upstream_message()}). This is "
            "a problem with the query, not evidence that the record is missing."
        )
    data = body.get("data")
    if not isinstance(data, dict):
        raise MalformedRecordError(f"{what}: the GraphQL reply carried no data")
    return data


def _missing(fetcher: Fetcher, pdb_id: str, response: Response) -> Cited[Any]:
    """Explain a 404: obsolete and superseded, deposited but on hold, or never assigned."""
    cited = [source(pdb_id, response)]
    try:
        holdings = fetcher.get_json(holdings_url(pdb_id))
    except (UpstreamError, OfflineMissError):
        return Cited(
            found=False,
            note=f"RCSB PDB has no released entry {pdb_id} (HTTP {response.status}); whether "
            "it was withdrawn or is still on hold could not be checked",
            sources=cited,
        )
    combined = (
        holdings.body.get("rcsb_repository_holdings_combined", {})
        if holdings.status == 200 and isinstance(holdings.body, dict)
        else {}
    )
    status = str(combined.get("status") or "")
    if status == "REMOVED":
        successor = combined.get("id_code_replaced_by_latest")
        note = f"PDB entry {pdb_id} is obsolete: it was removed from the archive and " + (
            f"superseded by {successor}; look that entry up instead"
            if successor
            else "has no replacement"
        )
    elif status == "UNRELEASED":
        note = (
            f"PDB entry {pdb_id} has been deposited but is not released (status "
            f"{combined.get('status_code', 'unknown')}), so it has no public coordinates, "
            "method or resolution yet"
        )
    elif holdings.status == 404:
        note = f"RCSB PDB has no entry {pdb_id}: that ID is not in the archive"
    else:
        note = f"RCSB PDB has no released entry {pdb_id} (HTTP {response.status})"
    return Cited(found=False, note=note, sources=cited)


def _load_entry(fetcher: Fetcher, raw_id: str) -> tuple[str, Response | None, Cited[Any]]:
    """Check the ID and fetch the entry. The response is None when there is no entry."""
    pdb_id = raw_id.strip().upper()
    if not PDB_ID_RE.match(pdb_id):
        return pdb_id, None, Cited(found=False, note=f"'{raw_id}' is not a four-character PDB ID")
    response = fetcher.get_json(entry_url(pdb_id))
    raise_if_rejected(response, f"RCSB PDB {pdb_id}")
    if response.status in (404, 410):
        return pdb_id, None, _missing(fetcher, pdb_id, response)
    if not isinstance(response.body, dict):
        raise MalformedRecordError(f"RCSB PDB {pdb_id}: the response was not a record")
    return pdb_id, response, Cited(found=True, sources=[source(pdb_id, response)])


def _entities(fetcher: Fetcher, pdb_id: str) -> dict[str, Any]:
    entry = _graphql(fetcher, entities_url(pdb_id), f"RCSB PDB {pdb_id}").get("entry")
    if not isinstance(entry, dict):
        raise MalformedRecordError(
            f"RCSB PDB {pdb_id}: the entry exists but its entity records did not load"
        )
    return entry


def _organisms(raw: dict[str, Any]) -> tuple[str | None, int | None]:
    items = raw.get("rcsb_entity_source_organism") or []
    names: list[str] = []
    for item in items:
        name = item.get("ncbi_scientific_name")
        if name and str(name) not in names:
            names.append(str(name))
    taxon = items[0].get("ncbi_taxonomy_id") if items else None
    return ("; ".join(names) or None), taxon


def _polymers(entry: dict[str, Any]) -> list[PolymerEntity]:
    polymers: list[PolymerEntity] = []
    for raw in entry.get("polymer_entities") or []:
        ids = raw.get("rcsb_polymer_entity_container_identifiers") or {}
        organism, taxon_id = _organisms(raw)
        poly = raw.get("entity_poly") or {}
        chains = [
            str((inst.get("rcsb_polymer_entity_instance_container_identifiers") or {})
                .get("auth_asym_id") or "")
            for inst in raw.get("polymer_entity_instances") or []
        ]  # fmt: skip
        polymers.append(
            PolymerEntity(
                entity_id=str(ids.get("entity_id", "")),
                description=(raw.get("rcsb_polymer_entity") or {}).get("pdbx_description"),
                polymer_type=poly.get("rcsb_entity_polymer_type"),
                chains=sorted((c for c in chains if c), key=_id_key),
                organism=organism,
                taxon_id=taxon_id,
                length=poly.get("rcsb_sample_sequence_length"),
                mutation=(raw.get("rcsb_polymer_entity") or {}).get("pdbx_mutation"),
                uniprot_accessions=[str(a) for a in ids.get("uniprot_ids") or []],
            )
        )
    polymers.sort(key=lambda p: _id_key(p.entity_id))
    return polymers


def _ligands(entry: dict[str, Any]) -> list[Ligand]:
    ligands: list[tuple[str, Ligand]] = []
    for raw in entry.get("nonpolymer_entities") or []:
        ids = raw.get("rcsb_nonpolymer_entity_container_identifiers") or {}
        nonpoly = raw.get("pdbx_entity_nonpoly") or {}
        comp_id = nonpoly.get("comp_id")
        if not comp_id:
            continue
        name = nonpoly.get("name")
        if name:
            if comp_id in METAL_IONS:
                name = f"{name} (metal ion; may be a cofactor or crystallisation additive)"
            elif comp_id in ADDITIVES:
                name = f"{name} (common additive or ion)"
        chains = sorted((str(c) for c in ids.get("auth_asym_ids") or []), key=_id_key)
        ligands.append(
            (str(ids.get("entity_id", "")), Ligand(comp_id=str(comp_id), name=name, chains=chains))
        )
    ligands.sort(key=lambda pair: _id_key(pair[0]))
    return [ligand for _, ligand in ligands]


def _refine_float(body: dict[str, Any], key: str) -> float | None:
    refine = body.get("refine") or []
    if not refine or not isinstance(refine[0], dict):
        return None
    value = refine[0].get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return round(float(value), 4)


def get_structure(fetcher: Fetcher, raw_id: str) -> Cited[StructureEntry]:
    pdb_id, response, result = _load_entry(fetcher, raw_id)
    if response is None:
        return Cited[StructureEntry](found=False, note=result.note, sources=result.sources)
    body: dict[str, Any] = response.body
    info = body.get("rcsb_entry_info", {})
    resolutions = info.get("resolution_combined") or []
    entities = _entities(fetcher, pdb_id)
    polymers, ligands = _polymers(entities), _ligands(entities)
    truncated = len(polymers) > MAX_POLYMERS or len(ligands) > MAX_LIGANDS
    entry = StructureEntry(
        pdb_id=pdb_id,
        title=body.get("struct", {}).get("title"),
        methods=[str(e.get("method")) for e in body.get("exptl", []) if e.get("method")],
        resolution_angstrom=float(resolutions[0]) if resolutions else None,
        r_free=_refine_float(body, "ls_R_factor_R_free"),
        r_work=_refine_float(body, "ls_R_factor_R_work"),
        deposit_date=_date(body.get("rcsb_accession_info", {}).get("deposit_date")),
        release_date=_date(body.get("rcsb_accession_info", {}).get("initial_release_date")),
        polymer_entities=polymers[:MAX_POLYMERS],
        ligands=ligands[:MAX_LIGANDS],
        truncated=truncated,
    )
    note = (
        f"showing the first {MAX_POLYMERS} polymer entities and {MAX_LIGANDS} ligands"
        if truncated
        else None
    )
    return Cited[StructureEntry](found=True, data=entry, note=note, sources=result.sources)


# Residue numbering: author numbers in a chain <-> positions on the UniProtKB sequence.


@dataclass(frozen=True)
class _Segment:
    """A gap-free run of the deposited construct aligned to one UniProtKB sequence."""

    accession: str
    seq_start: int  # 1-based index into the construct
    uniprot_start: int
    length: int

    def uniprot_position(self, seq_id: int) -> int | None:
        offset = seq_id - self.seq_start
        return self.uniprot_start + offset if 0 <= offset < self.length else None

    def seq_id(self, uniprot_position: int) -> int | None:
        offset = uniprot_position - self.uniprot_start
        return self.seq_start + offset if 0 <= offset < self.length else None


@dataclass(frozen=True)
class _Chain:
    author_id: str
    asym_id: str
    entity_id: str
    description: str | None
    organism: str | None
    mutation: str | None
    numbering: list[str]  # author residue number of each construct position
    sequence: str  # one letter per construct position
    segments: list[_Segment]
    unobserved: list[tuple[int, int]] | None  # construct ranges with no coordinates

    def observed(self, seq_id: int) -> bool | None:
        if self.unobserved is None:
            return None
        return not any(first <= seq_id <= last for first, last in self.unobserved)

    def coverage(self) -> list[ChainCoverage]:
        out: list[ChainCoverage] = []
        for seg in self.segments:
            last = seg.seq_start + seg.length - 1
            if 1 <= seg.seq_start <= last <= len(self.numbering):
                out.append(
                    ChainCoverage(
                        uniprot_accession=seg.accession,
                        uniprot_start=seg.uniprot_start,
                        uniprot_end=seg.uniprot_start + seg.length - 1,
                        author_start=self.numbering[seg.seq_start - 1],
                        author_end=self.numbering[last - 1],
                    )
                )
        return out

    def describe(self) -> str:
        covered = self.coverage()
        if not covered:
            return "it has no residues aligned to UniProtKB"
        return "it covers " + ", ".join(
            f"{c.uniprot_accession} {c.uniprot_start}-{c.uniprot_end} "
            f"(author residues {c.author_start} to {c.author_end})"
            for c in covered
        )


def _chain_instances(entities: dict[str, Any]) -> list[tuple[str, str]]:
    """(author chain ID, mmCIF chain ID) for every polymer chain in the entry."""
    pairs: list[tuple[str, str]] = []
    for raw in entities.get("polymer_entities") or []:
        for inst in raw.get("polymer_entity_instances") or []:
            ids = inst.get("rcsb_polymer_entity_instance_container_identifiers") or {}
            if ids.get("asym_id"):
                pairs.append((str(ids.get("auth_asym_id") or ids["asym_id"]), str(ids["asym_id"])))
    return pairs


def _pick_chains(pairs: list[tuple[str, str]], wanted: str) -> list[tuple[str, str]]:
    """Chains matching what the caller typed: author ID first, then the mmCIF ID."""
    for index in (0, 1):
        exact = [p for p in pairs if p[index] == wanted]
        if exact:
            return exact
    return [p for p in pairs if p[0].upper() == wanted.upper()]


def _segments(entity: dict[str, Any]) -> list[_Segment]:
    segments: list[_Segment] = []
    for align in entity.get("rcsb_polymer_entity_align") or []:
        if str(align.get("reference_database_name", "")).lower() != "uniprot":
            continue
        accession = str(align.get("reference_database_accession") or "")
        for region in align.get("aligned_regions") or []:
            try:
                segments.append(
                    _Segment(
                        accession,
                        int(region["entity_beg_seq_id"]),
                        int(region["ref_beg_seq_id"]),
                        int(region["length"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
    return segments


def _unobserved(instance: dict[str, Any]) -> list[tuple[int, int]] | None:
    features = instance.get("rcsb_polymer_instance_feature")
    if features is None:
        return None
    spans: list[tuple[int, int]] = []
    for feature in features:
        if feature.get("type") != "UNOBSERVED_RESIDUE_XYZ":
            continue
        for span in feature.get("feature_positions") or []:
            if span.get("beg_seq_id") is not None:
                first = int(span["beg_seq_id"])
                spans.append((first, int(span.get("end_seq_id") or first)))
    return spans


def _load_chain(fetcher: Fetcher, pdb_id: str, author_id: str, asym_id: str) -> _Chain:
    if not _ASYM_RE.match(asym_id):
        raise MalformedRecordError(f"RCSB PDB {pdb_id}: unexpected chain ID '{asym_id}'")
    what = f"RCSB PDB {pdb_id} chain {author_id}"
    instance = _graphql(fetcher, chain_url(pdb_id, asym_id), what).get("polymer_entity_instance")
    if not isinstance(instance, dict):
        raise MalformedRecordError(f"{what}: the chain record did not load")
    ids = instance.get("rcsb_polymer_entity_instance_container_identifiers") or {}
    entity = instance.get("polymer_entity") or {}
    numbering = [str(n) for n in ids.get("auth_to_entity_poly_seq_mapping") or []]
    raw_sequence = (entity.get("entity_poly") or {}).get("pdbx_seq_one_letter_code_can") or ""
    sequence = re.sub(r"\s+", "", str(raw_sequence))
    if not numbering or len(numbering) != len(sequence):
        raise MalformedRecordError(f"{what}: residue numbering is unavailable")
    described = entity.get("rcsb_polymer_entity") or {}
    organisms = entity.get("rcsb_entity_source_organism") or [{}]
    return _Chain(
        author_id=author_id,
        asym_id=asym_id,
        entity_id=str(ids.get("entity_id", "")),
        description=described.get("pdbx_description"),
        organism=organisms[0].get("ncbi_scientific_name"),
        mutation=described.get("pdbx_mutation"),
        numbering=numbering,
        sequence=sequence,
        segments=_segments(entity),
        unobserved=_unobserved(instance),
    )


def _locate(
    chain: _Chain,
    pdb_id: str,
    author_residue: str | None,
    uniprot_position: int | None,
    uniprot_accession: str | None = None,
) -> tuple[int, _Segment | None] | str:
    """Find the construct position asked for, or say why this chain does not have it."""
    where = f"chain {chain.author_id} of {pdb_id}"
    if author_residue is not None:
        if author_residue not in chain.numbering:
            return (
                f"{where} has no residue numbered {author_residue} (author numbering runs "
                f"{chain.numbering[0]} to {chain.numbering[-1]}); {chain.describe()}"
            )
        seq_id = chain.numbering.index(author_residue) + 1
        aligned = [s for s in chain.segments if s.uniprot_position(seq_id) is not None]
        return seq_id, (aligned[0] if aligned else None)
    assert uniprot_position is not None
    hits = [s for s in chain.segments if s.seq_id(uniprot_position) is not None]
    if uniprot_accession is not None:
        wanted_acc = uniprot.normalise_accession(uniprot_accession)
        hits = [s for s in hits if s.accession.upper() == wanted_acc]
    accessions = sorted({s.accession for s in hits})
    if len(accessions) > 1:
        return (
            f"{where} is a fusion of {', '.join(accessions)}, and position {uniprot_position} "
            f"exists in more than one of them; pass uniprot_accession to disambiguate; "
            f"{chain.describe()}"
        )
    if not hits:
        for_acc = (
            f" of {uniprot.normalise_accession(uniprot_accession)}" if uniprot_accession else ""
        )
        return (
            f"{where} does not include UniProtKB position {uniprot_position}{for_acc}; "
            f"{chain.describe()}"
        )
    found = hits[0].seq_id(uniprot_position)
    assert found is not None
    return found, hits[0]


def _uniprot_residue(
    fetcher: Fetcher, accession: str, position: int
) -> tuple[str | None, list[Source], str | None]:
    """The canonical residue at a position, its source, and a note if it could not be read."""
    try:
        loaded, _ = uniprot.load_sequence(fetcher, accession)
    except (UpstreamError, OfflineMissError) as exc:
        return None, [], f"the UniProtKB residue could not be checked ({type(exc).__name__})"
    if loaded is None or position > len(loaded.sequence):
        return None, [], f"UniProtKB {accession} has no residue {position} to compare with"
    return loaded.sequence[position - 1], loaded.sources, None


def _mapping(
    fetcher: Fetcher, pdb_id: str, chain: _Chain, seq_id: int, segment: _Segment | None
) -> tuple[ResidueMapping, list[Source], list[str]]:
    letter = chain.sequence[seq_id - 1]
    author_residue = chain.numbering[seq_id - 1]
    notes: list[str] = []
    sources: list[Source] = []
    accession = position = uniprot_letter = None
    if segment is None:
        notes.append(
            f"residue {author_residue} is part of the construct but is not aligned to "
            "UniProtKB (an expression tag, linker or unmapped segment)"
        )
    else:
        accession, position = segment.accession, segment.uniprot_position(seq_id)
        assert position is not None
        uniprot_letter, sources, problem = _uniprot_residue(fetcher, accession, position)
        if problem:
            notes.append(problem)
    matches = None if uniprot_letter is None else uniprot_letter == letter
    if matches is False:
        notes.append(
            f"the structure has {letter} where {accession} has {uniprot_letter} at {position}: "
            "an engineered mutation, a variant or a sequence difference"
            + (f" (depositor's note: {chain.mutation})" if chain.mutation else "")
        )
    observed = chain.observed(seq_id)
    if observed is False:
        notes.append(
            "this residue is in the crystallised or imaged construct but was not modelled: "
            "it has no coordinates"
        )
    mapping = ResidueMapping(
        pdb_id=pdb_id,
        chain=chain.author_id,
        label_asym_id=chain.asym_id,
        entity_id=chain.entity_id,
        entity_description=chain.description,
        organism=chain.organism,
        author_residue=author_residue,
        label_seq_id=seq_id,
        structure_residue=letter,
        structure_residue_three_letter=uniprot.THREE_LETTER.get(letter, "Xaa"),
        observed=observed,
        uniprot_accession=accession,
        uniprot_position=position,
        uniprot_residue=uniprot_letter,
        matches_uniprot=matches,
        coverage=chain.coverage(),
    )
    return mapping, sources, notes


def map_structure_residue(
    fetcher: Fetcher,
    raw_id: str,
    chain: str,
    residue_number: int | None = None,
    insertion_code: str | None = None,
    uniprot_position: int | None = None,
    uniprot_accession: str | None = None,
) -> Cited[ResidueMapping]:
    """Translate between a chain's author numbering and UniProtKB positions.

    Give residue_number (with insertion_code if it has one) to go from the structure to
    UniProtKB, or uniprot_position to go the other way.
    """
    if (residue_number is None) == (uniprot_position is None):
        raise InvalidInputError("give exactly one of residue_number or uniprot_position")
    wanted_chain = chain.strip()
    if not _ASYM_RE.match(wanted_chain):
        raise InvalidInputError(f"'{chain}' is not a chain ID")
    pdb_id, response, result = _load_entry(fetcher, raw_id)
    if response is None:
        return Cited[ResidueMapping](found=False, note=result.note, sources=result.sources)
    pairs = _chain_instances(_entities(fetcher, pdb_id))
    candidates = _pick_chains(pairs, wanted_chain)
    if not candidates:
        known = ", ".join(sorted({p[0] for p in pairs}, key=_id_key)[:40]) or "none"
        return Cited[ResidueMapping](
            found=False,
            note=f"PDB entry {pdb_id} has no polymer chain '{wanted_chain}'; chains: {known}",
            sources=result.sources,
        )
    author_residue = (
        None
        if residue_number is None
        else f"{residue_number}{(insertion_code or '').strip().upper()}"
    )
    misses: list[str] = []
    for author_id, asym_id in candidates:  # an author chain ID can name more than one polymer
        loaded = _load_chain(fetcher, pdb_id, author_id, asym_id)
        located = _locate(loaded, pdb_id, author_residue, uniprot_position, uniprot_accession)
        if isinstance(located, str):
            misses.append(located)
            continue
        mapping, extra_sources, notes = _mapping(fetcher, pdb_id, loaded, *located)
        if author_id != wanted_chain:
            notes.insert(0, f"'{wanted_chain}' matched author chain {author_id}")
        return Cited[ResidueMapping](
            found=True,
            data=mapping,
            note="; ".join(notes) or None,
            sources=[*result.sources, *extra_sources],
        )
    return Cited[ResidueMapping](found=False, note="; ".join(misses), sources=result.sources)
