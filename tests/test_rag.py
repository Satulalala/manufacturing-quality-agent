import unittest

from agent.workflow import QualityAgent
from data.demo_data import generate_records
from rag.ingest import build_index, load_documents, load_index
from rag.retriever import retrieve
from tools.knowledge_tool import retrieve_quality_documents


class RagTests(unittest.TestCase):
    def test_ingest_loads_three_documents_with_sections(self):
        chunks = load_documents()

        doc_names = {chunk["doc"] for chunk in chunks}
        self.assertEqual(
            doc_names,
            {"quality_standard.md", "defect_code_manual.md", "maintenance_cases.md"},
        )
        self.assertTrue(all(chunk["section"] and chunk["text"] for chunk in chunks))
        self.assertTrue(any(chunk["section"].startswith("torque_low") for chunk in chunks))

    def test_index_round_trip_preserves_documents(self):
        build_index()

        documents = load_index()

        self.assertTrue(documents)
        self.assertEqual(documents, load_documents())

    def test_retrieve_finds_torque_low_manual(self):
        documents = load_documents()

        results = retrieve("torque_low", documents, top_k=3)

        self.assertTrue(results)
        self.assertEqual(results[0]["doc"], "defect_code_manual.md")

    def test_retrieve_finds_w07_case(self):
        documents = load_documents()

        results = retrieve("W-07 工位扭矩不良", documents, top_k=5)

        self.assertIn(
            "maintenance_cases.md",
            {result["doc"] for result in results},
        )

    def test_retrieve_returns_empty_for_unrelated_query(self):
        documents = load_documents()

        results = retrieve("量子计算芯片设计", documents)

        self.assertEqual(results, [])

    def test_retrieve_is_deterministic(self):
        documents = load_documents()

        first = retrieve("扭矩偏低 排查", documents)
        second = retrieve("扭矩偏低 排查", documents)

        self.assertEqual(first, second)

    def test_knowledge_tool_reports_no_results_honestly(self):
        result = retrieve_quality_documents("量子计算芯片设计")

        self.assertEqual(result["status"], "no_results")
        self.assertEqual(result["results"], [])
        self.assertIn("未检索到", result["evidence"])

    def test_knowledge_tool_returns_structured_results(self):
        result = retrieve_quality_documents("torque_low 扭矩偏低")

        self.assertEqual(result["status"], "success")
        self.assertIn("query", result)
        self.assertTrue(result["results"])
        self.assertTrue(all({"doc", "section", "score", "snippet"}.issubset(item) for item in result["results"]))
        self.assertIn("evidence", result)

    def test_agent_report_includes_knowledge_refs(self):
        agent = QualityAgent(generate_records(2400, seed=42))
        report = agent.answer("请分析 2026-01-01 到 2026-01-31 A产线的不良率异常")

        self.assertIn("knowledge_refs", report)
        self.assertIn("knowledge_summary", report)
        self.assertIn("retrieve_quality_documents", [step["tool"] for step in report["trace"]])


if __name__ == "__main__":
    unittest.main()
