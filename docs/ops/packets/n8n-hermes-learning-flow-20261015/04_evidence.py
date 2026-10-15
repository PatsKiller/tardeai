#!/usr/bin/env python3
"""n8n fabric process hermes-learning — STEP 4: read-only shadow evidence and parity for one slot.

For one stage slot (a scheduled shadow fire) it joins, step by step:
  * the n8n side: coordination ledger ``runs`` + ``run_outcomes`` rows whose run_id is the process key
    ``p:<lane>:dry_run:<YYYYMMDD>T<HHMM>`` (sqlite ``mode=ro``; never migrates or writes), and the tail of each
    RunReceipt@v1's stdout;
  * the cron side: the stage runner's PipelineStepReceipt@v1 lines for the same date
    ($PROJ/logs/pipelines/hermes_learning/<stage>_steps.jsonl) and its last PipelineRun@v1 summary;
and prints a parity verdict: a runnable step MATCHES when the n8n dry run ended RUN_DONE and the cron step ended ok
(both healthy), or both did not; a BLOCKED step is cron-only by design. Timings are printed side by side.

    python3 04_evidence.py --date 20261016 --stage learn           # after a scheduled 10:50 ET shadow fire
    python3 04_evidence.py --since 2026-10-15T14:07:00+00:00 --manual   # after 02_verify.sh (manual slot)

The 5-run shadow passes when five CONSECUTIVE daily learn slots each print "verdict": "PARITY" (tune has no runnable
step while autonomous_self_tune is BLOCKED: it prints "verdict": "NO_RUNNABLE_STEP"). Writes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("REPO") or Path.home() / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild")
PROCESS = "hermes-learning"


def _state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def _proj() -> Path:
    return Path(os.environ.get("PROJ") or Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT")


def _rows(conn: sqlite3.Connection, sql: str, args: tuple) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.OperationalError as exc:
        return [{"error": str(exc)}]


def _spec() -> tuple[dict, dict]:
    spec = json.loads((REPO / "config" / "n8n_fabric_processes.json").read_text(encoding="utf-8"))["processes"][PROCESS]
    manifest = json.loads((REPO / spec["manifest"]).read_text(encoding="utf-8"))
    return spec, manifest


def _hhmm(expr: str) -> str:
    m, h = expr.split()[:2]
    return f"{int(h):02d}{int(m):02d}"


def _tail(path: str | None) -> str | None:
    if not path:
        return None
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return str(doc.get("stdout_tail") or "")[-400:]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(
        prog="04_evidence.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--date", metavar="YYYYMMDD", help="slot date (America/New_York) of a scheduled shadow fire")
    ap.add_argument("--stage", choices=("learn", "tune"), default="learn")
    ap.add_argument("--since", metavar="ISO8601_UTC", help="with --manual: rows requested at or after this instant")
    ap.add_argument("--manual", action="store_true", help="evidence of a manual (02_verify.sh) run: any p: slot")
    ap.add_argument("--ledger", default=None, metavar="PATH")
    if not argv:
        ap.print_help()
        return 2
    a = ap.parse_args(argv)
    if not a.manual and not (a.date and len(a.date) == 8 and a.date.isdigit()):
        ap.error("--date YYYYMMDD is required (or --manual --since ...)")
    if a.manual and not a.since:
        ap.error("--manual needs --since")
    spec, manifest = _spec()
    stages = list(manifest["stages"]) if a.manual else [a.stage]
    ledger = Path(a.ledger) if a.ledger else _state_root() / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    conn = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    out: dict = {"ledger": str(ledger), "process": PROCESS, "stages": {}}
    for stage in stages:
        slot = None if a.manual else f"{a.date}T{_hhmm(manifest['stages'][stage]['proposed_schedule'])}"
        cron_lines: list[dict] = []
        jl = _proj() / "logs" / "pipelines" / "hermes_learning" / f"{stage}_steps.jsonl"
        try:
            for raw in jl.read_text(encoding="utf-8").splitlines()[-500:]:
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                day = str(rec.get("ts", ""))[:10].replace("-", "")
                if rec.get("dry_run") is False and (a.manual or day == a.date):
                    cron_lines.append(rec)
        except OSError as exc:
            cron_lines.append({"error": f"{jl}: {type(exc).__name__}"})
        cron_by_step = {r.get("id"): r for r in cron_lines if "id" in r}  # last line of the day per step wins
        steps = []
        for st in manifest["stages"][stage]["steps"]:
            sid = st["id"]
            ss = spec["steps"][sid]
            lane = ss["lane_id"]
            if a.manual:
                runs = _rows(
                    conn,
                    "SELECT r.run_id, r.state, r.mode, r.exit_code, r.duration_s, r.requested_at, o.status,"
                    " o.receipt_path FROM runs r LEFT JOIN run_outcomes o ON o.run_id = r.run_id"
                    " WHERE r.lane_id = ? AND r.run_id LIKE 'p:%' AND r.requested_at >= ? ORDER BY r.requested_at",
                    (lane, a.since),
                )
            else:
                runs = _rows(
                    conn,
                    "SELECT r.run_id, r.state, r.mode, r.exit_code, r.duration_s, r.requested_at, o.status,"
                    " o.receipt_path FROM runs r LEFT JOIN run_outcomes o ON o.run_id = r.run_id"
                    " WHERE r.run_id IN (?, ?, ?) ORDER BY r.requested_at",
                    tuple(f"p:{lane}:dry_run:{slot}{sfx}" for sfx in ("", ":a2", ":a3")),
                )
            n8n = runs[-1] if runs else None
            cron = cron_by_step.get(sid)
            row = {
                "step_id": sid,
                "lane_id": lane,
                "blocked": bool(ss["blocked"]),
                "n8n": None if n8n is None else {**n8n, "stdout_tail": _tail(n8n.get("receipt_path"))},
                "n8n_attempts": len(runs),
                "cron": cron,
            }
            if ss["blocked"]:
                row["parity"] = "BLOCKED_CRON_ONLY" if n8n is None else "UNEXPECTED_N8N_RUN"
            elif n8n is None or "error" in n8n:
                row["parity"] = "N8N_MISSING"
            elif cron is None:
                row["parity"] = "CRON_MISSING"
            else:
                n_ok, c_ok = n8n.get("state") == "RUN_DONE", cron.get("status") == "ok"
                row["parity"] = "MATCH" if n_ok == c_ok else "MISMATCH"
                row["timing_s"] = {"n8n_dry_run": n8n.get("duration_s"), "cron_live": (cron.get("ms") or 0) / 1000}
            steps.append(row)
        runnable = [s for s in steps if not s["blocked"]]
        if not runnable:
            verdict = "NO_RUNNABLE_STEP"
        elif all(s["parity"] == "MATCH" for s in runnable) and not any(
            s["parity"] == "UNEXPECTED_N8N_RUN" for s in steps
        ):
            verdict = "PARITY"
        else:
            verdict = "NO_PARITY"
        out["stages"][stage] = {"slot": slot or "manual", "verdict": verdict, "steps": steps}
        print(f"[{stage} {slot or 'manual'}] {verdict}", file=sys.stderr)
        for s in steps:
            t = s.get("timing_s") or {}
            print(
                f"  {s['step_id']:<26} {s['parity']:<18} n8n={((s['n8n'] or {}).get('state'))!s:<16}"
                f" cron={((s['cron'] or {}).get('status'))!s:<8} t_n8n={t.get('n8n_dry_run')} t_cron={t.get('cron_live')}",
                file=sys.stderr,
            )
    conn.close()
    print(json.dumps(out, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
