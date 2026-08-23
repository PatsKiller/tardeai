from __future__ import annotations

import json

import pytest

from scripts.lib.ollama_embedding_policy import (
    ALLOWED_MODEL,
    ALLOWED_MODEL_DIGEST,
    EXPECTED_DIMENSION,
    OllamaEmbeddingPolicyError,
    embed,
    normalize_input,
    validate_request,
)


class _Response:
    def __init__(self, body: dict):
        self.body = body

    def read(self):
        return json.dumps(self.body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_policy_is_pinned():
    assert ALLOWED_MODEL == "nomic-embed-text"
    assert len(ALLOWED_MODEL_DIGEST) == 64
    assert EXPECTED_DIMENSION == 768


@pytest.mark.parametrize("path", ["/api/chat", "/api/generate", "/api/embeddings"])
def test_local_generative_and_legacy_endpoints_rejected(path):
    with pytest.raises(OllamaEmbeddingPolicyError, match="ENDPOINT_FORBIDDEN"):
        validate_request(url=f"http://127.0.0.1:11434{path}", model=ALLOWED_MODEL)


def test_nonapproved_model_rejected():
    with pytest.raises(OllamaEmbeddingPolicyError, match="MODEL_FORBIDDEN"):
        validate_request(url="http://127.0.0.1:11434/api/embed", model="unapproved")


def test_normalized_input_and_dimension(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured.update(json.loads(request.data))
        return _Response({"embeddings": [[0.25] * EXPECTED_DIMENSION]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    vector = embed("  NOC\n\t thesis  ")
    assert captured == {"model": ALLOWED_MODEL, "input": "NOC thesis"}
    assert len(vector) == EXPECTED_DIMENSION


def test_wrong_dimension_rejected(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _Response({"embeddings": [[0.0] * 12]}),
    )
    with pytest.raises(OllamaEmbeddingPolicyError, match="DIMENSION_MISMATCH"):
        embed("NOC")
