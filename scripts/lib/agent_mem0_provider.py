"""agent_mem0_provider.py — Mem0 adapter + shadow pilot (Phase 4).

READ_ONLY_ADVISORY. The `mem0` package is NOT installed and MUST NOT be
installed in this tree. This module provides a fail-soft adapter
(`Mem0MemoryProvider`) that reports NOT_CONFIGURED honestly, plus the due-
diligence record.

Feature flags are NOT declared here. The single source of truth for runtime
activation is ``scripts/lib/agent_feature_flags.py`` (conservative defaults:
MEMORY_PROVIDER="null", MEMORY_SHADOW=0, MEMORY_BEHAVIOR_INFLUENCE=0). This
module only carries Mem0 capability / due-diligence metadata; it must never
expose contradictory runtime activation defaults.
"""
from __future__ import annotations

from typing import Any, Optional

from scripts.lib.agent_context_envelope import RETRIEVAL_NOT_CONFIGURED

_PROVIDER_NAME = "Mem0MemoryProvider"
_NOT_CONFIGURED = "NOT_CONFIGURED"
_REASON_NOT_INSTALLED = (
    "mem0 package not installed; self-hosted/local-controlled data path preferred"
)

# ── Due diligence (honest: nothing is configured in production) ───────────
MEM0_DUE_DILIGENCE: dict[str, Any] = {
    "package": "mem0",
    "version": "none installed",
    "installed": False,
    "hosting_preference": "self-hosted/local-controlled",
    "oss_vs_hosted": "self-hosted OSS preferred over hosted SaaS (no operator data egress)",
    "storage_backend": "TBD",
    "vector_backend": "TBD",
    "embedding_provider": "TBD",
    "license": "TBD (mem0 core is Apache-2.0; confirm per selected backend)",
    "retention": "TBD (must carry explicit expires_at + retention policy)",
    "privacy": "no data leaves a local-controlled path; no operator PII admitted",
    "failure_behavior": "fail-soft: health()=NOT_CONFIGURED; search returns empty; add_candidate returns None",
    "production_status": "NOT_CONFIGURED — shadow pilot only",
    "notes": (
        "No production memory backend is configured. Until a self-hosted backend is "
        "reviewed and wired, the LocalTestMemoryProvider in-memory test double is the "
        "only provider in use."
    ),
}

try:  # fail-soft import: never crash the process when mem0 is absent
    import mem0  # noqa: F401

    _MEM0_AVAILABLE = True
except Exception:  # noqa: BLE001
    _MEM0_AVAILABLE = False


class Mem0MemoryProvider:
    """Fail-soft adapter over the (uninstalled) mem0 package.

    Never constructs a client, never opens a network path, never raises. When a
    reviewed self-hosted backend exists, this class is the seam to wire it in
    behind the same MemoryProvider protocol — without changing callers.
    """

    name = _PROVIDER_NAME

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Deliberately no-op: do not construct a client against an unconfigured backend.
        self._configured = bool(_MEM0_AVAILABLE)

    def health(self) -> dict[str, Any]:
        if not _MEM0_AVAILABLE:
            return {"status": _NOT_CONFIGURED, "reason": _REASON_NOT_INSTALLED}
        return {"status": _NOT_CONFIGURED, "reason": "no self-hosted backend configured"}

    def search(
        self,
        query: Any = None,
        scope: Any = None,
        symbols: Optional[list[str]] = None,
        top_k: int = 8,
        budget_tokens: int = 1500,
    ) -> dict[str, Any]:
        return {
            "query": query,
            "scope": scope,
            "symbols": list(symbols or []),
            "records": [],
            "supporting": [],
            "counter_memory": [],
            "conflicts": [],
            "memory_ids": [],
            "retrieval_status": RETRIEVAL_NOT_CONFIGURED,
            "provider": self.name,
        }

    def add_candidate(self, record: dict[str, Any]) -> Optional[str]:
        return None

    def get(self, memory_id: str) -> Optional[dict[str, Any]]:
        return None

    def dispute(self, memory_id: str, reason: str) -> bool:
        return False

    def expire(self, memory_id: str) -> bool:
        return False
