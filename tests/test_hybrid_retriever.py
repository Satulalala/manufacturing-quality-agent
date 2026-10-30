import unittest
import sys
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rag.embedding import OllamaUnavailable
from rag.hybrid_retriever import fuse_ranked_results, retrieve_hybrid
from rag.retriever import retrieve_bm25
from tools.knowledge_tool import retrieve_quality_documents
from evaluation.retrieval_benchmark import retrieval_metrics, run_benchmark


CHUNKS = [
    {
        "doc": "defect_code_manual.md",
        "section": "torque_low 扭矩偏低",
        "text": "扭矩偏低：装配扭矩低于规格下限，检查扭矩枪。",
    },
    {
        "doc": "maintenance_cases.md",
        "section": "案例一：W-07 扭矩偏低批量不良",
        "text": "W-07 工位扭矩枪校准漂移，造成螺丝拧不紧。",
    },
    {
        "doc": "quality_standard.md",
        "section": "电池绝缘检查",
        "text": "电池绝缘电阻应符合技术标准。",
    },
]


class BM25Tests(unittest.TestCase):
    def test_matches_chinese_terms_and_alphanumeric_workstation_codes(self):
        chinese = retrieve_bm25("扭矩偏低", CHUNKS, top_k=3)
        code = retrieve_bm25("W-07 校准漂移", CHUNKS, top_k=3)

        self.assertEqual(chinese[0]["doc"], "defect_code_manual.md")
        self.assertEqual(code[0]["section"], "案例一：W-07 扭矩偏低批量不良")
        self.assertIn("bm25", code[0]["sources"])

    def test_empty_query_and_nonpositive_top_k_return_no_results(self):
        self.assertEqual(retrieve_bm25("   ", CHUNKS), [])
        self.assertEqual(retrieve_bm25("扭矩", CHUNKS, top_k=0), [])
        self.assertEqual(retrieve_bm25("扭矩", CHUNKS, top_k=-1), [])
        self.assertEqual(retrieve_bm25("量子计算芯片设计", CHUNKS), [])


class HybridRetrieverTests(unittest.TestCase):
    def test_mrr_uses_relevant_rank_across_candidate_pool(self):
        case = {"expected_doc": "target.md", "expected_section": "target"}
        ranked = [
            {"doc": "distractor.md", "section": "other"},
            {"doc": "target.md", "section": "target"},
        ]

        metrics = retrieval_metrics([(ranked, case)], top_k=1, latencies_ms=[1.0])

        self.assertEqual(metrics["recall@1"], 0.0)
        self.assertEqual(metrics["mrr"], 0.5)

    def test_rrf_fuses_both_ranks_and_reports_sources_and_scores(self):
        bm25 = [
            {"doc": "a.md", "section": "a", "score": 2.0, "snippet": "a"},
            {"doc": "b.md", "section": "b", "score": 1.0, "snippet": "b"},
        ]
        vector = [
            {"doc": "b.md", "section": "b", "score": 0.9, "snippet": "b"},
            {"doc": "c.md", "section": "c", "score": 0.8, "snippet": "c"},
        ]

        results = fuse_ranked_results(bm25, vector, top_k=3)

        self.assertEqual(results[0]["doc"], "b.md")
        self.assertEqual(results[0]["sources"], ["bm25", "vector"])
        self.assertEqual(set(results[0]["source_scores"]), {"bm25", "vector"})
        self.assertAlmostEqual(results[0]["score"], 1 / 62 + 1 / 61)
        self.assertEqual(results[0]["score_kind"], "rrf")

    def test_lexical_rerank_is_not_reported_as_neural(self):
        vector = [
            {"doc": "defect_code_manual.md", "section": "torque_low 扭矩偏低", "score": 0.9, "snippet": CHUNKS[0]["text"]},
            {"doc": "maintenance_cases.md", "section": "案例一：W-07 扭矩偏低批量不良", "score": 0.8, "snippet": CHUNKS[1]["text"]},
        ]

        result = retrieve_hybrid(
            "W-07 校准漂移",
            CHUNKS,
            top_k=2,
            vector_results=vector,
            rerank_mode="lexical",
        )

        self.assertEqual(result["results"][0]["doc"], "maintenance_cases.md")
        self.assertEqual(result["metadata"]["reranker_mode"], "lexical")
        self.assertFalse(result["metadata"]["reranker_is_neural"])

    def test_cross_encoder_uses_only_the_explicit_local_model_path(self):
        calls = {}

        class FakeCrossEncoder:
            def __init__(self, model_path, **kwargs):
                calls["model_path"] = model_path
                calls.update(kwargs)

            def predict(self, pairs, show_progress_bar=False):
                return [0.9 if "W-07" in document else 0.1 for _, document in pairs]

        vector = [
            {"doc": "defect_code_manual.md", "section": "torque_low 扭矩偏低", "score": 0.9, "snippet": CHUNKS[0]["text"]},
            {"doc": "maintenance_cases.md", "section": "案例一：W-07 扭矩偏低批量不良", "score": 0.8, "snippet": CHUNKS[1]["text"]},
        ]
        with TemporaryDirectory() as model_dir, patch.dict(
            sys.modules,
            {"sentence_transformers": SimpleNamespace(CrossEncoder=FakeCrossEncoder)},
        ):
            result = retrieve_hybrid(
                "W-07 校准漂移",
                CHUNKS,
                top_k=2,
                vector_results=vector,
                rerank_mode="cross_encoder",
                reranker_model=model_dir,
            )

        self.assertEqual(result["metadata"]["reranker_mode"], "cross_encoder")
        self.assertTrue(result["metadata"]["reranker_is_neural"])
        self.assertTrue(calls["local_files_only"])
        self.assertEqual(result["results"][0]["doc"], "maintenance_cases.md")

    def test_blank_query_does_not_call_vector_service(self):
        def should_not_run(*args, **kwargs):
            raise AssertionError("vector service must not run for an empty query")

        result = retrieve_hybrid("  ", CHUNKS, vector_retriever=should_not_run)

        self.assertEqual(result["results"], [])
        self.assertEqual(result["metadata"]["retrieval_mode"], "no_query")

    def test_nonpositive_top_k_does_not_call_vector_service(self):
        def should_not_run(*args, **kwargs):
            raise AssertionError("vector service must not run when top_k is zero")

        result = retrieve_hybrid("扭矩", CHUNKS, top_k=0, vector_retriever=should_not_run)

        self.assertEqual(result["results"], [])
        self.assertEqual(result["metadata"]["retrieval_mode"], "no_results")

    def test_vector_failure_is_explicit_bm25_fallback(self):
        def unavailable(*args, **kwargs):
            raise OllamaUnavailable("offline for test")

        with patch("tools.knowledge_tool.load_index", return_value=CHUNKS), patch(
            "tools.knowledge_tool.retrieve_vector", side_effect=unavailable
        ):
            result = retrieve_quality_documents("扭矩偏低")

        self.assertEqual(result["metadata"]["retrieval_mode"], "bm25_fallback")
        self.assertEqual(result["metadata"]["vector_status"], "unavailable")
        self.assertIn("offline for test", result["metadata"]["fallback_reason"])
        self.assertTrue(result["results"])

    def test_fallback_lexical_reranker_sees_candidates_beyond_top_k(self):
        bm25_candidates = [
            {"doc": "first.md", "section": "first", "score": 3.0, "snippet": "扭矩偏低"},
            {"doc": "second.md", "section": "second", "score": 2.0, "snippet": "W-07 工位扭矩枪校准漂移"},
        ]

        def unavailable(*args, **kwargs):
            raise OllamaUnavailable("offline for test")

        with patch("rag.hybrid_retriever.retrieve_bm25", return_value=bm25_candidates):
            result = retrieve_hybrid(
                "W-07 校准漂移",
                CHUNKS,
                top_k=1,
                vector_retriever=unavailable,
                rerank_mode="lexical",
            )

        self.assertEqual(result["results"][0]["doc"], "second.md")
        self.assertEqual(result["metadata"]["retrieval_mode"], "bm25_fallback")
        self.assertEqual(result["metadata"]["reranker_mode"], "lexical")

    def test_knowledge_tool_defaults_to_hybrid_with_compatible_result_fields(self):
        vector_hit = {
            "doc": "maintenance_cases.md",
            "section": "案例一：W-07 扭矩偏低批量不良",
            "score": 0.9,
            "snippet": CHUNKS[1]["text"],
        }
        with patch("tools.knowledge_tool.load_index", return_value=CHUNKS), patch(
            "tools.knowledge_tool.retrieve_vector", return_value=[vector_hit]
        ):
            result = retrieve_quality_documents("W-07 扭矩偏低")

        self.assertEqual(result["metadata"]["retrieval_mode"], "hybrid")
        self.assertEqual(result["metadata"]["vector_status"], "available")
        self.assertTrue(any("vector" in item["sources"] for item in result["results"]))
        self.assertTrue(
            all({"doc", "section", "snippet", "score"}.issubset(item) for item in result["results"])
        )

    def test_use_vector_false_keeps_bm25_only_compatibility(self):
        with patch("tools.knowledge_tool.load_index", return_value=CHUNKS), patch(
            "tools.knowledge_tool.retrieve_vector", side_effect=AssertionError("must not call")
        ):
            result = retrieve_quality_documents("W-07", use_vector=False)

        self.assertEqual(result["metadata"]["retrieval_mode"], "bm25")
        self.assertEqual(result["results"][0]["section"], "案例一：W-07 扭矩偏低批量不良")

    def test_benchmark_skips_vector_variants_when_service_fails(self):
        def unavailable(*args, **kwargs):
            raise OllamaUnavailable("offline for test")

        case = {
            "question": "W-07 扭矩偏低",
            "expected_doc": "maintenance_cases.md",
            "expected_section": "案例一：W-07 扭矩偏低批量不良",
        }
        report = run_benchmark(
            cases=[case],
            chunks=CHUNKS,
            vector_retriever=unavailable,
            top_k=2,
        )

        self.assertEqual(report["variants"]["bm25"]["status"], "ok")
        for name in ("vector", "hybrid", "hybrid_rerank"):
            self.assertEqual(report["variants"][name]["status"], "skipped")
            self.assertIn("offline for test", report["variants"][name]["reason"])

    def test_benchmark_reports_lexical_rerank_as_non_neural(self):
        case = {
            "question": "W-07 扭矩偏低",
            "expected_doc": "maintenance_cases.md",
            "expected_section": "案例一：W-07 扭矩偏低批量不良",
        }
        vector_hit = {
            "doc": case["expected_doc"],
            "section": case["expected_section"],
            "score": 0.9,
            "snippet": CHUNKS[1]["text"],
        }

        report = run_benchmark(
            cases=[case],
            chunks=CHUNKS,
            vector_retriever=lambda *args, **kwargs: [vector_hit],
            rerank_mode="lexical",
            top_k=1,
        )

        self.assertEqual(report["variants"]["vector"]["status"], "ok")
        self.assertEqual(report["variants"]["hybrid"]["status"], "ok")
        self.assertEqual(report["variants"]["hybrid_rerank"]["status"], "ok")
        self.assertEqual(report["variants"]["hybrid_rerank"]["reranker_mode"], "lexical")
        self.assertFalse(report["variants"]["hybrid_rerank"]["reranker_is_neural"])

    def test_unconfigured_neural_reranker_skips_only_reranked_variant(self):
        case = {
            "question": "W-07 扭矩偏低",
            "expected_doc": "maintenance_cases.md",
            "expected_section": "案例一：W-07 扭矩偏低批量不良",
        }
        vector_hit = {
            "doc": case["expected_doc"],
            "section": case["expected_section"],
            "score": 0.9,
            "snippet": CHUNKS[1]["text"],
        }

        report = run_benchmark(
            cases=[case],
            chunks=CHUNKS,
            vector_retriever=lambda *args, **kwargs: [vector_hit],
            rerank_mode="cross_encoder",
            top_k=2,
        )

        self.assertEqual(report["variants"]["vector"]["status"], "ok")
        self.assertEqual(report["variants"]["hybrid"]["status"], "ok")
        self.assertEqual(report["variants"]["hybrid_rerank"]["status"], "skipped")
        self.assertIn("explicit local model path", report["variants"]["hybrid_rerank"]["reason"])
        self.assertFalse(report["variants"]["hybrid_rerank"]["reranker_is_neural"])
        self.assertTrue(any("local CrossEncoder model path" in item for item in report["missing_dependencies"]))


if __name__ == "__main__":
    unittest.main()
