"""Deterministic BASELINE_PROJECTION from existing graph/state. Zero paid. No research."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from scripts.lib.curation_cycle import curate_security
from scripts.lib.free_first_refresh import load_profiles
from scripts.lib.hermes_curation_summary import KIND_BASELINE, load_latest
from scripts.lib.security_identity import attach_identity_v2, normalize_symbol

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "BaselineCurationProjectionReport@v1"


def project_baseline_universe(root: Path | str, *, symbols: list[str] | None = None) -> dict[str, Any]:
    """Write kind=BASELINE_PROJECTION once per security. Never calls a provider."""
    profiles = [attach_identity_v2(p) for p in load_profiles(root)]
    if symbols:
        want = {normalize_symbol(s) for s in symbols}
        profiles = [p for p in profiles if normalize_symbol(p.get("symbol")) in want]
    created = 0
    existed = 0
    unresolved = 0
    rows: list[dict[str, Any]] = []
    for p in profiles:
        sym = normalize_symbol(p.get("symbol"))
        prev = load_latest(root, security_guid=p.get("security_guid"), symbol=sym)
        out = curate_security(root, p, {
            "symbol": sym,
            "decision": "NO_NEW_INFO",
            "hermes_resolved": True,
            "searx_accepted": 0,
            "path": ["NO_NEW_INFO", "BASELINE_PROJECTION"],
        })
        reason = out.get("curation_reason")
        wrote = bool(out.get("curation_wrote"))
        if wrote and reason == KIND_BASELINE:
            created += 1
        elif not wrote and prev:
            existed += 1
        elif not wrote:
            unresolved += 1
        rows.append({
            "symbol": sym,
            "wrote": wrote,
            "reason": reason,
            "version": out.get("curation_version"),
            "paid_dispatch": out.get("paid_dispatch"),
        })
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "mode": "BASELINE_PROJECTION",
        "paid_dispatch_entered": 0,
        "financial_action": False,
        "memory_behavior_influence": 0,
        "source_sha": str(os.getenv("FREE_FIRST_SOURCE_SHA") or ""),
        "tracked": len(profiles),
        "created": created,
        "existing": existed,
        "unresolved": unresolved,
        "research_required": 0,
        "rows": rows,
    }
