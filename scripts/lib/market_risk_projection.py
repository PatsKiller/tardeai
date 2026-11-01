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
SNAPSHOT_SCHEMA = "MarketRiskSnapshot@v1"
ASSESSMENT_SCHEMA = "MarketRiskAssessment@v1"
TIERS = ("GREEN", "NONE", "BLUE", "YELLOW", "ORANGE", "RED")  # NONE = evaluated, nothing to flag (review #2383, N6)
ACTIONABLE = ("ORANGE", "RED")
# The ONE path the engine writes and every consumer reads, relative to a project root whose data/runtime is the
# persistent-state runtime dir (release dirs symlink it). Review of #2362, B1: the evaluator wrote
# data/runtime/market_risk/latest.json while the CIO, the API and Home read data/runtime/market_risk_latest.json.
SNAPSHOT_REL = "data/runtime/market_risk_latest.json"
# What `market_risk_evaluate.py --shadow` writes (MarketRiskAssessment@v1, mode shadow). Served only while no live
# snapshot exists, always labelled shadow, never with the live episode (review of #2425).
SHADOW_REL = "data/runtime/market_risk/shadow_latest.json"


UNREADABLE_SCHEMA = "MarketRiskSnapshotUnreadable@v1"


def load_snapshot(load, exists=None) -> dict | None:
    """The snapshot consumers should show. ``load(rel) -> dict | None`` reads a JSON file under the project root;
    ``exists(rel) -> bool`` says whether it is on disk (without it, a None load is read as "absent").

    * live snapshot readable -> it;
    * live snapshot ON DISK but unreadable or not an object -> an ``UNREADABLE_SCHEMA`` marker: the projection reads
      not_evaluated with that reason and still carries the live episode. Never the shadow fallback: a stale shadow
      tier must not replace a live one that is merely torn (review of PR 2425 round 4);
    * live snapshot absent -> the shadow assessment, converted and marked ``mode: shadow``; else None."""
    # existence is checked BEFORE the read: a file seen on disk that then fails to load (torn, or deleted mid-read)
    # is "unreadable", never "absent", so a stale shadow tier can never replace it through that race
    on_disk_before = bool(exists(SNAPSHOT_REL)) if exists is not None else None
    live = load(SNAPSHOT_REL)
    if isinstance(live, dict) and live.get("mode") != "shadow":
        return live
    on_disk = on_disk_before if on_disk_before is not None else live is not None
    if on_disk and not isinstance(live, dict):
        return {
            "schema": UNREADABLE_SCHEMA,
            "reason": f"live market-risk snapshot {SNAPSHOT_REL} is on disk but unreadable "
            f"({'not a JSON object' if live is not None else 'torn or unparseable'}); the next evaluation rewrites it",
        }
    sh = load(SHADOW_REL)
    if isinstance(sh, dict):
        sh = snapshot_from_assessment(sh) if sh.get("schema") == ASSESSMENT_SCHEMA else sh
        sh["mode"] = "shadow"
        return sh
    return live if isinstance(live, dict) else None


def _label(category: str) -> str:
    return str(category or "").replace("_", " ").strip().capitalize() or "Unknown"


def _detail(headline: str | None, category: str) -> str | None:
    """Contributor detail without the repeated "Category: " prefix the engine's headlines carry."""
    if not headline:
        return None
    h = str(headline)
    for pre in (f"{_label(category)}:", f"{category}:"):
        if h.lower().startswith(pre.lower()):
            return h[len(pre) :].strip() or None
    return h


def snapshot_from_assessment(doc: dict, *, history: list | None = None) -> dict:
    """MarketRiskAssessment@v1 (the evaluator's output) -> MarketRiskSnapshot@v1 (what Home, Risk, the CIO and
    Ask-the-CIO read). Field mapping: contributor ``category`` -> ``name`` and ``headline`` -> ``detail``; observations
    -> ``categories``; portfolio -> ``book`` (symbols, stop distances, budget names). Never invents a tier."""
    contributors = []
    for c in (doc.get("contributors") or [])[:5]:
        if not isinstance(c, dict):
            continue
        cat = str(c.get("category") or c.get("name") or "")
        contributors.append(
            {
                "name": _label(cat),
                "category": cat,
                "points": c.get("points"),
                "detail": c.get("detail") or _detail(c.get("headline"), cat),
                "as_of": c.get("as_of"),
            }
        )
    categories = []
    for o in doc.get("observations") or []:
        if not isinstance(o, dict):
            continue
        cat = str(o.get("category") or "")
        categories.append(
            {
                "name": _label(cat),
                "category": cat,
                "state": o.get("state"),
                "score": o.get("score"),
                "detail": _detail(o.get("headline"), cat) if o.get("state") != "UNKNOWN" else o.get("reason_unknown"),
                "as_of": o.get("observed_at"),
            }
        )
    conf = doc.get("confirming")
    port = doc.get("portfolio") if isinstance(doc.get("portfolio"), dict) else {}
    book = None
    if port:
        book = {
            "vulnerability": port.get("vulnerability"),
            # budget NAMES only: actual and limit are book-weight percentages and never leave the engine (review #2383, M3)
            "budgets": [
                {
                    "budget": b.get("budget"),
                    "scope": "book" if b.get("scope", "book") == "book" else "account",
                    "breached": True,
                }
                for b in port.get("budget_breaches") or []
                if isinstance(b, dict)
            ],
            "positions": [
                {"symbol": d.get("symbol"), "stop_distance_pct": d.get("stop_distance_pct"), "note": None}
                for d in port.get("drivers") or []
                if isinstance(d, dict) and d.get("symbol")
            ],
            "note": port.get("note") or None,
        }
    up = doc.get("uplift") if isinstance(doc.get("uplift"), dict) else None
    probs = doc.get("probabilities")
    return {
        "schema": SNAPSHOT_SCHEMA,
        "source_schema": doc.get("schema"),
        "as_of": doc.get("as_of"),
        "tier": doc.get("tier"),
        "market_tier": doc.get("market_tier"),
        "score": doc.get("score"),
        "market_score": doc.get("market_score"),
        "confirming": {"n": int(conf), "of": len(categories) or 9} if isinstance(conf, (int, float)) else None,
        "contributors": contributors,
        "categories": categories,
        "deescalates_if": doc.get("deescalates_if"),
        "uplift": (
            {"market_score": up.get("market_score"), "vulnerability": up.get("vulnerability"), "note": up.get("note")}
            if up
            else None
        ),
        "book": book,
        "sectors": doc.get("sectors") or None,
        "shock_type": doc.get("shock_type") or None,
        "heatmap": heatmap_with_sector_fields(doc.get("heatmap"), doc.get("sectors")),
        "leadership": doc.get("leadership") or None,
        "positions": doc.get("positions") or {},
        "reentry_watch": doc.get("reentry_watch") or {},
        "probabilities": probs if isinstance(probs, list) and probs else None,
        "history": list(history or [])[-30:],
        "episode": None,
        "mode": snapshot_mode(doc.get("mode")),
        # the tier rests only on data carried across a closure: shown, labelled "carried — not alerting" (PR 2431)
        "carried_only": bool((doc.get("hysteresis") or {}).get("carried_only")),
    }


def heatmap_with_sector_fields(heatmap: Any, sectors: Any) -> list:
    """Heat-map rows plus ``rs1`` and ``reason_unknown`` from ``sectors.groups`` (design home/v005: the card shows the
    1-day move vs SPY and why a group is not measured; ``sectors.heatmap()`` drops both)."""
    groups = {g.get("key"): g for g in ((sectors or {}).get("groups") or []) if isinstance(g, dict)}
    out = []
    for h in heatmap or []:
        if not isinstance(h, dict):
            continue
        g = groups.get(h.get("key")) or {}
        out.append({**h, "rs1": h.get("rs1", g.get("rs1")), "reason_unknown": h.get("reason_unknown", g.get("reason_unknown"))})
    return out


def snapshot_mode(mode: Any) -> str | None:
    """``live`` for an --apply evaluation, ``shadow`` for --shadow (no alert path ran), else None. Home, the API and
    the CIO see it on every projection so a shadow tier is never mistaken for one the operator was alerted on."""
    m = str(mode or "").lower()
    return "live" if m in ("apply", "live") else "shadow" if m == "shadow" else None


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
    if isinstance(snapshot, dict) and snapshot.get("schema") == ASSESSMENT_SCHEMA:
        snapshot = snapshot_from_assessment(snapshot)
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SNAPSHOT_SCHEMA:
        unreadable = isinstance(snapshot, dict) and snapshot.get("schema") == UNREADABLE_SCHEMA
        return {
            "schema": SCHEMA,
            "state": "not_evaluated",
            "tier": "NOT_EVALUATED",
            "score": None,
            "as_of": None,
            "age_hours": None,
            "stale": False,
            "reason": snapshot.get("reason")
            if unreadable
            else "Market Risk Engine not live yet (DSN-20261031-market-risk-engine P2-T1); only the P0 options-flow detector reports",
            "contributors": [],
            "categories": [],
            # a torn live snapshot keeps the live episode (and its Acknowledge): the episode ledger is still truth
            "episode": episode if unreadable else None,
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
    if snapshot.get("mode") == "shadow":
        episode = None  # a live episode (and its Acknowledge) never rides on a shadow tier (review of #2425)
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
        "sectors": snapshot.get("sectors"),
        "shock_type": snapshot.get("shock_type"),
        "heatmap": heatmap_with_sector_fields(snapshot.get("heatmap"), snapshot.get("sectors")),
        "leadership": snapshot.get("leadership"),
        "positions": snapshot.get("positions") or {},
        "reentry_watch": snapshot.get("reentry_watch") or {},
        "probabilities": snapshot.get("probabilities"),
        "history": list(snapshot.get("history") or [])[-30:],
        "mode": snapshot.get("mode"),
        "carried_only": bool(snapshot.get("carried_only")),
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
    if not str(actor or "").startswith("tailnet:"):
        # the ACK is an operator act: the shared service token (agents, automations) is refused (review #2383, N6)
        return 403, {"ok": False, "error": "acknowledgment needs a signed-in operator (tailnet identity)"}
    wanted = str((body or {}).get("episode_id") or "") or None
    shown = (projection or {}).get("episode") or {}
    if wanted is None and shown.get("id"):
        wanted = str(shown.get("id"))
    # the episode tier the PAGE showed, sent by the client as ``episode_tier`` (the projection here is rebuilt at POST
    # time, so its tier is the server's current one, not what the operator saw — review of #2411, B1). It is required
    # whenever an episode is open and checked under the ledger lock: an ORANGE->RED upgrade that lands after the page
    # rendered is refused with the reason, never silently acknowledged.
    shown_tier = str((body or {}).get("episode_tier") or "").strip() or None
    return esc.acknowledge(
        wanted,
        actor=actor,
        channel="command_center",
        now=now or datetime.now(timezone.utc),
        path=path,
        expected_tier=shown_tier,
        require_expected_tier=True,
    )
