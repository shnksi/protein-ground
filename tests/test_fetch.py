from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from proteinground.fetch import Fetcher, Mode, OfflineMissError, UpstreamError, cache_path

URL = "https://rest.uniprot.org/uniprotkb/P01308.json?fields=accession"


def client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_cache_first_writes_then_replays_offline(tmp_path: Path) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, json={"primaryAccession": "P01308"}, headers={"x-uniprot-release": "2026_04"}
        )

    live = Fetcher(tmp_path, Mode.CACHE_FIRST, client(httpx.MockTransport(handle)))
    first = live.get_json(URL)
    assert first.ok and not first.from_cache and first.headers["x-uniprot-release"] == "2026_04"
    assert cache_path(tmp_path, URL).exists()

    replayed = Fetcher(tmp_path, Mode.OFFLINE).get_json(URL)
    assert replayed.from_cache and replayed.body == {"primaryAccession": "P01308"}
    assert calls == 1


def test_not_found_is_cached_like_a_record(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(404))
    Fetcher(tmp_path, Mode.CACHE_FIRST, client(transport)).get_json(URL)
    replayed = Fetcher(tmp_path, Mode.OFFLINE).get_json(URL)
    assert replayed.status == 404 and replayed.body is None


def test_offline_miss_raises(tmp_path: Path) -> None:
    fetcher = Fetcher(tmp_path, Mode.OFFLINE)
    with pytest.raises(OfflineMissError):
        fetcher.get_json(URL)
    assert fetcher.misses == [URL]


def test_replay_fetches_misses_without_writing(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    fetcher = Fetcher(tmp_path, Mode.REPLAY, client(transport))
    assert fetcher.get_json(URL).body == {"ok": True}
    assert fetcher.misses == [URL]
    assert not cache_path(tmp_path, URL).exists()


def test_retries_server_errors_then_gives_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("proteinground.fetch.time.sleep", lambda s: None)
    statuses = iter([503, 200])
    transport = httpx.MockTransport(lambda r: httpx.Response(next(statuses), json={"n": 1}))
    assert Fetcher(None, Mode.LIVE, client(transport)).get_json(URL).ok

    always = httpx.MockTransport(lambda r: httpx.Response(503))
    with pytest.raises(UpstreamError):
        Fetcher(None, Mode.LIVE, client(always)).get_json(URL)


def test_offline_needs_a_cache_dir() -> None:
    with pytest.raises(ValueError):
        Fetcher(None, Mode.OFFLINE)


def test_corrupt_cache_file_is_a_miss(tmp_path: Path) -> None:
    cache_path(tmp_path, URL).write_bytes(b"not gzip")
    with pytest.raises(OfflineMissError):
        Fetcher(tmp_path, Mode.OFFLINE).get_json(URL)


def test_cache_first_rechecks_expired_records(tmp_path: Path) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    fetcher = Fetcher(tmp_path, Mode.CACHE_FIRST, client(httpx.MockTransport(handle)),
                      ttl_days=7, negative_ttl_days=0)  # fmt: skip
    fetcher.get_json(URL)
    fetcher.get_json(URL)
    assert calls == 2  # a cached "not found" older than its TTL is fetched again
    keep = Fetcher(tmp_path, Mode.CACHE_FIRST, client(httpx.MockTransport(handle)))
    keep.get_json(URL)
    assert calls == 2  # no TTL: the snapshot keeps it


def test_from_env_expands_tilde_and_disables_url_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEINGROUND_CACHE_DIR", "~/.cache/proteinground-test")
    monkeypatch.setenv("PROTEINGROUND_MODE", "cache-first")
    f = Fetcher.from_env()
    assert f.cache_dir is not None and f.cache_dir.is_absolute()
    assert not str(f.cache_dir).startswith("~")
    assert f._track_urls is False


def test_429_respects_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("proteinground.fetch.time.sleep", slept.append)
    replies = iter(
        [httpx.Response(429, headers={"Retry-After": "4"}), httpx.Response(200, json={"ok": True})]
    )
    f = Fetcher(None, Mode.LIVE, client(httpx.MockTransport(lambda r: next(replies))))
    assert f.get_json(URL).ok
    assert slept == [4.0]
