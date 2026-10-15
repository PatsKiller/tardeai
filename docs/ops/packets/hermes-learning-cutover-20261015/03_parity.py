#!/usr/bin/env python3
"""hermes-learning cutover — read-only parity check for one learn slot, or N consecutive days.

Reads (sqlite ``mode=ro``; never migrates or writes): the coordination ledger's ``runs``, ``run_outcomes``,
``effect_claims`` and ``comms_intents`` (+ ``comms_intent_consumption``) tables, each RunReceipt@v1 the outcome points
to, and the cron stage runner's step receipts ($PROJ/logs/pipelines/hermes_learning/learn_steps.jsonl).

    python3 03_parity.py --date 20261020 --mode live                 # one live slot (after C3)
    python3 03_parity.py --date 20261024 --mode live --days 5        # the 5-day live parity gate (README)
    python3 03_parity.py --date 20261016 --mode dry_run --days 5     # the 5-day shadow gate, with the new checks

Per runnable LEARN step (outcome_grader, tag_engine, outcome_feedback_agent, outcome_learning, config_governor):

  dry_run  PASS = the n8n dry run RUN_DONE iff the cron step ended ok (the flow packet's 04_evidence.py rule), AND the
           run row carries the gateway's validated slot_key (p: key checked server-side), AND the receipt's
           offpeak verdict was in_window (a live run at that minute would not have been PEAK_SKIPped).
  live     PASS = the n8n live run RUN_DONE (not reason offpeak_skip), its receipt's effect block claimed=true and
           final_state DONE, the ledger's effect_claims row for fx:<lane>:<slot>:v1 is DONE with scheduler n8n, AND
           the cron step for the same day is skipped_effect (cron still present, fenced) or absent (line retired).
  score_history_retention (EXCLUDED, cron retention): the cron step ended ok that day (it still runs on cron).
  live day extras: no RUN_REFUSED / RUN_FAILED / RUN_TIMEOUT row for a learn lane that day; every comms intent the
           feedback agent queued that day (workflow_id host.hermes_outcome_feedback_agent) is consumed DONE (none
           FAILED / dead-lettered).

Exit 0 when every requested day is PARITY, 1 otherwise. Prints a JSON report on stdout and a summary on stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROCESS = "hermes-learning"
LEARN_STEPS = ("outcome_grader", "tag_engine", "outcome_feedback_agent", "outcome_learning", "config_governor")
EXCLUDED = "score_history_retention"
HOST_WF = "host.hermes_outcome_feedback_agent"


def _repo() -> Path:
    return Path(os.environ.get("REPO") or Path.home() / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild")


def _state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def _proj() -> Path:
    return Path(os.environ.get("PROJ") or Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT")


def _rows(conn: sqlite3.Connection, sql: str, args: tuple) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.OperationalError as exc:
        return [{"error": str(exc)}]


def _receipt(path: str | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _cron_steps(date: str) -> dict[str, dict]:
    jl = _proj() / "logs" / "pipelines" / "hermes_learning" / "learn_steps.jsonl"
    out: dict[str, dict] = {}
    try:
        lines = jl.read_text(encoding="utf-8").splitlines()[-2000:]
    except OSError:
        return {"_error": {"error": f"{jl} unreadable"}}
    for raw in lines:
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if str(rec.get("ts", ""))[:10].replace("-", "") == date and rec.get("dry_run") is False and "id" in rec:
            out[rec["id"]] = rec  # last line of the day per step wins
    return out


def check_day(conn: sqlite3.Connection, spec: dict, slot_hhmm: str, date: str, mode: str) -> dict:
    slot = f"{date}T{slot_hhmm}"
    cron = _cron_steps(date)
    steps = []
    for sid in LEARN_STEPS:
        lane = spec["steps"][sid]["lane_id"]
        keys = tuple(f"p:{lane}:{mode}:{slot}{sfx}" for sfx in ("", ":a2", ":a3"))
        runs = _rows(
            conn,
            "SELECT r.run_id, r.state, r.mode, r.slot_key, r.duration_s, o.status, o.receipt_path FROM runs r"
            " LEFT JOIN run_outcomes o ON o.run_id = r.run_id WHERE r.run_id IN (?, ?, ?) ORDER BY r.requested_at",
            keys,
        )
        n8n = runs[-1] if runs else None
        rec = _receipt((n8n or {}).get("receipt_path"))
        c = cron.get(sid)
        row: dict = {
            "step_id": sid,
            "lane_id": lane,
            "n8n_state": (n8n or {}).get("state"),
            "n8n_reason": rec.get("reason"),
            "cron_status": (c or {}).get("status"),
            "problems": [],
        }
        p = row["problems"]
        if n8n is None or "error" in n8n:
            p.append("n8n_run_missing")
        elif mode == "dry_run":
            if (n8n.get("state") == "RUN_DONE") != ((c or {}).get("status") == "ok"):
                p.append("n8n_vs_cron_health_mismatch")
            if n8n.get("slot_key") != keys[0]:
                p.append("slot_key_not_gateway_validated")
            if (rec.get("offpeak") or {}).get("in_window") is not True:
                p.append("offpeak_out_of_window")
        else:
            fx_key = f"fx:{lane}:{slot}:v1"
            fx = _rows(conn, "SELECT state, scheduler, run_id FROM effect_claims WHERE effect_key = ?", (fx_key,))
            eff = rec.get("effect") or {}
            row["effect"] = {"key": fx_key, "ledger": fx[0] if fx else None, "receipt": eff}
            if n8n.get("state") != "RUN_DONE":
                p.append(f"n8n_{n8n.get('state')}")
            if rec.get("reason") == "offpeak_skip":
                p.append("n8n_offpeak_skip")
            if not (eff.get("claimed") is True and eff.get("final_state") == "DONE"):
                p.append("effect_not_done_on_receipt")
            if not fx or fx[0].get("state") != "DONE" or fx[0].get("scheduler") != "n8n":
                p.append("effect_claims_row_not_done_by_n8n")
            if c is not None and c.get("status") != "skipped_effect":
                p.append(f"cron_step_{c.get('status')}_not_fenced")  # cron ran the effect too: DOUBLE EFFECT
        row["verdict"] = "PASS" if not p else "FAIL"
        steps.append(row)
    ret = cron.get(EXCLUDED)
    extras: list[str] = []
    if (ret or {}).get("status") != "ok":
        extras.append(f"retention_cron_{(ret or {}).get('status')}")
    if mode == "live":
        day_iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        lanes = [spec["steps"][s]["lane_id"] for s in LEARN_STEPS]
        bad = _rows(
            conn,
            "SELECT run_id, state FROM runs WHERE lane_id IN (%s) AND requested_at LIKE ? AND state IN"
            " ('RUN_REFUSED', 'RUN_FAILED', 'RUN_TIMEOUT')" % ",".join("?" * len(lanes)),
            (*lanes, f"{day_iso}%"),
        )
        if bad:
            extras.append(f"bad_runs:{[b.get('run_id') or b.get('error') for b in bad]}")
        intents = _rows(
            conn,
            "SELECT i.intent_id, i.state, c.state AS consumed FROM comms_intents i LEFT JOIN comms_intent_consumption c"
            " ON c.intent_id = i.intent_id WHERE i.workflow_id = ? AND i.first_at LIKE ?",
            (HOST_WF, f"{day_iso}%"),
        )
        if any("error" in i for i in intents):
            extras.append("intents_unreadable")
        not_done = [i["intent_id"] for i in intents if "error" not in i and i.get("state") != "DONE"]
        if not_done:
            extras.append(f"intents_not_consumed:{not_done}")
    verdict = "PARITY" if all(s["verdict"] == "PASS" for s in steps) and not extras else "NO_PARITY"
    return {"date": date, "slot": slot, "mode": mode, "verdict": verdict, "steps": steps, "day_problems": extras}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="03_parity.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--date", required=True, metavar="YYYYMMDD", help="the LAST slot date (America/New_York)")
    ap.add_argument("--mode", required=True, choices=("dry_run", "live"))
    ap.add_argument("--days", type=int, default=1, help="consecutive days ending at --date (5 = the gate)")
    ap.add_argument("--ledger", default=None, metavar="PATH")
    a = ap.parse_args(argv)
    if not (len(a.date) == 8 and a.date.isdigit()) or not 1 <= a.days <= 30:
        ap.error("--date YYYYMMDD and 1 <= --days <= 30")
    spec = json.loads((_repo() / "config" / "n8n_fabric_processes.json").read_text(encoding="utf-8"))["processes"][
        PROCESS
    ]
    manifest = json.loads((_repo() / spec["manifest"]).read_text(encoding="utf-8"))
    m, h = manifest["stages"]["learn"]["proposed_schedule"].split()[:2]
    hhmm = f"{int(h):02d}{int(m):02d}"
    ledger = Path(a.ledger) if a.ledger else _state_root() / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    conn = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    last = datetime.strptime(a.date, "%Y%m%d")
    days = [(last - timedelta(days=i)).strftime("%Y%m%d") for i in reversed(range(a.days))]
    report = [check_day(conn, spec, hhmm, d, a.mode) for d in days]
    conn.close()
    for d in report:
        print(f"[{d['date']} {d['mode']}] {d['verdict']} {d['day_problems'] or ''}", file=sys.stderr)
        for s in d["steps"]:
            print(
                f"  {s['step_id']:<24} {s['verdict']:<5} n8n={s['n8n_state']} cron={s['cron_status']} {s['problems'] or ''}",
                file=sys.stderr,
            )
    ok = all(d["verdict"] == "PARITY" for d in report)
    print(
        json.dumps({"process": PROCESS, "ledger": str(ledger), "all_parity": ok, "days": report}, indent=1, default=str)
    )
    print(f"GATE ({a.days} day(s), {a.mode}): {'PASS' if ok else 'FAIL'}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
