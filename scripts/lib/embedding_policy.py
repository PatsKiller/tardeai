"""EmbeddingPolicy@v1 — local-first. Cloud embeddings disabled by default.

Does not require Amazon Titan. Institutional memory path must not call a
generative local LLM.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.ollama_embedding_policy import (
    ALLOWED_MODEL,
    ALLOWED_MODEL_DIGEST,
    EXPECTED_DIMENSION,
)

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "EmbeddingPolicy@v1"
LOCAL_FIRST_SCHEMA = "LOCAL_FIRST_MEMORY_EMBEDDING_POLICY@v1"

MODE_LOCAL_ONLY = "LOCAL_ONLY"
MODE_CLOUD_AUTHORIZED = "CLOUD_AUTHORIZED"
CLOUD_PROVIDERS_FORBIDDEN_BY_DEFAULT = ("amazon.titan", "titan", "bedrock", "openai", "voyage")


def default_policy() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "local_first_schema": LOCAL_FIRST_SCHEMA,
        "mode": MODE_LOCAL_ONLY,
        "provider": "ollama",
        "model": ALLOWED_MODEL,
        "model_digest": ALLOWED_MODEL_DIGEST,
        "dimension": EXPECTED_DIMENSION,
        "local": True,
        "generative": False,
        "data_classification": "OPERATOR_AND_RESEARCH_MEMORY",
        "allowed_namespaces": [
            "RESEARCH_EVIDENCE",
            "SHARED_ENTITY",
            "POLICY_BELIEF",
        ],
        "fallback_policy": "FAIL_CLOSED_NO_CLOUD",
        "cost_policy": "ZERO_CLOUD_EMBEDDING",
        "privacy_policy": "LOOPBACK_ONLY_NO_EXTERNAL_TRANSMIT",
        "version": 1,
        "authority": AUTHORITY,
        "financial_action": False,
        "cloud_embeddings": "DISABLED_BY_DEFAULT",
    }


def assert_memory_path_allowed(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    p = dict(policy or default_policy())
    if p.get("generative") is True:
        raise RuntimeError("GENERATIVE_MODEL_FORBIDDEN_ON_MEMORY_PATH")
    if p.get("mode") != MODE_LOCAL_ONLY and p.get("mode") != MODE_CLOUD_AUTHORIZED:
        raise RuntimeError("EMBEDDING_MODE_UNKNOWN")
    if p.get("mode") == MODE_CLOUD_AUTHORIZED:
        auth = p.get("cloud_authorization") or {}
        required = ("provider", "data_classification", "operator_authorization", "cost_ceiling_usd", "privacy_acknowledgement")
        missing = [k for k in required if not auth.get(k)]
        if missing:
            raise RuntimeError("CLOUD_EMBEDDING_UNAUTHORIZED:" + ",".join(missing))
    else:
        provider = str(p.get("provider") or "").lower()
        if any(tok in provider for tok in CLOUD_PROVIDERS_FORBIDDEN_BY_DEFAULT):
            raise RuntimeError("CLOUD_EMBEDDING_DISABLED_BY_DEFAULT")
        if p.get("local") is not True:
            raise RuntimeError("LOCAL_ONLY_REQUIRES_LOCAL_PROVIDER")
    return p


def refuse_titan() -> None:
    assert_memory_path_allowed({"schema": SCHEMA, "mode": MODE_LOCAL_ONLY, "provider": "amazon.titan", "local": False, "generative": False})
