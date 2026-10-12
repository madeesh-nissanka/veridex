# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for CLI commands and exit codes. Stdlib only."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from veridex import api
from veridex.cli import EXIT_INTERNAL, EXIT_OK, EXIT_POLICY, EXIT_TAMPER, EXIT_USAGE, main
from veridex.httpclient import HttpClient, Response
from veridex.resolvers import SourceOpts, build, source_names


@pytest.fixture(autouse=True)
def _offline_transport(monkeypatch):
    """Keep every CLI test offline: inject a deterministic empty-response
    transport so no network request is ever made (unit tests must not use the
    network). Adapters that get no usable records report NOT_FOUND."""
    def fake(url: str, timeout: float | None = None) -> Response:
        return Response(url=url, status=200, body=b'{"message": {"items": []}}', from_cache=False)

    monkeypatch.setattr(api, "TRANSPORT", fake)
    yield


def _run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run CLI via main() and return (exit_code, stdout, stderr)."""
    import sys
    from io import StringIO

    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = StringIO()
    sys.stderr = StringIO()
    try:
        code = main(args)
        return code, sys.stdout.getvalue(), sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr


def _run_subprocess(args: list[str]) -> tuple[int, str, str]:
    """Run CLI as subprocess."""
    result = subprocess.run(
        ["python3", "-m", "veridex"] + args,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    return result.returncode, result.stdout, result.stderr


class TestCliAbout:
    def test_about(self):
        code, out, err = _run_cli(["about"])
        assert code == EXIT_OK
        assert "veridex 0.3.0" in out
        assert "MIT" in out
        assert "Madeesh P. Nissanka" in out

    def test_about_json(self):
        code, out, err = _run_cli(["about", "--json"])
        assert code == EXIT_OK
        data = json.loads(out)
        assert data["name"] == "veridex"
        assert data["version"] == "0.3.0"
        assert data["license"] == "MIT"
        assert data["copyright"] == "Madeesh P. Nissanka"

    def test_version_flag(self):
        code, out, err = _run_cli(["--version"])
        assert code == EXIT_OK
        assert "veridex 0.3.0" in out

    def test_version_flag_includes_license(self):
        code, out, err = _run_cli(["--version"])
        assert code == EXIT_OK
        assert "License: MIT" in out
        assert "Madeesh P. Nissanka" in out

    def test_about_flag_alias(self):
        code, out, err = _run_cli(["--about"])
        assert code == EXIT_OK
        assert "veridex 0.3.0" in out
        assert "License: MIT" in out
        assert "Madeesh P. Nissanka" in out


class TestCliParse:
    def test_parse_bibtex(self):
        code, out, err = _run_cli(["parse", "examples/refs.bib"])
        assert code == EXIT_OK
        assert "2 references" in out
        assert "Soil consolidation settlement" in out

    def test_parse_json(self):
        code, out, err = _run_cli(["parse", "examples/refs.bib", "--json"])
        assert code == EXIT_OK
        data = json.loads(out)
        assert data["count"] == 2
        assert len(data["references"]) == 2

    def test_parse_missing_file(self):
        # parse treats non-existent paths as literal text (by design)
        code, out, err = _run_cli(["parse", "nonexistent.bib"])
        assert code == EXIT_OK
        assert "1 references" in out


class TestCliAudit:
    def test_audit_bibtex_offline(self):
        """Audit with injected fake transport (no network)."""
        code, out, err = _run_cli(["audit", "examples/refs.bib", "--no-cache"])
        assert code == EXIT_OK
        assert "2 references" in out

    def test_audit_json_output(self):
        code, out, err = _run_cli(["audit", "examples/refs.bib", "--json", "--no-cache"])
        assert code == EXIT_OK
        data = json.loads(out)
        assert data["tool"] == "veridex"
        assert data["version"] == "0.3.0"
        assert "summary" in data
        assert "results" in data
        assert len(data["results"]) == 2

    def test_audit_with_policy(self):
        code, out, err = _run_cli(
            ["audit", "examples/refs.bib", "--policy", "examples/policy.yaml", "--no-cache"]
        )
        assert code in (EXIT_OK, EXIT_POLICY)  # depends on fixtures


class TestCliVerifyLedger:
    def test_verify_ledger_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            path = f.name
        try:
            code, out, err = _run_cli(["verify-ledger", path])
            assert code == EXIT_OK
            assert "ledger OK" in out or "ledger ok" in out.lower()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_verify_ledger_json(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            path = f.name
        try:
            code, out, err = _run_cli(["verify-ledger", path, "--json"])
            assert code == EXIT_OK
            data = json.loads(out)
            assert data["ok"] is True
            assert data["problems"] == []
        finally:
            Path(path).unlink(missing_ok=True)

    def test_verify_ledger_tampered(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            # Write a tampered line (wrong prev_hash)
            f.write('{"seq": 1, "timestamp": "2024-01-01T00:00:00Z", "prev_hash": "0" * 64, "data": {}, "entry_hash": "invalid"}\n')
            path = f.name
        try:
            code, out, err = _run_cli(["verify-ledger", path])
            assert code == EXIT_TAMPER
            assert "FAILED" in out or "malformed" in err.lower()
        finally:
            Path(path).unlink(missing_ok=True)


class TestCliDiff:
    def test_diff_missing_args(self):
        code, out, err = _run_cli(["diff"])
        assert code == EXIT_USAGE

    def test_diff_invalid_ledger(self):
        # diff on missing ledger returns 0 changes (not an error)
        code, out, err = _run_cli(["diff", "nonexistent.jsonl", "run1", "run2"])
        assert code == EXIT_OK
        assert "0 changed" in out


class TestCliPolicy:
    def test_policy_valid(self):
        code, out, err = _run_cli(["policy", "examples/policy.yaml"])
        assert code == EXIT_OK
        assert "policy OK" in out or "policy ok" in out.lower()

    def test_policy_json(self):
        code, out, err = _run_cli(["policy", "examples/policy.yaml", "--json"])
        assert code == EXIT_OK
        data = json.loads(out)
        assert data["ok"] is True
        assert "policy" in data

    def test_policy_invalid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("unknown_key: value\n")
            path = f.name
        try:
            code, out, err = _run_cli(["policy", path, "--json"])
            assert code == EXIT_USAGE
            data = json.loads(out)
            assert data["ok"] is False
            assert len(data["errors"]) > 0
        finally:
            Path(path).unlink(missing_ok=True)


class TestCliRepair:
    def test_repair_no_positionals(self):
        code, out, err = _run_cli(["repair"])
        assert code == EXIT_USAGE

    def test_repair_with_file(self):
        code, out, err = _run_cli(["repair", "examples/refs.bib", "--no-cache"])
        assert code == EXIT_OK
        assert "suggested change" in out.lower() or "0 suggested" in out.lower()

    def test_repair_out_without_records(self, monkeypatch):
        def fake(url: str, timeout: float | None = None) -> Response:
            return Response(url=url, status=200, body=b"{}", from_cache=False)

        monkeypatch.setattr(api, "TRANSPORT", fake)
        with tempfile.TemporaryDirectory() as tmpdir:
            code, out, err = _run_cli(
                ["repair", "examples/refs.bib", "--out", tmpdir, "--no-cache"]
            )
            assert code == EXIT_OK
            assert "not written" in err
            assert not list(Path(tmpdir).glob("repaired.*"))

    def test_repair_out_writes_repaired_files(self, monkeypatch):
        hit = json.dumps(
            {
                "status": "ok",
                "message": {
                    "DOI": "10.1000/example.2018.001",
                    "title": [
                        "Soil consolidation settlement under staged embankment loading"
                    ],
                    "author": [{"family": "Smith", "given": "A."}],
                    "issued": {"date-parts": [[2018]]},
                    "container-title": ["Geotechnical Journal"],
                    "volume": "77",
                    "page": "101-118",
                },
            }
        ).encode()

        def fake(url: str, timeout: float | None = None) -> Response:
            if url.startswith("https://api.crossref.org/works/10."):
                return Response(url=url, status=200, body=hit, from_cache=False)
            return Response(
                url=url, status=200, body=b'{"message": {"items": []}}', from_cache=False
            )

        monkeypatch.setattr(api, "TRANSPORT", fake)
        with tempfile.TemporaryDirectory() as tmpdir:
            code, out, err = _run_cli(
                ["repair", "examples/refs.bib", "--out", tmpdir, "--no-cache"]
            )
            assert code == EXIT_OK
            bib = Path(tmpdir) / "repaired.bib"
            ris = Path(tmpdir) / "repaired.ris"
            csl = Path(tmpdir) / "repaired.csl.json"
            assert bib.exists() and bib.stat().st_size > 0
            assert "Smith" in bib.read_text()
            assert ris.exists() and ris.stat().st_size > 0
            assert csl.exists() and csl.stat().st_size > 0
            assert "wrote" in err

    def test_repair_json_payload_has_written_paths(self, monkeypatch):
        def fake(url: str, timeout: float | None = None) -> Response:
            if url.startswith("https://api.crossref.org/works/10."):
                hit = json.loads(
                    json.dumps(
                        {
                            "status": "ok",
                            "message": {
                                "DOI": "10.1000/example.2018.001",
                                "title": ["Soil consolidation"],
                                "author": [{"family": "Smith", "given": "A."}],
                                "issued": {"date-parts": [[2018]]},
                                "container-title": ["Geotechnical Journal"],
                            },
                        }
                    )
                )
                return Response(url=url, status=200, body=json.dumps(hit).encode(), from_cache=False)
            return Response(
                url=url, status=200, body=b'{"message": {"items": []}}', from_cache=False
            )

        monkeypatch.setattr(api, "TRANSPORT", fake)
        with tempfile.TemporaryDirectory() as tmpdir:
            code, out, err = _run_cli(
                ["--json", "repair", "examples/refs.bib", "--out", tmpdir, "--no-cache"]
            )
            assert code == EXIT_OK
            data = json.loads(out)
            assert "repairs" in data
            assert any(p.endswith("repaired.bib") for p in data["written"])


class TestCliReport:
    def test_report_missing_out(self):
        code, out, err = _run_cli(["report", "examples/refs.bib"])
        assert code == EXIT_USAGE

    def test_report_creates_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            code, out, err = _run_cli(["report", "examples/refs.bib", "--out", tmpdir, "--no-cache"])
            assert code == EXIT_OK
            # Check that some report file was created
            files = list(Path(tmpdir).glob("report.*"))
            assert len(files) > 0


class TestCliLegacyCompat:
    def test_v01_compat_audit_runs(self):
        """Test v0.1 compatible invocation runs without error (outputs report.json fallback)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code, out, err = _run_cli(
                ["examples/refs.txt", "--out", tmpdir, "--format", "text", "--no-cache"]
            )
            assert code == EXIT_OK
            # Current behavior: falls back to report.json since text format not in reports module
            assert Path(tmpdir, "report.json").exists()

    def test_v01_compat_ledger_created(self):
        """Legacy audit should still create ledger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code, out, err = _run_cli(
                ["examples/refs.txt", "--out", tmpdir, "--format", "text", "--no-cache"]
            )
            assert code == EXIT_OK
            ledger = Path(tmpdir, "ledger.jsonl")
            assert ledger.exists()
            # Verify ledger is valid
            report = api.verify_ledger(str(ledger))
            assert report["ok"] is True


class TestCliSourcesFlag:
    def test_sources_enable(self):
        code, out, err = _run_cli(["audit", "examples/refs.bib", "--sources", "crossref", "--no-cache", "--json"])
        assert code == EXIT_OK
        data = json.loads(out)
        # Should only use crossref
        for r in data["results"]:
            # All evidence should be from crossref
            for ev in r.get("evidence", []):
                assert ev["source"] == "crossref"

    def test_sources_disable(self):
        code, out, err = _run_cli(["audit", "examples/refs.bib", "--sources", "no-crossref", "--no-cache", "--json"])
        assert code == EXIT_OK
        data = json.loads(out)
        for r in data["results"]:
            for ev in r.get("evidence", []):
                assert ev["source"] != "crossref"

    def test_available_sources(self):
        names = source_names()
        assert "crossref" in names
        assert "openalex" in names
        assert "arxiv" in names
        assert len(names) == 9


class TestCliWorkers:
    def test_workers_flag(self):
        code, out, err = _run_cli(["audit", "examples/refs.bib", "--workers", "2", "--no-cache"])
        assert code == EXIT_OK


class TestCliCache:
    def test_no_cache_flag(self):
        code, out, err = _run_cli(["audit", "examples/refs.bib", "--no-cache"])
        assert code == EXIT_OK

    def test_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            code, out, err = _run_cli(["audit", "examples/refs.bib", "--cache-dir", tmpdir])
            assert code == EXIT_OK


class TestCliExitCodes:
    def test_usage_error(self):
        code, out, err = _run_cli(["nonexistent_command"])
        assert code == EXIT_USAGE

    def test_policy_violation_exit_code(self):
        # Create a policy that will fail on the status an offline audit yields
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("fail_on:\n  - NOT_FOUND\n  - DOI_NOT_FOUND\n")
            path = f.name
        try:
            code, out, err = _run_cli(["audit", "examples/refs.bib", "--policy", path, "--no-cache"])
            assert code == EXIT_POLICY
        finally:
            Path(path).unlink(missing_ok=True)


class TestApiWithFakeTransport:
    """Test API functions with injected fake transport."""

    def test_audit_references_with_fake_transport(self):
        def fake_transport(url: str, timeout: float | None = None) -> Response:
            return Response(
                url=url,
                status=200,
                body=b'{"message": {"items": []}}',
                from_cache=False,
            )

        results = api.audit_references(
            "examples/refs.bib",
            transport=fake_transport,
            sources=["crossref"],
        )
        assert len(results) == 2
        for r in results:
            assert r.status in ("NOT_FOUND", "DOI_NOT_FOUND")

    def test_parse_references(self):
        refs = api.parse_references("examples/refs.bib")
        assert len(refs) == 2
        assert refs[0].title == "Soil consolidation settlement under staged embankment loading"

    def test_parse_references_text(self):
        refs = api.parse_references("examples/refs.txt")
        assert len(refs) == 2

    def test_verify_ledger_api(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            path = f.name
        try:
            report = api.verify_ledger(path)
            assert report["ok"] is True
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_policy_api(self):
        policy = api.load_policy("examples/policy.yaml")
        assert policy["fail_on"] == ["RETRACTED", "DOI_NOT_FOUND"]

    def test_write_report_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = api.audit_references("examples/refs.bib", transport=lambda u, t: Response(u, 200, b'{"message": {"items": []}}', False))
            path = api.write_report(results, tmpdir, fmt="json")
            assert path is not None
            assert Path(path).exists()
            data = json.loads(Path(path).read_text())
            assert data["tool"] == "veridex"
            assert len(data["results"]) == 2

    def test_summarize(self):
        results = api.audit_references("examples/refs.bib", transport=lambda u, t: Response(u, 200, b'{"message": {"items": []}}', False))
        summary = api.summarize(results)
        assert isinstance(summary, dict)
        assert sum(summary.values()) == 2


class TestResolverBuild:
    def test_build_all_sources(self):
        client = HttpClient(user_agent="test", cache_dir=None, transport=lambda u, t: Response(u, 200, b"{}", False))
        for name in source_names():
            src = build(name, client, SourceOpts(enabled=True))
            assert src is not None
            assert src.name == name

    def test_build_disabled(self):
        client = HttpClient(user_agent="test", cache_dir=None, transport=lambda u, t: Response(u, 200, b"{}", False))
        src = build("crossref", client, SourceOpts(enabled=False))
        assert src is None

    def test_build_unknown(self):
        client = HttpClient(user_agent="test", cache_dir=None, transport=lambda u, t: Response(u, 200, b"{}", False))
        src = build("unknown_source", client, SourceOpts(enabled=True))
        assert src is None


class TestMainModule:
    def test_main_module(self):
        code, out, err = _run_subprocess(["--version"])
        assert code == 0
        assert "veridex 0.3.0" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])