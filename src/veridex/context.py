# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Context analysis: BM25, TF-IDF, citation support. Stdlib only."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List, Tuple

from .models import AuditResult


def bm25_scores(query_tokens: list[str], corpus: list[list[str]]) -> list[float]:
    """Compute BM25 scores for query against corpus documents.
    
    Args:
        query_tokens: List of query terms
        corpus: List of documents, each as list of tokens
        
    Returns:
        List of BM25 scores, one per corpus document
    """
    if not corpus:
        return []
    
    if not query_tokens:
        return [0.0] * len(corpus)
    
    # BM25 parameters
    k1 = 1.5
    b = 0.75
    
    # Compute document frequencies
    doc_freqs: Dict[str, int] = {}
    for doc in corpus:
        seen_terms = set(doc)
        for term in seen_terms:
            doc_freqs[term] = doc_freqs.get(term, 0) + 1
    
    # Compute average document length
    doc_lengths = [len(doc) for doc in corpus]
    avg_doc_len = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 0.0
    
    # Compute scores
    scores = []
    for doc_idx, doc in enumerate(corpus):
        score = 0.0
        doc_len = doc_lengths[doc_idx]
        
        # Count term frequencies in this document
        term_freqs = Counter(doc)
        
        for term in query_tokens:
            if term not in doc_freqs:
                continue
                
            # IDF component (smoothed, always non-negative)
            df = doc_freqs[term]
            idf = math.log(1.0 + (len(corpus) - df + 0.5) / (df + 0.5))
            
            # TF component
            tf = term_freqs.get(term, 0)
            if tf == 0:
                continue

            # BM25 formula
            numerator = tf * (k1 + 1)
            if avg_doc_len > 0:
                denominator = tf + k1 * (1 - b + b * (doc_len / avg_doc_len))
            else:
                denominator = tf + k1
            score += idf * (numerator / denominator)

        scores.append(score)
    
    return scores


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: lowercase and split on non-alphanumeric."""
    if not text:
        return []
    return re.findall(r'[a-z0-9]+', text.lower())


def _compute_tfidf_vector(tokens: list[str], vocab: Dict[str, int], doc_freqs: Dict[str, int], num_docs: int) -> List[float]:
    """Compute TF-IDF vector for a document."""
    vector = [0.0] * len(vocab)
    term_freqs = Counter(tokens)
    doc_len = len(tokens)
    
    for term, tf in term_freqs.items():
        if term in vocab:
            idx = vocab[term]
            # TF component (normalized term frequency)
            tf_norm = tf / doc_len if doc_len > 0 else 0
            # IDF component
            df = doc_freqs.get(term, 0)
            idf = math.log((num_docs + 1) / (df + 1)) + 1  # smoothed
            vector[idx] = tf_norm * idf
    
    return vector


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return dot_product / (norm1 * norm2)


def score_support(sentence: str, title: str, abstract: str | None = None) -> dict[str, Any]:
    """Score contextual support using TF-IDF cosine similarity.
    
    Returns dict with score (0..1) and label ("WEAK"|"MODERATE"|"OK").
    """
    if not sentence or not title:
        return {"score": 0.0, "label": "WEAK"}
    
    # Combine title and abstract for context
    context_text = title
    if abstract:
        context_text += " " + abstract
    
    # Tokenize
    query_tokens = _tokenize(sentence)
    context_tokens = _tokenize(context_text)
    
    if not query_tokens or not context_tokens:
        return {"score": 0.0, "label": "WEAK"}
    
    # Build vocabulary from both query and context
    all_tokens = list(set(query_tokens + context_tokens))
    vocab = {token: idx for idx, token in enumerate(all_tokens)}
    
    # Compute document frequencies (for IDF)
    # We have two "documents": query and context
    doc_freqs: Dict[str, int] = {}
    query_set = set(query_tokens)
    context_set = set(context_tokens)
    
    for token in all_tokens:
        df = 0
        if token in query_set:
            df += 1
        if token in context_set:
            df += 1
        doc_freqs[token] = df
    
    # Compute TF-IDF vectors
    query_vector = _compute_tfidf_vector(query_tokens, vocab, doc_freqs, 2)
    context_vector = _compute_tfidf_vector(context_tokens, vocab, doc_freqs, 2)
    
    # Compute cosine similarity
    similarity = _cosine_similarity(query_vector, context_vector)
    
    # Clamp to [0, 1] range (should already be, but just in case)
    similarity = max(0.0, min(1.0, similarity))
    
    # Determine label based on thresholds
    if similarity < 0.15:
        label = "WEAK"
    elif similarity < 0.35:
        label = "MODERATE"
    else:
        label = "OK"
    
    return {"score": round(similarity, 4), "label": label, "heuristic": True}


def analyze_citations(citations: list[dict[str, Any]], results: list[Any]) -> None:
    """Analyze citations for contextual support.
    
    Modifies results in-place, adding:
    - weak_context_support flags to AuditResult objects
    - context dict to AuditResult with citation analysis
    """
    if not citations or not results:
        return
    
    # Process each citation
    for citation in citations:
        marker = citation.get("marker", "")
        sentence = citation.get("sentence", "")
        ref_index = citation.get("ref_index")
        
        if not sentence or ref_index is None or not isinstance(ref_index, int):
            continue
            
        # Check if ref_index is valid
        if ref_index < 0 or ref_index >= len(results):
            continue
        
        result = results[ref_index]
        if not hasattr(result, 'context'):
            # Initialize context if not present
            result.context = {}
        
        record = getattr(result, 'record', None)
        if not record:
            # No record to check against
            support_info = {"score": 0.0, "label": "WEAK", "heuristic": True}
            marker_key = f"citation_{len(result.context)}" if hasattr(result, 'context') and isinstance(result.context, dict) else "citation_0"
            if not hasattr(result, 'context'):
                result.context = {}
            result.context[marker_key] = support_info
            
            # Add weak context support flag if score is weak
            if support_info["score"] < 0.15:
                if not hasattr(result, 'flags') or not isinstance(result.flags, list):
                    result.flags = []
                if "weak_context_support" not in result.flags:
                    result.flags.append("weak_context_support")
            continue
        
        # Get title and abstract from record
        title = getattr(record, 'title', None)
        abstract = getattr(record, 'abstract', None)
        
        # Score support
        support_info = score_support(sentence, title or "", abstract or None)
        support_info["heuristic"] = True
        
        # Store in context
        if not hasattr(result, 'context'):
            result.context = {}
        # Use marker as key if available, otherwise generate one
        context_key = marker if marker else f"citation_{len(result.context)}"
        result.context[context_key] = support_info
        
        # Add weak context support flag if score is weak
        if support_info["score"] < 0.15:
            if not hasattr(result, 'flags') or not isinstance(result.flags, list):
                result.flags = []
            if "weak_context_support" not in result.flags:
                result.flags.append("weak_context_support")