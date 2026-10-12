# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Semantic Scholar Graph API resolver adapter. Stdlib only."""
from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any

from veridex.httpclient import HttpClient, Response
from veridex.models import Evidence, ParsedReference, ResolvedRecord
from veridex.resolvers import Source, register_source

BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,year,venue,authors,externalIds,publicationTypes,abstract,url,publicationVenue"


@register_source
class SemScholarSource(Source):
    """Semantic Scholar paper lookup by DOI/arXiv/PMID and relevance search."""

    name = "semscholar"
    rate_limit = 1.0

    def lookup(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        if ref.doi:
            return self._fetch(f"DOI:{ref.doi}")
        if ref.arxiv_id:
            return self._fetch(f"arXiv:{ref.arxiv_id}")
        if ref.pmid:
            return self._fetch(f"PMID:{ref.pmid}")
        if ref.title:
            return self.search({"query": ref.title})
        return [], []

    def search(self, query: dict[str, Any]) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        terms = query.get("query") or ""
        if not terms:
            return [], []
        url = (
            f"{BASE}/paper/search?query={urllib.parse.quote(terms)}"
            f"&limit=5&fields={FIELDS}"
        )
        data, resp = self.client.fetch_json(url)
        evidence = [self._make_evidence(resp)]
        records: list[ResolvedRecord] = []
        if resp.ok:
            for item in data.get("data") or []:
                if isinstance(item, dict):
                    records.append(self.from_json(item, resp))
        return records, evidence

    def _fetch(self, paper_id: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        url = f"{BASE}/paper/{urllib.parse.quote(paper_id, safe='/:')}?fields={FIELDS}"
        data, resp = self.client.fetch_json(url)
        ev = [self._make_evidence(resp)]
        if not resp.ok or not isinstance(data, dict) or not data:
            return [], ev
        return [self.from_json(data, resp)], ev

    def _fetch_by_doi(self, doi: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._fetch(f"DOI:{doi}")

    def _fetch_by_pmid(self, pmid: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._fetch(f"PMID:{pmid}")

    def _fetch_by_arxiv(self, arxiv_id: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._fetch(f"arXiv:{arxiv_id}")

    def _fetch_by_isbn(self, isbn: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return [], []

    @staticmethod
    def from_json(data: dict[str, Any], response: Response) -> ResolvedRecord:
        authors = [
            {"family": "", "given": a.get("name", "")}
            for a in (data.get("authors") or [])
            if isinstance(a, dict) and a.get("name")
        ]
        external = data.get("externalIds") or {}
        doi = external.get("DOI")
        year = data.get("year")
        try:
            year = int(year) if year is not None else None
        except (TypeError, ValueError):
            year = None

        pub_types = data.get("publicationTypes") or []
        document_type = None
        for t in pub_types:
            name = (t.get("name") if isinstance(t, dict) else str(t)) or ""
            if "Review" in name:
                document_type = "review"
            elif "JournalArticle" in name:
                document_type = "article"
            elif "Conference" in name:
                document_type = "conference"

        body = response.body or b""
        return ResolvedRecord(
            source="semscholar",
            source_id=str(data.get("paperId", "")),
            title=data.get("title"),
            authors=authors,
            year=year,
            journal=data.get("venue"),
            publisher=None,
            doi=doi,
            pmid=external.get("PubMed"),
            arxiv_id=external.get("ArXiv"),
            url=data.get("url"),
            document_type=document_type,
            abstract=data.get("abstract"),
            extra={"corpusId": external.get("CorpusId"), "paperId": data.get("paperId")},
            source_url=response.url,
            raw_sha256=hashlib.sha256(body).hexdigest() if body else None,
            raw_size=len(body),
        )
