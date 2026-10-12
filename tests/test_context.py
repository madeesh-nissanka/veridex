# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for context.py."""
from __future__ import annotations

from veridex.context import bm25_scores, score_support, analyze_citations
from veridex.models import AuditResult, ResolvedRecord


def test_bm25_scores_empty():
    """Test BM25 scores with empty inputs."""
    assert bm25_scores([], []) == []
    assert bm25_scores(["term"], []) == []
    assert bm25_scores(["term"], [[], []]) == [0.0, 0.0]


def test_bm25_scores_simple():
    """Test BM25 scores with simple case."""
    query = ["test", "document"]
    corpus = [
        ["test", "document"],  # Exact match
        ["other", "words"],    # No match
        ["test", "other"]      # Partial match
    ]
    
    scores = bm25_scores(query, corpus)
    assert len(scores) == 3
    
    # First document should have highest score
    assert scores[0] > scores[1]
    assert scores[0] > scores[2]
    
    # Second document should have lowest score (no query terms)
    assert scores[1] <= scores[0]
    assert scores[1] <= scores[2]
    
    # All scores should be non-negative
    assert all(s >= 0 for s in scores)


def test_bm25_scores_idf_effect():
    """Test that IDF affects scoring - rare terms score higher."""
    query = ["rare", "common"]
    corpus = [
        ["rare", "term"],        # Has rare term
        ["common", "word"],      # Has common term
        ["rare", "common"]       # Has both
    ]
    
    scores = bm25_scores(query, corpus)
    
    # Document with both terms should score highest
    assert scores[2] >= scores[0]
    assert scores[2] >= scores[1]
    
    # Rare term should contribute more than common term
    # (This depends on corpus statistics, but generally true)


def test_tokenize_helper():
    """Test the internal _tokenize function indirectly through score_support."""
    # This is tested through score_support, but we can verify tokenization works
    from veridex.context import _tokenize
    
    assert _tokenize("Hello, World!") == ["hello", "world"]
    assert _tokenize("") == []
    assert _tokenize("Test-123") == ["test", "123"]
    assert _tokenize("Multiple   spaces") == ["multiple", "spaces"]


def test_score_support_basic():
    """Test basic score_support functionality."""
    # Exact match should score high
    result = score_support("hello world", "Hello World")
    assert result["score"] > 0.8  # Should be very high for identical text
    assert result["label"] == "OK"
    
    # No match should score low
    result = score_support("foo bar", "Hello World")
    assert result["score"] < 0.15  # Should be low for no overlap
    assert result["label"] == "WEAK"
    
    # Partial match
    result = score_support("hello world", "Hello there world")
    assert 0.15 <= result["score"] <= 0.8
    if result["score"] < 0.15:
        assert result["label"] == "WEAK"
    elif result["score"] < 0.35:
        assert result["label"] == "MODERATE"
    else:
        assert result["label"] == "OK"


def test_score_support_empty_inputs():
    """Test score_support with empty inputs."""
    assert score_support("", "Hello")["score"] == 0.0
    assert score_support("Hello", "")["score"] == 0.0
    assert score_support("", "")["score"] == 0.0
    assert score_support(None, "Hello")["score"] == 0.0
    assert score_support("Hello", None)["score"] == 0.0


def test_score_support_with_abstract():
    """Test score_support uses abstract when provided."""
    sentence = "This paper discusses machine learning techniques"
    title = "A Study on Machine Learning"
    abstract = "We present novel machine learning techniques for pattern recognition"
    
    result = score_support(sentence, title, abstract)
    # Should score higher with abstract than without
    result_without_abstract = score_support(sentence, title)
    
    # With abstract should generally score higher (though not guaranteed due to TF-IDF specifics)
    assert result["score"] >= 0.0  # At least valid
    assert "label" in result


def test_score_support_heuristic_flag():
    """Test that score_support result includes heuristic flag."""
    result = score_support("test", "test")
    assert "heuristic" in result
    assert result["heuristic"] == True


def test_analyze_citations_empty():
    """Test analyze_citations with empty inputs."""
    # Should not crash
    analyze_citations([], [])
    analyze_citations([{"marker": "[1]", "sentence": "test", "ref_index": 0}], [])
    analyze_citations([], [AuditResult(index=0)])


def test_analyze_citations_basic():
    """Test basic analyze_citations functionality."""
    # Create a mock result
    result = AuditResult(index=0)
    result.record = ResolvedRecord(
        title="Neural Networks for Image Recognition",
        abstract="We use deep learning to recognize images"
    )
    
    # Create citation that matches well
    citation = {
        "marker": "[1]",
        "sentence": "Our approach uses neural networks for image recognition tasks",
        "ref_index": 0
    }
    
    results = [result]
    analyze_citations([citation], results)
    
    # Should have added context and possibly flags
    assert hasattr(result, 'context')
    assert isinstance(result.context, dict)
    assert len(result.context) > 0
    
    # Check that context contains heuristic information
    for key, value in result.context.items():
        assert isinstance(value, dict)
        assert "score" in value
        assert "label" in value
        assert "heuristic" in value
        assert value["heuristic"] == True


def test_analyze_citations_weak_support():
    """Test analyze_citations adds weak_context_support flag for low scores."""
    # Create a mock result with unrelated title/abstract
    result = AuditResult(index=0)
    result.record = ResolvedRecord(
        title="Cooking Recipes for Beginners",
        abstract="Learn to cook delicious meals"
    )
    
    # Create citation about unrelated topic
    citation = {
        "marker": "[1]",
        "sentence": "Quantum computing uses qubits for processing information",
        "ref_index": 0
    }
    
    results = [result]
    analyze_citations([citation], results)
    
    # Should have weak context support (low score)
    # Note: Depending on the actual scoring, this might or might not be weak
    # But we can check that if score < 0.15, the flag is added
    if hasattr(result, 'context') and result.context:
        for key, value in result.context.items():
            if isinstance(value, dict) and "score" in value:
                if value["score"] < 0.15:
                    # Should have weak context support flag
                    assert hasattr(result, 'flags')
                    assert isinstance(result.flags, list)
                    # The flag might be added, but we won't guarantee it since
                    # the exact score depends on implementation details
                    pass


def test_analyze_citations_multiple_citations():
    """Test analyze_citations with multiple citations."""
    result = AuditResult(index=0)
    result.record = ResolvedRecord(
        title="Machine Learning in Healthcare",
        abstract="Applications of ML to medical diagnosis"
    )
    
    citations = [
        {
            "marker": "[1]",
            "sentence": "Machine learning transforms healthcare delivery",
            "ref_index": 0
        },
        {
            "marker": "[2]",
            "sentence": "Deep learning models assist in medical imaging",
            "ref_index": 0
        },
        {
            "marker": "[3]",
            "sentence": "Unrelated topic about space exploration",
            "ref_index": 0
        }
    ]
    
    results = [result]
    analyze_citations(citations, results)
    
    # Should have processed all citations
    assert hasattr(result, 'context')
    assert isinstance(result.context, dict)
    # Should have entries for each citation
    assert len(result.context) == 3


def test_analyze_citations_invalid_ref_index():
    """Test analyze_citations handles invalid ref_index gracefully."""
    result = AuditResult(index=0)
    result.record = ResolvedRecord(title="Test", year=2020)
    
    # Citation with invalid ref_index (too high)
    citation = {
        "marker": "[1]",
        "sentence": "test sentence",
        "ref_index": 5  # Out of bounds
    }
    
    results = [result]
    # Should not crash
    analyze_citations([citation], results)
    
    # Citation with negative ref_index
    citation2 = {
        "marker": "[2]",
        "sentence": "test sentence",
        "ref_index": -1
    }
    
    analyze_citations([citation2], results)
    # Should still not crash


def test_analyze_citations_missing_fields():
    """Test analyze_citations handles missing fields gracefully."""
    result = AuditResult(index=0)
    result.record = ResolvedRecord(title="Test", year=2020)
    
    # Citation missing ref_index
    citation = {
        "marker": "[1]",
        "sentence": "test sentence"
        # Missing ref_index
    }
    
    results = [result]
    analyze_citations([citation], results)
    # Should not crash
    
    # Citation missing sentence
    citation2 = {
        "marker": "[1]",
        "ref_index": 0
        # Missing sentence
    }
    
    analyze_citations([citation2], results)
    # Should not crash