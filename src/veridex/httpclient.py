# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""HTTP client with disk cache, retries, and per-host rate limiting. Stdlib only."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse


@dataclass
class Response:
    """HTTP response with metadata."""

    url: str
    status: int
    body: bytes
    from_cache: bool = False
    ok: bool = True
    error: Optional[str] = None


Transport = Callable[[str, int], Response]


class HttpClient:
    """HTTP client with caching, exponential backoff, and per-host rate limiting."""

    def __init__(
        self,
        user_agent: str,
        cache_dir: Optional[str] = None,
        cache_ttl: int = 86400,
        timeout: int = 30,
        max_retries: int = 3,
        min_interval: float = 0.5,
        transport: Optional[Transport] = None,
    ) -> None:
        self.user_agent = user_agent
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval
        self._transport = transport
        self._host_last_request: dict[str, float] = {}
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def _cache_path(self, url: str) -> str:
        assert self.cache_dir is not None
        key = hashlib.sha256(url.encode()).hexdigest()
        return os.path.join(self.cache_dir, key)

    def _read_cache(self, url: str) -> Optional[Response]:
        if not self.cache_dir:
            return None
        path = self._cache_path(url)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if time.time() - data["timestamp"] > self.cache_ttl:
                return None
            return Response(
                url=data["url"],
                status=data["status"],
                body=bytes.fromhex(data["body_hex"]),
                from_cache=True,
                ok=data["ok"],
                error=data.get("error"),
            )
        except Exception:
            return None

    def _write_cache(self, response: Response) -> None:
        if not self.cache_dir:
            return
        path = self._cache_path(response.url)
        try:
            with open(path, "w") as f:
                json.dump(
                    {
                        "url": response.url,
                        "status": response.status,
                        "body_hex": response.body.hex(),
                        "timestamp": time.time(),
                        "ok": response.ok,
                        "error": response.error,
                    },
                    f,
                )
        except Exception:
            pass

    def _wait_for_host(self, url: str) -> None:
        host = urlparse(url).netloc
        now = time.monotonic()
        last = self._host_last_request.get(host, 0.0)
        elapsed = now - last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._host_last_request[host] = time.monotonic()

    def _default_transport(self, url: str, timeout: int) -> Response:
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                return Response(url=url, status=r.status, body=body, ok=True)
        except urllib.error.HTTPError as e:
            body = e.read() if hasattr(e, "read") else b""
            return Response(url=url, status=e.code, body=body, ok=False, error=f"http_{e.code}")
        except urllib.error.URLError as e:
            return Response(url=url, status=0, body=b"", ok=False, error=f"url_error: {e}")
        except Exception as e:
            return Response(url=url, status=0, body=b"", ok=False, error=f"error: {e}")

    def get(self, url: str) -> Response:
        """GET request with retries, caching, and rate limiting."""
        cached = self._read_cache(url)
        if cached:
            return cached

        transport = self._transport or self._default_transport
        last_error: Optional[str] = None

        for attempt in range(self.max_retries + 1):
            self._wait_for_host(url)
            resp = transport(url, self.timeout)

            if resp.ok:
                self._write_cache(resp)
                return resp

            if resp.status in (429, 503) or resp.error and resp.error.startswith("url_error"):
                last_error = resp.error or f"http_{resp.status}"
                if attempt < self.max_retries:
                    backoff = 2 ** attempt
                    time.sleep(backoff)
                    continue

            self._write_cache(resp)
            return resp

        return Response(
            url=url, status=0, body=b"", ok=False, error=last_error or "max_retries_exceeded"
        )

    def fetch_json(self, url: str) -> tuple[dict, Response]:
        """GET and parse JSON. Returns (data, response)."""
        resp = self.get(url)
        if not resp.ok or not resp.body:
            return {}, resp
        try:
            data = json.loads(resp.body.decode("utf-8"))
            return data, resp
        except Exception as e:
            error_resp = Response(
                url=resp.url,
                status=resp.status,
                body=resp.body,
                from_cache=resp.from_cache,
                ok=False,
                error=f"json_decode: {e}",
            )
            return {}, error_resp