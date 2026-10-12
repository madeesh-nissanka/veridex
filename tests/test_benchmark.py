# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for the offline labelled benchmark (benchmarks/run_benchmark.py).

These tests exercise the real detection pipeline over the synthetic labelled
dataset. They assert structural properties and reproducibility rather than
hard-coding metric values, so the numbers stay honest if cases change.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_BENCH = Path(__file__).resolve().parents[1] / "benchmarks" / "run_benchmark.py"


def _load_benchmark():
    spec = importlib.util.spec_from_file_location("run_benchmark", _BENCH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bench():
    return _load_benchmark()


class TestBenchmarkDataset:
    def test_dataset_is_deterministic(self, bench):
        assert bench.build_cases() == bench.build_cases()

    def test_expected_size_and_categories(self, bench):
        cases = bench.build_cases()
        assert len(cases) == 59
        categories = {c["category"] for c in cases}
        for cat in (
            "correct",
            "fabricated",
            "corrupted_year",
            "corrupted_author",
            "doi_different_work",
            "retracted",
            "near_duplicate",
            "hard_negative",
            "paraphrase",
        ):
            assert cat in categories, cat

    def test_labels_are_known_signals(self, bench):
        for case in bench.build_cases():
            for label in case["labels"]:
                assert label in bench.SIGNALS

    def test_case_ids_unique(self, bench):
        ids = [c["id"] for c in bench.build_cases()]
        assert len(ids) == len(set(ids))


class TestBenchmarkMetrics:
    def test_metrics_structure(self, bench):
        metrics = bench.run_benchmark()
        assert metrics["n_cases"] == 59
        for signal in bench.SIGNALS:
            m = metrics["per_signal"][signal]
            for key in ("tp", "fp", "fn", "tn", "precision", "recall", "f1"):
                assert key in m
            assert 0.0 <= m["precision"] <= 1.0
            assert 0.0 <= m["recall"] <= 1.0
            assert 0.0 <= m["f1"] <= 1.0

    def test_metric_identities_hold(self, bench):
        metrics = bench.run_benchmark()
        total = 0
        for signal in bench.SIGNALS:
            m = metrics["per_signal"][signal]
            total += m["tp"] + m["fp"] + m["fn"] + m["tn"]
            if m["tp"] + m["fp"]:
                assert m["precision"] == pytest.approx(m["tp"] / (m["tp"] + m["fp"]), abs=1e-3)
            if m["tp"] + m["fn"]:
                assert m["recall"] == pytest.approx(m["tp"] / (m["tp"] + m["fn"]), abs=1e-3)
        # Each case contributes to each signal's confusion matrix exactly once.
        assert total == metrics["n_cases"] * len(bench.SIGNALS)

    def test_deterministic_metrics(self, bench):
        assert bench.run_benchmark() == bench.run_benchmark()

    def test_clean_signals_are_high_confidence(self, bench):
        """Signals with only cleanly-separable cases must reach F1 == 1.0."""
        metrics = bench.run_benchmark()
        for signal in (
            "no_matching_record",
            "year_mismatch",
            "author_mismatch",
            "retracted",
            "near_duplicate",
        ):
            m = metrics["per_signal"][signal]
            assert m["f1"] == 1.0, (signal, m)

    def test_paraphrase_limit_is_recorded(self, bench):
        """Lexical matching is expected to misread paraphrases: record the FP."""
        metrics = bench.run_benchmark()
        m = metrics["per_signal"]["doi_resolves_to_different_work"]
        assert m["recall"] == 1.0
        assert m["fp"] >= 1
        assert m["precision"] < 1.0

    def test_overall_classification(self, bench):
        metrics = bench.run_benchmark()
        overall = metrics["overall"]
        assert overall["recall"] == 1.0
        assert overall["accuracy"] >= 0.85


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
