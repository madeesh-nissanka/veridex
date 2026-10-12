# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""DOAJ (Directory of Open Access Journals) resolver adapter. Stdlib only."""
from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any

from veridex.httpclient import HttpClient, Response
from veridex.models import Evidence, ParsedReference, ResolvedRecord
from veridex.resolvers import Source, register_source

BASE = "https://doaj.org/api/search/articles"


@register_source
class DoajSource(Source):
    """DOAJ article search by DOI, title, or generic query string."""

    name = "doaj"
    rate_limit = 1.0

    def lookup(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        if ref.doi:
            return self._search(f'doi:"{ref.doi}"')
        if ref.title:
            terms = f'title:"{ref.title}"'
            if ref.authors:
                terms += f' AND authors.name:"{ref.authors[0]}"'
            return self._search(terms)
        return [], []

    def search(self, query: dict[str, Any]) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        return self._search(query.get("query") or "")

    def _search(self, terms: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not terms:
            return [], []
        url = f"{BASE}/{urllib.parse.quote(terms)}?pageSize=5"
        data, resp = self.client.fetch_json(url)
        evidence = [self._make_evidence(resp)]
        records: list[ResolvedRecord] = []
        if resp.ok:
            for item in data.get("results") or []:
                bibjson = item.get("bibjson") if isinstance(item, dict) else None
                if isinstance(bibjson, dict):
                    wrapped = {"bibjson": bibjson, "id": item.get("id")}
                    records.append(self.from_json(wrapped, resp))
        return records, evidence

    def _fetch_by_doi(self, doi: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._search(f'doi:"{doi}"')

    def _fetch_by_pmid(self, pmid: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._search(f'pmid:"{pmid}"')

    def _fetch_by_arxiv(self, arxiv_id: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return [], []

    def _fetch_by_isbn(self, isbn: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return [], []

    @staticmethod
    def from_json(data: dict[str, Any], response: Response) -> ResolvedRecord:
        bib = data.get("bibjson") or {}

        authors = [
            {"family": a.get("name", ""), "given": ""}
            for a in bib.get("author") or []
            if isinstance(a, dict) and a.get("name")
        ]

        year = None
        try:
            year = int(bib.get("year")) if bib.get("year") else None
        except (TypeError, ValueError):
            year = None

        journal = bib.get("journal") or {}
        pages = bib.get("pages") or {}
        page_range = None
        if isinstance(pages, dict) and (pages.get("start") or pages.get("end")):
            page_range = f"{pages.get('start', '')}-{pages.get('end', '')}"

        doi = None
        isbn = None
        for ident in bib.get("identifier") or []:
            if not isinstance(ident, dict):
                continue
            if ident.get("type") == "doi":
                doi = ident.get("id")
            elif ident.get("type") == "isbn":
                isbn = ident.get("id")

        body = response.body or b""
        return ResolvedRecord(
            source="doaj",
            source_id=str(data.get("id", "")),
            title=bib.get("title"),
            authors=authors,
            year=year,
            journal=journal.get("title"),
            volume=journal.get("volume"),
            issue=journal.get("number"),
            pages=page_range,
            publisher=bib.get("publisher"),
            doi=doi,
            isbn=isbn,
            document_type="article",
            abstract=bib.get("abstract"),
            extra={
                "issn": journal.get("issn"),
                "fulltext_url": (bib.get("link") or [{}])[0].get("url") if bib.get("link") else None,
                "license": (bib.get("license") or [{}])[0].get("type") if bib.get("license") else None,
            },
            source_url=response.url,
            raw_sha256=hashlib.sha256(body).hexdigest() if body else None,
            raw_size=len(body),
        )
