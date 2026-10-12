# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Reference matching and comparison logic. Stdlib only."""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

from .ids import clean_doi
from .models import ParsedReference, ResolvedRecord, Status


def normalize_title(title: str | None) -> str:
    """Normalize title for comparison (v0.1 compatible)."""
    if not title:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def title_similarity(a: str | None, b: str | None) -> float:
    """Compute title similarity as max of SequenceMatcher ratio and token Jaccard."""
    na = normalize_title(a)
    nb = normalize_title(b)
    if not na or not nb:
        return 0.0
    seq_ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    ta = set(na.split())
    tb = set(nb.split())
    if not ta or not tb:
        jaccard = 0.0
    else:
        jaccard = len(ta & tb) / len(ta | tb)
    return max(seq_ratio, jaccard)


def _fold_diacritics(s: str) -> str:
    """Fold diacritics using NFD normalization and remove combining marks."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _normalize_name_part(part: str) -> str:
    """Normalize a name part: fold diacritics, lowercase, strip punctuation."""
    part = _fold_diacritics(part)
    part = re.sub(r"[^\w\-]", "", part)
    return part.lower()


def _expand_initials(name: str) -> list[str]:
    """Expand initials in a name to possible full forms (heuristic).
    Returns list of normalized tokens for the name."""
    tokens = name.split()
    result = []
    for token in tokens:
        token = _normalize_name_part(token)
        if re.fullmatch(r"[a-z]\.?", token):
            result.append(token.rstrip("."))
        else:
            result.append(token)
    return result


def _parse_author_name(name: str) -> dict[str, list[str]]:
    """Parse author name into surname and given name tokens."""
    name = name.strip()
    if "," in name:
        surname_part, given_part = name.split(",", 1)
        surname = _normalize_name_part(surname_part.strip())
        given_tokens = _expand_initials(given_part.strip())
    else:
        parts = name.split()
        if not parts:
            return {"surname": [], "given": []}
        surname = _normalize_name_part(parts[-1])
        given_tokens = []
        for p in parts[:-1]:
            given_tokens.extend(_expand_initials(p))
    return {"surname": [surname] if surname else [], "given": given_tokens}


def _author_tokens(author: dict[str, str]) -> dict[str, list[str]]:
    """Extract normalized surname and given tokens from a ResolvedRecord author dict."""
    family = author.get("family", "")
    given = author.get("given", "")
    surname = _normalize_name_part(family) if family else ""
    given_tokens = _expand_initials(given) if given else []
    return {"surname": [surname] if surname else [], "given": given_tokens}


def compare_authors(
    parsed_authors: list[str], record_authors: list[dict[str, str]]
) -> dict[str, Any]:
    """Compare parsed authors to record authors.
    Returns dict with jaccard, order_ok, first_in_set, translit_candidates."""
    if not parsed_authors or not record_authors:
        return {"jaccard": 0.0, "order_ok": True, "first_in_set": False, "translit_candidates": []}

    parsed = [_parse_author_name(a) for a in parsed_authors]
    record = [_author_tokens(a) for a in record_authors]

    parsed_surnames = [p["surname"][0] for p in parsed if p["surname"]]
    record_surnames = [r["surname"][0] for r in record if r["surname"]]

    if not parsed_surnames or not record_surnames:
        return {"jaccard": 0.0, "order_ok": True, "first_in_set": False, "translit_candidates": []}

    set_parsed = set(parsed_surnames)
    set_record = set(record_surnames)
    jaccard = len(set_parsed & set_record) / len(set_parsed | set_record)

    order_ok = True
    if parsed_surnames and record_surnames:
        order_ok = parsed_surnames[0] == record_surnames[0]

    first_in_set = parsed_surnames[0] in set_record if parsed_surnames else False

    translit_candidates = []
    for ps in parsed_surnames:
        for rs in record_surnames:
            if ps and rs and ps[0] == rs[0] and len(ps) >= 3 and len(rs) >= 3:
                if ps not in set_record and rs not in set_parsed:
                    translit_candidates.append({"parsed": ps, "record": rs})

    return {
        "jaccard": round(jaccard, 4),
        "order_ok": order_ok,
        "first_in_set": first_in_set,
        "translit_candidates": translit_candidates,
    }


def compare_fields(ref: ParsedReference, rec: ResolvedRecord) -> dict[str, bool | str]:
    """Compare year, venue, volume, pages. Returns flags dict."""
    flags: dict[str, bool | str] = {}

    ref_year = ref.year
    rec_year = rec.year
    if ref_year is not None and rec_year is not None:
        diff = abs(ref_year - rec_year)
        if diff == 1:
            flags["year_off_by_one"] = True
        elif diff > 1:
            flags["year_mismatch"] = True
    elif ref_year is not None or rec_year is not None:
        flags["year_mismatch"] = True

    ref_venue = ref.journal or ""
    rec_venue = rec.journal or ""
    if ref_venue and rec_venue:
        rv_tokens = set(normalize_title(ref_venue).split())
        rr_tokens = set(normalize_title(rec_venue).split())
        if rv_tokens and rr_tokens:
            overlap = len(rv_tokens & rr_tokens) / len(rv_tokens | rr_tokens)
            if overlap < 0.5:
                flags["venue_mismatch"] = True
    elif ref_venue or rec_venue:
        flags["venue_mismatch"] = True

    if ref.volume and rec.volume:
        if ref.volume != rec.volume:
            flags["volume_mismatch"] = True
    elif ref.volume or rec.volume:
        flags["volume_mismatch"] = True

    if ref.pages and rec.pages:
        if ref.pages != rec.pages:
            flags["pages_mismatch"] = True
    elif ref.pages or rec.pages:
        flags["pages_mismatch"] = True

    return flags


def evaluate(ref: ParsedReference, rec: ResolvedRecord, semantic: bool = False) -> dict[str, Any]:
    """Evaluate a parsed reference against a resolved record.
    Returns dict with status, flags, scores.

    When ``semantic`` is true and the optional semantic extra is importable, a
    local embedding model refines the title similarity (never lowering the
    lexical score). Otherwise the stdlib lexical path is used unchanged.
    """
    flags: list[str] = []

    title_sim = title_similarity(ref.title, rec.title)
    if semantic:
        try:
            from . import semantic as _semantic

            title_sim = _semantic.best_title_similarity(title_sim, ref.title, rec.title, enabled=True)
        except Exception:  # pragma: no cover - defensive
            pass

    doi_only = bool(ref.doi) and not (ref.title or "").strip()
    if doi_only:
        # Identifier-only query: there is no bibliographic data supplied to
        # compare, so a successful resolution is the verification signal
        # (v0.1 DOI-check semantics). A resolved record carrying a different
        # DOI is still a hard mismatch.
        flags.append("doi_only_resolves_no_title_to_compare")
        ref_doi = clean_doi(ref.doi)
        rec_doi = clean_doi(rec.doi) if rec.doi else None
        if rec_doi and ref_doi and rec_doi != ref_doi:
            flags.append("doi_resolves_to_different_work")
            status = Status.MISMATCH
        else:
            status = Status.VERIFIED_WITH_WARNINGS
        author_sim = compare_authors(ref.authors, rec.authors)["jaccard"]
        scores = {
            "title_sim": round(title_sim, 4),
            "author_sim": round(author_sim, 4),
            "year_ok": 1.0,
            "venue_sim": 0.0,
            "overall": round(title_sim * 0.5 + author_sim * 0.2 + 0.2, 4),
        }
        return {"status": status, "flags": sorted(set(flags)), "scores": scores}

    author_cmp = compare_authors(ref.authors, rec.authors)
    author_sim = author_cmp["jaccard"]
    author_ok = author_cmp["first_in_set"]
    if not author_ok:
        flags.append("author_mismatch")
    elif not author_cmp["order_ok"]:
        flags.append("author_order_differs")


    ref_year = ref.year
    rec_year = rec.year
    year_ok = True
    if ref_year is not None and rec_year is not None:
        diff = abs(ref_year - rec_year)
        if diff == 1:
            flags.append("year_off_by_one")
        elif diff > 1:
            flags.append("year_mismatch")
            year_ok = False
    elif ref_year is not None or rec_year is not None:
        flags.append("year_mismatch")
        year_ok = False

    field_flags = compare_fields(ref, rec)
    for k, v in field_flags.items():
        if v:
            flags.append(k)

    if ref.doi and title_sim < 0.6:
        flags.append("doi_resolves_to_different_work")

    if title_sim >= 0.90 and year_ok and author_ok:
        status = Status.VERIFIED if not flags else Status.VERIFIED_WITH_WARNINGS
    else:
        mismatch_fields = []
        if title_sim < 0.90:
            mismatch_fields.append("title")
        if not year_ok:
            mismatch_fields.append("year")
        if not author_ok:
            mismatch_fields.append("author")
        for mf in mismatch_fields:
            flags.append(f"mismatch_{mf}")
        status = Status.MISMATCH

    venue_sim = 0.0
    if ref.journal and rec.journal:
        rv_tokens = set(normalize_title(ref.journal).split())
        rr_tokens = set(normalize_title(rec.journal).split())
        if rv_tokens and rr_tokens:
            venue_sim = len(rv_tokens & rr_tokens) / len(rv_tokens | rr_tokens)

    overall = (title_sim * 0.5) + (author_sim * 0.2) + (1.0 if year_ok else 0.0) * 0.2 + (venue_sim * 0.1)

    scores = {
        "title_sim": round(title_sim, 4),
        "author_sim": round(author_sim, 4),
        "year_ok": 1.0 if year_ok else 0.0,
        "venue_sim": round(venue_sim, 4),
        "overall": round(overall, 4),
    }

    return {"status": status, "flags": sorted(set(flags)), "scores": scores}


def find_near_duplicates(refs: list[ParsedReference]) -> list[dict[str, Any]]:
    """Find near-duplicate references (title similarity >= 0.92)."""
    pairs: list[dict[str, Any]] = []
    n = len(refs)
    for i in range(n):
        for j in range(i + 1, n):
            sim = title_similarity(refs[i].title, refs[j].title)
            if sim >= 0.92:
                pairs.append({"i": i, "j": j, "similarity": round(sim, 4)})
    pairs.sort(key=lambda x: (x["i"], x["j"]))
    return pairs