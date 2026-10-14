#!/usr/bin/env python3
"""n8n fabric Phase 1 — read-only evidence for the proofs (README "DRY-RUN PROOF PLAN").

Opens the coordination ledger with sqlite ``mode=ro`` (never migrates or writes) and tails the relay log. Prints:
the probe's ledger runs row(s) and run_outcomes row(s) (P1), the error probe's comms_intents row(s) (P2), the relay
log lines for op run_outcome / intent / POST /run since --since, and the shadow crontab snapshot mtime.

    python3 03_evidence.py --since 2026-10-15T14:07:00+00:00
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def _rows(conn: sqlite3.Connection, sql: str, args: tuple) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.OperationalError as exc:  # table absent = the release that adds it is not served yet
        return [{"error": str(exc)}]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", required=True, help="ISO-8601 UTC instant the proof started")
    ap.add_argument("--ledger", default=None)
    a = ap.parse_args()
    state = _state_root()
    ledger = Path(a.ledger) if a.ledger else state / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    conn = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    out = {
        "ledger": str(ledger),
        "since": a.since,
        "P1_runs": _rows(
            conn,
            "SELECT run_id, lane_id, mode, state, exit_code, requested_at, finished_at FROM runs"
            " WHERE run_id LIKE 'fabric-probe-%' AND requested_at >= ? ORDER BY requested_at",
            (a.since,),
        ),
        "P1_run_outcomes": _rows(
            conn,
            "SELECT run_id, status, run_state, exit_code, receipt_path, duration_s, effect_key, recorded_at"
            " FROM run_outcomes WHERE run_id LIKE 'fabric-probe-%' AND recorded_at >= ? ORDER BY recorded_at",
            (a.since,),
        ),
        "P2_comms_intents": _rows(
            conn,
            "SELECT intent_id, domain, kind, tier, state, count, workflow_id, execution_id, first_at FROM comms_intents"
            " WHERE first_at >= ? ORDER BY first_at",
            (a.since,),
        ),
    }
    conn.close()
    for row in out["P1_run_outcomes"]:
        path = row.get("receipt_path")
        if path:
            row["receipt_exists"] = Path(path).is_file()
    log = state / "data" / "runtime" / "n8n_relay" / "relay_log.jsonl"
    lines = []
    try:
        for raw in log.read_text(encoding="utf-8").splitlines()[-2000:]:
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if str(rec.get("at", "")) >= a.since and (
                rec.get("op") in ("run_outcome", "intent") or str(rec.get("run_id", "")).startswith("fabric-probe-")
            ):
                lines.append(rec)
    except OSError as exc:
        lines.append({"error": f"relay log: {type(exc).__name__}"})
    out["relay_log"] = lines
    shadow = state / "data" / "runtime" / "n8n_runs" / "shadow" / "crontab_snapshot.txt"
    out["shadow_snapshot_mtime"] = (
        datetime.fromtimestamp(shadow.stat().st_mtime, timezone.utc).isoformat() if shadow.exists() else None
    )
    print(json.dumps(out, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
