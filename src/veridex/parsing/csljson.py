# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""CSL JSON parser: array or single object; author [{family,given}]; issued date-parts; container-title; page/volume/issue; DOI/URL id."""
from __future__ import annotations

import json
import re
from typing import Any

from veridex.models import ParsedReference
from veridex.ids import extract_identifiers, find_doi, clean_doi


def _clean_value(val: str) -> str:
    if not val:
        return ""
    val = val.strip()
    val = re.sub(r"\s+", " ", val)
    return val


def _parse_authors(author_list: list[dict[str, Any]]) -> list[str]:
    authors = []
    for author in author_list or []:
        if not isinstance(author, dict):
            continue
        family = author.get("family", "")
        given = author.get("given", "")
        if family and given:
            authors.append(f"{family}, {given}")
        elif family:
            authors.append(family)
        elif given:
            authors.append(given)
    return authors


def _parse_year(issued: dict[str, Any] | None) -> int | None:
    if not issued:
        return None
    date_parts = issued.get("date-parts")
    if not date_parts or not isinstance(date_parts, list) or not date_parts[0]:
        return None
    first_part = date_parts[0]
    if not first_part or not isinstance(first_part, list):
        return None
    try:
        year = int(first_part[0])
        if 1000 <= year <= 2100:
            return year
    except (ValueError, TypeError, IndexError):
        pass
    return None


def _get_first(items: Any) -> str | None:
    """First usable string from a scalar, list, or {'name': ...} dict."""
    if items is None:
        return None
    if isinstance(items, str):
        return items or None
    if isinstance(items, (int, float)):
        return str(items)
    if isinstance(items, dict):
        name = items.get("name") or items.get("literal")
        return str(name) if name else None
    if isinstance(items, list):
        for item in items:
            val = _get_first(item)
            if val:
                return val
    return None


def _text(item: dict[str, Any], key: str) -> str | None:
    val = _get_first(item.get(key))
    if val is None:
        return None
    val = _clean_value(val)
    return val or None


def _extract_doi_from_ids(ids: dict[str, str] | None) -> str | None:
    if not ids:
        return None
    for key, val in ids.items():
        if key.lower() in ("doi", "DOI"):
            return find_doi(str(val))
    return None


def parse_csljson(text: str, source_file: str | None = None) -> list[ParsedReference]:
    """Parse CSL JSON text into list of ParsedReference."""
    if not text or not text.strip():
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = data
    else:
        return []

    refs: list[ParsedReference] = []
    index = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        raw_fields: dict[str, str] = {}
        for key, val in item.items():
            if isinstance(val, (str, int, float)):
                raw_fields[key] = str(val)
            elif isinstance(val, list):
                raw_fields[key] = json.dumps(val)
            elif isinstance(val, dict):
                raw_fields[key] = json.dumps(val)

        ref = ParsedReference(
            index=index,
            raw=json.dumps(item),
            format="csl-json",
            source_file=source_file,
            raw_fields=raw_fields,
        )

        ref.title = _text(item, "title")
        ref.authors = _parse_authors(item.get("author"))
        ref.year = _parse_year(item.get("issued"))
        ref.journal = _text(item, "container-title")
        ref.volume = _text(item, "volume")
        ref.issue = _text(item, "issue")
        ref.pages = _text(item, "page")
        ref.publisher = _text(item, "publisher")
        ref.doi = clean_doi(_text(item, "DOI"))
        ref.url = _text(item, "URL")

        if not ref.doi:
            for cand in (item.get("id"), item.get("URL"), item.get("url"), item.get("eprint")):
                if isinstance(cand, str):
                    doi = find_doi(cand)
                    if doi:
                        ref.doi = doi
                        break
        if not ref.doi:
            ids = extract_identifiers(" ".join(filter(None, [
                ref.title or "",
                " ".join(ref.authors),
                str(ref.year) if ref.year else "",
                ref.journal or "",
                ref.volume or "",
                ref.issue or "",
                ref.pages or "",
                item.get("id") if isinstance(item.get("id"), str) else "",
            ])))
            ref.doi = ids.get("doi")
            ref.pmid = ids.get("pmid")
            ref.arxiv_id = ids.get("arxiv_id")
            ref.isbn = ids.get("isbn")
            if not ref.url:
                ref.url = ids.get("url")

        refs.append(ref)
        index += 1

    return refs