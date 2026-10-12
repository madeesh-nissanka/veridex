# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""SARIF 2.1.0 structural validation for the ``sarif`` report format.

The renderer output is checked against the mandatory parts of the OASIS
SARIF 2.1.0 JSON shape (sections 3.13 log, 3.14 run, 3.20 driver,
3.49 reporting descriptor, 3.27 result, 3.11 message object) with a
hand-written stdlib validator - no schema download, fully offline.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from veridex.models import AuditResult, ParsedReference, ResolvedRecord, Status
from veridex.reports import render_report

_LEVELS = {"none", "note", "warning", "error"}


def _is_uri(value: Any) -> bool:
    return isinstance(value, str) and "://" in value and not value.startswith(" ")


def _check_message(obj: dict, path: str, problems: list[str]) -> None:
    msg = obj.get("message")
    if not isinstance(msg, dict):
        problems.append(f"{path}: message must be a message object")
    elif not isinstance(msg.get("text"), str) or not msg["text"]:
        problems.append(f"{path}: message.text must be a non-empty string")


def validate_sarif(data: Any) -> list[str]:
    """Return a list of SARIF 2.1.0 conformance problems (empty = valid)."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["log must be a JSON object"]
    if data.get("version") != "2.1.0":
        problems.append("version must be the string '2.1.0'")
    if "$schema" in data and not _is_uri(data["$schema"]):
        problems.append("$schema must be a URI string")
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        problems.append("runs must be a non-empty array")
        return problems
    for ri, run in enumerate(runs):
        rpath = f"runs[{ri}]"
        if not isinstance(run, dict):
            problems.append(f"{rpath}: must be an object")
            continue
        tool = run.get("tool")
        if not isinstance(tool, dict):
            problems.append(f"{rpath}: tool is required and must be an object")
            continue
        driver = tool.get("driver")
        if not isinstance(driver, dict):
            problems.append(f"{rpath}: tool.driver is required and must be an object")
            continue
        name = driver.get("name")
        if not isinstance(name, str) or not name:
            problems.append(f"{rpath}: tool.driver.name must be a non-empty string")
        if "version" in driver and not isinstance(driver["version"], str):
            problems.append(f"{rpath}: tool.driver.version must be a string")
        if "informationUri" in driver and not _is_uri(driver["informationUri"]):
            problems.append(f"{rpath}: tool.driver.informationUri must be a URI string")
        rule_ids: set[str] = set()
        for xi, rule in enumerate(driver.get("rules", [])):
            rpath2 = f"{rpath}: rules[{xi}]"
            if not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or not rule["id"]:
                problems.append(f"{rpath2}: rule id must be a non-empty string")
                continue
            if rule["id"] in rule_ids:
                problems.append(f"{rpath2}: duplicate rule id {rule['id']}")
            rule_ids.add(rule["id"])
            for key in ("shortDescription", "fullDescription"):
                if key in rule:
                    if not isinstance(rule[key], dict) or not isinstance(rule[key].get("text"), str):
                        problems.append(f"{rpath2}: {key}.text must be a string")
            dc = rule.get("defaultConfiguration")
            if isinstance(dc, dict) and dc.get("level") not in _LEVELS | {None}:
                problems.append(f"{rpath2}: defaultConfiguration.level invalid")
        results = run.get("results", [])
        if not isinstance(results, list):
            problems.append(f"{rpath}: results must be an array")
            continue
        for yi, res in enumerate(results):
            rpath3 = f"{rpath}: results[{yi}]"
            if not isinstance(res, dict):
                problems.append(f"{rpath3}: must be an object")
                continue
            if "ruleId" in res:
                if not isinstance(res["ruleId"], str) or not res["ruleId"]:
                    problems.append(f"{rpath3}: ruleId must be a non-empty string")
                elif rule_ids and res["ruleId"] not in rule_ids:
                    problems.append(f"{rpath3}: ruleId {res['ruleId']} not declared in driver.rules")
            if res.get("level") not in _LEVELS | {None}:
                problems.append(f"{rpath3}: level must be one of none/note/warning/error")
            _check_message(res, rpath3, problems)
            locs = res.get("locations", [])
            if not isinstance(locs, list):
                problems.append(f"{rpath3}: locations must be an array")
                continue
            for zi, loc in enumerate(locs):
                lpath = f"{rpath3}: locations[{zi}]"
                ph = loc.get("physicalLocation") if isinstance(loc, dict) else None
                if not isinstance(ph, dict):
                    problems.append(f"{lpath}: physicalLocation must be an object")
                    continue
                art = ph.get("artifactLocation")
                if not isinstance(art, dict) or not isinstance(art.get("uri"), str) or not art["uri"]:
                    problems.append(f"{lpath}: artifactLocation.uri must be a non-empty string")
                region = ph.get("region")
                if "region" in ph:
                    if not isinstance(region, dict) or not isinstance(region.get("startLine"), int) or region["startLine"] < 1:
                        problems.append(f"{lpath}: region.startLine must be an integer >= 1")
            if "properties" in res and not isinstance(res["properties"], dict):
                problems.append(f"{rpath3}: properties must be an object")
    return problems


def _ref(idx: int) -> ParsedReference:
    return ParsedReference(
        index=idx, title=f"Input Title {idx}", authors=[f"Author {idx}A"],
        year=2020 + idx, journal=f"Input Journal {idx}", doi=f"10.1234/input{idx}",
    )


def _result(idx: int, **kw: Any) -> AuditResult:
    record = ResolvedRecord(
        source="crossref", source_id=f"rec{idx}", title=f"Resolved Title {idx}",
        authors=[{"family": f"Author{idx}A", "given": "A"}], year=2020 + idx,
        journal=f"Resolved Journal {idx}", volume="10", issue="2",
        pages="100-110", publisher="Publisher", doi=f"10.5678/r{idx}",
        url=f"https://example.com/r{idx}",
        source_url=f"https://api.crossref.org/works/10.5678/r{idx}",
        abstract="Abstract text.",
    )
    defaults: dict[str, Any] = {
        "index": idx, "input": _ref(idx), "record": record,
        "status": Status.VERIFIED, "flags": [], "fabrication": {"score": 0.1, "signals": []},
        "integrity": [], "evidence": [], "notes": [],
    }
    defaults.update(kw)
    return AuditResult(**defaults)


def _fixture_results() -> tuple[list[AuditResult], list[ParsedReference]]:
    retracted = _result(
        2, status=Status.RETRACTED, flags=["retracted"],
        fabrication={"score": 0.8, "signals": [{"code": "retracted", "weight": 0.5}]},
    )
    retracted.integrity = [{"kind": "retraction", "target": "work", "url": "https://example.com/x", "label": "Retracted"}]
    results = [
        _result(0, flags=["year_off_by_one"]),
        _result(1, status=Status.NOT_FOUND, record=None,
                flags=["no_matching_record"], fabrication={"score": 0.9, "signals": []}),
        retracted,
    ]
    return results, [_ref(i) for i in range(3)]


def _rendered(tmp: str, meta: dict[str, Any] | None = None) -> dict:
    results, entries = _fixture_results()
    out = Path(tmp) / "report.sarif"
    render_report(results, entries, "sarif", out, meta=meta)
    return json.loads(out.read_text(encoding="utf-8"))


class TestSarifConformance:
    def test_rendered_output_is_valid_sarif(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert validate_sarif(_rendered(tmp)) == []

    def test_every_result_references_a_declared_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _rendered(tmp)
            declared = {r["id"] for r in data["runs"][0]["tool"]["driver"]["rules"]}
            used = {r["ruleId"] for r in data["runs"][0]["results"]}
            assert used and used <= declared

    def test_driver_version_and_name_follow_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _rendered(tmp, meta={"tool": "mytool", "version": "9.9.9"})
            driver = data["runs"][0]["tool"]["driver"]
            assert driver["name"] == "mytool"
            assert driver["version"] == "9.9.9"

    def test_information_uri_is_a_real_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = _rendered(tmp)["runs"][0]["tool"]["driver"]
            assert _is_uri(driver["informationUri"])


class TestValidatorRejectsBrokenLogs:
    """The validator must not rubber-stamp: mutate a valid log, expect problems."""

    def _good(self, tmp: str) -> dict:
        return _rendered(tmp)

    def test_wrong_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._good(tmp)
            data["version"] = "2.0.0"
            assert any("version" in p for p in validate_sarif(data))

    def test_missing_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._good(tmp)
            del data["runs"][0]["results"][0]["message"]
            assert any("message" in p for p in validate_sarif(data))

    def test_dangling_rule_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._good(tmp)
            data["runs"][0]["results"][0]["ruleId"] = "not-a-rule"
            assert any("not declared" in p for p in validate_sarif(data))

    def test_bad_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._good(tmp)
            data["runs"][0]["results"][0]["level"] = "critical"
            assert any("level" in p for p in validate_sarif(data))

    def test_bad_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._good(tmp)
            data["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]["startLine"] = 0
            assert any("startLine" in p for p in validate_sarif(data))

    def test_empty_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._good(tmp)
            data["runs"] = []
            assert validate_sarif(data)
