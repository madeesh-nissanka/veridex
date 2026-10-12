# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""OpenLibrary resolver adapter (ISBN-first). Stdlib only."""
from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any

from veridex.httpclient import HttpClient, Response
from veridex.models import Evidence, ParsedReference, ResolvedRecord
from veridex.resolvers import Source, register_source

BASE = "https://openlibrary.org"


@register_source
class OpenLibrarySource(Source):
    """OpenLibrary books adapter: ISBN lookup and title/author search."""

    name = "openlibrary"
    rate_limit = 1.0

    def lookup(self, ref: ParsedReference) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        if ref.isbn:
            return self._fetch_isbn(ref.isbn)
        if ref.title:
            return self.search({"query": ref.title, "author": (ref.authors or [""])[0]})
        return [], []

    def search(self, query: dict[str, Any]) -> tuple[list[ResolvedRecord], list[Evidence]]:
        if not self.opts.enabled:
            return [], []
        params = {"limit": 5}
        if query.get("query"):
            params["title"] = query["query"]
        if query.get("author"):
            params["author"] = query["author"]
        if query.get("year"):
            params["publish_year"] = query["year"]
        if "title" not in params and "author" not in params:
            return [], []
        url = f"{BASE}/search.json?{urllib.parse.urlencode(params)}"
        data, resp = self.client.fetch_json(url)
        evidence = [self._make_evidence(resp)]
        records: list[ResolvedRecord] = []
        if resp.ok:
            for item in (data.get("docs") or [])[:5]:
                if isinstance(item, dict):
                    records.append(self.from_json(item, resp))
        return records, evidence

    def _fetch_isbn(self, isbn: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        digits = "".join(c for c in isbn if c.isdigit() or c in "Xx")
        url = f"{BASE}/isbn/{digits}.json"
        data, resp = self.client.fetch_json(url)
        ev = [self._make_evidence(resp)]
        if not resp.ok or not data:
            return [], ev
        data = dict(data)
        data["_isbn"] = digits
        return [self.from_json(data, resp)], ev

    def _fetch_by_doi(self, doi: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return [], []

    def _fetch_by_pmid(self, pmid: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return [], []

    def _fetch_by_arxiv(self, arxiv_id: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return [], []

    def _fetch_by_isbn(self, isbn: str) -> tuple[list[ResolvedRecord], list[Evidence]]:
        return self._fetch_isbn(isbn)

    @staticmethod
    def from_json(data: dict[str, Any], response: Response) -> ResolvedRecord:
        title = data.get("title")
        authors = []
        for a in data.get("authors") or []:
            if isinstance(a, dict):
                name = a.get("name") or ""
            else:
                name = str(a).rstrip("/").rsplit("/", 1)[-1]
            if name:
                authors.append({"family": name, "given": ""})

        year = None
        publish_date = str(data.get("publish_date") or "")
        parts = publish_date.split()
        for part in parts:
            if len(part) == 4 and part.isdigit():
                year = int(part)
                break
        if year is None and data.get("first_publish_year"):
            try:
                year = int(data["first_publish_year"])
            except (TypeError, ValueError):
                year = None

        publishers = data.get("publishers") or []
        publisher = publishers[0].get("name") if publishers and isinstance(publishers[0], dict) else (
            str(publishers[0]) if publishers else None
        )

        isbn = data.get("_isbn")
        if not isbn:
            isbns = data.get("isbn") or data.get("isbn_13") or []
            if isinstance(isbns, list) and isbns:
                isbn = str(isbns[0])
        if isinstance(isbn, list):
            isbn = str(isbn[0]) if isbn else None

        body = response.body or b""
        return ResolvedRecord(
            source="openlibrary",
            source_id=str(data.get("key") or isbn or ""),
            title=title,
            authors=authors,
            year=year,
            publisher=publisher,
            isbn=isbn,
            document_type="book",
            extra={
                "number_of_pages": data.get("number_of_pages_median") or data.get("number_of_pages"),
                "subject_count": data.get("subject_count"),
            },
            source_url=response.url,
            raw_sha256=hashlib.sha256(body).hexdigest() if body else None,
            raw_size=len(body),
        )
