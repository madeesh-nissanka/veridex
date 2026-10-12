# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for optional semantic title similarity and its stdlib fallback."""
from __future__ import annotations

import pytest

from veridex import matching, semantic
from veridex.models import ParsedReference, ResolvedRecord


@pytest.fixture(autouse=True)
def _reset_embedder():
    semantic.set_embedder(None)
    yield
    semantic.set_embedder(None)


def _ref(title: str, **kw) -> ParsedReference:
    return ParsedReference(index=0, title=title, authors=["Smith, A."], year=2020, doi="10.1000/x", **kw)


def _rec(title: str, **kw) -> ResolvedRecord:
    return ResolvedRecord(source="crossref", source_id="x", title=title,
                          authors=[{"family": "Smith", "given": "A."}], year=2020, doi="10.1000/x", **kw)


class TestFallback:
    def test_no_embedder_returns_none(self, monkeypatch):
        # Pretend sentence-transformers is not installed.
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("sentence_transformers"):
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        semantic.set_embedder(None)
        # Force a re-load attempt.
        semantic._LOAD_ATTEMPTED = False  # type: ignore[attr-defined]
        assert semantic.similarity("a", "b") is None

    def test_best_title_similarity_disabled_is_lexical(self):
        assert semantic.best_title_similarity(0.42, "a", "b", enabled=False) == 0.42

    def test_best_title_similarity_no_backend_is_lexical(self):
        assert semantic.best_title_similarity(0.42, "a", "b", enabled=True) == 0.42

    def test_empty_text_returns_none(self):
        semantic.set_embedder(lambda texts: [[1.0], [1.0]])
        assert semantic.similarity("", "x") is None
        assert semantic.similarity(None, "x") is None


class TestInjectedEmbedder:
    def test_cosine_similarity(self):
        def embed(texts):
            table = {"paraphrase": [1.0, 0.0], "original": [0.9, 0.1]}
            return [table.get(t, [0.0, 1.0]) for t in texts]

        semantic.set_embedder(embed)
        sim = semantic.similarity("paraphrase", "original")
        assert sim is not None and sim > 0.9

    def test_semantic_can_only_increase_score(self):
        semantic.set_embedder(lambda texts: [[1.0, 0.0], [1.0, 0.0]])
        assert semantic.best_title_similarity(0.1, "a", "b", enabled=True) == pytest.approx(1.0)

    def test_evaluate_uses_semantic_title_similarity(self):
        # Lexically the titles are unrelated; the fake embedder makes them equal.
        ref = _ref("How shallow supports sink into sandy ground")
        rec = _rec("Elastic settlement of footings on granular soil")
        lexical = matching.evaluate(ref, rec)
        assert lexical["scores"]["title_sim"] < 0.6

        semantic.set_embedder(lambda texts: [[1.0, 0.0], [1.0, 0.0]])
        boosted = matching.evaluate(ref, rec, semantic=True)
        assert boosted["scores"]["title_sim"] == pytest.approx(1.0)
        assert "doi_resolves_to_different_work" not in boosted["flags"]
        assert "doi_resolves_to_different_work" in lexical["flags"]

    def test_evaluate_semantic_false_ignores_embedder(self):
        semantic.set_embedder(lambda texts: [[1.0, 0.0], [1.0, 0.0]])
        ref = _ref("Alpha beta gamma delta physics")
        rec = _rec("Zeta omega kappa lambda chemistry")
        ev = matching.evaluate(ref, rec, semantic=False)
        assert ev["scores"]["title_sim"] < 0.9

    def test_broken_embedder_falls_back(self):
        def broken(texts):
            raise RuntimeError("boom")

        semantic.set_embedder(broken)
        assert semantic.best_title_similarity(0.3, "a", "b", enabled=True) == 0.3


class TestCliFlag:
    def test_semantic_flag_parsed(self, monkeypatch):
        from veridex import api
        from veridex.cli import main
        from veridex.httpclient import Response

        def fake(url, timeout=None):
            return Response(url=url, status=200, body=b'{"message": {"items": []}}', from_cache=False)

        monkeypatch.setattr(api, "TRANSPORT", fake)
        # Should run cleanly offline whether or not a semantic backend is present.
        code = main(["--json", "--semantic", "audit", "examples/refs.bib", "--no-cache"])
        assert code == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
