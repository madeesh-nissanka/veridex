# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Plain text reference parser. Handles numbered lists, author-year lines, free-text paragraphs,
and identifier-only lines (DOI/URL/PMID/arXiv/ISBN). Ports v0.1 parse_text_line behavior as one strategy."""
from __future__ import annotations

import re
from typing import Any

from veridex.models import ParsedReference
from veridex.ids import (
    extract_identifiers,
    looks_like_identifier_only,
    find_doi,
    find_url,
    find_pmid,
    find_arxiv_id,
    find_isbn,
)

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9<>]+\b")
YEAR_RE = re.compile(r"\b(19|20)\d{2}[a-z]?\b")
NUMBERED_RE = re.compile(r"^(\[\d+\]|\d+\.)\s*(.+)$")
AY_PAREN_RE = re.compile(r"^(.+?)\s*[\(\[](\d{4})[a-z]?[\)\]]\s*(.*)$")
AY_COMMA_RE = re.compile(r"^(.+?),\s*(\d{4})[a-z]?\s+(.*)$")


def _clean_doi(doi: str | None) -> str | None:
    """Clean DOI from v0.1 parse_text_line."""
    if not doi:
        return None
    doi = doi.strip()
    if doi.lower().startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]
    if doi.lower().startswith("doi:"):
        doi = doi[4:]
    doi = doi.rstrip(".,;: ")
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1].rstrip(".,;: ")
    return doi or None


def _extract_year(text: str) -> int | None:
    """Extract year from text."""
    match = YEAR_RE.search(text)
    if match:
        try:
            return int(match.group(0)[:4])
        except ValueError:
            pass
    return None


def _extract_first_author(text: str) -> str | None:
    """Extract first author surname from text."""
    match = re.match(r"(?:\[?\d+\]?\s*)?([A-Z][A-Za-z\-']+(?:,\s*[A-Z]\.?(?:\s*[A-Z]\.?)?)?)", text)
    if match:
        name = match.group(1)
        if "," in name:
            return name.split(",")[0].strip()
        return name
    return None


def _extract_title_v01(text: str) -> str | None:
    """Port of v0.1 title extraction logic from parse_text_line."""
    doi_match = DOI_RE.search(text)
    if doi_match:
        before_doi = text[:doi_match.start()]
    else:
        before_doi = text

    ym = re.search(r"\((?:19|20)\d{2}[a-z]?\)\.?\s*", before_doi)
    if ym:
        rest = before_doi[ym.end():]
        tm = re.match(r"(.+?)\.\s+(?=[A-Z\"'])", rest)
        title = (tm.group(1) if tm else rest.rstrip(". ")).strip() or None
    else:
        title_match = re.search(r"[.)]\s*([A-Z][^.]{10,}?)\.", before_doi)
        title = title_match.group(1).strip() if title_match else None
    return title


def _parse_numbered_line(line: str, index: int, source_file: str | None) -> ParsedReference | None:
    """Parse a numbered list line like '[1] ...' or '1. ...'."""
    match = NUMBERED_RE.match(line.strip())
    if not match:
        return None
    content = match.group(2).strip()
    if not content:
        return None

    ref = ParsedReference(
        index=index,
        raw=line.strip(),
        format="text",
        source_file=source_file,
    )

    ids = extract_identifiers(content)
    ref.doi = ids.get("doi")
    ref.pmid = ids.get("pmid")
    ref.arxiv_id = ids.get("arxiv_id")
    ref.isbn = ids.get("isbn")
    ref.url = ids.get("url")

    ref.year = _extract_year(content)
    ref.authors = [_extract_first_author(content)] if _extract_first_author(content) else []
    ref.title = _extract_title_v01(content)

    return ref


def _tidy_author(author: str, paren_mode: bool) -> str:
    """Normalize author capture. In paren mode drop a trailing single-letter
    initial ('Brown A' -> 'Brown') unless the name is comma-formatted."""
    author = author.strip().rstrip(",").strip()
    if paren_mode and "," not in author:
        tokens = author.split()
        if len(tokens) > 1 and len(tokens[-1]) <= 2 and tokens[-1][0].isupper():
            return " ".join(tokens[:-1])
    return author


def _parse_author_year_line(line: str, index: int, source_file: str | None) -> ParsedReference | None:
    """Parse an author-year line like 'Smith, J. (2020) ...' or 'Jones M, 2021 ...'."""
    stripped = line.strip()
    paren = False
    match = AY_PAREN_RE.match(stripped)
    if not match:
        match = AY_COMMA_RE.match(stripped)
    if not match:
        return None

    author_raw = match.group(1).strip()
    year_str = match.group(2)
    rest = match.group(3).strip() if match.group(3) else ""

    if not re.fullmatch(r"[A-Z][A-Za-z\-']+(?:[,.\s]+[A-Z][A-Za-z\-']*(?:\.)?)*", author_raw):
        return None

    author = _tidy_author(author_raw, paren_mode=stripped[len(author_raw):].lstrip().startswith("(") or stripped[len(author_raw):].lstrip().startswith("["))

    ref = ParsedReference(
        index=index,
        raw=stripped,
        format="text",
        source_file=source_file,
    )

    ids = extract_identifiers(stripped)
    ref.doi = ids.get("doi")
    ref.pmid = ids.get("pmid")
    ref.arxiv_id = ids.get("arxiv_id")
    ref.isbn = ids.get("isbn")
    ref.url = ids.get("url")

    try:
        ref.year = int(year_str[:4])
    except (ValueError, TypeError):
        ref.year = _extract_year(stripped)

    if author:
        ref.authors = [author]

    ref.title = _extract_title_v01(stripped) or (rest.rstrip(". ") if rest else None)

    return ref


def _parse_identifier_only_line(line: str, index: int, source_file: str | None) -> ParsedReference | None:
    """Parse a line that contains only an identifier (DOI/URL/PMID/arXiv/ISBN)."""
    if not looks_like_identifier_only(line):
        return None

    ref = ParsedReference(
        index=index,
        raw=line.strip(),
        format="text",
        source_file=source_file,
    )

    ids = extract_identifiers(line)
    ref.doi = ids.get("doi")
    ref.pmid = ids.get("pmid")
    ref.arxiv_id = ids.get("arxiv_id")
    ref.isbn = ids.get("isbn")
    ref.url = ids.get("url")

    return ref


def _parse_free_text_line(line: str, index: int, source_file: str | None) -> ParsedReference | None:
    """Parse a free-text paragraph line using v0.1 parse_text_line behavior."""
    line = line.strip()
    if not line:
        return None

    ref = ParsedReference(
        index=index,
        raw=line,
        format="text",
        source_file=source_file,
    )

    ids = extract_identifiers(line)
    ref.doi = ids.get("doi")
    ref.pmid = ids.get("pmid")
    ref.arxiv_id = ids.get("arxiv_id")
    ref.isbn = ids.get("isbn")
    ref.url = ids.get("url")

    ref.year = _extract_year(line)
    ref.authors = [_extract_first_author(line)] if _extract_first_author(line) else []
    ref.title = _extract_title_v01(line) or line.rstrip(". ")

    return ref


def parse_plain(text: str, source_file: str | None = None) -> list[ParsedReference]:
    """Parse plain text references into list of ParsedReference.

    Strategies applied in order:
    1. Numbered lists: '[1] ...' or '1. ...'
    2. Author-year lines: 'Smith (2020) ...' or 'Smith, 2020 ...'
    3. Identifier-only lines: lines that are only DOI/URL/PMID/arXiv/ISBN
    4. Free-text paragraphs: v0.1 parse_text_line behavior as fallback
    """
    if not text or not text.strip():
        return []

    lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    refs: list[ParsedReference] = []
    index = 0

    for line in lines:
        parsed = None

        parsed = _parse_identifier_only_line(line, index, source_file)
        if parsed:
            refs.append(parsed)
            index += 1
            continue

        parsed = _parse_numbered_line(line, index, source_file)
        if parsed:
            refs.append(parsed)
            index += 1
            continue

        parsed = _parse_author_year_line(line, index, source_file)
        if parsed:
            refs.append(parsed)
            index += 1
            continue

        parsed = _parse_free_text_line(line, index, source_file)
        if parsed:
            refs.append(parsed)
            index += 1
            continue

    return refs