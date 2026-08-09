"""Semantic vector retrieval over the quality knowledge base.

Chunks are embedded once into ``rag/vector_index.json``; a query is embedded
at request time and ranked by cosine similarity against every chunk. The
output shape mirrors the bigram retriever (doc/section/score/snippet) so the
Agent-facing tool can switch between them transparently.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Iterable, Mapping

from rag.embedding import OllamaUnavailable, embed_texts
from rag.ingest import DEFAULT_DOCS_DIR, DEFAULT_INDEX_PATH, load_documents


DEFAULT_VECTOR_INDEX_PATH = Path(__file__).resolve().parent / "vector_index.json"
EmbedFn = Callable[[list[str]], list[list[float]]]


def cosine_similarity(query: list[float], vectors: list[list[float]]) -> list[float]:
    """Cosine similarity of one query vector against many document vectors."""

    query_norm = math.sqrt(sum(value * value for value in query)) or 1.0
    scores: list[float] = []
    for vector in vectors:
        dot = sum(q * v for q, v in zip(query, vector))
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        scores.append(dot / (query_norm * norm))
    return scores


def build_vector_index(
    chunks: Iterable[Mapping[str, object]] | None = None,
    index_path: str | Path = DEFAULT_VECTOR_INDEX_PATH,
    embed_fn: EmbedFn | None = None,
) -> dict[str, object]:
    """Embed document chunks and persist ``{chunks, vectors}``."""

    chunk_list = list(chunks) if chunks is not None else load_documents(DEFAULT_DOCS_DIR)
    resolve_embed = embed_fn or embed_texts
    vectors = resolve_embed([str(chunk["text"]) for chunk in chunk_list])

    index = {"chunks": [dict(chunk) for chunk in chunk_list], "vectors": vectors}
    destination = Path(index_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return index


def load_index(index_path: str | Path = DEFAULT_VECTOR_INDEX_PATH) -> dict[str, object]:
    """Load the vector index; rebuild it on first use."""

    path = Path(index_path)
    if not path.exists():
        return build_vector_index(index_path=path)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def retrieve_vector(
    query: str,
    chunks: Iterable[Mapping[str, object]] | None = None,
    top_k: int = 3,
    min_score: float = 0.55,
    embed_fn: EmbedFn | None = None,
    index_path: str | Path = DEFAULT_VECTOR_INDEX_PATH,
) -> list[dict[str, object]]:
    """Rank chunks by cosine similarity; returns bigram-shaped results."""

    resolve_embed = embed_fn or embed_texts
    if chunks is not None:
        chunk_list = list(chunks)
        vectors = resolve_embed([str(chunk["text"]) for chunk in chunk_list])
    else:
        index = load_index(index_path)
        chunk_list = [dict(chunk) for chunk in index["chunks"]]
        vectors = index["vectors"]

    query_vector = resolve_embed([query])[0]
    scores = cosine_similarity(query_vector, vectors)

    ranked = sorted(
        zip(chunk_list, scores),
        key=lambda item: item[1],
        reverse=True,
    )
    results: list[dict[str, object]] = []
    for chunk, score in ranked:
        if score < min_score:
            break
        results.append(
            {
                "doc": chunk["doc"],
                "section": chunk["section"],
                "score": round(score, 4),
                "snippet": str(chunk.get("text", ""))[:240],
            }
        )
        if len(results) >= top_k:
            break
    return results
