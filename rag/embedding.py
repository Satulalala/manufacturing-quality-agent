"""Embedding client for local Ollama models (nomic-embed-text)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Iterable


DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "bge-m3"


class OllamaUnavailable(Exception):
    """Raised when the local Ollama server cannot be reached."""


def embed_texts(
    texts: Iterable[str],
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 30.0,
) -> list[list[float]]:
    """Embed a list of texts into vectors via the local Ollama server."""

    resolved_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)
    resolved_model = os.environ.get("OLLAMA_EMBED_MODEL", DEFAULT_MODEL)
    if base_url:
        resolved_url = base_url
    if model:
        resolved_model = model

    payload = json.dumps({"model": resolved_model, "input": list(texts)}).encode("utf-8")
    request = urllib.request.Request(
        f"{resolved_url}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as error:
        raise OllamaUnavailable(f"cannot reach Ollama at {resolved_url}: {error}") from error

    embeddings = body.get("embeddings")
    if not embeddings:
        raise OllamaUnavailable("Ollama returned no embeddings")
    return embeddings
