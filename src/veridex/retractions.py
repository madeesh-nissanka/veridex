# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Offline retraction / correction data loading (stdlib only).

Lets VERIDEX flag retracted or corrected works without network access, from
files the user supplies:

* **Retraction Watch CSV export** (columns such as ``Original Paper DOI``,
  ``Retraction DOI``, ``Reason``, ``RetractionDate``/``Retraction Date`` and
  ``RetractionNature``).
* **Crossref update JSON** (an ``items`` array or a bare list of records with a
  ``DOI``/``update-to`` relation and an ``update-type``).
* **JSONL** — one JSON object per line, each with a ``doi`` field.

Everything is normalised to a mapping of DOI -> list of notices. Notices have
the same shape as the ones produced by :mod:`veridex.integrity`, so they flow
through the existing integrity/report machinery unchanged.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .ids import clean_doi

# Column names (lower-cased) that may hold the DOI of the affected work.
_DOI_COLUMNS = (
    "original paper doi",
    "originalpaperdoi",
    "original_doi",
    "doi",
    "record doi",
    "affected doi",
    "retraction doi",
)

_REASON_COLUMNS = ("reason", "retractionreason", "cause")
_DATE_COLUMNS = ("retractiondate", "retraction date", "date", "updated")
_NATURE_COLUMNS = ("retractionnature", "nature", "type", "kind", "update-type", "updatetype")

_NATURE_KIND = {
    "retraction": "retraction",
    "retracted": "retraction",
    "withdrawal": "withdrawal",
    "correction": "correction",
    "erratum": "correction",
    "expression of concern": "expression_of_concern",
    "expression-of-concern": "expression_of_concern",
    "concern": "expression_of_concern",
    "reinstatement": "reinstatement",
}


def _norm(doi: Any) -> str | None:
    if doi is None:
        return None
    cleaned = clean_doi(str(doi))
    return cleaned.lower() if cleaned else None


def _kind_from_nature(value: Any) -> str:
    if not value:
        return "retraction"
    key = str(value).strip().lower()
    return _NATURE_KIND.get(key, "retraction")


def _pick(row: dict[str, Any], columns: tuple[str, ...]) -> Any:
    """Return the first present, non-empty value among candidate columns."""
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for col in columns:
        if col in lowered and str(lowered[col]).strip():
            return lowered[col]
    return None


def _notice(kind: str, source: str, url: str, reason: str | None, date: str | None) -> dict[str, Any]:
    label = kind.replace("_", " ").title()
    notice: dict[str, Any] = {
        "kind": kind,
        "source": source,
        "url": url,
        "label": label,
        "target": "work",
    }
    if reason:
        notice["reason"] = reason
    if date:
        notice["date"] = date
    return notice


def _add(table: dict[str, list[dict[str, Any]]], doi: str | None, notice: dict[str, Any]) -> None:
    key = _norm(doi)
    if not key:
        return
    bucket = table.setdefault(key, [])
    if notice not in bucket:
        bucket.append(notice)


def _from_csv(path: Path) -> dict[str, list[dict[str, Any]]]:
    table: dict[str, list[dict[str, Any]]] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            doi = _pick(row, _DOI_COLUMNS)
            if not doi:
                continue
            kind = _kind_from_nature(_pick(row, _NATURE_COLUMNS))
            reason = _pick(row, _REASON_COLUMNS)
            date = _pick(row, _DATE_COLUMNS)
            _add(
                table,
                doi,
                _notice(kind, "retraction-watch", "", str(reason) if reason else None,
                        str(date) if date else None),
            )
    return table


def _from_json_record(record: dict[str, Any]) -> list[tuple[str | None, dict[str, Any]]]:
    """Extract (doi, notice) pairs from one JSON record."""
    out: list[tuple[str | None, dict[str, Any]]] = []

    # Crossref update-to style: {"DOI": ..., "update-to": [{"DOI":..., "type":...}]}
    updates = record.get("update-to") or record.get("update_to") or record.get("updates")
    if isinstance(updates, list):
        for upd in updates:
            if isinstance(upd, dict):
                kind = _kind_from_nature(upd.get("type") or upd.get("update-type"))
                out.append((
                    upd.get("DOI") or upd.get("doi") or record.get("DOI") or record.get("doi"),
                    _notice(kind, "crossref", str(upd.get("URL") or upd.get("url") or ""),
                            upd.get("label"), upd.get("updated")),
                ))
        if out:
            return out

    # Flat style: {"doi": ..., "kind": ..., "reason": ..., "date": ...}
    doi = record.get("doi") or record.get("DOI") or record.get("original_doi")
    if doi:
        kind = _kind_from_nature(
            record.get("kind") or record.get("type") or record.get("nature")
        )
        out.append((
            doi,
            _notice(kind, str(record.get("source", "offline")),
                    str(record.get("url", "")),
                    record.get("reason"), record.get("date")),
        ))
    return out


def _from_json(path: Path) -> dict[str, list[dict[str, Any]]]:
    table: dict[str, list[dict[str, Any]]] = {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("items") or data.get("records") or [data]
    else:
        items = data
    if not isinstance(items, list):
        raise ValueError("retraction JSON must be an object or a list")
    for record in items:
        if not isinstance(record, dict):
            continue
        for doi, notice in _from_json_record(record):
            _add(table, doi, notice)
    return table


def _from_jsonl(path: Path) -> dict[str, list[dict[str, Any]]]:
    table: dict[str, list[dict[str, Any]]] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                continue
            for doi, notice in _from_json_record(record):
                _add(table, doi, notice)
    return table


def load_retractions(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Load an offline retraction file into a DOI -> notices mapping.

    The format is chosen from the file suffix (``.csv``, ``.jsonl``/``.ndjson``,
    ``.json``); an unknown suffix is sniffed (JSON first, then CSV).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"retraction file not found: {p}")
    suffix = p.suffix.lower()
    if suffix == ".csv":
        return _from_csv(p)
    if suffix in (".jsonl", ".ndjson"):
        return _from_jsonl(p)
    if suffix == ".json":
        return _from_json(p)
    # Sniff: try JSON, then JSONL, then CSV.
    text = p.read_text(encoding="utf-8").lstrip()
    if text.startswith("{") or text.startswith("["):
        try:
            return _from_json(p)
        except (ValueError, json.JSONDecodeError):
            return _from_jsonl(p)
    return _from_csv(p)


def apply_retractions(
    results: list[Any],
    table: dict[str, list[dict[str, Any]]],
) -> int:
    """Attach offline notices to results whose DOI is in ``table``.

    Sets status to RETRACTED and adds the ``retracted`` flag for retraction or
    withdrawal notices. Returns the number of results changed.
    """
    changed = 0
    for result in results:
        candidates: list[Any] = []
        if getattr(result, "record", None) is not None:
            candidates.append(getattr(result.record, "doi", None))
        if getattr(result, "input", None) is not None:
            candidates.append(getattr(result.input, "doi", None))
        matched: list[dict[str, Any]] = []
        for doi in candidates:
            key = _norm(doi)
            if key and key in table:
                for notice in table[key]:
                    if notice not in matched:
                        matched.append(notice)
        if not matched:
            continue
        notices = matched
        existing = result.integrity or []
        for notice in notices:
            if notice not in existing:
                existing.append(notice)
        result.integrity = existing
        kinds = {n.get("kind") for n in notices}
        if kinds & {"retraction", "withdrawal"}:
            if "retracted" not in result.flags:
                result.flags = sorted(set(list(result.flags) + ["retracted"]))
            result.status = "RETRACTED"
        changed += 1
    return changed


__all__ = ["load_retractions", "apply_retractions"]
