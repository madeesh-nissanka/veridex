# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Identifier extraction and cleaning (DOI, URL, PMID, arXiv, ISBN). Stdlib only."""
from __future__ import annotations

import re

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9<>]+\b")
DOI_URL_PREFIX = "https://doi.org/"
URL_RE = re.compile(r"https?://[^\s<>\[\](){}\"']+", re.IGNORECASE)
PMID_RE = re.compile(
    r"(?:\bpmid[:\s]*|https?://pubmed\.ncbi\.nlm\.nih\.gov/)(\d{2,9})\b",
    re.IGNORECASE,
)
ARXIV_RE = re.compile(
    r"(?:arxiv[:\s]*(?:abs|pdf)?/?|https?://arxiv\.org/(?:abs|pdf)/)"
    r"((?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?))",
    re.IGNORECASE,
)
ISBN_RE = re.compile(r"\b(?:isbn[:\s]*)?(97[89][- ]?(?:\d[- ]?){9,10}|\d{9}[- ]?[0-9Xx])\b", re.IGNORECASE)


def clean_doi(doi: str | None) -> str | None:
    """Strip DOI/URL prefixes and trailing punctuation, keep balanced parentheses."""
    if not doi:
        return None
    doi = doi.strip()
    if doi.lower().startswith(DOI_URL_PREFIX):
        doi = doi[len(DOI_URL_PREFIX):]
    if doi.lower().startswith("doi:"):
        doi = doi[4:]
    doi = doi.rstrip(".,;: ")
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1].rstrip(".,;: ")
    return doi or None


def is_valid_doi_format(doi: str | None) -> bool:
    """True when the string matches the numeric-suffix DOI syntax."""
    return bool(doi and DOI_RE.fullmatch(doi.strip()))


def find_doi(text: str) -> str | None:
    """First DOI-looking substring, cleaned; None if absent."""
    match = DOI_RE.search(text or "")
    return clean_doi(match.group(0)) if match else None


def find_url(text: str) -> str | None:
    """First http(s) URL substring, quotes stripped."""
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip("'\",")


def find_pmid(text: str) -> str | None:
    match = PMID_RE.search(text or "")
    return match.group(1) if match else None


def find_arxiv_id(text: str) -> str | None:
    match = ARXIV_RE.search(text or "")
    return match.group(1) if match else None


def normalize_isbn(isbn: str | None) -> str | None:
    """Return digits-only ISBN (10 or 13), validating the check digit."""
    if not isbn:
        return None
    digits = re.sub(r"[^0-9Xx]", "", isbn.strip())
    if len(digits) == 10:
        return _isbn10(digits)
    if len(digits) == 13:
        return _isbn13(digits)
    return None


def _isbn10(digits: str) -> str | None:
    if len(digits) != 10 or not re.fullmatch(r"\d{9}[0-9Xx]", digits):
        return None
    total = sum((10 - i) * (10 if d in "Xx" else int(d)) for i, d in enumerate(digits))
    return digits.upper() if total % 11 == 0 else None


def _isbn13(digits: str) -> str | None:
    if len(digits) != 13 or not digits.isdigit():
        return None
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits))
    return digits if total % 10 == 0 else None


def find_isbn(text: str) -> str | None:
    for match in ISBN_RE.finditer(text or ""):
        candidate = normalize_isbn(match.group(0))
        if candidate:
            return candidate
    return None


def extract_identifiers(text: str) -> dict[str, str | None]:
    """All machine identifiers present in one string."""
    return {
        "doi": find_doi(text),
        "pmid": find_pmid(text),
        "arxiv_id": find_arxiv_id(text),
        "isbn": find_isbn(text),
        "url": find_url(text),
    }


def looks_like_identifier_only(text: str) -> bool:
    """True when the line is essentially just a DOI/URL/PMID/arXiv/ISBN."""
    text = (text or "").strip()
    if not text:
        return False
    ids = extract_identifiers(text)
    residue = text
    for key in ("doi", "pmid", "arxiv_id", "isbn", "url"):
        value = ids[key]
        if value:
            residue = residue.replace(value, "", 1)
    residue = re.sub(r"^(?:\[?\d+\]?|doi|pmid|isbn|arxiv|:|\s|[.,;])+$", "", residue, flags=re.IGNORECASE)
    return residue == "" and any(ids.values())
