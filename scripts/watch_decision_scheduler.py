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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

import watch_decision_refresh as wdr  # noqa: E402
import watch_packet_quality as packet_quality  # noqa: E402

TIER_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
QUALITY_ORDER = {"ADMITTED": 0, "UNASSESSED": 1, "RESEARCH_ONLY": 2, "QUARANTINED": 3}
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,5}$")


def _now():
    return datetime.now(timezone.utc)


def _is_tradeable_ticker(sym: str) -> bool:
    """Drop CUSIPs / junk ids that burn the 40-symbol scheduler cap."""
    s = str(sym or "").upper().strip()
    return bool(s) and bool(_TICKER_RE.match(s)) and not s[0].isdigit()


def _priority_key(item: dict) -> tuple:
    # MAIN desk names first — operator SETUP ADVISORY gaps beat bulk watchlist.
    return (
        0 if item.get("main_lane") else 1,
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
    main_syms: set[str] = set()
    try:
        from lib.watch_lane_admission import main_sql_source_clause, load_policy as _wlp
        main_sql, main_params = main_sql_source_clause(_wlp())
        cur.execute(
            f"""SELECT DISTINCT upper(wi.symbol)
                FROM watchlist_items wi
                WHERE wi.status <> 'removed' AND {main_sql}""",
            main_params,
        )
        main_syms = {row[0] for row in cur.fetchall() if row and row[0]}
    except Exception:
        conn.rollback()
        main_syms = set()
    # MAIN desk + stars + existing packets — weekend operators need ticket rebuilds too
    population = sorted(
        s for s in (set(packets) | starred | main_syms) if _is_tradeable_ticker(s)
    )

    cur.execute("""SELECT DISTINCT symbol FROM watch_decision_refresh_jobs
                   WHERE state IN ('QUEUED','RUNNING')""")
    in_flight = {row[0].upper() for row in cur.fetchall()}

    plan = {
        "local": [],
        "blind": [],
        "skipped_in_flight": [],
        "quality_deferred": [],
        "not_due": [],
        "main_syms": sorted(main_syms),
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
        if quality_state == "QUARANTINED" and not held_or_starred:
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

        det = str(gate.get("deterministic") or "NOT_RUN").upper().replace(" ", "_")
        age_min = None
        if packet:
            age_min = (now - packet["generated_at"]).total_seconds() / 60
        if not packet:
            due_local = True
            due_reason = "PACKET_ABSENT — deterministic quality assessment required"
        elif det in ("NOT_RUN", "NOTRUN", "") or quality_state == "UNASSESSED":
            # Fresh rebuilds with no zone/mechanics stay NOT_RUN by design — that is a
            # plan gap (entry planner), not a missing LOCAL_QUANT pass. Only re-queue
            # when the packet is absent/stale past the tier ceiling.
            stale = bool(local_ceiling and age_min is not None and age_min > float(local_ceiling))
            if stale or age_min is None:
                due_local = True
                due_reason = (
                    "TICKET_NOT_RUN — stale/missing deterministic assessment for MAIN desk"
                    if det in ("NOT_RUN", "NOTRUN", "")
                    else "QUALITY_UNASSESSED — rebuild locally before any model lane"
                )
            else:
                due_local = False
        else:
            due_local = bool(local_ceiling and age_min is not None and age_min > float(local_ceiling))
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
            "main_lane": symbol in main_syms,
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


def auto_run_free_critics(conn, *, cap: int = 12, dry_run: bool = False) -> dict:
    """Run critic lanes for ADMITTED+PASS tickets with missing review verdicts."""
    import watch_packet_quality as packet_quality

    cur = conn.cursor()
    cur.execute("""SELECT symbol, packet FROM decision_packets
                   WHERE superseded_by IS NULL
                   ORDER BY generated_at DESC NULLS LAST
                   LIMIT 200""")
    candidates = []
    for symbol, packet in cur.fetchall():
        sym = str(symbol or "").upper()
        pkt = packet or {}
        selected = packet_quality.select_governing_validation(pkt)
        validation = selected.get("validation") or {}
        deterministic = selected.get("deterministic") or "NOT_RUN"
        quality = validation.get("quality_admission") or {}
        prior = pkt.get("ticket_review") or {}
        reviews = prior.get("reviews") or {}
        missing = [lane for lane in ("local", "deepseek-flash", "grok", "chatgpt")
                   if not (reviews.get(lane) or {}).get("verdict")]
        may_review = (
            deterministic in {"PASS", "REVIEW_REQUIRED"}
            and quality.get("state") == "ADMITTED"
            and quality.get("new_entry_allowed") is not False
            and missing
        )
        if may_review:
            candidates.append(sym)

    ran = []
    for sym in candidates[:cap]:
        if dry_run:
            ran.append(sym)
            continue
        try:
            from run_ticket_review_job import main as review_main
            review_main(sym, "local,grok,chatgpt")
            ran.append(sym)
        except Exception as exc:
            ran.append(f"{sym}:err:{type(exc).__name__}")
    return {"eligible": len(candidates), "ran": len(ran), "symbols": ran[:cap]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--critics-only", action="store_true")
    args = parser.parse_args()
    conn = wdr._conn()
    if args.critics_only:
        print(json.dumps(auto_run_free_critics(conn, dry_run=not args.run), indent=2, default=str))
        return
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
    out = {
        "swept": len(swept.get("swept", [])),
        "workers_spawned": swept.get("workers_spawned", 0),
        **plan["estimates"],
        "runs": [],
    }
    blind_symbols = {item["symbol"] for item in plan["blind"]}
    local_symbols = [item["symbol"] for item in plan["local"] if item["symbol"] not in blind_symbols]
    main_set = set(plan.get("main_syms") or [])
    main_due = [s for s in local_symbols if s in main_set]
    rest_due = [s for s in local_symbols if s not in main_set]
    # Separate MAIN run at priority 10 so SETUP ADVISORY gaps claim ahead of bulk P2.
    for label, syms, prio, reason in (
        ("LOCAL_QUANT_MAIN", main_due, 10, "main_desk_ticket_not_run"),
        ("LOCAL_QUANT", rest_due, 100, "quality_aware_policy_cadence"),
    ):
        if not syms:
            continue
        result = wdr.enqueue_run(
            syms,
            scope="AFFECTED_DIMENSIONS",
            analysis_tier="LOCAL_QUANT",
            requested_by="scheduler",
            reason=reason,
            priority=prio,
        )
        out["runs"].append({
            "tier": label, "run_id": result.get("run_id"),
            "queued": result.get("queued"),
            "skipped_locked": result.get("skipped_locked"),
            "symbols": result.get("symbols") or syms,
        })
        if not result.get("queued"):
            out["workers_spawned"] = (
                int(out.get("workers_spawned") or 0) + wdr.ensure_refresh_workers()
            )
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
    critics = auto_run_free_critics(conn, cap=12, dry_run=False)
    out["free_critics"] = critics
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
