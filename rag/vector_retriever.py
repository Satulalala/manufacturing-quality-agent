"""Semantic vector retrieval over the quality knowledge base."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Iterable, Mapping

from rag.embedding import DEFAULT_BASE_URL, DEFAULT_MODEL, embed_texts, embedding_identity
from rag.ingest import DEFAULT_DOCS_DIR, load_documents


DEFAULT_VECTOR_INDEX_PATH = Path(__file__).resolve().parent / "vector_index.json"
EmbedFn = Callable[[list[str]], list[list[float]]]


def _vector_matrix_is_valid(vectors: object, expected_count: int) -> bool:
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        return False
    if expected_count == 0:
        return True
    try:
        dimensions = {len(vector) for vector in vectors}
    except TypeError:
        return False
    return len(dimensions) == 1 and bool(next(iter(dimensions), 0))


def _same_corpus(
    cached_chunks: object,
    chunks: list[Mapping[str, object]],
) -> bool:
    if not isinstance(cached_chunks, list):
        return False
    try:
        cached = [
            (chunk.get("doc"), chunk.get("section"), chunk.get("text"))
            for chunk in cached_chunks
        ]
    except AttributeError:
        return False
    current = [
        (chunk.get("doc"), chunk.get("section"), chunk.get("text"))
        for chunk in chunks
    ]
    return cached == current


def _compatible_cached_vectors(
    index_path: str | Path,
    chunks: list[Mapping[str, object]],
    identity: Mapping[str, str],
) -> list[list[float]] | None:
    path = Path(index_path)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            index = json.load(handle)
        cached_identity = index.get("embedding_identity")
        default_identity = embedding_identity(base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL)
        identity_matches = cached_identity == dict(identity)
        # Old indexes predate identity metadata. Reuse them only under the
        # original default model and endpoint; other configurations re-embed.
        if cached_identity is None and dict(identity) == default_identity:
            identity_matches = True
        vectors = index.get("vectors")
        if (
            identity_matches
            and _same_corpus(index.get("chunks"), chunks)
            and _vector_matrix_is_valid(vectors, len(chunks))
        ):
            return vectors
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return None


def cosine_similarity(query: list[float], vectors: list[list[float]]) -> list[float]:
    """Cosine similarity of one query vector against many document vectors."""

    if not query:
        raise ValueError("query embedding is empty")
    if not _vector_matrix_is_valid(vectors, len(vectors)):
        raise ValueError("document embeddings must have one consistent non-empty dimension")
    dimension = len(query)
    if any(len(vector) != dimension for vector in vectors):
        raise ValueError("query and document embedding dimensions do not match")

    query_norm = math.sqrt(sum(value * value for value in query)) or 1.0
    scores: list[float] = []
    for vector in vectors:
        dot = sum(q * v for q, v in zip(query, vector))
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        scores.append(dot / (query_norm * norm))
    return scores


def _embedder_identity(embed_fn: EmbedFn | None) -> dict[str, str]:
    if embed_fn is None:
        return embedding_identity()
    function_name = getattr(embed_fn, "__qualname__", type(embed_fn).__qualname__)
    module_name = getattr(embed_fn, "__module__", type(embed_fn).__module__)
    return {"provider": "custom", "model": f"{module_name}.{function_name}"}


def build_vector_index(
    chunks: Iterable[Mapping[str, object]] | None = None,
    index_path: str | Path = DEFAULT_VECTOR_INDEX_PATH,
    embed_fn: EmbedFn | None = None,
) -> dict[str, object]:
    """Embed document chunks and persist corpus, vectors, and model identity."""

    chunk_list = list(chunks) if chunks is not None else load_documents(DEFAULT_DOCS_DIR)
    resolve_embed = embed_fn or embed_texts
    vectors = resolve_embed([str(chunk["text"]) for chunk in chunk_list])
    if not _vector_matrix_is_valid(vectors, len(chunk_list)):
        raise ValueError("embedding response count or dimensions do not match the document chunks")

    index = {
        "chunks": [dict(chunk) for chunk in chunk_list],
        "vectors": vectors,
        "embedding_identity": _embedder_identity(embed_fn),
    }
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
    """Rank chunks by cosine similarity; returns citation-compatible results."""

    if top_k <= 0 or not str(query).strip():
        return []

    chunk_list = (
        [dict(chunk) for chunk in chunks]
        if chunks is not None
        else load_documents(DEFAULT_DOCS_DIR)
    )
    if not chunk_list:
        return []

    resolve_embed = embed_fn or embed_texts
    identity = _embedder_identity(embed_fn)
    used_cache = False
    if embed_fn is None:
        vectors = _compatible_cached_vectors(index_path, chunk_list, identity)
        if vectors is not None:
            used_cache = True
        else:
            vectors = build_vector_index(chunks=chunk_list, index_path=index_path)["vectors"]
    else:
        vectors = resolve_embed([str(chunk["text"]) for chunk in chunk_list])

    if not _vector_matrix_is_valid(vectors, len(chunk_list)):
        raise ValueError("document embedding count or dimensions do not match the corpus")

    query_vectors = resolve_embed([query])
    if len(query_vectors) != 1 or not query_vectors[0]:
        raise ValueError("embedding service did not return one non-empty query vector")
    query_vector = query_vectors[0]

    if len(query_vector) != len(vectors[0]):
        if used_cache and embed_fn is None:
            # The same model name can point to changed weights; a dimension
            # mismatch invalidates the cache even if its metadata matched.
            vectors = build_vector_index(chunks=chunk_list, index_path=index_path)["vectors"]
            if len(query_vector) != len(vectors[0]):
                raise ValueError("query and refreshed document embedding dimensions do not match")
        else:
            raise ValueError("query and document embedding dimensions do not match")

    scores = cosine_similarity(query_vector, vectors)
    ranked = sorted(zip(chunk_list, scores), key=lambda item: item[1], reverse=True)
    results: list[dict[str, object]] = []
    for chunk, score in ranked:
        if score < min_score:
            break
        results.append(
            {
                "doc": chunk["doc"],
                "section": chunk["section"],
                "score": round(score, 4),
                "score_kind": "cosine_similarity",
                "sources": ["vector"],
                "source_scores": {"vector": round(score, 4)},
                "snippet": str(chunk.get("text", ""))[:240],
            }
        )
        if len(results) >= top_k:
            break
    return results
