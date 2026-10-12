# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for the offline retraction/update loader. Stdlib only, no network."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from veridex import api
from veridex.httpclient import Response
from veridex.models import AuditResult, ParsedReference, ResolvedRecord, Status
from veridex.retractions import apply_retractions, load_retractions


def _write(tmp: str, name: str, content: str) -> Path:
    path = Path(tmp) / name
    path.write_text(content, encoding="utf-8")
    return path


def _result(idx: int, doi: str | None, status: str = Status.VERIFIED) -> AuditResult:
    ref = ParsedReference(index=idx, title="Sample title", year=2018, doi=doi)
    rec = None
    if doi:
        rec = ResolvedRecord(source="crossref", source_id=doi, title="Sample title",
                             year=2018, doi=doi)
    return AuditResult(index=idx, input=ref, record=rec, status=status, flags=[])


class TestLoadRetractionsCsv:
    def test_basic_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                tmp,
                "rw.csv",
                "Original Paper DOI,Reason,RetractionDate\n"
                "10.1000/ABC,Data fabrication,2019-05-01\n"
                "https://doi.org/10.2000/xyz,Plagiarism,2020-01-02\n",
            )
            table = load_retractions(path)
            assert "10.1000/abc" in table
            assert "10.2000/xyz" in table
            notice = table["10.1000/abc"][0]
            assert notice["kind"] == "retraction"
            assert notice["reason"] == "Data fabrication"
            assert notice["date"] == "2019-05-01"
            assert notice["source"] == "retraction-watch"

    def test_csv_with_nature_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                tmp,
                "rw.csv",
                "DOI,RetractionNature\n10.1000/a,Correction\n10.1000/b,Retraction\n",
            )
            table = load_retractions(path)
            assert table["10.1000/a"][0]["kind"] == "correction"
            assert table["10.1000/b"][0]["kind"] == "retraction"

    def test_csv_rows_without_doi_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "rw.csv", "Original Paper DOI,Reason\n,missing\n10.1/ok,fine\n")
            table = load_retractions(path)
            assert list(table) == ["10.1/ok"]


class TestLoadRetractionsJson:
    def test_flat_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                tmp,
                "r.json",
                json.dumps([
                    {"doi": "10.1000/a", "kind": "retraction", "reason": "error"},
                    {"doi": "10.1000/b", "kind": "correction"},
                ]),
            )
            table = load_retractions(path)
            assert table["10.1000/a"][0]["kind"] == "retraction"
            assert table["10.1000/b"][0]["kind"] == "correction"
            assert table["10.1000/a"][0]["reason"] == "error"

    def test_crossref_update_style(self):
        payload = {
            "items": [
                {
                    "DOI": "10.1000/orig",
                    "update-to": [
                        {"DOI": "10.1000/orig", "type": "retraction", "URL": "https://x"}
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "cr.json", json.dumps(payload))
            table = load_retractions(path)
            assert "10.1000/orig" in table
            assert table["10.1000/orig"][0]["kind"] == "retraction"

    def test_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                tmp,
                "r.jsonl",
                '{"doi": "10.1000/a", "kind": "withdrawal"}\n'
                "\n"
                '{"doi": "10.1000/b", "kind": "expression of concern"}\n',
            )
            table = load_retractions(path)
            assert table["10.1000/a"][0]["kind"] == "withdrawal"
            assert table["10.1000/b"][0]["kind"] == "expression_of_concern"

    def test_sniff_json_with_unknown_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "data.txt", json.dumps([{"doi": "10.1/a"}]))
            table = load_retractions(path)
            assert "10.1/a" in table

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_retractions("/nonexistent/definitely-missing.csv")


class TestApplyRetractions:
    def test_retraction_flips_status(self):
        results = [_result(0, "10.1000/a"), _result(1, "10.1000/b")]
        table = {"10.1000/a": [{"kind": "retraction", "source": "rw", "url": "", "label": "Retracted", "target": "work"}]}
        changed = apply_retractions(results, table)
        assert changed == 1
        assert results[0].status == Status.RETRACTED
        assert "retracted" in results[0].flags
        assert results[0].integrity
        assert results[1].status == Status.VERIFIED
        assert results[1].flags == []

    def test_correction_does_not_retract(self):
        results = [_result(0, "10.1000/a")]
        table = {"10.1000/a": [{"kind": "correction", "source": "rw", "url": "", "label": "Correction", "target": "work"}]}
        apply_retractions(results, table)
        assert results[0].status == Status.VERIFIED
        assert "retracted" not in results[0].flags
        assert results[0].integrity

    def test_no_duplicate_notices(self):
        notice = {"kind": "retraction", "source": "rw", "url": "", "label": "Retracted", "target": "work"}
        results = [_result(0, "10.1000/a")]
        results[0].integrity = [dict(notice)]
        apply_retractions(results, {"10.1000/a": [dict(notice)]})
        assert len(results[0].integrity) == 1

    def test_unmatched_doi_untouched(self):
        results = [_result(0, "10.9999/other")]
        changed = apply_retractions(results, {"10.1000/a": [{"kind": "retraction"}]})
        assert changed == 0
        assert results[0].status == Status.VERIFIED

    def test_matches_input_doi_when_record_doi_differs(self):
        """Retraction is keyed on the cited DOI even if a source resolved a
        different record DOI (e.g. a preprint/version mismatch)."""
        ref = ParsedReference(index=0, title="Sample", doi="10.1000/cited")
        rec = ResolvedRecord(source="crossref", source_id="x", title="Other", doi="10.5555/other")
        result = AuditResult(index=0, input=ref, record=rec, status=Status.MISMATCH, flags=[])
        changed = apply_retractions(
            [result], {"10.1000/cited": [{"kind": "retraction", "source": "rw", "url": "", "label": "Retracted", "target": "work"}]}
        )
        assert changed == 1
        assert result.status == Status.RETRACTED
        assert "retracted" in result.flags


class TestRetractionsEndToEnd:
    def test_audit_applies_offline_retractions(self, monkeypatch):
        hit = json.dumps(
            {
                "status": "ok",
                "message": {
                    "DOI": "10.1000/example.2018.001",
                    "title": ["Soil consolidation settlement"],
                    "author": [{"family": "Smith", "given": "A."}],
                    "issued": {"date-parts": [[2018]]},
                    "container-title": ["Geotechnical Journal"],
                },
            }
        ).encode()

        def fake(url: str, timeout: float | None = None) -> Response:
            if url.startswith("https://api.crossref.org/works/10."):
                return Response(url=url, status=200, body=hit, from_cache=False)
            return Response(url=url, status=200, body=b'{"message": {"items": []}}', from_cache=False)

        monkeypatch.setattr(api, "TRANSPORT", fake)
        with tempfile.TemporaryDirectory() as tmp:
            retr = _write(tmp, "rw.csv", "Original Paper DOI,Reason\n10.1000/example.2018.001,Fabricated data\n")
            results = api.audit_references(
                "examples/refs.bib", transport=fake, retraction_file=str(retr)
            )
            assert results
            target = [r for r in results if r.input and r.input.doi == "10.1000/example.2018.001"]
            assert target, "expected the example DOI in results"
            assert target[0].status == Status.RETRACTED
            assert "retracted" in target[0].flags


class TestRetractionsCli:
    def test_retraction_file_flag_is_wired(self, monkeypatch, capsys):
        from veridex.cli import EXIT_OK, main

        hit = json.dumps(
            {
                "status": "ok",
                "message": {
                    "DOI": "10.1000/example.2018.001",
                    "title": ["Soil consolidation settlement"],
                    "author": [{"family": "Smith", "given": "A."}],
                    "issued": {"date-parts": [[2018]]},
                    "container-title": ["Geotechnical Journal"],
                },
            }
        ).encode()

        def fake(url: str, timeout: float | None = None) -> Response:
            if url.startswith("https://api.crossref.org/works/10."):
                return Response(url=url, status=200, body=hit, from_cache=False)
            return Response(url=url, status=200, body=b'{"message": {"items": []}}', from_cache=False)

        monkeypatch.setattr(api, "TRANSPORT", fake)
        with tempfile.TemporaryDirectory() as tmp:
            retr = _write(tmp, "rw.csv", "Original Paper DOI\n10.1000/example.2018.001\n")
            code = main([
                "--json", "audit", "examples/refs.bib", "--no-cache",
                "--retraction-file", str(retr),
            ])
            assert code == EXIT_OK
            payload = json.loads(capsys.readouterr().out)
            statuses = {r["status"] for r in payload["results"]}
            assert Status.RETRACTED in statuses

