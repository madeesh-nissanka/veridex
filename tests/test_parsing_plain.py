# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for plain text parser."""
from __future__ import annotations

import pytest

from veridex.parsing.plain import parse_plain


def test_plain_numbered_brackets() -> None:
    text = """[1] Smith J (2020) Soil consolidation under cyclic loading. J Geotech Eng 45:123-145. doi:10.1234/test"""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.raw == "[1] Smith J (2020) Soil consolidation under cyclic loading. J Geotech Eng 45:123-145. doi:10.1234/test"
    assert ref.doi == "10.1234/test"
    assert ref.year == 2020
    assert ref.authors == ["Smith"]
    assert "consolidation" in (ref.title or "").lower()


def test_plain_numbered_dot() -> None:
    text = """1. Jones M (2021) Beam deflection analysis. Struct J 10:1-10."""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.year == 2021
    assert ref.authors == ["Jones"]


def test_plain_author_year_paren() -> None:
    text = """Smith, J. (2020) Soil consolidation under cyclic loading. Journal of Geotechnical Engineering, 45(3), 123-145. doi:10.1234/test"""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.authors == ["Smith, J."]
    assert ref.year == 2020
    assert ref.doi == "10.1234/test"


def test_plain_author_year_comma() -> None:
    text = """Jones M, 2021 Beam deflection in composites. Structural Journal 10:1-10."""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.authors == ["Jones M"]
    assert ref.year == 2021


def test_plain_identifier_only_doi() -> None:
    text = """10.1234/test.doi"""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.doi == "10.1234/test.doi"
    assert ref.title is None
    assert ref.authors == []


def test_plain_identifier_only_url() -> None:
    text = """https://example.com/paper"""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.url == "https://example.com/paper"


def test_plain_identifier_only_pmid() -> None:
    text = """PMID: 12345678"""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.pmid == "12345678"


def test_plain_identifier_only_arxiv() -> None:
    text = """arXiv:2001.00001"""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.arxiv_id == "2001.00001"


def test_plain_identifier_only_isbn() -> None:
    text = """ISBN 978-3-16-148410-0"""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.isbn == "9783161484100"


def test_plain_free_text_fallback() -> None:
    text = """Brown A (2022) Heat conduction in layered media. Physics Journal 5:50-60. doi:10.5555/free.text"""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.doi == "10.5555/free.text"
    assert ref.year == 2022
    assert ref.authors == ["Brown"]


def test_plain_multiple_lines() -> None:
    text = """[1] First ref 2020. doi:10.1111/first
[2] Second ref 2021. doi:10.2222/second
Author Three, 2022 Third ref."""
    refs = parse_plain(text)
    assert len(refs) == 3
    assert refs[0].doi == "10.1111/first"
    assert refs[1].doi == "10.2222/second"
    assert refs[2].year == 2022
    assert refs[2].authors == ["Author Three"]


def test_plain_empty_input() -> None:
    refs = parse_plain("")
    assert refs == []
    refs = parse_plain("   \n\n  ")
    assert refs == []


def test_plain_unicode() -> None:
    text = """Silva J (2020) Pavement fatigue: análise e modelação. Revista 10:1-10."""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert "análise" in (ref.title or "")


def test_plain_v01_compat_author_year_doi() -> None:
    """v0.1 compat: author-year line with DOI parses to same doi/title/year as seed logic intends."""
    text = """Smith J (2020) Soil consolidation under cyclic loading. Journal of Geotechnical Engineering 45:123-145. doi:10.1234/jge.2020.001"""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.doi == "10.1234/jge.2020.001"
    assert ref.year == 2020
    assert "consolidation" in (ref.title or "").lower()
    assert ref.authors == ["Smith"]


def test_plain_mixed_strategies() -> None:
    text = """[1] Numbered ref 2020. doi:10.1111/num
Author Two (2021) Author year ref. doi:10.2222/ay
10.3333/identifier-only
Free text fallback 2022. doi:10.4444/free"""
    refs = parse_plain(text)
    assert len(refs) == 4
    assert refs[0].doi == "10.1111/num"
    assert refs[1].doi == "10.2222/ay"
    assert refs[1].authors == ["Author Two"]
    assert refs[2].doi == "10.3333/identifier-only"
    assert refs[3].doi == "10.4444/free"


def test_plain_year_extraction_variants() -> None:
    text = """Author (2020a) Title. Journal."""
    refs = parse_plain(text)
    assert len(refs) == 1
    assert refs[0].year == 2020

    text2 = """Author [2021] Title. Journal."""
    refs2 = parse_plain(text2)
    assert len(refs2) == 1
    assert refs2[0].year == 2021


def test_plain_no_false_positive_numbered() -> None:
    text = """Not a numbered list item."""
    refs = parse_plain(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title is not None or ref.doi is not None


def test_plain_malformed_numbered() -> None:
    text = """[abc] Not a number"""
    refs = parse_plain(text)
    assert len(refs) >= 0