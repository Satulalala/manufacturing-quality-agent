import unittest

from rag.embedding import OllamaUnavailable
from rag.vector_retriever import build_vector_index, load_index, retrieve_vector
from tools.knowledge_tool import retrieve_quality_documents


def fake_embedder():
    """Return a deterministic 4-dim embedder with one dimension per keyword.

    A text activates dimension ``i`` if it contains keyword ``i``; queries and
    chunks sharing a keyword get cosine similarity ~1, others ~0.
    """

    keywords = ("装配", "气源", "扭矩枪", "电池")

    def embed(texts):
        vectors = []
        for text in texts:
            vectors.append([1.0 if keyword in text else 0.0 for keyword in keywords])
        return vectors

    return embed


CHUNKS = [
    {"doc": "defect_code_manual.md", "section": "torque_low 扭矩偏低", "text": "扭矩偏低：装配扭矩低于规格下限"},
    {"doc": "defect_code_manual.md", "section": "pressure_high 压力偏高", "text": "压力偏高：气源压力波动"},
    {"doc": "maintenance_cases.md", "section": "案例一", "text": "W-07 扭矩偏低批量不良，扭矩枪校准漂移"},
]


class VectorRetrieverTests(unittest.TestCase):
    def test_ranks_semantically_similar_chunk_first(self):
        embed = fake_embedder()

        results = retrieve_vector("螺丝拧不紧 装配问题", CHUNKS, top_k=2, min_score=0.0, embed_fn=embed)

        self.assertEqual(results[0]["section"], "torque_low 扭矩偏低")
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_respects_top_k(self):
        embed = fake_embedder()

        results = retrieve_vector("装配", CHUNKS, top_k=1, min_score=0.0, embed_fn=embed)

        self.assertEqual(len(results), 1)

    def test_filters_below_min_score(self):
        embed = fake_embedder()

        results = retrieve_vector("电池绝缘", CHUNKS, top_k=3, min_score=0.9, embed_fn=embed)

        self.assertEqual(results, [])

    def test_build_vector_index_round_trip(self, tmp_path=None):
        import tempfile
        from pathlib import Path

        tmp_path = Path(tempfile.mkdtemp())
        index_path = tmp_path / "vector_index.json"
        embed = fake_embedder()

        index = build_vector_index(chunks=CHUNKS, index_path=index_path, embed_fn=embed)

        self.assertEqual(len(index["chunks"]), 3)
        self.assertEqual(len(index["vectors"]), 3)
        saved = load_index(index_path)
        self.assertEqual(saved["chunks"], CHUNKS)


class KnowledgeToolFallbackTests(unittest.TestCase):
    def test_falls_back_to_bigram_when_embedding_unavailable(self):
        from tools import knowledge_tool as knowledge_module

        original = knowledge_module.retrieve_vector

        def broken(*args, **kwargs):
            raise OllamaUnavailable("no server")

        knowledge_module.retrieve_vector = broken
        try:
            result = retrieve_quality_documents("扭矩偏低")
        finally:
            knowledge_module.retrieve_vector = original

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["results"])


if __name__ == "__main__":
    unittest.main()
