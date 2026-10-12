# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Programmatic API for VERIDEX. Thin, documented, stdlib only.

Everything the command line can do is reachable from here. The audit pipeline
resolves each parsed reference through the enabled sources, picks the best
matching record, evaluates it, optionally records provenance in the ledger and
returns a deterministic, index-sorted list of :class:`AuditResult`.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Optional

from veridex import matching
from veridex.httpclient import HttpClient
from veridex.ledger import Ledger
from veridex.ledger import verify_ledger as _verify_ledger
from veridex.ledger import diff_ledgers as _diff_ledgers
from veridex.models import (
    AuditResult,
    Evidence,
    ParsedReference,
    ResolvedRecord,
    TOOL_NAME,
    TOOL_VERSION,
    Status,
    retraction_status,
)
from veridex.parsing import parse_file, parse_text
from veridex.policy import evaluate_policy as _evaluate_policy
from veridex.policy import load_policy as _load_policy
from veridex.policy import validate_policy as _validate_policy
from veridex.resolvers import SourceOpts, build as build_source, source_names

LOGGER = logging.getLogger("veridex")

# Injectable transport for offline tests: tests may monkeypatch this module
# attribute with a ``callable(url, timeout) -> Response``.
TRANSPORT: Any = None

_ADAPTERS = (
    "arxiv",
    "crossref",
    "datacite",
    "doaj",
    "europepmc",
    "openalex",
    "openlibrary",
    "pubmed",
    "semscholar",
)


def _register_adapters() -> None:
    """Import resolver adapters so their registration decorators run."""
    for name in _ADAPTERS:
        try:
            importlib.import_module(f"veridex.resolvers.{name}")
        except Exception:  # pragma: no cover - optional adapter
            continue


_register_adapters()


try:  # optional analysis modules (other units)
    from veridex import fabrication as _fabrication
except Exception:  # pragma: no cover - module may not exist yet
    _fabrication = None

try:
    from veridex import integrity as _integrity
except Exception:  # pragma: no cover
    _integrity = None

try:
    from veridex import context as _context
except Exception:  # pragma: no cover
    _context = None

try:
    from veridex import repair as _repair
except Exception:  # pragma: no cover
    _repair = None

try:
    from veridex import reports as _reports
except Exception:  # pragma: no cover
    _reports = None


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def parse_references(input: Any, fmt: str = "auto") -> list[ParsedReference]:
    """Parse references from a path (if it exists) or from literal text."""
    if isinstance(input, (list, tuple)):
        return list(input)
    if isinstance(input, os.PathLike):
        return parse_file(os.fspath(input), fmt=fmt)
    if isinstance(input, str):
        if os.path.exists(input):
            return parse_file(input, fmt=fmt)
        return parse_text(input, fmt=fmt)
    raise TypeError("input must be a path, text, or list of ParsedReference")


def load_policy(path_or_text: Any) -> dict[str, Any]:
    """Load a policy mapping from a path or inline text (see policy module)."""
    return _load_policy(path_or_text)


def validate_policy(policy: Any) -> list[str]:
    """Return validation problems for a policy mapping."""
    return _validate_policy(policy)


def evaluate_policy(results: Iterable[AuditResult], policy: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate audit results against a policy, returning violations."""
    return _evaluate_policy(list(results), policy)


# --------------------------------------------------------------------------
# Source selection
# --------------------------------------------------------------------------
def _select_sources(sources: Any) -> list[str]:
    available = set(source_names())
    if sources is None:
        return sorted(available)
    if isinstance(sources, dict):
        return sorted(name for name, enabled in sources.items() if enabled and name in available)
    entries = [str(item).strip() for item in sources if str(item).strip()]
    positives = [e for e in entries if not e.startswith("no-")]
    negatives = {e[3:] for e in entries if e.startswith("no-")}
    if positives:
        chosen = {e for e in positives if e in available}
    else:
        chosen = set(available)
    return sorted(chosen - negatives)


def _make_client(cache_dir: Optional[str], max_interval: Optional[float] = None) -> HttpClient:
    user_agent = f"{TOOL_NAME}/{TOOL_VERSION} (+https://github.com/madeesh-nissanka/veridex)"
    interval = 0.0 if TRANSPORT is not None else 0.5
    if max_interval is not None:
        interval = max_interval
    return HttpClient(
        user_agent=user_agent,
        cache_dir=cache_dir,
        transport=TRANSPORT,
        min_interval=interval,
    )


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------
def _pick_best(
    ref: ParsedReference, records: list[ResolvedRecord], semantic: bool = False
) -> tuple[Optional[ResolvedRecord], dict[str, Any], list[ResolvedRecord]]:
    scored: list[tuple[float, float, int, ResolvedRecord, dict[str, Any]]] = []
    for order, record in enumerate(records):
        evaluation = matching.evaluate(ref, record, semantic=semantic)
        scores = evaluation.get("scores", {})
        scored.append(
            (
                float(scores.get("overall", 0.0)),
                float(scores.get("title_sim", 0.0)),
                -order,
                record,
                evaluation,
            )
        )
    if not scored:
        return None, {}, []
    scored.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    candidates = sorted(scored, key=lambda row: (row[3].source, row[3].source_id, row[3].title or ""))
    best_eval = scored[0][4]
    return scored[0][3], best_eval, [row[3] for row in candidates]


def _no_record_status(ref: ParsedReference) -> str:
    if ref.doi:
        return Status.DOI_NOT_FOUND
    if ref.identifier():
        return Status.NOT_FOUND
    return Status.NOT_FOUND


def _run_id(refs: list[ParsedReference], sources: list[str]) -> str:
    payload = "|".join(sources) + "||" + "|".join(
        (r.raw or r.identifier() or str(r.index)) for r in refs
    )
    return "run-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _ledger_entry(result: AuditResult, run_id: str, evidence: Evidence) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "tool_version": TOOL_VERSION,
        "entry_index": result.index,
        "source": evidence.source,
        "request_url": evidence.request_url,
        "http_status": evidence.http_status,
        "response_sha256": evidence.response_sha256,
        "response_bytes": evidence.response_bytes,
        "from_cache": evidence.from_cache,
        "status": result.status,
        "flags": list(result.flags),
        "evidence_type": "lookup",
    }


def _checkpoint_entry(result: AuditResult, run_id: str) -> dict[str, Any]:
    """Create a checkpoint entry for a completed reference."""
    return {
        "run_id": run_id,
        "tool_version": TOOL_VERSION,
        "entry_index": result.index,
        "evidence_type": "checkpoint",
        "result": result.to_dict(),
    }


def _load_completed_from_ledger(
    ledger_path: str, run_id: str, total_refs: int
) -> tuple[set[int], dict[int, AuditResult]]:
    """Load completed entries from a ledger for a specific run_id.

    Returns a set of completed indices and a dict mapping index -> AuditResult.
    """
    from .ledger import read_records

    completed_indices: set[int] = set()
    completed_results: dict[int, AuditResult] = {}

    try:
        records = read_records(ledger_path, run_id=run_id)
        for entry in records:
            idx = entry.get("entry_index")
            if idx is None:
                continue

            # Check for checkpoint entries that contain full results
            if entry.get("evidence_type") == "checkpoint":
                result_data = entry.get("result")
                if result_data:
                    # Reconstruct AuditResult from dict
                    result = AuditResult(
                        index=result_data.get("index", idx),
                        input=None,  # ParsedReference not stored in checkpoint
                        record=None,  # ResolvedRecord not stored
                        candidates=[],
                        status=result_data.get("status", "UNKNOWN"),
                        flags=result_data.get("flags", []),
                        scores=result_data.get("scores", {}),
                        evidence=[],
                        fabrication=result_data.get("fabrication", {"score": 0.0, "signals": []}),
                        integrity=result_data.get("integrity", []),
                        repairs=result_data.get("repairs", []),
                    )
                    completed_results[idx] = result
                    completed_indices.add(idx)
            else:
                # Legacy lookup entry - just track index as completed
                completed_indices.add(idx)
    except Exception as exc:
        LOGGER.warning("Failed to load resume data from ledger: %s", exc)

    return completed_indices, completed_results


def audit_references(
    input: Any,
    out_dir: Optional[str] = None,
    sources: Any = None,
    policy: Any = None,
    ledger_path: Optional[str] = None,
    manuscript: Optional[str] = None,
    fmt: str = "auto",
    cache_dir: Optional[str] = None,
    max_workers: Optional[int] = None,
    transport: Any = None,
    retraction_file: Optional[str] = None,
    semantic: bool = False,
    resume_from: Optional[str] = None,
    batch_size: int = 1000,
) -> list[AuditResult]:
    """Audit references and return results in input order.

    ``input`` is a path, literal text, or parsed references. ``sources`` may be
    a list of source names (``no-`` prefix disables) or a mapping name->bool.
    ``policy`` is a path, inline text, or already-loaded mapping. When
    ``ledger_path`` is given every network interaction is appended to the hash
    chain. No network access occurs unless a real transport is used.
    ``retraction_file`` points to an offline Retraction Watch CSV / Crossref
    update JSON / JSONL file whose notices are applied after resolution.
    ``resume_from`` specifies a run_id to resume from; completed entries from
    that run are loaded from the ledger and skipped. ``batch_size`` controls
    how many references are processed per batch for memory-bounded operation
    (default 1000, used when ledger_path is set).
    """
    global TRANSPORT
    previous_transport = TRANSPORT
    if transport is not None:
        TRANSPORT = transport

    try:
        refs = parse_references(input, fmt=fmt)
        if not refs:
            return []

        enabled = _select_sources(sources)
        client = _make_client(cache_dir)
        instances = {}
        for name in enabled:
            instance = build_source(name, client, SourceOpts(enabled=True))
            if instance is not None:
                instances[name] = instance

        run_id = _run_id(refs, sorted(instances))
        if resume_from == "auto":
            resume_from = run_id

        # Resume logic: if resume_from is specified and ledger_path exists,
        # load completed entries from the ledger to skip re-processing
        completed_indices: set[int] = set()
        completed_results: dict[int, AuditResult] = {}
        if resume_from and ledger_path and os.path.exists(ledger_path):
            completed_indices, completed_results = _load_completed_from_ledger(
                ledger_path, resume_from, len(refs)
            )
            if completed_indices:
                LOGGER.info("Resuming from run %s: %d/%d entries already completed",
                            resume_from, len(completed_indices), len(refs))

        def _audit_one(ref: ParsedReference) -> AuditResult:
            records: list[ResolvedRecord] = []
            evidence: list[Evidence] = []
            for name in sorted(instances):
                try:
                    found, events = instances[name].lookup(ref)
                except Exception as exc:  # pragma: no cover - defensive
                    LOGGER.warning("source %s failed on entry %s: %s", name, ref.index, exc)
                    found, events = [], []
                records.extend(found)
                evidence.extend(events)

            best, best_eval, candidates = _pick_best(ref, records, semantic=semantic)

            if best is not None:
                status = str(best_eval.get("status", Status.MISMATCH))
                flags = list(best_eval.get("flags", []))
                scores = dict(best_eval.get("scores", {}))
            else:
                status = _no_record_status(ref)
                flags = ["no_matching_record"]
                scores = {}

            result = AuditResult(
                index=ref.index,
                input=ref,
                record=best,
                candidates=candidates,
                status=status,
                flags=sorted(set(flags)),
                scores=scores,
                evidence=evidence,
            )

            if _fabrication is not None:
                summary = {
                    "sources": sorted(instances),
                    "evidence_count": len(evidence),
                    "status": status,
                }
                try:
                    result.fabrication = _fabrication.score_fabrication(
                        ref, best, best_eval, summary
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    LOGGER.warning("fabrication scoring failed: %s", exc)
            if not result.fabrication:
                result.fabrication = {"score": 0.0, "signals": []}

            if _integrity is not None and records:
                try:
                    result.integrity = _integrity.collect_integrity(records)
                except Exception as exc:  # pragma: no cover - defensive
                    LOGGER.warning("integrity collection failed: %s", exc)

            if retraction_status(result):
                if Status.RETRACTED not in result.flags:
                    result.flags = sorted(set(result.flags + [Status.RETRACTED.lower()]))
                result.status = Status.RETRACTED

            if _repair is not None:
                try:
                    result.repairs = _repair.suggest_repairs(result)
                except Exception as exc:  # pragma: no cover - defensive
                    LOGGER.warning("repair suggestion failed: %s", exc)

            return result

        worker_count = max(1, int(max_workers)) if max_workers else 1

        # Process in batches for memory efficiency when ledger_path is set
        use_batching = ledger_path is not None and len(refs) > batch_size

        if use_batching:
            # Process in batches, writing ledger incrementally
            all_results: list[AuditResult] = []

            for batch_start in range(0, len(refs), batch_size):
                batch_end = min(batch_start + batch_size, len(refs))
                batch_refs = refs[batch_start:batch_end]

                # Filter out entries whose full result was checkpointed
                to_process = [r for r in batch_refs if r.index not in completed_results]

                if worker_count > 1 and len(to_process) > 1:
                    with ThreadPoolExecutor(max_workers=worker_count) as pool:
                        batch_results = list(pool.map(_audit_one, to_process))
                else:
                    batch_results = [_audit_one(r) for r in to_process]

                # Merge completed and new results for this batch
                for r in batch_refs:
                    if r.index in completed_results:
                        all_results.append(completed_results[r.index])
                    else:
                        # Find in batch_results
                        for br in batch_results:
                            if br.index == r.index:
                                all_results.append(br)
                                break

                # Write batch to ledger incrementally (evidence + checkpoints)
                if ledger_path:
                    ledger = Ledger(ledger_path)
                    for result in batch_results:
                        for event in result.evidence:
                            ledger.append(_ledger_entry(result, run_id, event), run_id=run_id)
                        # Write checkpoint for this completed reference
                        ledger.append(_checkpoint_entry(result, run_id), run_id=run_id)

            # Sort final results
            all_results.sort(key=lambda r: r.index)
            results = all_results
        else:
            to_audit = [ref for ref in refs if ref.index not in completed_results]
            if worker_count > 1 and len(to_audit) > 1:
                with ThreadPoolExecutor(max_workers=worker_count) as pool:
                    results = list(pool.map(_audit_one, to_audit))
            else:
                results = [_audit_one(ref) for ref in to_audit]

            # Merge completed results
            if completed_results:
                merged = []
                for ref in refs:
                    if ref.index in completed_results:
                        merged.append(completed_results[ref.index])
                    else:
                        for r in results:
                            if r.index == ref.index:
                                merged.append(r)
                                break
                results = merged
            else:
                results.sort(key=lambda r: r.index)

        if retraction_file:
            from .retractions import apply_retractions, load_retractions

            table = load_retractions(retraction_file)
            apply_retractions(results, table)

        if manuscript and _context is not None:
            _apply_context(manuscript, results)

        if ledger_path and not use_batching:
            ledger = Ledger(ledger_path)
            for result in results:
                for event in result.evidence:
                    ledger.append(_ledger_entry(result, run_id, event), run_id=run_id)
                ledger.append(_checkpoint_entry(result, run_id), run_id=run_id)

        if out_dir:
            write_report(results, out_dir)

        return results
    finally:
        TRANSPORT = previous_transport


def _apply_context(manuscript: str, results: list[AuditResult]) -> None:
    """Attach heuristic context support from a manuscript (guarded)."""
    try:
        from veridex.parsing.docx import extract_docx

        extracted = extract_docx(manuscript)
        citations = extracted.get("in_text_citations", []) if isinstance(extracted, dict) else []
        _context.analyze_citations(citations, results)
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.warning("context analysis failed: %s", exc)


# --------------------------------------------------------------------------
# Ledger / diffs / reports
# --------------------------------------------------------------------------
def verify_ledger(path: str) -> dict[str, Any]:
    """Verify the hash chain at ``path``."""
    return _verify_ledger(path)


def diff_runs(ledger_path: str, run_a: str, run_b: str) -> list[dict[str, Any]]:
    """Compare the latest per-URL records of two runs in a ledger."""
    return _diff_ledgers(ledger_path, run_a, run_b)


_EXT = {
    "md": "md",
    "markdown": "md",
    "text": "txt",
    "txt": "txt",
    "html": "html",
    "json": "json",
    "csv": "csv",
    "sarif": "sarif",
}


def write_report(
    results: list[AuditResult],
    out_dir: str,
    fmt: str = "md",
    meta: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Write a report file into ``out_dir``; returns the path written.

    Uses the reports module when available and otherwise falls back to a plain
    JSON dump so the CLI never depends on another unit being finished.
    """
    if fmt.lower() == "all":
        written = [write_report(results, out_dir, f, meta) for f in ("json", "md", "html", "csv", "sarif")]
        return written[0]
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    extension = _EXT.get(fmt.lower(), "md")
    out_path = directory / f"report.{extension}"

    if _reports is not None and hasattr(_reports, "render_report"):
        entries = [r.input for r in results]
        try:
            written = _reports.render_report(results, entries, fmt, str(out_path), meta or {})
            return written if isinstance(written, str) else str(out_path)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("report rendering failed, falling back to JSON: %s", exc)
            out_path = directory / "report.json"

    payload = {
        "tool": TOOL_NAME,
        "version": TOOL_VERSION,
        "meta": meta or {},
        "results": [r.to_dict() for r in results],
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(out_path)


def summarize(results: Iterable[AuditResult]) -> dict[str, int]:
    """Count statuses across results (deterministic key order)."""
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return dict(sorted(counts.items()))


def lookup_references(
    input: Any,
    sources: Any = None,
    cache_dir: Optional[str] = None,
    max_workers: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Batch identifier lookup: one row per line of a DOI/URL/PMID/arXiv/ISBN list.

    Thin wrapper over :func:`audit_references` so caching, retries, rate
    limits and source selection behave identically, but returns compact
    lookup rows (query, identifier, status, matched metadata) instead of
    full audit results.
    """
    results = audit_references(
        input, sources=sources, cache_dir=cache_dir, max_workers=max_workers
    )
    rows: list[dict[str, Any]] = []
    for result in results:
        ref = result.input
        identifier = None
        for attr in ("doi", "url", "pmid", "arxiv_id", "isbn"):
            value = getattr(ref, attr, None)
            if value:
                identifier = str(value)
                break
        record = result.record
        rows.append(
            {
                "index": result.index,
                "query": (ref.raw or "").strip(),
                "identifier": identifier,
                "status": result.status,
                "source": record.source if record else None,
                "title": record.title if record else None,
                "year": record.year if record else None,
                "journal": record.journal if record else None,
                "doi": record.doi if record else None,
            }
        )
    return rows


def write_cross_check_report(
    results: list[AuditResult],
    entries: list[ParsedReference],
    in_text_citations: list[dict[str, Any]],
    out_dir: str,
    fmt: str = "md",
    meta: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Write a cross-check report comparing in-text citations to reference list.

    ``entries`` are the parsed reference list entries.
    ``in_text_citations`` are extracted from the manuscript (e.g., via ``extract_docx``).
    ``fmt`` can be 'md' or 'html'.
    """
    if _reports is not None:
        directory = Path(out_dir)
        directory.mkdir(parents=True, exist_ok=True)
        extension = "html" if fmt.lower() == "html" else "md"
        out_path = directory / f"cross_check.{extension}"
        try:
            if fmt.lower() == "html":
                _reports.render_cross_check_report_html(results, entries, in_text_citations, str(out_path), meta or {})
            else:
                _reports.render_cross_check_report(results, entries, in_text_citations, str(out_path), meta or {})
            return str(out_path)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("cross-check report rendering failed: %s", exc)
    return None


__all__ = [
    "TRANSPORT",
    "audit_references",
    "diff_runs",
    "evaluate_policy",
    "load_policy",
    "lookup_references",
    "parse_references",
    "summarize",
    "validate_policy",
    "verify_ledger",
    "write_report",
    "write_cross_check_report",
]
