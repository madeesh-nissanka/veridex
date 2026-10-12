# VERIDEX v0.3.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Offline tests for resumable audits and memory-bounded batched runs.

No network access: a counting fake transport returns empty Crossref-shaped
responses. Tests prove checkpoint/resume skipping and that batched runs do
not duplicate ledger evidence. Stdlib only.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from veridex import api
from veridex.cli import EXIT_OK, main
from veridex.httpclient import Response
from veridex.ledger import read_records


@pytest.fixture
def counting_transport(monkeypatch):
    calls: list[str] = []

    def fake(url: str, timeout: float | None = None) -> Response:
        calls.append(url)
        return Response(url=url, status=200, body=b'{"message": {"items": []}}', from_cache=False)

    monkeypatch.setattr(api, "TRANSPORT", fake)
    return calls


def _write_refs(dirpath: str, count: int) -> str:
    path = Path(dirpath, "refs.txt")
    lines = [
        f"[{i}] Author, A. (20{10 + i % 10}). Study of beam deflection, {i}. "
        f"Journal of Structural Examples, 12({i}), 1-9."
        for i in range(1, count + 1)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class TestBatchedLedger:
    def test_checkpoints_written_and_chain_verifies(self, counting_transport):
        with tempfile.TemporaryDirectory() as tmp:
            refs = _write_refs(tmp, 5)
            ledger = str(Path(tmp, "ledger.jsonl"))
            results = api.audit_references(
                refs, sources=["crossref"], ledger_path=ledger,
                batch_size=2, cache_dir=None,
            )
            assert len(results) == 5
            assert [r.index for r in results] == sorted(r.index for r in results)
            report = api.verify_ledger(ledger)
            assert report["ok"] is True
            entries = read_records(ledger)
            checkpoints = [e for e in entries if e.get("evidence_type") == "checkpoint"]
            lookups = [e for e in entries if e.get("evidence_type") == "lookup"]
            assert len(checkpoints) == 5
            assert len(lookups) == len(counting_transport)

    def test_batched_run_writes_evidence_once(self, counting_transport):
        with tempfile.TemporaryDirectory() as tmp:
            refs = _write_refs(tmp, 6)
            ledger = str(Path(tmp, "ledger.jsonl"))
            api.audit_references(
                refs, sources=["crossref"], ledger_path=ledger,
                batch_size=2, cache_dir=None,
            )
            calls_first = len(counting_transport)
            entries = read_records(ledger)
            lookups = [e for e in entries if e.get("evidence_type") == "lookup"]
            assert len(lookups) == calls_first
            assert calls_first > 0


class TestResume:
    def test_resume_skips_checkpointed_entries(self, counting_transport):
        with tempfile.TemporaryDirectory() as tmp:
            refs = _write_refs(tmp, 5)
            ledger = str(Path(tmp, "ledger.jsonl"))
            first = api.audit_references(
                refs, sources=["crossref"], ledger_path=ledger,
                batch_size=2, cache_dir=None,
            )
            calls_after_first = len(counting_transport)
            assert calls_after_first > 0

            second = api.audit_references(
                refs, sources=["crossref"], ledger_path=ledger,
                batch_size=2, cache_dir=None, resume_from="auto",
            )
            assert len(counting_transport) == calls_after_first
            assert len(second) == len(first)
            assert [(r.index, r.status) for r in second] == [
                (r.index, r.status) for r in first
            ]

    def test_resume_on_small_run_also_skips(self, counting_transport):
        with tempfile.TemporaryDirectory() as tmp:
            refs = _write_refs(tmp, 3)
            ledger = str(Path(tmp, "ledger.jsonl"))
            api.audit_references(
                refs, sources=["crossref"], ledger_path=ledger, cache_dir=None,
            )
            calls_after_first = len(counting_transport)
            assert calls_after_first > 0
            second = api.audit_references(
                refs, sources=["crossref"], ledger_path=ledger,
                cache_dir=None, resume_from="auto",
            )
            assert len(second) == 3
            assert len(counting_transport) == calls_after_first

    def test_resume_without_ledger_performs_full_audit(self, counting_transport):
        with tempfile.TemporaryDirectory() as tmp:
            refs = _write_refs(tmp, 3)
            results = api.audit_references(
                refs, sources=["crossref"], cache_dir=None, resume_from="auto",
            )
            assert len(results) == 3
            assert len(counting_transport) > 0

    def test_resume_from_unknown_run_id_audits_all(self, counting_transport):
        with tempfile.TemporaryDirectory() as tmp:
            refs = _write_refs(tmp, 4)
            ledger = str(Path(tmp, "ledger.jsonl"))
            api.audit_references(
                refs, sources=["crossref"], ledger_path=ledger,
                batch_size=2, cache_dir=None,
            )
            calls_after_first = len(counting_transport)
            second = api.audit_references(
                refs, sources=["crossref"], ledger_path=ledger,
                batch_size=2, cache_dir=None, resume_from="run-000000000000",
            )
            assert len(second) == 4
            assert len(counting_transport) > calls_after_first


class TestCliResume:
    def test_cli_resume_flag_reuses_ledger(self, counting_transport):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = str(Path(tmp, "ledger.jsonl"))
            code = main([
                "--json", "--quiet", "--no-cache", "audit",
                "examples/refs.bib", "--ledger", ledger,
            ])
            assert code == EXIT_OK
            calls_after_first = len(counting_transport)
            assert calls_after_first > 0

            code = main([
                "--json", "--quiet", "--no-cache", "audit",
                "examples/refs.bib", "--ledger", ledger, "--resume",
            ])
            assert code == EXIT_OK
            assert len(counting_transport) == calls_after_first

    def test_cli_resume_flag_accepts_v01_style(self, counting_transport):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = str(Path(tmp, "ledger.jsonl"))
            first = main([
                "examples/refs.bib", "--ledger", ledger, "--json", "--quiet",
            ])
            assert first == EXIT_OK
            calls_after_first = len(counting_transport)
            second = main([
                "examples/refs.bib", "--ledger", ledger, "--resume",
                "--json", "--quiet",
            ])
            assert second == EXIT_OK
            assert len(counting_transport) == calls_after_first

    def test_cli_resume_and_batch_flags_parse(self, counting_transport):
        code = main(["--json", "--quiet", "--no-cache", "audit",
                     "examples/refs.bib", "--resume"])
        assert code == EXIT_OK
