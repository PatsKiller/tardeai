"""Market-risk projection for the Command Center (DSN-20261031-market-risk-ui P1-T1 / P2-T1).

Serves `GET /api/v2/market-risk/latest`. Until the engine (DSN-20261031-market-risk-engine P2-T1) writes
`data/runtime/market_risk_latest.json` (MarketRiskSnapshot@v1), the projection is honest about it: `state`
is `not_evaluated`, the tier is `NOT_EVALUATED`, and the only live source it can show is the P0 options-flow
detector's block inside `data/runtime/hedging_radar_latest.json`. Nothing here scores or infers a tier from a
single source; a tier the engine did not compute is never shown as one.

Flat module on purpose: `scripts/lib/market_risk/` is born on the P0-T6 branch and this branch must merge
independently; the engine (P2) moves this file into the package.

Pure functions over dicts; the API route does the file reads. Acknowledgment: there is no episodes store yet
(engine P3-T7), so `ack_outcome()` refuses with the reason; the UI shows the refusal verbatim.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA = "MarketRiskProjection@v1"
TIERS = ("GREEN", "BLUE", "YELLOW", "ORANGE", "RED")
ACTIONABLE = ("ORANGE", "RED")


def _age_hours(as_of: str | None, now: datetime | None = None) -> float | None:
    if not as_of:
        return None
    try:
        t = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return round(((now or datetime.now(timezone.utc)) - t).total_seconds() / 3600, 2)


def build(
    snapshot: dict | None, radar: dict | None, *, stale_after_hours: float = 1.0, now: datetime | None = None
) -> dict:
    """snapshot: the engine's MarketRiskSnapshot@v1 (or None); radar: hedging_radar_latest.json (or None)."""
    now = now or datetime.now(timezone.utc)
    flow = (radar or {}).get("options_flow") if isinstance(radar, dict) else None
    sources: dict[str, Any] = {}
    if isinstance(flow, dict):
        sources["options_flow"] = {
            "as_of": (radar or {}).get("captured_at"),
            "age_hours": _age_hours((radar or {}).get("captured_at"), now),
            "findings": [f for f in (flow.get("findings") or []) if isinstance(f, dict)],
            "priority": flow.get("priority"),
            "session": flow.get("session"),
        }
    if not isinstance(snapshot, dict) or snapshot.get("schema") != "MarketRiskSnapshot@v1":
        return {
            "schema": SCHEMA,
            "state": "not_evaluated",
            "tier": "NOT_EVALUATED",
            "score": None,
            "as_of": None,
            "age_hours": None,
            "stale": False,
            "reason": "Market Risk Engine not live yet (DSN-20261031-market-risk-engine P2-T1); only the P0 options-flow detector reports",
            "contributors": [],
            "categories": [],
            "episode": None,
            "book": None,
            "probabilities": None,
            "sources": sources,
            "generated_at": now.isoformat(),
        }
    age = _age_hours(snapshot.get("as_of"), now)
    stale = age is None or age > float(stale_after_hours)
    tier = str(snapshot.get("tier") or "NOT_EVALUATED").upper()
    if tier not in TIERS:
        tier = "NOT_EVALUATED"
    episode = snapshot.get("episode") if isinstance(snapshot.get("episode"), dict) else None
    return {
        "schema": SCHEMA,
        "state": "stale" if stale else "evaluated",
        "tier": tier,
        "score": snapshot.get("score"),
        "as_of": snapshot.get("as_of"),
        "age_hours": age,
        "stale": stale,
        "stale_after_hours": stale_after_hours,
        "reason": None,
        "contributors": list(snapshot.get("contributors") or [])[:5],
        "categories": list(snapshot.get("categories") or []),
        "confirming": snapshot.get("confirming"),
        "deescalates_if": snapshot.get("deescalates_if"),
        "uplift": snapshot.get("uplift"),
        "episode": episode,
        "book": snapshot.get("book"),
        "probabilities": snapshot.get("probabilities"),
        "history": list(snapshot.get("history") or [])[-30:],
        "sources": sources,
        "generated_at": now.isoformat(),
    }


def banner_visible(projection: dict) -> bool:
    """The Home banner shows only for an evaluated, non-stale ORANGE or RED (design home/v002 section 2)."""
    return projection.get("state") == "evaluated" and projection.get("tier") in ACTIONABLE


def ack_outcome(projection: dict, body: dict | None) -> tuple[int, dict]:
    """HTTP status and body for POST /api/v2/market-risk/ack. Refuses honestly until the episodes store exists."""
    episode = projection.get("episode") or {}
    wanted = str((body or {}).get("episode_id") or "")
    if not episode:
        return 409, {
            "ok": False,
            "error": "no open market-risk episode to acknowledge",
            "detail": "the acknowledgment ledger (market_risk_episodes) lands with DSN-20261031-market-risk-engine-P3-T7",
        }
    if wanted and wanted != str(episode.get("id")):
        return 409, {"ok": False, "error": f"episode {wanted} is not the open episode {episode.get('id')}"}
    return 501, {
        "ok": False,
        "error": "acknowledgment store not built yet (DSN-20261031-market-risk-engine-P3-T7)",
        "episode_id": episode.get("id"),
    }
