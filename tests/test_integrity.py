# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for integrity.py."""
from __future__ import annotations

from veridex.models import AuditResult, ResolvedRecord, Status
from veridex.integrity import collect_integrity, pair_preprint, status_for


def test_collect_integrity_empty():
    """Test collect_integrity with empty records."""
    result = collect_integrity([])
    assert result == []


def test_collect_integrity_no_notices():
    """Test collect_integrity when records have no integrity notices."""
    record = ResolvedRecord(title="Test", year=2020)
    # No integrity field or empty notices
    result = collect_integrity([record])
    assert result == []


def test_collect_integrity_with_notices():
    """Test collect_integrity with integrity notices."""
    record = ResolvedRecord(
        title="Test", 
        year=2020,
        integrity={
            "notices": [
                {"kind": "retraction", "url": "http://example.com/retraction", "label": "Retracted", "target": "work"},
                {"kind": "correction", "url": "http://example.com/correction", "label": "Corrected", "target": "work"}
            ]
        }
    )
    
    result = collect_integrity([record])
    assert len(result) == 2
    
    # Check first notice
    assert result[0]["kind"] == "retraction"
    assert result[0]["source"] == ""  # Default from record.source
    assert result[0]["url"] == "http://example.com/retraction"
    assert result[0]["label"] == "Retracted"
    assert result[0]["target"] == "work"
    
    # Check second notice
    assert result[1]["kind"] == "correction"
    assert result[1]["url"] == "http://example.com/correction"
    assert result[1]["label"] == "Corrected"
    assert result[1]["target"] == "work"


def test_collect_integrity_with_source():
    """Test collect_integrity uses record source when notice has no source."""
    record = ResolvedRecord(
        title="Test", 
        year=2020,
        source="crossref",
        integrity={
            "notices": [
                {"kind": "retraction", "url": "http://example.com/retraction", "label": "Retracted"}  # No source
            ]
        }
    )
    
    result = collect_integrity([record])
    assert len(result) == 1
    assert result[0]["source"] == "crossref"


def test_collect_integrity_multiple_records():
    """Test collect_integrity with multiple records."""
    record1 = ResolvedRecord(
        title="Test1", 
        year=2020,
        integrity={"notices": [{"kind": "retraction", "url": "http://example.com/1", "label": "Retracted1"}]}
    )
    
    record2 = ResolvedRecord(
        title="Test2", 
        year=2021,
        integrity={"notices": [{"kind": "correction", "url": "http://example.com/2", "label": "Corrected2"}]}
    )
    
    result = collect_integrity([record1, record2])
    assert len(result) == 2
    assert result[0]["kind"] == "retraction"
    assert result[1]["kind"] == "correction"


def test_pair_preprint_no_matches():
    """Test pair_preprint with no matches."""
    # Create results with no preprint relationships
    results = []
    for i in range(3):
        audit_result = AuditResult(index=i)
        audit_result.record = ResolvedRecord(
            title=f"Paper {i}",
            year=2020,
            authors=[{"family": "Author", "given": f"Test{i}"}]
        )
        results.append(audit_result)
    
    pair_preprint(results)
    
    # No flags should be added
    for result in results:
        assert not hasattr(result, 'flags') or "preprint_pair_found" not in result.flags
        assert not hasattr(result, 'flags') or "published_version_found" not in result.flags


def test_pair_preprint_arxiv_match():
    """Test pair_preprint with arXiv ID match."""
    # Preprint with arXiv ID
    preprint_result = AuditResult(index=0)
    preprint_result.record = ResolvedRecord(
        title="Interesting Paper",
        year=2020,
        arxiv_id="1234.5678",
        document_type="preprint"
    )
    
    # Published version with same arXiv ID
    published_result = AuditResult(index=1)
    published_result.record = ResolvedRecord(
        title="Interesting Paper",
        year=2021,
        arxiv_id="1234.5678",
        document_type="journal-article"
    )
    
    results = [preprint_result, published_result]
    pair_preprint(results)
    
    # Preprint should have preprint_pair_found
    assert "preprint_pair_found" in preprint_result.flags
    # Published version should have published_version_found
    assert "published_version_found" in published_result.flags


def test_pair_preprint_doi_10_48550_match():
    """Test pair_preprint with DOI 10.48550 match."""
    # Preprint with DOI 10.48550
    preprint_result = AuditResult(index=0)
    preprint_result.record = ResolvedRecord(
        title="Interesting Paper",
        year=2020,
        doi="10.48550/1234.5678",
        document_type="preprint"
    )
    
    # Published version with same DOI
    published_result = AuditResult(index=1)
    published_result.record = ResolvedRecord(
        title="Interesting Paper",
        year=2021,
        doi="10.48550/1234.5678",
        document_type="journal-article"
    )
    
    results = [preprint_result, published_result]
    pair_preprint(results)
    
    # Preprint should have preprint_pair_found
    assert "preprint_pair_found" in preprint_result.flags
    # Published version should have published_version_found
    assert "published_version_found" in published_result.flags


def test_pair_preprint_title_similarity():
    """Test pair_preprint with title similarity >= 0.95."""
    # Preprint
    preprint_result = AuditResult(index=0)
    preprint_result.record = ResolvedRecord(
        title="A Very Interesting Paper About Something",
        year=2020,
        document_type="preprint"
    )
    
    # Published version with similar title
    published_result = AuditResult(index=1)
    published_result.record = ResolvedRecord(
        title="A Very Interesting Paper About Something",  # Identical title
        year=2021,
        document_type="journal-article"
    )
    
    results = [preprint_result, published_result]
    pair_preprint(results)
    
    # Should detect as pair due to high title similarity
    assert "preprint_pair_found" in preprint_result.flags
    assert "published_version_found" in published_result.flags


def test_pair_preprint_not_same_type():
    """Test pair_preprint only marks when one is preprint and one is published."""
    # Both preprints
    preprint1 = AuditResult(index=0)
    preprint1.record = ResolvedRecord(
        title="Paper One",
        year=2020,
        arxiv_id="1234.5678",
        document_type="preprint"
    )
    
    preprint2 = AuditResult(index=1)
    preprint2.record = ResolvedRecord(
        title="Paper One",
        year=2020,
        arxiv_id="1234.5678",
        document_type="preprint"
    )
    
    results = [preprint1, preprint2]
    pair_preprint(results)
    
    # Should not flag as pair since both are preprints
    assert "preprint_pair_found" not in preprint1.flags
    assert "published_version_found" not in preprint1.flags
    assert "preprint_pair_found" not in preprint2.flags
    assert "published_version_found" not in preprint2.flags


def test_status_for_no_retraction():
    """Test status_for when no retraction notice targets work."""
    audit_result = AuditResult(index=0)
    audit_result.status = Status.VERIFIED
    audit_result.integrity = [
        {"kind": "correction", "url": "http://example.com/correction", "label": "Corrected", "target": "work"},
        {"kind": "retraction", "url": "http://example.com/retraction", "label": "Retracted", "target": "author"}  # Not targeting work
    ]
    
    status = status_for(audit_result)
    assert status == Status.VERIFIED  # Should remain unchanged


def test_status_for_retraction_targets_work():
    """Test status_for when retraction notice targets work."""
    audit_result = AuditResult(index=0)
    audit_result.status = Status.VERIFIED
    audit_result.integrity = [
        {"kind": "retraction", "url": "http://example.com/retraction", "label": "Retracted", "target": "work"}
    ]
    
    status = status_for(audit_result)
    assert status == Status.RETRACTED


def test_status_for_withdrawal_targets_work():
    """Test status_for when withdrawal notice targets work."""
    audit_result = AuditResult(index=0)
    audit_result.status = Status.VERIFIED
    audit_result.integrity = [
        {"kind": "withdrawal", "url": "http://example.com/withdrawal", "label": "Withdrawn", "target": "work"}
    ]
    
    status = status_for(audit_result)
    assert status == Status.RETRACTED


def test_status_for_expression_of_concern():
    """Test status_for expression of concern does not change status."""
    audit_result = AuditResult(index=0)
    audit_result.status = Status.VERIFIED
    audit_result.integrity = [
        {"kind": "expression_of_concern", "url": "http://example.com/eoc", "label": "Expression of Concern", "target": "work"}
    ]
    
    status = status_for(audit_result)
    assert status == Status.VERIFIED  # Should not change to RETRACTED


def test_status_for_empty_integrity():
    """Test status_for with empty integrity list."""
    audit_result = AuditResult(index=0)
    audit_result.status = Status.MISMATCH
    audit_result.integrity = []
    
    status = status_for(audit_result)
    assert status == Status.MISMATCH


def test_status_for_none_integrity():
    """Test status_for when integrity is None."""
    audit_result = AuditResult(index=0)
    audit_result.status = Status.VERIFIED
    audit_result.integrity = None
    
    status = status_for(audit_result)
    assert status == Status.VERIFIED