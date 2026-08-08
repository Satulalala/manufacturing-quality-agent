"""Deterministic, dependency-free retrieval over the quality index.

Queries and chunks are compared on character bigrams: the more query bigrams a
chunk contains, the higher its score. This is a keyword-style retriever — no
embeddings, no external services — which is enough for the small fixed corpus
and stays fully reproducible.
"""

from __future__ import annotations

import re
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
                "snippet": str(document.get("text", ""))[:80],
            }
        )
        if len(results) >= top_k:
            break
    return results
