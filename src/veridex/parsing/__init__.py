# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Reference parsing module. Supports BibTeX, RIS, CSL JSON, EndNote XML,
plain text, and DOCX formats."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from veridex.models import ParsedReference
from veridex.parsing import bibtex, ris, csljson, endnote, plain, docx

__all__ = [
    "parse_file",
    "parse_text",
    "detect_format",
    "ParsedReference",
]

_FORMAT_ALIASES = {
    "bibtex": "bib",
    "csljson": "csl-json",
    "csl-json": "csl-json",
    "endnote-xml": "endnote",
    "endnote": "endnote",
    "ris": "ris",
    "text": "text",
    "plain": "text",
    "dois": "text",
    "docx": "docx",
}

_SUPPORTED_FORMATS = {"auto", "bib", "ris", "csl-json", "endnote", "text", "dois", "docx"}


def detect_format(path: str | None, text: str) -> str:
    """Detect reference format from file extension and/or content."""
    if path:
        ext = Path(path).suffix.lower()
        if ext in (".bib", ".bibtex"):
            return "bib"
        if ext in (".ris",):
            return "ris"
        if ext in (".json", ".csl.json", ".csljson"):
            return "csl-json"
        if ext in (".xml", ".enw", ".endnote"):
            return "endnote"
        if ext in (".docx",):
            return "docx"
        if ext in (".txt", ".text", ".refs", ".references"):
            return "text"

    t = text.lstrip()
    if not t:
        return "text"

    if t.startswith("@"):
        return "bib"
    if t.startswith("TY  -"):
        return "ris"
    if t.startswith("<?xml") or t.startswith("<xml"):
        if "EndNote" in t[:500] or "endnote" in t[:500].lower():
            return "endnote"
    if t.startswith("[") or t[0].isdigit():
        if re.match(r"^\[\d+\]|^\d+\.", t):
            return "text"
    if t.startswith("{") or t.startswith("["):
        try:
            data = json.loads(t)
            if isinstance(data, list) and data and isinstance(data[0], dict):
                if any(k in data[0] for k in ("title", "author", "container-title", "DOI", "issued")):
                    return "csl-json"
        except json.JSONDecodeError:
            pass
    if re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9<>]+\b", t):
        return "text"

    return "text"


def _normalize_fmt(fmt: str) -> str:
    fmt = fmt.strip().lower()
    if fmt in _FORMAT_ALIASES:
        return _FORMAT_ALIASES[fmt]
    if fmt in _SUPPORTED_FORMATS:
        return fmt
    if fmt == "auto":
        return "auto"
    return "text"


def _dispatch_parse(text: str, fmt: str, source_file: str | None = None) -> list[ParsedReference]:
    if fmt == "bib":
        return bibtex.parse_bibtex(text, source_file=source_file)
    if fmt == "ris":
        return ris.parse_ris(text, source_file=source_file)
    if fmt == "csl-json":
        return csljson.parse_csljson(text, source_file=source_file)
    if fmt == "endnote":
        return endnote.parse_endnote(text, source_file=source_file)
    if fmt in ("text", "dois"):
        return plain.parse_plain(text, source_file=source_file)
    if fmt == "docx":
        return docx.parse_docx(text, source_file=source_file)
    return plain.parse_plain(text, source_file=source_file)


def parse_text(text: str, fmt: str = "auto") -> list[ParsedReference]:
    """Parse reference text in the specified format.

    Args:
        text: Reference text to parse.
        fmt: Format name ("auto", "bib", "ris", "csl-json", "endnote", "text", "dois", "docx").

    Returns:
        List of ParsedReference objects.
    """
    if not text or not text.strip():
        return []

    normalized = _normalize_fmt(fmt)
    if normalized == "auto":
        normalized = detect_format(None, text)

    return _dispatch_parse(text, normalized, source_file=None)


def parse_file(path: str, fmt: str = "auto") -> list[ParsedReference]:
    """Parse references from a file.

    Args:
        path: Path to the reference file.
        fmt: Format name ("auto", "bib", "ris", "csl-json", "endnote", "text", "dois", "docx").

    Returns:
        List of ParsedReference objects.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if fmt == "docx" or p.suffix.lower() == ".docx":
        return docx.parse_docx_file(path)

    text = p.read_text(encoding="utf-8", errors="replace")

    normalized = _normalize_fmt(fmt)
    if normalized == "auto":
        normalized = detect_format(path, text)

    return _dispatch_parse(text, normalized, source_file=path)