"""Active Trader Stage 0 read API — health/status/sessions + Stage 1a venue eligibility."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from .flags import Stage0Flags, load_flags

READ_API_CONTRACT = "active-trader-stage0-read-api-v1"
STAGE = 0

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Product intent venues (2026-07-27). Stage 0: inventory only — all live flags false.
VENUE_IDS = ("schwab", "moomoo", "alpaca")


def _load_compliance_fixtures() -> dict[str, Any]:
    """Read-only compliance/tradeability snapshot (fixture at Stage 1a). Prefers a live
    config file, falls back to the committed example, then to a minimal safe default.
    Never raises — returns {} at worst so eligibility fails closed to 'unknown'."""
    candidates = []
    env = os.environ.get("ACTIVE_TRADER_COMPLIANCE_FIXTURES", "").strip()
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(_REPO_ROOT / "config" / "active_trader_compliance_fixtures.json")
    candidates.append(_REPO_ROOT / "config" / "active_trader_compliance_fixtures.example.json")
    for p in candidates:
        try:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


def capability_snapshot(flags: Stage0Flags | None = None) -> dict[str, Any]:
    """Build the read-only capability snapshot the venue-eligibility evaluator consumes.

    Combines the venue inventory (roles) with the compliance fixtures (per-symbol Schwab
    blocks + venue availability / operator opt-in). All order/execution authority stays
    false — this only informs eligibility + the operator-prompt UX contract."""
    inv = venue_inventory(flags)
    fx = _load_compliance_fixtures()
    fx_venues = fx.get("venues") if isinstance(fx.get("venues"), Mapping) else {}
    venues: dict[str, Any] = {}
    for vid in VENUE_IDS:
        base = dict(inv.get(vid) or {})
        extra = fx_venues.get(vid) if isinstance(fx_venues.get(vid), Mapping) else {}
        # merge fixture availability/opt-in/coverage over the inventory role (no order auth)
        merged = {**base, **{k: v for k, v in extra.items() if k != "order_path"}}
        merged["order_path"] = False
        venues[vid] = merged
    compliance = fx.get("symbol_compliance") if isinstance(fx.get("symbol_compliance"), Mapping) else {}
    return {
        "venues": venues,
        "symbol_compliance": dict(compliance),
        "source": "fixtures" if fx else "empty",
        "read_only": True,
    }


def _load_near_ready_fixtures() -> list[dict[str, Any]]:
    """Read-only near-ready candidate inputs (fixture at Stage 1b). Prefers a live config
    file, falls back to the committed example, then to an empty list. Never raises — an
    empty list yields an honest empty candidate set."""
    candidates_paths = []
    env = os.environ.get("ACTIVE_TRADER_NEAR_READY_FIXTURES", "").strip()
    if env:
        candidates_paths.append(Path(env).expanduser())
    candidates_paths.append(_REPO_ROOT / "config" / "active_trader_near_ready_fixtures.json")
    candidates_paths.append(_REPO_ROOT / "config" / "active_trader_near_ready_fixtures.example.json")
    for p in candidates_paths:
        try:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                rows = data.get("candidates") if isinstance(data, Mapping) else data
                if isinstance(rows, list):
                    return [r for r in rows if isinstance(r, Mapping)]
        except Exception:
            continue
    return []


def near_ready_candidates(
    flags: Stage0Flags | None = None,
    *,
    include_watch: bool = False,
    join_venue: bool = True,
) -> dict[str, Any]:
    """Build the read-only near-ready candidate set from fixtures (or, later, live scanner/
    watch payloads). Pure scoring via near_ready.select_near_ready. When join_venue is set,
    annotates each row with the Stage 1a venue-eligibility *prompt_required* flag only — no
    routing, no auto-switch, no order authority."""
    from .near_ready import select_near_ready, CONTRACT as NEAR_READY_CONTRACT
    raw = _load_near_ready_fixtures()
    rows = select_near_ready(raw, include_watch=include_watch)
    if join_venue and rows:
        from .venue_eligibility import evaluate_eligibility
        snap = capability_snapshot(flags)
        for r in rows:
            # empty venue string -> evaluator's Schwab-primary default (no venue hardcoded)
            elig = evaluate_eligibility(r.get("symbol") or "", "", snap)
            r["venue_status"] = elig.status
            r["venue_prompt_required"] = bool(elig.prompt_required)
            r["venue_auto_route"] = False
    return {
        "contract": NEAR_READY_CONTRACT,
        "candidates": rows,
        "source": "fixtures" if raw else "empty",
    }


def venue_inventory(flags: Stage0Flags | None = None) -> dict[str, dict[str, Any]]:
    """Read-only venue matrix. data/execution always false at Stage 0."""
    _ = flags
    out: dict[str, dict[str, Any]] = {}
    roles = {
        "schwab": "primary_execution_when_eligible",
        "moomoo": "augment_on_schwab_block_plus_l2_tape",
        "alpaca": "augment_execution_alternate",
    }
    for vid in VENUE_IDS:
        out[vid] = {
            "data": False,
            "execution": False,
            "read_only_inventory": True,
            "order_path": False,
            "role_intent": roles[vid],
        }
    return out


def _scalp_registry_view() -> dict[str, Any]:
    """Read-only projection of the scalp setup registry (config/scalp_setup_registry.yaml). Fail-closed
    to an empty registry on any error — never raises, never writes."""
    try:
        import sys as _sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in _sys.path:
            _sys.path.insert(0, sp)
        import scalp_setup_registry as _reg
        return _reg.public_view()
    except Exception:
        return {"registry_version": None, "setups": [], "read_only": True,
                "write_authority": False, "error": "registry_unavailable"}


def _scalp_setup_events(limit: int = 50, session_date: str | None = None,
                        setup: str | None = None) -> tuple[list[dict[str, Any]], str]:
    """Read-only recent setup-tagged events. Fail-closed to ([], 'unavailable') if the DB/table/columns
    are absent (e.g. before the additive migration runs). Never writes."""
    try:
        import sys as _sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in _sys.path:
            _sys.path.insert(0, sp)
        from db_adapter import get_connection
    except Exception:
        return [], "unavailable"
    lim = max(1, min(int(limit or 50), 500))
    sql = ("SELECT symbol, fired_at, session_date, lane, primary_setup_id, primary_setup_label, "
           "matched_setup_labels, setup_state, market_session, confirmation_labels, setup_version, "
           "registry_hash FROM scalp_ignition_events WHERE primary_setup_id IS NOT NULL")
    params: list[Any] = []
    if session_date:
        sql += " AND session_date = %s"; params.append(session_date)
    if setup:
        sql += " AND primary_setup_id = %s"; params.append(setup)
    sql += " ORDER BY fired_at DESC LIMIT %s"; params.append(lim)
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
        return rows, "db"
    except Exception:
        return [], "unavailable"


# ActiveTrader account posture (product policy). `eligible` reflects REAL live-routability (false for
# every venue in this build); the UI may make them selectable in DRY-RUN mode but NOTHING is submitted.
_ACTIVE_TRADER_ACCOUNTS: list[dict[str, Any]] = [
    {"id": "schwab-taxable", "venue": "schwab", "label": "Schwab Taxable", "maskedNumber": "…123",
     "permissionLabel": "margin / short OK · integration read-only", "buyingPower": 0,
     "eligible": False, "eligibilityReason": "Live route not authorized (dry-run visibility only)",
     "paper": False, "readOnly": True, "maxShares": 500},
    {"id": "schwab-rollover", "venue": "schwab", "label": "Schwab Rollover IRA", "maskedNumber": "…258",
     "permissionLabel": "long only / no margin · integration read-only", "buyingPower": 0,
     "eligible": False, "eligibilityReason": "Live route not authorized (dry-run visibility only)",
     "paper": False, "readOnly": True, "maxShares": 300},
    {"id": "alpaca-paper", "venue": "alpaca_paper", "label": "Alpaca Paper", "maskedNumber": "PA-tradeai",
     "permissionLabel": "paper / manual confirmation only", "buyingPower": 100000,
     "eligible": True, "paper": True, "readOnly": False, "maxShares": 500},
    {"id": "alpaca-live", "venue": "alpaca_live", "label": "Alpaca Taxable Live", "maskedNumber": "…LIVE",
     "permissionLabel": "live route structurally blocked · dry-run visibility only", "buyingPower": 0,
     "eligible": False, "eligibilityReason": "Live order path not built", "paper": False,
     "readOnly": True, "maxShares": 0},
    {"id": "moomoo", "venue": "moomoo", "label": "Moomoo / OpenD", "maskedNumber": "data-plane",
     "permissionLabel": "L2 + tape data · execution disabled", "buyingPower": 0, "eligible": False,
     "eligibilityReason": "Stage 0 data plane only", "paper": False, "readOnly": True, "maxShares": 0},
]

_ALERT_LANES = ("IGN_45", "IGN_60", "IGN_75", "IGN_ACCEL", "TRIGGER")
_SUBSCORE_KEYS = ("v_rvol", "v_burst", "v_cat", "v_disp", "v_liq", "v_rs")


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _map_ignition_row_to_signal(r: Mapping[str, Any]) -> dict[str, Any]:
    """Map one scalp_ignition_events row to the ActiveTrader ScalpSignal shape. Read-only projection —
    subscores scaled to 0-100 for the bars; state derived from lane/gate/setup_state; no order fields."""
    lane = r.get("lane") or "BELOW"
    gate = r.get("gate_result")
    setup_state = r.get("setup_state")
    if gate == "VETO" or setup_state == "INVALIDATED":
        state = "VETOED"
    elif lane == "TRIGGER" or setup_state == "FIRED":
        state = "TRIGGERED"
    elif setup_state == "EXPIRED":
        state = "EXPIRED"
    else:
        state = "ARMED"
    sub = r.get("subscores") or {}
    subscores = {k: max(0, min(100, round(_f(sub.get(k)) * 100))) for k in _SUBSCORE_KEYS}
    label = r.get("primary_setup_label") or ("IGNITION BREAKOUT" if lane == "TRIGGER" else lane)
    matched = list(r.get("matched_setup_labels") or ([label] if label else []))
    entry = _f(r.get("entry_ref"))
    stop = _f(r.get("stop_ref"))
    gate_reasons = r.get("gate_reasons") or {}
    evidence = []
    if gate:
        evidence.append({"id": "gate", "label": f"gate {gate}", "tone": "pass" if gate == "PASS" else "fail"})
    for cl in list(r.get("confirmation_labels") or [])[:5]:
        good = any(t in str(cl) for t in ("PASS", "CONFIRMED", "ALIGNED", "OK"))
        evidence.append({"id": str(cl), "label": str(cl), "tone": "pass" if good else "context"})
    veto_reason = None
    if state == "VETOED":
        fails = r.get("setup_fail_reasons") or gate_reasons or {}
        if isinstance(fails, dict):
            veto_reason = next(iter(fails.values()), None)
        elif isinstance(fails, (list, tuple)) and fails:
            veto_reason = fails[0]
        veto_reason = str(veto_reason) if veto_reason is not None else "gate veto"
    sig = {
        "id": f"sie-{r.get('id')}", "symbol": r.get("symbol"), "last": entry, "changePct": 0.0,
        "ign": round(_f(r.get("ign_score"))), "ignDelta": 0, "ignDeltaMinutes": 0, "lane": lane,
        "mode": "MANUAL_PAPER_TEST_ONLY", "state": state,
        "cohort": "profiled" if r.get("profile_source") == "per_symbol" else "proxy",
        "dataTier": r.get("data_tier") or "T0", "tierMultiplier": round(_f(r.get("dcf"), 0.4), 2),
        "primarySetupLabel": label, "matchedSetupLabels": matched,
        "session": r.get("market_session") or "REGULAR", "subscores": subscores,
        "fsm": ["IDLE", "IMPULSE", "PULLBACK", "ARMED", "TRIGGERED"],
        "fsmCurrent": "TRIGGERED" if state == "TRIGGERED" else ("ARMED" if state == "ARMED" else "IMPULSE"),
        "expiresInSeconds": 0, "entryRef": entry, "stopRef": stop, "riskPerShare": _f(r.get("r_dollars")),
        "stopBps": round(_f(r.get("stop_dist_bps"))), "legToR": _f(gate_reasons.get("rr")), "floatM": 0.0,
        "rvolTod": round(_f(r.get("rvol_tod")), 1), "evidence": evidence,
        "operatorQuantity": 0, "tierDerivedQuantity": 0,
    }
    if veto_reason:
        sig["vetoReason"] = veto_reason
    # distinct state systems (never collapsed) + persisted setup identity
    sig["gateDecision"] = "PASS" if gate == "PASS" else ("VETO" if gate == "VETO" else "DEFER")
    if setup_state:
        sig["setupState"] = setup_state
    sig["fsmState"] = sig["fsmCurrent"]
    if r.get("primary_setup_id"):
        sig["primarySetupId"] = r["primary_setup_id"]
    if r.get("matched_setup_ids"):
        sig["matchedSetupIds"] = list(r["matched_setup_ids"])
    if r.get("setup_version"):
        sig["setupVersion"] = str(r["setup_version"])
    if r.get("registry_hash"):
        sig["registryHash"] = r["registry_hash"]
    return sig


def _permission_queue_signals(limit: int = 25) -> dict[str, Any]:
    """Real alert-worthy signals from the most recent session that HAS any. Read-only; never writes.
    Returns {available, signals, source_session, is_live_session, last_event_at}. available=False means
    the DB/table could not be reached — reported as API_UNAVAILABLE, NEVER disguised as an empty queue."""
    empty = {"available": False, "signals": [], "source_session": None,
             "is_live_session": False, "last_event_at": None}
    try:
        import sys as _sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in _sys.path:
            _sys.path.insert(0, sp)
        from db_adapter import get_connection
    except Exception:
        return empty
    lim = max(1, min(int(limit or 25), 100))
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT max(session_date), max(fired_at) FROM scalp_ignition_events WHERE lane = ANY(%s)",
                        (list(_ALERT_LANES),))
            row = cur.fetchone()
            sess = row[0] if row else None
            last_ev = row[1] if row else None
            if sess is None:
                return {"available": True, "signals": [], "source_session": None,
                        "is_live_session": False, "last_event_at": None}
            cur.execute(
                """SELECT id, symbol, lane, ign_score, setup_state, primary_setup_id, primary_setup_label,
                          matched_setup_ids, matched_setup_labels, setup_version, registry_hash,
                          market_session, data_tier, dcf, rvol_tod, profile_source, entry_ref, stop_ref,
                          r_dollars, stop_dist_bps, gate_result, gate_reasons, subscores, confirmation_labels,
                          setup_fail_reasons, fired_at
                   FROM scalp_ignition_events
                   WHERE session_date = %s AND lane = ANY(%s)
                   ORDER BY ign_score DESC, fired_at DESC LIMIT %s""",
                (sess, list(_ALERT_LANES), lim))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        import datetime as _dt
        return {"available": True, "signals": [_map_ignition_row_to_signal(r) for r in rows],
                "source_session": sess.isoformat(), "is_live_session": bool(sess == _dt.date.today()),
                "last_event_at": last_ev.isoformat() if last_ev else None}
    except Exception:
        return empty


# Real momentum routes the live scanner assigns to an actionable scalp fire (vs watch_only/reject).
_LIVE_SCAN_MOMENTUM_ROUTES = ("momentum_scalp", "meme_squeeze_momentum")
_LIVE_SCAN_ACTIONABLE_DECISIONS = ("GO", "ENTER", "TAKE")


def _live_scan_signals(limit: int = 40) -> dict[str, Any]:
    """TODAY's LIVE momentum-scalp scanner activity from scalp_scan_results (the engine that actually
    runs 6am-noon incl. premarket). Read-only projection of REAL scanner fields — score/grade/decision/
    route/rvol/gap — with NO fabricated IGN or subscores (those live only in scalp_ignition_events).
    available=False means the DB/table was unreachable (reported honestly, never disguised as idle)."""
    from datetime import datetime as _dtm
    from zoneinfo import ZoneInfo as _ZI
    et = _ZI("America/New_York")
    today = _dtm.now(et).date().isoformat()
    empty = {"available": False, "session_date": today, "scan_count": 0, "fires": []}
    try:
        import sys as _sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in _sys.path:
            _sys.path.insert(0, sp)
        from db_adapter import get_connection
    except Exception:
        return empty
    lim = max(1, min(int(limit or 40), 100))
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), count(DISTINCT symbol), max(scanned_at) FROM scalp_scan_results "
                "WHERE scanned_at >= %s",
                (f"{today} 00:00:00-04",))
            total, distinct_syms, last_at = cur.fetchone()
            cur.execute(
                """SELECT symbol, scanned_at, score, grade, decision, route, route_strategy_id,
                          route_actionability, rvol, volume, gap_pct, price, float_mm, change_pct,
                          sector, industry, catalyst_verified, catalyst_confidence, alerted,
                          disqualified, disqualification_reason, operator_pill, operator_subtitle,
                          operator_color_token, scout_status, scout_pillar_count, not_tradeable
                   FROM scalp_scan_results
                   WHERE scanned_at >= %s
                   ORDER BY scanned_at DESC, score DESC NULLS LAST
                   LIMIT %s""",
                (f"{today} 00:00:00-04", lim))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.execute(
                "SELECT decision, count(*) FROM scalp_scan_results WHERE scanned_at >= %s GROUP BY 1",
                (f"{today} 00:00:00-04",))
            by_decision = {str(k): v for k, v in cur.fetchall()}
            cur.execute(
                "SELECT route, count(*) FROM scalp_scan_results WHERE scanned_at >= %s GROUP BY 1",
                (f"{today} 00:00:00-04",))
            by_route = {("none" if k is None else str(k)): v for k, v in cur.fetchall()}
    except Exception:
        return empty

    def _fire(r: Mapping[str, Any]) -> dict[str, Any]:
        sc = r.get("scanned_at")
        route = r.get("route")
        decision = r.get("decision")
        actionable = (decision in _LIVE_SCAN_ACTIONABLE_DECISIONS) or (route in _LIVE_SCAN_MOMENTUM_ROUTES)
        return {
            "symbol": r.get("symbol"),
            "scanned_at": sc.isoformat() if hasattr(sc, "isoformat") else sc,
            "scanned_at_et": sc.astimezone(et).strftime("%H:%M") if hasattr(sc, "astimezone") else None,
            "score": r.get("score"), "grade": r.get("grade"), "decision": decision,
            "route": route, "route_strategy_id": r.get("route_strategy_id"),
            "route_actionability": r.get("route_actionability"),
            "rvol": float(r["rvol"]) if r.get("rvol") is not None else None,
            "gap_pct": float(r["gap_pct"]) if r.get("gap_pct") is not None else None,
            "change_pct": float(r["change_pct"]) if r.get("change_pct") is not None else None,
            "price": float(r["price"]) if r.get("price") is not None else None,
            "float_mm": float(r["float_mm"]) if r.get("float_mm") is not None else None,
            "sector": r.get("sector"), "industry": r.get("industry"),
            "catalyst_verified": r.get("catalyst_verified"),
            "catalyst_confidence": r.get("catalyst_confidence"),
            "alerted": r.get("alerted"), "disqualified": r.get("disqualified"),
            "disqualification_reason": r.get("disqualification_reason"),
            "operator_pill": r.get("operator_pill"), "operator_subtitle": r.get("operator_subtitle"),
            "operator_color_token": r.get("operator_color_token"),
            "scout_status": r.get("scout_status"), "scout_pillar_count": r.get("scout_pillar_count"),
            "not_tradeable": r.get("not_tradeable"),
            "actionable": actionable,
        }

    fires = [_fire(r) for r in rows]
    # actionable = today's GO/route-momentum count (computed from full-day distributions, not just page)
    go_ct = sum(v for k, v in by_decision.items() if k in _LIVE_SCAN_ACTIONABLE_DECISIONS)
    route_ct = sum(v for k, v in by_route.items() if k in _LIVE_SCAN_MOMENTUM_ROUTES)
    return {
        "available": True, "session_date": today, "is_today": True,
        "scan_count": int(total or 0), "distinct_symbols": int(distinct_syms or 0),
        "actionable_count": int(go_ct), "momentum_route_count": int(route_ct),
        "last_scan_at": last_at.isoformat() if hasattr(last_at, "isoformat") else last_at,
        "window": "06:00-12:00 ET", "fires": fires,
        "by_decision": by_decision, "by_route": by_route,
        "source": "scalp_scan_results",
        "note": "LIVE momentum-scalp scanner (runs 6am-noon ET incl. premarket). Real scanner fields; "
                "IGN/subscores/setup taxonomy are NOT fabricated here (those come from scalp_ignition_events "
                "during RTH). Read-only, no order path.",
    }


def _et_today() -> str:
    from datetime import datetime as _dtm
    from zoneinfo import ZoneInfo as _ZI
    return _dtm.now(_ZI("America/New_York")).date().isoformat()


def _ign_trigger_today(limit: int = 25) -> list[dict[str, Any]]:
    """TODAY's IGN TRIGGER fires (the actionable, fired lane) mapped to the rich ScalpSignal shape.
    Actionable = something a human could paper-route right now; stale sessions are NOT actionable."""
    try:
        import sys as _sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in _sys.path:
            _sys.path.insert(0, sp)
        from db_adapter import get_connection
    except Exception:
        return []
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, symbol, lane, ign_score, setup_state, primary_setup_id, primary_setup_label,
                          matched_setup_ids, matched_setup_labels, setup_version, registry_hash,
                          market_session, data_tier, dcf, rvol_tod, profile_source, entry_ref, stop_ref,
                          r_dollars, stop_dist_bps, gate_result, gate_reasons, subscores, confirmation_labels,
                          setup_fail_reasons, fired_at
                   FROM scalp_ignition_events
                   WHERE session_date = %s AND lane = 'TRIGGER'
                   ORDER BY ign_score DESC, fired_at DESC LIMIT %s""",
                (_et_today(), max(1, min(int(limit or 25), 100))))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        return []
    out = []
    for r in rows:
        sig = _map_ignition_row_to_signal(r)
        sig["source"] = "ign_trigger"
        sig["reviewState"] = "TRIGGERED"
        out.append(sig)
    return out


# What TradeAI actually "fires" — not just GO. The orchestrator (trade_ai_scans: screener → enrichment →
# scalp critic) surfaces GO plus MANUAL_REVIEW momentum fires (squeeze / runner / top-gainer / micro-float).
_TRADE_AI_ACTIONABLE_DECISIONS = ("GO", "MANUAL_REVIEW", "ENTER", "TAKE")


def _trade_ai_actionable(limit: int = 40) -> list[dict[str, Any]]:
    """TODAY's actionable signals from the SAME orchestrator TradeAI's scanner uses (trade_ai_scans),
    latest scan per symbol: decision GO or MANUAL_REVIEW (the momentum fires the header counts). Honest
    scanner fields (score/grade/decision/setup_class/operator_pill/rvol/gap) — NO fabricated IGN/subscores.
    This is why the Active Trader queue must match TradeAI's GO count, not a separate momentum-scalp table."""
    from datetime import datetime as _dtm
    from zoneinfo import ZoneInfo as _ZI
    et = _ZI("America/New_York")
    today = _et_today()
    try:
        import sys as _sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in _sys.path:
            _sys.path.insert(0, sp)
        from db_adapter import get_connection
    except Exception:
        return []
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT ON (symbol) symbol, scanned_at, score, grade, decision, route,
                          route_strategy_id, route_actionability, setup_class, operator_pill,
                          operator_subtitle, critic_verdict, catalyst_verified, rvol, gap_pct,
                          change_pct, price, float_m, sector, manual_review_required, not_tradeable
                   FROM trade_ai_scans
                   WHERE run_date = %s AND decision = ANY(%s) AND NOT COALESCE(disqualified, false)
                   ORDER BY symbol, scanned_at DESC""",
                (today, list(_TRADE_AI_ACTIONABLE_DECISIONS)))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        return []
    # GO first, then by score desc (matches how TradeAI surfaces actionable)
    rows.sort(key=lambda r: (0 if r.get("decision") == "GO" else 1, -(r.get("score") or 0)))
    out = []
    for r in rows[: max(1, min(int(limit or 40), 100))]:
        sc = r.get("scanned_at")
        out.append({
            "source": "scanner", "id": f"tai-{r.get('symbol')}-{sc.isoformat() if hasattr(sc,'isoformat') else sc}",
            "symbol": r.get("symbol"),
            "scannedAt": sc.isoformat() if hasattr(sc, "isoformat") else sc,
            "scannedAtEt": sc.astimezone(et).strftime("%H:%M") if hasattr(sc, "astimezone") else None,
            "score": r.get("score"), "grade": r.get("grade"), "decision": r.get("decision"),
            "route": r.get("route"), "routeStrategyId": r.get("route_strategy_id"),
            "routeActionability": r.get("route_actionability"),
            "setupClass": r.get("setup_class"), "operatorPill": r.get("operator_pill"),
            "operatorSubtitle": r.get("operator_subtitle"), "criticVerdict": r.get("critic_verdict"),
            "catalystVerified": r.get("catalyst_verified"),
            "rvol": float(r["rvol"]) if r.get("rvol") is not None else None,
            "gapPct": float(r["gap_pct"]) if r.get("gap_pct") is not None else None,
            "changePct": float(r["change_pct"]) if r.get("change_pct") is not None else None,
            "price": float(r["price"]) if r.get("price") is not None else None,
            "floatM": float(r["float_m"]) if r.get("float_m") is not None else None,
            "sector": r.get("sector"),
            "manualReviewRequired": bool(r.get("manual_review_required")),
            "notTradeable": bool(r.get("not_tradeable")),
            "reviewState": r.get("decision") or "GO",
        })
    return out


def _actionable_queue(limit: int = 40) -> dict[str, Any]:
    """The ActiveTrader review queue: TODAY's actionable signals to paper-route — IGN TRIGGER fires +
    the TradeAI orchestrator's actionable set (GO + MANUAL_REVIEW momentum fires), deduped by symbol
    (IGN evidence wins). No full scan dump, no stale-session fallback; empty only when genuinely nothing
    is actionable. Draws from the SAME orchestrator TradeAI's header uses, so counts match."""
    ign = _ign_trigger_today(limit)
    scan = _trade_ai_actionable(limit)
    seen = {str(i.get("symbol")) for i in ign}
    items = ign + [s for s in scan if str(s.get("symbol")) not in seen]
    go = sum(1 for s in scan if s.get("decision") == "GO")
    return {"items": items, "ign_trigger_count": len(ign),
            "scanner_actionable_count": len(scan), "scanner_go_count": go}


def _engine_status() -> dict[str, Any]:
    """Compact live status of the two engines feeding the queue (NOT a data dump): the TradeAI
    orchestrator scanner (trade_ai_scans — GO + MANUAL_REVIEW fires) and the RTH IGN/trigger engine."""
    from datetime import datetime as _dtm
    from zoneinfo import ZoneInfo as _ZI
    et = _ZI("America/New_York")
    now = _dtm.now(et)
    market_open = (now.weekday() < 5) and ((now.hour, now.minute) >= (9, 30)) and (now.hour < 16)
    scanner = {"available": False, "go_count_today": 0, "manual_review_count_today": 0,
               "wait_count_today": 0, "actionable_count_today": 0, "last_scan_at": None,
               "latest_run_label": None, "distinct_symbols": 0}
    ign_today = ign_trigger = 0
    try:
        import sys as _sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in _sys.path:
            _sys.path.insert(0, sp)
        from db_adapter import get_connection
        conn = get_connection()
        today = _et_today()
        with conn.cursor() as cur:
            # latest scan per symbol today → decision distribution (matches TradeAI's actionable view)
            cur.execute(
                """WITH latest AS (
                       SELECT DISTINCT ON (symbol) symbol, decision, scanned_at
                       FROM trade_ai_scans WHERE run_date=%s AND NOT COALESCE(disqualified,false)
                       ORDER BY symbol, scanned_at DESC)
                   SELECT
                     count(*) FILTER (WHERE decision='GO'),
                     count(*) FILTER (WHERE decision='MANUAL_REVIEW'),
                     count(*) FILTER (WHERE decision='WAIT'),
                     count(*), max(scanned_at) FROM latest""", (today,))
            go, mr, wait, distinct, last_at = cur.fetchone()
            cur.execute("SELECT run_label FROM trade_ai_scans WHERE run_date=%s ORDER BY scanned_at DESC LIMIT 1", (today,))
            rl = cur.fetchone()
            scanner = {
                "available": True, "go_count_today": int(go or 0),
                "manual_review_count_today": int(mr or 0), "wait_count_today": int(wait or 0),
                "actionable_count_today": int((go or 0) + (mr or 0)),
                "last_scan_at": last_at.isoformat() if hasattr(last_at, "isoformat") else last_at,
                "latest_run_label": rl[0] if rl else None, "distinct_symbols": int(distinct or 0),
            }
            cur.execute("SELECT count(*), count(*) FILTER (WHERE lane='TRIGGER') "
                        "FROM scalp_ignition_events WHERE session_date=%s", (today,))
            ign_today, ign_trigger = cur.fetchone()
    except Exception:
        pass
    return {
        "scanner": scanner,
        "ign": {
            "rth_only": True, "opens_et": "09:30", "market_open": bool(market_open),
            "today_row_count": int(ign_today or 0), "today_trigger_count": int(ign_trigger or 0),
            "note": "premarket coverage pending a premarket volume profile (fails closed until then)",
        },
    }


_ARMING_LANES = ("IGN_45", "IGN_60", "IGN_75", "IGN_ACCEL")
_LANE_LADDER = ("BELOW", "IGN_45", "IGN_60", "IGN_75", "IGN_ACCEL", "TRIGGER")


def _arming_status(limit: int = 25) -> dict[str, Any]:
    """Pre-fire visibility: what is CLIMBING the ignition ladder toward a trigger (IGN_45→ACCEL, below
    TRIGGER), plus the moomoo L2/T2 arm set (L2 is subscribed only when a symbol's FSM hits ARMED).
    Read-only. Empty ladder is honest — recent RTH sessions have been all-BELOW (nothing arming)."""
    from datetime import datetime as _dtm
    from zoneinfo import ZoneInfo as _ZI
    et = _ZI("America/New_York")
    now = _dtm.now(et)
    market_open = (now.weekday() < 5) and ((now.hour, now.minute) >= (9, 30)) and (now.hour < 16)
    ladder = {k: 0 for k in _LANE_LADDER}
    near = []
    available = False
    try:
        import sys as _sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in _sys.path:
            _sys.path.insert(0, sp)
        from db_adapter import get_connection
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT ON (symbol) symbol, lane, ign_score, gate_result, setup_state,
                          data_tier, rvol_tod, minute_of_session, primary_setup_label, spread_bps
                   FROM scalp_ignition_events WHERE session_date=%s
                   ORDER BY symbol, minute_of_session DESC""", (_et_today(),))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        available = True
        for r in rows:
            lane = r.get("lane") or "BELOW"
            if lane in ladder:
                ladder[lane] += 1
            # "close to firing" = climbing the IGN ladder (IGN_45+) OR a named setup that has ARMED
            if lane in _ARMING_LANES or r.get("setup_state") == "ARMED":
                near.append({
                    "symbol": r.get("symbol"), "lane": lane, "ign": round(_f(r.get("ign_score"))),
                    "gate": r.get("gate_result") or "—", "setupState": r.get("setup_state"),
                    "dataTier": r.get("data_tier") or "T0",
                    "l2Engaged": (r.get("data_tier") == "T2"),
                    "rvolTod": round(_f(r.get("rvol_tod")), 1) if r.get("rvol_tod") is not None else None,
                    "primarySetupLabel": r.get("primary_setup_label"),
                    "spreadBps": round(_f(r.get("spread_bps"))) if r.get("spread_bps") is not None else None,
                })
        near.sort(key=lambda x: x["ign"], reverse=True)
        near = near[: max(1, min(int(limit or 25), 100))]
    except Exception:
        available = False

    # moomoo L2/T2 arm set — L2 is only "looked at" for symbols whose FSM reached ARMED
    l2 = {"enabled": False, "max_armed": None, "ttl_seconds": None, "armed": [], "connected": False,
          "note": "L2 (moomoo T2) arms on-demand when a symbol's trigger FSM hits ARMED; observability-only until OpenD is connected."}
    try:
        import sys as _sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in _sys.path:
            _sys.path.insert(0, sp)
        import scalp_shadow_logger as _L
        cfg = _L.load_config()
        t2 = cfg.get("data_tiers", {}).get("t2", cfg.get("t2", {})) or {}
        l2["enabled"] = bool(t2.get("arm_from_trigger", False))
        l2["max_armed"] = t2.get("max_armed")
        l2["ttl_seconds"] = t2.get("ttl_seconds")
        state_path = _REPO_ROOT / (t2.get("state_file") or "data/scalp/moomoo_armed_state.json")
        if state_path.is_file():
            data = json.loads(state_path.read_text(encoding="utf-8"))
            armed = data.get("armed") if isinstance(data, dict) else data
            if isinstance(armed, dict):
                l2["armed"] = list(armed.keys())
            elif isinstance(armed, list):
                l2["armed"] = [x.get("symbol") if isinstance(x, dict) else x for x in armed]
            l2["connected"] = True
    except Exception:
        pass
    return {"available": available, "market_open": bool(market_open),
            "lane_ladder": ladder, "near_firing": near, "l2": l2,
            "note": "IGN_45→IGN_ACCEL = climbing toward a trigger; TRIGGER = fired. L2 pulls only on FSM ARMED."}


class ReadOnlyActiveTraderAPI:
    """Framework-neutral Stage 0 read surface. No create/update/delete/order methods."""

    def __init__(self, flags: Stage0Flags | None = None) -> None:
        self._flags = flags or load_flags()

    def health(self) -> dict[str, Any]:
        return {
            "contract": READ_API_CONTRACT,
            "stage": STAGE,
            "write": False,
            "canary": False,
            "read_only": True,
            "live_orders": False,
            "session_authorize": False,
            "venues": venue_inventory(self._flags),
            "ok": True,
            "product_intent": {
                "multi_broker": True,
                "schwab_primary": True,
                "operator_opt_in_required": True,
                "unattended_discover_and_fire": False,
            },
        }

    def status(self) -> dict[str, Any]:
        body = self.health()
        body["feature_flags"] = {
            k: bool(v) for k, v in self._flags.flags.items()
        }
        # Force hard offs even if misconfigured file somehow loaded (assert already ran)
        body["feature_flags"]["live_canary"] = False
        body["feature_flags"]["order_routes"] = False
        body["mode"] = "read_only_baseline"
        body["authority"] = {
            "mutation": False,
            "order": False,
            "session_authorize": False,
            "canary": False,
            "financial_action": False,
        }
        return body

    def list_sessions(self) -> dict[str, Any]:
        return {
            "contract": READ_API_CONTRACT,
            "stage": STAGE,
            "write": False,
            "canary": False,
            "sessions": [],
            "venues": venue_inventory(self._flags),
            "note": "Stage 0: no session schema yet; empty list is honest",
        }

    def venue_eligibility(self, symbol: str, proposed_venue: str | None = None) -> dict[str, Any]:
        """Stage 1a capability read: is `symbol` executable on `proposed_venue` (Schwab by
        default)? Read-only; on a Schwab compliance block it returns the block reason + an
        operator-prompt TEMPLATE and never auto-routes. Fail-closed to 'unknown'."""
        from .venue_eligibility import evaluate_eligibility, operator_prompt_required
        snap = capability_snapshot(self._flags)
        # proposed_venue None/"" -> evaluate_eligibility defaults to its SCHWAB product
        # constant (Schwab-primary contract); no venue string is hardcoded here.
        result = evaluate_eligibility(symbol, proposed_venue or "", snap)
        return {
            "contract": READ_API_CONTRACT,
            "stage": 1,
            "sub_stage": "1a",
            "write": False,
            "canary": False,
            "read_only": True,
            "auto_route": False,
            "capability_source": snap.get("source"),
            "eligibility": result.to_dict(),
            "operator_prompt": operator_prompt_required(result),
            "authority": {
                "mutation": False, "order": False, "session_authorize": False,
                "canary": False, "financial_action": False,
            },
        }

    def scalp_setups(self) -> dict[str, Any]:
        """Read-only scalp setup registry (the named-setup taxonomy the modal renders). SHADOW /
        MANUAL PAPER ONLY. A lane is NOT a setup. No write/order authority is exposed here."""
        return {
            "contract": READ_API_CONTRACT, "stage": 1, "sub_stage": "scalp-taxonomy",
            "write": False, "canary": False, "read_only": True, "auto_route": False,
            "setup_registry": _scalp_registry_view(),
            "operating_note": "SHADOW / MANUAL PAPER ONLY — setups are named, versioned, deterministic "
                              "patterns; a lane (IGN_60/IGN_ACCEL/TRIGGER) is not a setup.",
            "authority": {"mutation": False, "order": False, "session_authorize": False,
                          "canary": False, "financial_action": False},
        }

    def scalp_setup_events(self, *, limit: int = 50, session_date: str | None = None,
                           setup: str | None = None) -> dict[str, Any]:
        """Read-only recent setup-tagged events (empty until the additive migration + shadow logger have
        run). MANUAL PAPER ONLY — never an order; nothing here routes or fires."""
        rows, source = _scalp_setup_events(limit, session_date, setup)
        return {
            "contract": READ_API_CONTRACT, "stage": 1, "sub_stage": "scalp-taxonomy",
            "write": False, "canary": False, "read_only": True, "auto_route": False,
            "events": rows, "count": len(rows), "source": source,
            "note": "Read-only setup-tagged events. MANUAL PAPER ONLY — never an order.",
            "authority": {"mutation": False, "order": False, "session_authorize": False,
                          "canary": False, "financial_action": False},
        }

    def permission_queue(self) -> dict[str, Any]:
        """ActiveTrader review queue (read-only). The queue is TODAY's ACTIONABLE momentum-scalp signals
        a human would paper-route: IGN TRIGGER fires + scanner GO/momentum-route, deduped by symbol. It is
        NOT a scanner dump and does NOT fall back to a stale session — an empty queue is the honest state
        when nothing is actionable right now. `engine_status` is a compact live status of both engines (not
        a data dump). No order path, no routing, no write authority, no submitOrder."""
        import datetime as _dt
        aq = _actionable_queue()
        signals = aq["items"]
        engine_status = _engine_status()
        arming = _arming_status()
        db_ok = bool(engine_status["scanner"]["available"]) or engine_status["ign"]["today_row_count"] > 0
        if not db_ok and not signals:
            data_state = "API_UNAVAILABLE"
        elif signals:
            data_state = "LIVE_DATA"
        else:
            data_state = "EMPTY_LIVE_QUEUE"    # engines reachable, nothing actionable yet today (honest)
        actionable = len(signals)
        # last IGN alert-worthy session — REFERENCE ONLY (context: "last fire was …"), never the queue.
        ref = _permission_queue_signals(limit=1)
        try:
            reg = _scalp_registry_view()
            reg_ver, reg_hash = reg.get("registry_version"), reg.get("registry_hash")
        except Exception:
            reg_ver = reg_hash = None
        return {
            "contract": READ_API_CONTRACT, "stage": 1, "sub_stage": "active-trader-permission-queue",
            "write": False, "canary": False, "read_only": True, "auto_route": False,
            "mode": "MANUAL_PAPER_TEST_ONLY",
            "data_state": data_state,          # API_UNAVAILABLE | EMPTY_LIVE_QUEUE | LIVE_DATA
            "is_sample": False,                # server never returns a reference sample; the UI owns preview mode
            "signals": signals,                # actionable queue items (source: ign_trigger | scanner)
            "actionable_count": actionable,
            "ign_trigger_count": aq["ign_trigger_count"],
            "scanner_go_count": aq["scanner_go_count"],
            "scanner_actionable_count": aq["scanner_actionable_count"],
            "accounts": _ACTIVE_TRADER_ACCOUNTS,
            "source": "scalp_ignition_events (IGN TRIGGER) + trade_ai_scans (GO/MANUAL_REVIEW)",
            "engine_status": engine_status,
            "arming": arming,          # pre-fire ladder (IGN_45→ACCEL) + moomoo L2 arm set
            # reference-only: the last alert-worthy IGN session (context, NOT the queue)
            "last_ign_session_date": ref.get("source_session"),
            "last_ign_event_at": ref.get("last_event_at"),
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "registry_version": reg_ver, "registry_hash": reg_hash,
            "route_health": "ok",
            "posture": {
                "selectable_paper_venue": "alpaca_paper",
                "read_only_visible": ["schwab", "alpaca_live"],
                "data_plane_only": ["moomoo"], "manual_handoff": ["thinkorswim_manual"],
                "order_path": False, "live_routing": False, "live_session_enabled": False,
                "final_submit_present": False, "automation": "none_wired",
            },
            "note": "Read-only. Queue = TODAY's actionable signals only (IGN TRIGGER + scanner GO/momentum-route). "
                    "No scanner dump, no stale fallback, no order path, no live routing, no submitOrder.",
            "authority": {"mutation": False, "order": False, "session_authorize": False,
                          "canary": False, "financial_action": False},
        }

    def near_ready(self, *, include_watch: bool = False) -> dict[str, Any]:
        """Stage 1b read model: candidates below the Trade AI GO bar that show building
        volume/momentum / pullback-break characteristics. Read-only, list, empty OK.

        The `near_ready_desk` feature flag gates OPERATIONAL promotion (UI/later stages),
        NOT read visibility — it defaults OFF and is reported as `desk_enabled`. Nothing
        here routes, fires, or authorizes. Not equivalent to a Trade AI scanner GO."""
        desk_enabled = bool(self._flags.flags.get("near_ready_desk", False))
        built = near_ready_candidates(self._flags, include_watch=include_watch)
        return {
            "contract": READ_API_CONTRACT,
            "stage": 1,
            "sub_stage": "1b",
            "write": False,
            "canary": False,
            "read_only": True,
            "auto_route": False,
            "desk_enabled": desk_enabled,
            "near_ready_contract": built["contract"],
            "capability_source": built["source"],
            "count": len(built["candidates"]),
            "candidates": built["candidates"],
            "not_a_go": "Near-ready is NOT a Trade AI scanner GO — weaker, building-characteristics read; operator opts in later.",
            "authority": {
                "mutation": False, "order": False, "session_authorize": False,
                "canary": False, "financial_action": False,
            },
        }
