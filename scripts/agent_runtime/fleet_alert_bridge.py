#!/usr/bin/env python3
"""Read-only bridge: HIGH/CRITICAL FLEET artifacts → Telegram via health_agent path.

Run: PYTHONPATH=scripts python3 -m agent_runtime.fleet_alert_bridge [--dry-run]

Does NOT auto-remediate. Reuses telegram_alert.send_telegram only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = ROOT / "scripts"
# Avoid agent_runtime/ shadowing stdlib when executed as a file path.
sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
if str(_SCRIPTS) not in sys.path:
    sys.path.append(str(_SCRIPTS))

STATE_FILE = Path.home() / ".local/state/tradeai/fleet_alert_bridge.json"
SEVERITIES = ("high", "critical")


def _connect():
    import psycopg2

    dsn = os.environ.get("AGENT_RUNTIME_DISPATCH_DSN") or os.environ.get("TRADE_AI_DSN")
    if not dsn:
        pw = os.environ.get("DB_PASSWORD", "")
        dsn = f"host=localhost port=5432 dbname=trade_ai user=trade_ai password={pw}"
    return psycopg2.connect(dsn)


def _load_state() -> dict:
    if not STATE_FILE.is_file():
        return {"seen_artifact_ids": []}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"seen_artifact_ids": []}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    seen = state.get("seen_artifact_ids") or []
    state["seen_artifact_ids"] = seen[-500:]
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def fetch_high_critical(*, limit: int = 20) -> list[dict]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT artifact_id, agent_id, artifact_type, created_at, payload
        FROM agentic_runtime.agent_artifacts
        WHERE lower(coalesce(payload->>'severity', '')) = ANY(%s)
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (list(SEVERITIES), limit),
    )
    cols = [d[0] for d in cur.description or ()]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def format_alert(row: dict) -> str:
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    findings = payload.get("findings") or []
    first = findings[0].get("message") if findings and isinstance(findings[0], dict) else ""
    sev = str(payload.get("severity") or "high").upper()
    return (
        f"🚨 FLEET {sev}: {row.get('agent_id')} · {row.get('artifact_type')}\n"
        f"{first or 'See Command Center agent runtime for details.'}\n"
        f"artifact_id={row.get('artifact_id')}"
    )


def run(*, dry_run: bool = False) -> dict:
    state = _load_state()
    seen = set(state.get("seen_artifact_ids") or [])
    rows = fetch_high_critical()
    new_rows = [r for r in rows if str(r.get("artifact_id")) not in seen]
    sent = 0
    if new_rows and not dry_run:
        from telegram_alert import send_telegram

        for row in new_rows:
            send_telegram(format_alert(row))
            seen.add(str(row.get("artifact_id")))
            sent += 1
        state["seen_artifact_ids"] = list(seen)
        _save_state(state)
    elif new_rows and dry_run:
        sent = len(new_rows)
    return {"candidates": len(rows), "new_alerts": len(new_rows), "sent": sent, "dry_run": dry_run}


def main() -> int:
    ap = argparse.ArgumentParser(description="Bridge HIGH/CRITICAL FLEET artifacts to Telegram")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = run(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
