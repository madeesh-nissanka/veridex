# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for repair module."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from veridex.models import AuditResult, ParsedReference, ResolvedRecord
from veridex.repair import (
    build_bibtex,
    build_csljson,
    build_ris,
    make_key,
    suggest_repairs,
    write_repairs,
)


def _make_parsed_ref(idx: int, **kwargs) -> ParsedReference:
    defaults = {
        "index": idx,
        "title": "Test Title",
        "authors": ["Author A", "Author B"],
        "year": 2020,
        "journal": "Test Journal",
        "volume": "10",
        "issue": "2",
        "pages": "100-110",
        "publisher": "Test Publisher",
        "doi": "10.1234/test",
        "url": "https://example.com/test",
    }
    defaults.update(kwargs)
    return ParsedReference(**defaults)


def _make_resolved_record(**kwargs) -> ResolvedRecord:
    defaults = {
        "source": "crossref",
        "source_id": "12345",
        "title": "Resolved Title",
        "authors": [{"family": "Author", "given": "A"}, {"family": "Author", "given": "B"}],
        "year": 2021,
        "journal": "Resolved Journal",
        "volume": "11",
        "issue": "3",
        "pages": "200-210",
        "publisher": "Resolved Publisher",
        "doi": "10.5678/resolved",
        "url": "https://example.com/resolved",
        "source_url": "https://api.crossref.org/works/10.5678/resolved",
    }
    defaults.update(kwargs)
    return ResolvedRecord(**defaults)


_UNSET = object()


def _make_audit_result(idx: int, parsed=_UNSET, record=_UNSET) -> AuditResult:
    return AuditResult(
        index=idx,
        input=_make_parsed_ref(idx) if parsed is _UNSET else parsed,
        record=_make_resolved_record() if record is _UNSET else record,
        status="VERIFIED",
    )


class TestSuggestRepairs:
    def test_no_record_returns_empty(self):
        result = _make_audit_result(0, record=None)
        assert suggest_repairs(result) == []

    def test_no_input_returns_empty(self):
        result = _make_audit_result(0, parsed=None)
        assert suggest_repairs(result) == []

    def test_identical_fields_returns_empty(self):
        parsed = _make_parsed_ref(0, title="Same", year=2020)
        record = _make_resolved_record(title="Same", year=2020)
        result = _make_audit_result(0, parsed=parsed, record=record)
        repairs = suggest_repairs(result)
        # Only fields that differ should appear
        assert all(r["field"] != "title" and r["field"] != "year" for r in repairs)

    def test_differing_title(self):
        parsed = _make_parsed_ref(0, title="Old Title")
        record = _make_resolved_record(title="New Title")
        result = _make_audit_result(0, parsed=parsed, record=record)
        repairs = suggest_repairs(result)
        title_repairs = [r for r in repairs if r["field"] == "title"]
        assert len(title_repairs) == 1
        assert title_repairs[0]["old"] == "Old Title"
        assert title_repairs[0]["new"] == "New Title"
        assert title_repairs[0]["source"] == "crossref"

    def test_differing_year(self):
        parsed = _make_parsed_ref(0, year=2019)
        record = _make_resolved_record(year=2020)
        result = _make_audit_result(0, parsed=parsed, record=record)
        repairs = suggest_repairs(result)
        year_repairs = [r for r in repairs if r["field"] == "year"]
        assert len(year_repairs) == 1
        assert year_repairs[0]["old"] == 2019
        assert year_repairs[0]["new"] == 2020

    def test_differing_authors(self):
        parsed = _make_parsed_ref(0, authors=["Old Author"])
        record = _make_resolved_record(authors=[{"family": "New", "given": "Author"}])
        result = _make_audit_result(0, parsed=parsed, record=record)
        repairs = suggest_repairs(result)
        author_repairs = [r for r in repairs if r["field"] == "authors"]
        assert len(author_repairs) == 1
        assert author_repairs[0]["old"] == ["Old Author"]
        assert author_repairs[0]["new"] == ["New"]

    def test_none_new_value_excluded(self):
        parsed = _make_parsed_ref(0, title="Has Title")
        record = _make_resolved_record(title=None)
        result = _make_audit_result(0, parsed=parsed, record=record)
        repairs = suggest_repairs(result)
        title_repairs = [r for r in repairs if r["field"] == "title"]
        assert len(title_repairs) == 0

    def test_source_url_included(self):
        parsed = _make_parsed_ref(0, doi="10.1111/old")
        record = _make_resolved_record(doi="10.2222/new", source_url="https://api.crossref.org/works/10.2222/new")
        result = _make_audit_result(0, parsed=parsed, record=record)
        repairs = suggest_repairs(result)
        doi_repairs = [r for r in repairs if r["field"] == "doi"]
        assert len(doi_repairs) == 1
        assert doi_repairs[0]["source_url"] == "https://api.crossref.org/works/10.2222/new"


class TestMakeKey:
    def test_basic_key(self):
        record = _make_resolved_record(
            authors=[{"family": "Smith", "given": "John"}],
            year=2020,
            title="Soil Consolidation Analysis",
        )
        key = make_key(record)
        assert key == "Smith2020Soil"

    def test_no_authors(self):
        record = _make_resolved_record(authors=[], year=2020, title="Test")
        key = make_key(record)
        assert key == "unknown2020Test"

    def test_no_year(self):
        record = _make_resolved_record(authors=[{"family": "Doe", "given": "Jane"}], year=None, title="Test")
        key = make_key(record)
        assert key == "DoenodateTest"

    def test_special_chars_removed(self):
        record = _make_resolved_record(
            authors=[{"family": "O'Connor", "given": "J."}],
            year=2020,
            title="Heat & Mass Transfer",
        )
        key = make_key(record)
        assert key == "OConnor2020Heat"

    def test_empty_title(self):
        record = _make_resolved_record(authors=[{"family": "A", "given": "B"}], year=2020, title="")
        key = make_key(record)
        assert key == "A2020untitled"


class TestBuildBibtex:
    def test_basic_entry(self):
        record = _make_resolved_record(
            authors=[{"family": "Smith", "given": "John"}],
            year=2020,
            title="Test Title",
            journal="Test Journal",
        )
        key = "Smith2020Test"
        bib = build_bibtex(record, key)
        assert bib.startswith("@article{Smith2020Test,")
        assert "title = {Test Title}" in bib
        assert "author = {Smith, John}" in bib
        assert "year = {2020}" in bib
        assert "journal = {Test Journal}" in bib
        assert bib.endswith("}")

    def test_special_chars_escaped(self):
        record = _make_resolved_record(
            title="A & B: Heat & Mass Transfer",
            authors=[{"family": "Smith", "given": "J."}],
        )
        bib = build_bibtex(record, "key")
        assert r"\&" in bib

    def test_optional_fields(self):
        record = _make_resolved_record(
            volume="5",
            issue="2",
            pages="100-110",
            publisher="Elsevier",
            doi="10.1234/test",
            url="https://example.com",
        )
        bib = build_bibtex(record, "key")
        assert "volume = {5}" in bib
        assert "number = {2}" in bib
        assert "pages = {100-110}" in bib
        assert "publisher = {Elsevier}" in bib
        assert "doi = {10.1234/test}" in bib
        assert "url = {https://example.com}" in bib


class TestBuildRis:
    def test_basic_entry(self):
        record = _make_resolved_record(
            title="Test Title",
            authors=[{"family": "Smith", "given": "John"}],
            year=2020,
            journal="Test Journal",
        )
        ris = build_ris(record)
        assert ris.startswith("TY  - JOUR")
        assert "TI  - Test Title" in ris
        assert "AU  - Smith, John" in ris
        assert "PY  - 2020" in ris
        assert "JO  - Test Journal" in ris
        assert ris.endswith("ER  - ")

    def test_pages_split(self):
        record = _make_resolved_record(pages="100-110")
        ris = build_ris(record)
        assert "SP  - 100" in ris
        assert "EP  - 110" in ris

    def test_single_page(self):
        record = _make_resolved_record(pages="100")
        ris = build_ris(record)
        assert "SP  - 100" in ris
        assert "EP" not in ris


class TestBuildCsljson:
    def test_basic_entry(self):
        record = _make_resolved_record(
            title="Test Title",
            authors=[{"family": "Smith", "given": "John"}],
            year=2020,
            journal="Test Journal",
        )
        csl = build_csljson(record)
        assert csl["type"] == "article-journal"
        assert csl["title"] == "Test Title"
        assert csl["author"] == [{"family": "Smith", "given": "John"}]
        assert csl["issued"] == {"date-parts": [[2020]]}
        assert csl["container-title"] == "Test Journal"

    def test_optional_fields(self):
        record = _make_resolved_record(
            volume="5",
            issue="2",
            pages="100-110",
            publisher="Elsevier",
            doi="10.1234/test",
            url="https://example.com",
            abstract="Test abstract",
        )
        csl = build_csljson(record)
        assert csl["volume"] == "5"
        assert csl["issue"] == "2"
        assert csl["page"] == "100-110"
        assert csl["publisher"] == "Elsevier"
        assert csl["DOI"] == "10.1234/test"
        assert csl["URL"] == "https://example.com"
        assert csl["abstract"] == "Test abstract"


class TestWriteRepairs:
    def test_writes_all_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = [
                _make_audit_result(0),
                _make_audit_result(1, parsed=_make_parsed_ref(1, title="Entry 2")),
            ]
            paths = write_repairs(results, tmp)
            assert set(paths.keys()) == {"bib", "ris", "csljson", "log"}
            for p in paths.values():
                assert Path(p).exists()

    def test_bib_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = [_make_audit_result(0)]
            paths = write_repairs(results, tmp)
            content = Path(paths["bib"]).read_text()
            assert "@article{" in content
            assert "title = {Resolved Title}" in content

    def test_ris_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = [_make_audit_result(0)]
            paths = write_repairs(results, tmp)
            content = Path(paths["ris"]).read_text()
            assert "TY  - JOUR" in content
            assert "TI  - Resolved Title" in content

    def test_csljson_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = [_make_audit_result(0)]
            paths = write_repairs(results, tmp)
            content = Path(paths["csljson"]).read_text()
            data = json.loads(content)
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["title"] == "Resolved Title"

    def test_log_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            parsed = _make_parsed_ref(0, title="Old", year=2019)
            record = _make_resolved_record(title="New", year=2020)
            results = [_make_audit_result(0, parsed=parsed, record=record)]
            paths = write_repairs(results, tmp)
            content = Path(paths["log"]).read_text()
            log = json.loads(content)
            assert isinstance(log, list)
            assert len(log) >= 2  # title and year at minimum
            for entry in log:
                assert "entry_index" in entry
                assert "field" in entry
                assert "old" in entry
                assert "new" in entry
                assert "source" in entry
                assert "evidence_url" in entry
                assert "ledger_key" in entry

    def test_force_false_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = [_make_audit_result(0)]
            write_repairs(results, tmp, force=False)
            # Second call should create .1 files
            paths2 = write_repairs(results, tmp, force=False)
            assert ".1" in paths2["bib"]
            assert ".1" in paths2["ris"]
            assert ".1" in paths2["csljson"]
            assert ".1" in paths2["log"]

    def test_force_true_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = [_make_audit_result(0)]
            paths1 = write_repairs(results, tmp, force=False)
            paths2 = write_repairs(results, tmp, force=True)
            assert paths1 == paths2  # Same paths, overwritten

    def test_never_modifies_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = [_make_audit_result(0)]
            # Write to a subdirectory, ensure no input files touched
            write_repairs(results, Path(tmp) / "out")
            # Input directory should be untouched
            assert not (Path(tmp) / "repaired.bib").exists()

    def test_empty_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_repairs([], tmp)
            # Files may not be created if no results
            for p in paths.values():
                # Path returned but file may be empty or not exist
                pass

    def test_deterministic_output(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            results = [_make_audit_result(i) for i in range(3)]
            write_repairs(results, tmp1)
            write_repairs(results, tmp2)
            # Compare content
            for name in ["repaired.bib", "repaired.ris", "repaired.csl.json", "repair_log.json"]:
                c1 = Path(tmp1, name).read_text()
                c2 = Path(tmp2, name).read_text()
                assert c1 == c2, f"{name} not deterministic"


class TestCslRoundTrip:
    """Test CSL-JSON parse -> audit -> repair -> CSL-JSON emit round-trip."""

    def test_csl_round_trip(self):
        """Parse CSL-JSON, audit, repair, emit CSL-JSON - should produce valid output."""
        # Create CSL-JSON input
        csl_input = [{
            "type": "article-journal",
            "title": "Test Article on Soil Mechanics",
            "author": [{"family": "Smith", "given": "John"}, {"family": "Doe", "given": "Jane"}],
            "issued": {"date-parts": [[2020]]},
            "container-title": "Journal of Geotechnical Engineering",
            "volume": "15",
            "issue": "3",
            "page": "100-115",
            "DOI": "10.1234/test.2020.001",
            "publisher": "Test Publisher",
        }]

        # Parse
        import json
        from veridex import api
        from veridex.httpclient import Response

        # Mock transport that returns a matching record (Crossref format uses 'issued')
        def fake_transport(url, timeout=None):
            mock_response = {
                "message": {
                    "items": [{
                        "DOI": "10.1234/test.2020.001",
                        "title": ["Test Article on Soil Mechanics"],
                        "author": [{"family": "Smith", "given": "John"}, {"family": "Doe", "given": "Jane"}],
                        "issued": {"date-parts": [[2020]]},
                        "container-title": ["Journal of Geotechnical Engineering"],
                        "volume": "15",
                        "issue": "3",
                        "page": "100-115",
                        "publisher": "Test Publisher",
                        "type": "journal-article"
                    }]
                }
            }
            return Response(url=url, status=200, body=json.dumps(mock_response).encode(), from_cache=False)

        import veridex.api as api_module
        original_transport = api_module.TRANSPORT
        api_module.TRANSPORT = fake_transport

        try:
            refs = api.parse_references(json.dumps(csl_input), fmt="csl-json")
            assert len(refs) == 1
            assert refs[0].title == "Test Article on Soil Mechanics"
            assert refs[0].doi == "10.1234/test.2020.001"

            # Audit
            results = api.audit_references(json.dumps(csl_input), fmt="csl-json", sources=["crossref"])
            assert len(results) == 1
            # Note: status may be VERIFIED or VERIFIED_WITH_WARNINGS depending on minor differences
            assert results[0].status in ("VERIFIED", "VERIFIED_WITH_WARNINGS")

            # Repair
            from veridex import repair
            with tempfile.TemporaryDirectory() as tmp:
                written = repair.write_repairs(results, tmp, force=True)
                assert "csljson" in written

                # Verify CSL-JSON output
                with open(written["csljson"]) as f:
                    output_csl = json.load(f)

                assert isinstance(output_csl, list)
                assert len(output_csl) == 1
                out = output_csl[0]
                assert out["type"] == "article-journal"
                assert out["title"] == "Test Article on Soil Mechanics"
                assert out["author"] == [{"family": "Smith", "given": "John"}, {"family": "Doe", "given": "Jane"}]
                assert out["issued"] == {"date-parts": [[2020]]}
                assert out["container-title"] == "Journal of Geotechnical Engineering"
                assert out["volume"] == "15"
                assert out["issue"] == "3"
                assert out["page"] == "100-115"
                assert out["DOI"] == "10.1234/test.2020.001"
                assert out["publisher"] == "Test Publisher"
        finally:
            api_module.TRANSPORT = original_transport

    def test_csl_round_trip_with_repairs(self):
        """Round-trip with actual repairs (parsed differs from resolved)."""
        csl_input = [{
            "type": "article-journal",
            "title": "Wrong Title in Input",
            "author": [{"family": "Wrong", "given": "Author"}],
            "issued": {"date-parts": [[2019]]},
            "container-title": "Wrong Journal",
            "DOI": "10.1234/test.2020.001",
        }]

        import json
        from veridex import api
        from veridex.httpclient import Response

        def fake_transport(url, timeout=None):
            mock_response = {
                "message": {
                    "items": [{
                        "DOI": "10.1234/test.2020.001",
                        "title": ["Correct Title from Source"],
                        "author": [{"family": "Correct", "given": "Author"}],
                        "issued": {"date-parts": [[2020]]},
                        "container-title": ["Correct Journal"],
                        "volume": "10",
                        "issue": "2",
                        "page": "50-60",
                        "publisher": "Correct Publisher",
                        "type": "journal-article"
                    }]
                }
            }
            return Response(url=url, status=200, body=json.dumps(mock_response).encode(), from_cache=False)

        import veridex.api as api_module
        original_transport = api_module.TRANSPORT
        api_module.TRANSPORT = fake_transport

        try:
            refs = api.parse_references(json.dumps(csl_input), fmt="csl-json")
            results = api.audit_references(json.dumps(csl_input), fmt="csl-json", sources=["crossref"])

            # Should have mismatch flags
            assert results[0].status == "MISMATCH"
            assert "mismatch_title" in results[0].flags
            assert "author_mismatch" in results[0].flags

            from veridex import repair
            with tempfile.TemporaryDirectory() as tmp:
                written = repair.write_repairs(results, tmp, force=True)
                with open(written["csljson"]) as f:
                    output_csl = json.load(f)

                # Output should have CORRECTED values from the resolved record
                out = output_csl[0]
                assert out["title"] == "Correct Title from Source"
                assert out["author"] == [{"family": "Correct", "given": "Author"}]
                assert out["issued"] == {"date-parts": [[2020]]}
                assert out["container-title"] == "Correct Journal"
                assert out["volume"] == "10"
                assert out["issue"] == "2"
                assert out["page"] == "50-60"
                assert out["publisher"] == "Correct Publisher"

                # Repair log should document the changes
                with open(written["log"]) as f:
                    log = json.load(f)
                fields_changed = {entry["field"] for entry in log}
                assert "title" in fields_changed
                assert "year" in fields_changed
                assert "authors" in fields_changed
                assert "journal" in fields_changed
        finally:
            api_module.TRANSPORT = original_transport


if __name__ == "__main__":
    pytest.main([__file__, "-v"])