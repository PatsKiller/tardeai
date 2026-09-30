"""Expression missed-opportunity ledger (counterfactual vs chosen)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REL = Path("data") / "cio" / "expression_missed_opportunities.jsonl"
AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ExpressionMissedOpportunity@v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[3]
    return base / DEFAULT_REL


def record_if_missed(
    decision: dict[str, Any],
    *,
    chosen_family: str | None,
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """If chosen ≠ top evaluable shadow family, append a ledger row."""
    cmp = decision.get("expression_comparison") if isinstance(decision.get("expression_comparison"), dict) else {}
    ranked = list(cmp.get("ranked") or [])
    top = None
    for c in ranked:
        if c.get("status") == "evaluable_shadow":
            top = c
            break
    if top is None and ranked:
        top = ranked[0]
    top_fam = (top or {}).get("family")
    chosen = (chosen_family or "").strip() or None
    if not top_fam or not chosen or chosen == top_fam:
        return {"ok": True, "recorded": False, "reason": "no_miss_or_incomplete"}
    row = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "ts": _now(),
        "symbol": (decision.get("identity") or {}).get("symbol"),
        "signal_kind": (decision.get("signal_state") or {}).get("kind"),
        "chosen_family": chosen,
        "top_shadow_family": top_fam,
        "top_status": (top or {}).get("status"),
        "delta_note": "chosen expression differs from top shadow candidate — counterfactual only",
    }
    dest = path or default_path(root)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        return {"ok": True, "recorded": True, "path": str(dest)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "recorded": False, "error": f"{type(exc).__name__}:{exc}"[:160]}
