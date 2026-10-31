"""Market-risk projection for the Command Center (DSN-20261031-market-risk-ui P1-T1 / P2-T1).

Serves `GET /api/v2/market-risk/latest`. Until the engine (DSN-20261031-market-risk-engine P2-T1) writes
`data/runtime/market_risk_latest.json` (MarketRiskSnapshot@v1), the projection is honest about it: `state`
is `not_evaluated`, the tier is `NOT_EVALUATED`, and the only live source it can show is the P0 options-flow
detector's block inside `data/runtime/hedging_radar_latest.json`. Nothing here scores or infers a tier from a
single source; a tier the engine did not compute is never shown as one.

Flat module on purpose: `scripts/lib/market_risk/` is born on the P0-T6 branch and this branch must merge
independently; the engine (P2) moves this file into the package.

Pure functions over dicts; the API route does the file reads. Acknowledgment (engine P3-T7): `ack_outcome()` writes
the operator's acknowledgment to the episode ledger (`market_risk.escalation`, file store until the
`market_risk_episodes` table is granted) and returns the episode; it refuses with the reason when no episode is open.
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
    snapshot: dict | None,
    radar: dict | None,
    *,
    stale_after_hours: float = 1.0,
    now: datetime | None = None,
    episode: dict | None = None,
) -> dict:
    """snapshot: the engine's MarketRiskSnapshot@v1 (or None); radar: hedging_radar_latest.json (or None);
    episode: the open MarketRiskEpisode@v1 from the ledger, used when the snapshot carries none."""
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
    if isinstance(snapshot.get("episode"), dict):
        episode = snapshot.get("episode")
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


def ack_outcome(
    projection: dict, body: dict | None, *, actor: str = "", now: datetime | None = None, path=None
) -> tuple[int, dict]:
    """HTTP status and body for POST /api/v2/market-risk/ack: record the operator's acknowledgment of the open
    episode in the ledger (safe direction, one click, AGENTS §27.3). Refuses with the reason when there is none."""
    try:
        from lib.market_risk import escalation as esc
    except ImportError:  # pragma: no cover - imported as scripts.lib
        from scripts.lib.market_risk import escalation as esc
    wanted = str((body or {}).get("episode_id") or "") or None
    shown = (projection or {}).get("episode") or {}
    if wanted is None and shown.get("id"):
        wanted = str(shown.get("id"))
    return esc.acknowledge(
        wanted, actor=actor, channel="command_center", now=now or datetime.now(timezone.utc), path=path
    )
