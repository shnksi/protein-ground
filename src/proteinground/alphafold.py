"""AlphaFold Protein Structure Database client: model confidence summaries."""

from __future__ import annotations

from typing import Any

from proteinground.fetch import (
    Fetcher,
    InvalidInputError,
    OfflineMissError,
    Response,
    UpstreamError,
    raise_if_rejected,
)
from proteinground.models import AlphaFoldSummary, Cited, ConfidenceWindow, Region, Source
from proteinground.uniprot import ACCESSION_RE, normalise_accession, not_an_accession

BASE = "https://alphafold.ebi.ac.uk/api/prediction"
LOW_PLDDT = 50.0
MIN_REGION = 10
# Summary fields read from the prediction record, by the name the result gives them.
_NUMBERS = {
    "mean_plddt": "globalMetricValue",
    "fraction_very_high": "fractionPlddtVeryHigh",
    "fraction_confident": "fractionPlddtConfident",
    "fraction_low": "fractionPlddtLow",
    "fraction_very_low": "fractionPlddtVeryLow",
}


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
            elif previous is not None and number != previous + 1:
                if previous - run_start + 1 >= min_len:
                    regions.append(Region(start=run_start, end=previous))
                run_start = number
            previous = number
            continue
        if run_start is not None and previous is not None and previous - run_start + 1 >= min_len:
            regions.append(Region(start=run_start, end=previous))
        run_start = previous = None
    if run_start is not None and previous is not None and previous - run_start + 1 >= min_len:
        regions.append(Region(start=run_start, end=previous))
    return regions


def confidence_window(
    numbers: list[int], scores: list[float], start: int, end: int
) -> ConfidenceWindow | None:
    """Confidence over residues start..end, or None when the model has none of them."""
    inside = [s for n, s in zip(numbers, scores, strict=False) if start <= n <= end]
    if not inside:
        return None
    return ConfidenceWindow(
        start=start,
        end=end,
        residues=len(inside),
        mean_plddt=round(sum(inside) / len(inside), 2),
        min_plddt=round(min(inside), 2),
        below_70=sum(s < 70.0 for s in inside),
    )


def _fragment_overlap(model: dict[str, Any], start: int, end: int) -> tuple[int, int]:
    """(covers_full_window, overlapping_residues) for a fragment against [start, end]."""
    m_start = _int(model, "uniprotStart", "sequenceStart")
    m_end = _int(model, "uniprotEnd", "sequenceEnd")
    if m_start is None or m_end is None:
        return (0, 0)
    overlap = max(0, min(m_end, end) - max(m_start, start) + 1)
    full = int(m_start <= start and m_end >= end)
    return (full, overlap)


def _matches_accession(model: dict[str, Any], accession: str) -> bool:
    model_acc = str(model.get("uniprotAccession", "")).upper()
    return model_acc == accession or model_acc.startswith(f"{accession}-")


def _pick_model(
    models: list[dict[str, Any]],
    accession: str,
    start: int | None = None,
    end: int | None = None,
    model_id: str | None = None,
) -> dict[str, Any] | None:
    if model_id is not None:
        wanted = model_id.strip().upper()
        for m in models:
            if not _matches_accession(m, accession):
                continue
            if wanted in (
                str(m.get("entryId", "")).upper(),
                str(m.get("modelEntityId", "")).upper(),
            ):
                return m
        return None
    own = [m for m in models if str(m.get("uniprotAccession", "")).upper() == accession]
    if not own:
        return None
    if start is not None and len(own) > 1:
        last = start if end is None else end
        scored = sorted(
            own,
            key=lambda m: (
                -_fragment_overlap(m, start, last)[0],
                -_fragment_overlap(m, start, last)[1],
                not str(m.get("entryId", "")).endswith("-F1"),
                str(m.get("entryId", "")),
            ),
        )
        if _fragment_overlap(scored[0], start, last)[1] > 0:
            return scored[0]
    own.sort(key=lambda m: (not str(m.get("entryId", "")).endswith("-F1"), str(m.get("entryId"))))
    return own[0]


def _number(model: dict[str, Any], key: str) -> float | None:
    """A numeric field, or None. A missing value must not turn into a confident 0.0."""
    value = model.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _int(model: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = model.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def get_alphafold_summary(
    fetcher: Fetcher,
    raw_accession: str,
    start: int | None = None,
    end: int | None = None,
    model_id: str | None = None,
) -> Cited[AlphaFoldSummary]:
    """Model confidence for an accession; start and end add the confidence of one region."""
    accession = normalise_accession(raw_accession)
    if not ACCESSION_RE.match(accession):
        return Cited[AlphaFoldSummary](found=False, note=not_an_accession(raw_accession))
    if end is not None and start is None:
        raise InvalidInputError("end needs a start")
    if start is not None and (start < 1 or (end is not None and end < start)):
        raise InvalidInputError(f"not a residue range: start={start}, end={end}")
    response = fetcher.get_json(prediction_url(accession))
    raise_if_rejected(response, f"AlphaFold DB {accession}")
    models = response.body if isinstance(response.body, list) else []
    model = (
        _pick_model(models, accession, start=start, end=end, model_id=model_id)
        if response.status == 200
        else None
    )
    if model is None:
        checked = Source(
            database="AlphaFold DB",
            record_id=accession,
            url=f"https://alphafold.ebi.ac.uk/entry/{accession}",
            retrieved_at=response.retrieved_at,
        )
        available = [
            str(m.get("entryId"))
            for m in models
            if _matches_accession(m, accession) and m.get("entryId")
        ]
        if model_id is not None and available:
            shown = ", ".join(available[:10]) + ("..." if len(available) > 10 else "")
            note = f"AlphaFold DB has no model '{model_id}' for {accession}; available: {shown}"
        elif available:
            shown = ", ".join(available[:10]) + ("..." if len(available) > 10 else "")
            note = (
                f"AlphaFold DB has no canonical model for {accession}, only "
                f"{len(available)} isoform model(s) ({shown}); pass model_id to inspect one"
            )
        else:
            note = f"AlphaFold DB has no model for {accession} (HTTP {response.status})"
        return Cited[AlphaFoldSummary](found=False, note=note, sources=[checked])
    cited = source(model, response)
    regions: list[Region] = []
    window: ConfidenceWindow | None = None
    notes: list[str] = []
    numbers: list[int] = []
    scores: list[float] = []
    others = [str(m.get("entryId")) for m in models if m is not model and m.get("entryId")]
    residue_start = _int(model, "uniprotStart", "sequenceStart")
    doc_url = model.get("plddtDocUrl")
    if not doc_url:
        notes.append("per-residue confidence file not listed; regions omitted")
    else:
        try:
            doc = fetcher.get_json(str(doc_url))
        except (UpstreamError, OfflineMissError) as exc:
            notes.append(
                f"per-residue confidence file unavailable ({type(exc).__name__}); regions omitted"
            )
        else:
            if doc.status == 200 and isinstance(doc.body, dict):
                numbers = [int(n) for n in doc.body.get("residueNumber", [])]
                if residue_start and residue_start > 1 and numbers and numbers[0] == 1:
                    offset = residue_start - 1
                    numbers = [n + offset for n in numbers]
                scores = [float(s) for s in doc.body.get("confidenceScore", [])]
                regions = low_confidence_regions(numbers, scores)
            else:
                notes.append(
                    f"per-residue confidence file unavailable (HTTP {doc.status}); regions omitted"
                )
    if start is not None:
        last = start if end is None else end
        if scores:
            window = confidence_window(numbers, scores, start, last)
            if window is None:
                extra = f"; other fragments: {', '.join(others)}" if others else ""
                notes.append(
                    f"the model has no residues in {start}-{last}; it covers "
                    f"{numbers[0]}-{numbers[-1]}{extra}"
                )
            elif window.residues < last - start + 1:
                extra = f"; check other fragments ({', '.join(others)})" if others else ""
                notes.append(
                    f"model {cited.record_id} covers {window.residues} of {last - start + 1} "
                    f"residues in {start}-{last} (fragment spans {numbers[0]}-{numbers[-1]}){extra}"
                )
        else:
            notes.append(f"no per-residue scores, so no confidence for {start}-{last}")
    values = {name: _number(model, key) for name, key in _NUMBERS.items()}
    missing = [key for name, key in _NUMBERS.items() if values[name] is None]
    if missing:
        notes.append(f"the AlphaFold DB record has no value for: {', '.join(missing)}")
    mean = values["mean_plddt"]
    summary = AlphaFoldSummary(
        model_id=cited.record_id,
        accession=accession,
        model_version=_int(model, "latestVersion"),
        created=str(model.get("modelCreatedDate", ""))[:10] or None,
        residue_start=_int(model, "uniprotStart", "sequenceStart"),
        residue_end=_int(model, "uniprotEnd", "sequenceEnd"),
        mean_plddt=None if mean is None else round(mean, 2),
        fraction_very_high=values["fraction_very_high"],
        fraction_confident=values["fraction_confident"],
        fraction_low=values["fraction_low"],
        fraction_very_low=values["fraction_very_low"],
        low_confidence_regions=regions,
        window=window,
        other_models=others,
    )
    return Cited[AlphaFoldSummary](
        found=True, data=summary, note="; ".join(notes) or None, sources=[cited]
    )
