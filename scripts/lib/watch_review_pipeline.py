"""Watch Intelligence Maria/CIO schedule, universe, dedupe, jobs, freshness.

Phase 1: create jobs and status only — never call providers.
Workers remain disabled until canaries pass (phase 5).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from lib.watch_review_policy_ledger import (
    CANONICAL_POLICY_ID,
    CIO_SPEC,
    EVENT_STATE_DIR,
    JOBS_DIR,
    MARIA_SPEC,
    NO_CALL_DIR,
    agent_spec,
    create_execution_authorization,
    load_policy,
    validate_policy,
    _atomic_write,
    _ensure_dirs,
    _now,
    _now_iso,
    _read_json,
)

ET = ZoneInfo("America/New_York")
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Freshness windows
REVIEW_FRESHNESS_HOURS = 72
NO_MATERIAL_FRESHNESS_HOURS = 72
EVENT_CHAIN_COOLDOWN_HOURS = 24

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SCHEDULE_DAYS = frozenset({"Monday", "Wednesday", "Friday"})

EXCLUDE_STATES = frozenset({
    "AVOID", "BLOCKED", "DETERMINISTIC_FAIL", "DATA_UNAVAILABLE",
})


def next_mwf_at(hour: int, minute: int, *, after: datetime | None = None) -> datetime:
    """Next Mon/Wed/Fri at hour:minute America/New_York (returned as aware ET)."""
    base = after or datetime.now(ET)
    if base.tzinfo is None:
        base = base.replace(tzinfo=ET)
    else:
        base = base.astimezone(ET)
    for offset in range(0, 8):
        d = (base + timedelta(days=offset)).date()
        name = WEEKDAY_NAMES[d.weekday()]
        if name not in SCHEDULE_DAYS:
            continue
        candidate = datetime(d.year, d.month, d.day, hour, minute, tzinfo=ET)
        if candidate > base:
            return candidate
    # fallback
    d = (base + timedelta(days=7)).date()
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=ET)


def schedule_times() -> dict[str, Any]:
    maria_next = next_mwf_at(16, 5)
    cio_next = next_mwf_at(16, 20)
    return {
        "timezone": "America/New_York",
        "maria_days": sorted(SCHEDULE_DAYS),
        "cio_days": sorted(SCHEDULE_DAYS),
        "maria_time_et": "16:05",
        "cio_time_et": "16:20",
        "next_maria_review_at": maria_next.isoformat(),
        "next_cio_review_at": cio_next.isoformat(),
        "maria_precedes_cio": True,
    }


def compute_input_hash(symbol: str, *, material_fingerprint: str | None, extra: dict | None = None) -> str:
    payload = {
        "symbol": symbol.upper(),
        "material_fingerprint": material_fingerprint or "",
        "extra": extra or {},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def dedupe_key(agent_id: str, process_id: str, symbol: str, input_hash: str, policy: str) -> str:
    raw = f"{agent_id}|{process_id}|{symbol.upper()}|{input_hash}|{policy}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _find_recent_complete(symbol: str, agent_id: str, input_hash: str, policy: str) -> dict[str, Any] | None:
    """Look for COMPLETE artifact or NO_CALL with same dedupe key within freshness window."""
    from lib.data_broker.watch_domains import ARTIFACTS
    cutoff = _now() - timedelta(hours=NO_MATERIAL_FRESHNESS_HOURS)
    for root in (ARTIFACTS, NO_CALL_DIR):
        if not root.exists():
            continue
        for path in root.glob(f"{symbol.upper()}_{agent_id}*.json"):
            data = _read_json(path)
            if not data:
                continue
            if data.get("input_hash") != input_hash:
                continue
            if (data.get("executed_policy") or data.get("requested_policy")) not in (policy, "NO_CALL"):
                if data.get("status") not in ("COMPLETE", "NO_CALL", "NOT_RUN"):
                    continue
            completed = data.get("completed_at") or data.get("created_at")
            if not completed:
                continue
            try:
                ts = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
            except Exception:
                continue
            if data.get("status") == "COMPLETE" or data.get("reason_code") == "NO_MATERIAL_CHANGE_NO_CALL":
                return data
    return None


def write_no_call_artifact(
    *,
    symbol: str,
    agent_id: str,
    reason_code: str = "NO_MATERIAL_CHANGE_NO_CALL",
    input_hash: str,
    process_id: str,
    trigger_reason: str,
) -> dict[str, Any]:
    """Persist NO_CALL — never looks like a DeepSeek COMPLETE artifact."""
    _ensure_dirs()
    rec = {
        "agent_id": agent_id,
        "symbol": symbol.upper(),
        "status": "NOT_RUN",
        "reason_code": reason_code,
        "artifact_disposition": reason_code,
        "provider": None,
        "model": None,
        "requested_policy": "NO_CALL",
        "executed_policy": "NO_CALL",
        "fallback_used": False,
        "estimated_cost_usd": 0.0,
        "registered_process_id": process_id,
        "input_hash": input_hash,
        "trigger_reason": trigger_reason,
        "completed_at": _now_iso(),
        "created_at": _now_iso(),
        "display": {
            "label": f"{agent_id.upper()} REVIEW: NO CALL",
            "provider": "NONE",
            "model": "NONE",
            "policy": "NO_CALL",
            "cost": "$0",
            "reason": reason_code,
        },
    }
    path = NO_CALL_DIR / f"{symbol.upper()}_{agent_id}_nocall.json"
    _atomic_write(path, rec)
    return rec


def eligible_universe(
    cards: list[dict[str, Any]],
    *,
    priority_limit: int = 40,
    event_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Priority order: held → starred → top ideas non-held → street SB/B → event.

    Excludes AVOID/BLOCKED/DETERMINISTIC_FAIL/DATA_UNAVAILABLE and quarantine-only cases
    handled separately at job time.
    """
    event_symbols = event_symbols or set()
    held, starred, top, street, events = [], [], [], [], []
    seen: set[str] = set()

    def accept(c: dict) -> bool:
        st = (c.get("trade_ai_state") or "").upper()
        if st in EXCLUDE_STATES:
            return False
        if c.get("last") is None and (c.get("freshness_state") or "") == "DATA_UNAVAILABLE":
            return False
        return True

    for c in cards:
        if not accept(c):
            continue
        sym = (c.get("symbol") or "").upper()
        if not sym or sym in seen:
            continue
        row = {"symbol": sym, "card": c}
        if c.get("held"):
            held.append(row)
            seen.add(sym)
        elif c.get("starred"):
            starred.append(row)
            seen.add(sym)

    for c in cards:
        if not accept(c):
            continue
        sym = (c.get("symbol") or "").upper()
        if not sym or sym in seen:
            continue
        if c.get("rank") is not None and not c.get("held"):
            top.append(row := {"symbol": sym, "card": c})
            seen.add(sym)

    for c in cards:
        if not accept(c):
            continue
        sym = (c.get("symbol") or "").upper()
        if not sym or sym in seen:
            continue
        if (c.get("street_rating") or "") in ("STRONG BUY", "BUY"):
            street.append({"symbol": sym, "card": c})
            seen.add(sym)

    for sym in sorted(event_symbols):
        if sym in seen:
            continue
        c = next((x for x in cards if (x.get("symbol") or "").upper() == sym), {"symbol": sym})
        if accept(c) or sym in event_symbols:
            # event can force inclusion unless hard exclude
            st = (c.get("trade_ai_state") or "").upper()
            if st in ("AVOID", "BLOCKED"):
                continue
            events.append({"symbol": sym, "card": c, "event": True})
            seen.add(sym)

    ordered = held + starred + top + street + events
    return ordered[:priority_limit]


def review_freshness_fields(card: dict[str, Any]) -> dict[str, Any]:
    """Populate SLA / next-review fields for projection (no provider calls)."""
    sym = (card.get("symbol") or "").upper()
    maria = card.get("maria_review") or {}
    cio = card.get("cio_review") or {}
    times = schedule_times()

    def parse_ts(v: Any) -> datetime | None:
        if not v:
            return None
        try:
            ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        except Exception:
            return None

    last_maria = parse_ts(maria.get("completed_at"))
    last_cio = parse_ts(cio.get("completed_at"))
    next_maria = times["next_maria_review_at"]
    next_cio = times["next_cio_review_at"]

    def age_hours(ts: datetime | None) -> float | None:
        if not ts:
            return None
        return (_now() - ts).total_seconds() / 3600.0

    m_age = age_hours(last_maria)
    c_age = age_hours(last_cio)

    def sla_for(status: str | None, reason: str | None, age: float | None, agent: str) -> str:
        st = (status or "").upper()
        disp = (card.get(f"{agent}_review") or {}).get("artifact_disposition")
        if disp == "QUARANTINED" or reason == "UNVERIFIED_OPERATOR_AUTHORIZATION":
            return "BLOCKED"
        if st == "COMPLETE" and age is not None:
            if age <= 48:
                return "CURRENT"
            if age <= REVIEW_FRESHNESS_HOURS:
                return "DUE_SOON"
            return "OVERDUE"
        if reason == "NO_MATERIAL_CHANGE_NO_CALL":
            return "CURRENT"
        if reason == "COST_DEFERRED":
            return "COST_DEFERRED"
        if reason == "NOT_SCHEDULED":
            return "SCHEDULED"
        if st == "NOT_RUN":
            return "SCHEDULED"
        return "SCHEDULED"

    maria_sla = sla_for(maria.get("status"), maria.get("reason_code"), m_age, "maria")
    cio_sla = sla_for(cio.get("status"), cio.get("reason_code"), c_age, "cio")

    # CIO prerequisite
    if maria.get("status") != "COMPLETE" and cio.get("status") != "COMPLETE":
        if cio_sla not in ("BLOCKED", "COST_DEFERRED"):
            if maria_sla in ("SCHEDULED", "OVERDUE", "DUE_SOON"):
                cio_due_reason = "Maria prerequisite missing"
            else:
                cio_due_reason = cio.get("reason_code") or "NOT_SCHEDULED"
        else:
            cio_due_reason = cio.get("reason_code") or cio_sla
    else:
        cio_due_reason = cio.get("reason_code")

    review_due_reason = None
    if maria_sla == "OVERDUE":
        review_due_reason = "Maria freshness > 72h"
    elif cio_sla == "OVERDUE":
        review_due_reason = "CIO freshness > 72h"

    # condition watch for near triggers
    if card.get("is_near_trigger") or card.get("material_change"):
        if maria_sla == "SCHEDULED":
            maria_sla = "CONDITION_WATCH"

    return {
        "last_maria_review_at": last_maria.isoformat() if last_maria else None,
        "last_cio_review_at": last_cio.isoformat() if last_cio else None,
        "next_maria_review_at": next_maria,
        "next_cio_review_at": next_cio,
        "next_review_condition": card.get("next_review_condition")
            or ("Rolling 5-session |move| ≥ 7%" if card.get("material_change") else "Mon/Wed/Fri schedule"),
        "review_sla_state": maria_sla if maria_sla == "OVERDUE" else (
            "OVERDUE" if cio_sla == "OVERDUE" else maria_sla
        ),
        "maria_review_sla_state": maria_sla,
        "cio_review_sla_state": cio_sla,
        "review_due_reason": review_due_reason or cio_due_reason or maria.get("reason_code"),
        "last_attempt_at": max(
            [x for x in [last_maria, last_cio] if x],
            default=None,
        ),
        "last_attempt_status": (
            "COMPLETE" if maria.get("status") == "COMPLETE" or cio.get("status") == "COMPLETE"
            else (maria.get("reason_code") or cio.get("reason_code") or "NOT_SCHEDULED")
        ),
    }


def enrich_review_display(rev: dict[str, Any], *, agent: str, card: dict) -> dict[str, Any]:
    """UI-facing display for scheduled / no-call / complete states."""
    r = dict(rev or {})
    fields = review_freshness_fields({**card, f"{agent}_review": r})
    status = (r.get("status") or "NOT_RUN").upper()
    reason = r.get("reason_code")
    sla = fields.get(f"{agent}_review_sla_state") or fields.get("review_sla_state")

    if status == "COMPLETE" and r.get("provider") and r.get("model"):
        r.setdefault("display", {})
        r["display"] = {
            **(r.get("display") or {}),
            "label": f"{agent.upper()} REVIEW: COMPLETE",
            "provider": str(r.get("provider") or "").upper(),
            "model": r.get("model"),
            "policy": r.get("executed_policy") or r.get("requested_policy"),
            "cost": f"${float(r.get('estimated_cost_usd') or 0):.5f}",
            "completed_at": r.get("completed_at"),
            "review_age": fields.get(f"last_{agent}_review_at"),
            "next_review": fields.get(f"next_{agent}_review_at"),
        }
        r["next_review_at"] = fields.get(f"next_{agent}_review_at")
        r["review_sla_state"] = sla
        return r

    # NOT complete — never show configured provider/model
    next_at = fields.get(f"next_{agent}_review_at")
    if reason == "NO_MATERIAL_CHANGE_NO_CALL":
        label = f"{agent.upper()} REVIEW: NO CALL"
    elif reason == "UNVERIFIED_OPERATOR_AUTHORIZATION" or r.get("artifact_disposition") == "QUARANTINED":
        label = f"{agent.upper()} REVIEW: NOT RUN"
    elif sla == "OVERDUE":
        label = f"{agent.upper()} REVIEW: OVERDUE"
    elif sla == "COST_DEFERRED":
        label = f"{agent.upper()} REVIEW: COST DEFERRED"
    elif sla == "CONDITION_WATCH":
        label = f"{agent.upper()} REVIEW: CONDITION WATCH"
    else:
        label = f"{agent.upper()} REVIEW: SCHEDULED"

    detail_reason = reason or fields.get("review_due_reason")
    if agent == "cio" and fields.get("review_due_reason") == "Maria prerequisite missing":
        detail_reason = "Maria prerequisite missing"

    r["status"] = "NOT_RUN"
    r["provider"] = None
    r["model"] = None
    r["requested_policy"] = "NO_CALL"
    r["executed_policy"] = "NO_CALL"
    r["estimated_cost_usd"] = 0.0
    r["review_sla_state"] = sla
    r["next_review_at"] = next_at
    r["display"] = {
        "label": label,
        "provider": "NONE",
        "model": "NONE",
        "policy": "NO_CALL",
        "cost": "$0",
        "reason": detail_reason,
        "disposition": r.get("artifact_disposition"),
        "next_review": next_at,
        "sla": sla,
    }
    return r


def plan_jobs(
    cards: list[dict[str, Any]],
    *,
    trigger_reason: str = "SCHEDULED_MWF",
    max_maria: int | None = None,
    max_cio: int | None = None,
    event_symbols: set[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Build governed job plan. Never calls providers.

    dry_run=True (default): do not write jobs or execution authorizations.
    workers_enabled must be true on policy to materialize jobs for workers.
    """
    pol = load_policy()
    ok, reason = validate_policy(pol)
    times = schedule_times()
    if not ok:
        return {
            "ok": False,
            "error": reason,
            "provider_calls": 0,
            "jobs": [],
            "deferred": [],
        }

    assert pol is not None
    max_maria = max_maria if max_maria is not None else int((pol.get("maximum_calls_per_run") or {}).get("maria") or 15)
    max_cio = max_cio if max_cio is not None else int((pol.get("maximum_calls_per_run") or {}).get("cio") or 8)

    universe = eligible_universe(cards, event_symbols=event_symbols)
    jobs: list[dict] = []
    deferred: list[dict] = []
    maria_count = 0
    cio_count = 0

    for item in universe:
        sym = item["symbol"]
        card = item.get("card") or {}
        fp = card.get("material_fingerprint") or ""
        ih = compute_input_hash(sym, material_fingerprint=fp)

        # Maria
        if maria_count >= max_maria:
            deferred.append({"symbol": sym, "agent_id": "maria", "reason": "COST_DEFERRED", "next": times["next_maria_review_at"]})
        else:
            recent = _find_recent_complete(sym, "maria", ih, MARIA_SPEC["policy"])
            if recent and recent.get("status") == "COMPLETE":
                jobs.append({
                    "symbol": sym,
                    "agent_id": "maria",
                    "action": "NO_CALL",
                    "reason_code": "NO_MATERIAL_CHANGE_NO_CALL",
                    "input_hash": ih,
                })
            else:
                jobs.append({
                    "symbol": sym,
                    "agent_id": "maria",
                    "action": "QUEUE",
                    "registered_process_id": MARIA_SPEC["registered_process_id"],
                    "provider": MARIA_SPEC["provider"],
                    "model": MARIA_SPEC["model"],
                    "policy": MARIA_SPEC["policy"],
                    "thinking": "off",
                    "fallback_allowed": False,
                    "input_hash": ih,
                    "trigger_reason": trigger_reason,
                    "authorization_policy_id": pol["authorization_policy_id"],
                })
                maria_count += 1

        # CIO — requires current Maria COMPLETE for same/compatible input
        maria_ok = False
        from lib.data_broker.watch_domains import load_review_artifacts
        arts = load_review_artifacts(sym)
        m = arts.get("maria") or {}
        if m.get("status") == "COMPLETE" and m.get("artifact_disposition") == "COMPLETE":
            maria_ok = True
        # also accept just-planned queue as future prerequisite marker only for ordering
        if not maria_ok:
            jobs.append({
                "symbol": sym,
                "agent_id": "cio",
                "action": "BLOCKED",
                "reason_code": "MARIA_PREREQUISITE_MISSING",
                "input_hash": ih,
            })
            continue
        if cio_count >= max_cio:
            deferred.append({"symbol": sym, "agent_id": "cio", "reason": "COST_DEFERRED", "next": times["next_cio_review_at"]})
            continue
        recent_c = _find_recent_complete(sym, "cio", ih, CIO_SPEC["policy"])
        if recent_c and recent_c.get("status") == "COMPLETE":
            jobs.append({
                "symbol": sym,
                "agent_id": "cio",
                "action": "NO_CALL",
                "reason_code": "NO_MATERIAL_CHANGE_NO_CALL",
                "input_hash": ih,
            })
        else:
            jobs.append({
                "symbol": sym,
                "agent_id": "cio",
                "action": "QUEUE",
                "registered_process_id": CIO_SPEC["registered_process_id"],
                "provider": CIO_SPEC["provider"],
                "model": CIO_SPEC["model"],
                "policy": CIO_SPEC["policy"],
                "thinking": "off",
                "fallback_allowed": False,
                "input_hash": ih,
                "trigger_reason": trigger_reason,
                "authorization_policy_id": pol["authorization_policy_id"],
            })
            cio_count += 1

    materialized = []
    if not dry_run and pol.get("workers_enabled"):
        _ensure_dirs()
        for j in jobs:
            if j.get("action") == "NO_CALL":
                write_no_call_artifact(
                    symbol=j["symbol"],
                    agent_id=j["agent_id"],
                    input_hash=j["input_hash"],
                    process_id=agent_spec(j["agent_id"])["registered_process_id"],
                    trigger_reason=trigger_reason,
                )
            elif j.get("action") == "QUEUE":
                snap = f"snap-{j['symbol']}-{j['agent_id']}-{j['input_hash'][:12]}"
                try:
                    exec_auth = create_execution_authorization(
                        policy_id=pol["authorization_policy_id"],
                        symbol=j["symbol"],
                        agent_id=j["agent_id"],
                        input_snapshot_id=snap,
                        input_hash=j["input_hash"],
                        trigger_reason=j.get("trigger_reason") or trigger_reason,
                    )
                    j["execution_authorization_id"] = exec_auth["execution_authorization_id"]
                    j["input_snapshot_id"] = snap
                    j["status"] = "PENDING"
                    j["created_at"] = _now_iso()
                    jid = f"{j['symbol']}_{j['agent_id']}_{j['input_hash'][:10]}"
                    _atomic_write(JOBS_DIR / "pending" / f"{jid}.json", j)
                    materialized.append(j)
                except PermissionError as e:
                    deferred.append({"symbol": j["symbol"], "agent_id": j["agent_id"], "reason": str(e)})
    elif not dry_run and not pol.get("workers_enabled"):
        # phase 2: plan only
        pass

    return {
        "ok": True,
        "provider_calls": 0,
        "dry_run": dry_run,
        "workers_enabled": bool(pol.get("workers_enabled")),
        "authorization_policy_id": pol.get("authorization_policy_id"),
        "schedule": times,
        "universe_size": len(universe),
        "jobs": jobs,
        "materialized": materialized,
        "deferred": deferred,
        "maria_queued": maria_count,
        "cio_queued": cio_count,
    }


# ── Event watcher (deterministic, no provider calls) ────────────────────────

def rolling_5_session_move_pct(
    current_price: float | None,
    close_5_sessions_ago: float | None,
    *,
    current_as_of: Any = None,
    prior_as_of: Any = None,
    now: datetime | None = None,
) -> tuple[float | None, str | None]:
    """Return (move_pct, reject_reason). move_pct is fractional (0.07 = 7%)."""
    now = now or _now()
    if current_price is None or close_5_sessions_ago is None:
        return None, "MISSING_PRICE"
    try:
        cur = float(current_price)
        prior = float(close_5_sessions_ago)
    except (TypeError, ValueError):
        return None, "MALFORMED_PRICE"
    if cur <= 0 or prior <= 0:
        return None, "NON_POSITIVE_PRICE"
    # future-dated / stale checks when timestamps present
    for label, ts in (("current", current_as_of), ("prior", prior_as_of)):
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if t > now + timedelta(minutes=5):
                return None, f"FUTURE_DATED_{label.upper()}"
            age_h = (now - t).total_seconds() / 3600.0
            if label == "current" and age_h > 24:
                return None, "STALE_CURRENT_PRICE"
        except Exception:
            return None, f"BAD_TIMESTAMP_{label.upper()}"
    return (cur / prior) - 1.0, None


def evaluate_event_trigger(
    symbol: str,
    *,
    current_price: float | None,
    close_5_sessions_ago: float | None,
    current_as_of: Any = None,
    prior_as_of: Any = None,
    threshold: float = 0.07,
) -> dict[str, Any]:
    """Edge-triggered 7% absolute rolling 5-session move. No provider calls."""
    _ensure_dirs()
    move, reject = rolling_5_session_move_pct(
        current_price, close_5_sessions_ago,
        current_as_of=current_as_of, prior_as_of=prior_as_of,
    )
    state_path = EVENT_STATE_DIR / f"{symbol.upper()}.json"
    prev = _read_json(state_path) or {
        "symbol": symbol.upper(),
        "above_threshold": False,
        "last_event_at": None,
        "last_move_pct": None,
    }
    out: dict[str, Any] = {
        "symbol": symbol.upper(),
        "move_pct": move,
        "abs_move_pct": abs(move) if move is not None else None,
        "threshold": threshold,
        "triggered": False,
        "reject_reason": reject,
        "reason_code": None,
        "provider_calls": 0,
        "observations": {
            "current_price": current_price,
            "close_5_sessions_ago": close_5_sessions_ago,
            "current_as_of": current_as_of,
            "prior_as_of": prior_as_of,
        },
    }
    if reject or move is None:
        return out

    # Use tiny epsilon so exact 7% constructed in float still qualifies
    above = abs(move) + 1e-12 >= threshold
    out["above_threshold"] = above
    # 24h cooldown
    last_ev = prev.get("last_event_at")
    if last_ev:
        try:
            le = datetime.fromisoformat(str(last_ev).replace("Z", "+00:00"))
            if le.tzinfo is None:
                le = le.replace(tzinfo=timezone.utc)
            if _now() - le < timedelta(hours=EVENT_CHAIN_COOLDOWN_HOURS):
                out["cooldown_active"] = True
                out["triggered"] = False
                # still update above state without firing
                prev["above_threshold"] = above
                prev["last_move_pct"] = move
                prev["updated_at"] = _now_iso()
                _atomic_write(state_path, prev)
                return out
        except Exception:
            pass

    # edge: was below, now above
    was_above = bool(prev.get("above_threshold"))
    if above and not was_above:
        out["triggered"] = True
        out["reason_code"] = "ROLLING_5_SESSION_MOVE_GE_7PCT"
        prev["last_event_at"] = _now_iso()
        prev["last_event_move_pct"] = move
    prev["above_threshold"] = above
    prev["last_move_pct"] = move
    prev["updated_at"] = _now_iso()
    prev["last_observations"] = out["observations"]
    _atomic_write(state_path, prev)
    out["state"] = prev
    return out


def cio_may_run(symbol: str, *, maria_input_hash: str | None = None) -> tuple[bool, str]:
    """CIO only when current Maria COMPLETE exists (and optional hash compatibility)."""
    from lib.data_broker.watch_domains import load_review_artifacts
    arts = load_review_artifacts(symbol)
    m = arts.get("maria") or {}
    if m.get("status") != "COMPLETE" or m.get("artifact_disposition") != "COMPLETE":
        return False, "MARIA_PREREQUISITE_MISSING"
    if maria_input_hash and m.get("input_hash") and m.get("input_hash") != maria_input_hash:
        # compatible fingerprint: allow if both present and recent — strict for now
        return False, "MARIA_INPUT_HASH_MISMATCH"
    return True, "OK"
