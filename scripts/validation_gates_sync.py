#!/usr/bin/env python3
"""validation-gates-sync — the writer for validation_gates / validation_events (LQ-20261107-2141 / 2143).

n8n dispatcher lane, every 5 minutes, all days (gates have due times at night). Each run, in ONE transaction:
  1. ingest ``ValidationGateDecl@v1`` files from ``<state>/data/coordination/validation_gates/inbox`` (upsert keyed
     on gate_id + decl_sha256; a vetted close request closes a gate; a refused one is counted, never applied);
  2. evaluate every OPEN/OVERDUE/FAILED gate's check (named read-only queries, 2 s statement_timeout);
  3. apply transitions (PASSED / FAILED / OVERDUE) and write a validation_events row for each.
Only after the commit are ingested files moved to ``.../ingested/``.

* No ``--apply``: a dry run. It reads and evaluates, rolls back, moves nothing, writes no receipt.
* ``LANE_OUTPUT`` (stderr) carries {ingested, evaluated, transitions, errors}. ``produced_count == 0`` with no
  ``empty_reason`` exits non-zero: "no open gates" is only proven by ``evaluated`` plus the receipt ``ok_at``.

AUTHORITY: writes validation_gates / validation_events only. No broker, order, stop or credential access.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from lib import lane_output  # noqa: E402
from lib import validation_gates as VG  # noqa: E402
from lib.lane_receipt_main import run_main  # noqa: E402

LANE = "validation-gates-sync"
QUERIES_REL = "config/validation_gate_queries.json"
STATEMENT_TIMEOUT_MS = 2000


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def load_queries(path: Path | None = None) -> dict:
    p = path or (HERE.parent / QUERIES_REL)
    return json.loads(p.read_text(encoding="utf-8")).get("queries", {})


def lane_ok_at_reader(root: Path):
    def _read(lane_id: str):
        try:
            doc = json.loads((root / "data" / "runtime" / f"{lane_id}_last.json").read_text(encoding="utf-8"))
            return VG.parse_ts(doc.get("ok_at"))
        except (OSError, ValueError, TypeError, AttributeError):
            return None
    return _read


def run(conn, *, root: Path, queries: dict, now: datetime, apply: bool, run_id: str, postgres: bool = True) -> dict:
    """One lane run against an open connection. Commits only when ``apply``; never moves files itself on a dry run."""
    cur = conn.cursor()
    if postgres:
        cur.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
    inbox = root / "data" / "coordination" / "validation_gates" / "inbox"
    ingested_dir = root / "data" / "coordination" / "validation_gates" / "ingested"
    out = {"ingested": 0, "refused": 0, "unchanged": 0, "errors": 0, "files": []}
    done_files = []
    refused_files = []  # (path, reason): moved aside on apply so one bad file is not re-counted every 5 minutes
    for f in sorted(inbox.glob("*.json")) if inbox.is_dir() else []:
        try:
            decl = VG.parse_decl(json.loads(f.read_text(encoding="utf-8")), queries=queries)
        except (VG.DeclError, ValueError, OSError) as exc:
            out["refused"] += 1
            out["files"].append({"file": f.name, "refused": str(exc)[:200]})
            refused_files.append((f, str(exc)[:200]))
            continue
        cur.execute("SAVEPOINT decl")
        try:
            res = VG.apply_decl(cur, decl, now=now, decl_path=str(f))
            cur.execute("RELEASE SAVEPOINT decl")
        except Exception as exc:  # noqa: BLE001 -- DeclError or a DB CHECK: this file is refused, the rest go on
            cur.execute("ROLLBACK TO SAVEPOINT decl")
            out["refused"] += 1
            out["files"].append({"file": f.name, "refused": f"{type(exc).__name__}: {str(exc)[:160]}"})
            refused_files.append((f, f"{type(exc).__name__}: {str(exc)[:160]}"))
            continue
        if res["action"] == "noop":
            out["unchanged"] += 1
        else:
            out["ingested"] += 1
            if res["action"] == "inserted":
                VG.record_event(cur, {"gate_id": decl["gate_id"], "category": decl["category"],
                                      "owner": decl["owner"], "check_spec": {}}, "opened", occurred_at=now,
                                run_id=run_id, summary=f"{decl['title']}: opened")
            ev_gate = {"gate_id": decl["gate_id"], "category": decl["category"], "owner": decl["owner"],
                       "check_spec": decl["check_spec"]}  # check_spec is frozen: it equals the stored one
            if res.get("monitoring"):
                VG.record_event(cur, ev_gate, "monitoring", occurred_at=now, run_id=run_id,
                                summary=f"{decl['title']}: monitoring fix {decl.get('fix_ref')}")
            if res["action"] == "closed":  # a vetted manual close is a transition too (LQ-2692)
                VG.record_event(cur, ev_gate, "passed" if res["status"] == "PASSED" else "waived", occurred_at=now,
                                run_id=run_id, summary=f"{decl['title']}: {res['status'].lower()} by {res['by']}")
        done_files.append(f)

    def run_query(qid: str):
        q = queries.get(qid)
        if not q:
            raise KeyError(qid)
        cur.execute("SAVEPOINT q")
        try:
            cur.execute(q["sql"])
            row = cur.fetchone()
            cur.execute("RELEASE SAVEPOINT q")
            return row[0] if row else None
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT q")
            raise

    ev = VG.evaluate_open(cur, now=now, run_id=run_id, lane_ok_at=lane_ok_at_reader(root), run_query=run_query)
    out.update(ev)
    if apply:
        conn.commit()
        if done_files:
            ingested_dir.mkdir(parents=True, exist_ok=True)
            for f in done_files:
                shutil.move(str(f), str(ingested_dir / f.name))
        if refused_files:
            refused_dir = ingested_dir.parent / "refused"
            refused_dir.mkdir(parents=True, exist_ok=True)
            for f, reason in refused_files:
                (refused_dir / (f.name + ".reason.txt")).write_text(reason + "\n", encoding="utf-8")
                shutil.move(str(f), str(refused_dir / f.name))
    else:
        conn.rollback()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="commit and move ingested files (default: dry run)")
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    mode = "apply" if args.apply else "dry_run"
    from db_adapter import _get_conn

    conn = _get_conn()
    if conn is None:
        print(json.dumps({"lane": LANE, "ok": False, "error": "db unavailable"}))
        return 1
    try:
        out = run(conn, root=state_root(), queries=load_queries(), now=now, apply=args.apply,
                  run_id=f"d:{LANE}:{mode}:{now.strftime('%Y%m%dT%H%M')}")
    except Exception as exc:  # noqa: BLE001 -- roll back, name the type only; the table stays as it was
        conn.rollback()
        print(json.dumps({"lane": LANE, "ok": False, "error": type(exc).__name__}))
        return 1
    produced = out["ingested"] + out["transitions"]
    block = lane_output.output_block(
        produced=produced, attempted=out["evaluated"] + out["ingested"] + out["refused"] + out["unchanged"],
        skipped={"declaration_refused": out["refused"], "declaration_unchanged": out["unchanged"],
                 "check_error": out["errors"]},
        empty_reason="no declarations and no transitions", unit="gate_actions")
    lane_output.emit(LANE, mode, block)
    print(json.dumps({"lane": LANE, "mode": mode, "ok": True, "wrote": args.apply,
                      **{k: v for k, v in out.items() if k != "files"}, "refused_files": out["files"]}))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(LANE, main, script="scripts/validation_gates_sync.py"))
