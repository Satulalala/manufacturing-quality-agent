"""Agent tool for retrieving quality knowledge documents with citations."""

from __future__ import annotations

from rag.ingest import load_index
from rag.retriever import retrieve


def retrieve_quality_documents(query: str, top_k: int = 3) -> dict[str, object]:
    """Retrieve relevant knowledge chunks or state honestly that none matched."""

    results = retrieve(query, load_index(), top_k=top_k)

    if not results:
        return {
            "status": "no_results",
            "query": query,
            "results": [],
            "evidence": "未检索到与查询相关的知识库文档，不编造来源。",
        }

    return {
        "status": "success",
        "query": query,
        "results": results,
        "evidence": "rag/index.json：" + "、".join(f"{item['doc']}（{item['section']}）" for item in results),
    }
