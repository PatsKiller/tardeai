"""Versioned reference policy. Loading this file never grants live authority."""
from __future__ import annotations

import json
from pathlib import Path


def load_rulebook(path: Path | None = None) -> dict:
    path = path or Path(__file__).resolve().parents[4] / "config/conflict_rulebook.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "ConflictRulebook@v1" or doc.get("version") not in {1, 2}:
        raise ValueError("unsupported conflict rulebook")
    if doc.get("status") not in {"PROPOSED", "APPROVED"}:
        raise ValueError("unknown conflict rulebook status")
    # The full matrix never-auto list (EXCEPTIONS_MATRIX "Never auto-resolved"); a rulebook may add, never drop.
    required = {"safety", "protection", "policy", "money_mismatch", "schedule_state", "flapping", "ownership",
                "pending_fill", "wash_window", "cross_instrument", "nway_recorded_split", "held_exit_vs_add"}
    if not required.issubset(doc.get("never_auto", [])):
        raise ValueError("conflict rulebook weakens never-auto boundary")
    if doc.get("status") == "PROPOSED" and (doc.get("approval") or doc.get("live_enabled")):
        raise ValueError("proposed conflict rulebook cannot assert approval or live authority")
    if doc.get("status") == "APPROVED":
        approval = doc.get("approval") or {}
        if not all(str(approval.get(k) or "").strip() for k in ("by", "at", "ref")) or approval.get("by") != "operator":
            raise ValueError("approved conflict rulebook needs the operator's approval record (by, at, ref)")
        if not doc.get("matrix_sha256"):
            raise ValueError("approved conflict rulebook must stay bound to the exceptions matrix sha256")
    return doc


RULEBOOK = load_rulebook()
