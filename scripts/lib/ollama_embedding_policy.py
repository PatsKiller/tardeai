"""Application allowlist for Trade AI's sole candidate local GPU workload."""
from __future__ import annotations

import json
import math
import re
import unicodedata
import urllib.request
from urllib.parse import urlparse

ALLOWED_MODEL = "nomic-embed-text"
ALLOWED_MODEL_DIGEST = (
    "0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"
)
EXPECTED_DIMENSION = 768
ALLOWED_PATH = "/api/embed"
DEFAULT_URL = "http://127.0.0.1:11434/api/embed"


class OllamaEmbeddingPolicyError(RuntimeError):
    pass


def normalize_input(value: str) -> str:
    """Canonicalize semantically identical input before embedding."""
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", normalized).strip()


def validate_request(*, url: str, model: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise OllamaEmbeddingPolicyError("OLLAMA_ENDPOINT_NOT_LOOPBACK")
    if parsed.path != ALLOWED_PATH or parsed.query or parsed.fragment:
        raise OllamaEmbeddingPolicyError("OLLAMA_ENDPOINT_FORBIDDEN")
    if model != ALLOWED_MODEL:
        raise OllamaEmbeddingPolicyError("OLLAMA_MODEL_FORBIDDEN")


def embed(
    text: str,
    *,
    url: str = DEFAULT_URL,
    model: str = ALLOWED_MODEL,
    timeout_s: float = 120,
) -> list[float]:
    """Call only the approved embedding endpoint and enforce its vector contract."""
    validate_request(url=url, model=model)
    payload = json.dumps({"model": model, "input": normalize_input(text)}).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        body = json.loads(response.read())
    embeddings = body.get("embeddings") or []
    vector = embeddings[0] if embeddings and isinstance(embeddings[0], list) else []
    if len(vector) != EXPECTED_DIMENSION:
        raise OllamaEmbeddingPolicyError(
            f"EMBEDDING_DIMENSION_MISMATCH:{len(vector)}:{EXPECTED_DIMENSION}"
        )
    values = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in values):
        raise OllamaEmbeddingPolicyError("EMBEDDING_NON_FINITE")
    return values
