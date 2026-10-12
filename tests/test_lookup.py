# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Offline tests for the ``lookup`` batch identifier command (v0.3.0)."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from veridex import api
from veridex.cli import main
from veridex.httpclient import Response

WORK = {
    "DOI": "10.1016/j.soil.2019.01.001",
    "title": ["Soil consolidation settlement under staged loading"],
    "container-title": ["Journal of Generic Geotechnics"],
    "issued": {"date-parts": [[2019]]},
    "volume": "45",
    "issue": "3",
    "page": "100-118",
    "author": [{"family": "Alvarez", "given": "M."}, {"family": "Berg", "given": "K."}],
}


def fake_transport(url: str, timeout=None) -> Response:
    if "api.crossref.org/works/10.1016" in url:
        return Response(url=url, status=200, body=json.dumps({"message": WORK}).encode(), ok=True)
    return Response(url=url, status=200, body=b'{"message": {"items": []}}', ok=True)


@pytest.fixture()
def offline(monkeypatch):
    monkeypatch.setattr(api, "TRANSPORT", fake_transport)


@pytest.fixture()
def ids_file(tmp_path: Path) -> str:
    f = tmp_path / "ids.txt"
    f.write_text(
        "10.1016/j.soil.2019.01.001\n"
        "https://doi.org/10.9999/nothing.here\n"
        "just some prose line without any identifier\n",
        encoding="utf-8",
    )
    return str(f)


class TestLookupApi:
    def test_hit_and_miss_rows(self, offline, ids_file):
        rows = api.lookup_references(ids_file, sources=["crossref"], cache_dir=None)
        assert len(rows) == 3
        assert rows[0]["title"] == WORK["title"][0]
        assert rows[0]["year"] == 2019
        assert rows[0]["source"] == "crossref"
        assert rows[0]["status"] in ("VERIFIED", "VERIFIED_WITH_WARNINGS")
        assert rows[1]["title"] is None  # DOI query with no record
        assert rows[1]["identifier"] == "10.9999/nothing.here"

    def test_rows_follow_input_order(self, offline, ids_file):
        rows = api.lookup_references(ids_file, sources=["crossref"], cache_dir=None)
        assert [r["index"] for r in rows] == [0, 1, 2]

    def test_row_contract_keys(self, offline, ids_file):
        rows = api.lookup_references(ids_file, sources=["crossref"], cache_dir=None)
        expected = {"index", "query", "identifier", "status", "source",
                    "title", "year", "journal", "doi"}
        assert all(expected == set(r) for r in rows)


class TestLookupCli:
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_json_output(self, offline, ids_file):
        code, out, _ = self._run(
            ["lookup", ids_file, "--sources", "crossref", "--no-cache", "--json"]
        )
        assert code == 0
        payload = json.loads(out)
        assert payload["count"] == 3
        assert payload["lookups"][0]["doi"] == WORK["DOI"]

    def test_text_output(self, offline, ids_file):
        code, out, _ = self._run(
            ["lookup", ids_file, "--sources", "crossref", "--no-cache"]
        )
        assert code == 0
        assert "10.1016/j.soil.2019.01.001" in out
        assert "Soil consolidation settlement" in out
        assert "no matching record" in out

    def test_requires_file(self, offline):
        code, _, err = self._run(["lookup"])
        assert code == 2
        assert "requires an identifier file" in err

    def test_missing_file_exit_2(self, offline):
        code, _, err = self._run(["lookup", "/no/such/ids.txt"])
        assert code == 2
        assert "file not found" in err
