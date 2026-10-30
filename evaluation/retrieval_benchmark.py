"""Compare the repository's lexical, vector, hybrid, and reranked retrieval."""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable, Mapping

from rag.embedding import embedding_identity
from rag.hybrid_retriever import retrieve_hybrid
from rag.ingest import DEFAULT_DOCS_DIR, load_documents
from rag.retriever import retrieve, retrieve_bm25
from rag.vector_retriever import build_vector_index, retrieve_vector


DEFAULT_CASES_PATH = Path(__file__).with_name("retrieval_cases.json")
VectorSearch = Callable[..., list[dict[str, object]]]


def load_cases(path: str | Path = DEFAULT_CASES_PATH) -> list[dict[str, str]]:
    """Load manually labeled questions with expected document and section."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    for index, case in enumerate(cases):
        if not all(case.get(key) for key in ("question", "expected_doc", "expected_section")):
            raise ValueError(f"case {index} needs question, expected_doc, and expected_section")
    return cases


def _relevant_rank(results: Iterable[Mapping[str, object]], case: Mapping[str, str]) -> int | None:
    expected = (case["expected_doc"], case["expected_section"])
    for rank, result in enumerate(results, start=1):
        if (str(result.get("doc", "")), str(result.get("section", ""))) == expected:
            return rank
    return None


def retrieval_metrics(
    ranked_by_case: Iterable[tuple[Iterable[Mapping[str, object]], Mapping[str, str]]],
    top_k: int,
    latencies_ms: Iterable[float],
) -> dict[str, float | int]:
    """Compute exact-section Recall@k, MRR, and mean query latency."""

    pairs = list(ranked_by_case)
    if not pairs:
        return {f"recall@{top_k}": 0.0, "mrr": 0.0, "avg_latency_ms": 0.0, "queries": 0}
    reciprocal_ranks = []
    hits = 0
    for results, case in pairs:
        rank = _relevant_rank(results, case)
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        if rank is not None and rank <= top_k:
            hits += 1
    latency_values = list(latencies_ms)
    return {
        f"recall@{top_k}": round(hits / len(pairs), 4),
        "mrr": round(sum(reciprocal_ranks) / len(pairs), 4),
        "avg_latency_ms": round(sum(latency_values) / len(latency_values), 3) if latency_values else 0.0,
        "queries": len(pairs),
    }


def _variant(metrics: dict[str, float | int]) -> dict[str, object]:
    return {"status": "ok", "metrics": metrics}


def run_benchmark(
    cases: Iterable[Mapping[str, str]] | None = None,
    chunks: Iterable[Mapping[str, object]] | None = None,
    top_k: int = 5,
    vector_retriever: VectorSearch | None = None,
    rerank_mode: str = "lexical",
    reranker_model: str | None = None,
) -> dict[str, object]:
    """Evaluate all variants on identical questions and a single chunk corpus.

    If vector retrieval fails for any case, vector-dependent variants are
    skipped for the whole benchmark. They never reuse BM25 output as a proxy.
    """

    resolved_cases = list(cases) if cases is not None else load_cases()
    chunk_list = [dict(chunk) for chunk in chunks] if chunks is not None else load_documents(DEFAULT_DOCS_DIR)
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    candidate_k = max(top_k * 4, top_k)
    for index, case in enumerate(resolved_cases):
        if not all(case.get(key) for key in ("question", "expected_doc", "expected_section")):
            raise ValueError(f"case {index} needs question, expected_doc, and expected_section")

    keyword_rankings: list[tuple[list[dict[str, object]], Mapping[str, str]]] = []
    bm25_rankings: list[tuple[list[dict[str, object]], Mapping[str, str]]] = []
    keyword_latencies: list[float] = []
    bm25_latencies: list[float] = []
    for case in resolved_cases:
        query = str(case["question"])
        start = time.perf_counter()
        keyword_results = retrieve(query, chunk_list, top_k=candidate_k)
        keyword_latencies.append((time.perf_counter() - start) * 1000)
        keyword_rankings.append((keyword_results, case))

        start = time.perf_counter()
        bm25_results = retrieve_bm25(query, chunk_list, top_k=candidate_k)
        bm25_latencies.append((time.perf_counter() - start) * 1000)
        bm25_rankings.append((bm25_results, case))

    variants: dict[str, object] = {
        "keyword": _variant(retrieval_metrics(keyword_rankings, top_k, keyword_latencies)),
        "bm25": _variant(retrieval_metrics(bm25_rankings, top_k, bm25_latencies)),
    }

    vector_search = vector_retriever or retrieve_vector
    vector_model = (
        embedding_identity()["model"]
        if vector_search is retrieve_vector
        else f"{getattr(vector_search, '__module__', type(vector_search).__module__)}."
        f"{getattr(vector_search, '__qualname__', type(vector_search).__qualname__)}"
    )
    vector_rankings: list[tuple[list[dict[str, object]], Mapping[str, str]]] = []
    hybrid_rankings: list[tuple[list[dict[str, object]], Mapping[str, str]]] = []
    reranked_rankings: list[tuple[list[dict[str, object]], Mapping[str, str]]] = []
    vector_latencies: list[float] = []
    hybrid_latencies: list[float] = []
    reranked_latencies: list[float] = []
    vector_failure: str | None = None
    reranker_failure: str | None = None

    with tempfile.TemporaryDirectory(prefix="rag-retrieval-benchmark-") as temp_dir:
        vector_index_path = Path(temp_dir) / "vector_index.json"
        try:
            if vector_search is retrieve_vector:
                build_vector_index(chunks=chunk_list, index_path=vector_index_path)

            for case in resolved_cases:
                query = str(case["question"])
                start = time.perf_counter()
                vector_results = vector_search(
                    query,
                    chunks=chunk_list,
                    top_k=candidate_k,
                    min_score=0.55,
                    index_path=vector_index_path,
                )
                vector_elapsed = (time.perf_counter() - start) * 1000
                vector_latencies.append(vector_elapsed)
                vector_rankings.append((vector_results, case))

                start = time.perf_counter()
                hybrid = retrieve_hybrid(
                    query,
                    chunk_list,
                    top_k=candidate_k,
                    vector_results=vector_results,
                )
                hybrid_elapsed = (time.perf_counter() - start) * 1000
                hybrid_latencies.append(vector_elapsed + hybrid_elapsed)
                hybrid_rankings.append((hybrid["results"], case))

                if reranker_failure is None:
                    start = time.perf_counter()
                    reranked = retrieve_hybrid(
                        query,
                        chunk_list,
                        top_k=candidate_k,
                        vector_results=vector_results,
                        rerank_mode=rerank_mode,
                        reranker_model=reranker_model,
                    )
                    rerank_elapsed = (time.perf_counter() - start) * 1000
                    if reranked["metadata"].get("reranker_mode") == "unavailable":
                        reranker_failure = str(reranked["metadata"].get("reranker_reason", "reranker unavailable"))
                    else:
                        reranked_latencies.append(vector_elapsed + rerank_elapsed)
                        reranked_rankings.append((reranked["results"], case))
        except Exception as error:
            vector_failure = f"{type(error).__name__}: {error}"

    if vector_failure:
        reason = f"向量或重排服务不可用：{vector_failure}"
        variants["vector"] = {"status": "skipped", "reason": reason}
        variants["hybrid"] = {"status": "skipped", "reason": reason}
        variants["hybrid_rerank"] = {
            "status": "skipped",
            "reason": reason,
            "reranker_mode": "unavailable",
            "reranker_is_neural": False,
        }
    else:
        variants["vector"] = _variant(retrieval_metrics(vector_rankings, top_k, vector_latencies))
        variants["hybrid"] = _variant(retrieval_metrics(hybrid_rankings, top_k, hybrid_latencies))
        if reranker_failure:
            variants["hybrid_rerank"] = {
                "status": "skipped",
                "reason": reranker_failure,
                "reranker_mode": "unavailable",
                "reranker_is_neural": False,
            }
        else:
            variants["hybrid_rerank"] = {
                **_variant(retrieval_metrics(reranked_rankings, top_k, reranked_latencies)),
                "reranker_mode": rerank_mode,
                "reranker_is_neural": rerank_mode == "cross_encoder",
            }

    missing_dependencies: list[str] = []
    if rerank_mode == "cross_encoder" and importlib.util.find_spec("sentence_transformers") is None:
        missing_dependencies.append("sentence-transformers")
    if rerank_mode == "cross_encoder" and not reranker_model:
        missing_dependencies.append("local CrossEncoder model path (RAG_RERANKER_MODEL or --reranker-model)")
    elif rerank_mode == "cross_encoder" and reranker_model and not Path(reranker_model).expanduser().is_dir():
        missing_dependencies.append(f"local CrossEncoder model directory not found: {reranker_model}")

    return {
        "top_k": top_k,
        "candidate_k": candidate_k,
        "case_count": len(resolved_cases),
        "corpus_chunks": len(chunk_list),
        "vector_embedding_model": vector_model,
        "expected_match": "exact doc + section",
        "variants": variants,
        "missing_dependencies": missing_dependencies,
    }


def _print_report(report: Mapping[str, object]) -> None:
    top_k = int(report["top_k"])
    print(
        f"Retrieval benchmark: {report['case_count']} cases, Recall@{top_k}, "
        f"candidate pool {report['candidate_k']}, exact doc + section"
    )
    print(f"{'variant':<18} {'status':<9} {'Recall@k':>9} {'MRR':>8} {'avg ms':>10}  mode")
    variants = report["variants"]
    labels = {
        "keyword": "keyword bigram",
        "bm25": "BM25",
        "vector": "pure vector",
        "hybrid": "BM25 + vector",
        "hybrid_rerank": "hybrid + rerank",
    }
    for key in ("keyword", "bm25", "vector", "hybrid", "hybrid_rerank"):
        entry = variants[key]
        if entry["status"] != "ok":
            print(f"{labels[key]:<18} {'skipped':<9} {'-':>9} {'-':>8} {'-':>10}  {entry['reason']}")
            continue
        metrics = entry["metrics"]
        mode = entry.get("reranker_mode", "")
        if key == "hybrid_rerank":
            mode = f"{mode}; neural={entry['reranker_is_neural']}"
        print(
            f"{labels[key]:<18} {'ok':<9} {metrics[f'recall@{top_k}']:>9.3f} "
            f"{metrics['mrr']:>8.3f} {metrics['avg_latency_ms']:>10.3f}  {mode}"
        )
    if report["missing_dependencies"]:
        print("Missing dependencies/config: " + ", ".join(report["missing_dependencies"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--rerank-mode", choices=("lexical", "cross_encoder"), default="lexical")
    parser.add_argument("--reranker-model", help="path to a local CrossEncoder model directory")
    parser.add_argument("--json", type=Path, help="optional path for the full JSON report")
    args = parser.parse_args()

    report = run_benchmark(
        cases=load_cases(args.cases),
        top_k=args.top_k,
        rerank_mode=args.rerank_mode,
        reranker_model=args.reranker_model,
    )
    _print_report(report)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json}")


if __name__ == "__main__":
    main()
