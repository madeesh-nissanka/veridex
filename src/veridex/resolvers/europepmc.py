# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Europe PMC resolver adapter (also carries retraction/correction signals). Stdlib only."""
from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any

from veridex.httpclient import HttpClient, Response
from veridex.models import Evidence, ParsedReference, ResolvedRecord
from veridex.resolvers import Source, register_source

REST = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

_NOTICE_KINDS = {
    "retraction": "retraction",
    "expression of concern": "expression_of_concern",
    "correction": "correction",
    "erratum": "correction",
    "withdrawal": "retraction",
}


@register_source
class EuropePmcSource(Source):
    """Europe PMC REST search adapter with core result type."""

    name = "europepmc"
    rate_limit = 5.0

    def lookup(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        if ref.doi:
            return self._query(f'DOI:"{ref.doi}"')
        if ref.pmid:
            return self._query(f"EXT_ID:{ref.pmid} AND SRC:MED")
        if ref.arxiv_id:
            return self._query(f"EXT_ID:{ref.arxiv_id} AND SRC:PPR")
        if ref.title:
            terms = f'TITLE:"{ref.title}"'
            if ref.authors:
                terms += f' AND AUTH:"{ref.authors[0]}"'
            return self._query(terms)
        return [], []

    def search(self, query: dict[str, Any]) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        return self._query(query.get("query") or "")

    def _query(self, terms: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not terms:
            return [], []
        url = (
            f"{REST}?query={urllib.parse.quote(terms)}"
            "&format=json&resultType=core&pageSize=5"
        )
        data, resp = self.client.fetch_json(url)
        evidence = [self._make_evidence(resp)]
        records: list[ResolvedRecord] = []
        if resp.ok:
            for item in (data.get("resultList") or {}).get("result") or []:
                if isinstance(item, dict):
                    records.append(self.from_json(item, resp))
        return records, evidence

    def _fetch_by_doi(self, doi: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._query(f'DOI:"{doi}"')

    def _fetch_by_pmid(self, pmid: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._query(f"EXT_ID:{pmid} AND SRC:MED")

    def _fetch_by_arxiv(self, arxiv_id: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._query(f"EXT_ID:{arxiv_id} AND SRC:PPR")

    def _fetch_by_isbn(self, isbn: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return [], []

    @staticmethod
    def from_json(data: dict[str, Any], response: Response) -> ResolvedRecord:
        authors = []
        for chunk in (data.get("authorString") or "").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if " " in chunk:
                family, given = chunk.split(" ", 1)
            else:
                family, given = chunk, ""
            authors.append({"family": family.strip(), "given": given.strip()})

        year = None
        pubdate = str(data.get("publicationDate") or data.get("pubYear") or "")
        if len(pubdate) >= 4 and pubdate[:4].isdigit():
            year = int(pubdate[:4])

        pages = data.get("pageInfo")

        integrity: dict[str, Any] = {"notices": []}
        pub_types = str(data.get("pubType") or "")
        lowered = pub_types.lower()
        for needle, kind in _NOTICE_KINDS.items():
            if needle in lowered:
                integrity["notices"].append({
                    "kind": kind,
                    "url": data.get("pmcid") or data.get("doi") or data.get("id", ""),
                    "label": pub_types,
                    "target": "work",
                    "source": "europepmc",
                })

        journal_info = data.get("journalInfo") or {}
        journal = journal_info.get("journal", {}).get("title") or data.get("journalTitle")

        body = response.body or b""
        return ResolvedRecord(
            source="europepmc",
            source_id=str(data.get("id", "")),
            title=data.get("title"),
            authors=authors,
            year=year,
            journal=journal,
            volume=data.get("volume"),
            issue=journal_info.get("issue"),
            pages=pages,
            doi=data.get("doi"),
            pmid=data.get("pmid"),
            document_type=("preprint" if data.get("src") == "PPR" else "article"),
            abstract=data.get("abstractText"),
            integrity=integrity,
            extra={
                "src": data.get("src"),
                "pmcid": data.get("pmcid"),
                "isOpenAccess": data.get("isOpenAccess"),
                "pubType": pub_types,
            },
            source_url=response.url,
            raw_sha256=hashlib.sha256(body).hexdigest() if body else None,
            raw_size=len(body),
        )
