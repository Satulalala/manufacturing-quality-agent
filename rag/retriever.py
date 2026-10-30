"""Deterministic lexical retrieval over the quality index.

``retrieve`` retains the original character-bigram behavior for compatibility.
``retrieve_bm25`` provides a dependency-free BM25 baseline with Chinese
character n-grams and intact Latin/alphanumeric identifiers such as ``W-07``.
"""

from __future__ import annotations

import re
import math
from typing import Iterable, Mapping


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", str(text).lower())
    return {compact[index : index + 2] for index in range(len(compact) - 1)}


def score(query: str, text: str) -> float:
    """Return the fraction of query bigrams present in the text."""

    query_grams = _bigrams(query)
    if not query_grams:
        return 0.0
    text_grams = _bigrams(text)
    if not text_grams:
        return 0.0
    return len(query_grams & text_grams) / len(query_grams)


def retrieve(
    query: str,
    documents: Iterable[Mapping[str, object]],
    top_k: int = 3,
    min_score: float = 0.05,
) -> list[dict[str, object]]:
    """Rank document chunks by query-bigram overlap and return the best."""

    if top_k <= 0 or not str(query).strip():
        return []

    scored = [
        (float(score(query, str(document.get("text", "")))), document)
        for document in documents
    ]
    results: list[dict[str, object]] = []
    for rank, (rank_score, document) in enumerate(sorted(scored, key=lambda item: item[0], reverse=True)):
        if rank_score < min_score:
            break
        results.append(
            {
                "doc": document["doc"],
                "section": document["section"],
                "score": round(rank_score, 4),
                "snippet": str(document.get("text", ""))[:240],
            }
        )
        if len(results) >= top_k:
            break
    return results


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*|[\u3400-\u4dbf\u4e00-\u9fff]+", re.IGNORECASE)
_HAN_RE = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff]+$")


def tokenize(text: str) -> list[str]:
    """Split text into searchable terms without requiring an offline segmenter.

    Latin words and codes remain whole (and codes also get a separator-free
    alias). Chinese runs emit overlapping bigrams; one-character runs remain
    searchable while longer text avoids noisy matches on common characters.
    """

    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(str(text).lower()):
        token = match.group(0)
        if _HAN_RE.fullmatch(token):
            if len(token) == 1:
                tokens.append(token)
            else:
                tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
            continue
        tokens.append(token)
        compact = re.sub(r"[-_.]", "", token)
        if compact != token:
            tokens.append(compact)
    return tokens


def retrieve_bm25(
    query: str,
    documents: Iterable[Mapping[str, object]],
    top_k: int = 3,
    min_score: float = 0.0,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[dict[str, object]]:
    """Rank chunks with BM25 using title/section plus body text."""

    if top_k <= 0 or not str(query).strip():
        return []

    query_terms = set(tokenize(query))
    if not query_terms:
        return []

    corpus = list(documents)
    tokenized = [
        tokenize(f"{document.get('section', '')} {document.get('text', '')}")
        for document in corpus
    ]
    if not corpus:
        return []

    document_frequency: dict[str, int] = {}
    for terms in tokenized:
        for term in set(terms):
            document_frequency[term] = document_frequency.get(term, 0) + 1

    average_length = sum(map(len, tokenized)) / len(tokenized) or 1.0
    document_count = len(corpus)
    scored: list[tuple[float, int, Mapping[str, object]]] = []
    for index, (document, terms) in enumerate(zip(corpus, tokenized)):
        frequencies: dict[str, int] = {}
        for term in terms:
            frequencies[term] = frequencies.get(term, 0) + 1

        length = len(terms)
        rank_score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            df = document_frequency.get(term, 0)
            inverse_frequency = math.log1p((document_count - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1 - b + b * length / average_length)
            rank_score += inverse_frequency * (frequency * (k1 + 1)) / denominator
        if rank_score >= min_score and rank_score > 0:
            scored.append((rank_score, index, document))

    scored.sort(key=lambda item: (-item[0], item[1]))
    results: list[dict[str, object]] = []
    for rank_score, _, document in scored[:top_k]:
        results.append(
            {
                "doc": document["doc"],
                "section": document["section"],
                "score": round(rank_score, 6),
                "score_kind": "bm25",
                "sources": ["bm25"],
                "source_scores": {"bm25": round(rank_score, 6)},
                "snippet": str(document.get("text", ""))[:240],
            }
        )
    return results
