"""Polite, write-once cached HTTP client.

Raw data rules:
- Every response body is stored gzipped under ``raw_dir/<cache_key>.json.gz``
  and is never overwritten. A cache hit never touches the network.
- 404s are recorded as ``<cache_key>.404`` markers so missing resources are not re-requested.
- Every network fetch is appended to ``raw_dir/manifest.jsonl``
  (url, cache path, status, UTC timestamp, sha256, size).
- Requests to the same host are spaced at least ``min_interval_s`` apart; 429/5xx and
  connection errors are retried with exponential backoff.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

_SAFE_KEY = re.compile(r"^[A-Za-z0-9_\-./=]+$")


class NotFound(Exception):
    """The resource returned 404 (live or from a cached 404 marker)."""


class CachedClient:
    def __init__(
        self,
        raw_dir: str | Path,
        user_agent: str,
        min_interval_s: float = 1.0,
        timeout_s: float = 30,
        max_retries: int = 4,
        backoff_base_s: float = 2.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.raw_dir = Path(raw_dir)
        self.min_interval_s = min_interval_s
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}
        self.network_calls = 0

    @classmethod
    def from_config(cls, cfg: dict[str, Any], raw_dir: str | Path) -> "CachedClient":
        h = cfg["http"]
        return cls(
            raw_dir=raw_dir,
            user_agent=h["user_agent"],
            min_interval_s=h["min_interval_s"],
            timeout_s=h["timeout_s"],
            max_retries=h["max_retries"],
            backoff_base_s=h["backoff_base_s"],
        )

    def _paths(self, cache_key: str) -> tuple[Path, Path]:
        if not _SAFE_KEY.match(cache_key) or ".." in cache_key.split("/"):
            raise ValueError(f"unsafe cache key: {cache_key!r}")
        base = self.raw_dir / cache_key
        return base.with_name(base.name + ".json.gz"), base.with_name(base.name + ".404")

    def is_cached(self, cache_key: str) -> bool:
        body, missing = self._paths(cache_key)
        return body.exists() or missing.exists()

    def get_json(self, url: str, cache_key: str) -> Any:
        body_path, missing_path = self._paths(cache_key)
        if body_path.exists():
            return json.loads(gzip.decompress(body_path.read_bytes()))
        if missing_path.exists():
            raise NotFound(url)

        resp = self._fetch(url)
        if resp.status_code == 404:
            self._write_once(missing_path, b"")
            self._log(url, missing_path, 404, b"")
            raise NotFound(url)
        resp.raise_for_status()
        content = resp.content
        data = json.loads(content)  # validate before caching
        self._write_once(body_path, gzip.compress(content, mtime=0))
        self._log(url, body_path, resp.status_code, content)
        return data

    def _fetch(self, url: str) -> requests.Response:
        host = urlparse(url).netloc
        for attempt in range(self.max_retries + 1):
            last = self._last_request.get(host)
            if last is not None:
                wait = self.min_interval_s - (self._clock() - last)
                if wait > 0:
                    self._sleep(wait)
            self._last_request[host] = self._clock()
            self.network_calls += 1
            try:
                resp = self.session.get(url, timeout=self.timeout_s)
            except requests.ConnectionError:
                if attempt == self.max_retries:
                    raise
            else:
                if resp.status_code != 429 and resp.status_code < 500:
                    return resp
                if attempt == self.max_retries:
                    return resp
            self._sleep(self.backoff_base_s * 2**attempt)
        raise AssertionError("unreachable")

    @staticmethod
    def _write_once(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"raw cache is immutable: {path}")
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    def _log(self, url: str, path: Path, status: int, content: bytes) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        rec = {
            "url": url,
            "path": str(path.relative_to(self.raw_dir)),
            "status": status,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
        with (self.raw_dir / "manifest.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")
