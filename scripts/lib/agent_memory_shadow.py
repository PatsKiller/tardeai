"""Governed memory shadow comparator.

READ_ONLY_ADVISORY. Compares baseline (no memory) vs retrieved memory context
without changing production advisory action. Does not reuse Program 2 lesson/FS
gates and never flips MEMORY_BEHAVIOR_INFLUENCE.

GOVERNED_MEMORY_ADVISORY_INFLUENCE: OFF | SHADOW | CANARY | ACTIVE_ADVISORY
Default OFF. SHADOW retrieves and records; production behavior is unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from scripts.lib.agent_durable_memory import DurableJsonlMemoryProvider, default_store_path
from scripts.lib.agent_memory_provider import MEMORY_AUTHORITY
from scripts.lib.maturity_control.schema import utc_now
from scripts.lib.maturity_control.store import resolve_root

MEMORY_FLAG = "GOVERNED_MEMORY_ADVISORY_INFLUENCE"
MODES = ("OFF", "SHADOW", "CANARY", "ACTIVE_ADVISORY")


def memory_mode(env: dict[str, str] | None = None) -> str:
    raw = str((env or os.environ).get(MEMORY_FLAG) or "OFF").strip().upper()
    return raw if raw in MODES else "OFF"


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def compare_memory_shadow(
    payload: dict[str, Any],
    *,
    provider: Optional[DurableJsonlMemoryProvider] = None,
    root: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    mode = memory_mode(env)
    query = payload.get("query") or payload.get("subject") or ""
    symbols = list(payload.get("symbols") or [])
    truth = {
        "action": payload.get("canonical_action") or payload.get("action") or payload.get("verdict"),
        "cash": payload.get("cash"),
        "holdings_digest": payload.get("holdings_digest"),
        "risk_limits": payload.get("risk_limits"),
    }
    baseline = {
        "verdict": payload.get("verdict") or "HOLD",
        "conviction": float(payload.get("conviction") or 0),
        "memory_ids": [],
        "influenced": False,
    }
    retrieved: dict[str, Any] = {
        "supporting": [],
        "counter": [],
        "disputed": [],
        "superseded_context": [],
        "memory_ids": [],
        "retrieval_status": "NOT_CONFIGURED",
    }
    if mode != "OFF":
        prov = provider or DurableJsonlMemoryProvider(path=default_store_path(root))
        retrieved = prov.search(query=query, symbols=symbols, top_k=int(payload.get("top_k") or 8))
    enhanced = {
        "verdict": baseline["verdict"],
        "conviction": baseline["conviction"],
        "influenced": False,
        "memory_ids": list(retrieved.get("memory_ids") or []) if mode != "OFF" else [],
        "primary": mode in {"CANARY", "ACTIVE_ADVISORY"},
        "authority_class": MEMORY_AUTHORITY,
    }
    rec = {
        "run_id": "memsh_" + _digest({"t": utc_now(), "p": payload})[:16],
        "at": utc_now(),
        "mode": mode,
        "query": query,
        "symbols": symbols,
        "canonical_truth": truth,
        "baseline": baseline,
        "enhanced": enhanced,
        "retrieval": {
            "supporting": [r.get("memory_id") for r in (retrieved.get("supporting") or [])],
            "counter": [r.get("memory_id") for r in (retrieved.get("counter") or retrieved.get("counter_memory") or [])],
            "disputed": [r.get("memory_id") for r in (retrieved.get("disputed") or [])],
            "superseded_context": [r.get("memory_id") for r in (retrieved.get("superseded_context") or [])],
            "retrieval_status": retrieved.get("retrieval_status"),
            "provenance_visible": True,
        },
        "production_behavior_changed": False,
        "advisory_changes": 0,
        "executed": False,
        "financial_action": False,
        "memory_behavior_influence": str((env or os.environ).get("MEMORY_BEHAVIOR_INFLUENCE") or "0"),
        "authority": "READ_ONLY_ADVISORY",
        "authority_class": MEMORY_AUTHORITY,
    }
    dest = resolve_root(root) / "data" / "cio" / "memory_shadow_runs.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    return rec


def shadow_metrics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "comparator_runs": len(runs),
        "real_retrievals": sum(1 for r in runs if (r.get("retrieval") or {}).get("retrieval_status") == "OK"),
        "advisory_changes": sum(int(r.get("advisory_changes") or 0) for r in runs),
        "production_behavior_changes": sum(1 for r in runs if r.get("production_behavior_changed")),
        "authority_violations": sum(1 for r in runs if r.get("financial_action")),
    }
