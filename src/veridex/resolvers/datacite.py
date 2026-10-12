# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""DataCite resolver adapter. Stdlib only."""
from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any

from veridex.httpclient import HttpClient, Response
from veridex.models import Evidence, ParsedReference, ResolvedRecord
from veridex.resolvers import Source, register_source


@register_source
class DataciteSource(Source):
    """DataCite REST API adapter (DOI + bibliographic search)."""

    name = "datacite"
    rate_limit = 2.0

    BASE_URL = "https://api.datacite.org/dois"

    def lookup(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        if ref.doi:
            return self._fetch_by_doi(ref.doi)
        if ref.title:
            query = {"query": ref.title, "author": (ref.authors or [""])[0]}
            return self.search(query)
        return [], []

    def search(self, query: dict[str, Any]) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        parts = []
        if query.get("query"):
            parts.append(f"titles.title:{urllib.parse.quote(str(query['query']))}")
        if query.get("author"):
            parts.append(f"creators.name:{urllib.parse.quote(str(query['author']))}")
        if query.get("year"):
            parts.append(f"publicationYear:{query['year']}")
        if not parts:
            return [], []
        url = f"{self.BASE_URL}?query={'+AND+'.join(parts)}&page[size]=5"
        data, resp = self.client.fetch_json(url)
        evidence = [self._make_evidence(resp)]
        records: list[ResolvedRecord] = []
        if resp.ok:
            for item in (data.get("data") or [])[:5]:
                if isinstance(item, dict):
                    records.append(self.from_json(item, resp))
        return records, evidence

    def _fetch_by_doi(self, doi: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        url = f"{self.BASE_URL}/{urllib.parse.quote(doi)}"
        data, resp = self.client.fetch_json(url)
        ev = self._make_evidence(resp)
        if not resp.ok:
            return [], [ev]
        item = data.get("data")
        if isinstance(item, list):
            item = item[0] if item else None
        records = [self.from_json(item, resp)] if isinstance(item, dict) else []
        return records, [ev]

    def _fetch_unsupported(self) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return [], []
    def _fetch_by_pmid(self, pmid: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._fetch_unsupported()

    def _fetch_by_arxiv(self, arxiv_id: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._fetch_unsupported()

    def _fetch_by_isbn(self, isbn: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._fetch_unsupported()

    @staticmethod
    def from_json(data: dict[str, Any], response: Response) -> ResolvedRecord:
        attrs = data.get("attributes") or {}

        title = None
        titles = attrs.get("titles") or []
        if isinstance(titles, list) and titles:
            first = titles[0]
            title = first.get("title") if isinstance(first, dict) else str(first)
        elif isinstance(titles, dict):
            title = titles.get("title")

        authors: list[dict[str, str]] = []
        for creator in attrs.get("creators") or []:
            if not isinstance(creator, dict):
                continue
            name = creator.get("name", "")
            family = creator.get("familyName", "")
            given = creator.get("givenName", "")
            if not family and name:
                family = name.split(",")[0].strip()
                given = name.split(",", 1)[1].strip() if "," in name else ""
            if family or given or name:
                authors.append({"family": family or name, "given": given})

        year = attrs.get("publicationYear")
        try:
            year = int(year) if year is not None else None
        except (TypeError, ValueError):
            year = None

        journal = attrs.get("containerTitle")
        publisher = attrs.get("publisher")
        if isinstance(publisher, dict):
            publisher = publisher.get("name")

        doi = attrs.get("doi") or data.get("id")
        if doi and str(doi).startswith("https://doi.org/"):
            doi = str(doi)[len("https://doi.org/"):]

        resource_type = str(((attrs.get("types") or {}).get("resourceTypeGeneral")) or "")
        document_type = "preprint" if resource_type.lower() == "text" else (
            resource_type.lower() or None
        )

        url = attrs.get("url")
        body = response.body or b""
        return ResolvedRecord(
            source="datacite",
            source_id=str(doi or data.get("id", "")),
            title=title,
            authors=authors,
            year=year,
            journal=journal,
            publisher=publisher,
            url=url,
            doi=doi,
            document_type=document_type,
            extra={
                "resource_type": resource_type,
                "publisher": publisher,
                "versions": attrs.get("versions"),
            },
            source_url=response.url,
            raw_sha256=hashlib.sha256(body).hexdigest() if body else None,
            raw_size=len(body),
        )
