# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for CSL JSON parser."""
from __future__ import annotations

import pytest

from veridex.parsing.csljson import parse_csljson


def test_csljson_single_object() -> None:
    text = """{
  "type": "article-journal",
  "title": "Soil consolidation under cyclic loading",
  "author": [
    {"family": "Smith", "given": "John"},
    {"family": "Jones", "given": "Mary"}
  ],
  "container-title": "Journal of Geotechnical Engineering",
  "volume": "45",
  "issue": "3",
  "page": "123-145",
  "issued": {"date-parts": [[2020]]},
  "DOI": "10.1234/jge.2020.001",
  "URL": "https://example.com/paper"
}"""
    refs = parse_csljson(text)
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
    assert ref.url == "https://example.com/paper"
    assert ref.format == "csl-json"


def test_csljson_array() -> None:
    text = """[
  {
    "type": "article-journal",
    "title": "First paper",
    "author": [{"family": "Alpha", "given": "A."}],
    "issued": {"date-parts": [[2020]]}
  },
  {
    "type": "book",
    "title": "Second book",
    "author": [{"family": "Beta", "given": "B."}],
    "publisher": "Press Name",
    "issued": {"date-parts": [[2021]]}
  }
]"""
    refs = parse_csljson(text)
    assert len(refs) == 2
    assert refs[0].title == "First paper"
    assert refs[0].year == 2020
    assert refs[1].title == "Second book"
    assert refs[1].publisher == "Press Name"
    assert refs[1].year == 2021


def test_csljson_author_variants() -> None:
    text = """{
  "title": "Author variants",
  "author": [
    {"family": "Full", "given": "Name"},
    {"family": "FamilyOnly"},
    {"given": "GivenOnly"}
  ],
  "issued": {"date-parts": [[2020]]}
}"""
    refs = parse_csljson(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.authors == ["Full, Name", "FamilyOnly", "GivenOnly"]


def test_csljson_date_parts_variants() -> None:
    text = """{
  "title": "Date variants",
  "author": [{"family": "Author", "given": "A."}],
  "issued": {"date-parts": [[2020, 5, 15]]}
}"""
    refs = parse_csljson(text)
    assert len(refs) == 1
    assert refs[0].year == 2020

    text2 = """{
  "title": "Date variants 2",
  "author": [{"family": "Author", "given": "A."}],
  "issued": {"date-parts": [[2021]]}
}"""
    refs2 = parse_csljson(text2)
    assert refs2[0].year == 2021


def test_csljson_missing_fields() -> None:
    text = """{
  "title": "Minimal entry",
  "author": [{"family": "Minimal", "given": "M."}]
}"""
    refs = parse_csljson(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "Minimal entry"
    assert ref.authors == ["Minimal, M."]
    assert ref.year is None
    assert ref.journal is None


def test_csljson_doi_from_ids() -> None:
    text = """{
  "title": "DOI from IDs",
  "author": [{"family": "Author", "given": "A."}],
  "issued": {"date-parts": [[2020]]},
  "id": "https://doi.org/10.5555/test.doi"
}"""
    refs = parse_csljson(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.doi == "10.5555/test.doi"


def test_csljson_unicode() -> None:
    text = """{
  "title": "Pavement fatigue: análise e modelação",
  "author": [
    {"family": "Silva", "given": "João"},
    {"family": "Müller", "given": "Jürgen"}
  ],
  "container-title": "Revista de Engenharia",
  "issued": {"date-parts": [[2020]]}
}"""
    refs = parse_csljson(text)
    assert len(refs) == 1
    ref = refs[0]
    assert "análise" in ref.title
    assert "Silva, João" in ref.authors[0]
    assert "Müller, Jürgen" in ref.authors[1]


def test_csljson_empty_input() -> None:
    refs = parse_csljson("")
    assert refs == []
    refs = parse_csljson("   ")
    assert refs == []


def test_csljson_malformed_json() -> None:
    text = """{
  "title": "Bad JSON,
  "author": [{"family": "Author", "given": "A."}]
}"""
    refs = parse_csljson(text)
    assert refs == []


def test_csljson_non_dict_items() -> None:
    text = """[
  "not a dict",
  {"title": "Valid", "author": [{"family": "Valid", "given": "V."}]},
  123
]"""
    refs = parse_csljson(text)
    assert len(refs) == 1
    assert refs[0].title == "Valid"


def test_csljson_publisher_and_url() -> None:
    text = """{
  "type": "book",
  "title": "Book with publisher",
  "author": [{"family": "Author", "given": "A."}],
  "publisher": "Academic Press",
  "URL": "https://book.example.com",
  "issued": {"date-parts": [[2020]]}
}"""
    refs = parse_csljson(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.publisher == "Academic Press"
    assert ref.url == "https://book.example.com"


def test_csljson_container_title_variants() -> None:
    text = """{
  "title": "Paper",
  "author": [{"family": "Author", "given": "A."}],
  "container-title": "Journal Name",
  "issued": {"date-parts": [[2020]]}
}"""
    refs = parse_csljson(text)
    assert len(refs) == 1
    assert refs[0].journal == "Journal Name"

    text2 = """{
  "title": "Paper 2",
  "author": [{"family": "Author", "given": "A."}],
  "container-title": ["Journal Name", "Short Name"],
  "issued": {"date-parts": [[2020]]}
}"""
    refs2 = parse_csljson(text2)
    assert refs2[0].journal == "Journal Name"