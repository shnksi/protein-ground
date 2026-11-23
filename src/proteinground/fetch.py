"""HTTP GET for JSON, with an on-disk response cache.

Every response the tools read can be written to a cache directory and replayed
offline. The eval runs offline against a frozen snapshot, so the agent sees
exactly the records the gold answers were computed from.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from proteinground.version import __version__

USER_AGENT = f"proteinground/{__version__} (+https://github.com/shnksi/protein-ground)"
KEEP_HEADERS = ("x-uniprot-release", "x-uniprot-release-date", "x-total-results")
# Statuses that are an answer rather than a transport failure: returned without a retry.
TERMINAL_STATUSES = frozenset({200, 400, 404, 410})
# Of those, the ones that describe the record. They are cached, so "this does not exist"
# replays offline too. A 400 describes our request (a renamed field, a malformed query),
# never the record, so it is neither cached nor read as "not found".
CACHED_STATUSES = frozenset({200, 404, 410})
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class Mode(StrEnum):
    LIVE = "live"
    """Always fetch; write to the cache if one is configured."""
    CACHE_FIRST = "cache-first"
    """Read the cache when it has the URL, otherwise fetch and write."""
    OFFLINE = "offline"
    """Read the cache only; a miss raises OfflineMissError."""
    REPLAY = "replay"
    """Read the cache; on a miss fetch live but do not write, and count the miss."""


class OfflineMissError(LookupError):
    """Offline mode was asked for a URL the cache does not hold."""


class UpstreamError(RuntimeError):
    """The database did not answer usefully after retries."""


class RejectedRequestError(UpstreamError):
    """The database rejected the request itself (HTTP 400, or a GraphQL error).

    That is a fault in the query or a change in the upstream API. It says nothing about
    whether the record exists, so it must never be reported as "not found".
    """


class MalformedRecordError(UpstreamError):
    """The database answered, but the record lacks a field the tool needs."""


class InvalidInputError(ValueError):
    """The caller's arguments cannot be turned into a lookup."""


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    body: Any
    retrieved_at: str
    headers: dict[str, str]
    from_cache: bool

    @property
    def ok(self) -> bool:
        return self.status == 200

    def upstream_message(self) -> str:
        """What the database said about a rejected request, when it said anything."""
        body = self.body
        if isinstance(body, dict):
            for key in ("messages", "errors"):
                items = body.get(key)
                if isinstance(items, list) and items:
                    first = items[0]
                    text = first.get("message") if isinstance(first, dict) else first
                    return str(text)[:300]
            for key in ("error", "message"):
                if body.get(key):
                    return str(body[key])[:300]
        return ""


def raise_if_rejected(response: Response, what: str) -> None:
    """Turn an HTTP 400 into an error, so it is never mistaken for a missing record."""
    if response.status != 400:
        return
    said = response.upstream_message()
    raise RejectedRequestError(
        f"{what}: the database rejected the request (HTTP 400"
        + (f": {said}" if said else "")
        + "). This is a problem with the query, not evidence that the record is missing."
    )


def is_graphql_error(body: Any) -> bool:
    return isinstance(body, dict) and bool(body.get("errors"))


def cache_path(cache_dir: Path, url: str) -> Path:
    netloc = urlsplit(url).netloc
    prefix = next((name for name in ("uniprot", "rcsb", "alphafold") if name in netloc), "other")
    digest = hashlib.sha256(url.encode()).hexdigest()[:20]
    return cache_dir / f"{prefix}-{digest}.json.gz"


class Fetcher:
    """Fetches JSON and records each response so it can be replayed."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        mode: Mode = Mode.CACHE_FIRST,
        client: httpx.Client | None = None,
        retries: int = 2,
        ttl_days: float | None = None,
        negative_ttl_days: float | None = None,
    ) -> None:
        """ttl_days and negative_ttl_days apply in cache-first mode only. None keeps a
        cached record forever, which is what a frozen eval snapshot wants; the MCP server
        sets them from the environment so "not found" and stale values get rechecked."""
        if mode in (Mode.OFFLINE, Mode.REPLAY) and cache_dir is None:
            raise ValueError(f"{mode.value} mode needs a cache directory")
        self.cache_dir = cache_dir
        self.mode = mode
        self.retries = retries
        self.ttl_days = ttl_days
        self.negative_ttl_days = negative_ttl_days
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        self.urls_seen: list[str] = []
        self.misses: list[str] = []

    @classmethod
    def from_env(cls) -> Fetcher:
        raw_dir = os.environ.get("PROTEINGROUND_CACHE_DIR")
        mode = Mode(os.environ.get("PROTEINGROUND_MODE", Mode.CACHE_FIRST.value))
        ttl = float(os.environ.get("PROTEINGROUND_CACHE_TTL_DAYS", "7"))
        return cls(
            cache_dir=Path(raw_dir) if raw_dir else None,
            mode=mode,
            ttl_days=ttl,
            negative_ttl_days=min(ttl, 1.0),
        )

    def get_json(self, url: str) -> Response:
        self.urls_seen.append(url)
        if self.cache_dir is not None and self.mode is not Mode.LIVE:
            cached = self._read(url)
            if cached is not None and not self._expired(cached):
                return cached
        if self.mode is Mode.OFFLINE:
            self.misses.append(url)
            raise OfflineMissError(f"not in the frozen snapshot: {url}")
        if self.mode is Mode.REPLAY:
            self.misses.append(url)
            return self._fetch(url)
        response = self._fetch(url)
        # A GraphQL error arrives as HTTP 200; like a 400 it describes the request.
        cacheable = response.status in CACHED_STATUSES and not is_graphql_error(response.body)
        if self.cache_dir is not None and cacheable:
            self._write(response)
        return response

    def _fetch(self, url: str) -> Response:
        last_error = "no attempt made"
        for attempt in range(self.retries + 1):
            try:
                raw = self._client.get(url)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if raw.status_code in TERMINAL_STATUSES:
                    return Response(
                        url=url,
                        status=raw.status_code,
                        body=_parse_body(raw),
                        retrieved_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        headers={k: raw.headers[k] for k in KEEP_HEADERS if k in raw.headers},
                        from_cache=False,
                    )
                last_error = f"HTTP {raw.status_code}"
                if raw.status_code not in RETRY_STATUSES:
                    break
            if attempt < self.retries:
                time.sleep(1.5 * (attempt + 1))
        raise UpstreamError(f"{url}: {last_error}")

    def _expired(self, cached: Response) -> bool:
        if self.mode is not Mode.CACHE_FIRST:
            return False
        ttl = self.ttl_days if cached.ok else self.negative_ttl_days
        if ttl is None:
            return False
        try:
            fetched = datetime.strptime(cached.retrieved_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return True
        age_days = (datetime.now(UTC) - fetched.replace(tzinfo=UTC)).total_seconds() / 86400
        return age_days > ttl

    def _read(self, url: str) -> Response | None:
        assert self.cache_dir is not None
        path = cache_path(self.cache_dir, url)
        if not path.exists():
            return None
        try:
            record = json.loads(gzip.decompress(path.read_bytes()))
            if record.get("url") != url:  # hash collision guard
                return None
            return Response(
                url=url,
                status=int(record["status"]),
                body=record["body"],
                retrieved_at=str(record["retrieved_at"]),
                headers=dict(record.get("headers", {})),
                from_cache=True,
            )
        except (OSError, EOFError, ValueError, KeyError, TypeError):
            return None  # a truncated or corrupt file is a miss, not a crash

    def _write(self, response: Response) -> None:
        assert self.cache_dir is not None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "url": response.url,
            "status": response.status,
            "retrieved_at": response.retrieved_at,
            "headers": response.headers,
            "body": response.body,
        }
        path = cache_path(self.cache_dir, response.url)
        data = json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode()
        partial = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        partial.write_bytes(gzip.compress(data, mtime=0))
        os.replace(partial, path)  # atomic, so a concurrent reader never sees half a file


def _parse_body(raw: httpx.Response) -> Any:
    if raw.status_code != 200:
        try:  # keep the database's own explanation of a 400 or 404 when it gives one
            return raw.json()
        except ValueError:
            return None
    try:
        return raw.json()
    except ValueError as exc:
        raise UpstreamError(f"{raw.url}: response was not JSON") from exc
