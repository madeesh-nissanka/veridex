# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Command line interface for VERIDEX.

Exit codes: ``0`` clean, ``1`` policy violation, ``2`` usage error,
``3`` internal error, ``4`` ledger tamper. Progress is written to stderr and
machine-readable output to stdout (``--json``). The v0.1 invocation
``veridex refs.txt --out audit --format text`` (no subcommand) still works.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

from veridex import api
from veridex.config import load_user_config, merge_config
from veridex.models import LEGACY_STATUS_MAP, TOOL_NAME, TOOL_VERSION
from veridex.policy import load_policy, validate_policy
from veridex.resolvers import source_names

EXIT_OK = 0
EXIT_POLICY = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3
EXIT_TAMPER = 4

COMMANDS = (
    "parse",
    "resolve",
    "lookup",
    "audit",
    "repair",
    "report",
    "dashboard",
    "verify-ledger",
    "diff",
    "policy",
    "cross-check",
    "about",
)

_BOOL_FLAGS = {
    "--json": "json",
    "--quiet": "quiet",
    "-q": "quiet",
    "--verbose": "verbose",
    "-v": "verbose",
    "--no-cache": "no_cache",
    "--legacy-status": "legacy_status",
    "--semantic": "semantic",
    "--resume": "resume",
    "--help": "help",
    "-h": "help",
}

_VALUE_FLAGS = {
    "--policy": "policy",
    "--sources": "sources",
    "--cache-dir": "cache_dir",
    "--workers": "workers",
    "--out": "out",
    "--ledger": "ledger",
    "--format": "format",
    "--manuscript": "manuscript",
    "--retraction-file": "retraction_file",
}

_LEGACY_OUT = {value: key for key, value in LEGACY_STATUS_MAP.items()}


@dataclass
class _Context:
    json: bool = False
    quiet: bool = False
    verbose: bool = False
    no_cache: bool = False
    legacy_status: bool = False
    help: bool = False
    version: bool = False
    policy: Optional[str] = None
    sources: list[str] = field(default_factory=list)
    cache_dir: Optional[str] = None
    workers: Optional[int] = None
    out: Optional[str] = None
    ledger: Optional[str] = None
    fmt: Optional[str] = None
    manuscript: Optional[str] = None
    retraction_file: Optional[str] = None
    semantic: bool = False
    resume: bool = False
    command: Optional[str] = None
    positionals: list[str] = field(default_factory=list)


def _progress(ctx: _Context, message: str) -> None:
    if not ctx.quiet:
        print(message, file=sys.stderr)


def _emit_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _display_status(ctx: _Context, status: str) -> str:
    if ctx.legacy_status:
        return _LEGACY_OUT.get(status, status)
    return status


def _partition_sources(values: list[str]) -> Any:
    entries: list[str] = []
    for value in values:
        for piece in str(value).split(","):
            piece = piece.strip()
            if piece:
                entries.append(piece)
    return entries or None


def _parse_args(argv: list[str]) -> _Context:
    ctx = _Context()
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--version":
            ctx.version = True
            index += 1
            continue
        if token == "--about":
            ctx.positionals.append("about")
            index += 1
            continue
        if token.startswith("--no-") and token[5:] in source_names():
            ctx.sources.append(token[2:])
            index += 1
            continue
        if "=" in token and token.startswith("--"):
            name, _, value = token.partition("=")
            if name in _VALUE_FLAGS:
                _assign_value(ctx, _VALUE_FLAGS[name], value)
                index += 1
                continue
        if token in _BOOL_FLAGS:
            setattr(ctx, _BOOL_FLAGS[token], True)
            index += 1
            continue
        if token in _VALUE_FLAGS:
            if index + 1 >= len(argv):
                raise ValueError(f"missing value for {token}")
            _assign_value(ctx, _VALUE_FLAGS[token], argv[index + 1])
            index += 2
            continue
        if token.startswith("-") and token != "-":
            raise ValueError(f"unknown option: {token}")
        ctx.positionals.append(token)
        index += 1
    return ctx


def _assign_value(ctx: _Context, attr: str, value: str) -> None:
    if attr == "workers":
        try:
            ctx.workers = int(value)
        except ValueError as exc:
            raise ValueError(f"--workers expects an integer, got {value!r}") from exc
    elif attr == "sources":
        ctx.sources.append(value)
    elif attr == "format":
        ctx.fmt = value
    else:
        setattr(ctx, attr, value)


_REF_EXTS = {".bib", ".ris", ".json", ".xml", ".enw", ".txt", ".md", ".docx", ".doc"}


def _looks_like_input(token: str) -> bool:
    """A bare positional is a v0.1-style audit target only if it looks like a
    reference file (exists, or carries a known extension)."""
    if os.path.exists(token):
        return True
    return os.path.splitext(token)[1].lower() in _REF_EXTS


def _resolve_command(ctx: _Context) -> None:
    if ctx.positionals and ctx.positionals[0] in COMMANDS:
        ctx.command = ctx.positionals[0]
        ctx.positionals = ctx.positionals[1:]
    elif ctx.positionals and _looks_like_input(ctx.positionals[0]):
        ctx.command = "audit"
    else:
        ctx.command = None


def _sources_for(ctx: _Context) -> Any:
    return _partition_sources(ctx.sources)


def _fail(message: str, code: int = EXIT_USAGE) -> int:
    print(message, file=sys.stderr)
    return code


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def _cmd_about(ctx: _Context) -> int:
    if ctx.json:
        _emit_json(
            {
                "name": TOOL_NAME,
                "version": TOOL_VERSION,
                "license": "MIT",
                "copyright": "Madeesh P. Nissanka",
            }
        )
    else:
        print(f"{TOOL_NAME} {TOOL_VERSION}")
        print("License: MIT")
        print("Copyright (c) 2026 Madeesh P. Nissanka")
    return EXIT_OK


def _cmd_parse(ctx: _Context) -> int:
    if not ctx.positionals:
        return _fail("parse requires a reference file")
    refs = api.parse_references(ctx.positionals[0], fmt=ctx.fmt or "auto")
    _progress(ctx, f"parsed {len(refs)} references")
    if ctx.json:
        _emit_json(
            {
                "count": len(refs),
                "references": [r.to_dict() for r in refs],
            }
        )
    else:
        for ref in refs:
            print(f"[{ref.index}] {ref.title or ref.raw[:70]}")
        print(f"{len(refs)} references")
    return EXIT_OK


def _cmd_resolve(ctx: _Context) -> int:
    return _run_audit(ctx)


def _cmd_lookup(ctx: _Context) -> int:
    if not ctx.positionals:
        return _fail("lookup requires an identifier file")
    if not os.path.exists(ctx.positionals[0]):
        return _fail(f"lookup: file not found: {ctx.positionals[0]}")
    _progress(ctx, f"looking up {ctx.positionals[0]}")
    rows = api.lookup_references(
        ctx.positionals[0],
        sources=_sources_for(ctx),
        cache_dir=ctx.cache_dir,
        max_workers=ctx.workers,
    )
    if ctx.json:
        _emit_json({"count": len(rows), "lookups": rows})
    else:
        for row in rows:
            print(f"[{row['index']}] {row['query'][:60]}")
            if row["title"]:
                print(
                    f"     {row['source']} -> {row['status']}: "
                    f"{row['title']} ({row['year']}) {row['journal']} doi:{row['doi']}"
                )
            else:
                print(f"     -> {row['status']}: no matching record")
    return EXIT_OK


def _cmd_audit(ctx: _Context) -> int:
    return _run_audit(ctx)


def _run_audit(ctx: _Context) -> int:
    if not ctx.positionals:
        return _fail("audit requires a reference file")

    policy_mapping: Optional[dict[str, Any]] = None
    if ctx.policy:
        policy_mapping = load_policy(ctx.policy)
        problems = validate_policy(policy_mapping)
        if problems:
            for problem in problems:
                print(f"policy error: {problem}", file=sys.stderr)
            return EXIT_USAGE

    ledger_path = ctx.ledger
    if ledger_path is None and ctx.out:
        ledger_path = os.path.join(ctx.out, "ledger.jsonl")

    if ledger_path and os.path.exists(ledger_path):
        before = api.verify_ledger(ledger_path)
        if not before.get("ok", True):
            _report_tamper(ctx, before)
            return EXIT_TAMPER

    _progress(ctx, f"auditing {ctx.positionals[0]}")
    results = api.audit_references(
        ctx.positionals[0],
        out_dir=None,
        sources=_sources_for(ctx),
        policy=policy_mapping,
        ledger_path=ledger_path,
        manuscript=ctx.manuscript,
        cache_dir=ctx.cache_dir,
        max_workers=ctx.workers,
        retraction_file=ctx.retraction_file,
        semantic=ctx.semantic,
        resume_from="auto" if ctx.resume else None,
    )

    if ledger_path:
        after = api.verify_ledger(ledger_path)
        if not after.get("ok", True):
            _report_tamper(ctx, after)
            return EXIT_TAMPER

    if ctx.out:
        fmt = ctx.fmt or "md"
        written = api.write_report(
            results, ctx.out, fmt=fmt,
            meta={"tool": TOOL_NAME, "version": TOOL_VERSION},
        )
        _progress(ctx, f"wrote {written}")

    violations: list[dict[str, Any]] = []
    if policy_mapping is not None:
        violations = api.evaluate_policy(results, policy_mapping)

    _emit_audit(ctx, results, violations)

    if violations:
        return EXIT_POLICY
    return EXIT_OK


def _emit_audit(ctx: _Context, results: list[Any], violations: list[dict[str, Any]]) -> None:
    summary = api.summarize(results)
    if ctx.json:
        _emit_json(
            {
                "tool": TOOL_NAME,
                "version": TOOL_VERSION,
                "summary": summary,
                "violations": violations,
                "results": [
                    _result_payload(ctx, result) for result in results
                ],
            }
        )
        return

    for result in results:
        title = ""
        if result.input is not None:
            title = result.input.title or (result.input.raw or "")[:70]
        print(f"[{result.index}] {_display_status(ctx, result.status)} {title}")
    counts = ", ".join(f"{status} {count}" for status, count in summary.items())
    print(f"{len(results)} references: {counts or 'none'}")
    for violation in violations:
        print(f"policy: {violation['code']}: {violation['message']}")


def _result_payload(ctx: _Context, result: Any) -> dict[str, Any]:
    payload = result.to_dict()
    if ctx.legacy_status:
        payload["status"] = _display_status(ctx, result.status)
    return payload


def _report_tamper(ctx: _Context, report: dict[str, Any]) -> None:
    if ctx.json:
        _emit_json({"ok": False, "problems": report.get("problems", [])})
    else:
        print("ledger tamper detected", file=sys.stderr)
        for problem in report.get("problems", []):
            print(f"  line {problem.get('line')}: {problem.get('reason')}", file=sys.stderr)


def _cmd_verify_ledger(ctx: _Context) -> int:
    path = ctx.positionals[0] if ctx.positionals else ctx.ledger
    if not path:
        return _fail("verify-ledger requires a ledger path")
    report = api.verify_ledger(path)
    if ctx.json:
        _emit_json(report)
    elif report.get("ok"):
        print("ledger OK")
    else:
        print("ledger FAILED", file=sys.stderr)
        for problem in report.get("problems", []):
            print(f"  line {problem.get('line')}: {problem.get('reason')}", file=sys.stderr)
    return EXIT_OK if report.get("ok") else EXIT_TAMPER


def _cmd_diff(ctx: _Context) -> int:
    positionals = ctx.positionals
    if len(positionals) == 3:
        ledger_path, run_a, run_b = positionals
    elif len(positionals) == 2 and ctx.ledger:
        ledger_path = ctx.ledger
        run_a, run_b = positionals
    else:
        return _fail("diff requires LEDGER RUN_A RUN_B (or --ledger with RUN_A RUN_B)")
    rows = api.diff_runs(ledger_path, run_a, run_b)
    if ctx.json:
        _emit_json({"changes": rows})
    else:
        changed = [row for row in rows if row["change"] != "UNCHANGED"]
        for row in changed:
            print(f"{row['change']}: {row['key']} ({row['old_status']} -> {row['new_status']})")
        print(f"{len(changed)} changed of {len(rows)} entries")
    return EXIT_OK


def _cmd_policy(ctx: _Context) -> int:
    path = ctx.policy or (ctx.positionals[0] if ctx.positionals else None)
    if not path:
        return _fail("policy requires a policy path")
    try:
        mapping = load_policy(path)
    except (ValueError, TypeError) as exc:
        return _fail(f"cannot load policy: {exc}")
    problems = validate_policy(mapping)
    if ctx.json:
        _emit_json({"ok": not problems, "policy": mapping, "errors": problems})
    else:
        if problems:
            for problem in problems:
                print(f"policy error: {problem}", file=sys.stderr)
        else:
            print("policy OK")
    return EXIT_OK if not problems else EXIT_USAGE


def _cmd_repair(ctx: _Context) -> int:
    repair = getattr(api, "_repair", None)
    if repair is None:
        return _fail("repair support is not available in this build", EXIT_INTERNAL)
    if not ctx.positionals:
        return _fail("repair requires a reference file")
    results = api.audit_references(
        ctx.positionals[0],
        sources=_sources_for(ctx),
        cache_dir=ctx.cache_dir,
        max_workers=ctx.workers,
        retraction_file=ctx.retraction_file,
        semantic=ctx.semantic,
    )
    repairs = [{"index": r.index, "changes": r.repairs} for r in results]
    written_paths: dict[str, str] = {}
    if ctx.out:
        written_paths = repair.write_repairs(results, ctx.out)
    existing = sorted(p for p in written_paths.values() if os.path.exists(p))
    if ctx.json:
        payload: dict[str, Any] = {"repairs": repairs}
        if ctx.out:
            payload["written"] = existing
        _emit_json(payload)
    else:
        for entry in repairs:
            print(f"[{entry['index']}] {len(entry['changes'])} suggested change(s)")
        if ctx.out:
            for path in existing:
                _progress(ctx, f"wrote {path}")
            if not existing:
                _progress(ctx, "no resolved records: repaired files not written")
    return EXIT_OK


def _cmd_report(ctx: _Context) -> int:
    if not ctx.positionals:
        return _fail("report requires a reference file")
    if not ctx.out:
        return _fail("report requires --out DIR")
    results = api.audit_references(
        ctx.positionals[0],
        sources=_sources_for(ctx),
        cache_dir=ctx.cache_dir,
        max_workers=ctx.workers,
        retraction_file=ctx.retraction_file,
        semantic=ctx.semantic,
    )
    fmt = ctx.fmt or "md"
    written = api.write_report(
        results, ctx.out, fmt=fmt,
        meta={"tool": TOOL_NAME, "version": TOOL_VERSION},
    )
    if ctx.json:
        _emit_json({"report": written, "count": len(results)})
    else:
        print(f"wrote {written}")
    return EXIT_OK


def _cmd_dashboard(ctx: _Context) -> int:
    if not ctx.positionals:
        return _fail("dashboard requires a reference file")
    if not ctx.out:
        return _fail("dashboard requires --out DIR")
    results = api.audit_references(
        ctx.positionals[0],
        sources=_sources_for(ctx),
        cache_dir=ctx.cache_dir,
        max_workers=ctx.workers,
        retraction_file=ctx.retraction_file,
        semantic=ctx.semantic,
    )
    from veridex.reports import render_dashboard
    from pathlib import Path
    out_dir = Path(ctx.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "dashboard.html"
    refs = api.parse_references(ctx.positionals[0])
    render_dashboard(results, refs, out_path, meta={"tool": TOOL_NAME, "version": TOOL_VERSION})
    if ctx.json:
        _emit_json({"dashboard": str(out_path), "count": len(results)})
    else:
        _progress(ctx, f"wrote {out_path}")
    return EXIT_OK


def _cmd_cross_check(ctx: _Context) -> int:
    if not ctx.positionals:
        return _fail("cross-check requires a reference file")
    if not ctx.manuscript:
        return _fail("cross-check requires --manuscript PATH (DOCX file)")
    if not ctx.out:
        return _fail("cross-check requires --out DIR")

    results = api.audit_references(
        ctx.positionals[0],
        sources=_sources_for(ctx),
        cache_dir=ctx.cache_dir,
        max_workers=ctx.workers,
        retraction_file=ctx.retraction_file,
        semantic=ctx.semantic,
    )

    refs = api.parse_references(ctx.positionals[0])

    # Extract in-text citations from manuscript
    try:
        from veridex.parsing.docx import extract_docx
        extracted = extract_docx(ctx.manuscript)
        in_text_citations = extracted.get("in_text_citations", []) if isinstance(extracted, dict) else []
    except Exception as exc:
        return _fail(f"failed to extract citations from manuscript: {exc}")

    fmt = ctx.fmt or "md"
    written = api.write_cross_check_report(
        results, refs, in_text_citations, ctx.out, fmt=fmt,
        meta={"tool": TOOL_NAME, "version": TOOL_VERSION},
    )
    if written:
        if ctx.json:
            _emit_json({"cross_check": written, "count": len(results)})
        else:
            _progress(ctx, f"wrote {written}")
    else:
        return _fail("cross-check report generation failed", EXIT_INTERNAL)
    return EXIT_OK


_USAGE = (
    "usage: veridex [--json] [--quiet] [--verbose] [--policy PATH] "
    "[--sources a,b|no-x] [--cache-dir DIR] [--no-cache] [--workers N] "
    "[--out DIR] [--ledger PATH] [--format FMT] [--manuscript PATH] "
    "[--retraction-file PATH] [--semantic] [--resume]\n"
    "                <parse|resolve|lookup|audit|repair|report|dashboard|verify-ledger|diff|policy|cross-check|about> "
    "[args...]\n"
    "       veridex FILE [--out DIR] [--format FMT]   (v0.1 compatible audit)"
)


def main(argv: Optional[list[str]] = None) -> int:
    """Run the CLI. Returns a process exit code."""
    if argv is None:
        argv = sys.argv[1:]

    logging.basicConfig(level=logging.WARNING, format="veridex: %(message)s")

    try:
        ctx = _parse_args(list(argv))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return EXIT_USAGE

    if ctx.version:
        print(f"{TOOL_NAME} {TOOL_VERSION}")
        print("License: MIT")
        print("Copyright (c) 2026 Madeesh P. Nissanka")
        return EXIT_OK

    if ctx.help:
        print(_USAGE)
        return EXIT_OK

    _resolve_command(ctx)

    # Load user config file (CLI args take precedence)
    user_config = load_user_config()
    if user_config:
        bool_flag_attrs = set(_BOOL_FLAGS.values())
        value_flag_attrs = set(_VALUE_FLAGS.values())
        merge_config(ctx, user_config, bool_flag_attrs, value_flag_attrs)

    if ctx.command is None:
        print(_USAGE, file=sys.stderr)
        return EXIT_USAGE

    handler = {
        "about": _cmd_about,
        "parse": _cmd_parse,
        "resolve": _cmd_resolve,
        "lookup": _cmd_lookup,
        "audit": _cmd_audit,
        "repair": _cmd_repair,
        "report": _cmd_report,
        "dashboard": _cmd_dashboard,
        "verify-ledger": _cmd_verify_ledger,
        "diff": _cmd_diff,
        "policy": _cmd_policy,
        "cross-check": _cmd_cross_check,
    }[ctx.command]

    try:
        return handler(ctx)
    except FileNotFoundError as exc:
        return _fail(f"error: {exc}", EXIT_USAGE)
    except ValueError as exc:
        return _fail(f"error: {exc}", EXIT_USAGE)
    except Exception as exc:  # pragma: no cover - defensive
        if ctx.verbose:
            import traceback

            traceback.print_exc()
        return _fail(f"internal error: {exc}", EXIT_INTERNAL)


__all__ = ["main", "EXIT_OK", "EXIT_POLICY", "EXIT_USAGE", "EXIT_INTERNAL", "EXIT_TAMPER"]
