"""Ingest quality knowledge documents into a retrievable index.

Each markdown file under ``docs/`` is split on ``##`` headings into sections.
The result is a list of ``{doc, section, text}`` chunks written to
``rag/index.json`` so retrieval never re-parses markdown at query time.
"""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
DEFAULT_INDEX_PATH = Path(__file__).resolve().parent / "index.json"

KNOWLEDGE_FILES = ("quality_standard.md", "defect_code_manual.md", "maintenance_cases.md")


def _split_sections(markdown_text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in markdown_text.splitlines():
        if line.startswith("## "):
            if current_heading is not None:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line[3:].strip()
            current_lines = [line]
        elif line.startswith("# "):
            continue
        else:
            current_lines.append(line)

    if current_heading is not None:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    return [(heading, text) for heading, text in sections if text]


def load_documents(docs_dir: str | Path = DEFAULT_DOCS_DIR) -> list[dict[str, str]]:
    """Parse every markdown document into section chunks."""

    documents: list[dict[str, str]] = []
    for path in sorted(Path(docs_dir).glob("*.md")):
        if path.name not in KNOWLEDGE_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for section, content in _split_sections(text):
            documents.append({"doc": path.name, "section": section, "text": content})
    return documents


def build_index(
    docs_dir: str | Path = DEFAULT_DOCS_DIR,
    index_path: str | Path = DEFAULT_INDEX_PATH,
) -> list[dict[str, str]]:
    """Parse documents and persist the chunk index."""

    documents = load_documents(docs_dir)
    destination = Path(index_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(documents, ensure_ascii=False, indent=2), encoding="utf-8")
    return documents


def load_index(index_path: str | Path = DEFAULT_INDEX_PATH) -> list[dict[str, str]]:
    """Load the chunk index, building it on first use."""

    path = Path(index_path)
    if not path.exists():
        return build_index(index_path=path)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
