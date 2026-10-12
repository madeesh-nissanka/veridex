# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Resolver base class and registry. Stdlib only."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from veridex.httpclient import HttpClient, Response
from veridex.models import Evidence, ParsedReference, ResolvedRecord


@dataclass
class SourceOpts:
    """Options for a source adapter."""

    enabled: bool = True


class Source(ABC):
    """Base class for all source adapters."""

    name: str = ""
    rate_limit: float = 1.0  # requests per second

    def __init__(self, client: HttpClient, opts: Optional[SourceOpts] = None) -> None:
        self.client = client
        self.opts = opts or SourceOpts()

    @abstractmethod
    def lookup(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        """Try exact ID first, then bibliographic search."""

    @abstractmethod
    def search(self, query: dict[str, Any]) -> tuple[list[ResolvedRecord], list[Evidence]]:
        """Generic bibliographic search."""

    @staticmethod
    @abstractmethod
    def from_json(data: dict[str, Any], response: Response) -> ResolvedRecord:
        """Normalize a raw API response into a ResolvedRecord."""

    def _make_evidence(
        self, response: Response, body: bytes | None = None
    ) -> Evidence:
        body = body or response.body
        sha = hashlib.sha256(body).hexdigest() if body else ""
        return Evidence(
            source=self.name,
            request_url=response.url,
            http_status=response.status,
            response_sha256=sha,
            response_bytes=len(body) if body else 0,
            timestamp=time_now(),
            ok=response.ok,
            error=response.error,
            from_cache=response.from_cache,
        )

    def _try_doi(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not ref.doi:
            return [], []
        return self._fetch_by_doi(ref.doi)

    def _try_pmid(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not ref.pmid:
            return [], []
        return self._fetch_by_pmid(ref.pmid)

    def _try_arxiv(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not ref.arxiv_id:
            return [], []
        return self._fetch_by_arxiv(ref.arxiv_id)

    def _try_isbn(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not ref.isbn:
            return [], []
        return self._fetch_by_isbn(ref.isbn)

    @abstractmethod
    def _fetch_by_doi(self, doi: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        pass

    @abstractmethod
    def _fetch_by_pmid(self, pmid: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        pass

    @abstractmethod
    def _fetch_by_arxiv(self, arxiv_id: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        pass

    @abstractmethod
    def _fetch_by_isbn(self, isbn: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        pass


def time_now() -> str:
    """Current UTC time in ISO format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


SOURCES: dict[str, type[Source]] = {}


def register_source(cls: type[Source]) -> type[Source]:
    """Decorator to register a source class."""
    SOURCES[cls.name] = cls
    return cls


def source_names() -> list[str]:
    """Return sorted list of registered source names."""
    return sorted(SOURCES.keys())


def build(name: str, client: HttpClient, opts: Optional[SourceOpts] = None) -> Optional[Source]:
    """Build a source instance by name."""
    cls = SOURCES.get(name)
    if not cls:
        return None
    if opts and not opts.enabled:
        return None
    return cls(client, opts)


import hashlib