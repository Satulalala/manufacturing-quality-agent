from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from server.services.comparisons import ComparisonService


class ComparisonServiceTests(unittest.TestCase):
    def test_create_returns_latest_child_run_updated_at(self):
        expected_updated_at = "2026-10-23T08:30:00+00:00"
        sources_by_id = {
            source_id: SimpleNamespace(
                source_id=source_id,
                data_version="version-1",
                name=f"{source_id}.csv",
            )
            for source_id in ("source-1", "source-2")
        }
        sources = Mock()
        sources.get.side_effect = sources_by_id.get
        conversations = Mock()
        conversations.create_session.side_effect = lambda *_args: {"session_id": str(uuid4())}
        runs = Mock()
        runs.get.return_value = {
            "status": "running",
            "report": None,
            "updated_at": expected_updated_at,
        }

        with tempfile.TemporaryDirectory() as directory:
            service = ComparisonService(
                sources,
                conversations,
                runs,
                Path(directory) / "comparisons.sqlite3",
            )

            result = service.create(
                str(uuid4()),
                "比较质量趋势",
                list(sources_by_id),
            )

        self.assertEqual(result["updated_at"], expected_updated_at)


if __name__ == "__main__":
    unittest.main()
