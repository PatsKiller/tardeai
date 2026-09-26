#!/usr/bin/env python3
"""Server-owned refresh cadence for the governed Watch decision desk.

The browser never schedules. Local deterministic rebuilds may repair incomplete
research evidence, but OAuth blind lanes are eligible only after deterministic
quality admission and ticket validation pass. Non-held quarantined names remain
in audit and research history but do not consume the active refresh budget.
Premium is operator-only and is never scheduled.

    --dry-run   print the quality-aware plan; no enqueue or writes
    --run       sweep stale jobs and enqueue bounded work
"""
from __future__ import annotations

import argparse
import json
import glob
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

import watch_decision_refresh as wdr  # noqa: E402
import watch_packet_quality as packet_quality  # noqa: E402

TIER_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
QUALITY_ORDER = {"ADMITTED": 0, "UNASSESSED": 1, "RESEARCH_ONLY": 2, "QUARANTINED": 3}


def _now():
    return datetime.now(timezone.utc)


def _priority_key(item: dict) -> tuple:
    return (
        TIER_ORDER.get(item.get("tier"), 9),
        QUALITY_ORDER.get(item.get("quality"), 9),
        str(item.get("symbol") or ""),
    )


def build_plan(conn) -> dict:
    import packet_invalidation as invalidation

    policy = wdr.load_policy()
    tiers = policy.get("tiers") or {}
    limits = policy.get("limits") or {}
    cap = int(limits.get("max_symbols_per_scheduler_pass", 40))
    cur = conn.cursor()
    cur.execute("""SELECT symbol, generated_at, model_review_mode, packet
                   FROM decision_packets WHERE superseded_by IS NULL""")
    packets = {
        row[0].upper(): {
            "generated_at": row[1],
            "mode": row[2],
            "packet": row[3] or {},
            "gate": packet_quality.packet_gate(row[3] or {}),
        }
        for row in cur.fetchall()
    }
    cur.execute("SELECT upper(symbol) FROM operator_starred_symbols")
    starred = {row[0] for row in cur.fetchall()}
    population = sorted(set(packets) | starred)

    cur.execute("""SELECT DISTINCT symbol FROM watch_decision_refresh_jobs
                   WHERE state IN ('QUEUED','RUNNING')""")
    in_flight = {row[0].upper() for row in cur.fetchall()}

    plan = {
        "local": [],
        "blind": [],
        "skipped_in_flight": [],
        "quality_deferred": [],
        "not_due": [],
    }
    quality_counts = {state: 0 for state in QUALITY_ORDER}
    now = _now()

    for symbol in population:
        packet_info = packets.get(symbol)
        gate = packet_info["gate"] if packet_info else {
            "quality": "UNASSESSED", "new_entry_allowed": None,
            "deterministic": "NOT_RUN", "held": False,
            "quality_reasons": [], "validation_source": None,
        }
        quality_state = gate["quality"] if gate["quality"] in QUALITY_ORDER else "UNASSESSED"
        quality_counts[quality_state] += 1
        held_or_starred = gate["held"] or symbol in starred

        if symbol in in_flight:
            plan["skipped_in_flight"].append(symbol)
            continue

        tier = wdr.classify_priority(symbol, conn)
        tier_config = tiers.get(tier) or {}
        packet = packet_info

        # A non-held quarantined research symbol remains queryable but is not an
        # active scheduler candidate. Operator stars and holdings stay visible
        # for evidence/management, never as an implicit new-entry exemption.
        # 2026-09-26: a quarantine judged on a packet from 09-13 was never looked at
        # again (1,021 deferred). Past the recheck age, rebuild locally so the gate
        # judges current data; a rebuild grants no entry, it only re-assesses.
        recheck_min = float(os.getenv("WATCH_QUARANTINE_RECHECK_DAYS", "7")) * 1440
        quarantine_recheck = bool(
            quality_state == "QUARANTINED" and not held_or_starred and packet_info
            and recheck_min > 0
            and (now - packet_info["generated_at"]).total_seconds() / 60 > recheck_min
        )
        if quality_state == "QUARANTINED" and not held_or_starred and not quarantine_recheck:
            plan["quality_deferred"].append({
                "symbol": symbol,
                "tier": tier,
                "quality": quality_state,
                "deterministic": gate["deterministic"],
                "validation_source": gate.get("validation_source"),
                "why": (gate["quality_reasons"] or gate.get("hard_failures")
                        or ["quality gate refused active entry"])[0],
            })
            continue

        local_ceiling = tier_config.get("full_local_packet_max_minutes")
        blind_ceiling = tier_config.get("standard_blind_max_minutes")
        due_local = False
        due_reason = ""

        if quarantine_recheck:
            due_local = True
            due_reason = "QUARANTINE_RECHECK — quarantine judged on a packet older than the recheck age"
        elif not packet:
            due_local = True
            due_reason = "PACKET_ABSENT — deterministic quality assessment required"
        elif quality_state == "UNASSESSED":
            due_local = True
            due_reason = "QUALITY_UNASSESSED — rebuild locally before any model lane"
        else:
            age_min = (now - packet["generated_at"]).total_seconds() / 60
            due_local = bool(local_ceiling and age_min > float(local_ceiling))
            if due_local:
                due_reason = f"age {age_min:.0f}m > ceiling {local_ceiling}m"
            else:
                try:
                    snapshot = invalidation.build_current_input_snapshot(symbol, conn)
                    comparison = invalidation.compare_packet_inputs(packet["packet"], snapshot)
                    if not comparison.get("inputs_match"):
                        due_local = True
                        due_reason = "inputs changed"
                except Exception:
                    conn.rollback()

        if not due_local:
            plan["not_due"].append({
                "symbol": symbol,
                "tier": tier,
                "quality": quality_state,
                "deterministic": gate["deterministic"],
            })
            continue

        local_item = {
            "symbol": symbol,
            "tier": tier,
            "quality": quality_state,
            "deterministic": gate["deterministic"],
            "validation_source": gate.get("validation_source"),
            "held_or_starred": held_or_starred,
            "why": due_reason,
        }
        plan["local"].append(local_item)

        # OAuth blind reasoning is an oversight layer, not a discovery filter.
        # It is scheduled only for an admitted, deterministically valid ticket.
        if (quality_state == "ADMITTED"
                and gate["new_entry_allowed"] is not False
                and gate["deterministic"] == "PASS"
                and blind_ceiling and float(blind_ceiling) > 0
                and packet):
            age_min = (now - packet["generated_at"]).total_seconds() / 60
            if age_min > float(blind_ceiling):
                plan["blind"].append({
                    "symbol": symbol,
                    "tier": tier,
                    "quality": quality_state,
                    "validation_source": gate.get("validation_source"),
                    "why": f"admitted deterministic PASS; blind age {age_min:.0f}m > {blind_ceiling}m",
                })

    plan["local"].sort(key=_priority_key)
    plan["local"] = plan["local"][:cap]
    local_symbols = {item["symbol"] for item in plan["local"]}
    plan["blind"] = [item for item in plan["blind"] if item["symbol"] in local_symbols]
    plan["blind"].sort(key=_priority_key)
    lane_budget = int(limits.get("max_blind_lane_calls_per_hour", 60))
    plan["blind"] = plan["blind"][:max(0, lane_budget // 2)]
    plan["quality_deferred"].sort(key=_priority_key)

    plan["estimates"] = {
        "local_symbols": len(plan["local"]),
        "blind_symbols": len(plan["blind"]),
        "lane_calls": 2 * len(plan["blind"]),
        "paid_cost_usd": 0,
        "population": len(population),
        "in_flight": len(plan["skipped_in_flight"]),
        "not_due": len(plan["not_due"]),
        "quality_deferred": len(plan["quality_deferred"]),
        "quality_counts": quality_counts,
        "policy_version": wdr.policy_version(),
        "quality_policy_version": "watch-quality-admission-v1",
        "authority": "local deterministic first; OAuth only after ADMITTED + PASS; premium never scheduled",
    }
    return plan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    conn = wdr._conn()
    if args.dry_run or not args.run:
        plan = build_plan(conn)
        print(json.dumps({
            "dry_run": True,
            **plan["estimates"],
            "local": plan["local"],
            "blind": plan["blind"],
            "quality_deferred": plan["quality_deferred"],
            "deferred_in_flight": plan["skipped_in_flight"],
        }, indent=2, default=str))
        return

    pause = PROJECT_ROOT / "data" / "runtime" / "WATCH_SCHEDULER_PAUSED"
    if pause.exists():
        print(json.dumps({"paused": True, "reason": pause.read_text()[:200] or "operator pause"}))
        return

    swept = wdr.sweep_stale()
    plan = build_plan(conn)
    out = {"swept": len(swept.get("swept", [])), **plan["estimates"], "runs": []}
    blind_symbols = {item["symbol"] for item in plan["blind"]}
    local_symbols = [item["symbol"] for item in plan["local"] if item["symbol"] not in blind_symbols]
    if local_symbols:
        result = wdr.enqueue_run(
            local_symbols,
            scope="AFFECTED_DIMENSIONS",
            analysis_tier="LOCAL_QUANT",
            requested_by="scheduler",
            reason="quality_aware_policy_cadence",
        )
        out["runs"].append({
            "tier": "LOCAL_QUANT", "run_id": result.get("run_id"),
            "queued": result.get("queued"),
        })
    if blind_symbols:
        result = wdr.enqueue_run(
            sorted(blind_symbols),
            scope="AFFECTED_DIMENSIONS",
            analysis_tier="STANDARD_BLIND",
            requested_by="scheduler",
            reason="admitted_quality_blind_cadence",
        )
        out["runs"].append({
            "tier": "STANDARD_BLIND", "run_id": result.get("run_id"),
            "queued": result.get("queued"),
        })
    print(json.dumps(out, indent=2, default=str))


def _force_exit(rc: int) -> None:
    """Exit now, but never before the run's own report has reached the pipe.

    os._exit() skips interpreter shutdown -- which is the point, since systemd
    Type=oneshot otherwise waits on leftover non-daemon threads from the DB
    adapters. It ALSO skips flushing stdio. Under systemd stdout is a pipe, so it
    is block-buffered, and the batch summary this script prints as its only
    record of what it did was discarded on every single scheduled run.

    Measured 2026-09-13 on the live release: with the force-exit active the run
    exits 0 and produces ZERO lines; with WATCH_SCHEDULER_NO_FORCE_EXIT=1 the
    same run prints 27 lines of real JSON (population 1496, in_flight 160,
    quality_deferred 929). The work was always fine. The evidence of it was
    being thrown away.

    Flush failures are swallowed deliberately: a broken pipe on the way out must
    not turn a completed batch into a non-zero exit.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001 - see docstring
            pass
    _reap_own_children()
    os._exit(rc)


def _own_children() -> list[int]:
    """PIDs this process has forked, from /proc/self/task/*/children."""
    pids: set[int] = set()
    for path in glob.glob("/proc/self/task/*/children"):
        try:
            with open(path, encoding="ascii") as fh:
                pids.update(int(tok) for tok in fh.read().split())
        except (OSError, ValueError):
            continue
    return sorted(pids)


def _reap_own_children(grace_seconds: float = 2.0) -> None:
    """Kill and reap our own children before exiting.

    os._exit() ends THIS process and nothing else, so anything forked underneath
    is inherited by systemd. Measured 2026-09-13: this script reaches its exit
    with exactly two children, both forked copies of itself.

    That is what produced the unit's standing lie. main() exits 0, systemd tears
    down the cgroup, and those two block in uninterruptible I/O long enough to
    outlast TimeoutStopSec -- so a batch that SUCCEEDED is reported
    Result=timeout. Over 30 days: 72 successes against 33 such failures.

    Two alternatives were tried at the unit level first and both measured worse.
    KillMode=process stops the cgroup kill and the children then never exit at
    all -- still alive and sleeping at 195 seconds, ~357M each, on a timer-driven
    unit, which is a process leak rather than a fix. Raising TimeoutStopSec to
    45s was simply unreliable: one clean run, then two failures at exactly 45s.

    Doing it here is the honest place. The batch is already complete and printed
    by the time this runs, systemd would kill these same processes moments later
    anyway, and reaping them ourselves means the cgroup is empty when systemd
    looks -- so the unit's verdict finally matches its exit status.

    Everything is best-effort: a failure to reap must never turn a completed
    batch into a non-zero exit.
    """
    try:
        children = _own_children()
    except Exception:  # noqa: BLE001
        return
    for pid in children:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    deadline = time.monotonic() + grace_seconds
    for pid in children:
        while time.monotonic() < deadline:
            try:
                if os.waitpid(pid, os.WNOHANG) != (0, 0):
                    break
            except ChildProcessError:
                break
            except OSError:
                break
            time.sleep(0.02)


if __name__ == "__main__":
    try:
        main()
        rc = 0
    except Exception:
        rc = 1
        raise
    if os.environ.get("WATCH_SCHEDULER_NO_FORCE_EXIT") != "1":
        _force_exit(rc)
