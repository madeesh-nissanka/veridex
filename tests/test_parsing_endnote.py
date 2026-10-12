# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for EndNote XML parser."""
from __future__ import annotations

import pytest

from veridex.parsing.endnote import parse_endnote


def test_endnote_basic_record() -> None:
    text = """<?xml version="1.0" encoding="UTF-8"?>
<xml>
  <records>
    <record>
      <titles>
        <title>Soil consolidation under cyclic loading</title>
      </titles>
      <authors>
        <author>
          <name>Smith, John</name>
        </author>
        <author>
          <name>Jones, Mary</name>
        </author>
      </authors>
      <periodical>
        <full-title>Journal of Geotechnical Engineering</full-title>
      </periodical>
      <volume>45</volume>
      <number>3</number>
      <pages>123-145</pages>
      <dates>
        <year>2020</year>
      </dates>
      <electronic-public-datum>10.1234/jge.2020.001</electronic-public-datum>
    </record>
  </records>
</xml>"""
    refs = parse_endnote(text)
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
    assert ref.format == "endnote"


def test_endnote_multiple_records() -> None:
    text = """<?xml version="1.0"?>
<xml>
  <records>
    <record>
      <titles><title>First paper</title></titles>
      <authors><author><name>Author, A.</name></author></authors>
      <dates><year>2020</year></dates>
    </record>
    <record>
      <titles><title>Second book</title></titles>
      <authors><author><name>Author, B.</name></author></authors>
      <publisher>Press Name</publisher>
      <dates><year>2021</year></dates>
    </record>
  </records>
</xml>"""
    refs = parse_endnote(text)
    assert len(refs) == 2
    assert refs[0].title == "First paper"
    assert refs[0].year == 2020
    assert refs[1].title == "Second book"
    assert refs[1].publisher == "Press Name"
    assert refs[1].year == 2021


def test_endnote_doi_from_urls() -> None:
    text = """<?xml version="1.0"?>
<xml>
  <records>
    <record>
      <titles><title>DOI from URLs</title></titles>
      <authors><author><name>Author, A.</name></author></authors>
      <urls>
        <url>https://doi.org/10.5555/url.doi.test</url>
      </urls>
      <dates><year>2020</year></dates>
    </record>
  </records>
</xml>"""
    refs = parse_endnote(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.doi == "10.5555/url.doi.test"


def test_endnote_fallback_identifiers() -> None:
    text = """<?xml version="1.0"?>
<xml>
  <records>
    <record>
      <titles><title>Identifiers in text</title></titles>
      <authors><author><name>Author, A.</name></author></authors>
      <periodical><full-title>Journal</full-title></periodical>
      <volume>10</volume>
      <pages>1-10</pages>
      <dates><year>2020</year></dates>
      <electronic-public-datum>PMID: 12345678</electronic-public-datum>
    </record>
  </records>
</xml>"""
    refs = parse_endnote(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.pmid == "12345678"


def test_endnote_unicode() -> None:
    text = """<?xml version="1.0" encoding="UTF-8"?>
<xml>
  <records>
    <record>
      <titles><title>Pavement fatigue: análise e modelação</title></titles>
      <authors>
        <author><name>Silva, João</name></author>
        <author><name>Müller, Jürgen</name></author>
      </authors>
      <dates><year>2020</year></dates>
    </record>
  </records>
</xml>"""
    refs = parse_endnote(text)
    assert len(refs) == 1
    ref = refs[0]
    assert "análise" in ref.title
    assert "Silva, João" in ref.authors[0]
    assert "Müller, Jürgen" in ref.authors[1]


def test_endnote_empty_input() -> None:
    refs = parse_endnote("")
    assert refs == []
    refs = parse_endnote("   ")
    assert refs == []


def test_endnote_malformed_xml() -> None:
    text = """<xml>
  <records>
    <record>
      <titles><title>Unclosed
    </record>
  </records>"""
    refs = parse_endnote(text)
    assert refs == []


def test_endnote_alt_paths() -> None:
    text = """<?xml version="1.0"?>
<xml>
  <records>
    <record>
      <title>Alt title path</title>
      <journal>Alt journal path</journal>
      <year>2020</year>
      <author>
        <name>Author, A.</name>
      </author>
    </record>
  </records>
</xml>"""
    refs = parse_endnote(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "Alt title path"
    assert ref.journal == "Alt journal path"
    assert ref.authors == ["Author, A."]
    assert ref.year == 2020


def test_endnote_raw_fields() -> None:
    text = """<?xml version="1.0"?>
<xml>
  <records>
    <record>
      <titles><title>Test</title></titles>
      <authors><author><name>Author, A.</name></author></authors>
      <periodical><full-title>Journal</full-title></periodical>
      <volume>5</volume>
      <number>2</number>
      <pages>10-20</pages>
      <publisher>Publisher</publisher>
      <dates><year>2020</year></dates>
    </record>
  </records>
</xml>"""
    refs = parse_endnote(text)
    assert len(refs) == 1
    ref = refs[0]
    assert "authors" in ref.raw_fields
    assert "title" in ref.raw_fields
    assert "journal" in ref.raw_fields
    assert "year" in ref.raw_fields
    assert "volume" in ref.raw_fields
    assert "issue" in ref.raw_fields
    assert "pages" in ref.raw_fields
    assert "publisher" in ref.raw_fields


def test_endnote_no_records() -> None:
    text = """<?xml version="1.0"?>
<xml>
  <records/>
</xml>"""
    refs = parse_endnote(text)
    assert refs == []


def test_endnote_author_name_parts() -> None:
    text = """<?xml version="1.0"?>
<xml>
  <records>
    <record>
      <titles><title>Name parts</title></titles>
      <authors>
        <author>
          <name>Smith</name>
          <name>John</name>
        </author>
      </authors>
      <dates><year>2020</year></dates>
    </record>
  </records>
</xml>"""
    refs = parse_endnote(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.authors == ["Smith John"]


def test_endnote_electronic_public_datum_multiple() -> None:
    text = """<?xml version="1.0"?>
<xml>
  <records>
    <record>
      <titles><title>Multiple EPD</title></titles>
      <authors><author><name>Author, A.</name></author></authors>
      <electronic-public-datum>Some text</electronic-public-datum>
      <electronic-public-datum>10.5555/second.doi</electronic-public-datum>
      <dates><year>2020</year></dates>
    </record>
  </records>
</xml>"""
    refs = parse_endnote(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.doi == "10.5555/second.doi"