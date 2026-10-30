"""BM25 plus vector retrieval, reciprocal-rank fusion, and optional reranking."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Mapping

from rag.retriever import retrieve_bm25, tokenize
from rag.vector_retriever import retrieve_vector


VectorSearch = Callable[..., list[dict[str, object]]]
DEFAULT_RRF_CONSTANT = 60


def _identity(result: Mapping[str, object]) -> tuple[str, str]:
    return str(result.get("doc", "")), str(result.get("section", ""))


def fuse_ranked_results(
    bm25_results: Iterable[Mapping[str, object]],
    vector_results: Iterable[Mapping[str, object]],
    top_k: int = 3,
    rrf_constant: int = DEFAULT_RRF_CONSTANT,
) -> list[dict[str, object]]:
    """Merge ranked lists with RRF and expose each lane's contribution."""

    if top_k <= 0:
        return []

    fused: dict[tuple[str, str], dict[str, object]] = {}
    for source, ranked in (("bm25", bm25_results), ("vector", vector_results)):
        for rank, item in enumerate(ranked, start=1):
            key = _identity(item)
            if not key[0] and not key[1]:
                continue
            contribution = 1.0 / (rrf_constant + rank)
            current = fused.get(key)
            if current is None:
                current = {
                    "doc": item.get("doc", ""),
                    "section": item.get("section", ""),
                    "snippet": str(item.get("snippet", "")),
                    "score": 0.0,
                    "score_kind": "rrf",
                    "sources": [],
                    "source_scores": {},
                }
                fused[key] = current
            elif not current["snippet"] and item.get("snippet"):
                current["snippet"] = str(item["snippet"])
            current["score"] = float(current["score"]) + contribution
            current["sources"].append(source)
            current["source_scores"][source] = round(contribution, 8)

    ordered = sorted(fused.values(), key=lambda item: (-float(item["score"]), str(item["doc"]), str(item["section"])))
    for item in ordered:
        item["score"] = round(float(item["score"]), 8)
    return ordered[:top_k]


def _lexical_rerank(query: str, results: list[dict[str, object]]) -> list[dict[str, object]]:
    query_terms = set(tokenize(query))
    scored: list[tuple[float, int, dict[str, object]]] = []
    for index, result in enumerate(results):
        text = f"{result.get('section', '')} {result.get('snippet', '')}"
        terms = set(tokenize(text))
        lexical_score = len(query_terms & terms) / len(query_terms) if query_terms else 0.0
        scored.append((lexical_score, index, result))

    scored.sort(key=lambda item: (-item[0], item[1]))
    ranked: list[dict[str, object]] = []
    for rank, (lexical_score, _, result) in enumerate(scored, start=1):
        item = dict(result)
        item["rerank_score"] = round(lexical_score, 6)
        item["rerank_rank"] = rank
        ranked.append(item)
    return ranked


@lru_cache(maxsize=1)
def _load_cross_encoder(model_path: str):
    """Load one local CrossEncoder and reuse it across queries."""
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as error:
        raise RuntimeError("sentence-transformers is not installed") from error

    return CrossEncoder(model_path, local_files_only=True)


def _cross_encoder_rerank(
    query: str,
    results: list[dict[str, object]],
    model_path: str,
) -> list[dict[str, object]]:
    """Run an explicitly configured local CrossEncoder without model downloads."""

    path = Path(model_path).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"CrossEncoder model directory does not exist: {path}")

    model = _load_cross_encoder(str(path))
    pairs = [(query, f"{item.get('section', '')}\n{item.get('snippet', '')}") for item in results]
    scores = model.predict(pairs, show_progress_bar=False)
    if len(scores) != len(results):
        raise ValueError("CrossEncoder returned a different number of scores than candidates")
    ranked = []
    for original_rank, (result, score) in enumerate(zip(results, scores), start=1):
        item = dict(result)
        item["rerank_score"] = float(score)
        item["original_rank"] = original_rank
        ranked.append(item)
    ranked.sort(key=lambda item: (-float(item["rerank_score"]), int(item["original_rank"])))
    for rank, item in enumerate(ranked, start=1):
        item["rerank_rank"] = rank
    return ranked


def _apply_reranker(
    query: str,
    results: list[dict[str, object]],
    rerank_mode: str,
    reranker_model: str | None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    metadata: dict[str, object] = {
        "reranker_mode": "none",
        "reranker_is_neural": False,
    }
    if rerank_mode == "none" or not results:
        return results, metadata
    if rerank_mode == "lexical":
        return _lexical_rerank(query, results), {
            "reranker_mode": "lexical",
            "reranker_is_neural": False,
        }
    if rerank_mode != "cross_encoder":
        return results, {
            "reranker_mode": "unavailable",
            "reranker_is_neural": False,
            "reranker_reason": f"unsupported rerank mode: {rerank_mode}",
        }
    if not reranker_model:
        return results, {
            "reranker_mode": "unavailable",
            "reranker_is_neural": False,
            "reranker_reason": "cross_encoder requires an explicit local model path",
        }
    try:
        ranked = _cross_encoder_rerank(query, results, reranker_model)
    except Exception as error:
        return results, {
            "reranker_mode": "unavailable",
            "reranker_is_neural": False,
            "reranker_reason": f"{type(error).__name__}: {error}",
        }
    return ranked, {
        "reranker_mode": "cross_encoder",
        "reranker_is_neural": True,
        "reranker_model": str(Path(reranker_model).expanduser().resolve()),
    }


def retrieve_hybrid(
    query: str,
    chunks: Iterable[Mapping[str, object]],
    top_k: int = 3,
    vector_retriever: VectorSearch | None = None,
    vector_results: Iterable[Mapping[str, object]] | None = None,
    rerank_mode: str = "none",
    reranker_model: str | None = None,
    index_path: str | Path | None = None,
) -> dict[str, object]:
    """Retrieve by BM25 and vectors, falling back explicitly when vectors fail."""

    metadata: dict[str, object] = {
        "retrieval_mode": "hybrid",
        "vector_status": "available",
        "fallback_reason": None,
        "reranker_mode": "none",
        "reranker_is_neural": False,
    }
    if not str(query).strip():
        metadata["retrieval_mode"] = "no_query"
        return {"results": [], "metadata": metadata}
    if top_k <= 0:
        metadata["retrieval_mode"] = "no_results"
        return {"results": [], "metadata": metadata}

    chunk_list = list(chunks)
    candidate_k = max(top_k * 4, top_k)
    bm25_results = retrieve_bm25(query, chunk_list, top_k=candidate_k)
    resolved_vector_results: list[Mapping[str, object]] = []
    if vector_results is not None:
        resolved_vector_results = list(vector_results)
    else:
        search = vector_retriever or retrieve_vector
        try:
            kwargs: dict[str, object] = {
                "chunks": chunk_list,
                "top_k": candidate_k,
                "min_score": 0.55,
            }
            if index_path is not None:
                kwargs["index_path"] = index_path
            resolved_vector_results = list(search(query, **kwargs))
        except Exception as error:
            metadata["retrieval_mode"] = "bm25_fallback"
            metadata["vector_status"] = "unavailable"
            metadata["fallback_reason"] = f"{type(error).__name__}: {error}"

    if metadata["vector_status"] == "unavailable":
        merged = bm25_results[:candidate_k]
    else:
        merged = fuse_ranked_results(bm25_results, resolved_vector_results, top_k=candidate_k)

    merged, reranker_metadata = _apply_reranker(query, merged, rerank_mode, reranker_model)
    metadata.update(reranker_metadata)
    return {"results": merged[:top_k], "metadata": metadata}
