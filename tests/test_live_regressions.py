# Copyright (c) 2026 Madeesh P. Nissanka. MIT License.
"""Regression tests for defects found by running the real CLI on live data."""

from __future__ import annotations

import tempfile
from pathlib import Path

from veridex import api
from veridex.matching import compare_fields
from veridex.models import ParsedReference, ResolvedRecord


def test_missing_input_venue_volume_pages_are_not_mismatches():
    ref = ParsedReference(title="A title", year=2020)
    rec = ResolvedRecord(title="A title", year=2020, journal="Journal of Test", volume="3", pages="10-20")
    flags = compare_fields(ref, rec)
    assert "venue_mismatch" not in flags
    assert "volume_mismatch" not in flags
    assert "pages_mismatch" not in flags


def test_present_but_different_fields_still_flag():
    ref = ParsedReference(title="A title", year=2020, journal="Alpha Quarterly", volume="1", pages="1-5")
    rec = ResolvedRecord(title="A title", year=2020, journal="Zeta Letters", volume="2", pages="9-12")
    flags = compare_fields(ref, rec)
    assert flags.get("venue_mismatch") is True
    assert flags.get("volume_mismatch") is True
    assert flags.get("pages_mismatch") is True


def test_write_report_format_all_writes_every_format():
    with tempfile.TemporaryDirectory() as tmp:
        first = api.write_report([], tmp, fmt="all")
        names = {p.name for p in Path(tmp).iterdir()}
        assert {"report.json", "report.md", "report.html", "report.csv", "report.sarif"} <= names
        assert Path(first).exists()
