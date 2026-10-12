# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""EndNote XML parser via xml.etree.ElementTree (Export-Xml records:
authors/author name-list, titles, electronic-public-datum DOI, dates year)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from veridex.models import ParsedReference
from veridex.ids import extract_identifiers, find_doi


def _clean_value(val: str) -> str:
    if not val:
        return ""
    val = val.strip()
    val = re.sub(r"\s+", " ", val)
    return val


def _parse_year(year_str: str) -> int | None:
    if not year_str:
        return None
    match = re.search(r"\b(1\d{3}|2\d{3})\b", year_str)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def _parse_authors(elem: ET.Element) -> list[str]:
    authors = []
    for author_elem in elem.findall(".//author"):
        name_parts = []
        for name_elem in author_elem.findall("name"):
            name_text = name_elem.text or ""
            if name_text.strip():
                name_parts.append(name_text.strip())
        if name_parts:
            authors.append(" ".join(name_parts))
    return authors


def _get_text(elem: ET.Element, *paths: str) -> str | None:
    for path in paths:
        found = elem.find(path)
        if found is not None and found.text:
            return _clean_value(found.text)
    return None


def _get_all_text(elem: ET.Element, *paths: str) -> list[str]:
    results = []
    for path in paths:
        for found in elem.findall(path):
            if found is not None and found.text:
                results.append(_clean_value(found.text))
    return results


def parse_endnote(text: str, source_file: str | None = None) -> list[ParsedReference]:
    """Parse EndNote XML text into list of ParsedReference."""
    if not text or not text.strip():
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    refs: list[ParsedReference] = []
    index = 0

    for record in root.findall(".//record"):
        raw_xml = ET.tostring(record, encoding="unicode")

        ref = ParsedReference(
            index=index,
            raw=raw_xml,
            format="endnote",
            source_file=source_file,
        )

        ref.authors = _parse_authors(record)

        ref.title = _get_text(record, "titles/title", "title")

        ref.journal = _get_text(record, "periodical/full-title", "periodical/title", "journal")

        ref.volume = _get_text(record, "volume")

        ref.issue = _get_text(record, "number")

        ref.pages = _get_text(record, "pages")

        ref.publisher = _get_text(record, "publisher")

        year_str = _get_text(record, "dates/year", "year")
        ref.year = _parse_year(year_str)

        doi = None
        for epd in record.findall(".//electronic-public-datum"):
            doi_candidate = find_doi(epd.text or "")
            if doi_candidate:
                doi = doi_candidate
                break
        if not doi:
            for url_elem in record.findall(".//urls/url"):
                doi_candidate = find_doi(url_elem.text or "")
                if doi_candidate:
                    doi = doi_candidate
                    break
        ref.doi = doi

        all_text_parts = filter(None, [
            ref.title,
            " ".join(ref.authors),
            str(ref.year) if ref.year else "",
            ref.journal,
            ref.volume,
            ref.issue,
            ref.pages,
        ])
        extra_parts = []
        for tag in ("electronic-public-datum", "electronic-resource-num"):
            for elem in record.findall(f".//{tag}"):
                if elem.text:
                    extra_parts.append(elem.text)
        for url_elem in record.findall(".//urls/url"):
            if url_elem.text:
                extra_parts.append(url_elem.text)
        all_text = " ".join(list(all_text_parts) + extra_parts)

        ids = extract_identifiers(all_text)
        if not ref.doi:
            ref.doi = ids.get("doi")
        ref.pmid = ref.pmid or ids.get("pmid")
        ref.arxiv_id = ref.arxiv_id or ids.get("arxiv_id")
        ref.isbn = ref.isbn or ids.get("isbn")
        ref.url = ref.url or ids.get("url")

        ref.raw_fields = {
            k: v for k, v in [
                ("authors", "; ".join(ref.authors)),
                ("title", ref.title or ""),
                ("journal", ref.journal or ""),
                ("year", str(ref.year) if ref.year else ""),
                ("volume", ref.volume or ""),
                ("issue", ref.issue or ""),
                ("pages", ref.pages or ""),
                ("publisher", ref.publisher or ""),
            ] if v
        }

        refs.append(ref)
        index += 1

    return refs