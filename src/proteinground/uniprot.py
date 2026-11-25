"""UniProtKB REST client: entries, sequence windows, features, variants and PDB cross-references."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from proteinground.fetch import (
    Fetcher,
    InvalidInputError,
    MalformedRecordError,
    RejectedRequestError,
    Response,
    raise_if_rejected,
)
from proteinground.models import (
    Cited,
    Feature,
    FeatureList,
    ProteinHit,
    ProteinSummary,
    Residue,
    SequenceWindow,
    Source,
    StructureRef,
    StructureRefList,
    Variant,
    VariantList,
)

BASE = "https://rest.uniprot.org/uniprotkb"
_ACCESSION = r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})"
ACCESSION_RE = re.compile(rf"^{_ACCESSION}$")
ISOFORM_RE = re.compile(rf"^({_ACCESSION})-([0-9]{{1,3}})$")
ENTRY_NAME_RE = re.compile(r"^[A-Z0-9]{1,16}_[A-Z0-9]{1,5}$")
ENTRY_FIELDS = ",".join(
    [
        "accession", "id", "protein_name", "gene_primary", "organism_name", "organism_id",
        "length", "reviewed", "sequence", "cc_function", "cc_subcellular_location",
        "ft_signal", "ft_transit", "ft_chain", "ft_propep", "ft_peptide", "ft_domain",
        "ft_region", "ft_motif", "ft_act_site", "ft_binding", "ft_site", "ft_disulfid",
        "ft_zn_fing", "ft_dna_bind", "ft_transmem", "ft_topo_dom", "ft_intramem",
        "ft_carbohyd", "ft_mod_res", "ft_lipid", "ft_crosslnk", "ft_init_met", "ft_repeat",
        "ft_coiled", "ft_compbias", "xref_pdb",
    ]
)  # fmt: skip
# The UniProt feature types the entry request above retrieves. Variants and mutagenesis
# have their own tool (get_variants); sequence conflicts and secondary structure are
# deliberately left out.
FEATURE_TYPES = (
    "Signal", "Transit peptide", "Chain", "Propeptide", "Peptide", "Domain", "Region",
    "Motif", "Active site", "Binding site", "Site", "Disulfide bond", "Zinc finger",
    "DNA binding", "Transmembrane", "Topological domain", "Intramembrane", "Glycosylation",
    "Modified residue", "Lipidation", "Cross-link", "Initiator methionine", "Repeat",
    "Coiled coil", "Compositional bias",
)  # fmt: skip
# What people and models call those types. Keys are normalised (lower case, spaces).
_FEATURE_ALIASES = {
    "signal peptide": "Signal", "signal sequence": "Signal",
    "transit": "Transit peptide",
    "propep": "Propeptide", "pro peptide": "Propeptide",
    "act site": "Active site", "catalytic site": "Active site",
    "catalytic residue": "Active site",
    "binding": "Binding site", "ligand binding site": "Binding site",
    "disulfide": "Disulfide bond", "disulfid": "Disulfide bond",
    "disulfide bridge": "Disulfide bond", "disulphide": "Disulfide bond",
    "disulphide bond": "Disulfide bond", "disulphide bridge": "Disulfide bond",
    "zn fing": "Zinc finger", "zinc finger region": "Zinc finger",
    "dna bind": "DNA binding", "dna binding region": "DNA binding",
    "dna binding domain": "DNA binding",
    "transmem": "Transmembrane", "transmembrane region": "Transmembrane",
    "transmembrane helix": "Transmembrane", "transmembrane helice": "Transmembrane",
    "transmembrane domain": "Transmembrane", "transmembrane segment": "Transmembrane",
    "tm helix": "Transmembrane",
    "topo dom": "Topological domain", "intramem": "Intramembrane",
    "intramembrane region": "Intramembrane",
    "carbohyd": "Glycosylation", "glycosylation site": "Glycosylation",
    "glycan": "Glycosylation",
    "mod res": "Modified residue",
    "lipid": "Lipidation", "lipidation site": "Lipidation",
    "crosslnk": "Cross-link", "crosslink": "Cross-link",
    "init met": "Initiator methionine",
    "coiled": "Coiled coil", "compbias": "Compositional bias",
}  # fmt: skip
_VARIANT_NAMES = frozenset(
    {"natural variant", "variant", "sequence variant", "mutagenesis", "mutagen", "mutation",
     "polymorphism", "snp"}
)  # fmt: skip
SEARCH_FIELDS = "accession,id,protein_name,gene_primary,organism_name,length,reviewed"
VARIANT_FIELDS = "accession,sequence,ft_variant,ft_mutagen"
MAX_WINDOW = 50
# Features whose start and end are two linked residues, not the ends of a span.
_PAIRED = frozenset({"Disulfide bond", "Cross-link"})
CURATED_SUBSET = (
    "UniProtKB curates variants from the literature and is not a complete catalogue, so "
    "absence here is not evidence that a variant does not occur; check ClinVar or gnomAD"
)

THREE_LETTER = {
    "A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln", "E": "Glu",
    "G": "Gly", "H": "His", "I": "Ile", "L": "Leu", "K": "Lys", "M": "Met", "F": "Phe",
    "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp", "Y": "Tyr", "V": "Val", "U": "Sec",
    "O": "Pyl", "X": "Xaa",
}  # fmt: skip


def entry_url(accession: str) -> str:
    return f"{BASE}/{accession}.json?fields={ENTRY_FIELDS}"


def variants_url(accession: str) -> str:
    return f"{BASE}/{accession}.json?fields={VARIANT_FIELDS}"


def isoform_url(isoform_id: str) -> str:
    return f"{BASE}/{isoform_id}.json?fields=accession,sequence"


def search_url(query: str, taxon_id: int | None, reviewed_only: bool, limit: int) -> str:
    clauses = [f"({query})"]
    if taxon_id is not None:
        clauses.append(f"(organism_id:{taxon_id})")
    if reviewed_only:
        clauses.append("(reviewed:true)")
    params = {
        "fields": SEARCH_FIELDS,
        "format": "json",
        "query": " AND ".join(clauses),
        "size": str(limit),
    }
    return f"{BASE}/search?{urlencode(params)}"


def source(accession: str, response: Response) -> Source:
    return Source(
        database="UniProtKB",
        record_id=accession,
        url=f"https://www.uniprot.org/uniprotkb/{accession}/entry",
        retrieved_at=response.retrieved_at,
        release=response.headers.get("x-uniprot-release"),
    )


def normalise_accession(raw: str) -> str:
    return raw.strip().upper()


def not_an_accession(raw: str) -> str:
    """Why this string cannot be looked up, with the next step when there is one."""
    cleaned = normalise_accession(raw)
    isoform = ISOFORM_RE.match(cleaned)
    if isoform:
        return (
            f"{cleaned} is an isoform ID. Annotations are kept on the canonical entry, so "
            f"call this tool with {isoform.group(1)}; get_sequence_window accepts isoform "
            "IDs and numbers residues on that isoform"
        )
    if ENTRY_NAME_RE.match(cleaned):
        return (
            f"'{raw}' looks like a UniProtKB entry name, not an accession; find the "
            "accession with search_proteins"
        )
    return f"'{raw}' is not a UniProt accession"


def fetch_entry(
    fetcher: Fetcher, raw_accession: str, url_for: Callable[[str], str] = entry_url
) -> tuple[dict[str, Any] | None, Cited[Any]]:
    """Return the raw entry, or a not-found result explaining why there is none.

    Only a 404 or 410 means the entry is missing. A 400 means UniProt rejected the request
    (a renamed field, say) and raises, so it can never be read as "no such entry".
    """
    accession = normalise_accession(raw_accession)
    if not ACCESSION_RE.match(accession):
        return None, Cited(found=False, note=not_an_accession(raw_accession))
    response = fetcher.get_json(url_for(accession))
    raise_if_rejected(response, f"UniProtKB {accession}")
    if response.status in (404, 410):
        return None, Cited(
            found=False,
            note=f"UniProtKB has no entry {accession} (HTTP {response.status})",
            sources=[source(accession, response)],
        )
    if not isinstance(response.body, dict):
        raise MalformedRecordError(f"UniProtKB {accession}: the response was not a record")
    body: dict[str, Any] = response.body
    if body.get("entryType") == "Inactive":
        reason = body.get("inactiveReason", {})
        targets = ", ".join(reason.get("mergeDemergeTo", [])) or "none"
        return None, Cited(
            found=False,
            note=(
                f"{accession} is an inactive UniProtKB entry "
                f"({reason.get('inactiveReasonType', 'unknown reason')}; now: {targets})"
            ),
            sources=[source(accession, response)],
        )
    primary = str(body.get("primaryAccession") or accession)
    note = None if primary == accession else f"{accession} is secondary; primary is {primary}"
    return body, Cited(found=True, note=note, sources=[source(primary, response)])


def _primary(body: dict[str, Any]) -> str:
    value = body.get("primaryAccession")
    if not value:
        raise MalformedRecordError("UniProtKB: the record has no primary accession")
    return str(value)


def _sequence(body: dict[str, Any], accession: str) -> str:
    """The sequence, or an error. A missing one must not become a length of zero."""
    value = body.get("sequence", {}).get("value")
    if not isinstance(value, str) or not value:
        raise MalformedRecordError(f"UniProtKB {accession}: the record has no sequence")
    return value


@dataclass(frozen=True)
class LoadedSequence:
    label: str  # the canonical accession, or the isoform ID
    sequence: str
    sources: list[Source]
    note: str | None


def load_sequence(fetcher: Fetcher, raw_accession: str) -> tuple[LoadedSequence | None, Cited[Any]]:
    """The canonical sequence of an accession, or the sequence of one isoform."""
    cleaned = normalise_accession(raw_accession)
    isoform = ISOFORM_RE.match(cleaned)
    if not isoform:
        body, result = fetch_entry(fetcher, raw_accession)
        if body is None:
            return None, result
        primary = _primary(body)
        return LoadedSequence(
            primary, _sequence(body, primary), result.sources, result.note
        ), result
    base = isoform.group(1)
    response = fetcher.get_json(isoform_url(cleaned))
    raise_if_rejected(response, f"UniProtKB {cleaned}")
    cited = Source(
        database="UniProtKB",
        record_id=cleaned,
        url=f"https://rest.uniprot.org/uniprotkb/{cleaned}.fasta",
        retrieved_at=response.retrieved_at,
        release=response.headers.get("x-uniprot-release"),
    )
    if response.status in (404, 410):
        return None, Cited(
            found=False,
            note=f"UniProtKB has no isoform {cleaned} (HTTP {response.status}); {base} may "
            "have fewer isoforms",
            sources=[cited],
        )
    if not isinstance(response.body, dict):
        raise MalformedRecordError(f"UniProtKB {cleaned}: the response was not a record")
    sequence = _sequence(response.body, cleaned)
    if str(response.body.get("primaryAccession", "")) == base:
        note = f"{cleaned} is the canonical sequence of {base}"
    else:
        note = (
            f"positions are numbered on isoform {cleaned} and can differ from the canonical "
            f"sequence of {base}"
        )
    loaded = LoadedSequence(cleaned, sequence, [cited], note)
    return loaded, Cited(found=True, note=note, sources=[cited])


def protein_name(body: dict[str, Any]) -> str | None:
    desc = body.get("proteinDescription", {})
    for key in ("recommendedName", "submissionNames"):
        node = desc.get(key)
        if isinstance(node, list):
            node = node[0] if node else None
        if isinstance(node, dict):
            value = node.get("fullName", {}).get("value")
            if value:
                return str(value)
    return None


def gene_name(body: dict[str, Any]) -> str | None:
    for gene in body.get("genes", []):
        value = gene.get("geneName", {}).get("value")
        if value:
            return str(value)
    return None


_CITATION = re.compile(r"\s*\((?:PubMed|By similarity|Ref\.)[^)]*\)")


def short_function(body: dict[str, Any], limit: int = 600) -> str | None:
    for comment in body.get("comments", []):
        if comment.get("commentType") == "FUNCTION" and comment.get("texts"):
            text = _CITATION.sub("", str(comment["texts"][0].get("value", ""))).strip()
            if len(text) <= limit:
                return text
            cut = text[:limit].rsplit(". ", 1)[0]
            return cut.rstrip(".") + ". [shortened]"
    return None


def subcellular_locations(body: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for comment in body.get("comments", []):
        if comment.get("commentType") != "SUBCELLULAR LOCATION":
            continue
        for item in comment.get("subcellularLocations", []):
            value = item.get("location", {}).get("value")
            if value and value not in found:
                found.append(str(value))
    return found


def get_protein(fetcher: Fetcher, accession: str) -> Cited[ProteinSummary]:
    body, result = fetch_entry(fetcher, accession)
    if body is None:
        return Cited[ProteinSummary](found=False, note=result.note, sources=result.sources)
    primary = _primary(body)
    organism = body.get("organism", {})
    summary = ProteinSummary(
        accession=primary,
        entry_name=str(body.get("uniProtkbId", "")),
        protein_name=protein_name(body),
        gene=gene_name(body),
        organism=organism.get("scientificName"),
        taxon_id=organism.get("taxonId"),
        length=len(_sequence(body, primary)),
        reviewed="reviewed" in str(body.get("entryType", "")).lower()
        and "unreviewed" not in str(body.get("entryType", "")).lower(),
        function=short_function(body),
        subcellular_locations=subcellular_locations(body),
    )
    return Cited[ProteinSummary](found=True, data=summary, note=result.note, sources=result.sources)


def _clip_window(label: str, length: int, start: int, end: int) -> tuple[int, int, list[str]] | str:
    """Clamp a 1-based window to the sequence. Returns a reason when nothing is left."""
    if start < 1 or end < start:
        return f"positions run from 1 to {length}; got start={start}, end={end}"
    if start > length:
        return f"position {start} is beyond the end of {label}, which has {length} residues"
    notes: list[str] = []
    if end - start + 1 > MAX_WINDOW:
        end = start + MAX_WINDOW - 1
        notes.append(f"window capped at {MAX_WINDOW} residues")
    if end > length:
        end = length
        notes.append(f"window clipped at the last residue ({length})")
    return start, end, notes


def _residues(sequence: str, start: int, end: int) -> list[Residue]:
    return [
        Residue(position=pos, one_letter=aa, three_letter=THREE_LETTER.get(aa, "Xaa"))
        for pos, aa in enumerate(sequence[start - 1 : end], start=start)
    ]


def get_sequence_window(
    fetcher: Fetcher, accession: str, start: int, end: int
) -> Cited[SequenceWindow]:
    loaded, result = load_sequence(fetcher, accession)
    if loaded is None:
        return Cited[SequenceWindow](found=False, note=result.note, sources=result.sources)
    length = len(loaded.sequence)
    clipped = _clip_window(loaded.label, length, start, end)
    if isinstance(clipped, str):
        return Cited[SequenceWindow](found=False, note=clipped, sources=loaded.sources)
    start, end, notes = clipped
    if loaded.note:
        notes.insert(0, loaded.note)
    window = SequenceWindow(
        accession=loaded.label,
        sequence_length=length,
        start=start,
        end=end,
        residues=_residues(loaded.sequence, start, end),
    )
    return Cited[SequenceWindow](
        found=True, data=window, note="; ".join(notes) or None, sources=loaded.sources
    )


def _position(location: dict[str, Any], key: str) -> int | None:
    value = location.get(key, {}).get("value")
    return int(value) if isinstance(value, int) else None


def _position_note(location: dict[str, Any]) -> str | None:
    """UniProt marks some boundaries as outside the sequence, unsure or unknown."""
    notes = []
    for key in ("start", "end"):
        modifier = str(location.get(key, {}).get("modifier") or "EXACT")
        if modifier != "EXACT":
            notes.append(f"{key} {modifier.lower()}")
    return ", ".join(notes) or None


def parse_features(body: dict[str, Any], primary: str | None = None) -> list[Feature]:
    canonical_id = primary or str(body.get("primaryAccession") or "")
    features: list[Feature] = []
    for raw in body.get("features", []):
        location = raw.get("location", {})
        description = raw.get("description") or None
        ligand = raw.get("ligand", {}).get("name")
        if ligand:
            description = f"binds {ligand}" + (f"; {description}" if description else "")
        on = str(location.get("sequence") or canonical_id)
        isoform = on if canonical_id and on != canonical_id else None
        features.append(
            Feature(
                type=str(raw.get("type", "")),
                start=_position(location, "start"),
                end=_position(location, "end"),
                description=description,
                position_note=_position_note(location),
                isoform=isoform,
            )
        )
    return features


def _normalise_type(raw: str) -> str:
    return re.sub(r"[\s_-]+", " ", raw.strip().lower()).removeprefix("ft ")


_FEATURE_LOOKUP = {_normalise_type(name): name for name in FEATURE_TYPES}


def resolve_feature_type(raw: str) -> str | None:
    """Map what the caller typed ("signal peptide", "ACT_SITE", "domains") to UniProt's name."""
    wanted = _normalise_type(raw)
    for candidate in (wanted, wanted.removesuffix("s")):
        name = _FEATURE_LOOKUP.get(candidate) or _FEATURE_ALIASES.get(candidate)
        if name:
            return name
    return None


def _covers(feature: Feature, position: int) -> bool:
    if feature.start is None or feature.end is None or feature.type in _PAIRED:
        return position in (feature.start, feature.end)
    return feature.start <= position <= feature.end


def get_features(
    fetcher: Fetcher,
    accession: str,
    feature_type: str | None = None,
    position: int | None = None,
) -> Cited[FeatureList]:
    body, result = fetch_entry(fetcher, accession)
    if body is None:
        return Cited[FeatureList](found=False, note=result.note, sources=result.sources)
    primary = _primary(body)
    length = len(_sequence(body, primary))
    wanted: str | None = None
    if feature_type and feature_type.strip():
        wanted = resolve_feature_type(feature_type)
        if wanted is None:
            asked = _normalise_type(feature_type)
            if asked in _VARIANT_NAMES or asked.removesuffix("s") in _VARIANT_NAMES:
                reason = f"'{feature_type}' records are served by get_variants, not this tool"
            else:
                reason = f"'{feature_type}' is not a feature type this tool retrieves"
            return Cited[FeatureList](
                found=False,
                note=(
                    f"{reason}, so this says nothing about whether the entry has it. "
                    f"Supported: {', '.join(FEATURE_TYPES)}"
                ),
                sources=result.sources,
            )
    if position is not None and not 1 <= position <= length:
        return Cited[FeatureList](
            found=False,
            note=f"position {position} is outside {primary}, which has {length} residues",
            sources=result.sources,
        )
    features = parse_features(body, primary)
    available = sorted({f.type for f in features})
    if wanted:
        features = [f for f in features if f.type == wanted]
    isoform_skipped = 0
    if position is not None:
        isoform_skipped = sum(f.isoform is not None for f in features)
        features = [f for f in features if f.isoform is None and _covers(f, position)]
    listing = FeatureList(
        accession=primary,
        sequence_length=length,
        requested_type=wanted,
        requested_position=position,
        features=features,
        available_types=available,
    )
    filtered = wanted is not None or position is not None
    notes: list[str] = [result.note] if result.note else []
    if filtered and not features:
        what = f"'{wanted}' features" if wanted else "features of the types this tool retrieves"
        where = f" at position {position}" if position is not None else ""
        notes.append(
            f"no {what} are annotated{where} on this entry; "
            f"types present: {', '.join(available) or 'none'}"
        )
    if isoform_skipped:
        notes.append(
            f"{isoform_skipped} isoform-numbered feature(s) were not matched against canonical "
            f"position {position}"
        )
    return Cited[FeatureList](
        found=bool(features) or not filtered,
        data=listing,
        note="; ".join(notes) or None,
        sources=result.sources,
    )


def parse_variants(body: dict[str, Any], primary: str) -> list[Variant]:
    variants: list[Variant] = []
    for raw in body.get("features", []):
        kind = str(raw.get("type", ""))
        if kind not in ("Natural variant", "Mutagenesis"):
            continue
        location = raw.get("location", {})
        start, end = _position(location, "start"), _position(location, "end")
        change = raw.get("alternativeSequence") or {}
        original = str(change["originalSequence"]) if change.get("originalSequence") else None
        alternatives = [str(a) for a in change.get("alternativeSequences") or []]
        description = str(raw["description"])[:500] if raw.get("description") else None
        on = str(location.get("sequence") or primary)
        canonical = on == primary
        if not canonical:  # numbered on an isoform, so it is not a canonical position
            description = f"on isoform {on}" + (f": {description}" if description else "")
        single = canonical and original is not None and len(original) == 1 and start == end
        variants.append(
            Variant(
                kind=kind,
                start=start,
                end=end,
                original=original,
                alternatives=alternatives,
                changes=[f"{original}{start}{a}" for a in alternatives if len(a) == 1]
                if single
                else [],
                description=description,
                feature_id=raw.get("featureId"),
                dbsnp=[
                    str(x["id"])
                    for x in raw.get("featureCrossReferences", [])
                    if x.get("database") == "dbSNP" and x.get("id")
                ],
                isoform=None if canonical else on,
            )
        )
    variants.sort(key=lambda v: (v.start or 0, v.kind, v.feature_id or ""))
    return variants


def get_variants(
    fetcher: Fetcher, accession: str, start: int, end: int | None = None
) -> Cited[VariantList]:
    """Curated natural variants and mutagenesis records over a residue range."""
    body, result = fetch_entry(fetcher, accession, variants_url)
    if body is None:
        return Cited[VariantList](found=False, note=result.note, sources=result.sources)
    primary = _primary(body)
    sequence = _sequence(body, primary)
    clipped = _clip_window(primary, len(sequence), start, start if end is None else end)
    if isinstance(clipped, str):
        return Cited[VariantList](found=False, note=clipped, sources=result.sources)
    start, last, notes = clipped
    every = parse_variants(body, primary)
    hits = [
        v for v in every
        if v.isoform is None
        and v.start is not None
        and v.end is not None
        and v.start <= last
        and v.end >= start
    ]  # fmt: skip
    isoform_count = sum(v.isoform is not None for v in every)
    if result.note:
        notes.insert(0, result.note)
    span = f"position {start}" if start == last else f"positions {start}-{last}"
    if hits:
        notes.append(CURATED_SUBSET)
    else:
        notes.append(
            f"UniProtKB annotates no natural variant or mutagenesis record at {span} of "
            f"{primary}. {CURATED_SUBSET}"
        )
    if isoform_count:
        notes.append(
            f"{isoform_count} isoform-numbered variant record(s) on this entry are excluded "
            "from canonical position matching"
        )
    listing = VariantList(
        accession=primary,
        sequence_length=len(sequence),
        start=start,
        end=last,
        reference=_residues(sequence, start, last),
        variants=hits,
        natural_variants_in_entry=sum(v.kind == "Natural variant" for v in every),
        mutagenesis_records_in_entry=sum(v.kind == "Mutagenesis" for v in every),
    )
    return Cited[VariantList](
        found=True, data=listing, note="; ".join(notes), sources=result.sources
    )


STRUCTURE_METHODS = ("X-ray", "EM", "NMR", "Neutron", "Fiber", "Model", "Other")
_METHOD_ALIASES = {
    "x ray": "X-ray",
    "xray": "X-ray",
    "x ray diffraction": "X-ray",
    "xray diffraction": "X-ray",
    "x ray crystallography": "X-ray",
    "xray crystallography": "X-ray",
    "crystal": "X-ray",
    "crystallography": "X-ray",
    "em": "EM",
    "cryo em": "EM",
    "cryoem": "EM",
    "electron microscopy": "EM",
    "cryo electron microscopy": "EM",
    "3dem": "EM",
    "nmr": "NMR",
    "solution nmr": "NMR",
    "solid state nmr": "NMR",
    "nuclear magnetic resonance": "NMR",
    "neutron": "Neutron",
    "neutron diffraction": "Neutron",
    "fiber": "Fiber",
    "fiber diffraction": "Fiber",
    "model": "Model",
    "other": "Other",
}


def resolve_structure_method(raw: str) -> str | None:
    """Map natural method names ('cryo-EM', 'X-RAY DIFFRACTION') to UniProt's PDB xref label."""
    key = re.sub(r"[\s_-]+", " ", raw.strip().lower())
    return _METHOD_ALIASES.get(key)


def _resolution(raw: str | None) -> float | None:
    if not raw:
        return None
    match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)", raw)
    return float(match.group(1)) if match else None


def parse_pdb_xrefs(body: dict[str, Any]) -> list[StructureRef]:
    refs: list[StructureRef] = []
    for xref in body.get("uniProtKBCrossReferences", []):
        if xref.get("database") != "PDB":
            continue
        props = {p.get("key"): p.get("value") for p in xref.get("properties", [])}
        refs.append(
            StructureRef(
                pdb_id=str(xref.get("id", "")).upper(),
                method=props.get("Method"),
                resolution_angstrom=_resolution(props.get("Resolution")),
                chains=props.get("Chains"),
            )
        )
    refs.sort(key=lambda r: (r.resolution_angstrom is None, r.resolution_angstrom or 0.0, r.pdb_id))
    return refs


def list_structures(
    fetcher: Fetcher, accession: str, method: str | None = None, limit: int = 20
) -> Cited[StructureRefList]:
    body, result = fetch_entry(fetcher, accession)
    if body is None:
        return Cited[StructureRefList](found=False, note=result.note, sources=result.sources)
    all_refs = parse_pdb_xrefs(body)
    present_methods = sorted({r.method for r in all_refs if r.method})
    refs = all_refs
    wanted: str | None = None
    if method and method.strip():
        wanted = resolve_structure_method(method)
        if wanted is None:
            return Cited[StructureRefList](
                found=False,
                note=(
                    f"'{method}' is not a recognised PDB method filter (supported: "
                    f"{', '.join(STRUCTURE_METHODS)}), so this says nothing about whether "
                    f"structures exist; methods present on this entry: "
                    f"{', '.join(present_methods) or 'none'}"
                ),
                sources=result.sources,
            )
        refs = [r for r in all_refs if (r.method or "").lower() == wanted.lower()]
    limit = max(1, min(limit, 100))
    listing = StructureRefList(
        accession=_primary(body),
        total=len(refs),
        returned=min(limit, len(refs)),
        structures=refs[:limit],
    )
    note = result.note
    if not refs:
        if wanted:
            note = (
                f"UniProtKB cross-references no PDB structures with method '{wanted}'; "
                f"methods present: {', '.join(present_methods) or 'none'}"
            )
        else:
            note = "UniProtKB cross-references no PDB structures"
    return Cited[StructureRefList](
        found=bool(refs), data=listing, note=note, sources=result.sources
    )


def search(
    fetcher: Fetcher,
    query: str,
    taxon_id: int | None = None,
    reviewed_only: bool = True,
    limit: int = 5,
) -> Cited[list[ProteinHit]]:
    if not query.strip():
        raise InvalidInputError("query cannot be empty")
    limit = max(1, min(limit, 25))
    url = search_url(query, taxon_id, reviewed_only, limit)
    response = fetcher.get_json(url)
    if response.status == 400:  # a query UniProt could not parse is not "no matches"
        said = response.upstream_message()
        raise RejectedRequestError(
            f"UniProtKB could not parse the query {query!r}"
            + (f" ({said})" if said else "")
            + "; rephrase it, e.g. 'gene:KRAS' or plain words"
        )
    if response.status != 200 or not isinstance(response.body, dict):
        raise MalformedRecordError(f"UniProtKB search returned HTTP {response.status}")
    hits: list[ProteinHit] = []
    sources: list[Source] = []
    for row in response.body.get("results", []):
        accession = str(row.get("primaryAccession", ""))
        hits.append(
            ProteinHit(
                accession=accession,
                entry_name=str(row.get("uniProtkbId", "")),
                protein_name=protein_name(row),
                gene=gene_name(row),
                organism=row.get("organism", {}).get("scientificName"),
                length=row.get("sequence", {}).get("length"),
                reviewed="unreviewed" not in str(row.get("entryType", "")).lower(),
            )
        )
        sources.append(source(accession, response))
    if hits:
        note = None
    elif reviewed_only:
        note = (
            "no reviewed (Swiss-Prot) UniProtKB entries matched; retry with "
            "reviewed_only=False to include unreviewed (TrEMBL) entries"
        )
    else:
        note = "no UniProtKB entries matched"
    return Cited[list[ProteinHit]](found=bool(hits), data=hits, note=note, sources=sources)
