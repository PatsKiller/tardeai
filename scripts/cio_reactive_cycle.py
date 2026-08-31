#!/usr/bin/env python3
"""cio_reactive_cycle.py — Event + goal reactive wake cycle (READ_ONLY_ADVISORY).

Runs frequently (systemd timer) as a safety net *beside* the 30-min heartbeat.
Does NOT trade or mutate risk/broker state.

Cycle:
  1. Poll CIOEventBus for each agent subscription
  2. Enqueue wake jobs (deduped) into CIOWakeJobStore
  3. Enqueue goal-due wakes via CIOWakeDispatcher.enqueue_goal_wakes
  4. Optional: poll_and_dispatch (creates CIO runs when run_store available)
  5. Advance event-bus cursors only after successful enqueue/skip

Kill switch: data/runtime/CIO_REACTIVE_DISABLED
Enable flag: env CIO_REACTIVE_WAKES=1 (default on when kill switch absent)

Usage:
  .venv/bin/python scripts/cio_reactive_cycle.py --once
  .venv/bin/python scripts/cio_reactive_cycle.py --once --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
# G2: root-only + scripts.lib — never also put scripts/ on path
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)

KILL = ROOT / "data" / "runtime" / "CIO_REACTIVE_DISABLED"
STATUS_PATH = ROOT / "data" / "runtime" / "cio_reactive_cycle_last.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enabled() -> bool:
    if KILL.exists():
        return False
    return os.environ.get("CIO_REACTIVE_WAKES", "1").strip().lower() not in (
        "0", "false", "off", "no",
    )


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


# A wake raised from a two-week-old event is analysis about a portfolio that no
# longer exists. The situation backlog on this bus is 1,100 events reaching back
# 15 days; routing `situation.raised` correctly started draining it at 12 per
# cycle, which is "processing a historical backlog" — operator-only under the
# wave rules, and the exact failure S1 names: fluent, confident, wrong, and
# delivered as if current.
#
# So the cycle only wakes on events young enough to still be about today. Older
# ones are counted and reported as stale, never silently dropped.
EVENT_MAX_AGE_HOURS = float(os.environ.get("CIO_REACTIVE_EVENT_MAX_AGE_HOURS", "48"))


def _event_age_hours(ev: Any, now: datetime) -> Optional[float]:
    """Age of an event in hours, or None when it carries no usable timestamp."""
    raw = getattr(ev, "timestamp", None)
    if raw is None and isinstance(ev, dict):
        raw = ev.get("timestamp") or ev.get("occurred_at")
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except Exception:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return (now - d).total_seconds() / 3600.0


def _known_agents() -> frozenset[str]:
    """Agents allowed to be named as a wake's target.

    Sourced from the routing table so the allowlist cannot drift away from the
    subscriptions it is meant to mirror.
    """
    try:
        from scripts.lib.cio_event_bus import AGENT_EVENT_ROUTING
        return frozenset(AGENT_EVENT_ROUTING)
    except Exception:
        return frozenset({"alex", "steph", "hermes", "morgan"})


KNOWN_AGENTS = _known_agents()


def run_once(*, max_wakes: int = 12, dispatch: bool = False) -> dict[str, Any]:
    """Enqueue reactive and goal wakes. Does NOT claim them by default.

    `dispatch` defaulted to True, and this cycle builds its dispatcher WITHOUT a
    run_store -- `CIOWakeDispatcher.poll_and_dispatch` only calls
    `run_store.create_run()` when one is injected. So every cycle claimed and
    dispatched wakes and created nothing, while the cron entrypoint that DOES
    carry a run_store then found an empty queue and logged `dispatched=0`.

    Measured 2026-08-27: 1,282 wakes dispatched, 55 ever went in-flight -- 1,227
    consumed and discarded. No CIO run has been created since 18:01 despite the
    dispatcher running every 5 minutes.

    That also makes the causal trigger unreachable: HERMES_RESOLVED cannot fire
    on a run that is never created, which is why it has 0 occurrences.

    `cio_wake_dispatch_entrypoint` is the documented sole claimant ("CIOWakeDispatcher
    is the sole wake owner"). This cycle enqueues; it does not claim. Pass
    --dispatch to opt in for manual use.
    """
    out: dict[str, Any] = {
        "ts": _now(),
        "authority": "READ_ONLY_ADVISORY",
        "enabled": _enabled(),
        "event_enqueued": [],
        "event_skipped": [],
        "event_stale": [],
        "cursor_advanced": [],
        "goal_enqueue": {},
        "dispatch": {},
        "errors": [],
    }
    if not out["enabled"]:
        out["errors"].append("reactive wakes disabled (kill switch or CIO_REACTIVE_WAKES=0)")
        return out

    try:
        from scripts.lib.cio_event_bus import (
            CIOEventBus,
            AGENT_EVENT_ROUTING,
            EVENT_PRIORITY,
        )
    except Exception as exc:
        out["errors"].append(f"event_bus_import: {exc}")
        return out

    try:
        from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    except Exception as exc:
        out["errors"].append(f"wake_store_import: {exc}")
        return out

    bus = CIOEventBus()
    wake_store = CIOWakeJobStore()
    _now_dt = datetime.now(timezone.utc)
    hour = _now_dt.strftime("%Y%m%d%H")
    enqueued_n = 0
    recent_types: list[str] = []

    for agent_id, event_types in AGENT_EVENT_ROUTING.items():
        try:
            events = bus.poll(consumer=f"reactive:{agent_id}", event_types=list(event_types))
        except Exception as exc:
            out["errors"].append(f"poll:{agent_id}:{exc}")
            continue
        if not events:
            continue
        last_id = None
        for ev in events:
            if enqueued_n >= max_wakes:
                break
            et = getattr(ev, "event_type", None) or (ev.get("event_type") if isinstance(ev, dict) else None)
            eid = getattr(ev, "event_id", None) or (ev.get("event_id") if isinstance(ev, dict) else None)
            if not et or not eid:
                continue
            recent_types.append(str(et))

            # Freshness bound. An unstamped event is allowed through — refusing
            # it would silently drop live events for a missing field — but a
            # demonstrably old one is not.
            _age = _event_age_hours(ev, _now_dt)
            if _age is not None and _age > EVENT_MAX_AGE_HOURS:
                out["event_stale"].append({
                    "event_id": eid, "event_type": str(et),
                    "age_hours": round(_age, 1),
                    "max_age_hours": EVENT_MAX_AGE_HOURS,
                })
                last_id = eid          # advance past it; do not re-read forever
                continue

            wake_job_id = f"wake_ev_{agent_id}_{_hash(eid)}_{hour}"
            # Dedup: if already in store as pending/active, skip
            try:
                existing = wake_store.get_wake_job(wake_job_id) if hasattr(wake_store, "get_wake_job") else None
                if existing and existing.get("current_status") in (
                    "PENDING", "CLAIMED", "DISPATCHED", "IN_FLIGHT", "ACKNOWLEDGED",
                ):
                    out["event_skipped"].append({"wake_job_id": wake_job_id, "reason": "already_active"})
                    last_id = eid
                    continue
            except Exception:
                pass

            priority = EVENT_PRIORITY.get(str(et), "NORMAL")
            reason = str(et).upper().replace(".", "_")
            # Carry the event's own subject onto the wake. Without this the wake
            # is subject-less and the record consult in the dispatcher has
            # nothing to load by — which is exactly why `load-by-subject` was
            # never called: 0 of 1,513 wakes carried a subject.
            _payload = getattr(ev, "payload", None)
            if _payload is None and isinstance(ev, dict):
                _payload = ev.get("payload")
            _payload = _payload if isinstance(_payload, dict) else {}
            _symbols = [str(s) for s in (_payload.get("symbols") or []) if s]
            _situation = _payload.get("situation_type")
            # `owner_agent` is payload data, and target_agent chooses which agent
            # handles the wake. Dispatching on whatever the payload says would let
            # an event pick its own handler — including one that does not exist,
            # or one that was never meant to receive that class of work. Validate
            # against the known agent set and fall back to the subscription that
            # actually matched, recording the rejected value rather than
            # discarding it silently.
            _claimed_owner = str(_payload.get("owner_agent") or "").strip() or None
            if _claimed_owner and _claimed_owner in KNOWN_AGENTS:
                _owner, _owner_rejected = _claimed_owner, None
            else:
                _owner, _owner_rejected = None, _claimed_owner
            wake_payload = {
                "wake_job_id": wake_job_id,
                "trigger_type": "EVENT_BUS",
                "trigger_ref": eid,
                "trigger_hash": _hash(f"{agent_id}:{eid}"),
                "reason_codes": ["EVENT_BUS", reason],
                "required_domains": ["portfolio"],
                "wake_intent": "NEW_RUN",
                "idempotency_key": wake_job_id,
                "context": {
                    # The payload names its owner; prefer it over the routing
                    # key so a morgan-owned situation does not arrive as alex's.
                    "target_agent": _owner or agent_id,
                    "routed_via_agent": agent_id,
                    # Present only when the payload named an agent we do not know.
                    "owner_agent_rejected": _owner_rejected,
                    "event_type": et,
                    "event_id": eid,
                    "priority": priority,
                    "authority": "READ_ONLY_ADVISORY",
                    "symbols": _symbols,
                    # First symbol is the wake's subject; a multi-symbol
                    # situation still resolves to one record to consult.
                    "symbol": _symbols[0] if _symbols else None,
                    "situation_type": _situation,
                    "plan_id": _payload.get("plan_id"),
                    "shadow": _payload.get("shadow"),
                },
            }
            try:
                wake_store.enqueue(
                    wake_payload,
                    actor_id="cio_reactive_cycle",
                    actor_type="system",
                    authority="READ_ONLY_ADVISORY",
                )
                out["event_enqueued"].append({
                    "agent_id": agent_id,
                    "event_type": et,
                    "event_id": eid,
                    "wake_job_id": wake_job_id,
                })
                enqueued_n += 1
            except Exception as exc:
                # treat duplicate as skip
                msg = str(exc)
                if "already" in msg.lower() or "duplicate" in msg.lower() or "exists" in msg.lower():
                    out["event_skipped"].append({"wake_job_id": wake_job_id, "reason": msg[:120]})
                else:
                    out["errors"].append(f"enqueue:{wake_job_id}:{msg[:160]}")
            last_id = eid

        if last_id:
            try:
                bus.advance_cursor(f"reactive:{agent_id}", last_id)
                out["cursor_advanced"].append({"consumer": f"reactive:{agent_id}", "event_id": last_id})
            except Exception as exc:
                out["errors"].append(f"cursor:{agent_id}:{exc}")

    # Goal-due / event-linked wakes
    try:
        from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher
        disp = CIOWakeDispatcher(wake_store=wake_store)
        out["goal_enqueue"] = disp.enqueue_goal_wakes(
            max_new=max(1, max_wakes // 2),
            recent_event_types=list(set(recent_types)) or None,
        )
        if dispatch:
            out["dispatch"] = disp.poll_and_dispatch(max_dispatches=max_wakes)
    except Exception as exc:
        out["errors"].append(f"dispatcher:{exc}")

    # Situation detector (Phase 2a/P2) — AFTER event path; live Data Broker evidence
    try:
        from scripts.lib.cio_situation_detector import (
            build_evidence_from_broker,
            run_detector_safe,
        )
        evidence = build_evidence_from_broker()
        out["situations"] = run_detector_safe(evidence=evidence or {})
        out["situations_evidence_keys"] = sorted((evidence or {}).keys())
    except Exception as exc:
        out["situations"] = {"errors": [f"situations_hook:{exc}"], "plans_created": []}

    # Two-way curation emit (forward edge) — CIO situations seed watchlist directives.
    # Emits from (1) newly created plans this pass AND (2) open S4/S5/S8 plans so
    # deduped-but-still-open situations keep the loop circulating (rate-limited).
    # Shadow/advisory + fail-soft: stages feedback only (firewalled); the app-role
    # drain (watch_directives_service) governs promotion. Never wedges the cycle.
    try:
        from scripts.lib.two_way_curation import (
            CIO_CURATION_SITUATIONS,
            cio_situation_to_feedback,
            emit_all,
        )
        _situations = out.get("situations") or {}
        _curation_emitted = 0
        _seen_keys: set[str] = set()
        plans_to_emit: list[dict] = list(_situations.get("plans_detail") or [])
        # Re-seed from open plans of curation types (materiality + rate limit).
        try:
            from scripts.lib.cio_plans import CIOPlanStore
            for _op in CIOPlanStore().list_open_plans(limit=40) or []:
                st = str(_op.get("situation_type") or "")
                if st not in CIO_CURATION_SITUATIONS:
                    continue
                plans_to_emit.append({
                    "plan_id": _op.get("plan_id"),
                    "situation_type": st,
                    "symbols": _op.get("symbols") or [],
                    "status": _op.get("status"),
                    "rationale": (_op.get("summary") or _op.get("narrative") or "")[:300],
                    "sectors": (_op.get("extra") or {}).get("sectors")
                               or (_op.get("extra") or {}).get("rotation_targets"),
                    "seed_symbols": (_op.get("extra") or {}).get("seed_symbols"),
                })
        except Exception as _open_exc:
            out.setdefault("curation_open_plan_errors", str(_open_exc)[:120])
        for _plan in plans_to_emit:
            st = str(_plan.get("situation_type") or "")
            if st not in CIO_CURATION_SITUATIONS:
                continue
            key = f"{st}|{','.join(sorted(str(s).upper() for s in (_plan.get('symbols') or [])[:5]))}"
            if key in _seen_keys:
                continue
            _seen_keys.add(key)
            _curation_emitted += emit_all("cio", cio_situation_to_feedback(_plan)).get("staged", 0)
        out["curation_emitted"] = _curation_emitted
        out["curation_plans_considered"] = len(_seen_keys)
        # Keep residual staging small: light stage-only drain of desk sources after emit
        # so CIO re-seed does not wait for the 30m full watch_directives --apply.
        if _curation_emitted > 0 or os.environ.get("CURATION_DRAIN_AFTER_EMIT", "1").strip() not in (
            "0", "false", "no",
        ):
            try:
                import psycopg2
                import psycopg2.extras
                import directive_promotion as _dp
                from scripts.lib.two_way_curation import drain_curation_sources as _drain_cs

                _conn = psycopg2.connect(
                    host=os.getenv("DB_HOST", "localhost"),
                    port=os.getenv("DB_PORT", "5432"),
                    dbname=os.getenv("DB_NAME", "trade_ai"),
                    user=os.getenv("DB_USER", "trade_ai"),
                    password=os.getenv("DB_PASSWORD"),
                    cursor_factory=psycopg2.extras.RealDictCursor,
                )
                _cur = _conn.cursor()
                _cur.execute("SET lock_timeout = '2s'")
                _rep: dict = {"detail": [], "promoted": 0, "staged": 0}

                def _resolve(d):
                    sp = d.get("spec") or {}
                    if d.get("kind") == "ticker" and sp.get("symbol"):
                        return [str(sp["symbol"]).upper()]
                    seeds = list(sp.get("seed_symbols") or [])
                    if sp.get("symbol"):
                        seeds.insert(0, sp["symbol"])
                    return [str(s).upper() for s in seeds if s][:5]

                def _eval(sym, did, reason, source, auto):
                    try:
                        # stage-only: record hit, avoid Finviz lock storms on the reactive timer
                        return _dp.promote_directive_lead(
                            sym, did, reason, source, conn=_conn, auto=False
                        )
                    except Exception as _e:
                        return {"status": "ERROR", "error": str(_e)[:120]}

                _drain_cs(
                    _cur, False, _rep, _eval, _resolve,
                    drain_limit=int(os.environ.get("CURATION_DRAIN_LIMIT", "15")),
                    auto_apply=None,
                )
                _conn.commit()
                _conn.close()
                out["curation_drained"] = _rep.get("curation_drained", 0)
                out["curation_staged_hits"] = _rep.get("staged", 0)
            except Exception as _drain_exc:
                out["curation_drain_error"] = str(_drain_exc)[:160]
    except Exception as exc:
        out["curation_emitted"] = 0
        out["errors"].append(f"curation_emit:{exc}")

    # Restart-safe cheap retry of research→product reassessment. Never reruns paid LLM.
    try:
        from scripts.lib.cio_product_reassessment import retry_pending_reassessments
        out["reassessment_retry"] = retry_pending_reassessments(limit=3)
    except Exception as exc:
        out.setdefault("errors", []).append(f"reassessment_retry:{exc}")

    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(out, indent=2, default=str))
    except Exception:
        pass
    return out


def main() -> int:
    # G2: after imports settle — refuse dual lib.X / scripts.lib.X identity
    from scripts.lib import assert_single_import_identity
    assert_single_import_identity()
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", default=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-wakes", type=int, default=12)
    # --no-dispatch kept for compatibility; dispatching is now off by default and
    # --dispatch opts in. See run_once.__doc__ for why.
    ap.add_argument("--no-dispatch", action="store_true")
    ap.add_argument("--dispatch", action="store_true",
                    help="claim and dispatch wakes (default: leave them for the sole claimant)")
    args = ap.parse_args()
    res = run_once(max_wakes=args.max_wakes,
                   dispatch=bool(args.dispatch) and not args.no_dispatch)
    if args.json:
        print(json.dumps(res, indent=2, default=str))
    else:
        print(f"[{res['ts']}] reactive cycle enabled={res['enabled']}")
        print(f"  event_enqueued={len(res['event_enqueued'])} skipped={len(res['event_skipped'])}")
        ge = res.get("goal_enqueue") or {}
        print(f"  goal_enqueued={len(ge.get('enqueued') or [])} blocked={len(ge.get('blocked_not_ready') or [])}")
        d = res.get("dispatch") or {}
        print(f"  dispatched={d.get('dispatched_count', 0)} errors={len(res.get('errors') or [])}")
        for e in (res.get("errors") or [])[:5]:
            print(f"  ERR: {e}")
    return 0 if not res.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
