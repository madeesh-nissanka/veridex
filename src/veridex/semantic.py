# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Optional semantic title similarity (stdlib fallback).

The default matching path is lexical (``difflib``) and needs nothing beyond the
standard library. When the optional ``semantic`` extra
(``pip install veridex[semantic]``) is installed, a small local sentence
embedding model can be used instead; it improves recall on paraphrased or
cross-language titles. If the model or its dependency is unavailable, every
function degrades gracefully to the lexical path and nothing raises.

Nothing here downloads a model implicitly: a model is only loaded when semantic
matching is explicitly enabled (``--semantic`` / ``evaluate(..., semantic=True)``)
and the dependency is importable. The model is cached in-process after first use.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Sequence

# In-process cached embedder: callable(list[str]) -> list[vector].
_EMBEDDER: Callable[[Sequence[str]], list[Sequence[float]]] | None = None
_LOAD_ATTEMPTED = False
_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def set_embedder(fn: Callable[[Sequence[str]], list[Sequence[float]]] | None) -> None:
    """Inject an embedder (used by tests); pass ``None`` to clear."""
    global _EMBEDDER, _LOAD_ATTEMPTED
    _EMBEDDER = fn
    _LOAD_ATTEMPTED = fn is not None


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += float(x) * float(y)
        na += float(x) * float(x)
        nb += float(y) * float(y)
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _load_default() -> Callable[[Sequence[str]], list[Sequence[float]]] | None:
    """Lazily build an embedder from sentence-transformers, or return None."""
    global _EMBEDDER, _LOAD_ATTEMPTED
    if _LOAD_ATTEMPTED:
        return _EMBEDDER
    _LOAD_ATTEMPTED = True
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception:
        return None
    try:
        model = SentenceTransformer(_DEFAULT_MODEL)

        def _embed(texts: Sequence[str]) -> list[Sequence[float]]:
            vectors = model.encode(list(texts), normalize_embeddings=True)
            return [list(v) for v in vectors]

        _EMBEDDER = _embed
    except Exception:
        _EMBEDDER = None
    return _EMBEDDER


def is_available() -> bool:
    """True if a semantic embedder can be used in this environment."""
    if _EMBEDDER is not None:
        return True
    return _load_default() is not None


def similarity(text_a: str | None, text_b: str | None) -> float | None:
    """Cosine similarity of two texts, or ``None`` when unavailable/empty.

    ``None`` signals the caller to fall back to lexical similarity; it is never
    an error.
    """
    if not text_a or not text_b:
        return None
    embedder = _EMBEDDER if _EMBEDDER is not None else _load_default()
    if embedder is None:
        return None
    try:
        vectors = embedder([text_a, text_b])
    except Exception:
        return None
    if not vectors or len(vectors) < 2:
        return None
    return _cosine(vectors[0], vectors[1])


def best_title_similarity(
    lexical: float,
    text_a: str | None,
    text_b: str | None,
    enabled: bool = False,
) -> float:
    """Combine lexical and (optional) semantic similarity.

    Semantic similarity, when available, can only increase the score: the two
    signals are complementary and the lexical path remains the safety floor.
    """
    if not enabled:
        return lexical
    sem = similarity(text_a, text_b)
    if sem is None:
        return lexical
    return max(lexical, max(0.0, min(1.0, sem)))


__all__ = ["set_embedder", "is_available", "similarity", "best_title_similarity"]
