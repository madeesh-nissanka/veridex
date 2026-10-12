# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for matching.py."""
from __future__ import annotations

from veridex.models import ParsedReference, ResolvedRecord
from veridex.matching import (
    normalize_title,
    title_similarity,
    compare_authors,
    compare_fields,
    evaluate,
    find_near_duplicates,
)


def test_normalize_title():
    assert normalize_title("Hello, World!") == "hello world"
    assert normalize_title("  TEST   ") == "test"
    assert normalize_title("") == ""
    assert normalize_title(None) == ""
    assert normalize_title("A B C") == "a b c"
    assert normalize_title("Version 2.0") == "version 2 0"


def test_title_similarity():
    # Identical titles
    assert title_similarity("Hello World", "Hello World") == 1.0
    
    # Completely different - no common letters
    assert title_similarity("abc", "def") == 0.0
    
    # Case insensitive
    assert title_similarity("hello world", "HELLO WORLD") == 1.0
    
    # Punctuation insensitive
    assert title_similarity("Hello, World!", "Hello World") == 1.0
    
    # Empty strings
    assert title_similarity("", "Hello") == 0.0
    assert title_similarity(None, "Hello") == 0.0
    assert title_similarity("", "") == 0.0
    
    # Partial overlap
    sim = title_similarity("The quick brown fox", "The quick brown dog")
    assert 0.0 < sim < 1.0
    
    # Test Jaccard vs SequenceMatcher
    # These should have same words but different order
    sim = title_similarity("cat dog mouse", "dog cat mouse")
    assert sim == 1.0  # Jaccard should be 1.0


def test_compare_authors():
    # Basic matching
    parsed = ["Smith, John"]
    record = [{"family": "Smith", "given": "John"}]
    result = compare_authors(parsed, record)
    assert result["jaccard"] > 0
    assert result["order_ok"] == True
    assert result["first_in_set"] == True
    
    # Multiple authors
    parsed = ["Smith, John", "Doe, Jane"]
    record = [{"family": "Smith", "given": "John"}, {"family": "Doe", "given": "Jane"}]
    result = compare_authors(parsed, record)
    assert result["jaccard"] == 1.0
    assert result["order_ok"] == True
    assert result["first_in_set"] == True
    
    # Author mismatch
    parsed = ["Smith, John"]
    record = [{"family": "Doe", "given": "Jane"}]
    result = compare_authors(parsed, record)
    assert result["jaccard"] == 0.0
    assert result["first_in_set"] == False
    
    # Empty lists
    assert compare_authors([], [])["jaccard"] == 0.0
    assert compare_authors(["Smith"], [])["jaccard"] == 0.0
    assert compare_authors([], [{"family": "Smith"}])["jaccard"] == 0.0
    
    # Initials expansion
    parsed = ["J. Smith"]
    record = [{"family": "Smith", "given": "John"}]
    result = compare_authors(parsed, record)
    assert result["jaccard"] > 0  # Should match through initials expansion
    
    # Diacritic folding
    parsed = ["José García"]
    record = [{"family": "Garcia", "given": "Jose"}]
    result = compare_authors(parsed, record)
    assert result["jaccard"] > 0  # Should match after diacritic folding


def test_compare_fields():
    ref = ParsedReference(
        title="Test",
        year=2020,
        journal="Journal of Test",
        volume="1",
        pages="1-10"
    )
    
    # Exact match
    rec = ResolvedRecord(
        title="Test",
        year=2020,
        journal="Journal of Test",
        volume="1",
        pages="1-10"
    )
    flags = compare_fields(ref, rec)
    assert len(flags) == 0
    
    # Year off by one
    rec.year = 2021
    flags = compare_fields(ref, rec)
    assert flags.get("year_off_by_one") == True
    
    # Year mismatch
    rec.year = 2022
    flags = compare_fields(ref, rec)
    assert flags.get("year_mismatch") == True
    
    # Missing year
    rec.year = None
    flags = compare_fields(ref, rec)
    assert flags.get("year_mismatch") == True
    
    # Venue mismatch
    rec.year = 2020
    rec.journal = "Different Journal"
    flags = compare_fields(ref, rec)
    assert flags.get("venue_mismatch") == True
    
    # Volume mismatch
    rec.journal = "Journal of Test"
    rec.volume = "2"
    flags = compare_fields(ref, rec)
    assert flags.get("volume_mismatch") == True
    
    # Pages mismatch
    rec.volume = "1"
    rec.pages = "11-20"
    flags = compare_fields(ref, rec)
    assert flags.get("pages_mismatch") == True


def test_evaluate_verified():
    """Test v0.1 rule compatibility: title_sim>=0.90 + year_ok + author_ok -> VERIFIED"""
    ref = ParsedReference(
        title="Exact Match Title",
        year=2020,
        authors=["Smith, John"]
    )
    
    rec = ResolvedRecord(
        title="Exact Match Title",  # title_sim = 1.0
        year=2020,
        authors=[{"family": "Smith", "given": "John"}]
    )
    
    result = evaluate(ref, rec)
    assert result["status"] == "VERIFIED"  # No flags should be present
    assert result["scores"]["title_sim"] >= 0.90
    assert result["scores"]["year_ok"] == 1.0
    # Author similarity should be high
    
    # Test with warnings (flags present but still VERIFIED_WITH_WARNINGS)
    ref.year = 2020
    rec.year = 2021  # year_off_by_one
    
    result = evaluate(ref, rec)
    assert result["status"] == "VERIFIED_WITH_WARNINGS"
    assert "year_off_by_one" in result["flags"]


def test_evaluate_mismatch():
    """Test mismatches produce MISMATCH status."""
    # Title mismatch
    ref = ParsedReference(title="Completely Different Title", year=2020, authors=["Smith, John"])
    rec = ResolvedRecord(title="Something Else", year=2020, authors=[{"family": "Smith", "given": "John"}])
    
    result = evaluate(ref, rec)
    assert result["status"] == "MISMATCH"
    assert any("mismatch_title" in flag for flag in result["flags"])
    
    # Year mismatch
    ref = ParsedReference(title="Test Title", year=2020, authors=["Smith, John"])
    rec = ResolvedRecord(title="Test Title", year=2022, authors=[{"family": "Smith", "given": "John"}])
    
    result = evaluate(ref, rec)
    assert result["status"] == "MISMATCH"
    assert any("mismatch_year" in flag for flag in result["flags"])
    
    # Author mismatch
    ref = ParsedReference(title="Test Title", year=2020, authors=["Smith, John"])
    rec = ResolvedRecord(title="Test Title", year=2020, authors=[{"family": "Doe", "given": "Jane"}])
    
    result = evaluate(ref, rec)
    assert result["status"] == "MISMATCH"
    assert any("mismatch_author" in flag for flag in result["flags"])


def test_evaluate_doi_resolves_to_different_work():
    """Test doi_resolves_to_different_work flag."""
    ref = ParsedReference(
        title="Original Title",
        year=2020,
        authors=["Smith, John"],
        doi="10.1234/abcd"
    )
    
    # Record with same DOI but very different title (sim < 0.6)
    rec = ResolvedRecord(
        title="Completely Different Paper Title",
        year=2020,
        authors=[{"family": "Smith", "given": "John"}],
        doi="10.1234/abcd"
    )
    
    result = evaluate(ref, rec)
    assert "doi_resolves_to_different_work" in result["flags"]


def test_find_near_duplicates():
    refs = [
        ParsedReference(title="Exact Match Title", year=2020),
        ParsedReference(title="Exact Match Title", year=2020),  # Duplicate
        ParsedReference(title="Completely Different Title", year=2020),
        ParsedReference(title="Almost Exact Match Title", year=2020),  # Similar
    ]
    
    pairs = find_near_duplicates(refs)
    
    # Should find pair (0,1) - exact duplicates
    assert len(pairs) >= 1
    assert any(p["i"] == 0 and p["j"] == 1 for p in pairs)
    
    # May also find (0,3) and (1,3) if similarity >= 0.92
    # But we're mainly testing that it runs without error


def test_edge_cases():
    # Test with None values
    ref = ParsedReference(title=None, year=None, authors=[])
    rec = ResolvedRecord(title=None, year=None, authors=[])
    
    result = evaluate(ref, rec)
    # Should handle gracefully
    assert "status" in result
    
    # Test empty authors
    ref = ParsedReference(title="Test", year=2020, authors=[])
    rec = ResolvedRecord(title="Test", year=2020, authors=[])
    
    result = evaluate(ref, rec)
    assert result["status"] == "MISMATCH"  # Author mismatch due to empty authors

def test_evaluate_doi_only_resolves_verifies_with_warning():
    """A bare DOI line that resolves is verified (v0.1 DOI-check semantics);
    the missing bibliographic data must not surface as field mismatches."""
    ref = ParsedReference(doi="10.1016/j.soil.2019.01.001")
    rec = ResolvedRecord(
        doi="10.1016/j.soil.2019.01.001",
        title="Soil consolidation settlement under staged loading",
        year=2019,
        journal="Journal of Generic Geotechnics",
        authors=[{"family": "Alvarez", "given": "M."}],
    )
    result = evaluate(ref, rec)
    assert result["status"] == "VERIFIED_WITH_WARNINGS"
    assert "doi_only_resolves_no_title_to_compare" in result["flags"]
    assert "venue_mismatch" not in result["flags"]
    assert "year_mismatch" not in result["flags"]
    assert "author_mismatch" not in result["flags"]
    assert "doi_resolves_to_different_work" not in result["flags"]


def test_evaluate_doi_only_resolves_to_different_work():
    ref = ParsedReference(doi="10.1000/claimed")
    rec = ResolvedRecord(doi="10.2000/actual", title="Some Other Work", year=2001)
    result = evaluate(ref, rec)
    assert result["status"] == "MISMATCH"
    assert "doi_resolves_to_different_work" in result["flags"]


def test_evaluate_doi_only_https_prefix_normalised():
    ref = ParsedReference(doi="https://doi.org/10.1016/j.soil.2019.01.001")
    rec = ResolvedRecord(doi="10.1016/j.soil.2019.01.001", title="T", year=2019)
    result = evaluate(ref, rec)
    assert result["status"] == "VERIFIED_WITH_WARNINGS"
