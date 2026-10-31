"""The CIO's view of market risk — one place the CIO surfaces read the Market Risk Engine.

Design DSN-20261031-market-risk-engine P3-T3. Operator 2026-10-31: "The CIO agent needs to know about everything,
including this market information to help with his decisions. You need to wire it in."

Consumers:

* ``tier_line`` — the first line of the morning brief and the 10/15/17 ET advice digests;
* ``ask_facts`` — the ``market_risk`` block of Ask-the-CIO's TRADE_AI_FACTS, so an answer can cite tier, score,
  contributors and as-of (and says "not evaluated" honestly when the engine has not run);
* ``apply_entry_gate`` — the curator's ``market_risk_gate`` (config/opportunity_conviction.yaml): entry ideas are
  DEMOTED at YELLOW and HELD (stance ADD/RE_ENTER -> HOLD/WATCH) at ORANGE and RED. Conviction and rank are untouched;
  the gate records what it changed on each assessment, the same pattern as ``position_conflict.suppress_add_hold``;
* ``temperament_posture`` — the posture word the CIO temperament carries per tier.

Read-only and advisory (``MBI_BEHAVIOR = 0``): nothing here sizes, orders, stops or weights. The input is the
projection ``scripts/lib/market_risk_projection.build`` returns (via ``cio_market_context_state``); a tier the engine
did not compute is never invented here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GATE_CONFIG_PATH = PROJECT_ROOT / "config" / "opportunity_conviction.yaml"
EVALUATED_TIERS = ("GREEN", "BLUE", "YELLOW", "ORANGE", "RED")


def load_market_risk() -> Optional[dict[str, Any]]:
    """The served projection, or None when the engine snapshot and the hedging radar are both unreadable."""
    try:
        from scripts.lib.cio_market_context_state import load_market_risk_projection  # type: ignore
    except ImportError:  # pragma: no cover — cron path with scripts/ on sys.path
        from lib.cio_market_context_state import load_market_risk_projection  # type: ignore
    try:
        return load_market_risk_projection()
    except Exception as exc:  # noqa: BLE001 — the CIO reports the failure as a fact, it never crashes on it
        return {"state": "not_evaluated", "tier": "NOT_EVALUATED", "reason": f"projection load failed: {exc}"[:200]}


def _age_hours(as_of: Any, now: datetime) -> Optional[float]:
    try:
        t = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() / 3600.0


def evaluated_tier(
    mr: Optional[dict[str, Any]], *, max_age_hours: Optional[float] = None, now: Optional[datetime] = None
) -> Optional[str]:
    """The engine's tier when it computed one (evaluated, or stale but younger than ``max_age_hours``); else None."""
    if not isinstance(mr, dict):
        return None
    tier = str(mr.get("tier") or "").upper()
    if tier not in EVALUATED_TIERS:
        return None
    state = mr.get("state")
    if state == "evaluated":
        return tier
    if state == "stale" and max_age_hours is not None:
        age = _age_hours(mr.get("as_of"), now or datetime.now(timezone.utc))
        if age is not None and age <= float(max_age_hours):
            return tier
    return None


def _contributor_names(mr: dict[str, Any], n: int = 3) -> list[str]:
    out = []
    for c in (mr.get("contributors") or [])[:n]:
        if isinstance(c, dict) and c.get("name"):
            out.append(str(c["name"]))
    return out


def _et_hhmm(as_of: Any) -> str:
    try:
        from zoneinfo import ZoneInfo

        t = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(ZoneInfo("America/New_York")).strftime("%a %H:%M ET")
    except (TypeError, ValueError):
        return "time unknown"


def tier_line(mr: Optional[dict[str, Any]]) -> str:
    """One line for the top of a brief or digest. Never shows a tier the engine did not compute."""
    if not isinstance(mr, dict):
        return "Market risk: not yet evaluated (no engine snapshot)"
    tier = str(mr.get("tier") or "").upper()
    if tier in EVALUATED_TIERS and mr.get("state") in ("evaluated", "stale"):
        score = mr.get("score")
        line = f"Market risk {tier}" + (f" {round(float(score))}/100" if isinstance(score, (int, float)) else "")
        names = _contributor_names(mr)
        if names:
            line += " — " + ", ".join(names)
        line += f"; as of {_et_hhmm(mr.get('as_of'))}"
        if mr.get("state") == "stale":
            line += " (stale)"
        return line
    reason = str(mr.get("reason") or "").strip()
    flow = ((mr.get("sources") or {}).get("options_flow") or {}).get("findings") or []
    hot = [f for f in flow if isinstance(f, dict) and f.get("state") in ("WARN", "STRESS")]
    line = "Market risk: not yet evaluated"
    if hot:
        line += " · options flow " + ", ".join(f"{f.get('symbol')} {str(f.get('state')).lower()}" for f in hot)
    elif reason:
        line += f" ({reason[:90]})"
    return line


def ask_facts(mr: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The ``market_risk`` block for Ask-the-CIO TRADE_AI_FACTS. Every field the model may cite carries ``as_of``."""
    if not isinstance(mr, dict):
        return {
            "tier": "NOT_EVALUATED",
            "state": "not_evaluated",
            "reason": "no market-risk projection",
            "line": tier_line(None),
        }
    tier = str(mr.get("tier") or "NOT_EVALUATED").upper()
    out: dict[str, Any] = {
        "tier": tier if tier in EVALUATED_TIERS else "NOT_EVALUATED",
        "state": mr.get("state") or "not_evaluated",
        "score": mr.get("score"),
        "as_of": mr.get("as_of"),
        "line": tier_line(mr),
    }
    if out["tier"] == "NOT_EVALUATED":
        out["reason"] = mr.get("reason")
        flow = (mr.get("sources") or {}).get("options_flow") or {}
        if flow.get("findings"):
            out["options_flow"] = {
                "as_of": flow.get("as_of"),
                "findings": [
                    {k: f.get(k) for k in ("symbol", "state", "pc_vol_ratio", "pc_oi_ratio") if k in f}
                    for f in flow["findings"]
                    if isinstance(f, dict)
                ],
            }
        return out
    out.update(
        {
            "confirming": mr.get("confirming"),
            "contributors": [
                {k: c.get(k) for k in ("name", "points", "detail", "as_of") if k in c}
                for c in (mr.get("contributors") or [])[:5]
                if isinstance(c, dict)
            ],
            "deescalates_if": mr.get("deescalates_if"),
            "book_vulnerability": (mr.get("book") or {}).get("vulnerability")
            if isinstance(mr.get("book"), dict)
            else None,
            "probabilities": mr.get("probabilities"),
            "stale": bool(mr.get("stale")),
        }
    )
    return out


def load_gate_config(path: Path | str = GATE_CONFIG_PATH) -> dict[str, Any]:
    """``market_risk_gate`` from config/opportunity_conviction.yaml ({} when absent or unreadable)."""
    import yaml

    try:
        return dict((yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("market_risk_gate") or {})
    except (OSError, ValueError, AttributeError):
        return {}


def gate_action(tier: Optional[str], cfg: dict[str, Any]) -> Optional[str]:
    """'hold', 'demote' or None for this tier under ``market_risk_gate``."""
    if not tier or not cfg.get("enabled", False):
        return None
    t = tier.upper()
    if t in {str(x).upper() for x in (cfg.get("hold_tiers") or [])}:
        return "hold"
    if t in {str(x).upper() for x in (cfg.get("demote_tiers") or [])}:
        return "demote"
    return None


def apply_entry_gate(
    assessments: list[dict[str, Any]],
    mr: Optional[dict[str, Any]],
    cfg: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Mark entry ideas DEMOTED or HELD by the market-risk tier. Returns (assessments, report).

    Only assessments whose type is in ``entry_types`` or whose stance is in ``hold_stances`` are touched. HOLD rewrites
    the stance (``hold_stances`` map, e.g. ADD -> HOLD, RE_ENTER -> WATCH) and records ``stance_suppressed``; DEMOTE
    leaves the stance and records ``market_risk_gate`` so the digest sorts the idea after ungated ones. Conviction,
    factors and rank are never changed.
    """
    tier = evaluated_tier(mr, max_age_hours=cfg.get("max_stale_hours"), now=now)
    action = gate_action(tier, cfg)
    report: dict[str, Any] = {
        "enabled": bool(cfg.get("enabled", False)),
        "tier": tier or "NOT_EVALUATED",
        "state": (mr or {}).get("state") if isinstance(mr, dict) else None,
        "as_of": (mr or {}).get("as_of") if isinstance(mr, dict) else None,
        "action": action,
        "held": [],
        "demoted": [],
    }
    if action is None:
        return assessments, report
    entry_types = {str(x) for x in (cfg.get("entry_types") or [])}
    stance_map = {str(k): str(v) for k, v in (cfg.get("hold_stances") or {}).items()}
    why = f"market risk {tier}" + (
        f" {round(float(mr['score']))}/100" if isinstance(mr.get("score"), (int, float)) else ""
    )
    for a in assessments:
        stance = str(a.get("stance") or "")
        is_entry = str(a.get("type") or "") in entry_types or stance in stance_map
        if not is_entry:
            continue
        sym = a.get("symbol")
        a["market_risk_gate"] = {"action": action, "tier": tier, "as_of": mr.get("as_of"), "why": why}
        if action == "hold":
            if stance in stance_map:
                a["stance_suppressed"] = {"from": stance, "reason": f"market_risk_gate: {why}"}
                a["stance"] = stance_map[stance]
            a["stance_rationale"] = f"Held while {why}. " + str(a.get("stance_rationale") or "")
            report["held"].append(sym)
        else:
            report["demoted"].append(sym)
    return assessments, report


def is_gated(item_or_assessment: dict[str, Any]) -> bool:
    return bool((item_or_assessment or {}).get("market_risk_gate"))


def temperament_posture(tier: Optional[str], cfg: dict[str, Any]) -> Optional[str]:
    """Posture word for the CIO temperament at this tier (``market_risk_gate.temperament``), or None."""
    if not tier:
        return None
    return (cfg.get("temperament") or {}).get(str(tier).upper())
