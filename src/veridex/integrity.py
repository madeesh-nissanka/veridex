# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Integrity checking: retractions, corrections, preprint pairs. Stdlib only."""
from __future__ import annotations

import re
from typing import Any

from .models import AuditResult, ParsedReference, ResolvedRecord, Status
from .matching import title_similarity


def collect_integrity(records: list[ResolvedRecord]) -> list[dict[str, Any]]:
    """Collect integrity notices from resolved records.
    
    Returns list of dicts with keys: kind, source, url, label, target.
    """
    results: list[dict[str, Any]] = []
    
    for record in records:
        # Get integrity notices from record.integrity
        integrity_notices = record.integrity.get("notices", []) if hasattr(record, 'integrity') else []
        
        for notice in integrity_notices:
            if isinstance(notice, dict):
                results.append({
                    "kind": notice.get("kind", ""),
                    "source": notice.get("source", record.source),
                    "url": notice.get("url", ""),
                    "label": notice.get("label", ""),
                    "target": notice.get("target", "work")
                })
        
        # Check Crossref relation fields for additional integrity info
        # Crossref relation types that indicate integrity issues
        relation_types = {
            "retraction": "retraction",
            "withdrawal": "withdrawal", 
            "erratum": "correction",
            "correction": "correction",
            "expression-of-concern": "expression_of_concern"
        }
        
        # Check if record has relation information
        if hasattr(record, 'extra') and isinstance(record.extra, dict):
            relations = record.extra.get("relation", [])
            if isinstance(relations, list):
                for relation in relations:
                    if isinstance(relation, dict):
                        rel_type = relation.get("type", "")
                        if rel_type in relation_types:
                            results.append({
                                "kind": relation_types[rel_type],
                                "source": record.source,
                                "url": relation.get("id", ""),
                                "label": rel_type.replace("-", " ").title(),
                                "target": "work"
                            })
    
    return results


def _record_is_preprint(record) -> bool:
    doc_type = getattr(record, 'document_type', '') or ''
    source = getattr(record, 'source', '') or ''
    return doc_type.lower() in ('preprint', 'draft') or source.lower() in ('arxiv', 'biorxiv', 'medrxiv')


def pair_preprint(results: list[AuditResult]) -> None:
    """Mark preprint pairs in audit results.
    
    Modifies results in-place, adding flags:
    - preprint_pair_found
    - published_version_found
    """
    # Build lookup of arXiv IDs and DOIs with prefix 10.48550
    arxiv_ids: dict[str, int] = {}  # arxiv_id -> index
    doi_10_48550: dict[str, int] = {}  # doi -> index
    
    for i, result in enumerate(results):
        record = result.record
        if not record:
            continue
            
        # Check for arXiv ID
        arxiv_id = getattr(record, 'arxiv_id', None)
        if arxiv_id:
            arxiv_ids[arxiv_id] = i
            
        # Check for DOI with prefix 10.48550
        doi = getattr(record, 'doi', None)
        if doi and doi.startswith("10.48550/"):
            doi_10_48550[doi] = i
    
    # Check for matches
    for i, result in enumerate(results):
        record = result.record
        if not record:
            continue
            
        # Check if this record is a preprint that matches a published version
        is_preprint = False
        title = getattr(record, 'title', None)

        # Check for preprint indicators
        is_preprint = _record_is_preprint(record)
        
        if is_preprint and title:
            # Check against arXiv IDs (pair only if the other is not a preprint)
            arxiv_id = getattr(record, 'arxiv_id', None)
            if arxiv_id and arxiv_id in arxiv_ids and arxiv_ids[arxiv_id] != i:
                other_idx = arxiv_ids[arxiv_id]
                if other_idx < len(results) and not _record_is_preprint(results[other_idx].record):
                    result.flags.append("preprint_pair_found")
                    results[other_idx].flags.append("published_version_found")
            
            # Check against DOI 10.48550
            doi = getattr(record, 'doi', None)
            if doi and doi.startswith("10.48550/") and doi in doi_10_48550 and doi_10_48550[doi] != i:
                other_idx = doi_10_48550[doi]
                if other_idx < len(results) and not _record_is_preprint(results[other_idx].record):
                    result.flags.append("preprint_pair_found")
                    results[other_idx].flags.append("published_version_found")
        
        # Also check by title similarity >= 0.95 for preprint pairs
        if is_preprint and title:
            for j, other_result in enumerate(results):
                if i >= j:
                    continue
                other_record = other_result.record
                if not other_record:
                    continue
                    
                other_title = getattr(other_record, 'title', None)
                if not other_title:
                    continue
                
                sim = title_similarity(title, other_title)
                if sim >= 0.95:
                    # One should be preprint, one should be published
                    other_is_preprint = False
                    other_doc_type = getattr(other_record, 'document_type', '') or ''
                    other_source = getattr(other_record, 'source', '') or ''
                    if other_doc_type.lower() in ('preprint', 'draft') or other_source.lower() in ('arxiv', 'biorxiv', 'medrxiv'):
                        other_is_preprint = True
                    
                    if is_preprint != other_is_preprint:
                        # One is preprint, one is published
                        if is_preprint:
                            result.flags.append("preprint_pair_found")
                            other_result.flags.append("published_version_found")
                        else:
                            other_result.flags.append("preprint_pair_found")
                            result.flags.append("published_version_found")


def status_for(result: AuditResult) -> str:
    """Determine status based on integrity notices.
    
    Returns RETRACTED if retraction notice targets the work.
    """
    if result.integrity is None:
        return result.status
    for item in result.integrity:
        if isinstance(item, dict):
            kind = item.get("kind", "")
            target = item.get("target", "work")
            if kind in ("retraction", "withdrawal") and target == "work":
                return Status.RETRACTED
    # If no retraction/withdrawal targeting work, return the existing status
    return result.status