# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Report rendering: markdown, HTML, JSON, CSV, SARIF."""
from __future__ import annotations

import csv
import json
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import AuditResult, ParsedReference, Status, TOOL_NAME, TOOL_VERSION


V01_CSV_HEADER = [
    "index",
    "status",
    "title",
    "authors",
    "year",
    "journal",
    "doi",
    "flags",
    "fabrication_score",
]

V02_CSV_EXTRA = [
    "volume",
    "issue",
    "pages",
    "publisher",
    "url",
    "source",
    "source_url",
    "verdict",
    "retracted",
    "near_duplicate",
    "weak_context",
]


def summary(results: list[AuditResult]) -> dict[str, int]:
    """Return counts per status and total."""
    counts: dict[str, int] = {s: 0 for s in [
        Status.VERIFIED,
        Status.VERIFIED_WITH_WARNINGS,
        Status.MISMATCH,
        Status.DOI_NOT_FOUND,
        Status.NOT_FOUND,
        Status.NO_DOI_MATCHED,
        Status.UNREACHABLE,
        Status.AMBIGUOUS,
        Status.RETRACTED,
        Status.ERROR,
    ]}
    counts["total"] = len(results)
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


def _authors_str(authors: list[dict[str, str]] | list[str]) -> str:
    if not authors:
        return ""
    if authors and isinstance(authors[0], dict):
        return "; ".join(f"{a.get('family', '')}, {a.get('given', '')}".strip(", ") for a in authors)
    return "; ".join(authors)


def _flags_str(flags: list[str]) -> str:
    return "|".join(sorted(flags))


def _fabrication_score(result: AuditResult) -> float:
    return (result.fabrication or {}).get("score", 0.0)


def _is_retracted(result: AuditResult) -> bool:
    for item in result.integrity:
        if item.get("kind") in ("retraction", "withdrawal") and item.get("target", "work") == "work":
            return True
    return False


def _has_near_duplicate(result: AuditResult) -> bool:
    return any(f.startswith("near_duplicate_of_") for f in result.flags)


def _has_weak_context(result: AuditResult) -> bool:
    return "weak_context_support" in result.flags


def _verdict(result: AuditResult) -> str:
    if result.status == Status.VERIFIED:
        return "PASS"
    if result.status == Status.VERIFIED_WITH_WARNINGS:
        return "PASS_WITH_WARNINGS"
    if result.status in (Status.MISMATCH, Status.RETRACTED):
        return "FAIL"
    return "UNKNOWN"


def _generated_at(results: list[AuditResult], meta: dict[str, Any]) -> str | None:
    """Deterministic generation stamp: explicit meta wins, else latest evidence
    timestamp in the data, else None (renderers omit the line)."""
    if meta.get("generated_at"):
        return str(meta["generated_at"])
    stamps = []
    for r in results:
        for ev in getattr(r, "evidence", []) or []:
            ts = ev.get("timestamp") if isinstance(ev, dict) else None
            if ts:
                stamps.append(str(ts))
    return max(stamps) if stamps else None


def render_report(
    results: list[AuditResult],
    entries: list[ParsedReference],
    fmt: str,
    out_path: str | Path,
    meta: dict[str, Any] | None = None,
) -> None:
    """Render a report in the given format to out_path."""
    meta = meta or {}
    fmt = fmt.lower()

    if fmt == "json":
        _render_json(results, entries, out_path, meta)
    elif fmt == "csv":
        _render_csv(results, entries, out_path, meta)
    elif fmt == "md" or fmt == "markdown":
        _render_md(results, entries, out_path, meta)
    elif fmt == "html":
        _render_html(results, entries, out_path, meta)
    elif fmt == "sarif":
        _render_sarif(results, entries, out_path, meta)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def _render_json(
    results: list[AuditResult],
    entries: list[ParsedReference],
    out_path: str | Path,
    meta: dict[str, Any],
) -> None:
    data = {
        "tool": "veridex",
        "version": TOOL_VERSION,
        "meta": {
            "tool": "veridex",
            "version": TOOL_VERSION,
            "generated_at": _generated_at(results, meta),
            **meta,
        },
        "summary": summary(results),
        "results": [r.to_dict() for r in results],
        "entries": [e.to_dict() for e in entries],
    }
    Path(out_path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _render_csv(
    results: list[AuditResult],
    entries: list[ParsedReference],
    out_path: str | Path,
    meta: dict[str, Any],
) -> None:
    header = V01_CSV_HEADER + V02_CSV_EXTRA
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for i, result in enumerate(results):
            rec = result.record
            row = [
                result.index,
                result.status,
                rec.title if rec else (entries[i].title if i < len(entries) else ""),
                _authors_str(rec.authors) if rec else _authors_str(entries[i].authors),
                rec.year if rec else (entries[i].year if i < len(entries) else ""),
                rec.journal if rec else (entries[i].journal if i < len(entries) else ""),
                rec.doi if rec else (entries[i].doi if i < len(entries) else ""),
                _flags_str(result.flags),
                f"{_fabrication_score(result):.3f}",
                rec.volume if rec else "",
                rec.issue if rec else "",
                rec.pages if rec else "",
                rec.publisher if rec else "",
                rec.url if rec else "",
                rec.source if rec else "",
                rec.source_url if rec else "",
                _verdict(result),
                "true" if _is_retracted(result) else "false",
                "true" if _has_near_duplicate(result) else "false",
                "true" if _has_weak_context(result) else "false",
            ]
            writer.writerow(row)


def _render_md(
    results: list[AuditResult],
    entries: list[ParsedReference],
    out_path: str | Path,
    meta: dict[str, Any],
) -> None:
    lines = []
    lines.append("# VERIDEX Audit Report")
    lines.append("")
    gen = _generated_at(results, meta)
    if gen:
        lines.append(f"**Generated:** {gen}")
    lines.append(f"**Tool:** veridex v0.2.0")
    lines.append(f"**Entries audited:** {len(results)}")
    lines.append("")

    # Executive summary
    summ = summary(results)
    lines.append("## Executive Summary")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|--------|-------|")
    for status in [
        Status.VERIFIED,
        Status.VERIFIED_WITH_WARNINGS,
        Status.MISMATCH,
        Status.DOI_NOT_FOUND,
        Status.NOT_FOUND,
        Status.NO_DOI_MATCHED,
        Status.UNREACHABLE,
        Status.AMBIGUOUS,
        Status.RETRACTED,
        Status.ERROR,
    ]:
        count = summ.get(status, 0)
        if count > 0:
            lines.append(f"| {status} | {count} |")
    lines.append(f"| **Total** | **{summ['total']}** |")
    lines.append("")

    # Per-entry details
    lines.append("## Per-Entry Results")
    lines.append("")
    for result in results:
        rec = result.record
        lines.append(f"### Entry {result.index}: {rec.title if rec else 'NO RECORD'}")
        lines.append("")
        lines.append(f"- **Status:** {result.status}")
        lines.append(f"- **Fabrication Score:** {_fabrication_score(result):.3f}")
        lines.append(f"- **Flags:** {_flags_str(result.flags) or 'none'}")
        lines.append(f"- **Retracted:** {'Yes' if _is_retracted(result) else 'No'}")
        lines.append(f"- **Near Duplicate:** {'Yes' if _has_near_duplicate(result) else 'No'}")
        lines.append(f"- **Weak Context:** {'Yes' if _has_weak_context(result) else 'No'}")
        lines.append("")
        if rec:
            lines.append("**Resolved Record:**")
            lines.append("")
            lines.append(f"- Title: {rec.title}")
            lines.append(f"- Authors: {_authors_str(rec.authors)}")
            lines.append(f"- Year: {rec.year}")
            lines.append(f"- Journal: {rec.journal}")
            lines.append(f"- Volume: {rec.volume}")
            lines.append(f"- Issue: {rec.issue}")
            lines.append(f"- Pages: {rec.pages}")
            lines.append(f"- Publisher: {rec.publisher}")
            lines.append(f"- DOI: {rec.doi}")
            lines.append(f"- URL: {rec.url}")
            lines.append(f"- Source: {rec.source} ({rec.source_url})")
            lines.append("")
        lines.append("**Evidence:**")
        lines.append("")
        for ev in result.evidence:
            lines.append(f"- {ev.source}: {ev.request_url} (HTTP {ev.http_status}, {'cache' if ev.from_cache else 'live'})")
        lines.append("")
        if result.notes:
            lines.append("**Notes:**")
            for note in result.notes:
                lines.append(f"- {note}")
            lines.append("")

    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


def _render_html(
    results: list[AuditResult],
    entries: list[ParsedReference],
    out_path: str | Path,
    meta: dict[str, Any],
) -> None:
    summ = summary(results)
    total = summ["total"]
    verified = summ.get(Status.VERIFIED, 0) + summ.get(Status.VERIFIED_WITH_WARNINGS, 0)
    failed = summ.get(Status.MISMATCH, 0) + summ.get(Status.RETRACTED, 0)

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='utf-8'>",
        "<title>VERIDEX Audit Report</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.5; }",
        "h1, h2, h3 { color: #1a1a1a; }",
        "table { border-collapse: collapse; width: 100%; margin: 1rem 0; }",
        "th, td { border: 1px solid #ddd; padding: 0.5rem; text-align: left; }",
        "th { background: #f5f5f5; }",
        ".summary { display: flex; gap: 2rem; flex-wrap: wrap; margin: 1rem 0; }",
        ".card { background: #fafafa; border: 1px solid #ddd; border-radius: 4px; padding: 1rem; min-width: 150px; }",
        ".card.pass { border-left: 4px solid #2e7d32; }",
        ".card.warn { border-left: 4px solid #f57f17; }",
        ".card.fail { border-left: 4px solid #c62828; }",
        ".card.unknown { border-left: 4px solid #546e7a; }",
        ".entry { margin: 2rem 0; padding: 1rem; border: 1px solid #eee; border-radius: 4px; }",
        ".entry-header { display: flex; justify-content: space-between; align-items: center; }",
        ".badge { padding: 0.2rem 0.5rem; border-radius: 3px; font-size: 0.85rem; font-weight: bold; }",
        ".badge-verified { background: #e8f5e9; color: #2e7d32; }",
        ".badge-warn { background: #fff3e0; color: #f57f17; }",
        ".badge-mismatch { background: #fce4ec; color: #c62828; }",
        ".badge-retracted { background: #fce4ec; color: #c62828; }",
        ".badge-error { background: #eceff1; color: #546e7a; }",
        ".badge-unknown { background: #eceff1; color: #546e7a; }",
        ".evidence { font-size: 0.9rem; color: #555; }",
        ".flags { font-family: monospace; font-size: 0.85rem; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>VERIDEX Audit Report</h1>",
        *( [f"<p><strong>Generated:</strong> {_generated_at(results, meta)}</p>"] if _generated_at(results, meta) else [] ),
        f"<p><strong>Tool:</strong> veridex v0.2.0</p>",
        f"<p><strong>Entries audited:</strong> {total}</p>",
        "<h2>Executive Summary</h2>",
        "<div class='summary'>",
        f"<div class='card pass'><strong>Verified</strong><br>{verified}</div>",
        f"<div class='card fail'><strong>Failed</strong><br>{failed}</div>",
        f"<div class='card unknown'><strong>Other</strong><br>{total - verified - failed}</div>",
        "</div>",
        "<table>",
        "<thead><tr><th>Status</th><th>Count</th></tr></thead>",
        "<tbody>",
    ]

    for status in [
        Status.VERIFIED,
        Status.VERIFIED_WITH_WARNINGS,
        Status.MISMATCH,
        Status.DOI_NOT_FOUND,
        Status.NOT_FOUND,
        Status.NO_DOI_MATCHED,
        Status.UNREACHABLE,
        Status.AMBIGUOUS,
        Status.RETRACTED,
        Status.ERROR,
    ]:
        count = summ.get(status, 0)
        if count > 0:
            html_parts.append(f"<tr><td>{html.escape(status)}</td><td>{count}</td></tr>")

    html_parts.extend([
        f"<tr><td><strong>Total</strong></td><td><strong>{total}</strong></td></tr>",
        "</tbody></table>",
        "<h2>Per-Entry Results</h2>",
    ])

    for result in results:
        rec = result.record
        badge_class = {
            Status.VERIFIED: "badge-verified",
            Status.VERIFIED_WITH_WARNINGS: "badge-warn",
            Status.MISMATCH: "badge-mismatch",
            Status.RETRACTED: "badge-retracted",
            Status.ERROR: "badge-error",
        }.get(result.status, "badge-unknown")

        html_parts.append("<div class='entry'>")
        html_parts.append("<div class='entry-header'>")
        title_text = rec.title if rec else "NO RECORD"
        html_parts.append(f"<h3>Entry {result.index}: {html.escape(title_text)}</h3>")
        html_parts.append(f"<span class='badge {badge_class}'>{html.escape(result.status)}</span>")
        html_parts.append("</div>")
        html_parts.append(f"<p><strong>Fabrication Score:</strong> {_fabrication_score(result):.3f}</p>")
        html_parts.append(f"<p class='flags'><strong>Flags:</strong> {html.escape(_flags_str(result.flags) or 'none')}</p>")
        html_parts.append(f"<p><strong>Retracted:</strong> {'Yes' if _is_retracted(result) else 'No'}</p>")
        html_parts.append(f"<p><strong>Near Duplicate:</strong> {'Yes' if _has_near_duplicate(result) else 'No'}</p>")
        html_parts.append(f"<p><strong>Weak Context:</strong> {'Yes' if _has_weak_context(result) else 'No'}</p>")

        if rec:
            html_parts.append("<h4>Resolved Record</h4>")
            html_parts.append("<table>")
            for label, value in [
                ("Title", rec.title),
                ("Authors", _authors_str(rec.authors)),
                ("Year", str(rec.year) if rec.year else ""),
                ("Journal", rec.journal),
                ("Volume", rec.volume),
                ("Issue", rec.issue),
                ("Pages", rec.pages),
                ("Publisher", rec.publisher),
                ("DOI", rec.doi),
                ("URL", rec.url),
                ("Source", f"{rec.source} ({rec.source_url})" if rec.source else ""),
            ]:
                if value:
                    html_parts.append(f"<tr><td>{html.escape(label)}</td><td>{html.escape(str(value))}</td></tr>")
            html_parts.append("</table>")

        if result.evidence:
            html_parts.append("<h4>Evidence</h4>")
            html_parts.append("<ul class='evidence'>")
            for ev in result.evidence:
                html_parts.append(
                    f"<li>{html.escape(ev.source)}: {html.escape(ev.request_url)} "
                    f"(HTTP {ev.http_status}, {'cache' if ev.from_cache else 'live'})</li>"
                )
            html_parts.append("</ul>")

        if result.notes:
            html_parts.append("<h4>Notes</h4>")
            html_parts.append("<ul>")
            for note in result.notes:
                html_parts.append(f"<li>{html.escape(note)}</li>")
            html_parts.append("</ul>")

        html_parts.append("</div>")

    html_parts.extend(["</body>", "</html>"])
    Path(out_path).write_text("\n".join(html_parts), encoding="utf-8")


def _render_sarif(
    results: list[AuditResult],
    entries: list[ParsedReference],
    out_path: str | Path,
    meta: dict[str, Any],
) -> None:
    # SARIF 2.1.0 structure
    rules = [
        {
            "id": "fabrication-score",
            "name": "Fabrication Score",
            "shortDescription": {"text": "High fabrication score indicates potential fabricated reference"},
            "fullDescription": {"text": "The fabrication score combines signals like no matching record, DOI resolving to different work, year mismatch, author mismatch, impossible date, implausible pages, venue not found, and invalid DOI format."},
            "defaultConfiguration": {"level": "warning"},
            "properties": {"tags": ["fabrication"], "precision": "medium"},
        },
        {
            "id": "flags",
            "name": "Validation Flags",
            "shortDescription": {"text": "Validation flags raised during audit"},
            "fullDescription": {"text": "Flags indicate specific mismatches or issues found during reference validation."},
            "defaultConfiguration": {"level": "note"},
            "properties": {"tags": ["validation"], "precision": "high"},
        },
        {
            "id": "retraction",
            "name": "Retraction Notice",
            "shortDescription": {"text": "The referenced work has been retracted or withdrawn"},
            "fullDescription": {"text": "A retraction or withdrawal notice was found for the resolved record."},
            "defaultConfiguration": {"level": "error"},
            "properties": {"tags": ["integrity"], "precision": "very-high"},
        },
    ]

    sarif_results = []
    for result in results:
        rec = result.record
        # Fabrication score rule
        fab_score = _fabrication_score(result)
        level = "error" if fab_score >= 0.7 else ("warning" if fab_score >= 0.4 else "note")
        sarif_results.append({
            "ruleId": "fabrication-score",
            "level": level,
            "message": {"text": f"Fabrication score: {fab_score:.3f}"},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": f"entry-{result.index}"},
                    "region": {"startLine": result.index + 1},
                }
            }],
            "properties": {"fabrication_score": fab_score, "signals": (result.fabrication or {}).get("signals", [])},
        })

        # Flags rule
        for flag in sorted(result.flags):
            flag_level = "error" if flag in ("retracted", "corrected", "expression_of_concern", "withdrawn") else "warning"
            sarif_results.append({
                "ruleId": "flags",
                "level": flag_level,
                "message": {"text": f"Flag: {flag}"},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": f"entry-{result.index}"},
                        "region": {"startLine": result.index + 1},
                    }
                }],
                "properties": {"flag": flag},
            })

        # Retraction rule
        if _is_retracted(result):
            sarif_results.append({
                "ruleId": "retraction",
                "level": "error",
                "message": {"text": "Retraction notice found for this work"},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": f"entry-{result.index}"},
                        "region": {"startLine": result.index + 1},
                    }
                }],
                "properties": {"integrity": result.integrity},
            })

    sarif = {
        "version": "2.1.0",
        "$schema": "https://schemastore.azurewebsites.net/schemas/json/sarif-2.1.0.json",
        "runs": [{
            "tool": {
                "driver": {
                    "name": str(meta.get("tool") or TOOL_NAME),
                    "version": str(meta.get("version") or TOOL_VERSION),
                    "informationUri": "https://github.com/madeesh-nissanka/veridex",
                    "rules": rules,
                }
            },
            "results": sarif_results,
        }],
    }

    Path(out_path).write_text(json.dumps(sarif, indent=2, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------
# Interactive HTML Dashboard (v0.3.0+)
# --------------------------------------------------------------------------
def _render_dashboard(
    results: list[AuditResult],
    entries: list[ParsedReference],
    out_path: str | Path,
    meta: dict[str, Any],
) -> None:
    """Render an interactive, self-contained HTML dashboard for review.

    Features:
    - Filter by status, flags, fabrication score range
    - Sort by any column (status, title, score, year, etc.)
    - Per-row accept/reject/pending decisions with notes
    - Export decisions to JSON or CSV
    - Fully self-contained (no external dependencies, stdlib only)
    """
    import html

    # Build rows data for JavaScript
    rows = []
    for result in results:
        rec = result.record
        entry = entries[result.index] if result.index < len(entries) else None
        rows.append({
            "index": result.index,
            "status": result.status,
            "fabrication_score": _fabrication_score(result),
            "flags": result.flags,
            "verdict": _verdict(result),
            "retracted": _is_retracted(result),
            "near_duplicate": _has_near_duplicate(result),
            "weak_context": _has_weak_context(result),
            "title": rec.title if rec else (entry.title if entry else "NO RECORD"),
            "authors": _authors_str(rec.authors) if rec else _authors_str(entry.authors) if entry else "",
            "year": rec.year if rec else (entry.year if entry else ""),
            "journal": rec.journal if rec else (entry.journal if entry else ""),
            "volume": rec.volume if rec else "",
            "issue": rec.issue if rec else "",
            "pages": rec.pages if rec else "",
            "publisher": rec.publisher if rec else "",
            "doi": rec.doi if rec else (entry.doi if entry else ""),
            "url": rec.url if rec else "",
            "source": rec.source if rec else "",
            "source_url": rec.source_url if rec else "",
            "notes": "",
            "decision": "pending",  # pending, accept, reject
        })

    rows_json = json.dumps(rows, ensure_ascii=False)
    summ = summary(results)
    total = summ["total"]
    verified = summ.get(Status.VERIFIED, 0) + summ.get(Status.VERIFIED_WITH_WARNINGS, 0)
    failed = summ.get(Status.MISMATCH, 0) + summ.get(Status.RETRACTED, 0)

    gen = _generated_at(results, meta)
    tool_version = meta.get("version", "0.3.0")

    # Self-contained HTML with embedded CSS and JavaScript
    dashboard_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>VERIDEX Review Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 1rem; background: #f8f9fa; line-height: 1.5; }}
.header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 1rem; }}
h1 {{ margin: 0; font-size: 1.5rem; color: #1a1a1a; }}
.toolbar {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; }}
.toolbar select, .toolbar input {{ padding: 0.4rem 0.6rem; border: 1px solid #ccc; border-radius: 4px; font-size: 0.9rem; }}
.toolbar input[type="text"] {{ width: 200px; }}
.toolbar input[type="range"] {{ width: 120px; }}
.btn {{ padding: 0.4rem 0.8rem; border: 1px solid #ccc; border-radius: 4px; background: white; cursor: pointer; font-size: 0.9rem; }}
.btn.primary {{ background: #1976d2; color: white; border-color: #1976d2; }}
.btn.success {{ background: #388e3c; color: white; border-color: #388e3c; }}
.btn.danger {{ background: #d32f2f; color: white; border-color: #d32f2f; }}
.btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
.table-container {{ background: white; border: 1px solid #ddd; border-radius: 4px; overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; min-width: 900px; }}
th, td {{ border: 1px solid #eee; padding: 0.5rem; text-align: left; font-size: 0.85rem; vertical-align: top; }}
th {{ background: #f5f5f5; position: sticky; top: 0; z-index: 1; cursor: pointer; user-select: none; }}
th:hover {{ background: #eee; }}
th.sorted-asc::after {{ content: " ▲"; }}
th.sorted-desc::after {{ content: " ▼"; }}
tr:hover {{ background: #fafafa; }}
tr.accepted {{ background: #e8f5e9; }}
tr.rejected {{ background: #fce4ec; }}
.badge {{ display: inline-block; padding: 0.15rem 0.4rem; border-radius: 3px; font-size: 0.75rem; font-weight: 600; }}
.badge-verified {{ background: #e8f5e9; color: #2e7d32; }}
.badge-warn {{ background: #fff3e0; color: #f57f17; }}
.badge-mismatch {{ background: #fce4ec; color: #c62828; }}
.badge-retracted {{ background: #fce4ec; color: #c62828; }}
.badge-error {{ background: #eceff1; color: #546e7a; }}
.badge-unknown {{ background: #eceff1; color: #546e7a; }}
.badge-pending {{ background: #e3f2fd; color: #1565c0; }}
.badge-accepted {{ background: #e8f5e9; color: #2e7d32; }}
.badge-rejected {{ background: #fce4ec; color: #c62828; }}
.flags {{ font-family: monospace; font-size: 0.7rem; color: #666; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.decision-btn {{ padding: 0.2rem 0.5rem; font-size: 0.75rem; border-radius: 3px; border: 1px solid transparent; cursor: pointer; margin-right: 0.2rem; }}
.decision-btn.accept {{ background: #e8f5e9; color: #2e7d32; border-color: #a5d6a7; }}
.decision-btn.reject {{ background: #fce4ec; color: #c62828; border-color: #ef9a9a; }}
.decision-btn.pending {{ background: #e3f2fd; color: #1565c0; border-color: #90caf9; }}
.decision-btn.active {{ font-weight: bold; }}
.notes-input {{ width: 100%; font-size: 0.75rem; padding: 0.2rem; border: 1px solid #ddd; border-radius: 3px; }}
.stats {{ display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }}
.stat-card {{ background: white; border: 1px solid #ddd; border-radius: 4px; padding: 0.75rem 1rem; min-width: 120px; }}
.stat-card .label {{ font-size: 0.75rem; color: #666; text-transform: uppercase; }}
.stat-card .value {{ font-size: 1.5rem; font-weight: bold; color: #1a1a1a; }}
.stat-card.pass {{ border-left: 4px solid #388e3c; }}
.stat-card.fail {{ border-left: 4px solid #d32f2f; }}
.stat-card.other {{ border-left: 4px solid #546e7a; }}
.stat-card.pending {{ border-left: 4px solid #1976d2; }}
.stat-card.accepted {{ border-left: 4px solid #388e3c; }}
.stat-card.rejected {{ border-left: 4px solid #d32f2f; }}
.footer {{ margin-top: 1rem; padding: 1rem; background: white; border: 1px solid #ddd; border-radius: 4px; font-size: 0.85rem; color: #666; }}
.footer-row {{ display: flex; gap: 1rem; flex-wrap: wrap; align-items: center; }}
.hidden {{ display: none !important; }}
.score-bar {{ height: 6px; background: #eee; border-radius: 3px; overflow: hidden; width: 100px; }}
.score-bar-fill {{ height: 100%; background: linear-gradient(90deg, #4caf50, #ffeb3b, #f44336); }}
@media (max-width: 768px) {{
    .toolbar select, .toolbar input {{ width: 100%; }}
    table {{ min-width: 100%; }}
}}
</style>
</head>
<body>
<div class="header">
    <h1>VERIDEX Review Dashboard</h1>
    <div style="font-size: 0.85rem; color: #666;">
        <strong>Tool:</strong> veridex v{tool_version} |
        <strong>Entries:</strong> {total} |
        <strong>Generated:</strong> {html.escape(gen) if gen else 'unknown'}
    </div>
</div>

<div class="stats" id="stats">
    <div class="stat-card pass"><div class="label">Verified</div><div class="value" id="stat-verified">{verified}</div></div>
    <div class="stat-card fail"><div class="label">Failed</div><div class="value" id="stat-failed">{failed}</div></div>
    <div class="stat-card other"><div class="label">Other</div><div class="value" id="stat-other">{total - verified - failed}</div></div>
    <div class="stat-card pending"><div class="label">Pending Review</div><div class="value" id="stat-pending">{total}</div></div>
    <div class="stat-card accepted"><div class="label">Accepted</div><div class="value" id="stat-accepted">0</div></div>
    <div class="stat-card rejected"><div class="label">Rejected</div><div class="value" id="stat-rejected">0</div></div>
</div>

<div class="toolbar">
    <label>Status:
        <select id="filter-status">
            <option value="">All</option>
            <option value="VERIFIED">VERIFIED</option>
            <option value="VERIFIED_WITH_WARNINGS">VERIFIED_WITH_WARNINGS</option>
            <option value="MISMATCH">MISMATCH</option>
            <option value="DOI_NOT_FOUND">DOI_NOT_FOUND</option>
            <option value="NOT_FOUND">NOT_FOUND</option>
            <option value="NO_DOI_MATCHED">NO_DOI_MATCHED</option>
            <option value="NO_DOI_UNMATCHED">NO_DOI_UNMATCHED</option>
            <option value="UNREACHABLE">UNREACHABLE</option>
            <option value="AMBIGUOUS">AMBIGUOUS</option>
            <option value="RETRACTED">RETRACTED</option>
            <option value="ERROR">ERROR</option>
        </select>
    </label>
    <label>Decision:
        <select id="filter-decision">
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="accept">Accept</option>
            <option value="reject">Reject</option>
        </select>
    </label>
    <label>Search title/DOI:
        <input type="text" id="filter-search" placeholder="Filter...">
    </label>
    <label>Max fabrication score:
        <input type="range" id="filter-score" min="0" max="1" step="0.05" value="1">
        <span id="score-value">1.00</span>
    </label>
    <button class="btn primary" onclick="exportJSON()">Export JSON</button>
    <button class="btn primary" onclick="exportCSV()">Export CSV</button>
    <button class="btn success" onclick="acceptAllVisible()">Accept All Visible</button>
    <button class="btn danger" onclick="rejectAllVisible()">Reject All Visible</button>
    <button class="btn" onclick="resetAll()">Reset All</button>
</div>

<div class="table-container">
<table id="results-table">
<thead>
<tr>
    <th data-col="index">#</th>
    <th data-col="status">Status</th>
    <th data-col="decision">Decision</th>
    <th data-col="title">Title</th>
    <th data-col="authors">Authors</th>
    <th data-col="year">Year</th>
    <th data-col="journal">Journal</th>
    <th data-col="fabrication_score">Fab. Score</th>
    <th data-col="flags">Flags</th>
    <th data-col="retracted">Retracted</th>
    <th data-col="near_duplicate">Near Dup</th>
    <th data-col="weak_context">Weak Ctx</th>
    <th data-col="doi">DOI</th>
    <th data-col="source">Source</th>
    <th data-col="notes">Notes</th>
</tr>
</thead>
<tbody id="table-body"></tbody>
</table>
</div>

<div class="footer">
    <div class="footer-row">
        <span>VERIDEX v{tool_version} — Interactive review dashboard (offline, self-contained)</span>
        <span>Decisions are stored in browser localStorage and exported files. No data leaves this page.</span>
    </div>
</div>

<script>
const ROWS = {rows_json};
let currentSort = {{ col: null, asc: true }};
let filteredRows = [...ROWS];

const statusBadgeClass = {{
    "VERIFIED": "badge-verified",
    "VERIFIED_WITH_WARNINGS": "badge-warn",
    "MISMATCH": "badge-mismatch",
    "DOI_NOT_FOUND": "badge-mismatch",
    "NOT_FOUND": "badge-mismatch",
    "NO_DOI_MATCHED": "badge-warn",
    "NO_DOI_UNMATCHED": "badge-mismatch",
    "UNREACHABLE": "badge-error",
    "AMBIGUOUS": "badge-unknown",
    "RETRACTED": "badge-retracted",
    "ERROR": "badge-error",
}};

function badgeClassForStatus(s) {{
    return statusBadgeClass[s] || "badge-unknown";
}}

function badgeClassForDecision(d) {{
    return "badge-" + d;
}}

function renderScoreBar(score) {{
    const pct = Math.round(score * 100);
    let color = "#4caf50";
    if (score >= 0.7) color = "#f44336";
    else if (score >= 0.4) color = "#ffeb3b";
    return `<div class="score-bar"><div class="score-bar-fill" style="width:{{pct}}%;background:{{color}}"></div></div>`;
}}

function escapeHtml(text) {{
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}}

function renderRows() {{
    const tbody = document.getElementById('table-body');
    tbody.innerHTML = '';
    filteredRows.forEach((row, i) => {{
        const tr = document.createElement('tr');
        if (row.decision === 'accept') tr.classList.add('accepted');
        else if (row.decision === 'reject') tr.classList.add('rejected');

        const statusBadge = `<span class="badge {{badgeClassForStatus(row.status)}}">{{escapeHtml(row.status)}}</span>`;
        const decisionBadge = `<span class="badge {{badgeClassForDecision(row.decision)}}">{{row.decision}}</span>`;

        tr.innerHTML = `
            <td>{{row.index}}</td>
            <td>{{statusBadge}}</td>
            <td>
                <button class="decision-btn accept {{row.decision === 'accept' ? 'active' : ''}}" onclick="setDecision({{row.index}}, 'accept')" title="Accept">✓ Accept</button>
                <button class="decision-btn reject {{row.decision === 'reject' ? 'active' : ''}}" onclick="setDecision({{row.index}}, 'reject')" title="Reject">✗ Reject</button>
                <button class="decision-btn pending {{row.decision === 'pending' ? 'active' : ''}}" onclick="setDecision({{row.index}}, 'pending')" title="Pending">⟳ Pending</button>
            </td>
            <td>{{escapeHtml(row.title || '')}}</td>
            <td>{{escapeHtml(row.authors || '')}}</td>
            <td>{{row.year || ''}}</td>
            <td>{{escapeHtml(row.journal || '')}}</td>
            <td>{{renderScoreBar(row.fabrication_score)}} <span style="font-size:0.75rem;color:#666;">{{row.fabrication_score.toFixed(3)}}</span></td>
            <td class="flags">{{escapeHtml(row.flags.join(' | ') || 'none')}}</td>
            <td>{{row.retracted ? 'Yes' : 'No'}}</td>
            <td>{{row.near_duplicate ? 'Yes' : 'No'}}</td>
            <td>{{row.weak_context ? 'Yes' : 'No'}}</td>
            <td>{{escapeHtml(row.doi || '')}}</td>
            <td>{{escapeHtml(row.source || '')}}</td>
            <td><input type="text" class="notes-input" value="{{escapeHtml(row.notes)}}" onchange="setNotes({{row.index}}, this.value)" placeholder="Notes..."></td>
        `;
        tbody.appendChild(tr);
    }});
    updateStats();
}}

function setDecision(index, decision) {{
    const row = ROWS.find(r => r.index === index);
    if (row) {{
        row.decision = decision;
        applyFilters();
    }}
}}

function setNotes(index, notes) {{
    const row = ROWS.find(r => r.index === index);
    if (row) {{
        row.notes = notes;
    }}
}}

function applyFilters() {{
    const statusFilter = document.getElementById('filter-status').value;
    const decisionFilter = document.getElementById('filter-decision').value;
    const searchFilter = document.getElementById('filter-search').value.toLowerCase();
    const maxScore = parseFloat(document.getElementById('filter-score').value);
    document.getElementById('score-value').textContent = maxScore.toFixed(2);

    filteredRows = ROWS.filter(row => {{
        if (statusFilter && row.status !== statusFilter) return false;
        if (decisionFilter && row.decision !== decisionFilter) return false;
        if (row.fabrication_score > maxScore) return false;
        if (searchFilter) {{
            const searchable = (row.title + ' ' + row.doi + ' ' + row.authors).toLowerCase();
            if (!searchable.includes(searchFilter)) return false;
        }}
        return true;
    }});

    // Re-apply current sort
    if (currentSort.col) {{
        sortRows(currentSort.col, currentSort.asc);
    }} else {{
        renderRows();
    }}
}}

function sortRows(col, asc) {{
    currentSort = {{ col, asc }};
    filteredRows.sort((a, b) => {{
        let av = a[col];
        let bv = b[col];
        if (av === undefined || av === null) av = '';
        if (bv === undefined || bv === null) bv = '';
        if (typeof av === 'string') av = av.toLowerCase();
        if (typeof bv === 'string') bv = bv.toLowerCase();
        if (av < bv) return asc ? -1 : 1;
        if (av > bv) return asc ? 1 : -1;
        return 0;
    }});
    // Update header indicators
    document.querySelectorAll('th[data-col]').forEach(th => {{
        th.classList.remove('sorted-asc', 'sorted-desc');
        if (th.dataset.col === col) {{
            th.classList.add(asc ? 'sorted-asc' : 'sorted-desc');
        }}
    }});
    renderRows();
}}

function updateStats() {{
    const counts = {{ pending: 0, accept: 0, reject: 0 }};
    ROWS.forEach(r => counts[r.decision]++);
    document.getElementById('stat-pending').textContent = counts.pending;
    document.getElementById('stat-accepted').textContent = counts.accept;
    document.getElementById('stat-rejected').textContent = counts.reject;
}}

function acceptAllVisible() {{
    filteredRows.forEach(row => {{ row.decision = 'accept'; }});
    applyFilters();
}}

function rejectAllVisible() {{
    filteredRows.forEach(row => {{ row.decision = 'reject'; }});
    applyFilters();
}}

function resetAll() {{
    ROWS.forEach(row => {{ row.decision = 'pending'; row.notes = ''; }});
    applyFilters();
}}

function exportData(format) {{
    const data = ROWS.map(row => ({{
        index: row.index,
        status: row.status,
        decision: row.decision,
        title: row.title,
        authors: row.authors,
        year: row.year,
        journal: row.journal,
        fabrication_score: row.fabrication_score,
        flags: row.flags.join(' | '),
        retracted: row.retracted,
        near_duplicate: row.near_duplicate,
        weak_context: row.weak_context,
        doi: row.doi,
        source: row.source,
        notes: row.notes,
    }}));
    if (format === 'json') {{
        const blob = new Blob([JSON.stringify({{ tool: 'veridex', version: '{tool_version}', generated_at: new Date().toISOString(), decisions: data }}, null, 2)], {{ type: 'application/json' }});
        downloadBlob(blob, 'veridex_decisions.json');
    }} else {{
        const headers = ['index','status','decision','title','authors','year','journal','fabrication_score','flags','retracted','near_duplicate','weak_context','doi','source','notes'];
        const rows = data.map(r => headers.map(h => '"' + String(r[h] || '').replace(/"/g, '""') + '"').join(','));
        const csv = [headers.join(','), ...rows].join('\\n');
        const blob = new Blob([csv], {{ type: 'text/csv' }});
        downloadBlob(blob, 'veridex_decisions.csv');
    }}
}}

function exportJSON() {{ exportData('json'); }}
function exportCSV() {{ exportData('csv'); }}

function downloadBlob(blob, filename) {{
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}}

// Initialize
document.getElementById('filter-status').addEventListener('change', applyFilters);
document.getElementById('filter-decision').addEventListener('change', applyFilters);
document.getElementById('filter-search').addEventListener('input', applyFilters);
document.getElementById('filter-score').addEventListener('input', applyFilters);
document.querySelectorAll('th[data-col]').forEach(th => {{
    th.addEventListener('click', () => {{
        const col = th.dataset.col;
        const asc = currentSort.col === col ? !currentSort.asc : true;
        sortRows(col, asc);
    }});
}});

// Load any saved decisions from localStorage
function loadSaved() {{
    try {{
        const saved = localStorage.getItem('veridex_dashboard_decisions');
        if (saved) {{
            const parsed = JSON.parse(saved);
            parsed.forEach(s => {{
                const row = ROWS.find(r => r.index === s.index);
                if (row) {{
                    row.decision = s.decision;
                    row.notes = s.notes || '';
                }}
            }});
        }}
    }} catch (e) {{}}
    applyFilters();
}}

// Save to localStorage on any change
function saveToStorage() {{
    try {{
        const data = ROWS.map(r => ({{
            index: r.index,
            decision: r.decision,
            notes: r.notes,
        }}));
        localStorage.setItem('veridex_dashboard_decisions', JSON.stringify(data));
    }} catch (e) {{}}
}}
const originalSetDecision = setDecision;
setDecision = function(index, decision) {{
    originalSetDecision(index, decision);
    saveToStorage();
}};
const originalSetNotes = setNotes;
setNotes = function(index, notes) {{
    originalSetNotes(index, notes);
    saveToStorage();
}};

loadSaved();
</script>
</body>
</html>"""

    Path(out_path).write_text(dashboard_html, encoding="utf-8")


def render_dashboard(
    results: list[AuditResult],
    entries: list[ParsedReference],
    out_path: str | Path,
    meta: dict[str, Any] | None = None,
) -> None:
    """Render an interactive HTML review dashboard to out_path."""
    _render_dashboard(results, entries, out_path, meta or {})


def render_cross_check_report(
    results: list[AuditResult],
    entries: list[ParsedReference],
    in_text_citations: list[dict[str, Any]],
    out_path: str | Path,
    meta: dict[str, Any] | None = None,
) -> None:
    """Render a cross-check report comparing in-text citations to reference list entries.

    Identifies:
    - In-text citations with no matching reference list entry (unmatched citations)
    - Reference list entries with no in-text citation (orphan references)
    - Weak context support for matched pairs
    """
    import html
    from collections import defaultdict

    meta = meta or {}
    gen = _generated_at(results, meta)

    # Map reference list entries by index (0-based)
    entry_by_idx = {i: entry for i, entry in enumerate(entries)}

    # Map in-text citations by ref_index
    citations_by_ref_idx = defaultdict(list)
    unmatched_citations = []
    for citation in in_text_citations:
        ref_idx = citation.get("ref_index")
        if ref_idx is not None and isinstance(ref_idx, int) and 0 <= ref_idx < len(entries):
            citations_by_ref_idx[ref_idx].append(citation)
        else:
            unmatched_citations.append(citation)

    # Find orphan references (entries with no citations)
    orphan_indices = [i for i in range(len(entries)) if i not in citations_by_ref_idx]

    # Build report
    lines = []
    lines.append("# VERIDEX Cross-Check Report: In-Text Citations vs Reference List")
    lines.append("")
    if gen:
        lines.append(f"**Generated:** {gen}")
    lines.append(f"**Tool:** veridex v0.3.0")
    lines.append(f"**Reference list entries:** {len(entries)}")
    lines.append(f"**In-text citations found:** {len(in_text_citations)}")
    lines.append(f"**Matched pairs:** {len(citations_by_ref_idx)}")
    lines.append(f"**Unmatched citations:** {len(unmatched_citations)}")
    lines.append(f"**Orphan references:** {len(orphan_indices)}")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    lines.append(f"| Matched citation-reference pairs | {len(citations_by_ref_idx)} |")
    lines.append(f"| Unmatched in-text citations | {len(unmatched_citations)} |")
    lines.append(f"| Orphan reference list entries | {len(orphan_indices)} |")
    lines.append("")

    # Unmatched citations
    if unmatched_citations:
        lines.append("## Unmatched In-Text Citations")
        lines.append("")
        lines.append("These citations appear in the text but have no corresponding reference list entry.")
        lines.append("")
        lines.append("| Citation | Sentence Context |")
        lines.append("|----------|------------------|")
        for cit in unmatched_citations:
            marker = html.escape(citation.get("marker", ""))
            sentence = html.escape(citation.get("sentence", "")[:200])
            lines.append(f"| {marker} | {sentence} |")
        lines.append("")

    # Orphan references
    if orphan_indices:
        lines.append("## Orphan Reference List Entries")
        lines.append("")
        lines.append("These references appear in the reference list but are never cited in the text.")
        lines.append("")
        lines.append("| Index | Title | Authors | Year |")
        lines.append("|-------|-------|---------|------|")
        for idx in orphan_indices:
            entry = entry_by_idx[idx]
            title = html.escape(entry.title or "NO TITLE")
            authors = html.escape(_authors_str(entry.authors))
            year = str(entry.year) if entry.year else ""
            lines.append(f"| {idx} | {title} | {authors} | {year} |")
        lines.append("")

    # Matched pairs with weak context
    weak_pairs = []
    for ref_idx, citations in citations_by_ref_idx.items():
        entry = entry_by_idx[ref_idx]
        for cit in citations:
            # Check if result has weak context flag
            if ref_idx < len(results):
                result = results[ref_idx]
                if "weak_context_support" in result.flags:
                    weak_pairs.append({
                        "ref_idx": ref_idx,
                        "citation": cit,
                        "entry": entry,
                        "score": getattr(result, 'context', {}).get(cit.get("marker", ""), {}).get("score", 0.0) if hasattr(result, 'context') else 0.0
                    })

    if weak_pairs:
        lines.append("## Matched Pairs with Weak Context Support")
        lines.append("")
        lines.append("These citation-reference pairs have low contextual similarity (BM25/TF-IDF heuristic).")
        lines.append("")
        lines.append("| Ref Index | Citation | Reference Title | Support Score |")
        lines.append("|-----------|----------|-----------------|---------------|")
        for pair in weak_pairs:
            marker = html.escape(pair["citation"].get("marker", ""))
            title = html.escape(pair["entry"].title or "NO TITLE")
            score = pair.get("score", 0.0)
            lines.append(f"| {pair['ref_idx']} | {marker} | {title} | {score:.3f} |")
        lines.append("")

    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


def render_cross_check_report_html(
    results: list[AuditResult],
    entries: list[ParsedReference],
    in_text_citations: list[dict[str, Any]],
    out_path: str | Path,
    meta: dict[str, Any] | None = None,
) -> None:
    """Render an HTML cross-check report."""
    import html
    from collections import defaultdict

    meta = meta or {}
    gen = _generated_at(results, meta)

    entry_by_idx = {i: entry for i, entry in enumerate(entries)}
    citations_by_ref_idx = defaultdict(list)
    unmatched_citations = []
    for citation in in_text_citations:
        ref_idx = citation.get("ref_index")
        if ref_idx is not None and isinstance(ref_idx, int) and 0 <= ref_idx < len(entries):
            citations_by_ref_idx[ref_idx].append(citation)
        else:
            unmatched_citations.append(citation)

    orphan_indices = [i for i in range(len(entries)) if i not in citations_by_ref_idx]

    # HTML template
    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='utf-8'>",
        "<title>VERIDEX Cross-Check Report</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.5; }",
        "h1, h2, h3 { color: #1a1a1a; }",
        "table { border-collapse: collapse; width: 100%; margin: 1rem 0; }",
        "th, td { border: 1px solid #ddd; padding: 0.5rem; text-align: left; }",
        "th { background: #f5f5f5; }",
        ".summary { display: flex; gap: 2rem; flex-wrap: wrap; margin: 1rem 0; }",
        ".card { background: #fafafa; border: 1px solid #ddd; border-radius: 4px; padding: 1rem; min-width: 150px; }",
        ".card.warn { border-left: 4px solid #f57f17; }",
        ".card.fail { border-left: 4px solid #c62828; }",
        ".card.ok { border-left: 4px solid #2e7d32; }",
        ".badge { padding: 0.2rem 0.5rem; border-radius: 3px; font-size: 0.85rem; font-weight: bold; }",
        ".badge-unmatched { background: #fff3e0; color: #f57f17; }",
        ".badge-orphan { background: #fce4ec; color: #c62828; }",
        ".badge-matched { background: #e8f5e9; color: #2e7d32; }",
        ".badge-weak { background: #fff3e0; color: #f57f17; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>VERIDEX Cross-Check Report</h1>",
        *( [f"<p><strong>Generated:</strong> {html.escape(gen)}</p>"] if gen else [] ),
        f"<p><strong>Tool:</strong> veridex v0.3.0</p>",
        f"<p><strong>Reference list entries:</strong> {len(entries)}</p>",
        f"<p><strong>In-text citations found:</strong> {len(in_text_citations)}</p>",
        f"<p><strong>Matched pairs:</strong> {len(citations_by_ref_idx)}</p>",
        f"<p><strong>Unmatched citations:</strong> {len(unmatched_citations)}</p>",
        f"<p><strong>Orphan references:</strong> {len(orphan_indices)}</p>",
        "<h2>Summary</h2>",
        "<div class='summary'>",
        f"<div class='card ok'><strong>Matched Pairs</strong><br>{len(citations_by_ref_idx)}</div>",
        f"<div class='card warn'><strong>Unmatched Citations</strong><br>{len(unmatched_citations)}</div>",
        f"<div class='card fail'><strong>Orphan References</strong><br>{len(orphan_indices)}</div>",
        "</div>",
    ]

    if unmatched_citations:
        html_parts.append("<h2>Unmatched In-Text Citations</h2>")
        html_parts.append("<p>These citations appear in the text but have no corresponding reference list entry.</p>")
        html_parts.append("<table>")
        html_parts.append("<thead><tr><th>Citation</th><th>Sentence Context</th></tr></thead>")
        html_parts.append("<tbody>")
        for cit in unmatched_citations:
            marker = html.escape(cit.get("marker", ""))
            sentence = html.escape(cit.get("sentence", "")[:300])
            html_parts.append(f"<tr><td><span class='badge badge-unmatched'>{marker}</span></td><td>{sentence}</td></tr>")
        html_parts.append("</tbody></table>")

    if orphan_indices:
        html_parts.append("<h2>Orphan Reference List Entries</h2>")
        html_parts.append("<p>These references appear in the reference list but are never cited in the text.</p>")
        html_parts.append("<table>")
        html_parts.append("<thead><tr><th>Index</th><th>Title</th><th>Authors</th><th>Year</th></tr></thead>")
        html_parts.append("<tbody>")
        for idx in orphan_indices:
            entry = entry_by_idx[idx]
            title = html.escape(entry.title or "NO TITLE")
            authors = html.escape(_authors_str(entry.authors))
            year = str(entry.year) if entry.year else ""
            html_parts.append(f"<tr><td>{idx}</td><td><span class='badge badge-orphan'>{title}</span></td><td>{authors}</td><td>{year}</td></tr>")
        html_parts.append("</tbody></table>")

    # Weak context matched pairs
    weak_pairs = []
    for ref_idx, citations in citations_by_ref_idx.items():
        entry = entry_by_idx[ref_idx]
        for cit in citations:
            if ref_idx < len(results):
                result = results[ref_idx]
                if "weak_context_support" in result.flags:
                    score = 0.0
                    if hasattr(result, 'context'):
                        ctx = result.context.get(cit.get("marker", ""), {})
                        score = ctx.get("score", 0.0) if isinstance(ctx, dict) else 0.0
                    weak_pairs.append({
                        "ref_idx": ref_idx,
                        "citation": cit,
                        "entry": entry,
                        "score": score
                    })

    if weak_pairs:
        html_parts.append("<h2>Matched Pairs with Weak Context Support</h2>")
        html_parts.append("<p>These citation-reference pairs have low contextual similarity (BM25/TF-IDF heuristic).</p>")
        html_parts.append("<table>")
        html_parts.append("<thead><tr><th>Ref Index</th><th>Citation</th><th>Reference Title</th><th>Support Score</th></tr></thead>")
        html_parts.append("<tbody>")
        for pair in weak_pairs:
            marker = html.escape(pair["citation"].get("marker", ""))
            title = html.escape(pair["entry"].title or "NO TITLE")
            score = pair.get("score", 0.0)
            html_parts.append(f"<tr><td>{pair['ref_idx']}</td><td><span class='badge badge-weak'>{marker}</span></td><td>{title}</td><td>{score:.3f}</td></tr>")
        html_parts.append("</tbody></table>")

    html_parts.extend(["</body>", "</html>"])
    Path(out_path).write_text("\n".join(html_parts), encoding="utf-8")


__all__ = ["render_report", "summary", "render_dashboard", "render_cross_check_report", "render_cross_check_report_html"]