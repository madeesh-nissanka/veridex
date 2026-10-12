# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""arXiv Atom API resolver adapter (stdlib xml parsing). Stdlib only."""
from __future__ import annotations

import hashlib
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

from veridex.httpclient import HttpClient, Response
from veridex.models import Evidence, ParsedReference, ResolvedRecord
from veridex.resolvers import Source, register_source

QUERY_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


@register_source
class ArxivSource(Source):
    """arXiv search adapter returning preprint records (latest version)."""

    name = "arxiv"
    rate_limit = 1.0

    def lookup(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        if ref.arxiv_id:
            return self._query(f"id_list={urllib.parse.quote(ref.arxiv_id)}")
        if ref.doi:
            return self._query(
                f"search_query=doi:{urllib.parse.quote(ref.doi)}&max_results=5"
            )
        if ref.title:
            return self.search({"query": ref.title})
        return [], []

    def search(self, query: dict[str, Any]) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        terms = query.get("query") or ""
        if not terms:
            return [], []
        return self._query(
            f"search_query=ti:{urllib.parse.quote(terms)}&max_results=5"
        )

    def _query(self, params: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        url = f"{QUERY_URL}?{params}"
        resp = self.client.get(url)
        evidence = [self._make_evidence(resp)]
        if not resp.ok:
            return [], evidence
        try:
            root = ET.fromstring(resp.body.decode("utf-8"))
        except ET.ParseError:
            return [], evidence
        records = [self._entry_from_xml(entry, resp) for entry in root.findall(f"{ATOM}entry")]
        return records, evidence

    @staticmethod
    def _entry_from_xml(entry: ET.Element, response: Response) -> ResolvedRecord:
        raw_id = _clean((entry.findtext(f"{ATOM}id") or ""))
        arxiv_id = raw_id.rsplit("/", 1)[-1]
        title = _clean(entry.findtext(f"{ATOM}title"))
        summary = _clean(entry.findtext(f"{ATOM}summary"))
        published = _clean(entry.findtext(f"{ATOM}published"))
        year = None
        if len(published) >= 4 and published[:4].isdigit():
            year = int(published[:4])

        authors = []
        for a in entry.findall(f"{ATOM}author"):
            name = _clean(a.findtext(f"{ATOM}name"))
            if not name:
                continue
            family = name.split(" ")[-1]
            given = " ".join(name.split(" ")[:-1])
            authors.append({"family": family, "given": given})

        doi = entry.findtext(f"{ARXIV_NS}doi")
        journal_ref = entry.findtext(f"{ARXIV_NS}journal_ref")
        primary = entry.find(f"{ARXIV_NS}primary_category")
        subject = primary.get("term") if primary is not None else None

        body = response.body or b""
        return ResolvedRecord(
            source="arxiv",
            source_id=arxiv_id,
            title=title or None,
            authors=authors,
            year=year,
            journal=journal_ref or None,
            doi=_clean(doi) or None,
            arxiv_id=arxiv_id,
            document_type="preprint",
            abstract=summary or None,
            extra={"subject": subject, "published": published, "raw_id": raw_id},
            source_url=response.url,
            raw_sha256=hashlib.sha256(body).hexdigest() if body else None,
            raw_size=len(body),
        )

    def _fetch_by_doi(self, doi: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._query(f"search_query=doi:{urllib.parse.quote(doi)}&max_results=5")

    def _fetch_by_pmid(self, pmid: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._query(f"search_query=pmid:{urllib.parse.quote(pmid)}&max_results=5")

    def _fetch_by_arxiv(self, arxiv_id: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._query(f"id_list={urllib.parse.quote(arxiv_id)}")

    def _fetch_by_isbn(self, isbn: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return [], []

    @staticmethod
    def from_json(data: dict[str, Any], response: Response) -> ResolvedRecord:
        """arXiv returns Atom XML, not JSON; route through _entry_from_xml."""
        return ArxivSource._entry_from_xml(data, response)  # type: ignore[arg-type]
