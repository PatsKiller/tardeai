#!/usr/bin/env python3
"""Daily AlertQuality@v1 from the alert ledgers (operator decision 2026-10-03).

Scores each completed ET day from what was actually recorded:
  * communication_deliveries joined to communication_events (outbound only)
  * data/runtime/comms_editor_receipts.jsonl (live-mode holds)
  * data/cio/outcome_checkpoints.jsonl, for delivered alerts that carry a decision_id

and persists one row per day through the approved operator-artifact store.

    python3 scripts/score_alert_quality.py                 # dry run: yesterday (ET)
    python3 scripts/score_alert_quality.py --days 14       # dry run: last 14 completed days
    python3 scripts/score_alert_quality.py --apply         # persist yesterday

A ledger that cannot be read leaves that day unwritten; it is never scored as zero.
READ_ONLY_ADVISORY: reads ledgers, writes one advisory artifact per day.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib.cio_operator_artifacts import record_alert_quality  # noqa: E402
from scripts.lib.cio_r13_institution import score_alerts  # noqa: E402

ET = ZoneInfo("America/New_York")
PRODUCER = "scripts/score_alert_quality.py"
RECEIPTS = ROOT / "data" / "runtime" / "comms_editor_receipts.jsonl"
CHECKPOINTS = ROOT / "data" / "cio" / "outcome_checkpoints.jsonl"
RECEIPT = ROOT / "data" / "runtime" / "alert_quality_last.json"
_DECISION_RE = re.compile(r'"decision_id"\s*:\s*"([^"]+)"')
_UP = {"BUY", "ADD", "ENTER", "ACCUMULATE"}
_DOWN = {"SELL", "TRIM", "EXIT", "REDUCE"}

DELIVERY_SQL = """
SELECT d.status, d.provider_message_id, e.producer, e.event_type, e.subject_guid,
       e.payload::text AS payload_text
  FROM communication_deliveries d
  JOIN communication_events e ON e.event_id = d.event_id
 WHERE d.created_at >= %s AND d.created_at < %s
"""


def day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=ET)
    return start, start + timedelta(days=1)


def fetch_deliveries(day: date, query=None) -> list[dict[str, Any]] | None:
    """Delivery rows for one ET day, or None when the ledger can't be read."""
    if query is None:
        from db_adapter import _execute as query
    start, end = day_window(day)
    rows = query(DELIVERY_SQL, (start, end), fetch="all")
    if rows is None:
        return None
    out = []
    for row in rows:
        row = dict(row)
        text = row.pop("payload_text", None) or ""
        row["decision_ids"] = sorted(set(_DECISION_RE.findall(text)))
        out.append(row)
    return out


def read_receipts(day: date, path: Path = RECEIPTS) -> list[dict[str, Any]] | None:
    if not path.is_file():
        return None
    start, end = (t.astimezone(ZoneInfo("UTC")).isoformat() for t in day_window(day))
    out = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = str(rec.get("ts") or "")
            if start <= ts < end:
                out.append(rec)
    return out


def decision_outcomes(decision_ids: set[str], path: Path = CHECKPOINTS) -> dict[str, dict[str, Any]]:
    """favourable / unfavourable from the latest resolved checkpoint per decision.

    Only directional recommendations can be judged; others are not_scorable.
    """
    if not decision_ids or not path.is_file():
        return {}
    latest: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"decision_id"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            did = str(row.get("decision_id") or "")
            if did in decision_ids:
                latest[did] = row
    out = {}
    for did, row in latest.items():
        change = row.get("change_pct")
        rec = str(row.get("recommendation") or row.get("action") or "").upper()
        if not row.get("outcome_id") or change is None:
            out[did] = {"verdict": "pending"}
        elif rec in _UP:
            out[did] = {"verdict": "favourable" if float(change) > 0 else "unfavourable"}
        elif rec in _DOWN:
            out[did] = {"verdict": "favourable" if float(change) < 0 else "unfavourable"}
        else:
            out[did] = {"verdict": "not_scorable"}
    return out


def score_day(day: date, query=None, receipts_path: Path = RECEIPTS,
              checkpoints_path: Path = CHECKPOINTS) -> dict[str, Any]:
    deliveries = fetch_deliveries(day, query)
    receipts = read_receipts(day, receipts_path)
    if deliveries is None or receipts is None:
        missing = [n for n, v in (("delivery ledger", deliveries), ("editor receipts", receipts)) if v is None]
        return {"day": day.isoformat(), "status": "UNAVAILABLE", "reason": f"unreadable: {', '.join(missing)}"}
    ids = {d for row in deliveries for d in row.get("decision_ids") or []}
    return score_alerts(deliveries=deliveries, editor_receipts=receipts,
                        decision_outcomes=decision_outcomes(ids, checkpoints_path), day=day.isoformat())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="persist (default: dry run)")
    ap.add_argument("--days", type=int, default=1, help="completed ET days back from yesterday")
    ap.add_argument("--day", help="one specific completed ET day, YYYY-MM-DD")
    args = ap.parse_args(argv)
    today = datetime.now(ET).date()
    days = [date.fromisoformat(args.day)] if args.day else [today - timedelta(days=i) for i in range(args.days, 0, -1)]
    results = []
    for day in days:
        if day >= today:
            results.append({"day": day.isoformat(), "status": "SKIPPED", "reason": "day not complete"})
            continue
        row = score_day(day)
        if args.apply and row.get("schema") == "AlertQuality@v1":
            end = day_window(day)[1].isoformat()
            row["persist"] = record_alert_quality(row, producer=PRODUCER, artifact_id=f"alert_quality:{row['day']}",
                                                  source_as_of=end, evidence_class="LEDGER_DERIVED")
        results.append(row)
    if args.apply:
        # The lane's output signal: proof this run happened, separate from the shared store.
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps({
            "at": datetime.now(ET).isoformat(),
            "days": [{"day": r.get("day"), "status": r.get("status", "SCORED"),
                      "persist": r.get("persist")} for r in results],
        }, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"applied": bool(args.apply), "days": results}, indent=2, default=str))
    return 0 if all(r.get("status") != "UNAVAILABLE" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
