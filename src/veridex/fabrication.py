# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Fabrication detection scoring. Stdlib only."""
from __future__ import annotations

from .models import ParsedReference, ResolvedRecord
from typing import Any, Dict, List


def score_fabrication(
    ref: ParsedReference,
    rec_or_none: ResolvedRecord | None,
    evaluation: Dict[str, Any],
    evidence_summary: List[Any],
) -> Dict[str, Any]:
    """Score likelihood of fabrication based on flags and evidence.
    
    Returns dict with score (0..1) and signals list.
    """
    score = 0.0
    signals: List[Dict[str, Any]] = []
    
    flags = evaluation.get("flags", [])
    
    # no_matching_record .35
    if "no_matching_record" in flags or rec_or_none is None:
        score += 0.35
        signals.append({
            "code": "no_matching_record",
            "weight": 0.35,
            "detail": "No matching record found"
        })
    
    # doi_resolves_to_different_work .30
    if "doi_resolves_to_different_work" in flags:
        score += 0.30
        signals.append({
            "code": "doi_resolves_to_different_work",
            "weight": 0.30,
            "detail": "DOI resolves to different work (title similarity < 0.6)"
        })
    
    # year_mismatch .15
    if "year_mismatch" in flags:
        score += 0.15
        signals.append({
            "code": "year_mismatch",
            "weight": 0.15,
            "detail": "Year mismatch (>1 year difference)"
        })
    
    # author_mismatch .20
    if "author_mismatch" in flags:
        score += 0.20
        signals.append({
            "code": "author_mismatch",
            "weight": 0.20,
            "detail": "Author mismatch"
        })
    
    # impossible_date .25
    if "impossible_date" in flags:
        score += 0.25
        signals.append({
            "code": "impossible_date",
            "weight": 0.25,
            "detail": "Impossible date (year out of 1500..current+1 or invalid month/day)"
        })
    
    # implausible_pages .10
    if "implausible_pages" in flags:
        score += 0.10
        signals.append({
            "code": "implausible_pages",
            "weight": 0.10,
            "detail": "Implausible pages (start>end, negative, or >1000 span)"
        })
    
    # venue_not_found .15
    if "venue_not_found" in flags:
        score += 0.15
        signals.append({
            "code": "venue_not_found",
            "weight": 0.15,
            "detail": "Venue not found in source"
        })
    
    # doi_format_invalid .20
    if "doi_format_invalid" in flags:
        score += 0.20
        signals.append({
            "code": "doi_format_invalid",
            "weight": 0.20,
            "detail": "DOI format invalid"
        })
    
    # Clamp score between 0 and 1
    score = max(0.0, min(1.0, score))
    
    return {"score": score, "signals": signals}