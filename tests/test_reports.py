# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for reports module."""
from __future__ import annotations

import csv
import json
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

from veridex.models import AuditResult, ParsedReference, ResolvedRecord, Status
from veridex.reports import render_report, render_dashboard, summary, render_cross_check_report, render_cross_check_report_html


def _make_parsed_ref(idx: int, **kwargs) -> ParsedReference:
    defaults = {
        "index": idx,
        "title": f"Input Title {idx}",
        "authors": [f"Author {idx}A", f"Author {idx}B"],
        "year": 2020 + idx,
        "journal": f"Input Journal {idx}",
        "doi": f"10.1234/input{idx}",
    }
    defaults.update(kwargs)
    return ParsedReference(**defaults)


def _make_resolved_record(idx: int, **kwargs) -> ResolvedRecord:
    defaults = {
        "source": "crossref",
        "source_id": f"rec{idx}",
        "title": f"Resolved Title {idx}",
        "authors": [{"family": f"Author{idx}A", "given": "First"}, {"family": f"Author{idx}B", "given": "Second"}],
        "year": 2020 + idx,
        "journal": f"Resolved Journal {idx}",
        "volume": f"{10+idx}",
        "issue": f"{2+idx}",
        "pages": f"{100+idx*10}-{110+idx*10}",
        "publisher": f"Publisher {idx}",
        "doi": f"10.5678/resolved{idx}",
        "url": f"https://example.com/resolved{idx}",
        "source_url": f"https://api.crossref.org/works/10.5678/resolved{idx}",
        "abstract": f"Abstract for entry {idx}",
    }
    defaults.update(kwargs)
    return ResolvedRecord(**defaults)


def _make_audit_result(idx: int, **kwargs) -> AuditResult:
    parsed = _make_parsed_ref(idx)
    record = _make_resolved_record(idx)
    defaults = {
        "index": idx,
        "input": parsed,
        "record": record,
        "status": Status.VERIFIED,
        "flags": [],
        "fabrication": {"score": 0.1, "signals": []},
        "integrity": [],
        "evidence": [],
        "notes": [],
    }
    defaults.update(kwargs)
    return AuditResult(**defaults)


def _make_results_with_variations() -> tuple[list[AuditResult], list[ParsedReference]]:
    """Create a diverse set of results for testing."""
    results = []
    entries = []
    for i in range(5):
        parsed = _make_parsed_ref(i)
        entries.append(parsed)
        if i == 0:
            result = _make_audit_result(i, status=Status.VERIFIED, flags=["year_off_by_one"])
        elif i == 1:
            result = _make_audit_result(i, status=Status.VERIFIED_WITH_WARNINGS, flags=["author_mismatch"])
        elif i == 2:
            result = _make_audit_result(i, status=Status.MISMATCH, flags=["title_low_similarity", "venue_mismatch"])
        elif i == 3:
            result = _make_audit_result(i, status=Status.RETRACTED, flags=["retracted"])
            result.integrity = [{"kind": "retraction", "target": "work", "url": "https://example.com/retraction", "label": "Retracted"}]
            result.fabrication = {"score": 0.8, "signals": [{"code": "retracted", "weight": 0.5}]}
        else:
            result = _make_audit_result(i, status=Status.NOT_FOUND, flags=["no_matching_record"])
            result.fabrication = {"score": 0.9, "signals": [{"code": "no_matching_record", "weight": 0.35}]}
        result.evidence = []
        results.append(result)
    return results, entries


class TestSummary:
    def test_counts_all_statuses(self):
        results, _ = _make_results_with_variations()
        summ = summary(results)
        assert summ["total"] == 5
        assert summ[Status.VERIFIED] == 1
        assert summ[Status.VERIFIED_WITH_WARNINGS] == 1
        assert summ[Status.MISMATCH] == 1
        assert summ[Status.RETRACTED] == 1
        assert summ[Status.NOT_FOUND] == 1

    def test_empty_results(self):
        summ = summary([])
        assert summ["total"] == 0
        for status in [
            Status.VERIFIED, Status.VERIFIED_WITH_WARNINGS, Status.MISMATCH,
            Status.DOI_NOT_FOUND, Status.NOT_FOUND, Status.NO_DOI_MATCHED,
            Status.UNREACHABLE, Status.AMBIGUOUS, Status.RETRACTED, Status.ERROR
        ]:
            assert summ.get(status, 0) == 0


class TestRenderJson:
    def test_writes_valid_json(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            render_report(results, entries, "json", out, {"test": "meta"})
            assert out.exists()
            data = json.loads(out.read_text())
            assert "meta" in data
            assert "summary" in data
            assert "results" in data
            assert "entries" in data
            assert data["meta"]["tool"] == "veridex"
            assert data["meta"]["version"] == "0.3.0"
            assert len(data["results"]) == 5
            assert len(data["entries"]) == 5

    def test_deterministic_output(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            out1 = Path(tmp1) / "report.json"
            out2 = Path(tmp2) / "report.json"
            render_report(results, entries, "json", out1)
            render_report(results, entries, "json", out2)
            assert out1.read_text() == out2.read_text()


class TestRenderCsv:
    def test_writes_valid_csv(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.csv"
            render_report(results, entries, "csv", out)
            assert out.exists()
            content = out.read_text()
            lines = content.strip().split("\n")
            assert len(lines) == 6  # header + 5 rows
            header = lines[0].split(",")
            # Check v0.1 header compatibility
            for h in ["index", "status", "title", "authors", "year", "journal", "doi", "flags", "fabrication_score"]:
                assert h in header
            # Check new columns
            for h in ["volume", "issue", "pages", "publisher", "url", "source", "source_url", "verdict", "retracted", "near_duplicate", "weak_context"]:
                assert h in header

    def test_csv_values(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.csv"
            render_report(results, entries, "csv", out)
            with open(out, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 5
            # Check first row (VERIFIED)
            row0 = rows[0]
            assert row0["index"] == "0"
            assert row0["status"] == Status.VERIFIED
            assert row0["verdict"] == "PASS"
            assert row0["retracted"] == "false"
            # Check retracted row
            row3 = rows[3]
            assert row3["status"] == Status.RETRACTED
            assert row3["verdict"] == "FAIL"
            assert row3["retracted"] == "true"

    def test_deterministic_output(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            out1 = Path(tmp1) / "report.csv"
            out2 = Path(tmp2) / "report.csv"
            render_report(results, entries, "csv", out1)
            render_report(results, entries, "csv", out2)
            assert out1.read_text() == out2.read_text()


class TestRenderMd:
    def test_writes_valid_markdown(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            render_report(results, entries, "md", out)
            assert out.exists()
            content = out.read_text()
            assert "# VERIDEX Audit Report" in content
            assert "## Executive Summary" in content
            assert "## Per-Entry Results" in content
            assert "Entry 0:" in content
            assert "Entry 4:" in content
            assert "VERIFIED" in content
            assert "RETRACTED" in content

    def test_deterministic_output(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            out1 = Path(tmp1) / "report.md"
            out2 = Path(tmp2) / "report.md"
            render_report(results, entries, "md", out1)
            render_report(results, entries, "md", out2)
            assert out1.read_text() == out2.read_text()


class TestRenderHtml:
    def test_writes_valid_html(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            render_report(results, entries, "html", out)
            assert out.exists()
            content = out.read_text()
            # Parse with HTMLParser to ensure well-formed
            parser = HTMLParser()
            parser.feed(content)
            # Check key elements
            assert "<!DOCTYPE html>" in content
            assert "<title>VERIDEX Audit Report</title>" in content
            assert "Executive Summary" in content
            assert "Per-Entry Results" in content
            assert "badge-verified" in content
            assert "badge-retracted" in content
            assert "Fabrication Score" in content

    def test_inline_css(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            render_report(results, entries, "html", out)
            content = out.read_text()
            assert "<style>" in content
            assert "</style>" in content
            # Should not have external CSS links
            assert "href=" not in content or "stylesheet" not in content

    def test_deterministic_output(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            out1 = Path(tmp1) / "report.html"
            out2 = Path(tmp2) / "report.html"
            render_report(results, entries, "html", out1)
            render_report(results, entries, "html", out2)
            assert out1.read_text() == out2.read_text()


class TestRenderSarif:
    def test_writes_valid_sarif(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.sarif"
            render_report(results, entries, "sarif", out)
            assert out.exists()
            data = json.loads(out.read_text())
            # Check SARIF 2.1.0 structure
            assert data["version"] == "2.1.0"
            assert "$schema" in data
            assert "runs" in data
            assert len(data["runs"]) == 1
            run = data["runs"][0]
            assert "tool" in run
            assert run["tool"]["driver"]["name"] == "veridex"
            assert "rules" in run["tool"]["driver"]
            assert len(run["tool"]["driver"]["rules"]) == 3  # fabrication, flags, retraction
            assert "results" in run
            assert len(run["results"]) > 0  # Should have results for each entry

    def test_sarif_rules(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.sarif"
            render_report(results, entries, "sarif", out)
            data = json.loads(out.read_text())
            rules = {r["id"]: r for r in data["runs"][0]["tool"]["driver"]["rules"]}
            assert "fabrication-score" in rules
            assert "flags" in rules
            assert "retraction" in rules
            # Check rule levels
            assert rules["fabrication-score"]["defaultConfiguration"]["level"] == "warning"
            assert rules["flags"]["defaultConfiguration"]["level"] == "note"
            assert rules["retraction"]["defaultConfiguration"]["level"] == "error"

    def test_sarif_results_levels(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.sarif"
            render_report(results, entries, "sarif", out)
            data = json.loads(out.read_text())
            sarif_results = data["runs"][0]["results"]
            # Check that we have results for fabrication score, flags, and retraction
            rule_ids = {r["ruleId"] for r in sarif_results}
            assert "fabrication-score" in rule_ids
            assert "flags" in rule_ids
            assert "retraction" in rule_ids
            # Check levels are error/warning/note
            for r in sarif_results:
                assert r["level"] in ("error", "warning", "note")

    def test_deterministic_output(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            out1 = Path(tmp1) / "report.sarif"
            out2 = Path(tmp2) / "report.sarif"
            render_report(results, entries, "sarif", out1)
            render_report(results, entries, "sarif", out2)
            assert out1.read_text() == out2.read_text()


class TestRenderDashboard:
    def test_writes_valid_dashboard(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dashboard.html"
            render_dashboard(results, entries, out, {"tool": "veridex", "version": "0.3.0"})
            assert out.exists()
            content = out.read_text()
            parser = HTMLParser()
            parser.feed(content)
            assert "<!DOCTYPE html>" in content
            assert "VERIDEX Review Dashboard" in content
            assert "const ROWS" in content
            assert "filter-status" in content
            assert "filter-decision" in content
            assert "filter-search" in content
            assert "exportJSON" in content
            assert "exportCSV" in content
            assert "Render the" not in content

    def test_embeds_rows_json(self):
        import re
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dashboard.html"
            render_dashboard(results, entries, out, {})
            content = out.read_text()
            match = re.search(r"const ROWS = (\[.*?\]);", content, re.S)
            assert match, "ROWS JSON not embedded"
            data = json.loads(match.group(1))
            assert len(data) == 5
            assert all("decision" in r and r["decision"] == "pending" for r in data)
            assert all("notes" in r for r in data)
            statuses = {r["status"] for r in data}
            assert Status.VERIFIED in statuses
            assert Status.NOT_FOUND in statuses

    def test_decision_buttons_present(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dashboard.html"
            render_dashboard(results, entries, out, {})
            content = out.read_text()
            assert "setDecision({{" not in content
            assert "row.decision === 'accept'" in content
            assert "localStorage" in content

    def test_no_double_braces_leaked(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dashboard.html"
            render_dashboard(results, entries, out, {})
            content = out.read_text()
            assert "{{" not in content
            assert "}}" not in content

    def test_deterministic_output(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            out1 = Path(tmp1) / "dashboard.html"
            out2 = Path(tmp2) / "dashboard.html"
            render_dashboard(results, entries, out1)
            render_dashboard(results, entries, out2)
            assert out1.read_text() == out2.read_text()


class TestFormatAliases:
    def test_markdown_alias(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            render_report(results, entries, "markdown", out)
            assert out.exists()

    def test_case_insensitive(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            render_report(results, entries, "JSON", out)
            assert out.exists()

    def test_invalid_format_raises(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.xyz"
            with pytest.raises(ValueError):
                render_report(results, entries, "xyz", out)


class TestTraceabilityFields:
    """Ensure all output formats include traceability fields."""
    def test_json_has_source_and_evidence(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            render_report(results, entries, "json", out)
            data = json.loads(out.read_text())
            for r in data["results"]:
                if r.get("record"):
                    assert "source" in r["record"]
                    assert "source_url" in r["record"]
                assert "evidence" in r

    def test_csv_has_source_columns(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.csv"
            render_report(results, entries, "csv", out)
            with open(out, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            for row in rows:
                assert "source" in row
                assert "source_url" in row

    def test_html_has_source_info(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            render_report(results, entries, "html", out)
            content = out.read_text()
            assert "Source:" in content or "source" in content.lower()

    def test_sarif_has_properties(self):
        results, entries = _make_results_with_variations()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.sarif"
            render_report(results, entries, "sarif", out)
            data = json.loads(out.read_text())
            for r in data["runs"][0]["results"]:
                assert "properties" in r


class TestRenderCrossCheck:
    def test_cross_check_report_md(self):
        results, entries = _make_results_with_variations()
        # Create mock in-text citations
        in_text_citations = [
            {"marker": "[1]", "sentence": "Soil settlement is important [1].", "ref_index": 0},
            {"marker": "[2]", "sentence": "Consolidation theory [2] predicts.", "ref_index": 1},
            {"marker": "[99]", "sentence": "Unknown reference [99].", "ref_index": 99},  # unmatched
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cross_check.md"
            render_cross_check_report(results, entries, in_text_citations, out, {"tool": "veridex", "version": "0.3.0"})
            assert out.exists()
            content = out.read_text()
            assert "# VERIDEX Cross-Check Report" in content
            assert "Unmatched In-Text Citations" in content
            assert "[99]" in content
            assert "Orphan Reference List Entries" in content
            # Entry 2, 3, 4 should be orphans (only 0, 1 are cited) - check for index numbers
            assert "| 2 |" in content or "| 3 |" in content or "| 4 |" in content

    def test_cross_check_report_html(self):
        results, entries = _make_results_with_variations()
        in_text_citations = [
            {"marker": "[1]", "sentence": "Soil settlement is important [1].", "ref_index": 0},
            {"marker": "[2]", "sentence": "Consolidation theory [2] predicts.", "ref_index": 1},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cross_check.html"
            render_cross_check_report_html(results, entries, in_text_citations, out, {"tool": "veridex", "version": "0.3.0"})
            assert out.exists()
            content = out.read_text()
            assert "<!DOCTYPE html>" in content
            assert "VERIDEX Cross-Check Report" in content
            assert "Matched Pairs" in content
            assert "2" in content  # matched count

    def test_cross_check_no_unmatched_no_orphans(self):
        # All entries cited
        results, entries = _make_results_with_variations()
        in_text_citations = [
            {"marker": f"[{i+1}]", "sentence": f"Citation {i+1}.", "ref_index": i}
            for i in range(len(entries))
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cross_check.md"
            render_cross_check_report(results, entries, in_text_citations, out)
            content = out.read_text()
            assert "Unmatched In-Text Citations" not in content
            assert "Orphan Reference List Entries" not in content

    def test_cross_check_weak_context_section(self):
        results, entries = _make_results_with_variations()
        # Modify one result to have weak_context_support flag
        results[0].flags.append("weak_context_support")
        results[0].context = {"[1]": {"score": 0.1, "label": "WEAK", "heuristic": True}}
        in_text_citations = [
            {"marker": "[1]", "sentence": "Soil settlement is important [1].", "ref_index": 0},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cross_check.md"
            render_cross_check_report(results, entries, in_text_citations, out)
            content = out.read_text()
            assert "Weak Context Support" in content
            assert "WEAK" in content or "0.1" in content

    def test_cross_check_deterministic(self):
        results, entries = _make_results_with_variations()
        in_text_citations = [
            {"marker": "[1]", "sentence": "Soil settlement is important [1].", "ref_index": 0},
        ]
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            out1 = Path(tmp1) / "cross_check.md"
            out2 = Path(tmp2) / "cross_check.md"
            render_cross_check_report(results, entries, in_text_citations, out1)
            render_cross_check_report(results, entries, in_text_citations, out2)
            assert out1.read_text() == out2.read_text()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])