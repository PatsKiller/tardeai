"""CanonicalStoreRegistry@v1 — one contract for persisted intelligence stores.

Consumers call resolve_store(store_id), not remembered filenames.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from scripts.lib.product_availability import canonicalize_reason

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CanonicalStoreRegistry@v1"

OWNERSHIP_CLASSES = (
    "AUTHORITATIVE",
    "APPEND_ONLY_EVIDENCE",
    "CANONICAL_PERSISTENT_STATE",
    "DERIVED_CURRENT_PROJECTION",
    "CACHE",
    "OPS_LOG",
    "RETIRED",
)

# Logical stores. Paths are relative to production state root.
STORES: dict[str, dict[str, Any]] = {
    "portfolio.holdings.current": {
        "path": "data/portfolios/state/holdings.json",
        "format": "json",
        "schema": "HoldingsSnapshot",
        "authority": AUTHORITY,
        "writer": "holdings reconciliation",
        "readers": ["aegis", "cio.product", "portfolio.state", "cio.operator_product"],
        "kind": "current",
        "ownership_class": "AUTHORITATIVE",
        "append_only": False,
        "rebuildable": False,
        "identity_key": "symbol+account",
        "freshness_policy": "last_known_good_if_write_rejected",
    },
    "cio.product.current": {
        "path": "data/cio/cio_investment_brief.json",
        "format": "json",
        "schema": "CIOInvestmentProduct@v1",
        "authority": AUTHORITY,
        "writer": "scripts.lib.cio_investment_product",
        "readers": ["aegis", "command_center", "cio.operator_product"],
        "kind": "current",
        "ownership_class": "DERIVED_CURRENT_PROJECTION",
        "append_only": False,
        "rebuildable": True,
        "aliases": [
            "data/cio/cio_investment_product_latest.json",
            "data/cio/CURRENT/cio_investment_product_latest.json",
        ],
        "stale_reader_filenames": ["cio_investment_product_latest.json"],
    },
    "cio.product.history": {
        "path": "data/cio/cio_investment_briefs.jsonl",
        "format": "jsonl",
        "schema": "CIOInvestmentProduct@v1",
        "authority": AUTHORITY,
        "writer": "scripts.lib.cio_investment_product",
        "kind": "history",
        "ownership_class": "APPEND_ONLY_EVIDENCE",
        "append_only": True,
        "rebuildable": False,
    },
    "cio.operator_product.current": {
        "path": "data/cio/cio_operator_product.json",
        "format": "json",
        "schema": "CIOOperatorProduct@v1",
        "authority": AUTHORITY,
        "writer": "scripts.lib.cio_operator_product",
        "readers": ["aegis", "telegram", "command_center", "morning", "eod"],
        "kind": "current",
        "ownership_class": "DERIVED_CURRENT_PROJECTION",
        "append_only": False,
        "rebuildable": True,
        "current_projection_of": "cio.product.current",
    },
    "cio.operator_product.history": {
        "path": "data/cio/cio_operator_product.jsonl",
        "format": "jsonl",
        "schema": "CIOOperatorProduct@v1",
        "authority": AUTHORITY,
        "writer": "scripts.lib.cio_operator_product",
        "kind": "history",
        "ownership_class": "APPEND_ONLY_EVIDENCE",
        "append_only": True,
        "rebuildable": False,
    },
    "cio.decisions": {
        "path": "data/cio/cio_decisions.jsonl",
        "format": "jsonl",
        "schema": "CIODecision",
        "authority": AUTHORITY,
        "writer": "cio_decision_pipeline",
        "kind": "history",
        "ownership_class": "APPEND_ONLY_EVIDENCE",
        "append_only": True,
        "rebuildable": False,
        "retired_as_canonical_current": True,
        "note": "Not the current CIO product. Aegis must not hunt this file.",
    },
    "cio.checkpoints": {
        "path": "data/cio/outcome_checkpoints.jsonl",
        "format": "jsonl",
        "schema": "OutcomeCheckpoint@v1",
        "authority": AUTHORITY,
        "writer": "scripts.lib.r17_checkpoint_binding",
        "kind": "history",
        "ownership_class": "APPEND_ONLY_EVIDENCE",
        "append_only": True,
        "rebuildable": False,
    },
    "cio.outcomes": {
        "path": "data/cio/outcome_observations.jsonl",
        "format": "jsonl",
        "schema": "OutcomeObservation@v1",
        "authority": AUTHORITY,
        "writer": "scripts.lib.cio_institutional_learning",
        "kind": "history",
        "ownership_class": "APPEND_ONLY_EVIDENCE",
        "append_only": True,
        "rebuildable": False,
    },
    "advisory.current": {
        "path": "data/runtime/advisory_desk_latest.json",
        "format": "json",
        "schema": "AdvisoryDesk",
        "authority": AUTHORITY,
        "writer": "scripts.api_v3_advisory",
        "readers": ["aegis", "advisory_api", "cio.operator_product"],
        "kind": "current",
        "ownership_class": "DERIVED_CURRENT_PROJECTION",
        "append_only": False,
        "rebuildable": True,
        "aliases": ["data/runtime/advisory_latest.json"],
        "stale_reader_filenames": ["advisory_latest.json"],
    },
    "research.current": {
        "path": "data/cio/hermes_research_projection.json",
        "format": "json",
        "schema": "HermesResearchProjection",
        "authority": AUTHORITY,
        "writer": "hermes_research_loop",
        "kind": "current",
        "ownership_class": "DERIVED_CURRENT_PROJECTION",
        "append_only": False,
        "rebuildable": True,
    },
    "research.raw": {
        "path": "data/cio/cio_research_impacts.jsonl",
        "format": "jsonl",
        "schema": "ResearchImpact",
        "authority": AUTHORITY,
        "writer": "cio_research",
        "kind": "history",
        "ownership_class": "APPEND_ONLY_EVIDENCE",
        "append_only": True,
        "rebuildable": False,
    },
    "research.hermes": {
        "path": "data/cio/hermes_research_projection.json",
        "format": "json",
        "schema": "HermesResearchProjection",
        "authority": AUTHORITY,
        "writer": "hermes_research_loop",
        "kind": "current",
        "ownership_class": "DERIVED_CURRENT_PROJECTION",
        "append_only": False,
        "rebuildable": True,
    },
    "memory.canonical": {
        "path": "data/cio/aif_memory.json",
        "format": "json",
        "schema": "AIFMemory",
        "authority": AUTHORITY,
        "writer": "scripts.lib.agent_durable_memory",
        "kind": "current",
        "ownership_class": "CANONICAL_PERSISTENT_STATE",
        "append_only": False,
        "rebuildable": False,
    },
    "ops.health": {
        "path": "data/health",
        "format": "dir",
        "schema": "OpsHealth",
        "authority": AUTHORITY,
        "writer": "health agents",
        "kind": "ops",
        "ownership_class": "OPS_LOG",
        "append_only": True,
        "rebuildable": True,
        "not_cio_intelligence": True,
    },
    "sector.momentum.current": {
        "path": "data/runtime/sector_momentum_latest.json",
        "format": "json",
        "schema": "SectorMomentum",
        "authority": AUTHORITY,
        "writer": "sector_momentum_engine",
        "readers": ["cio.operator_product"],
        "kind": "current",
        "ownership_class": "DERIVED_CURRENT_PROJECTION",
        "append_only": False,
        "rebuildable": True,
    },
    "industry.momentum.current": {
        "path": "data/runtime/industry_momentum_latest.json",
        "format": "json",
        "schema": "IndustryMomentum",
        "authority": AUTHORITY,
        "writer": "industry_momentum",
        "readers": ["cio.operator_product"],
        "kind": "current",
        "ownership_class": "DERIVED_CURRENT_PROJECTION",
        "append_only": False,
        "rebuildable": True,
    },
    "cio.theses": {
        "path": "data/cio/cio_theses_projection.json",
        "format": "json",
        "schema": "CIOTheses",
        "authority": AUTHORITY,
        "writer": "cio_theses",
        "kind": "current",
        "ownership_class": "CANONICAL_PERSISTENT_STATE",
        "append_only": False,
        "rebuildable": True,
    },
    "cio.feedback": {
        "path": "data/cio/decision_dispositions.jsonl",
        "format": "jsonl",
        "schema": "DecisionDisposition",
        "authority": AUTHORITY,
        "writer": "api_v3_cio",
        "kind": "history",
        "ownership_class": "APPEND_ONLY_EVIDENCE",
        "append_only": True,
        "rebuildable": False,
    },
    "notifications.outbox": {
        "path": "data/cio/cio_notification_outbox.jsonl",
        "format": "jsonl",
        "schema": "NotificationOutbox",
        "authority": AUTHORITY,
        "writer": "cio_notification_outbox",
        "kind": "history",
        "ownership_class": "APPEND_ONLY_EVIDENCE",
        "append_only": True,
        "rebuildable": False,
    },
}

# No ambiguous store: every entry must declare ownership_class.
assert all(v.get("ownership_class") in OWNERSHIP_CLASSES for v in STORES.values())

CANONICAL_FILENAMES = {Path(v["path"]).name for v in STORES.values() if v.get("path")}


def production_state_root(root: Path | str | None = None) -> Path:
    if root:
        return Path(root)
    env = os.environ.get("TRADEAI_STATE_ROOT") or os.environ.get("TRADEAI_ROOT")
    if env:
        return Path(env)
    persistent = os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")
    if persistent:
        return Path(persistent)
    preferred = Path.home() / "trade-ai-releases" / "persistent-state"
    if (preferred / "PERSISTENT_STATE_ROOT.json").is_file():
        return preferred
    current = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"
    if current.is_dir():
        return current.resolve()
    return Path(__file__).resolve().parents[2]


def registry() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "stores": STORES,
        "ownership_classes": OWNERSHIP_CLASSES,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def resolve_store(store_id: str, *, root: Path | str | None = None) -> dict[str, Any]:
    """Resolve a logical store to a real path. Tries aliases for stale readers."""
    spec = STORES.get(store_id)
    if not spec:
        return {
            "ok": False,
            "reason": "UNKNOWN_STORE",
            "store_id": store_id,
            "authority": AUTHORITY,
        }
    base = production_state_root(root)
    primary = base / spec["path"]
    found = primary if primary.exists() else None
    used_alias = None
    if found is None:
        for alias in spec.get("aliases") or []:
            p = base / alias
            if p.exists():
                found = p
                used_alias = alias
                break
    exists = found is not None and found.exists()
    return {
        "ok": True,
        "store_id": store_id,
        "path": found or primary,
        "primary_path": primary,
        "exists": exists,
        "used_alias": used_alias,
        "spec": spec,
        "unavailable_reason": None if exists else "PRODUCER_NOT_RUN",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def load_json_store(store_id: str, *, root: Path | str | None = None) -> dict[str, Any]:
    loc = resolve_store(store_id, root=root)
    if not loc.get("exists"):
        return {
            "ok": False,
            "available": False,
            "reason": canonicalize_reason(loc.get("unavailable_reason") or "PRODUCER_NOT_RUN"),
            "status": canonicalize_reason(loc.get("unavailable_reason") or "PRODUCER_NOT_RUN"),
            "store_id": store_id,
            "path": str(loc.get("primary_path")),
        }
    path = Path(loc["path"])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "available": False,
            "reason": "INVALID_SCHEMA",
            "status": "INVALID_SCHEMA",
            "operator_data_quality": "DEGRADED",
            "error": type(exc).__name__,
            "store_id": store_id,
            "path": str(path),
        }
    return {
        "ok": True,
        "available": True,
        "reason": None,
        "status": "AVAILABLE",
        "store_id": store_id,
        "path": str(path),
        "used_alias": loc.get("used_alias"),
        "data": data,
        "mtime": path.stat().st_mtime,
    }
