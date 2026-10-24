"""Versioned reference policy. Loading this file never grants live authority."""
from __future__ import annotations

import json
from pathlib import Path


def load_rulebook(path: Path | None = None) -> dict:
    path = path or Path(__file__).resolve().parents[4] / "config/conflict_rulebook.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "ConflictRulebook@v1" or doc.get("version") != 1:
        raise ValueError("unsupported conflict rulebook")
    if doc.get("status") not in {"PROPOSED", "APPROVED"}:
        raise ValueError("unknown conflict rulebook status")
    required = {"safety", "protection", "policy", "money_mismatch", "schedule_state", "flapping"}
    if not required.issubset(doc.get("never_auto", [])):
        raise ValueError("conflict rulebook weakens never-auto boundary")
    if doc.get("status") == "PROPOSED" and (doc.get("approval") or doc.get("live_enabled")):
        raise ValueError("proposed conflict rulebook cannot assert approval or live authority")
    return doc


RULEBOOK = load_rulebook()
