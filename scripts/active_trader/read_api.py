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
                """SELECT id, symbol, lane, ign_score, setup_state, primary_setup_label, matched_setup_labels,
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
        """ActiveTrader permission queue (read-only). Projects REAL alert-worthy signals from
        scalp_ignition_events with an HONEST, distinct data_state — API_UNAVAILABLE / EMPTY_LIVE_QUEUE /
        DATA_STALE / LIVE_DATA are never collapsed. The server NEVER returns a reference sample (the UI owns
        preview mode). No order path, no routing, no write authority, no submitOrder."""
        import datetime as _dt
        q = _permission_queue_signals()
        signals = q["signals"]
        if not q["available"]:
            data_state = "API_UNAVAILABLE"
        elif not signals:
            data_state = "EMPTY_LIVE_QUEUE"
        elif not q["is_live_session"]:
            data_state = "DATA_STALE"          # newest alert-worthy session is not today's
        else:
            data_state = "LIVE_DATA"
        actionable = sum(1 for s in signals if s.get("state") in ("ARMED", "TRIGGERED"))
        try:
            reg = _scalp_registry_view()
            reg_ver, reg_hash = reg.get("registry_version"), reg.get("registry_hash")
        except Exception:
            reg_ver = reg_hash = None
        return {
            "contract": READ_API_CONTRACT, "stage": 1, "sub_stage": "active-trader-permission-queue",
            "write": False, "canary": False, "read_only": True, "auto_route": False,
            "mode": "MANUAL_PAPER_TEST_ONLY",
            "data_state": data_state,          # API_UNAVAILABLE | EMPTY_LIVE_QUEUE | DATA_STALE | LIVE_DATA
            "is_sample": False,                # server never returns a reference sample; the UI owns preview mode
            "signals": signals,
            "actionable_count": actionable,
            "accounts": _ACTIVE_TRADER_ACCOUNTS,
            "source": "scalp_ignition_events",
            "source_session_date": q["source_session"],
            "is_live_session": q["is_live_session"],
            "last_event_at": q["last_event_at"],
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
            "note": "Read-only. Live signals projected from scalp_ignition_events; the server never returns a "
                    "reference sample (the UI owns preview mode). No order path, no live routing, no submitOrder.",
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
