# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for fabrication.py."""
from __future__ import annotations

from veridex.models import ParsedReference, ResolvedRecord
from veridex.fabrication import score_fabrication


def test_score_fabrication_no_matching_record():
    """Test no_matching_record signal."""
    ref = ParsedReference(title="Test", year=2020)
    evaluation = {"status": "MISMATCH", "flags": ["no_matching_record"], "scores": {}}
    
    result = score_fabrication(ref, None, evaluation, [])
    assert result["score"] == 0.35
    assert len(result["signals"]) == 1
    assert result["signals"][0]["code"] == "no_matching_record"
    assert result["signals"][0]["weight"] == 0.35


def test_score_fabrication_doi_resolves_to_different_work():
    """Test doi_resolves_to_different_work signal."""
    ref = ParsedReference(title="Test", year=2020)
    evaluation = {"status": "MISMATCH", "flags": ["doi_resolves_to_different_work"], "scores": {}}
    rec = ResolvedRecord(title="Test", year=2020)
    
    result = score_fabrication(ref, rec, evaluation, [])
    assert result["score"] == 0.30
    assert len(result["signals"]) == 1
    assert result["signals"][0]["code"] == "doi_resolves_to_different_work"
    assert result["signals"][0]["weight"] == 0.30


def test_score_fabrication_year_mismatch():
    """Test year_mismatch signal."""
    ref = ParsedReference(title="Test", year=2020)
    evaluation = {"status": "MISMATCH", "flags": ["year_mismatch"], "scores": {}}
    rec = ResolvedRecord(title="Test", year=2022)
    
    result = score_fabrication(ref, rec, evaluation, [])
    assert result["score"] == 0.15
    assert len(result["signals"]) == 1
    assert result["signals"][0]["code"] == "year_mismatch"
    assert result["signals"][0]["weight"] == 0.15


def test_score_fabrication_author_mismatch():
    """Test author_mismatch signal."""
    ref = ParsedReference(title="Test", year=2020)
    evaluation = {"status": "MISMATCH", "flags": ["author_mismatch"], "scores": {}}
    rec = ResolvedRecord(title="Test", year=2020)
    
    result = score_fabrication(ref, rec, evaluation, [])
    assert result["score"] == 0.20
    assert len(result["signals"]) == 1
    assert result["signals"][0]["code"] == "author_mismatch"
    assert result["signals"][0]["weight"] == 0.20


def test_score_fabrication_impossible_date():
    """Test impossible_date signal."""
    ref = ParsedReference(title="Test", year=1400)  # Too old
    evaluation = {"status": "MISMATCH", "flags": ["impossible_date"], "scores": {}}
    rec = ResolvedRecord(title="Test", year=1400)
    
    result = score_fabrication(ref, rec, evaluation, [])
    assert result["score"] == 0.25
    assert len(result["signals"]) == 1
    assert result["signals"][0]["code"] == "impossible_date"
    assert result["signals"][0]["weight"] == 0.25


def test_score_fabrication_implausible_pages():
    """Test implausible_pages signal."""
    ref = ParsedReference(title="Test", year=2020, pages="1000-500")  # start > end
    evaluation = {"status": "MISMATCH", "flags": ["implausible_pages"], "scores": {}}
    rec = ResolvedRecord(title="Test", year=2020, pages="1000-500")
    
    result = score_fabrication(ref, rec, evaluation, [])
    assert result["score"] == 0.10
    assert len(result["signals"]) == 1
    assert result["signals"][0]["code"] == "implausible_pages"
    assert result["signals"][0]["weight"] == 0.10


def test_score_fabrication_venue_not_found():
    """Test venue_not_found signal."""
    ref = ParsedReference(title="Test", year=2020)
    evaluation = {"status": "MISMATCH", "flags": ["venue_not_found"], "scores": {}}
    rec = ResolvedRecord(title="Test", year=2020)
    
    result = score_fabrication(ref, rec, evaluation, [])
    assert result["score"] == 0.15
    assert len(result["signals"]) == 1
    assert result["signals"][0]["code"] == "venue_not_found"
    assert result["signals"][0]["weight"] == 0.15


def test_score_fabrication_doi_format_invalid():
    """Test doi_format_invalid signal."""
    ref = ParsedReference(title="Test", year=2020, doi="invalid-doi")
    evaluation = {"status": "MISMATCH", "flags": ["doi_format_invalid"], "scores": {}}
    rec = ResolvedRecord(title="Test", year=2020, doi="invalid-doi")
    
    result = score_fabrication(ref, rec, evaluation, [])
    assert result["score"] == 0.20
    assert len(result["signals"]) == 1
    assert result["signals"][0]["code"] == "doi_format_invalid"
    assert result["signals"][0]["weight"] == 0.20


def test_score_fabrication_multiple_signals():
    """Test multiple signals are additive and clamped."""
    ref = ParsedReference(title="Test", year=2020)
    # Add multiple flags that sum to more than 1.0
    evaluation = {
        "status": "MISMATCH", 
        "flags": [
            "no_matching_record",      # 0.35
            "doi_resolves_to_different_work",  # 0.30
            "year_mismatch",           # 0.15
            "author_mismatch",         # 0.20
            "impossible_date",         # 0.25
            "implausible_pages",       # 0.10
            "venue_not_found",         # 0.15
            "doi_format_invalid"       # 0.20
            # Sum = 1.70, should be clamped to 1.0
        ], 
        "scores": {}
    }
    rec = ResolvedRecord(title="Test", year=2020)
    
    result = score_fabrication(ref, rec, evaluation, [])
    assert result["score"] == 1.0  # Clamped to maximum
    assert len(result["signals"]) == 8  # One signal per flag


def test_score_fabrication_no_signals():
    """Test zero score when no signals."""
    ref = ParsedReference(title="Test", year=2020)
    evaluation = {"status": "VERIFIED", "flags": [], "scores": {}}  # No flags
    rec = ResolvedRecord(title="Test", year=2020)
    
    result = score_fabrication(ref, rec, evaluation, [])
    assert result["score"] == 0.0
    assert len(result["signals"]) == 0


def test_score_fabrication_partial_signals():
    """Test partial signals sum correctly."""
    ref = ParsedReference(title="Test", year=2020)
    evaluation = {
        "status": "MISMATCH", 
        "flags": [
            "no_matching_record",      # 0.35
            "year_mismatch",           # 0.15
            "author_mismatch",         # 0.20
            # Sum = 0.70
        ], 
        "scores": {}
    }
    rec = ResolvedRecord(title="Test", year=2020)
    
    result = score_fabrication(ref, rec, evaluation, [])
    assert result["score"] == 0.70
    assert len(result["signals"]) == 3


def test_score_fabrication_detail_fields():
    """Test that signals contain correct detail fields."""
    ref = ParsedReference(title="Test", year=2020)
    evaluation = {"status": "MISMATCH", "flags": ["no_matching_record"], "scores": {}}
    rec = ResolvedRecord(title="Test", year=2020)
    
    result = score_fabrication(ref, rec, evaluation, [])
    signal = result["signals"][0]
    
    assert "code" in signal
    assert "weight" in signal
    assert "detail" in signal
    assert signal["code"] == "no_matching_record"
    assert signal["weight"] == 0.35
    assert isinstance(signal["detail"], str)
    assert len(signal["detail"]) > 0