# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for DOCX parser."""
from __future__ import annotations

import zipfile
import tempfile
import os

import pytest

from veridex.parsing.docx import extract_docx, parse_docx_file


def _make_docx(content_xml: str) -> str:
    """Create a temporary DOCX file with the given document.xml content."""
    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w") as z:
        z.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""")
        z.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""")
        z.writestr("word/_rels/document.xml.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>""")
        z.writestr("word/document.xml", content_xml)
    return tmp.name


def _docx_xml(paragraphs: list[tuple[str, str]]) -> str:
    """Generate document.xml from list of (style, text) paragraphs."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', f'<w:document {ns}>', '<w:body>']
    for style, text in paragraphs:
        style_attr = f'w:val="{style}"' if style else ""
        parts.append(f'<w:p><w:pPr><w:pStyle {style_attr}/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>')
    parts.append('</w:body></w:document>')
    return "\n".join(parts)


def test_docx_extract_full_text() -> None:
    xml = _docx_xml([
        ("Heading1", "Title"),
        ("Normal", "First paragraph with citation [1]."),
        ("Normal", "Second paragraph."),
    ])
    path = _make_docx(xml)
    try:
        data = extract_docx(path)
        assert "Title" in data["full_text"]
        assert "First paragraph" in data["full_text"]
        assert "Second paragraph" in data["full_text"]
    finally:
        os.unlink(path)


def test_docx_extract_reference_section_heading() -> None:
    xml = _docx_xml([
        ("Heading1", "Title"),
        ("Normal", "Body text [1]."),
        ("Heading1", "References"),
        ("Normal", "[1] Smith J (2020) Soil consolidation. J Geotech Eng. doi:10.1234/test"),
        ("Normal", "[2] Jones M (2021) Beam deflection. Struct J."),
    ])
    path = _make_docx(xml)
    try:
        data = extract_docx(path)
        assert "References" not in data["reference_section"]
        assert "Soil consolidation" in data["reference_section"]
        assert "Beam deflection" in data["reference_section"]
        assert data["reference_start_index"] == 3
    finally:
        os.unlink(path)


def test_docx_extract_reference_section_bibliography() -> None:
    xml = _docx_xml([
        ("Normal", "Body [1]."),
        ("Heading2", "Bibliography"),
        ("Normal", "[1] Author A (2020) Title. Journal. doi:10.1111/a"),
    ])
    path = _make_docx(xml)
    try:
        data = extract_docx(path)
        assert "Title" in data["reference_section"]
        assert "Journal" in data["reference_section"]
    finally:
        os.unlink(path)


def test_docx_extract_reference_section_works_cited() -> None:
    xml = _docx_xml([
        ("Normal", "Body [1]."),
        ("Heading1", "Works Cited"),
        ("Normal", "[1] Author A (2020) Title. Journal."),
    ])
    path = _make_docx(xml)
    try:
        data = extract_docx(path)
        assert "Title" in data["reference_section"]
    finally:
        os.unlink(path)


def test_docx_extract_reference_section_fallback_last_third() -> None:
    xml = _docx_xml([
        ("Normal", "Para 1"),
        ("Normal", "Para 2"),
        ("Normal", "Para 3"),
        ("Normal", "Para 4"),
        ("Normal", "Para 5"),
        ("Normal", "Para 6"),
    ])
    path = _make_docx(xml)
    try:
        data = extract_docx(path)
        assert "Para 5" in data["reference_section"]
        assert "Para 6" in data["reference_section"]
        assert "Para 1" not in data["reference_section"]
    finally:
        os.unlink(path)


def test_docx_extract_in_text_citations_bracket() -> None:
    xml = _docx_xml([
        ("Normal", "This is a sentence with citation [1]."),
        ("Normal", "Another with multiple [2, 3]."),
    ])
    path = _make_docx(xml)
    try:
        data = extract_docx(path)
        citations = data["in_text_citations"]
        assert len(citations) >= 2
        markers = [c["marker"] for c in citations]
        assert "[1]" in markers
        assert "[2]" in markers or "[3]" in markers
        for c in citations:
            assert "sentence" in c
            assert c["ref_index"] is not None
    finally:
        os.unlink(path)


def test_docx_extract_in_text_citations_author_year() -> None:
    xml = _docx_xml([
        ("Normal", "As shown by Smith (2020), the result holds."),
    ])
    path = _make_docx(xml)
    try:
        data = extract_docx(path)
        citations = data["in_text_citations"]
        assert len(citations) >= 1
        ay_cites = [c for c in citations if "Smith" in c["marker"]]
        assert len(ay_cites) >= 1
        assert ay_cites[0]["ref_index"] is None
    finally:
        os.unlink(path)


def test_docx_parse_file() -> None:
    xml = _docx_xml([
        ("Heading1", "Document"),
        ("Normal", "Body text [1]."),
        ("Heading1", "References"),
        ("Normal", "[1] Smith J (2020) Soil consolidation. J Geotech Eng. doi:10.1234/test"),
        ("Normal", "[2] Jones M (2021) Beam deflection. Struct J."),
    ])
    path = _make_docx(xml)
    try:
        refs = parse_docx_file(path)
        assert len(refs) == 2
        assert refs[0].doi == "10.1234/test"
        assert refs[0].year == 2020
        assert refs[1].year == 2021
    finally:
        os.unlink(path)


def test_docx_parse_empty() -> None:
    xml = _docx_xml([
        ("Normal", "No references here."),
    ])
    path = _make_docx(xml)
    try:
        refs = parse_docx_file(path)
        assert refs == []
    finally:
        os.unlink(path)


def test_docx_unicode() -> None:
    xml = _docx_xml([
        ("Heading1", "References"),
        ("Normal", "[1] Silva J (2020) Pavement fatigue: análise. Revista."),
    ])
    path = _make_docx(xml)
    try:
        refs = parse_docx_file(path)
        assert len(refs) == 1
        assert "análise" in (refs[0].title or "")
    finally:
        os.unlink(path)


def test_docx_invalid_file() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    tmp.write(b"not a docx")
    tmp.close()
    try:
        with pytest.raises(ValueError):
            extract_docx(tmp.name)
    finally:
        os.unlink(tmp.name)


def test_docx_missing_document_xml() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w") as z:
        z.writestr("other.xml", "<xml/>")
    try:
        with pytest.raises(ValueError):
            extract_docx(tmp.name)
    finally:
        os.unlink(tmp.name)


def test_docx_parse_docx_text_fallback() -> None:
    from veridex.parsing.docx import parse_docx
    text = "[1] Smith J (2020) Title. Journal. doi:10.1234/test"
    refs = parse_docx(text)
    assert len(refs) == 1
    assert refs[0].doi == "10.1234/test"


def test_docx_multiple_citations_same_sentence() -> None:
    xml = _docx_xml([
        ("Normal", "Multiple citations [1, 2, 3] in one sentence."),
        ("Heading1", "References"),
        ("Normal", "[1] Ref one."),
        ("Normal", "[2] Ref two."),
        ("Normal", "[3] Ref three."),
    ])
    path = _make_docx(xml)
    try:
        data = extract_docx(path)
        citations = data["in_text_citations"]
        markers = [c["marker"] for c in citations]
        assert "[1]" in markers
        assert "[2]" in markers
        assert "[3]" in markers
    finally:
        os.unlink(path)