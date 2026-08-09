"""Agent tool for retrieving quality knowledge documents with citations.

Semantic vector retrieval is preferred (local Ollama embedding); if the
embedding server is unreachable or produces no results, the deterministic
bigram retriever takes over so behaviour never degrades below the baseline.
"""

from __future__ import annotations

from rag.embedding import OllamaUnavailable
from rag.ingest import load_index
from rag.retriever import retrieve
from rag.vector_retriever import DEFAULT_VECTOR_INDEX_PATH, retrieve_vector


def retrieve_quality_documents(query: str, top_k: int = 3) -> dict[str, object]:
    """Retrieve relevant knowledge chunks or state honestly that none matched."""

    results: list[dict[str, object]] = []
    vector_mode = False
    try:
        results = retrieve_vector(query, top_k=top_k)
        vector_mode = True
    except OllamaUnavailable:
        results = retrieve(query, load_index(), top_k=top_k)
    except Exception:
        results = retrieve(query, load_index(), top_k=top_k)

    if not results:
        return {
            "status": "no_results",
            "query": query,
            "results": [],
            "evidence": "未检索到与查询相关的知识库文档，不编造来源。",
        }

    mode = "vector" if vector_mode else "bigram"
    return {
        "status": "success",
        "query": query,
        "results": results,
        "evidence": (
            f"{DEFAULT_VECTOR_INDEX_PATH.name}（{mode}）："
            + "、".join(f"{item['doc']}（{item['section']}）" for item in results)
        ),
    }
