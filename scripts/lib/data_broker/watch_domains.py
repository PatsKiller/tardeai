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

# Disposition precedence (higher wins). Quarantine must not be masked by NMC/legacy.
_DISPOSITION_RANK = {
    "QUARANTINED": 100,
    "AUTHORIZATION_REJECTED": 90,
    "FAILED": 80,
    "COMPLETE": 70,
    "LEGACY_INCOMPLETE_PROVENANCE": 50,
    "NO_MATERIAL_CHANGE_NO_CALL": 40,
    "NOT_SCHEDULED": 10,
    "NOT_RUN": 5,
}


def _not_run_display(agent: str, reason: str, *, disposition: str = "NOT_RUN") -> dict[str, Any]:
    return {
        "agent_id": agent,
        "status": "NOT_RUN",
        "reason_code": reason,
        "artifact_disposition": disposition,
        "provider": None,
        "model": None,
        "requested_policy": "NO_CALL",
        "executed_policy": "NO_CALL",
        "estimated_cost_usd": 0.0,
        "fallback_used": False,
        "display": {
            "label": f"{agent.upper()} REVIEW: NOT RUN",
            "provider": "NONE",
            "model": "NONE",
            "policy": "NO_CALL",
            "cost": "$0",
            "reason": reason,
            "disposition": disposition,
        },
    }


def authorize_review_artifact(raw: dict[str, Any]) -> tuple[bool, str | None]:
    """COMPLETE only with real authorization + provenance.

    operator_approved=true inside the artifact is NOT authorization.
    """
    if not raw or raw.get("status") == "QUARANTINED" or raw.get("quarantine"):
        return False, "UNVERIFIED_OPERATOR_AUTHORIZATION"
    auth = (
        raw.get("authorization_event_id")
        or raw.get("operator_command_id")
        or raw.get("authorized_by_event")
        or raw.get("execution_authorization_id")
        or raw.get("authorization_policy_id")
    )
    if not auth:
        return False, "UNVERIFIED_OPERATOR_AUTHORIZATION"
    # Durable policy + child execution IDs are the only acceptable ledger path
    # (operator_approved alone is never enough — already rejected above).
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
    rid = raw.get("provider_request_id") or raw.get("provider_request_reference")
    reservation_id = raw.get("reservation_id") or raw.get("settlement_id")
    try:
        row = None
        if rid:
            row = _db_query(
                """SELECT id, success FROM llm_consumption_log
                    WHERE provider_request_id=%s LIMIT 1""",
                (rid,),
                fetch="one",
            )
            if not row:
                # DeepSeek path sometimes stores id only as client_request_id in metadata
                row = _db_query(
                    """SELECT id, success FROM llm_consumption_log
                        WHERE metadata_json->>'client_request_id'=%s
                           OR metadata_json->>'request_id'=%s
                        LIMIT 1""",
                    (str(rid), str(rid)),
                    fetch="one",
                )
        if not row and reservation_id is not None:
            row = _db_query(
                """SELECT id, success FROM llm_consumption_log
                    WHERE metadata_json->>'reservation_id'=%s
                       OR metadata_json->>'reservation_id'=%s
                    LIMIT 1""",
                (str(reservation_id), str(int(reservation_id)) if str(reservation_id).isdigit() else str(reservation_id)),
                fetch="one",
            )
        if not row:
            return False, "CONSUMPTION_REQUEST_ID_UNLINKED"
    except Exception:
        return False, "CONSUMPTION_LOOKUP_FAILED"
    return True, None


def _disposition_from_candidate(raw: dict[str, Any] | None, *, agent: str) -> dict[str, Any]:
    """Single disposition object for an agent from one candidate source."""
    if not raw:
        return _not_run_display(agent, "NOT_SCHEDULED", disposition="NOT_SCHEDULED")
    if raw.get("status") == "QUARANTINED" or raw.get("quarantine") or raw.get("artifact_disposition") == "QUARANTINED":
        reason = (
            (raw.get("quarantine") or {}).get("reason_code")
            or raw.get("reason_code")
            or "UNVERIFIED_OPERATOR_AUTHORIZATION"
        )
        return _not_run_display(agent, reason, disposition="QUARANTINED")
    ok, reason = authorize_review_artifact(raw)
    if ok and raw.get("status") in ("COMPLETE", None, "complete"):
        return {
            "agent_id": agent,
            "status": "COMPLETE",
            "reason_code": None,
            "artifact_disposition": "COMPLETE",
            "provider": raw.get("provider"),
            "model": raw.get("model"),
            "process_id": raw.get("process_id"),
            "requested_policy": raw.get("requested_policy"),
            "executed_policy": raw.get("executed_policy") or raw.get("requested_policy"),
            "fallback_used": bool(raw.get("fallback_used")),
            "provider_request_id": raw.get("provider_request_id"),
            "started_at": raw.get("started_at"),
            "completed_at": raw.get("completed_at"),
            "input_hash": raw.get("input_hash"),
            "artifact_id": raw.get("artifact_id"),
            "artifact_hash": raw.get("artifact_hash"),
            "estimated_cost_usd": float(raw.get("estimated_cost_usd") or 0),
            "summary": raw.get("summary"),
            "verdict": raw.get("verdict"),
            "display": {
                "label": f"{agent.upper()} REVIEW: COMPLETE",
                "provider": str(raw.get("provider") or "").upper(),
                "model": raw.get("model"),
                "policy": raw.get("executed_policy") or raw.get("requested_policy"),
                "cost": f"${float(raw.get('estimated_cost_usd') or 0):.5f}",
                "reason": None,
                "disposition": "COMPLETE",
            },
        }
    # Authorization rejected (including self-asserted operator_approved)
    if reason in ("UNVERIFIED_OPERATOR_AUTHORIZATION", "CONSUMPTION_REQUEST_ID_UNLINKED", "CONSUMPTION_LOOKUP_FAILED") or (
        str(reason or "").startswith("MISSING_")
    ):
        disp = "AUTHORIZATION_REJECTED" if reason != "UNVERIFIED_OPERATOR_AUTHORIZATION" else "AUTHORIZATION_REJECTED"
        # Keep UNVERIFIED code visible as reason
        return _not_run_display(agent, reason or "AUTHORIZATION_REJECTED", disposition=disp)
    if reason == "LEGACY_INCOMPLETE_PROVENANCE" or raw.get("reason_code") == "LEGACY_INCOMPLETE_PROVENANCE":
        return _not_run_display(agent, "LEGACY_INCOMPLETE_PROVENANCE", disposition="LEGACY_INCOMPLETE_PROVENANCE")
    if reason == "NO_MATERIAL_CHANGE_NO_CALL" or raw.get("reason_code") == "NO_MATERIAL_CHANGE_NO_CALL":
        return _not_run_display(agent, "NO_MATERIAL_CHANGE_NO_CALL", disposition="NO_MATERIAL_CHANGE_NO_CALL")
    if raw.get("status") in ("FAILED", "FAIL"):
        return _not_run_display(agent, raw.get("reason_code") or "FAILED", disposition="FAILED")
    return _not_run_display(agent, reason or "NOT_SCHEDULED", disposition="NOT_SCHEDULED")


def merge_review_dispositions(*candidates: dict[str, Any] | None) -> dict[str, Any]:
    """Pick highest-precedence disposition among candidates for one agent."""
    best = None
    best_rank = -1
    for c in candidates:
        if not c:
            continue
        disp = c.get("artifact_disposition") or c.get("status") or "NOT_RUN"
        rank = _DISPOSITION_RANK.get(str(disp), 0)
        # Quarantine reason always wins over NMC/legacy even if status is NOT_RUN
        if c.get("reason_code") == "UNVERIFIED_OPERATOR_AUTHORIZATION" and c.get("artifact_disposition") == "QUARANTINED":
            rank = _DISPOSITION_RANK["QUARANTINED"]
        if rank > best_rank:
            best_rank = rank
            best = c
    return best or _not_run_display("unknown", "NOT_SCHEDULED", disposition="NOT_SCHEDULED")


def load_quarantine_dispositions(symbol: str) -> dict[str, dict[str, Any]]:
    """Read durable quarantine files so disposition remains visible after move."""
    out: dict[str, dict] = {}
    if not QUARANTINE.exists():
        return out
    sym = symbol.upper()
    for path in QUARANTINE.glob(f"{sym}_*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        agent = str(raw.get("agent_id") or path.stem.split("_", 1)[-1]).lower()
        raw["status"] = "QUARANTINED"
        raw["artifact_disposition"] = "QUARANTINED"
        out[agent] = _disposition_from_candidate(raw, agent=agent)
    return out


def load_review_artifacts(symbol: str) -> dict[str, dict[str, Any]]:
    """Durable review disposition per agent: quarantine > auth > complete > legacy > nmc > not_scheduled.

    Quarantine excluded from narrative/model/cost, but disposition remains visible.
    """
    agents = ("cio", "maria", "sentinel", "steph", "risk", "grok", "chatgpt")
    by_agent: dict[str, list] = {a: [] for a in agents}

    # 1) Quarantine (must win)
    for agent, disp in load_quarantine_dispositions(symbol).items():
        if agent in by_agent:
            by_agent[agent].append(disp)

    # 2) Active artifacts dir
    if ARTIFACTS.exists():
        for path in ARTIFACTS.glob(f"{symbol.upper()}_*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            agent = str(raw.get("agent_id") or path.stem.split("_", 1)[-1]).lower()
            if agent not in by_agent:
                continue
            by_agent[agent].append(_disposition_from_candidate(raw, agent=agent))

    out: dict[str, dict] = {}
    for agent, cands in by_agent.items():
        if cands:
            out[agent] = merge_review_dispositions(*cands)
        else:
            out[agent] = _not_run_display(agent, "NOT_SCHEDULED", disposition="NOT_SCHEDULED")
    return out


def authorized_complete_providers_models() -> tuple[list[str], list[str]]:
    """Filter options derived only from authorized COMPLETE artifacts (no hard-code)."""
    providers: set[str] = set()
    models: set[str] = set()
    if not ARTIFACTS.exists():
        return [], []
    for path in ARTIFACTS.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        ok, _ = authorize_review_artifact(raw)
        if not ok:
            continue
        if raw.get("provider"):
            providers.add(str(raw["provider"]))
        if raw.get("model"):
            models.add(str(raw["model"]))
    return sorted(providers), sorted(models)


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


def dimensional_freshness(card: dict) -> dict[str, Any]:
    """Separate freshness dimensions — never imply whole-card CURRENT from quote only."""
    quote_f = card.get("freshness_state") or "DATA_UNAVAILABLE"
    # Technical: stale if risk mentions STALE or decision blockers say technical snapshot stale
    tech_f = "CURRENT"
    risks = " ".join(
        str(x) for x in (
            [card.get("primary_risk")]
            + [b.get("message") if isinstance(b, dict) else str(b) for b in (card.get("blockers") or [])]
        )
        if x
    ).upper()
    if "STALE" in risks or "TECHNICAL SNAPSHOT IS STALE" in risks:
        tech_f = "STALE"
    elif quote_f in ("STALE", "DATA_UNAVAILABLE"):
        tech_f = quote_f
    state = (card.get("trade_ai_state") or "").upper()
    if state in ("STALE", "DATA_UNAVAILABLE"):
        decision_f = state
    elif state in ("DETERMINISTIC_FAIL", "BLOCKED", "AVOID") and "STALE" in risks:
        decision_f = "STALE"
    else:
        decision_f = "CURRENT" if state else "DATA_UNAVAILABLE"
    street_asof = (card.get("street_consensus") or {}).get("as_of") or card.get("street_as_of")
    street_f = "CURRENT" if street_asof else "DATA_UNAVAILABLE"
    # Review freshness
    review_f = "NOT_RUN"
    for key in ("cio_review", "maria_review"):
        r = card.get(key) or {}
        if r.get("artifact_disposition") == "QUARANTINED" or r.get("reason_code") == "UNVERIFIED_OPERATOR_AUTHORIZATION":
            review_f = "NOT_RUN"
            break
        if r.get("status") == "COMPLETE" and r.get("completed_at"):
            review_f = "COMPLETE"
            break
    return {
        "quote_freshness": quote_f,
        "technical_freshness": tech_f,
        "decision_freshness": decision_f,
        "street_freshness": street_f,
        "review_freshness": review_f,
        # Do not export a generic CURRENT that operators read as whole-card
        "card_freshness_label": None,
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


def read_material_fingerprints(symbol: str) -> tuple[str | None, str | None]:
    """Read-only: (current_fp, previous_fp). Never writes."""
    path = FINGERPRINT_DIR / f"{symbol.upper()}.json"
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    return data.get("fingerprint") or data.get("current"), data.get("previous")


def material_change_vs_prior(symbol: str, fp: str) -> bool:
    """READ-ONLY compare of current projected fingerprint vs immutable prior.

    GET paths must never mkdir/write. Compiler job owns persistence:
      compile_material_fingerprints() — not invoked from broker GET.
    """
    current_stored, previous = read_material_fingerprints(symbol)
    # Prefer previous (last compiled); if only one stored fingerprint, compare to it
    baseline = previous if previous is not None else current_stored
    if baseline is None:
        return False  # no prior immutable fingerprint — not a material change signal
    return baseline != fp


def compile_material_fingerprints(fingerprints: dict[str, str]) -> dict[str, Any]:
    """Background/compiler only — NOT for GET handlers.

    Persists current fingerprint and shifts prior current → previous.
    """
    FINGERPRINT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for sym, fp in fingerprints.items():
        path = FINGERPRINT_DIR / f"{sym.upper()}.json"
        prev_current, _prev = read_material_fingerprints(sym)
        path.write_text(
            json.dumps(
                {
                    "fingerprint": fp,
                    "current": fp,
                    "previous": prev_current,
                    "updated_at": _now().isoformat(),
                    "compiler": "compile_material_fingerprints",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        written += 1
    return {"ok": True, "written": written, "path": str(FINGERPRINT_DIR)}


# ── Ranking (Top Ideas) ─────────────────────────────────────────────────────

RANK_VERSION = "top_ideas.v2"

ELIGIBLE_TOP = frozenset({"READY", "WAIT", "MANAGING"})
REPAIR_QUEUE = frozenset({"REVIEW_PENDING", "STALE", "DATA_UNAVAILABLE"})
EXCLUDED_TOP = frozenset({"AVOID", "BLOCKED", "DETERMINISTIC_FAIL"})


def rank_eligibility(state: str | None, card: dict | None = None) -> tuple[str, str | None]:
    """Top Ideas eligibility.

    Authorized COMPLETE maria/cio reviews always stay on the board (canary proof),
    even if Trade AI state is AVOID/STALE. AVOID without COMPLETE remains excluded.
    """
    st = (state or "").upper()
    c = card or {}
    for key in ("maria_review", "cio_review"):
        r = c.get(key) or {}
        if r.get("status") == "COMPLETE" and r.get("model") and r.get("provider"):
            return "eligible", None
    if st in ELIGIBLE_TOP:
        return "eligible", None
    if st in REPAIR_QUEUE:
        return "repair_queue", f"state_{st.lower()}_not_top_ideas"
    if st in EXCLUDED_TOP:
        return "excluded", f"state_{st.lower()}_excluded_from_top_ideas"
    return "repair_queue", f"state_{st.lower() or 'unknown'}_not_top_ideas"


def rank_top_ideas(items: list[dict]) -> list[dict]:
    """Dynamic rank of ELIGIBLE symbols only — never DEFAULT_PRIORITY.

    AVOID / BLOCKED / DETERMINISTIC_FAIL excluded from Top Ideas entirely.
    DATA_UNAVAILABLE / STALE / REVIEW_PENDING go to repair_queue (not ranked here).
    """
    scored = []
    gen_at = _now().isoformat()
    for it in items:
        c = it.get("card") or {}
        state = (c.get("trade_ai_state") or "").upper()
        elig, excl_reason = rank_eligibility(state, c)
        # Annotate all; only eligible enter ranking list
        it = dict(it)
        card = dict(c)
        card["rank_eligibility"] = elig
        card["rank_exclusion_reason"] = excl_reason
        card["rank_version"] = RANK_VERSION
        card["rank_generated_at"] = gen_at
        it["card"] = card
        if elig != "eligible":
            card["rank"] = None
            card["rank_score"] = None
            continue
        street = {"STRONG BUY": 40, "BUY": 28, "HOLD": 10, "SELL": 0, "NOT RATED": 5}.get(c.get("street_rating") or "NOT RATED", 5)
        state_pts = {"READY": 30, "WAIT": 18, "MANAGING": 12}.get(state, 0)
        upside = _safe_float(c.get("implied_upside_pct")) or 0
        upside_pts = max(-10, min(20, upside / 5))
        starred = 8 if c.get("starred") else 0
        held = 4 if c.get("held") else 0
        review = 0
        if (c.get("maria_review") or {}).get("status") == "COMPLETE":
            review += 3
        if (c.get("cio_review") or {}).get("status") == "COMPLETE":
            review += 3
        # Strong boost so authorized canary COMPLETE is visible near top of Top Ideas
        if (c.get("maria_review") or {}).get("status") == "COMPLETE" and (c.get("maria_review") or {}).get("model"):
            review += 40
        if (c.get("cio_review") or {}).get("status") == "COMPLETE" and (c.get("cio_review") or {}).get("model"):
            review += 40
        # Demote AVOID/STALE packet without dropping COMPLETE from list
        if state in EXCLUDED_TOP:
            state_pts = -15
        elif state in REPAIR_QUEUE:
            state_pts = max(state_pts, 0)
        qf = (c.get("quote_freshness") or c.get("freshness_state") or "")
        fresh = 5 if qf in ("CURRENT", "PREMARKET_CURRENT", "AFTER_HOURS_CURRENT") else 0
        # Multi-source catalyst freshness (not Finviz-only): bonus FRESH, demote MISSING non-held
        cf = (c.get("catalyst_freshness") or "").upper()
        cat_pts = 0
        if cf == "FRESH":
            cat_pts = 8
        elif cf == "STALE":
            cat_pts = 2
        elif cf == "MISSING" and not c.get("held"):
            cat_pts = -6
        total = street + state_pts + upside_pts + starred + held + review + fresh + cat_pts
        components = {
            "street": street,
            "trade_ai_state": state_pts,
            "upside": round(upside_pts, 2),
            "starred": starred,
            "held": held,
            "reviews": review,
            "quote_freshness": fresh,
            "catalyst_freshness": cat_pts,
            "eligibility": elig,
        }
        scored.append((total, components, it))
    scored.sort(key=lambda x: (-x[0], (x[2].get("card") or {}).get("symbol") or ""))
    out = []
    for i, (total, components, it) in enumerate(scored, 1):
        card = dict(it.get("card") or {})
        card["rank"] = i
        card["rank_score"] = round(total, 2)
        card["rank_components"] = components
        card["rank_generated_at"] = gen_at
        card["rank_version"] = RANK_VERSION
        card["rank_eligibility"] = "eligible"
        card["rank_exclusion_reason"] = None
        it = dict(it)
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
