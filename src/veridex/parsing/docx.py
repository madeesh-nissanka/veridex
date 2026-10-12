# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""DOCX reference parser using stdlib zipfile + xml. Extracts full_text, reference_section,
and in-text citations. parse_docx_file(path) -> list[ParsedReference], parse_docx(text, source_file) for text fallback."""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from veridex.models import ParsedReference
from veridex.parsing.plain import parse_plain

NAMESPACES = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _get_text_from_xml(xml_bytes: bytes) -> str:
    """Extract plain text from word/document.xml."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""

    texts = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag in ("t", "delText"):
            if elem.text:
                texts.append(elem.text)
        elif tag == "tab":
            texts.append("\t")
        elif tag in ("br", "cr"):
            texts.append("\n")
        elif tag == "p":
            texts.append("\n")
    return "".join(texts)


def _extract_paragraphs(xml_bytes: bytes) -> list[tuple[str, str]]:
    """Extract paragraphs with their style names. Returns list of (style_name, text)."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    paragraphs = []
    for p in root.iter(f"{{{NAMESPACES['w']}}}p"):
        style_name = ""
        pPr = p.find(f"{{{NAMESPACES['w']}}}pPr")
        if pPr is not None:
            pStyle = pPr.find(f"{{{NAMESPACES['w']}}}pStyle")
            if pStyle is not None:
                style_name = pStyle.get(f"{{{NAMESPACES['w']}}}val", "")

        texts = []
        for elem in p.iter():
            tag = elem.tag.split("}")[-1]
            if tag in ("t", "delText"):
                if elem.text:
                    texts.append(elem.text)
            elif tag == "tab":
                texts.append("\t")
        para_text = "".join(texts).strip()
        if para_text:
            paragraphs.append((style_name, para_text))
    return paragraphs


def _detect_reference_section(paragraphs: list[tuple[str, str]]) -> tuple[str, int]:
    """Detect reference section. Returns (reference_text, start_index).
    Looks for 'References', 'Bibliography', 'Works Cited' heading; else last third of doc."""
    heading_keywords = ("references", "bibliography", "works cited", "reference list")

    for i, (style, text) in enumerate(paragraphs):
        low = text.lower()
        is_keyword_heading = (
            any(kw in low for kw in heading_keywords)
            and (len(low) <= 20 or (style.lower().startswith("heading") and len(low) <= 50))
        )
        if is_keyword_heading:
            if i + 1 < len(paragraphs):
                ref_text = "\n".join(p[1] for p in paragraphs[i + 1:])
                return ref_text, i + 1

    third = max(1, len(paragraphs) // 3)
    start = len(paragraphs) - third
    ref_text = "\n".join(p[1] for p in paragraphs[start:])
    return ref_text, start


def _extract_in_text_citations(text: str) -> list[dict[str, Any]]:
    """Extract in-text citations from full document text."""
    citations = []

    bracket_pattern = re.compile(r"\[(\d+(?:[,\s]+\d+)*)\]")
    for match in bracket_pattern.finditer(text):
        markers = match.group(1).split(",")
        for m in markers:
            m = m.strip()
            if m.isdigit():
                citations.append({
                    "marker": f"[{m}]",
                    "sentence": _get_surrounding_sentence(text, match.start()),
                    "ref_index": int(m) - 1,
                })

    author_year_pattern = re.compile(
        r"(?:\(|（)([A-Z][A-Za-z\-']+(?:\s+et\s+al\.?)?),\s*((?:19|20)\d{2})[a-z]?(?:\)|）)"
    )
    narrative_pattern = re.compile(
        r"\b([A-Z][A-Za-z\-']+(?:\s+et\s+al\.?)?)\s*\(\s*((?:19|20)\d{2})[a-z]?\s*\)"
    )
    seen_spans = set()
    for match in author_year_pattern.finditer(text):
        citations.append({
            "marker": match.group(0),
            "sentence": _get_surrounding_sentence(text, match.start()),
            "ref_index": None,
        })
        seen_spans.add(match.span())
    for match in narrative_pattern.finditer(text):
        if any(s <= match.start() and match.end() <= e for s, e in seen_spans):
            continue
        citations.append({
            "marker": f"{match.group(1)} ({match.group(2)})",
            "author": match.group(1),
            "year": int(match.group(2)),
            "sentence": _get_surrounding_sentence(text, match.start()),
            "ref_index": None,
        })

    return citations


def _get_surrounding_sentence(text: str, pos: int) -> str:
    """Get the sentence containing the position."""
    start = pos
    while start > 0 and text[start - 1] not in ".!?\n":
        start -= 1
    end = pos
    while end < len(text) and text[end] not in ".!?\n":
        end += 1
    if end < len(text):
        end += 1
    return text[start:end].strip()


def extract_docx(path: str) -> dict[str, Any]:
    """Extract full text, reference section, and in-text citations from a DOCX file.

    Returns dict with keys:
    - full_text: str, entire document text
    - reference_section: str, detected references section text
    - reference_start_index: int, paragraph index where references start
    - in_text_citations: list[dict] with 'marker', 'sentence', 'ref_index'
    """
    try:
        with zipfile.ZipFile(path, "r") as z:
            if "word/document.xml" not in z.namelist():
                raise ValueError("Not a valid DOCX file: missing word/document.xml")
            xml_bytes = z.read("word/document.xml")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid DOCX file: {exc}") from exc

    full_text = _get_text_from_xml(xml_bytes)
    paragraphs = _extract_paragraphs(xml_bytes)
    reference_section, reference_start_index = _detect_reference_section(paragraphs)
    in_text_citations = _extract_in_text_citations(full_text)

    return {
        "full_text": full_text,
        "reference_section": reference_section,
        "reference_start_index": reference_start_index,
        "in_text_citations": in_text_citations,
    }


_REF_LINE_RE = re.compile(
    r"^\s*(\[\d+\]|\d+\.)\s|\(\s*(?:19|20)\d{2}[a-z]?\s*\)|,\s*(?:19|20)\d{2}[a-z]?\b|doi:|10\.\d{4}/|\bhttps?://",
    re.IGNORECASE,
)


def reference_like_lines(text: str) -> list[str]:
    """Keep only lines that plausibly are reference-list entries."""
    return [line for line in text.splitlines() if line.strip() and _REF_LINE_RE.search(line)]


def parse_docx_file(path: str) -> list[ParsedReference]:
    """Parse references from a DOCX file."""
    data = extract_docx(path)
    lines = reference_like_lines(data["reference_section"])
    refs = parse_plain("\n".join(lines), source_file=path)
    for i, ref in enumerate(refs):
        ref.index = i
        ref.source_file = path
    return refs


def parse_docx(text: str, source_file: str | None = None) -> list[ParsedReference]:
    """Parse references from plain text (fallback for DOCX content already extracted)."""
    return parse_plain(text, source_file=source_file)