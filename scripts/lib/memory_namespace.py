"""MemoryNamespace@v1 — logical tenant isolation, not hardware isolation."""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "MemoryNamespace@v1"
DEFAULT_TENANT = "tradeai:tenant:primary"

NAMESPACES = (
    "OPERATOR_PRIVATE",
    "SESSION_PRIVATE",
    "SHARED_ENTITY",
    "RESEARCH_EVIDENCE",
    "POLICY_BELIEF",
    "ORCHESTRATION",
)

PRIVATE = frozenset({"OPERATOR_PRIVATE", "SESSION_PRIVATE"})


def require_tenant(tenant_id: str | None) -> str:
    tid = str(tenant_id or "").strip()
    if not tid:
        raise RuntimeError("TENANT_SCOPE_REQUIRED")
    return tid


def build_namespace(
    *,
    tenant_id: str | None = DEFAULT_TENANT,
    user_id: str | None = "operator:primary",
    agent_scope: str = "office",
    namespace: str,
    privacy_class: str | None = None,
    sharing_scope: str | None = None,
) -> dict[str, Any]:
    if namespace not in NAMESPACES:
        raise RuntimeError("UNKNOWN_MEMORY_NAMESPACE")
    tid = require_tenant(tenant_id)
    priv = privacy_class or ("PRIVATE" if namespace in PRIVATE else "SHARED")
    share = sharing_scope or ("NONE" if namespace in PRIVATE else "TENANT")
    return {
        "schema": SCHEMA,
        "tenant_id": tid,
        "user_id": user_id,
        "agent_scope": agent_scope,
        "namespace": namespace,
        "privacy_class": priv,
        "sharing_scope": share,
        "hardware_isolation": False,
        "isolation_class": "LOGICAL_TENANT_FILTER",
        "authority": AUTHORITY,
    }


def visible(*, viewer_tenant: str, record_tenant: str, record_namespace: str, viewer_namespace: str | None = None) -> bool:
    require_tenant(viewer_tenant)
    require_tenant(record_tenant)
    if viewer_tenant != record_tenant:
        return False
    if record_namespace in PRIVATE and viewer_namespace and viewer_namespace != record_namespace:
        if viewer_namespace == "SHARED_ENTITY":
            return False
    return True
