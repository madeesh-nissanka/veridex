# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Crossref resolver adapter. Stdlib only."""
from __future__ import annotations

import os
import urllib.parse
from typing import Any

from veridex.httpclient import HttpClient, Response
from veridex.models import Evidence, ParsedReference, ResolvedRecord
from veridex.resolvers import Source, register_source


@register_source
class CrossrefSource(Source):
    """Crossref API adapter."""

    name = "crossref"
    rate_limit = 50.0  # 50 req/s polite pool

    BASE_URL = "https://api.crossref.org/works"

    def lookup(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []

        records: list[ResolvedRecord] = []
        evidence: list[Evidence] = []

        # Try exact identifiers in order
        for method in (
            self._try_doi,
            self._try_pmid,
            self._try_arxiv,
            self._try_isbn,
        ):
            recs, ev = method(ref)
            records.extend(recs)
            evidence.extend(ev)
            if records:
                return records, evidence

        # Bibliographic search fallback
        if ref.title:
            query = self._build_bibliographic_query(ref)
            recs, ev = self.search(query)
            records.extend(recs)
            evidence.extend(ev)

        return records, evidence

    def search(self, query: dict[str, Any]) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []

        params = {
            "query.bibliographic": query.get("text", ""),
            "rows": 5,
        }
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        data, resp = self.client.fetch_json(url)
        evidence = [self._make_evidence(resp)]

        records: list[ResolvedRecord] = []
        if resp.ok and "message" in data and "items" in data["message"]:
            for item in data["message"]["items"]:
                records.append(self.from_json(item, resp))

        return records, evidence

    def _fetch_by_doi(self, doi: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        url = f"{self.BASE_URL}/{urllib.parse.quote(doi)}"
        data, resp = self.client.fetch_json(url)
        ev = self._make_evidence(resp)

        message = data.get("message")
        if (
            not resp.ok
            or not isinstance(message, dict)
            or "items" in message
            or "DOI" not in message
        ):
            return [], [ev]

        record = self.from_json(message, resp)
        return [record], [ev]

    def _fetch_by_pmid(self, pmid: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        # Crossref doesn't directly support PMID lookup; search for it
        params = {"query": f"PMID:{pmid}", "rows": 5}
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        data, resp = self.client.fetch_json(url)
        ev = self._make_evidence(resp)

        records: list[ResolvedRecord] = []
        if resp.ok and "message" in data and "items" in data["message"]:
            for item in data["message"]["items"]:
                records.append(self.from_json(item, resp))
        return records, [ev]

    def _fetch_by_arxiv(self, arxiv_id: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        params = {"query": f"arXiv:{arxiv_id}", "rows": 5}
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        data, resp = self.client.fetch_json(url)
        ev = self._make_evidence(resp)

        records: list[ResolvedRecord] = []
        if resp.ok and "message" in data and "items" in data["message"]:
            for item in data["message"]["items"]:
                records.append(self.from_json(item, resp))
        return records, [ev]

    def _fetch_by_isbn(self, isbn: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        params = {"query": f"ISBN:{isbn}", "rows": 5}
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        data, resp = self.client.fetch_json(url)
        ev = self._make_evidence(resp)

        records: list[ResolvedRecord] = []
        if resp.ok and "message" in data and "items" in data["message"]:
            for item in data["message"]["items"]:
                records.append(self.from_json(item, resp))
        return records, [ev]

    def _build_bibliographic_query(self, ref: ParsedReference) -> dict[str, Any]:
        parts = []
        if ref.title:
            parts.append(ref.title)
        if ref.authors:
            parts.append(" ".join(ref.authors[:3]))
        if ref.year:
            parts.append(str(ref.year))
        return {"text": " ".join(parts)}

    @staticmethod
    def from_json(data: dict[str, Any], response: Response) -> ResolvedRecord:
        msg = data

        # Title
        title_list = msg.get("title") or []
        title = title_list[0] if title_list else None

        # Authors
        authors = []
        for a in msg.get("author") or []:
            family = a.get("family", "")
            given = a.get("given", "")
            if family or given:
                authors.append({"family": family, "given": given})

        # Year
        year = None
        issued = msg.get("issued") or {}
        dp = issued.get("date-parts") or []
        if dp and dp[0]:
            year = dp[0][0]

        # Journal/container
        container = msg.get("container-title") or []
        journal = container[0] if container else None

        # Volume, issue, pages
        volume = msg.get("volume")
        issue = msg.get("issue")
        pages = msg.get("page")

        # Publisher
        publisher = msg.get("publisher")

        # DOI
        doi = msg.get("DOI")

        # URL
        url = msg.get("URL")

        # Document type
        doc_type = msg.get("type")

        # Language
        language = msg.get("language")

        # Abstract (Crossref doesn't typically provide abstracts)
        abstract = None

        # Integrity: check for retraction/correction notices
        integrity = {"notices": []}
        for rel in msg.get("relation") or {}:
            for item in msg["relation"].get(rel) or []:
                rel_type = item.get("relation-type") or item.get("type")
                if rel_type in ("is-retraction-of", "is-correction-of", "is-version-of", "has-preprint"):
                    integrity["notices"].append(
                        {
                            "kind": _map_relation_kind(rel_type),
                            "url": item.get("id", ""),
                            "label": item.get("label", rel_type),
                        }
                    )
        # Also check update-to (legacy)
        for item in msg.get("update-to") or []:
            utype = item.get("type")
            if utype in ("retraction", "withdrawal", "correction", "erratum"):
                integrity["notices"].append(
                    {
                        "kind": utype if utype != "erratum" else "correction",
                        "url": item.get("DOI", ""),
                        "label": item.get("label", utype),
                    }
                )

        # is-referenced-by-count as extra signal
        extra = {"is_referenced_by_count": msg.get("is-referenced-by-count", 0)}

        return ResolvedRecord(
            source="crossref",
            source_id=doi or "",
            title=title,
            authors=authors,
            year=year,
            journal=journal,
            volume=volume,
            issue=issue,
            pages=pages,
            publisher=publisher,
            url=url,
            doi=doi,
            document_type=doc_type,
            language=language,
            abstract=abstract,
            integrity=integrity,
            extra=extra,
            source_url=response.url,
            raw_sha256=hashlib.sha256(response.body).hexdigest() if response.body else None,
            raw_size=len(response.body) if response.body else 0,
        )


def _map_relation_kind(rel_type: str) -> str:
    mapping = {
        "is-retraction-of": "retraction",
        "is-correction-of": "correction",
        "is-version-of": "correction",
        "has-preprint": "expression_of_concern",
    }
    return mapping.get(rel_type, "correction")


import hashlib