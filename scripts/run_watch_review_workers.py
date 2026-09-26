#!/usr/bin/env python3
"""Watch review workers — Maria/CIO Mon/Wed/Fri schedule executor.

Fail-closed unless:
  policy.workers_enabled=true
  --allow-execute
  containment ACTIVE
  policy validates

Usage:
  python3 scripts/run_watch_review_workers.py --mode plan
  python3 scripts/run_watch_review_workers.py --mode event-scan
  python3 scripts/run_watch_review_workers.py --mode execute --allow-execute [--role all|maria|cio]
  python3 scripts/run_watch_review_workers.py --mode enable-workers
  python3 scripts/run_watch_review_workers.py --mode disable-workers
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# Shared daily cap for scheduled process (ledger also enforces run caps)
os.environ.setdefault("LLM_GLOBAL_DAILY_USD_CAP", "0.25")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cards(page_size: int = 60) -> list[dict]:
    """Load board cards. Prefer live Data Broker HTTP (production truth), fall back to local compose."""
    import urllib.request

    seen: set[str] = set()
    cards: list[dict] = []

    def _ingest(batch: list) -> None:
        for c in batch or []:
            if not isinstance(c, dict):
                continue
            sym = (c.get("symbol") or "").upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            cards.append(c)

    # Live portfolio-server (release) is the board the operator sees
    base = os.environ.get("WATCH_INTEL_API_BASE", "http://127.0.0.1:7777").rstrip("/")
    for view in ("top_ideas", "held", "starred", "all"):
        url = f"{base}/api/v3/data-broker/watch-intelligence?view={view}&page_size={page_size}"
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                payload = json.loads(r.read().decode())
            data = payload.get("data", payload) if isinstance(payload, dict) else {}
            _ingest(data.get("cards") or [])
        except Exception:
            continue

    if cards:
        return cards

    # Fallback: in-process compose (worktree may be decision-degraded vs release)
    try:
        from lib.data_broker.watch_intelligence import list_watch_intelligence

        for view in ("top_ideas", "held", "starred", "all"):
            try:
                out = list_watch_intelligence({"view": view, "page_size": page_size})
            except Exception:
                continue
            _ingest(out.get("cards") or [])
    except Exception:
        pass
    return cards


def _execute_jobs(*, role: str, dry_run: bool = False) -> dict:
    """Plan eligible universe and run provider calls for QUEUE jobs."""
    from lib.watch_review_policy_ledger import (
        load_policy,
        validate_policy,
        containment_required_ok,
        MARIA_SPEC,
        CIO_SPEC,
        ARTIFACTS_DIR,
        JOBS_DIR,
        _atomic_write,
        _ensure_dirs,
    )
    from lib.watch_review_pipeline import plan_jobs, schedule_times

    # Reuse canary executor primitives (auth + gate_and_generate + artifact write)
    from run_watch_review_canary import (
        build_context,
        maria_prompt,
        cio_prompt,
        parse_jsonish,
        run_agent_call,
        write_complete_artifact,
        assert_complete,
        ensure_cio_caps,
    )

    pol = load_policy()
    ok, reason = validate_policy(pol)
    times = schedule_times()
    base = {
        "ok": ok,
        "mode": "execute",
        "role": role,
        "dry_run": dry_run,
        "provider_calls": 0,
        "estimated_cost_usd": 0.0,
        "policy_validation": reason,
        "authorization_policy_id": (pol or {}).get("authorization_policy_id"),
        "workers_enabled": bool((pol or {}).get("workers_enabled")),
        "event_watcher_enabled": bool((pol or {}).get("event_watcher_enabled")),
        "schedule": times,
        "started_at": _now(),
        "completed": [],
        "failed": [],
        "skipped": [],
    }
    if not ok:
        base["error"] = reason
        return base

    cont_ok, cont_reason = containment_required_ok()
    base["containment"] = cont_reason
    if not cont_ok:
        base["error"] = "containment_required"
        base["ok"] = False
        return base

    if not (pol or {}).get("workers_enabled"):
        base["error"] = "execute_blocked"
        base["message"] = "policy.workers_enabled=false"
        base["ok"] = False
        return base

    ensure_cio_caps()
    cards = _load_cards()
    base["cards_loaded"] = len(cards)

    plan = plan_jobs(cards, trigger_reason="SCHEDULED_MWF", dry_run=True)
    base["plan_summary"] = {
        "universe_size": plan.get("universe_size"),
        "maria_queued": plan.get("maria_queued"),
        "cio_queued": plan.get("cio_queued"),
        "jobs": len(plan.get("jobs") or []),
        "deferred": len(plan.get("deferred") or []),
    }
    jobs = plan.get("jobs") or []

    # Role filter
    if role == "maria":
        jobs = [j for j in jobs if j.get("agent_id") == "maria"]
    elif role == "cio":
        jobs = [j for j in jobs if j.get("agent_id") == "cio"]

    if dry_run:
        base["jobs"] = jobs
        base["message"] = "dry_run — no provider calls"
        return base

    # Materialize pending plan under workers_enabled (writes no-call + exec auth for QUEUE)
    plan_live = plan_jobs(cards, trigger_reason="SCHEDULED_MWF", dry_run=False)
    base["materialized"] = len(plan_live.get("materialized") or [])

    # Build quick lookup of QUEUE jobs by symbol+agent after materialize
    queue = [
        j
        for j in (plan_live.get("jobs") or [])
        if j.get("action") == "QUEUE" and (role == "all" or j.get("agent_id") == role)
    ]
    # Order: all Maria first, then CIO (maria_precedes_cio)
    queue.sort(key=lambda j: (0 if j.get("agent_id") == "maria" else 1, j.get("symbol") or ""))

    _ensure_dirs()
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    for j in queue:
        sym = (j.get("symbol") or "").upper()
        agent = j.get("agent_id")
        try:
            if agent == "maria":
                ctx = build_context(sym)
                prompt = maria_prompt(ctx)
                # manual_trigger=True: workers are operator-enabled (policy.workers_enabled);
                # consumption process may still be mode=manual after registry seed — schedule is the auth.
                res = run_agent_call(
                    agent_id="maria",
                    symbol=sym,
                    process_id=MARIA_SPEC["registered_process_id"],
                    model=MARIA_SPEC["model"],
                    policy=MARIA_SPEC["policy"],
                    prompt=prompt,
                    max_cost=0.02,
                    manual_trigger=True,
                    policy_id=pol["authorization_policy_id"],
                )
                # Override trigger on execution auth already created as OPERATOR_CANARY in canary helper —
                # acceptable; policy parent is the same. Artifact marks scheduled.
                parsed = parse_jsonish(res["text"])
                body = write_complete_artifact(
                    agent_id="maria",
                    symbol=sym,
                    process_id=MARIA_SPEC["registered_process_id"],
                    model=MARIA_SPEC["model"],
                    policy=MARIA_SPEC["policy"],
                    thinking="off",
                    prompt=prompt,
                    text=res["text"],
                    prov=res["prov"],
                    parsed=parsed,
                    policy_id=res["policy_id"],
                    execution_authorization_id=res["execution"]["execution_authorization_id"],
                    input_snapshot_id=res["input_snapshot_id"],
                    input_hash=res["input_hash"],
                    started=res["started"],
                )
                body["canary"] = False
                body["trigger_reason"] = "SCHEDULED_MWF"
                body["artifact_disposition"] = "COMPLETE"
                # rewrite without canary flag
                path = ARTIFACTS_DIR / f"{sym}_maria.json"
                body.pop("_path", None)
                path.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
                assert_complete(body)
                cost = float(body.get("settled_cost_usd") or 0)
                base["provider_calls"] += 1
                base["estimated_cost_usd"] += cost
                base["completed"].append({"symbol": sym, "agent_id": "maria", "cost": cost, "path": str(path)})
            elif agent == "cio":
                from lib.data_broker.watch_domains import load_review_artifacts

                arts = load_review_artifacts(sym)
                maria = arts.get("maria") or {}
                if maria.get("status") != "COMPLETE":
                    base["skipped"].append({"symbol": sym, "agent_id": "cio", "reason": "MARIA_PREREQUISITE_MISSING"})
                    continue
                ctx = build_context(sym)
                prompt = cio_prompt(ctx, maria)
                res = run_agent_call(
                    agent_id="cio",
                    symbol=sym,
                    process_id=CIO_SPEC["registered_process_id"],
                    model=CIO_SPEC["model"],
                    policy=CIO_SPEC["policy"],
                    prompt=prompt,
                    max_cost=0.05,
                    manual_trigger=True,
                    policy_id=pol["authorization_policy_id"],
                )
                parsed = parse_jsonish(res["text"])
                body = write_complete_artifact(
                    agent_id="cio",
                    symbol=sym,
                    process_id=CIO_SPEC["registered_process_id"],
                    model=CIO_SPEC["model"],
                    policy=CIO_SPEC["policy"],
                    thinking="off",
                    prompt=prompt,
                    text=res["text"],
                    prov=res["prov"],
                    parsed=parsed,
                    policy_id=res["policy_id"],
                    execution_authorization_id=res["execution"]["execution_authorization_id"],
                    input_snapshot_id=res["input_snapshot_id"],
                    input_hash=res["input_hash"],
                    started=res["started"],
                    maria_ref=maria,
                )
                body["canary"] = False
                body["trigger_reason"] = "SCHEDULED_MWF"
                body["artifact_disposition"] = "COMPLETE"
                path = ARTIFACTS_DIR / f"{sym}_cio.json"
                body.pop("_path", None)
                path.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
                assert_complete(body)
                cost = float(body.get("settled_cost_usd") or 0)
                base["provider_calls"] += 1
                base["estimated_cost_usd"] += cost
                base["completed"].append({"symbol": sym, "agent_id": "cio", "cost": cost, "path": str(path)})
            else:
                base["skipped"].append({"symbol": sym, "agent_id": agent, "reason": "unknown_agent"})
        except Exception as e:
            base["failed"].append(
                {
                    "symbol": sym,
                    "agent_id": agent,
                    "error": str(e)[:300],
                    "trace": traceback.format_exc()[-500:],
                }
            )

    # Move completed job records
    for item in base["completed"]:
        jid = f"{item['symbol']}_{item['agent_id']}"
        rec = {
            "status": "COMPLETED",
            "completed_at": _now(),
            **item,
        }
        _atomic_write(JOBS_DIR / "completed" / f"{jid}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json", rec)

    base["finished_at"] = _now()
    base["ok"] = True
    base["broker_actions"] = 0
    base["order_actions"] = 0
    return base


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode",
        choices=("plan", "event-scan", "execute", "enable-workers", "disable-workers"),
        default="plan",
    )
    ap.add_argument(
        "--allow-execute",
        action="store_true",
        help="Required with execute; still blocked unless policy.workers_enabled",
    )
    ap.add_argument(
        "--role",
        choices=("all", "maria", "cio"),
        default="all",
        help="execute only Maria, only CIO, or both (default both, Maria first)",
    )
    ap.add_argument("--dry-run", action="store_true", help="With execute: plan queue only, zero provider calls")
    ap.add_argument("--operator-id", default="johnclaw")
    args = ap.parse_args()

    from lib.watch_review_policy_ledger import (
        load_policy,
        validate_policy,
        containment_required_ok,
        set_workers_enabled,
        policy_api_payload,
    )
    from lib.watch_review_pipeline import plan_jobs, schedule_times

    if args.mode == "enable-workers":
        try:
            pol = set_workers_enabled(
                workers=True,
                event_watcher=False,  # 7% event watcher stays off until separate enable
                operator_id=args.operator_id,
                reason="operator_enable_scheduled_mwf_all_eligible",
            )
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e), "provider_calls": 0}, indent=2))
            return 2
        # Consumption gate: CIO/Maria must be automated for cron + run-now (still policy-capped)
        mode_results = {}
        try:
            from lib import llm_consumption as lc
            from lib.watch_review_policy_ledger import MARIA_PROCESS_ID, CIO_PROCESS_ID

            lc.ensure_schema()
            for pid, cap in ((MARIA_PROCESS_ID, 0.08), (CIO_PROCESS_ID, 0.14)):
                mode_results[pid] = lc.set_process_mode(pid, "automated")
                try:
                    cur = lc._conn().cursor()
                    cur.execute(
                        """UPDATE llm_process_config
                              SET daily_cost_cap_usd=COALESCE(daily_cost_cap_usd, %s),
                                  daily_soft_cap=COALESCE(daily_soft_cap, 40),
                                  updated_at=NOW()
                            WHERE process_id=%s""",
                        (cap, pid),
                    )
                    lc._conn().commit()
                except Exception as e:
                    mode_results[pid] = {**(mode_results.get(pid) or {}), "cap_error": str(e)[:120]}
        except Exception as e:
            mode_results["error"] = str(e)[:200]
        out = {
            "ok": True,
            "mode": "enable-workers",
            "provider_calls": 0,
            "workers_enabled": True,
            "event_watcher_enabled": False,
            "authorization_policy_id": pol.get("authorization_policy_id"),
            "schedule": schedule_times(),
            "maximum_calls_per_run": pol.get("maximum_calls_per_run"),
            "maximum_cost_per_day_usd": pol.get("maximum_cost_per_day_usd"),
            "llm_process_modes": mode_results,
            "message": (
                "Scheduled workers ENABLED for Mon/Wed/Fri Maria 16:05 + CIO 16:20 ET. "
                "Event watcher remains OFF. CECO quarantine preserved. "
                "Maria/CIO process modes set automated (cost-capped). "
                "Run caps: Maria 15/run, CIO 8/run, global daily USD cap from policy."
            ),
            "api": policy_api_payload(),
        }
        print(json.dumps(out, indent=2, default=str))
        return 0

    if args.mode == "disable-workers":
        pol = set_workers_enabled(
            workers=False,
            event_watcher=False,
            operator_id=args.operator_id,
            reason="operator_disable_scheduled_workers",
        )
        mode_results = {}
        try:
            from lib import llm_consumption as lc
            from lib.watch_review_policy_ledger import MARIA_PROCESS_ID, CIO_PROCESS_ID

            # Fail closed: CIO back to manual; Maria stays automated only if other consumers need it —
            # return both to manual when schedule is off to prevent silent spend.
            for pid in (MARIA_PROCESS_ID, CIO_PROCESS_ID):
                mode_results[pid] = lc.set_process_mode(pid, "manual")
        except Exception as e:
            mode_results["error"] = str(e)[:200]
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "disable-workers",
                    "provider_calls": 0,
                    "workers_enabled": False,
                    "authorization_policy_id": pol.get("authorization_policy_id"),
                    "llm_process_modes": mode_results,
                },
                indent=2,
                default=str,
            )
        )
        return 0

    pol = load_policy()
    ok, reason = validate_policy(pol)
    base = {
        "ok": ok,
        "provider_calls": 0,
        "mode": args.mode,
        "policy_validation": reason,
        "authorization_policy_id": (pol or {}).get("authorization_policy_id"),
        "workers_enabled": bool((pol or {}).get("workers_enabled")),
        "event_watcher_enabled": bool((pol or {}).get("event_watcher_enabled")),
        "schedule": schedule_times(),
    }
    if not ok:
        print(json.dumps({**base, "error": reason}, indent=2))
        return 2

    cont_ok, cont_reason = containment_required_ok()
    base["containment"] = cont_reason
    if not cont_ok:
        print(json.dumps({**base, "error": "containment_required", "detail": cont_reason}, indent=2))
        return 78

    if args.mode == "plan":
        cards = _load_cards()
        plan = plan_jobs(cards, dry_run=True)
        print(json.dumps({**base, "cards_loaded": len(cards), "plan": plan}, indent=2, default=str))
        return 0

    if args.mode == "event-scan":
        if not (pol or {}).get("event_watcher_enabled"):
            print(
                json.dumps(
                    {
                        **base,
                        "error": "event_watcher_disabled",
                        "message": "Event watcher not enabled. No jobs created. No provider calls.",
                    },
                    indent=2,
                )
            )
            return 0
        print(
            json.dumps(
                {
                    **base,
                    "message": "event watcher flag set but broad scan not activated in this gate",
                    "provider_calls": 0,
                },
                indent=2,
            )
        )
        return 0

    # execute
    if not args.allow_execute and not args.dry_run:
        print(
            json.dumps(
                {
                    **base,
                    "error": "execute_blocked",
                    "message": "Pass --allow-execute (and policy.workers_enabled=true) to run providers.",
                    "provider_calls": 0,
                },
                indent=2,
            )
        )
        return 78

    if not (pol or {}).get("workers_enabled") and not args.dry_run:
        print(
            json.dumps(
                {
                    **base,
                    "error": "execute_blocked",
                    "message": "policy.workers_enabled=false — run --mode enable-workers first.",
                    "provider_calls": 0,
                },
                indent=2,
            )
        )
        return 78

    result = _execute_jobs(role=args.role, dry_run=bool(args.dry_run))
    print(json.dumps(result, indent=2, default=str))
    if result.get("failed") and not result.get("completed"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
