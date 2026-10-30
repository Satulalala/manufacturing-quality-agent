"""Agent tool for retrieving quality knowledge documents with citations."""

from __future__ import annotations

import os

from rag.hybrid_retriever import retrieve_hybrid
from rag.ingest import load_index
from rag.retriever import retrieve_bm25
from rag.vector_retriever import DEFAULT_VECTOR_INDEX_PATH, retrieve_vector


def retrieve_quality_documents(
    query: str,
    top_k: int = 3,
    use_vector: bool = True,
    rerank: bool = False,
    reranker_model: str | None = None,
) -> dict[str, object]:
    """Retrieve relevant chunks and expose the actual retrieval/rerank modes.

    Vector retrieval is part of the default BM25+vector hybrid. Set
    ``use_vector=False`` for deterministic BM25-only retrieval. Reranking is
    opt-in; without a configured model, requested reranking uses a clearly
    labeled offline lexical ranker. A CrossEncoder is loaded only from an
    explicitly supplied local directory.
    """

    base_metadata: dict[str, object] = {
        "retrieval_mode": "no_query" if not str(query).strip() else "no_results",
        "vector_status": "not_used",
        "fallback_reason": None,
        "reranker_mode": "none",
        "reranker_is_neural": False,
    }
    if not str(query).strip() or top_k <= 0:
        return {
            "status": "no_results",
            "query": query,
            "results": [],
            "metadata": base_metadata,
            "evidence": "未检索到与查询相关的知识库文档，不编造来源。",
        }

    documents = load_index()
    rerank_mode = "none"
    if rerank:
        resolved_model = reranker_model or os.environ.get("RAG_RERANKER_MODEL")
        rerank_mode = "cross_encoder" if resolved_model else "lexical"
    else:
        resolved_model = reranker_model or os.environ.get("RAG_RERANKER_MODEL")

    if use_vector:
        search = retrieve_hybrid(
            query,
            documents,
            top_k=top_k,
            vector_retriever=retrieve_vector,
            rerank_mode=rerank_mode,
            reranker_model=resolved_model,
        )
        results = search["results"]
        metadata = search["metadata"]
    else:
        results = retrieve_bm25(query, documents, top_k=top_k)
        metadata = dict(base_metadata)
        metadata["retrieval_mode"] = "bm25"
        metadata["vector_status"] = "not_used"
        if rerank_mode != "none":
            # BM25-only callers may still request the same optional reranker.
            search = retrieve_hybrid(
                query,
                documents,
                top_k=top_k,
                vector_results=[],
                rerank_mode=rerank_mode,
                reranker_model=resolved_model,
            )
            results = search["results"]
            metadata.update(search["metadata"])
            metadata["retrieval_mode"] = "bm25"
            metadata["vector_status"] = "not_used"

    if not results:
        return {
            "status": "no_results",
            "query": query,
            "results": [],
            "metadata": metadata,
            "evidence": "未检索到与查询相关的知识库文档，不编造来源。",
        }

    mode_label = str(metadata.get("retrieval_mode", "unknown"))
    reranker_label = str(metadata.get("reranker_mode", "none"))
    evidence = f"{DEFAULT_VECTOR_INDEX_PATH.name}（{mode_label}；reranker={reranker_label}）："
    evidence += "、".join(f"{item['doc']}（{item['section']}）" for item in results)
    return {
        "status": "success",
        "query": query,
        "results": results,
        "metadata": metadata,
        "evidence": evidence,
    }
