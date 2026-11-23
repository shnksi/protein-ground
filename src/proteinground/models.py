"""Typed results. Every tool returns a Cited[...] so each value travels with its source."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

Database = Literal["UniProtKB", "RCSB PDB", "AlphaFold DB"]
T = TypeVar("T")


class Source(BaseModel):
    database: Database
    record_id: str = Field(description="Accession, PDB ID or AlphaFold model ID")
    url: str = Field(description="Page a person can open to check the value")
    retrieved_at: str
    release: str | None = Field(default=None, description="Database release, when known")


class Cited(BaseModel, Generic[T]):
    """A tool result. When found is false, data is null and note says why."""

    found: bool
    data: T | None = None
    note: str | None = None
    sources: list[Source] = Field(default_factory=list)


# UniProtKB


class ProteinHit(BaseModel):
    accession: str
    entry_name: str
    protein_name: str | None
    gene: str | None
    organism: str | None
    length: int | None
    reviewed: bool


class ProteinSummary(BaseModel):
    accession: str
    entry_name: str
    protein_name: str | None
    gene: str | None
    organism: str | None
    taxon_id: int | None
    length: int
    reviewed: bool
    function: str | None = Field(description="UniProt FUNCTION comment, shortened")
    subcellular_locations: list[str]
    note: str | None = None


class Residue(BaseModel):
    position: int
    one_letter: str
    three_letter: str


class SequenceWindow(BaseModel):
    accession: str
    sequence_length: int
    start: int
    end: int
    residues: list[Residue] = Field(
        description="One entry per position, numbered from 1 on the canonical sequence"
    )


class Feature(BaseModel):
    type: str
    start: int | None
    end: int | None
    description: str | None


class FeatureList(BaseModel):
    accession: str
    sequence_length: int
    requested_type: str | None
    features: list[Feature]
    available_types: list[str] = Field(description="Every feature type this entry has")


class StructureRef(BaseModel):
    pdb_id: str
    method: str | None
    resolution_angstrom: float | None
    chains: str | None


class StructureRefList(BaseModel):
    accession: str
    total: int
    returned: int
    structures: list[StructureRef] = Field(description="Best resolution first; NMR last")


# RCSB PDB


class PolymerEntity(BaseModel):
    entity_id: str
    description: str | None
    polymer_type: str | None
    uniprot_accessions: list[str]


class Ligand(BaseModel):
    comp_id: str
    name: str | None


class StructureEntry(BaseModel):
    pdb_id: str
    title: str | None
    methods: list[str]
    resolution_angstrom: float | None
    deposit_date: str | None
    release_date: str | None
    polymer_entities: list[PolymerEntity]
    ligands: list[Ligand]
    truncated: bool = Field(description="True when entities were capped")


# AlphaFold DB


class Region(BaseModel):
    start: int
    end: int


class AlphaFoldSummary(BaseModel):
    model_id: str
    accession: str
    model_version: int
    created: str | None
    residue_start: int
    residue_end: int
    mean_plddt: float
    fraction_very_high: float = Field(description="Share of residues with pLDDT > 90")
    fraction_confident: float = Field(description="Share with 70 < pLDDT <= 90")
    fraction_low: float = Field(description="Share with 50 < pLDDT <= 70")
    fraction_very_low: float = Field(description="Share with pLDDT <= 50")
    low_confidence_regions: list[Region] = Field(
        description="Runs of 10+ residues with pLDDT below 50"
    )
    other_models: list[str] = Field(description="Further fragments or models for this accession")
