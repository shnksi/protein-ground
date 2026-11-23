"""UniProtKB REST client: entries, sequence windows, features and PDB cross-references."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from proteinground.fetch import Fetcher, Response
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
)

BASE = "https://rest.uniprot.org/uniprotkb"
ACCESSION_RE = re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})$"
)
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
# The UniProt feature types the entry request above retrieves. Variants, mutagenesis,
# sequence conflicts and secondary structure are deliberately left out.
FEATURE_TYPES = (
    "Signal", "Transit peptide", "Chain", "Propeptide", "Peptide", "Domain", "Region",
    "Motif", "Active site", "Binding site", "Site", "Disulfide bond", "Zinc finger",
    "DNA binding", "Transmembrane", "Topological domain", "Intramembrane", "Glycosylation",
    "Modified residue", "Lipidation", "Cross-link", "Initiator methionine", "Repeat",
    "Coiled coil", "Compositional bias",
)  # fmt: skip
_FEATURE_LOOKUP = {name.lower(): name for name in FEATURE_TYPES}
SEARCH_FIELDS = "accession,id,protein_name,gene_primary,organism_name,length,reviewed"
MAX_WINDOW = 50

THREE_LETTER = {
    "A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln", "E": "Glu",
    "G": "Gly", "H": "His", "I": "Ile", "L": "Leu", "K": "Lys", "M": "Met", "F": "Phe",
    "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp", "Y": "Tyr", "V": "Val", "U": "Sec",
    "O": "Pyl", "X": "Xaa",
}  # fmt: skip


def entry_url(accession: str) -> str:
    return f"{BASE}/{accession}.json?fields={ENTRY_FIELDS}"


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


def fetch_entry(fetcher: Fetcher, raw_accession: str) -> tuple[dict[str, Any] | None, Cited[Any]]:
    """Return the raw entry, or a not-found result explaining why there is none."""
    accession = normalise_accession(raw_accession)
    if not ACCESSION_RE.match(accession):
        return None, Cited(found=False, note=f"'{raw_accession}' is not a UniProt accession")
    response = fetcher.get_json(entry_url(accession))
    if response.status in (400, 404, 410) or not isinstance(response.body, dict):
        return None, Cited(
            found=False,
            note=f"UniProtKB has no entry {accession} (HTTP {response.status})",
            sources=[source(accession, response)],
        )
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
    primary = str(body.get("primaryAccession", accession))
    note = None if primary == accession else f"{accession} is secondary; primary is {primary}"
    return body, Cited(found=True, note=note, sources=[source(primary, response)])


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
    organism = body.get("organism", {})
    summary = ProteinSummary(
        accession=str(body["primaryAccession"]),
        entry_name=str(body.get("uniProtkbId", "")),
        protein_name=protein_name(body),
        gene=gene_name(body),
        organism=organism.get("scientificName"),
        taxon_id=organism.get("taxonId"),
        length=int(body.get("sequence", {}).get("length", 0)),
        reviewed="reviewed" in str(body.get("entryType", "")).lower()
        and "unreviewed" not in str(body.get("entryType", "")).lower(),
        function=short_function(body),
        subcellular_locations=subcellular_locations(body),
    )
    return Cited[ProteinSummary](found=True, data=summary, note=result.note, sources=result.sources)


def get_sequence_window(
    fetcher: Fetcher, accession: str, start: int, end: int
) -> Cited[SequenceWindow]:
    body, result = fetch_entry(fetcher, accession)
    if body is None:
        return Cited[SequenceWindow](found=False, note=result.note, sources=result.sources)
    sequence = str(body.get("sequence", {}).get("value", ""))
    length = len(sequence)
    primary = str(body["primaryAccession"])
    if start < 1 or end < start:
        return Cited[SequenceWindow](
            found=False,
            note=f"positions run from 1 to {length}; got start={start}, end={end}",
            sources=result.sources,
        )
    if start > length:
        return Cited[SequenceWindow](
            found=False,
            note=f"position {start} is beyond the end of {primary}, which has {length} residues",
            sources=result.sources,
        )
    notes = [result.note] if result.note else []
    if end - start + 1 > MAX_WINDOW:
        end = start + MAX_WINDOW - 1
        notes.append(f"window capped at {MAX_WINDOW} residues")
    if end > length:
        end = length
        notes.append(f"window clipped at the last residue ({length})")
    residues = [
        Residue(position=pos, one_letter=aa, three_letter=THREE_LETTER.get(aa, "Xaa"))
        for pos, aa in enumerate(sequence[start - 1 : end], start=start)
    ]
    window = SequenceWindow(
        accession=primary, sequence_length=length, start=start, end=end, residues=residues
    )
    return Cited[SequenceWindow](
        found=True, data=window, note="; ".join(notes) or None, sources=result.sources
    )


def _position(location: dict[str, Any], key: str) -> int | None:
    value = location.get(key, {}).get("value")
    return int(value) if isinstance(value, int) else None


def parse_features(body: dict[str, Any]) -> list[Feature]:
    features: list[Feature] = []
    for raw in body.get("features", []):
        location = raw.get("location", {})
        description = raw.get("description") or None
        ligand = raw.get("ligand", {}).get("name")
        if ligand:
            description = f"binds {ligand}" + (f"; {description}" if description else "")
        features.append(
            Feature(
                type=str(raw.get("type", "")),
                start=_position(location, "start"),
                end=_position(location, "end"),
                description=description,
            )
        )
    return features


def get_features(
    fetcher: Fetcher, accession: str, feature_type: str | None = None
) -> Cited[FeatureList]:
    body, result = fetch_entry(fetcher, accession)
    if body is None:
        return Cited[FeatureList](found=False, note=result.note, sources=result.sources)
    if feature_type and feature_type.strip().lower() not in _FEATURE_LOOKUP:
        return Cited[FeatureList](
            found=False,
            note=(
                f"'{feature_type}' is not a feature type this tool retrieves, so this says "
                f"nothing about whether the entry has it. Supported: {', '.join(FEATURE_TYPES)}"
            ),
            sources=result.sources,
        )
    features = parse_features(body)
    available = sorted({f.type for f in features})
    if feature_type:
        wanted = feature_type.strip().lower()
        features = [f for f in features if f.type.lower() == wanted]
    listing = FeatureList(
        accession=str(body["primaryAccession"]),
        sequence_length=int(body.get("sequence", {}).get("length", 0)),
        requested_type=feature_type,
        features=features,
        available_types=available,
    )
    note = result.note
    if feature_type and not features:
        note = (
            f"no '{feature_type}' features are annotated on this entry; "
            f"types present: {', '.join(available) or 'none'}"
        )
    return Cited[FeatureList](
        found=bool(features) or not feature_type, data=listing, note=note, sources=result.sources
    )


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
    refs = parse_pdb_xrefs(body)
    if method:
        wanted = method.strip().lower().replace("-", "")
        refs = [r for r in refs if (r.method or "").lower().replace("-", "") == wanted]
    limit = max(1, min(limit, 100))
    listing = StructureRefList(
        accession=str(body["primaryAccession"]),
        total=len(refs),
        returned=min(limit, len(refs)),
        structures=refs[:limit],
    )
    note = result.note
    if not refs:
        note = "UniProtKB cross-references no PDB structures" + (
            f" with method '{method}'" if method else ""
        )
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
    limit = max(1, min(limit, 25))
    url = search_url(query, taxon_id, reviewed_only, limit)
    response = fetcher.get_json(url)
    if response.status != 200 or not isinstance(response.body, dict):
        return Cited[list[ProteinHit]](
            found=False, note=f"UniProtKB search failed (HTTP {response.status}): check the query"
        )
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
    note = None if hits else "no UniProtKB entries matched"
    return Cited[list[ProteinHit]](found=bool(hits), data=hits, note=note, sources=sources)
