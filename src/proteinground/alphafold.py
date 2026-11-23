"""AlphaFold Protein Structure Database client: model confidence summaries."""

from __future__ import annotations

from typing import Any

from proteinground.fetch import Fetcher, OfflineMissError, Response, UpstreamError
from proteinground.models import AlphaFoldSummary, Cited, Region, Source
from proteinground.uniprot import ACCESSION_RE, normalise_accession

BASE = "https://alphafold.ebi.ac.uk/api/prediction"
LOW_PLDDT = 50.0
MIN_REGION = 10


def prediction_url(accession: str) -> str:
    return f"{BASE}/{accession}"


def source(model: dict[str, Any], response: Response) -> Source:
    accession = str(model.get("uniprotAccession", ""))
    version = model.get("latestVersion")
    return Source(
        database="AlphaFold DB",
        record_id=str(model.get("entryId") or model.get("modelEntityId") or accession),
        url=f"https://alphafold.ebi.ac.uk/entry/{accession}",
        retrieved_at=response.retrieved_at,
        release=f"model v{version}" if version is not None else None,
    )


def low_confidence_regions(
    numbers: list[int], scores: list[float], threshold: float = LOW_PLDDT, min_len: int = MIN_REGION
) -> list[Region]:
    regions: list[Region] = []
    run_start: int | None = None
    previous: int | None = None
    for number, score in zip(numbers, scores, strict=False):  # trust the shorter list
        if score < threshold:
            if run_start is None:
                run_start = number
            previous = number
            continue
        if run_start is not None and previous is not None and previous - run_start + 1 >= min_len:
            regions.append(Region(start=run_start, end=previous))
        run_start = previous = None
    if run_start is not None and previous is not None and previous - run_start + 1 >= min_len:
        regions.append(Region(start=run_start, end=previous))
    return regions


def _pick_model(models: list[dict[str, Any]], accession: str) -> dict[str, Any] | None:
    own = [m for m in models if str(m.get("uniprotAccession", "")).upper() == accession]
    if not own:
        return None
    own.sort(key=lambda m: (not str(m.get("entryId", "")).endswith("-F1"), str(m.get("entryId"))))
    return own[0]


def get_alphafold_summary(fetcher: Fetcher, raw_accession: str) -> Cited[AlphaFoldSummary]:
    accession = normalise_accession(raw_accession)
    if not ACCESSION_RE.match(accession):
        return Cited[AlphaFoldSummary](
            found=False, note=f"'{raw_accession}' is not a UniProt accession"
        )
    response = fetcher.get_json(prediction_url(accession))
    models = response.body if isinstance(response.body, list) else []
    model = _pick_model(models, accession) if response.status == 200 else None
    if model is None:
        checked = Source(
            database="AlphaFold DB",
            record_id=accession,
            url=f"https://alphafold.ebi.ac.uk/entry/{accession}",
            retrieved_at=response.retrieved_at,
        )
        return Cited[AlphaFoldSummary](
            found=False,
            note=f"AlphaFold DB has no model for {accession} (HTTP {response.status})",
            sources=[checked],
        )
    cited = source(model, response)
    regions: list[Region] = []
    note: str | None = None
    doc_url = model.get("plddtDocUrl")
    if not doc_url:
        note = "per-residue confidence file not listed; regions omitted"
    else:
        try:
            doc = fetcher.get_json(str(doc_url))
        except (UpstreamError, OfflineMissError) as exc:
            note = (
                f"per-residue confidence file unavailable ({type(exc).__name__}); regions omitted"
            )
        else:
            if doc.status == 200 and isinstance(doc.body, dict):
                regions = low_confidence_regions(
                    [int(n) for n in doc.body.get("residueNumber", [])],
                    [float(s) for s in doc.body.get("confidenceScore", [])],
                )
    others = [str(m.get("entryId")) for m in models if m is not model and m.get("entryId")]
    summary = AlphaFoldSummary(
        model_id=cited.record_id,
        accession=accession,
        model_version=int(model.get("latestVersion", 0)),
        created=str(model.get("modelCreatedDate", ""))[:10] or None,
        residue_start=int(model.get("uniprotStart") or model.get("sequenceStart") or 1),
        residue_end=int(model.get("uniprotEnd") or model.get("sequenceEnd") or 0),
        mean_plddt=round(float(model.get("globalMetricValue", 0.0)), 2),
        fraction_very_high=float(model.get("fractionPlddtVeryHigh", 0.0)),
        fraction_confident=float(model.get("fractionPlddtConfident", 0.0)),
        fraction_low=float(model.get("fractionPlddtLow", 0.0)),
        fraction_very_low=float(model.get("fractionPlddtVeryLow", 0.0)),
        low_confidence_regions=regions,
        other_models=others,
    )
    return Cited[AlphaFoldSummary](found=True, data=summary, note=note, sources=[cited])
