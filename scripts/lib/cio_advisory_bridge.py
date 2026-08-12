"""cio_advisory_bridge.py — read-only bridge from the Advisory Desk to CIO actors.

READ_ONLY_ADVISORY. Exposes a compact, deterministic view of the Advisory Desk
(top actionable rows + portfolio analytics + performance + governing thesis) so
the CIO (Alex), wealth advisor (Steph), advisor (Morgan), and the event-driven
CIO brief can consume the desk without importing the heavy builder directly.

Rules:
  * Never writes to disk, never mutates state, never calls an LLM.
  * All values are read from the desk cache / state JSON, or labeled DATA_UNAVAILABLE.
  * Deterministic only — no narrative generation, no opinion synthesis.

This module is the single seam where the desk output meets the CIO actor family.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

_ACTIONABLE = {"TRIM", "EXIT", "ADD", "RE_ENTER"}


def _get_advisory_desk(force: bool = False) -> dict[str, Any]:
    """Load the desk via the API layer (canonical surface). Fail-soft to {}."""
    try:
        from api_v3_advisory import get_advisory_desk  # type: ignore
        return get_advisory_desk(force=force) or {}
    except Exception:
        try:
            from scripts.api_v3_advisory import get_advisory_desk  # type: ignore
            return get_advisory_desk(force=force) or {}
        except Exception:
            return {}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def advisory_desk_context(*, max_rows: int = 8, min_mv: float = 0.0) -> dict[str, Any]:
    """Compact desk context for CIO actors and the event brief.

    Returns a deterministic dict; never raises. ``top_actionable`` rows are
    ranked by (actionable-first, market value) and trimmed to ``max_rows``.
    """
    desk = _get_advisory_desk(force=False)
    rows = desk.get("rows") or []
    ranked = sorted(
        [r for r in rows if (float(r.get("market_value") or 0) >= min_mv)],
        key=lambda r: (
            1 if str(r.get("verdict")) in _ACTIONABLE else 0,
            float(r.get("market_value") or 0),
        ),
        reverse=True,
    )

    def _row(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": r.get("symbol"),
            "account": r.get("account"),
            "verdict": r.get("verdict"),
            "confidence": r.get("confidence"),
            "market_value": r.get("market_value"),
            "weight_pct": r.get("weight_pct"),
            "holding_period": r.get("holding_period"),
            "adjusted_cost": r.get("adjusted_cost"),
            "rationale": (r.get("rationale") or "")[:160],
        }

    return {
        "ok": bool(desk.get("ok")),
        "as_of": desk.get("as_of"),
        "row_count": desk.get("row_count"),
        "verdict_counts": desk.get("verdict_counts") or {},
        "by_class": desk.get("by_class") or {},
        "top_actionable": [_row(r) for r in ranked[:max_rows]],
        "portfolio_analytics": desk.get("portfolio_analytics") or {},
        "performance": desk.get("performance") or {},
        "banners": desk.get("banners") or [],
        "synthesis": (desk.get("synthesis") or "")[:600],
        "authority": "READ_ONLY_ADVISORY",
    }


def living_thesis_context() -> dict[str, Any]:
    """Current desk@vN governing thesis from the CIO projection (JSON only)."""
    proj = _load_json(PROJECT_ROOT / "data" / "cio" / "cio_theses_projection.json")
    cur = (proj.get("current") or {}) if isinstance(proj, dict) else {}
    desk = cur.get("desk")
    if not isinstance(desk, dict):
        return {"state": "DATA_UNAVAILABLE", "reason": "no desk thesis published"}
    return {
        "state": "AVAILABLE",
        "thesis_version": desk.get("thesis_version"),
        "version": desk.get("version"),
        "stance": desk.get("stance"),
        "status": desk.get("status"),
        "summary": (desk.get("summary") or "")[:1200],
        "risk_posture": desk.get("risk_posture") or "",
        "principles": list(desk.get("principles") or [])[:12],
        "linked_symbols": list(desk.get("linked_symbols") or [])[:20],
        "authority": "READ_ONLY_ADVISORY",
    }
