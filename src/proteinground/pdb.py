"""RCSB PDB Data API client: entry metadata, polymer entities and bound ligands."""

from __future__ import annotations

import re
from typing import Any

from proteinground.fetch import Fetcher, Response
from proteinground.models import Cited, Ligand, PolymerEntity, Source, StructureEntry

BASE = "https://data.rcsb.org/rest/v1/core"
PDB_ID_RE = re.compile(r"^[1-9][A-Z0-9]{3}$")
MAX_ENTITIES = 12
# Common crystallisation additives. Kept in the ligand list, but flagged so an agent
# does not mistake glycerol for the drug.
ADDITIVES = frozenset(
    {"HOH", "SO4", "PO4", "GOL", "EDO", "CL", "NA", "K", "MG", "CA", "ZN", "ACT", "PEG",
     "DMS", "FMT", "IOD", "BR", "NO3", "MPD", "TRS", "EPE", "MES"}
)  # fmt: skip


def entry_url(pdb_id: str) -> str:
    return f"{BASE}/entry/{pdb_id}"


def polymer_url(pdb_id: str, entity_id: str) -> str:
    return f"{BASE}/polymer_entity/{pdb_id}/{entity_id}"


def nonpolymer_url(pdb_id: str, entity_id: str) -> str:
    return f"{BASE}/nonpolymer_entity/{pdb_id}/{entity_id}"


def source(pdb_id: str, response: Response) -> Source:
    return Source(
        database="RCSB PDB",
        record_id=pdb_id,
        url=f"https://www.rcsb.org/structure/{pdb_id}",
        retrieved_at=response.retrieved_at,
    )


def _date(value: Any) -> str | None:
    return str(value)[:10] if value else None


def _sorted_ids(ids: Any) -> list[str]:
    return sorted((str(i) for i in ids or []), key=lambda s: (len(s), s))


def get_structure(fetcher: Fetcher, raw_id: str) -> Cited[StructureEntry]:
    pdb_id = raw_id.strip().upper()
    if not PDB_ID_RE.match(pdb_id):
        return Cited[StructureEntry](found=False, note=f"'{raw_id}' is not a four-character PDB ID")
    response = fetcher.get_json(entry_url(pdb_id))
    if response.status != 200 or not isinstance(response.body, dict):
        return Cited[StructureEntry](
            found=False,
            note=f"RCSB PDB has no released entry {pdb_id} (HTTP {response.status})",
            sources=[source(pdb_id, response)],
        )
    body: dict[str, Any] = response.body
    info = body.get("rcsb_entry_info", {})
    resolutions = info.get("resolution_combined") or []
    ids = body.get("rcsb_entry_container_identifiers", {})
    polymer_ids = _sorted_ids(ids.get("polymer_entity_ids"))
    ligand_ids = _sorted_ids(ids.get("non_polymer_entity_ids"))
    truncated = len(polymer_ids) > MAX_ENTITIES or len(ligand_ids) > MAX_ENTITIES

    polymers: list[PolymerEntity] = []
    for entity_id in polymer_ids[:MAX_ENTITIES]:
        entity = fetcher.get_json(polymer_url(pdb_id, entity_id)).body or {}
        container = entity.get("rcsb_polymer_entity_container_identifiers", {})
        polymers.append(
            PolymerEntity(
                entity_id=entity_id,
                description=entity.get("rcsb_polymer_entity", {}).get("pdbx_description"),
                polymer_type=entity.get("entity_poly", {}).get("rcsb_entity_polymer_type"),
                uniprot_accessions=[str(a) for a in container.get("uniprot_ids") or []],
            )
        )
    ligands: list[Ligand] = []
    for entity_id in ligand_ids[:MAX_ENTITIES]:
        entity = fetcher.get_json(nonpolymer_url(pdb_id, entity_id)).body or {}
        nonpoly = entity.get("pdbx_entity_nonpoly", {})
        comp_id = nonpoly.get("comp_id")
        if not comp_id:
            continue
        name = nonpoly.get("name")
        if comp_id in ADDITIVES and name:
            name = f"{name} (common additive or ion)"
        ligands.append(Ligand(comp_id=str(comp_id), name=name))

    entry = StructureEntry(
        pdb_id=pdb_id,
        title=body.get("struct", {}).get("title"),
        methods=[str(e.get("method")) for e in body.get("exptl", []) if e.get("method")],
        resolution_angstrom=float(resolutions[0]) if resolutions else None,
        deposit_date=_date(body.get("rcsb_accession_info", {}).get("deposit_date")),
        release_date=_date(body.get("rcsb_accession_info", {}).get("initial_release_date")),
        polymer_entities=polymers,
        ligands=ligands,
        truncated=truncated,
    )
    note = f"showing the first {MAX_ENTITIES} entities of each kind" if truncated else None
    return Cited[StructureEntry](
        found=True, data=entry, note=note, sources=[source(pdb_id, response)]
    )
