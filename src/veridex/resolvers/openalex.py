# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""OpenAlex resolver adapter. Stdlib only."""
from __future__ import annotations

import os
import urllib.parse
from typing import Any

from veridex.httpclient import HttpClient, Response
from veridex.models import Evidence, ParsedReference, ResolvedRecord
from veridex.resolvers import Source, register_source


@register_source
class OpenAlexSource(Source):
    """OpenAlex API adapter."""

    name = "openalex"
    rate_limit = 10.0  # 10 req/s with mailto

    BASE_URL = "https://api.openalex.org/works"

    def lookup(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []

        records: list[ResolvedRecord] = []
        evidence: list[Evidence] = []

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

        if ref.title:
            query = self._build_bibliographic_query(ref)
            recs, ev = self.search(query)
            records.extend(recs)
            evidence.extend(ev)

        return records, evidence

    def search(self, query: dict[str, Any]) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []

        params = {"filter": query.get("filter", ""), "per-page": 5}
        if "search" in query:
            params["search"] = query["search"]
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        data, resp = self.client.fetch_json(url)
        evidence = [self._make_evidence(resp)]

        records: list[ResolvedRecord] = []
        if resp.ok and "results" in data:
            for item in data["results"]:
                records.append(self.from_json(item, resp))

        return records, evidence

    def _fetch_by_doi(self, doi: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        url = f"{self.BASE_URL}/https://doi.org/{urllib.parse.quote(doi)}"
        data, resp = self.client.fetch_json(url)
        ev = self._make_evidence(resp)

        if not resp.ok or not isinstance(data, dict):
            return [], [ev]
        if not (data.get("id") or data.get("title") or data.get("doi")):
            return [], [ev]

        records = [self.from_json(data, resp)]
        return records, [ev]

    def _fetch_by_pmid(self, pmid: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        params = {"filter": f"pmid:{pmid}", "per-page": 5}
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        data, resp = self.client.fetch_json(url)
        ev = self._make_evidence(resp)

        records: list[ResolvedRecord] = []
        if resp.ok and "results" in data:
            for item in data["results"]:
                records.append(self.from_json(item, resp))
        return records, [ev]

    def _fetch_by_arxiv(self, arxiv_id: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        params = {"filter": f"arxiv:{arxiv_id}", "per-page": 5}
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        data, resp = self.client.fetch_json(url)
        ev = self._make_evidence(resp)

        records: list[ResolvedRecord] = []
        if resp.ok and "results" in data:
            for item in data["results"]:
                records.append(self.from_json(item, resp))
        return records, [ev]

    def _fetch_by_isbn(self, isbn: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        # OpenAlex doesn't have ISBN filter; search by title if available
        return [], []

    def _build_bibliographic_query(self, ref: ParsedReference) -> dict[str, Any]:
        parts = []
        if ref.title:
            parts.append(f"title.search:{urllib.parse.quote(ref.title)}")
        if ref.authors:
            parts.append(f"author.search:{urllib.parse.quote(' '.join(ref.authors[:3]))}")
        if ref.year:
            parts.append(f"publication_year:{ref.year}")
        filter_str = ",".join(parts)
        return {"filter": filter_str}

    @staticmethod
    def _mailto_param() -> str:
        mailto = os.environ.get("VERIDEX_MAILTO")
        return f"&mailto={urllib.parse.quote(mailto)}" if mailto else ""

    @staticmethod
    def from_json(data: dict[str, Any], response: Response) -> ResolvedRecord:
        # Title
        title = data.get("title")

        # Authors
        authors = []
        for auth in data.get("authorships") or []:
            author = auth.get("author") or {}
            family = author.get("last_name", "")
            given = author.get("display_name", "").replace(family, "").strip(", ")
            if family or given:
                authors.append({"family": family, "given": given})

        # Year
        year = data.get("publication_year")

        # Journal/venue
        venue = data.get("host_venue") or {}
        journal = venue.get("display_name")

        # Volume, issue, pages
        biblio = data.get("biblio") or {}
        volume = biblio.get("volume")
        issue = biblio.get("issue")
        pages = None
        if biblio.get("first_page") and biblio.get("last_page"):
            pages = f"{biblio['first_page']}-{biblio['last_page']}"
        elif biblio.get("first_page"):
            pages = biblio["first_page"]

        # Publisher
        publisher = venue.get("publisher")

        # DOI
        doi = data.get("doi")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/") :]

        # URL
        url = data.get("id")

        # Document type
        doc_type = data.get("type")

        # Language
        language = data.get("language")

        # Abstract (inverted index)
        abstract = None
        inv_index = data.get("abstract_inverted_index")
        if inv_index:
            # Reconstruct abstract from inverted index
            max_pos = max(pos for positions in inv_index.values() for pos in positions)
            words = [""] * (max_pos + 1)
            for word, positions in inv_index.items():
                for pos in positions:
                    words[pos] = word
            abstract = " ".join(words)

        # Integrity: check for retractions/corrections
        integrity = {"notices": []}
        # OpenAlex has 'retracted' boolean
        if data.get("retracted"):
            integrity["notices"].append(
                {
                    "kind": "retraction",
                    "url": data.get("id", ""),
                    "label": "Retracted in OpenAlex",
                }
            )
        # Check for corrections via related works
        for rel in data.get("related_works") or []:
            pass  # Could expand with more detail if needed

        extra = {
            "cited_by_count": data.get("cited_by_count", 0),
            "open_access": data.get("open_access"),
            "type_crossref": data.get("type_crossref"),
        }

        return ResolvedRecord(
            source="openalex",
            source_id=doi or data.get("id", ""),
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


import hashlib