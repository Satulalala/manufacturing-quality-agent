"""Export current JSON sessions to the old LangGraph checkpoint format for rollback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.session_store import SessionStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export SQLite JSON session states to a legacy checkpoint database."
    )
    parser.add_argument(
        "--target",
        type=Path,
        help="Checkpoint database path to replace after validation (defaults to the configured legacy path).",
    )
    args = parser.parse_args()
    result = SessionStore().export_legacy_checkpoints(args.target)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
