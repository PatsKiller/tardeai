#!/usr/bin/env python3
"""seed_supervisor_sla.py — one SLA row per lane, derived from config/lane_registry.json (06 §4).

Dry-run by default: prints the rows it WOULD write and writes nothing. ``--json-out PATH`` writes
the seed file (the detector and the conformance report read it until the Postgres table exists).
``--apply`` upserts into ``intelligence.sla`` through db_adapter and needs the migration applied;
it refuses (exit 3) when the table is absent.

Heuristics (explicit so the owner can override in the table later):
  max_silence_s     3 × expected_cadence_hours (min 15 min, max 48 h); resident services 10 min
  max_run_s         15 min (the wake dispatcher's existing timeout) unless cadence < 15 min, then cadence
  max_queue_age_s   2 × cadence
  max_failure_rate  0.10
  memory_context_required  fail-closed for cio-* / options-* / advisory-* / watch-* lanes,
                           degraded for health/watchdog/monitor lanes, none otherwise
  ladder_max        3 for every lane (L4/L5 are Wave 4)

Approval: pkg-20260927-cogx-w1-d9e1 item 7. Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))

FAIL_CLOSED_PREFIXES = ("cio-", "cio_", "options-", "options_", "advisory-", "advisory_", "watch-", "watch_", "hermes-cio", "reentry", "re-entry")
DEGRADED_PREFIXES = ("health", "watchdog", "autonomy-watchdog", "monitor", "freshness", "heartbeat", "supervisor", "platform-conformance", "memory-compliance")


def memory_requirement(lane_id: str) -> str:
    l = lane_id.lower()
    if any(l.startswith(p) for p in DEGRADED_PREFIXES):
        return "degraded"
    if any(l.startswith(p) for p in FAIL_CLOSED_PREFIXES):
        return "fail-closed"
    return "none"


def sla_row(lane: dict) -> dict:
    lane_id = lane.get("lane_id")
    cadence_h = lane.get("expected_cadence_hours")
    sched = (lane.get("scheduler") or {}).get("kind")
    resident = sched == "systemd" and (cadence_h in (None, 0) or float(cadence_h or 0) < 0.1)
    if resident:
        max_silence = 600
    elif cadence_h:
        max_silence = int(min(max(3 * float(cadence_h) * 3600, 900), 48 * 3600))
    else:
        max_silence = None
    cadence_s = int(float(cadence_h) * 3600) if cadence_h else None
    max_run = 900 if not cadence_s or cadence_s >= 900 else cadence_s
    sig = lane.get("output_signal") or {}
    return {
        "lane_id": lane_id,
        "silo_id": None,  # assigned by config/platform_silos.json in report_platform_conformance
        "owner": lane.get("owner"),
        "state": lane.get("state"),
        "max_silence_s": max_silence,
        "max_run_s": max_run,
        "max_queue_age_s": 2 * cadence_s if cadence_s else None,
        "max_failure_rate": 0.10,
        "expected_output_signal": f"{sig.get('kind')}:{sig.get('path') or sig.get('table') or sig.get('key') or ''}" if sig else None,
        "event_to_effect_p95_s": 600 if str(lane_id).startswith("cio-") else None,
        "memory_context_required": memory_requirement(str(lane_id)),
        "ladder_max": 3,
        "alternate": None,
        "seeded_from": "config/lane_registry.json",
    }


def build(registry: dict) -> list[dict]:
    return [sla_row(l) for l in registry.get("lanes", []) if l.get("lane_id")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=str(PROJ / "config" / "lane_registry.json"))
    ap.add_argument("--json-out", help="write the seed file here (no Postgres)")
    ap.add_argument("--apply", action="store_true", help="upsert into intelligence.sla (needs the migration)")
    ap.add_argument("--only-active", action="store_true")
    args = ap.parse_args()
    reg = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    rows = build(reg)
    if args.only_active:
        rows = [r for r in rows if r.get("state") == "ACTIVE"]
    summary = {
        "schema": "SupervisorSlaSeed@v1", "as_of": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "lanes": len(rows), "fail_closed": sum(r["memory_context_required"] == "fail-closed" for r in rows),
        "degraded": sum(r["memory_context_required"] == "degraded" for r in rows),
        "no_cadence": sum(r["max_silence_s"] is None for r in rows), "rows": rows,
        "authority": "READ_ONLY_ADVISORY",
    }
    if args.json_out:
        out = Path(args.json_out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=1, sort_keys=False) + "\n", encoding="utf-8")
        print(f"wrote {out} ({len(rows)} lanes)")
    if args.apply:
        try:
            import db_adapter  # type: ignore
            conn = db_adapter._get_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('intelligence.sla')")
                if cur.fetchone()[0] is None:
                    print("intelligence.sla absent — apply migrations/2026_09_27_intelligence_v1.sql first", file=sys.stderr)
                    return 3
                for r in rows:
                    cur.execute(
                        """INSERT INTO intelligence.sla (lane_id, silo_id, owner, max_silence_s, max_run_s, max_queue_age_s,
                           max_failure_rate, expected_output_signal, event_to_effect_p95_s, memory_context_required, ladder_max, alternate, seeded_from, updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                           ON CONFLICT (lane_id) DO UPDATE SET owner=EXCLUDED.owner, max_silence_s=EXCLUDED.max_silence_s,
                           max_run_s=EXCLUDED.max_run_s, max_queue_age_s=EXCLUDED.max_queue_age_s, expected_output_signal=EXCLUDED.expected_output_signal,
                           memory_context_required=EXCLUDED.memory_context_required, seeded_from=EXCLUDED.seeded_from, updated_at=now()""",
                        (r["lane_id"], r["silo_id"], r["owner"], r["max_silence_s"], r["max_run_s"], r["max_queue_age_s"],
                         r["max_failure_rate"], r["expected_output_signal"], r["event_to_effect_p95_s"],
                         r["memory_context_required"], r["ladder_max"], r["alternate"], r["seeded_from"]))
            conn.commit()
            print(f"applied {len(rows)} SLA rows")
        except Exception as exc:  # noqa: BLE001
            print(f"apply failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    if not args.json_out and not args.apply:
        print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1))
        for r in rows[:5]:
            print(json.dumps(r))
        print(f"... dry run: {len(rows)} rows, nothing written (use --json-out or --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
