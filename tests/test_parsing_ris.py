# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for RIS parser."""
from __future__ import annotations

import pytest

from veridex.parsing.ris import parse_ris


def test_ris_basic_entry() -> None:
    text = """TY  - JOUR
TI  - Soil consolidation under cyclic loading
AU  - Smith, John
AU  - Jones, Mary
JO  - Journal of Geotechnical Engineering
VL  - 45
IS  - 3
SP  - 123
EP  - 145
PY  - 2020
DO  - 10.1234/jge.2020.001
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "Soil consolidation under cyclic loading"
    assert ref.authors == ["Smith, John", "Jones, Mary"]
    assert ref.journal == "Journal of Geotechnical Engineering"
    assert ref.volume == "45"
    assert ref.issue == "3"
    assert ref.pages == "123-145"
    assert ref.year == 2020
    assert ref.doi == "10.1234/jge.2020.001"
    assert ref.format == "ris"


def test_ris_multi_au() -> None:
    text = """TY  - JOUR
TI  - Multi-author paper
AU  - Alpha, A.
AU  - Beta, B.
AU  - Gamma, G.
AU  - Delta, D.
PY  - 2021
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert len(ref.authors) == 4
    assert ref.authors == ["Alpha, A.", "Beta, B.", "Gamma, G.", "Delta, D."]


def test_ris_do_tag_doi() -> None:
    text = """TY  - JOUR
TI  - DOI from DO tag
AU  - Author, A.
PY  - 2022
DO  - 10.5555/do.tag.test
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.doi == "10.5555/do.tag.test"


def test_ris_n1_tag_doi() -> None:
    text = """TY  - JOUR
TI  - DOI from N1 tag
AU  - Author, A.
PY  - 2023
N1  - doi: 10.5555/n1.tag.test
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.doi == "10.5555/n1.tag.test"


def test_ris_do_preferred_over_n1() -> None:
    text = """TY  - JOUR
TI  - DO preferred
AU  - Author, A.
PY  - 2024
DO  - 10.5555/do.preferred
N1  - doi: 10.5555/n1.ignored
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.doi == "10.5555/do.preferred"


def test_ris_multiple_entries() -> None:
    text = """TY  - JOUR
TI  - First paper
AU  - First, F.
PY  - 2020
ER  -
TY  - BOOK
TI  - Second book
AU  - Second, S.
PY  - 2021
PB  - Press Name
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 2
    assert refs[0].title == "First paper"
    assert refs[1].title == "Second book"
    assert refs[1].publisher == "Press Name"


def test_ris_url_extraction() -> None:
    text = """TY  - JOUR
TI  - URL test
AU  - Author, A.
PY  - 2020
UR  - https://example.com/paper
L4  - https://fulltext.example.com/pdf
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.url == "https://fulltext.example.com/pdf"


def test_ris_issn_raw_field() -> None:
    text = """TY  - JOUR
TI  - ISSN test
AU  - Author, A.
PY  - 2020
SN  - 1234-5678
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.raw_fields.get("issn") == "1234-5678"


def test_ris_empty_input() -> None:
    refs = parse_ris("")
    assert refs == []
    refs = parse_ris("   \n\n  ")
    assert refs == []


def test_ris_malformed_no_er() -> None:
    text = """TY  - JOUR
TI  - No ER tag
AU  - Author, A.
PY  - 2020"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "No ER tag"


def test_ris_unicode() -> None:
    text = """TY  - JOUR
TI  - Pavement fatigue: análise e modelação
AU  - Silva, João
AU  - Müller, Jürgen
PY  - 2020
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert "análise" in ref.title
    assert "Silva, João" in ref.authors[0]
    assert "Müller, Jürgen" in ref.authors[1]


def test_ris_sp_only_pages() -> None:
    text = """TY  - JOUR
TI  - Start page only
AU  - Author, A.
PY  - 2020
SP  - 100
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.pages == "100"


def test_ris_various_types() -> None:
    text = """TY  - CHAP
TI  - Book chapter on heat conduction
AU  - Author, A.
PY  - 2020
PB  - Publisher
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "Book chapter on heat conduction"
    assert ref.publisher == "Publisher"


def test_ris_extra_whitespace() -> None:
    text = """TY  -  JOUR
TI  -  Extra spaces
AU  -  Author, A.
PY  -  2020
ER  -"""
    refs = parse_ris(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "Extra spaces"
    assert ref.authors == ["Author, A."]
    assert ref.year == 2020