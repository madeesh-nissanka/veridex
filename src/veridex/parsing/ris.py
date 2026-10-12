# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""RIS parser with tag parser TY/AU/TI/PY/JO/SN/UR/L4 plus ER end; multi AU; DO/N1 DOI extraction."""
from __future__ import annotations

import re
from typing import Any

from veridex.models import ParsedReference
from veridex.ids import extract_identifiers, find_doi


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


def _clean_value(val: str) -> str:
    val = val.strip()
    val = re.sub(r"\s+", " ", val)
    return val


def parse_ris(text: str, source_file: str | None = None) -> list[ParsedReference]:
    """Parse RIS text into list of ParsedReference."""
    if not text or not text.strip():
        return []

    refs: list[ParsedReference] = []
    index = 0

    entries = re.split(r"\n\s*ER\s*-\s*\n", text)

    for entry_text in entries:
        entry_text = entry_text.strip()
        if not entry_text:
            continue

        fields: dict[str, list[str]] = {}
        raw_fields: dict[str, str] = {}

        for line in entry_text.splitlines():
            line = line.rstrip()
            if not line:
                continue
            if len(line) < 6:
                continue
            tag = line[:2].strip()
            value = line[6:].strip() if len(line) > 6 else ""
            if tag and value:
                if tag not in fields:
                    fields[tag] = []
                fields[tag].append(value)
                raw_fields[tag] = value

        ref = ParsedReference(
            index=index,
            raw=entry_text,
            format="ris",
            source_file=source_file,
            raw_fields=raw_fields,
        )

        ref.title = _clean_value(fields.get("TI", [""])[0]) if fields.get("TI") else None
        ref.authors = [_clean_value(au) for au in fields.get("AU", []) if au]
        ref.year = _parse_year(fields.get("PY", [""])[0]) if fields.get("PY") else None
        ref.journal = _clean_value(fields.get("JO", [""])[0]) if fields.get("JO") else None
        ref.volume = _clean_value(fields.get("VL", [""])[0]) if fields.get("VL") else None
        ref.issue = _clean_value(fields.get("IS", [""])[0]) if fields.get("IS") else None
        sp = _clean_value(fields["SP"][0]) if fields.get("SP") else None
        ep = _clean_value(fields["EP"][0]) if fields.get("EP") else None
        if sp and ep:
            ref.pages = f"{sp}-{ep}"
        else:
            ref.pages = sp or ep
        ref.publisher = _clean_value(fields.get("PB", [""])[0]) if fields.get("PB") else None

        sn = _clean_value(fields.get("SN", [""])[0]) if fields.get("SN") else None
        if sn:
            ref.raw_fields["issn"] = sn

        ur = _clean_value(fields.get("UR", [""])[0]) if fields.get("UR") else None
        if ur:
            ref.url = ur

        l4 = _clean_value(fields.get("L4", [""])[0]) if fields.get("L4") else None
        if l4:
            ref.url = l4

        all_text = " ".join(filter(None, [
            ref.title,
            " ".join(ref.authors),
            str(ref.year) if ref.year else "",
            ref.journal,
            ref.volume,
            ref.issue,
            ref.pages,
        ]))

        for do_val in fields.get("DO", []):
            doi = find_doi(do_val)
            if doi:
                ref.doi = doi
                break

        if not ref.doi:
            for n1_val in fields.get("N1", []):
                doi = find_doi(n1_val)
                if doi:
                    ref.doi = doi
                    break

        if not ref.doi:
            ids = extract_identifiers(all_text)
            ref.doi = ids.get("doi")
            ref.pmid = ids.get("pmid")
            ref.arxiv_id = ids.get("arxiv_id")
            ref.isbn = ids.get("isbn")
            if not ref.url:
                ref.url = ids.get("url")

        refs.append(ref)
        index += 1

    return refs