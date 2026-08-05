"""Canonical domain providers for Watch Intelligence (Data Broker layer).

Selection lives here (or in sibling broker modules). The projection composes
these domains; React and page libraries must not re-select sources.

Remaining direct deps documented at module bottom.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ET = ZoneInfo("America/New_York")
ARTIFACTS = PROJECT_ROOT / "data" / "runtime" / "watchlist_intelligence" / "artifacts"
QUARANTINE = PROJECT_ROOT / "data" / "runtime" / "watchlist_intelligence" / "quarantine"
FINGERPRINT_DIR = PROJECT_ROOT / "data" / "runtime" / "watchlist_intelligence" / "fingerprints"
ENRICH_CACHE = PROJECT_ROOT / "data" / "state" / "ticker_enrichment_cache.json"

NEAR_TRIGGER_MAX_PCT = 3.0
QUOTE_STALE_MIN = 90
STREET_STALE_HOURS = 24 * 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _db_query(sql: str, params=None, fetch: str = "all"):
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    if fetch == "one":
        return cur.fetchone()
    return cur.fetchall() or []


# ── Membership / positions ──────────────────────────────────────────────────

def membership_starred() -> set[str]:
    try:
        rows = _db_query("SELECT upper(symbol) AS s FROM operator_starred_symbols")
        return {(r["s"] if hasattr(r, "keys") else r[0]) for r in rows}
    except Exception:
        return set()


def membership_screener() -> set[str]:
    out: set[str] = set()
    try:
        rows = _db_query("SELECT upper(symbol) AS s FROM screener_find_pins WHERE active = true")
        out |= {(r["s"] if hasattr(r, "keys") else r[0]) for r in rows}
    except Exception:
        pass
    try:
        rows = _db_query(
            """
            SELECT DISTINCT upper(symbol) AS s FROM watchlist_items
             WHERE status IN ('active','researched')
               AND (lower(coalesce(source,'')) LIKE '%%screener%%'
                    OR lower(coalesce(trigger_source,'')) LIKE '%%screener%%')
             LIMIT 500
            """
        )
        out |= {(r["s"] if hasattr(r, "keys") else r[0]) for r in rows}
    except Exception:
        pass
    return out


def membership_held() -> tuple[set[str], str]:
    """Return (held symbols, source label). Prefer portfolio_snapshot broker."""
    try:
        from lib.data_broker.portfolio_snapshot import get_portfolio_snapshot
        snap = get_portfolio_snapshot(max_age_s=120) or {}
        holdings = snap.get("holdings") or snap.get("positions") or []
        if not holdings and isinstance(snap.get("data"), dict):
            holdings = snap["data"].get("holdings") or []
        held = set()
        for h in holdings:
            if not isinstance(h, dict) or h.get("is_cash"):
                continue
            s = str(h.get("symbol") or "").upper()
            if not s:
                continue
            if float(h.get("quantity") or h.get("shares") or 0) > 0 or float(h.get("market_value") or 0) > 0:
                held.add(s)
        if held:
            return held, "data_broker.portfolio_snapshot"
    except Exception:
        pass
    # Explicit fallback — file path documented
    try:
        path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        held = set()
        for h in data.get("holdings") or []:
            if h.get("is_cash"):
                continue
            s = str(h.get("symbol") or "").upper()
            if s and (float(h.get("quantity") or h.get("shares") or 0) > 0 or float(h.get("market_value") or 0) > 0):
                held.add(s)
        return held, "fallback:holdings.json"
    except Exception:
        return set(), "unavailable"


def saved_lists_canonical() -> list[dict[str, Any]]:
    """Actual list definitions — prefer watchlist groups/master if present."""
    lists: list[dict[str, Any]] = []
    # Try dedicated list tables first
    for sql, source in [
        (
            """SELECT id::text AS id, name AS label, count(*) OVER () AS n
                 FROM watchlist_groups ORDER BY name LIMIT 80""",
            "watchlist_groups",
        ),
        (
            """SELECT list_id::text AS id, list_name AS label, count(*)::int AS n
                 FROM watchlist_list_membership
                GROUP BY list_id, list_name ORDER BY n DESC LIMIT 80""",
            "watchlist_list_membership",
        ),
    ]:
        try:
            rows = _db_query(sql)
            if rows:
                for r in rows:
                    if hasattr(r, "keys"):
                        lists.append({
                            "id": r.get("id") or r.get("label"),
                            "label": r.get("label") or r.get("id"),
                            "count": r.get("n"),
                            "source": source,
                            "canonical": True,
                        })
                    else:
                        lists.append({"id": r[0], "label": r[1], "count": r[2], "source": source, "canonical": True})
                return lists
        except Exception:
            pass
    # No canonical list table — return empty with typed gap (do NOT substitute directives)
    return []


def saved_list_membership(list_id: str) -> set[str]:
    if not list_id:
        return set()
    try:
        rows = _db_query(
            """SELECT upper(symbol) AS s FROM watchlist_list_membership
                WHERE list_id::text=%s OR list_name=%s""",
            (list_id, list_id),
        )
        return {(r["s"] if hasattr(r, "keys") else r[0]) for r in rows}
    except Exception:
        return set()


# ── Review authorization ────────────────────────────────────────────────────

def authorize_review_artifact(raw: dict[str, Any]) -> tuple[bool, str | None]:
    """COMPLETE only with real authorization + provenance.

    operator_approved=true inside the artifact is NOT authorization.
    """
    if not raw or raw.get("status") == "QUARANTINED" or raw.get("quarantine"):
        return False, "UNVERIFIED_OPERATOR_AUTHORIZATION"
    # Explicit operator command / authorization ledger IDs only
    auth = raw.get("authorization_event_id") or raw.get("operator_command_id") or raw.get("authorized_by_event")
    if not auth:
        # Self-asserted flag is never enough
        if raw.get("operator_approved") is True and not auth:
            return False, "UNVERIFIED_OPERATOR_AUTHORIZATION"
        return False, "UNVERIFIED_OPERATOR_AUTHORIZATION"
    required = (
        "process_id", "provider", "model", "provider_request_id",
        "input_hash", "artifact_id", "artifact_hash",
        "started_at", "completed_at", "requested_policy", "executed_policy",
    )
    for k in required:
        if raw.get(k) in (None, "", "NONE"):
            return False, f"MISSING_{k.upper()}"
    if raw.get("fallback_used") is None:
        return False, "MISSING_FALLBACK_USED"
    # Prefer consumption row with matching provider_request_id
    rid = raw.get("provider_request_id")
    try:
        row = _db_query(
            """SELECT id, success FROM llm_consumption_log
                WHERE provider_request_id=%s LIMIT 1""",
            (rid,),
            fetch="one",
        )
        if not row:
            return False, "CONSUMPTION_REQUEST_ID_UNLINKED"
    except Exception:
        return False, "CONSUMPTION_LOOKUP_FAILED"
    return True, None


def load_review_artifacts(symbol: str) -> dict[str, dict[str, Any]]:
    """Load COMPLETE-eligible artifacts only; never from quarantine."""
    out: dict[str, dict] = {}
    if not ARTIFACTS.exists():
        return out
    sym = symbol.upper()
    for path in ARTIFACTS.glob(f"{sym}_*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        agent = str(raw.get("agent_id") or path.stem.split("_", 1)[-1]).lower()
        ok, reason = authorize_review_artifact(raw)
        if not ok:
            out[agent] = {
                "agent_id": agent,
                "status": "NOT_RUN",
                "reason_code": reason or "UNVERIFIED_OPERATOR_AUTHORIZATION",
                "provider": None,
                "model": None,
                "requested_policy": "NO_CALL",
                "executed_policy": "NO_CALL",
                "estimated_cost_usd": 0.0,
                "display": {
                    "label": f"{agent.upper()} REVIEW: NOT RUN",
                    "provider": "NONE",
                    "model": "NONE",
                    "policy": "NO_CALL",
                    "cost": "$0",
                    "reason": reason,
                },
            }
            continue
        out[agent] = raw
    return out


# ── Enrichment / relative / absolute performance ────────────────────────────

def enrichment_batch(symbols: list[str]) -> dict[str, dict]:
    try:
        raw = json.loads(ENRICH_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    want = {s.upper() for s in symbols}
    return {k.upper(): v for k, v in raw.items() if k.upper() in want and isinstance(v, dict)}


def absolute_performance(enrich: dict) -> dict[str, Any]:
    """Absolute returns only — never label as relative."""
    periods = {
        "1D": _safe_float(enrich.get("change_pct") or enrich.get("change_from_open_pct")),
        "1W": _safe_float(enrich.get("perf_week_pct")),
        "1M": _safe_float(enrich.get("perf_month_pct")),
        "3M": _safe_float(enrich.get("perf_quarter_pct")),
        "6M": _safe_float(enrich.get("perf_halfyr_pct")),
        "YTD": _safe_float(enrich.get("perf_ytd_pct")),
        "1Y": _safe_float(enrich.get("perf_year_pct")),
    }
    parts = []
    for k in ("1D", "1M", "3M", "1Y"):
        v = periods.get(k)
        if v is not None:
            parts.append(f"{v:+.1f}% {k}")
    return {
        "kind": "absolute",
        "periods": periods,
        "summary": " · ".join(parts) if parts else None,
        "label": "Absolute performance (not vs industry/sector/SPY)",
    }


def relative_performance_gaps() -> dict[str, Any]:
    return {
        "kind": "relative",
        "versus_industry": None,
        "versus_sector": None,
        "versus_spy": None,
        "quality_state": "UNAVAILABLE",
        "missing": ["versus_industry", "versus_sector", "versus_spy"],
        "note": "Industry/sector/SPY relative deltas not joined in broker yet",
    }


# ── Near trigger ────────────────────────────────────────────────────────────

def near_trigger_eval(card: dict, *, max_pct: float = NEAR_TRIGGER_MAX_PCT) -> dict[str, Any]:
    last = _safe_float(card.get("last"))
    # Prefer resistance as breakout trigger for long-biased WAIT; else support reclaim
    resistance = _safe_float(card.get("resistance"))
    support = _safe_float(card.get("support"))
    state = (card.get("trade_ai_state") or "").upper()
    tech_fresh = (card.get("freshness_state") or "").upper()
    if state != "WAIT" or last is None or last <= 0:
        return {"is_near": False, "reason": "not_wait_or_no_price"}
    if tech_fresh in ("STALE", "DATA_UNAVAILABLE"):
        return {"is_near": False, "reason": "technical_or_quote_not_fresh", "freshness_state": tech_fresh}
    candidates = []
    if resistance is not None and resistance > 0:
        dist = abs(resistance - last) / last * 100
        candidates.append({"trigger_level": resistance, "kind": "resistance_reclaim", "distance_pct": dist})
    if support is not None and support > 0:
        dist = abs(last - support) / last * 100
        candidates.append({"trigger_level": support, "kind": "support_hold", "distance_pct": dist})
    if not candidates:
        return {"is_near": False, "reason": "no_trigger_level"}
    best = min(candidates, key=lambda x: x["distance_pct"])
    near = best["distance_pct"] <= max_pct
    return {
        "is_near": near,
        "trigger_level": best["trigger_level"],
        "trigger_kind": best["kind"],
        "current_price": last,
        "distance_pct": round(best["distance_pct"], 4),
        "max_near_pct": max_pct,
        "confirmation_rule": "price within max_near_pct of trigger and quote not STALE",
        "freshness_state": tech_fresh,
        "reason": "within_threshold" if near else "outside_threshold",
    }


# ── Reviewed today ──────────────────────────────────────────────────────────

def market_date_et(now: datetime | None = None) -> str:
    ref = now or _now()
    return ref.astimezone(ET).date().isoformat()


def completed_today(completed_at: Any) -> bool:
    if not completed_at:
        return False
    try:
        if isinstance(completed_at, str):
            dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        else:
            dt = completed_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ET).date().isoformat() == market_date_et()
    except Exception:
        return False


# ── Material change / fingerprints ──────────────────────────────────────────

def material_fingerprint(card: dict) -> str:
    payload = {
        "symbol": card.get("symbol"),
        "trade_ai_state": card.get("trade_ai_state"),
        "street_rating": card.get("street_rating"),
        "last": card.get("last"),
        "proposal_allowed": card.get("proposal_allowed"),
        "primary_risk": card.get("primary_risk"),
        "cio_status": (card.get("cio_review") or {}).get("status"),
        "maria_status": (card.get("maria_review") or {}).get("status"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:32]


def material_change_vs_prior(symbol: str, fp: str) -> bool:
    FINGERPRINT_DIR.mkdir(parents=True, exist_ok=True)
    path = FINGERPRINT_DIR / f"{symbol.upper()}.json"
    prior = None
    if path.exists():
        try:
            prior = json.loads(path.read_text()).get("fingerprint")
        except Exception:
            prior = None
    changed = prior is not None and prior != fp
    path.write_text(json.dumps({"fingerprint": fp, "updated_at": _now().isoformat()}, indent=2))
    return changed


# ── Ranking (Top Ideas) ─────────────────────────────────────────────────────

RANK_VERSION = "top_ideas.v1"


def rank_top_ideas(items: list[dict]) -> list[dict]:
    """Dynamic rank — never DEFAULT_PRIORITY hard-wiring."""
    scored = []
    for it in items:
        c = it.get("card") or {}
        street = {"STRONG BUY": 40, "BUY": 28, "HOLD": 10, "SELL": 0, "NOT RATED": 5}.get(c.get("street_rating") or "NOT RATED", 5)
        state = c.get("trade_ai_state") or ""
        state_pts = {"READY": 30, "WAIT": 18, "MANAGING": 12, "REVIEW_PENDING": 10}.get(state, 0)
        if state in ("DETERMINISTIC_FAIL", "BLOCKED", "AVOID", "DATA_UNAVAILABLE"):
            state_pts = -5
        upside = _safe_float(c.get("implied_upside_pct")) or 0
        upside_pts = max(-10, min(20, upside / 5))
        starred = 8 if c.get("starred") else 0
        held = 4 if c.get("held") else 0
        review = 0
        if (c.get("maria_review") or {}).get("status") == "COMPLETE":
            review += 3
        if (c.get("cio_review") or {}).get("status") == "COMPLETE":
            review += 3
        # Prefer non-stale quotes
        fresh = 5 if (c.get("freshness_state") or "") in ("CURRENT", "PREMARKET_CURRENT", "AFTER_HOURS_CURRENT") else 0
        total = street + state_pts + upside_pts + starred + held + review + fresh
        components = {
            "street": street,
            "trade_ai_state": state_pts,
            "upside": round(upside_pts, 2),
            "starred": starred,
            "held": held,
            "reviews": review,
            "freshness": fresh,
        }
        scored.append((total, components, it))
    scored.sort(key=lambda x: (-x[0], (x[2].get("card") or {}).get("symbol") or ""))
    out = []
    gen_at = _now().isoformat()
    for i, (total, components, it) in enumerate(scored, 1):
        it = dict(it)
        card = dict(it.get("card") or {})
        card["rank"] = i
        card["rank_score"] = round(total, 2)
        card["rank_components"] = components
        card["rank_generated_at"] = gen_at
        card["rank_version"] = RANK_VERSION
        it["card"] = card
        out.append(it)
    return out


# ── Snapshot / quality ──────────────────────────────────────────────────────

def content_snapshot_id(items: list[dict], *, view: str, query: dict) -> str:
    """Hash complete projected content excluding generated_at transport noise."""
    payload = {
        "view": view,
        "query": {k: v for k, v in (query or {}).items() if k not in ("_",)},
        "items": [
            {
                "symbol": i.get("symbol"),
                "card": {
                    k: (i.get("card") or {}).get(k)
                    for k in (
                        "symbol", "street_rating", "trade_ai_state", "last", "day_change_pct",
                        "quote_id", "source_record_id", "freshness_state", "starred", "held",
                        "screener_origin", "rank", "rank_score", "material_change",
                        "implied_upside_pct", "target_mean", "absolute_performance_summary",
                        "next_review_at", "next_review_condition",
                        "cio_review", "maria_review",
                    )
                },
            }
            for i in items
        ],
        "contract": "watch_intelligence.broker.v1",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:32]


def assess_data_quality(items: list[dict]) -> dict[str, Any]:
    missing: dict[str, int] = {}
    for it in items:
        c = it.get("card") or {}
        if c.get("last") is None:
            missing["CanonicalQuote"] = missing.get("CanonicalQuote", 0) + 1
        if not c.get("company_summary"):
            missing["SymbolIdentity.company_summary"] = missing.get("SymbolIdentity.company_summary", 0) + 1
        if c.get("versus_industry") is None and c.get("relative_vs_industry") is None:
            missing["RelativePerformance.versus_industry"] = missing.get("RelativePerformance.versus_industry", 0) + 1
        if not c.get("business_model"):
            missing["BusinessModel"] = missing.get("BusinessModel", 0) + 1
    n = max(1, len(items))
    critical = missing.get("CanonicalQuote", 0)
    if critical == n:
        status = "UNAVAILABLE"
    elif missing:
        # if more than half missing relative or identity
        status = "PARTIAL" if critical == 0 else "DEGRADED"
    else:
        status = "COMPLETE"
    return {
        "status": status,
        "missing_domains": missing,
        "item_count": len(items),
        "reasons": [f"{k}:{v}" for k, v in sorted(missing.items())],
    }


# Direct dependencies still outside pure domain modules (documented):
# - decision_packets via lib.rockville.live_projection (Trade AI)
# - enrichment cache file for absolute performance / fundamentals fields
# - watchlist_strategy_cards for support/resistance
# - holdings.json only as portfolio_snapshot fallback
DIRECT_DEPENDENCIES = {
    "database": [
        "operator_starred_symbols",
        "screener_find_pins",
        "watchlist_items",
        "yahoo_analyst_targets_history",
        "catalyst_events",
        "watchlist_strategy_cards",
        "decision_packets (via rockville projection)",
        "llm_consumption_log (review auth)",
        "llm_cost_reservations (audit only)",
    ],
    "filesystem": [
        "data/state/ticker_enrichment_cache.json (absolute perf/fundamentals)",
        "data/portfolios/state/holdings.json (fallback positions only)",
        "data/runtime/watchlist_intelligence/artifacts (authorized reviews)",
        "data/runtime/watchlist_intelligence/quarantine (excluded)",
    ],
    "why_not_yet_broker": [
        "No saved-list membership table in DB on this host — returns empty canonical lists",
        "No industry/sector/SPY relative performance provider yet",
        "Trade AI still projected via rockville.live_projection until decision broker domain is split",
    ],
}
