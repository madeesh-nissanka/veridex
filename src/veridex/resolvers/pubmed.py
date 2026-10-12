# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""PubMed (NCBI E-utilities) resolver adapter. Stdlib only."""
from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any

from veridex.httpclient import HttpClient, Response
from veridex.models import Evidence, ParsedReference, ResolvedRecord
from veridex.resolvers import Source, register_source

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


@register_source
class PubmedSource(Source):
    """PubMed adapter using esearch + esummary JSON."""

    name = "pubmed"
    rate_limit = 3.0

    def lookup(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        if ref.pmid:
            return self._fetch_by_pmid(ref.pmid)
        if ref.doi:
            return self._search_terms(f'"{ref.doi}" [AID]')
        if ref.title:
            terms = f'"{ref.title}" [TITLE]'
            if ref.authors:
                terms += f' AND "{ref.authors[0]}" [AUTH]'
            return self._search_terms(terms)
        return [], []

    def search(self, query: dict[str, Any]) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        terms = query.get("query") or query.get("terms") or ""
        if query.get("year"):
            terms += f' AND {query["year"]}[PDAT]'
        return self._search_terms(terms)

    def _search_terms(self, terms: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not terms:
            return [], []
        url = (
            f"{EUTILS}/esearch.fcgi?db=pubmed&retmode=json&retmax=5"
            f"&term={urllib.parse.quote(terms)}"
        )
        data, resp = self.client.fetch_json(url)
        evidence = [self._make_evidence(resp)]
        ids = ((data.get("esearchresult") or {}).get("idlist")) or []
        if not resp.ok or not ids:
            return [], evidence
        recs, ev = self._fetch_ids(ids)
        return recs, evidence + ev

    def _fetch_by_pmid(self, pmid: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._fetch_ids([pmid])

    def _fetch_ids(self, ids: list[str]) -> tuple[list[ResolvedRecord], list[Evidence]]:
        url = (
            f"{EUTILS}/esummary.fcgi?db=pubmed&retmode=json&id="
            + urllib.parse.quote(",".join(ids))
        )
        data, resp = self.client.fetch_json(url)
        ev = [self._make_evidence(resp)]
        records: list[ResolvedRecord] = []
        if resp.ok:
            result = data.get("result") or {}
            for uid in result.get("uids") or ids:
                item = result.get(uid)
                if isinstance(item, dict):
                    records.append(self.from_json(item, resp))
        return records, ev

    def _fetch_by_doi(self, doi: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._search_terms(f'"{doi}" [AID]')

    def _fetch_by_arxiv(self, arxiv_id: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._search_terms(f'{arxiv_id}[AID]')

    def _fetch_by_isbn(self, isbn: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return [], []

    @staticmethod
    def from_json(data: dict[str, Any], response: Response) -> ResolvedRecord:
        title = data.get("title")
        authors = [
            {"family": a.get("name", ""), "given": ""}
            for a in (data.get("authors") or [])
            if isinstance(a, dict) and a.get("name")
        ]
        pubdate = str(data.get("pubdate") or "")
        year = None
        if len(pubdate) >= 4 and pubdate[:4].isdigit():
            year = int(pubdate[:4])

        doi = None
        for aid in data.get("articleids") or []:
            if isinstance(aid, dict) and aid.get("idtype") == "doi":
                doi = aid.get("value")
                break

        pages = data.get("pages")
        volume = data.get("volume")
        issue = data.get("issue")

        body = response.body or b""
        return ResolvedRecord(
            source="pubmed",
            source_id=str(data.get("uid", "")),
            title=title,
            authors=authors,
            year=year,
            journal=data.get("fulljournalname") or data.get("source"),
            volume=volume,
            issue=issue,
            pages=pages,
            doi=doi,
            pmid=str(data.get("uid", "")) or None,
            document_type="article",
            extra={
                "pubtype": data.get("pubtype"),
                "language": data.get("language"),
                "elocationid": data.get("elocationid"),
            },
            source_url=response.url,
            raw_sha256=hashlib.sha256(body).hexdigest() if body else None,
            raw_size=len(body),
        )
