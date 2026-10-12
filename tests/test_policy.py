# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for policy loading, validation and evaluation. Stdlib only."""
from __future__ import annotations

import tempfile
from pathlib import Path

from veridex.policy import (
    DEFAULT_POLICY,
    evaluate_policy,
    load_policy,
    parse_yaml,
    validate_policy,
)


class TestParseYAML:
    def test_empty_string(self):
        assert parse_yaml("") == {}

    def test_none_input(self):
        assert parse_yaml(None) is None

    def test_simple_mapping(self):
        data = parse_yaml("key: value\nnumber: 42")
        assert data == {"key": "value", "number": 42}

    def test_nested_mapping(self):
        data = parse_yaml("outer:\n  inner: value")
        assert data == {"outer": {"inner": "value"}}

    def test_inline_list(self):
        data = parse_yaml("items: [a, b, c]")
        assert data == {"items": ["a", "b", "c"]}

    def test_block_list(self):
        data = parse_yaml("items:\n  - a\n  - b\n  - c")
        assert data == {"items": ["a", "b", "c"]}

    def test_quoted_strings(self):
        data = parse_yaml('key: "quoted value"\nother: \'single quoted\'')
        assert data == {"key": "quoted value", "other": "single quoted"}

    def test_booleans(self):
        data = parse_yaml("yes: true\nno: false\nyes2: yes\nno2: no\non: on\noff: off")
        assert data["yes"] is True
        assert data["no"] is False
        assert data["yes2"] is True
        assert data["no2"] is False
        assert data["on"] is True
        assert data["off"] is False

    def test_null_values(self):
        data = parse_yaml("empty: null\ntilde: ~\nnone: none")
        assert data["empty"] is None
        assert data["tilde"] is None
        assert data["none"] is None

    def test_integers_and_floats(self):
        data = parse_yaml("int: 42\nneg: -7\nfloat: 3.14\nscientific: 1e-5")
        assert data["int"] == 42
        assert data["neg"] == -7
        assert data["float"] == 3.14
        assert data["scientific"] == 1e-5

    def test_comments(self):
        data = parse_yaml("key: value # comment\n# full line comment\nother: value2")
        assert data == {"key": "value", "other": "value2"}

    def test_comment_inside_quotes(self):
        data = parse_yaml('key: "value # not a comment"')
        assert data == {"key": "value # not a comment"}

    def test_mixed_list_and_mapping(self):
        # Parser doesn't support mixed list + mapping at same level; list takes precedence
        data = parse_yaml("map:\n  - a\n  - b\n  key: value")
        assert data == {"map": ["a", "b"]}

    def test_list_of_mappings(self):
        data = parse_yaml("items:\n  - key1: val1\n  - key2: val2")
        assert data == {"items": [{"key1": "val1"}, {"key2": "val2"}]}


class TestLoadPolicy:
    def test_default_when_empty(self):
        policy = load_policy("")
        assert policy == DEFAULT_POLICY

    def test_load_json_string(self):
        policy = load_policy('{"fail_on": ["RETRACTED"]}')
        assert policy["fail_on"] == ["RETRACTED"]

    def test_load_yaml_string(self):
        policy = load_policy("fail_on:\n  - RETRACTED")
        assert policy["fail_on"] == ["RETRACTED"]

    def test_load_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("fail_on:\n  - MISMATCH\n")
            path = f.name
        try:
            policy = load_policy(path)
            assert policy["fail_on"] == ["MISMATCH"]
        finally:
            Path(path).unlink()

    def test_nonexistent_file_treated_as_text(self):
        # load_policy returns empty dict for non-existent paths (treated as empty YAML)
        policy = load_policy("/nonexistent/path.yaml")
        assert policy == {}

    def test_preserves_existing_keys(self):
        policy = load_policy("fail_on: []\nmax_fabrication_score: 0.5")
        assert "max_fabrication_score" in policy
        assert policy["max_fabrication_score"] == 0.5


class TestValidatePolicy:
    def test_valid_default(self):
        errors = validate_policy(DEFAULT_POLICY)
        assert errors == []

    def test_unknown_key(self):
        errors = validate_policy({"unknown_key": "value"})
        assert any("unknown policy key" in e for e in errors)

    def test_fail_on_valid_statuses(self):
        errors = validate_policy({"fail_on": ["RETRACTED", "DOI_NOT_FOUND", "MISMATCH"]})
        assert errors == []

    def test_fail_on_invalid_status(self):
        errors = validate_policy({"fail_on": ["INVALID_STATUS"]})
        assert any("unknown status in fail_on" in e for e in errors)

    def test_fail_on_non_list(self):
        errors = validate_policy({"fail_on": "RETRACTED"})
        assert any("fail_on must be a list" in e for e in errors)

    def test_ratio_keys_valid(self):
        errors = validate_policy(
            {
                "max_fabrication_score": 0.5,
                "max_weak_context_ratio": 0.5,
                "min_verified_ratio": 0.5,
            }
        )
        assert errors == []

    def test_ratio_keys_out_of_range(self):
        errors = validate_policy({"max_fabrication_score": 1.5})
        assert any("must be between 0 and 1" in e for e in errors)

    def test_ratio_keys_non_numeric(self):
        errors = validate_policy({"max_fabrication_score": "high"})
        assert any("must be a number" in e for e in errors)

    def test_required_fields_valid(self):
        errors = validate_policy({"required_fields": ["title", "year", "authors"]})
        assert errors == []

    def test_required_fields_invalid(self):
        errors = validate_policy({"required_fields": ["nonexistent_field"]})
        assert any("unknown reference field" in e for e in errors)

    def test_allowed_venues_valid(self):
        errors = validate_policy({"allowed_venues": ["Journal A", "Journal B"]})
        assert errors == []

    def test_blocked_venues_valid(self):
        errors = validate_policy({"blocked_venues": ["Bad Journal"]})
        assert errors == []

    def test_venue_lists_non_strings(self):
        errors = validate_policy({"allowed_venues": ["Journal", 123]})
        assert any("entry is not a string" in e for e in errors)


class TestEvaluatePolicy:
    def _make_result(
        self,
        index: int,
        status: str = "VERIFIED",
        fabrication_score: float = 0.0,
        title: str = "Test Title",
        year: int = 2020,
        journal: str = "Test Journal",
        context_entries: list | None = None,
    ) -> dict:
        return {
            "index": index,
            "status": status,
            "fabrication": {"score": fabrication_score, "signals": []},
            "input": {"title": title, "year": year},
            "record": {"journal": journal},
            "context": context_entries or [],
        }

    def test_fail_on_retracted(self):
        results = [self._make_result(0, status="RETRACTED")]
        policy = {"fail_on": ["RETRACTED"]}
        violations = evaluate_policy(results, policy)
        assert len(violations) == 1
        assert violations[0]["code"] == "fail_on"

    def test_fail_on_doi_not_found(self):
        results = [self._make_result(0, status="DOI_NOT_FOUND")]
        policy = {"fail_on": ["DOI_NOT_FOUND"]}
        violations = evaluate_policy(results, policy)
        assert len(violations) == 1

    def test_max_fabrication_score(self):
        results = [self._make_result(0, fabrication_score=0.5)]
        policy = {"max_fabrication_score": 0.3}
        violations = evaluate_policy(results, policy)
        assert len(violations) == 1
        assert violations[0]["code"] == "max_fabrication_score"

    def test_max_fabrication_score_ok(self):
        results = [self._make_result(0, fabrication_score=0.2)]
        policy = {"max_fabrication_score": 0.3}
        violations = evaluate_policy(results, policy)
        assert violations == []

    def test_max_weak_context_ratio(self):
        # 1 WEAK out of 2 total = 0.5 <= 0.5, should pass
        results = [
            self._make_result(0, context_entries=[{"label": "WEAK"}]),
            self._make_result(1, context_entries=[{"label": "OK"}]),
        ]
        policy = {"max_weak_context_ratio": 0.5}
        violations = evaluate_policy(results, policy)
        assert violations == []

    def test_max_weak_context_ratio_violation(self):
        results = [
            self._make_result(0, context_entries=[{"label": "WEAK"}]),
            self._make_result(1, context_entries=[{"label": "WEAK"}]),
        ]
        policy = {"max_weak_context_ratio": 0.3}
        violations = evaluate_policy(results, policy)
        assert len(violations) == 1
        assert violations[0]["code"] == "max_weak_context_ratio"

    def test_required_fields_missing(self):
        results = [self._make_result(0, title="", year=None)]
        policy = {"required_fields": ["title", "year"]}
        violations = evaluate_policy(results, policy)
        assert len(violations) == 2
        codes = {v["code"] for v in violations}
        assert codes == {"missing_required_field"}

    def test_required_fields_present(self):
        results = [self._make_result(0, title="Test", year=2020)]
        policy = {"required_fields": ["title", "year"]}
        violations = evaluate_policy(results, policy)
        assert violations == []

    def test_allowed_venues_violation(self):
        results = [self._make_result(0, journal="Bad Journal")]
        policy = {"allowed_venues": ["Good Journal"]}
        violations = evaluate_policy(results, policy)
        assert len(violations) == 1
        assert violations[0]["code"] == "venue_not_allowed"

    def test_allowed_venues_ok(self):
        results = [self._make_result(0, journal="Good Journal")]
        policy = {"allowed_venues": ["Good Journal"]}
        violations = evaluate_policy(results, policy)
        assert violations == []

    def test_blocked_venues_violation(self):
        results = [self._make_result(0, journal="Blocked Journal")]
        policy = {"blocked_venues": ["Blocked Journal"]}
        violations = evaluate_policy(results, policy)
        assert len(violations) == 1
        assert violations[0]["code"] == "venue_blocked"

    def test_min_verified_ratio(self):
        # 2 VERIFIED out of 3 total = 0.67 >= 0.5, should pass
        results = [
            self._make_result(0, status="VERIFIED"),
            self._make_result(1, status="VERIFIED"),
            self._make_result(2, status="NOT_FOUND"),
        ]
        policy = {"min_verified_ratio": 0.5}
        violations = evaluate_policy(results, policy)
        assert violations == []

    def test_min_verified_ratio_violation(self):
        results = [
            self._make_result(0, status="MISMATCH"),
            self._make_result(1, status="NOT_FOUND"),
        ]
        policy = {"min_verified_ratio": 0.5}
        violations = evaluate_policy(results, policy)
        assert len(violations) == 1
        assert violations[0]["code"] == "min_verified_ratio"

    def test_deterministic_ordering(self):
        results = [
            self._make_result(2, status="MISMATCH", fabrication_score=0.5),
            self._make_result(0, status="MISMATCH", fabrication_score=0.5),
            self._make_result(1, status="MISMATCH", fabrication_score=0.5),
        ]
        policy = {"max_fabrication_score": 0.3}
        violations = evaluate_policy(results, policy)
        indices = [v["index"] for v in violations if v.get("index") is not None]
        assert indices == [0, 1, 2]


class TestPolicyFileIntegration:
    def test_load_example_policy(self):
        policy = load_policy("examples/policy.yaml")
        assert policy["fail_on"] == ["RETRACTED", "DOI_NOT_FOUND"]
        assert policy["max_fabrication_score"] == 0.35
        assert policy["required_fields"] == ["title", "year"]
        assert policy["blocked_venues"] == ["Predatory Reports Quarterly"]