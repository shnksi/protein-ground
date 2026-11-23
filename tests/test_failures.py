"""A failed lookup must never read as "this does not exist", and a missing value must
never read as zero. Each case fakes the upstream fault and checks what the agent is told."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from proteinground import alphafold, pdb, uniprot
from proteinground.fetch import (
    Fetcher,
    MalformedRecordError,
    Mode,
    RejectedRequestError,
    cache_path,
)
from proteinground.tools import run_tool

Handler = Callable[[httpx.Request], httpx.Response]


def fetcher(handler: Handler, cache_dir: Path | None = None) -> Fetcher:
    mode = Mode.CACHE_FIRST if cache_dir else Mode.LIVE
    return Fetcher(cache_dir, mode, httpx.Client(transport=httpx.MockTransport(handler)))


def uniprot_renamed_a_field(request: httpx.Request) -> httpx.Response:
    return httpx.Response(400, json={"messages": ["Invalid fields parameter value 'ft_signal'"]})


def test_rejected_request_is_an_error_not_a_missing_entry(tmp_path: Path) -> None:
    f = fetcher(uniprot_renamed_a_field, tmp_path)
    for name, arguments in (
        ("get_protein", {"accession": "P04637"}),
        ("get_sequence_window", {"accession": "P04637", "start": 1, "end": 2}),
        ("get_features", {"accession": "P04637"}),
        ("list_structures", {"accession": "P04637"}),
        ("get_variants", {"accession": "P04637", "start": 175}),
    ):
        text, is_error = run_tool(f, name, arguments)
        payload = json.loads(text)
        assert is_error and "found" not in payload, name
        assert "rejected the request" in payload["error"] and "ft_signal" in payload["error"]
        assert "not evidence that the record is missing" in payload["error"]
    assert list(tmp_path.iterdir()) == []  # a 400 is about the request, so it is not cached


def test_missing_entry_is_still_not_found() -> None:
    result = uniprot.get_protein(fetcher(lambda r: httpx.Response(404)), "P04637")
    assert not result.found and "no entry P04637" in (result.note or "")


def test_unparseable_search_is_an_error_not_zero_matches() -> None:
    f = fetcher(lambda r: httpx.Response(400, json={"messages": ["invalid syntax"]}))
    with pytest.raises(RejectedRequestError, match="could not parse the query"):
        uniprot.search(f, "gene:(")
    text, is_error = run_tool(f, "search_proteins", {"query": "gene:("})
    assert is_error and "found" not in json.loads(text)


def test_record_without_a_sequence_is_an_error_not_length_zero() -> None:
    body = {"primaryAccession": "P04637", "entryType": "UniProtKB reviewed (Swiss-Prot)"}
    f = fetcher(lambda r: httpx.Response(200, json=body))
    with pytest.raises(MalformedRecordError, match="no sequence"):
        uniprot.get_protein(f, "P04637")
    text, is_error = run_tool(
        f, "get_sequence_window", {"accession": "P04637", "start": 5, "end": 5}
    )
    assert is_error and "beyond the end" not in text


def alphafold_model(**overrides: Any) -> list[dict[str, Any]]:
    model: dict[str, Any] = {
        "uniprotAccession": "P04637",
        "entryId": "AF-P04637-F1",
        "latestVersion": 6,
        "uniprotStart": 1,
        "uniprotEnd": 393,
        "globalMetricValue": 75.06,
        "fractionPlddtVeryHigh": 0.527,
        "fractionPlddtConfident": 0.071,
        "fractionPlddtLow": 0.104,
        "fractionPlddtVeryLow": 0.298,
    }
    model.update(overrides)
    return [{k: v for k, v in model.items() if v is not None}]


def test_missing_alphafold_numbers_are_null_with_a_note_not_zero() -> None:
    models = alphafold_model(globalMetricValue=None, fractionPlddtVeryHigh=None)
    result = alphafold.get_alphafold_summary(
        fetcher(lambda r: httpx.Response(200, json=models)), "P04637"
    )
    assert result.found and result.data is not None
    assert result.data.mean_plddt is None and result.data.fraction_very_high is None
    assert result.data.fraction_low == 0.104
    assert result.note is not None
    assert "globalMetricValue" in result.note and "fractionPlddtVeryHigh" in result.note
    text, _ = run_tool(fetcher(lambda r: httpx.Response(200, json=models)), "get_alphafold_summary",
                       {"accession": "P04637"})  # fmt: skip
    assert "mean_plddt" not in json.loads(text)["data"]


def test_alphafold_rejection_differs_from_no_model() -> None:
    no_model = alphafold.get_alphafold_summary(
        fetcher(lambda r: httpx.Response(404, json={})), "Q00000"
    )
    assert not no_model.found and "no model" in (no_model.note or "")
    rejected = fetcher(lambda r: httpx.Response(400, json={"error": "Invalid identifier format"}))
    with pytest.raises(RejectedRequestError, match="Invalid identifier format"):
        alphafold.get_alphafold_summary(rejected, "P04637")


def rcsb(entity_reply: dict[str, Any], holdings: httpx.Response | None = None) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/graphql" in url:
            return httpx.Response(200, json=entity_reply)
        if "/holdings/" in url:
            return holdings or httpx.Response(404, json={"message": "No data found"})
        if url.endswith("/entry/4HHB"):
            return httpx.Response(200, json={"exptl": [{"method": "X-RAY DIFFRACTION"}]})
        return httpx.Response(404)

    return handle


def test_graphql_error_is_a_rejected_request_and_is_not_cached(tmp_path: Path) -> None:
    reply = {"errors": [{"message": "Field 'uniprot_ids' in type 'X' is undefined"}]}
    f = fetcher(rcsb(reply), tmp_path)
    text, is_error = run_tool(f, "get_structure", {"pdb_id": "4HHB"})
    assert is_error and "rejected the query" in text and "uniprot_ids" in text
    assert not cache_path(tmp_path, pdb.entities_url("4HHB")).exists()
    assert cache_path(tmp_path, pdb.entry_url("4HHB")).exists()  # the entry itself was fine


def test_entry_without_entity_records_is_an_error_not_an_empty_structure() -> None:
    with pytest.raises(MalformedRecordError, match="entity records did not load"):
        pdb.get_structure(fetcher(rcsb({"data": {"entry": None}})), "4HHB")


def test_unassigned_id_and_unreachable_status_are_told_apart() -> None:
    unassigned = pdb.get_structure(fetcher(rcsb({})), "2ZZZ")
    assert not unassigned.found and "not in the archive" in (unassigned.note or "")
    down = pdb.get_structure(fetcher(rcsb({}, holdings=httpx.Response(418))), "2ZZZ")
    assert not down.found and "could not be checked" in (down.note or "")
