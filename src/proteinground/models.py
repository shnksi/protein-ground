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
    accession: str = Field(description="Canonical accession, or the isoform ID asked for")
    sequence_length: int
    start: int
    end: int
    residues: list[Residue] = Field(
        description="One entry per position, numbered from 1 on this sequence"
    )


class Feature(BaseModel):
    type: str
    start: int | None
    end: int | None
    description: str | None
    position_note: str | None = Field(
        default=None, description="Set when UniProt marks a boundary as uncertain or unknown"
    )
    isoform: str | None = Field(
        default=None,
        description="Set when UniProt annotates this feature on a non-canonical isoform",
    )


class FeatureList(BaseModel):
    accession: str
    sequence_length: int
    requested_type: str | None
    requested_position: int | None = None
    features: list[Feature]
    available_types: list[str] = Field(description="Every feature type this entry has")


class Variant(BaseModel):
    kind: str = Field(description="'Natural variant' or 'Mutagenesis' (a lab-made change)")
    start: int | None
    end: int | None
    original: str | None = Field(description="Wild-type residue(s) UniProt records here")
    alternatives: list[str] = Field(description="Replacement residue(s); empty for a deletion")
    changes: list[str] = Field(description="Short form for single-residue swaps, e.g. G12C")
    description: str | None
    feature_id: str | None
    dbsnp: list[str]
    isoform: str | None = Field(
        default=None, description="Set when numbered on a non-canonical isoform"
    )


class VariantList(BaseModel):
    accession: str
    sequence_length: int
    start: int
    end: int
    reference: list[Residue] = Field(description="Canonical residue at each position asked for")
    variants: list[Variant]
    natural_variants_in_entry: int
    mutagenesis_records_in_entry: int


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
    chains: list[str] = Field(
        default_factory=list, description="Author chain IDs, as papers and viewers show them"
    )
    organism: str | None = None
    taxon_id: int | None = None
    length: int | None = None
    mutation: str | None = Field(default=None, description="Depositor's note on mutations")
    uniprot_accessions: list[str]


class Ligand(BaseModel):
    comp_id: str
    name: str | None
    chains: list[str] = Field(default_factory=list, description="Author chain IDs it sits with")


class StructureEntry(BaseModel):
    pdb_id: str
    title: str | None
    methods: list[str]
    resolution_angstrom: float | None
    r_free: float | None = Field(default=None, description="X-ray free R-factor, when refined")
    r_work: float | None = Field(default=None, description="X-ray working R-factor, when refined")
    deposit_date: str | None
    release_date: str | None
    polymer_entities: list[PolymerEntity]
    ligands: list[Ligand]
    truncated: bool = Field(description="True when entities were capped")


class ChainCoverage(BaseModel):
    uniprot_accession: str
    uniprot_start: int
    uniprot_end: int
    author_start: str = Field(description="Author residue number at the start of the segment")
    author_end: str


class ResidueMapping(BaseModel):
    pdb_id: str
    chain: str = Field(description="Author chain ID")
    label_asym_id: str = Field(description="The mmCIF chain ID, which can differ")
    entity_id: str
    entity_description: str | None
    organism: str | None
    author_residue: str = Field(
        description="Residue number as the authors numbered it, with any insertion code"
    )
    label_seq_id: int = Field(description="1-based index into the deposited construct")
    structure_residue: str = Field(description="One-letter code in the deposited sequence")
    structure_residue_three_letter: str
    observed: bool | None = Field(
        description="False when the residue is in the construct but has no coordinates"
    )
    uniprot_accession: str | None
    uniprot_position: int | None
    uniprot_residue: str | None = Field(description="Canonical residue at that position")
    matches_uniprot: bool | None = Field(
        description="False when the structure and the canonical sequence differ here"
    )
    coverage: list[ChainCoverage] = Field(description="The UniProt ranges this chain spans")


# AlphaFold DB


class Region(BaseModel):
    start: int
    end: int


class ConfidenceWindow(BaseModel):
    start: int
    end: int
    residues: int
    mean_plddt: float
    min_plddt: float
    below_70: int = Field(description="Residues in the window with pLDDT under 70")


class AlphaFoldSummary(BaseModel):
    model_id: str
    accession: str
    model_version: int | None
    created: str | None
    residue_start: int | None
    residue_end: int | None
    mean_plddt: float | None
    fraction_very_high: float | None = Field(description="Share of residues with pLDDT > 90")
    fraction_confident: float | None = Field(description="Share with 70 < pLDDT <= 90")
    fraction_low: float | None = Field(description="Share with 50 < pLDDT <= 70")
    fraction_very_low: float | None = Field(description="Share with pLDDT <= 50")
    low_confidence_regions: list[Region] = Field(
        description="Runs of 10+ residues with pLDDT below 50"
    )
    window: ConfidenceWindow | None = Field(
        default=None, description="Confidence over the residue range asked for"
    )
    other_models: list[str] = Field(description="Further fragments or models for this accession")
