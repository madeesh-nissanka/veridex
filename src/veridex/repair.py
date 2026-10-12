# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Repair utilities: suggest fixes and emit repaired bibliography files."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import AuditResult, ParsedReference, ResolvedRecord


def suggest_repairs(result: AuditResult) -> list[dict[str, Any]]:
    """Return list of suggested field repairs where parsed differs from best record.

    Only includes fields where a resolved record exists and the parsed value differs.
    Each repair dict has keys: field, old, new, source, source_url.
    """
    repairs: list[dict[str, Any]] = []
    if result.record is None or result.input is None:
        return repairs

    rec = result.record
    parsed = result.input

    rec = result.record
    parsed = result.input

    # Compare fields: title, authors, year, journal, volume, issue, pages, publisher, doi, url
    field_pairs = [
        ("title", parsed.title, rec.title),
        ("year", parsed.year, rec.year),
        ("journal", parsed.journal, rec.journal),
        ("volume", parsed.volume, rec.volume),
        ("issue", parsed.issue, rec.issue),
        ("pages", parsed.pages, rec.pages),
        ("publisher", parsed.publisher, rec.publisher),
        ("doi", parsed.doi, rec.doi),
        ("url", parsed.url, rec.url),
    ]

    for field, old_val, new_val in field_pairs:
        if old_val != new_val and new_val is not None:
            repairs.append(
                {
                    "field": field,
                    "old": old_val,
                    "new": new_val,
                    "source": rec.source,
                    "source_url": rec.source_url or "",
                }
            )

    # Authors comparison (list of strings vs list of dicts)
    parsed_authors = parsed.authors or []
    rec_authors = [a.get("family", "") for a in rec.authors if a.get("family")]
    if parsed_authors != rec_authors and rec_authors:
        repairs.append(
            {
                "field": "authors",
                "old": parsed_authors,
                "new": rec_authors,
                "source": rec.source,
                "source_url": rec.source_url or "",
            }
        )

    return repairs


def make_key(record: ResolvedRecord) -> str:
    """Generate a BibTeX-style citation key: family+year+first_title_word (v0.1 style)."""
    surnames = record.surnames()
    first_author = surnames[0] if surnames else "unknown"
    year = record.year or "nodate"
    title = record.title or "untitled"
    first_word = title.split()[0] if title.split() else "untitled"
    # Sanitize: keep alphanumeric only
    key = f"{first_author}{year}{first_word}"
    key = "".join(c for c in key if c.isalnum())
    return key


def _escape_bibtex(text: str) -> str:
    """Escape special characters for BibTeX."""
    # Order matters: backslash first to avoid double-escaping
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for ch, esc in replacements:
        text = text.replace(ch, esc)
    return text


def _format_authors_bibtex(authors: list[dict[str, str]]) -> str:
    """Format authors for BibTeX (Last, First and Last, First)."""
    if not authors:
        return ""
    parts = []
    for a in authors:
        family = a.get("family", "")
        given = a.get("given", "")
        if family and given:
            parts.append(f"{family}, {given}")
        elif family:
            parts.append(family)
        elif given:
            parts.append(given)
    return " and ".join(parts)


def _format_authors_ris(authors: list[dict[str, str]]) -> list[str]:
    """Format authors for RIS (one AU per author)."""
    out = []
    for a in authors:
        family = a.get("family", "")
        given = a.get("given", "")
        if family or given:
            out.append(f"{family}, {given}" if family and given else (family or given))
    return out


def build_bibtex(record: ResolvedRecord, key: str) -> str:
    """Build a BibTeX entry string from a ResolvedRecord."""
    lines = [f"@article{{{key},"]
    if record.title:
        lines.append(f"  title = {{{_escape_bibtex(record.title)}}},")
    authors_str = _format_authors_bibtex(record.authors)
    if authors_str:
        lines.append(f"  author = {{{authors_str}}},")
    if record.year:
        lines.append(f"  year = {{{record.year}}},")
    if record.journal:
        lines.append(f"  journal = {{{_escape_bibtex(record.journal)}}},")
    if record.volume:
        lines.append(f"  volume = {{{record.volume}}},")
    if record.issue:
        lines.append(f"  number = {{{record.issue}}},")
    if record.pages:
        lines.append(f"  pages = {{{record.pages}}},")
    if record.publisher:
        lines.append(f"  publisher = {{{_escape_bibtex(record.publisher)}}},")
    if record.doi:
        lines.append(f"  doi = {{{record.doi}}},")
    if record.url:
        lines.append(f"  url = {{{record.url}}},")
    lines.append("}")
    return "\n".join(lines)


def build_ris(record: ResolvedRecord) -> str:
    """Build a RIS entry string from a ResolvedRecord."""
    lines = ["TY  - JOUR"]
    if record.title:
        lines.append(f"TI  - {record.title}")
    for au in _format_authors_ris(record.authors):
        lines.append(f"AU  - {au}")
    if record.year:
        lines.append(f"PY  - {record.year}")
    if record.journal:
        lines.append(f"JO  - {record.journal}")
    if record.volume:
        lines.append(f"VL  - {record.volume}")
    if record.issue:
        lines.append(f"IS  - {record.issue}")
    if record.pages:
        lines.append(f"SP  - {record.pages.split('-')[0] if '-' in record.pages else record.pages}")
        if "-" in record.pages:
            lines.append(f"EP  - {record.pages.split('-')[1]}")
    if record.publisher:
        lines.append(f"PB  - {record.publisher}")
    if record.doi:
        lines.append(f"DO  - {record.doi}")
    if record.url:
        lines.append(f"UR  - {record.url}")
    if record.abstract:
        lines.append(f"AB  - {record.abstract}")
    lines.append("ER  - ")
    return "\n".join(lines)


def build_csljson(record: ResolvedRecord) -> dict[str, Any]:
    """Build a CSL-JSON object from a ResolvedRecord."""
    csl: dict[str, Any] = {"type": "article-journal"}
    if record.title:
        csl["title"] = record.title
    if record.authors:
        csl["author"] = [
            {"family": a.get("family", ""), "given": a.get("given", "")}
            for a in record.authors
            if a.get("family") or a.get("given")
        ]
    if record.year:
        csl["issued"] = {"date-parts": [[record.year]]}
    if record.journal:
        csl["container-title"] = record.journal
    if record.volume:
        csl["volume"] = record.volume
    if record.issue:
        csl["issue"] = record.issue
    if record.pages:
        csl["page"] = record.pages
    if record.publisher:
        csl["publisher"] = record.publisher
    if record.doi:
        csl["DOI"] = record.doi
    if record.url:
        csl["URL"] = record.url
    if record.abstract:
        csl["abstract"] = record.abstract
    return csl


def _next_path(path: Path, force: bool) -> Path:
    """Return the path to write to, adding .1 suffix if exists and not force."""
    if not path.exists() or force:
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        new_path = parent / f"{stem}.{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def write_repairs(
    results: list[AuditResult],
    out_dir: str | os.PathLike[str],
    force: bool = False,
) -> dict[str, str]:
    """Write repaired bibliography files and a repair log.

    Creates: repaired.bib, repaired.ris, repaired.csl.json, repair_log.json
    Returns dict mapping format name to written file path.
    Never modifies input files. Refuses to overwrite unless force=True.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Determine output paths with suffix handling
    bib_path = _next_path(out_path / "repaired.bib", force)
    ris_path = _next_path(out_path / "repaired.ris", force)
    csl_path = _next_path(out_path / "repaired.csl.json", force)
    log_path = _next_path(out_path / "repair_log.json", force)

    bib_entries: list[str] = []
    ris_entries: list[str] = []
    csl_entries: list[dict[str, Any]] = []
    log_entries: list[dict[str, Any]] = []

    for result in results:
        if result.record is None or result.input is None:
            continue

        key = make_key(result.record)
        repairs = suggest_repairs(result)

        # Build output formats
        bib_entries.append(build_bibtex(result.record, key))
        ris_entries.append(build_ris(result.record))
        csl_entries.append(build_csljson(result.record))

        # Log each repair with ledger key info
        for repair in repairs:
            log_entries.append(
                {
                    "entry_index": result.index,
                    "field": repair["field"],
                    "old": repair["old"],
                    "new": repair["new"],
                    "source": repair["source"],
                    "evidence_url": repair["source_url"],
                    "ledger_key": f"{result.index}:{repair['field']}",
                }
            )

    # Write files
    if bib_entries:
        bib_path.write_text("\n\n".join(bib_entries) + "\n", encoding="utf-8")
    if ris_entries:
        ris_path.write_text("\n\n".join(ris_entries) + "\n", encoding="utf-8")
    if csl_entries:
        csl_path.write_text(json.dumps(csl_entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if log_entries:
        log_path.write_text(json.dumps(log_entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "bib": str(bib_path),
        "ris": str(ris_path),
        "csljson": str(csl_path),
        "log": str(log_path),
    }


__all__ = [
    "suggest_repairs",
    "make_key",
    "build_bibtex",
    "build_ris",
    "build_csljson",
    "write_repairs",
]