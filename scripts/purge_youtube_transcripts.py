#!/usr/bin/env python3
"""purge_youtube_transcripts.py — the monthly YouTube transcript purge as a step script (cron rank 4).

Replaces crontab line 163 (2026-10-07), which ran two inline `python -c` programs on the 1st at 03:00:
  1. `transcript_processor.set_purge_dates()` — stamps `purge_after` on undated rows by quality tier;
  2. `DELETE FROM youtube_transcripts WHERE purge_after IS NOT NULL AND purge_after < CURRENT_DATE`.

Default is a DRY RUN: it counts the undated rows and the expired rows and writes nothing. `--apply`
is the cron's behaviour (stamp, delete, commit) and writes the durable receipt
`data/runtime/youtube_transcript_purge_last.json` (schema YoutubeTranscriptPurge@v1) — the proof it
ran, which the inline cron never produced. The connection is `transcript_processor._get_conn()`, the
same localhost/trade_ai connection the inline program built by hand; no second credential path.

Runner: scripts/pipelines/run_platform_maintenance_pipeline.sh --cadence monthly (step youtube_transcript_purge).
AUTHORITY: platform maintenance only. No broker, no LLM, no network beyond the local Postgres.
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "step script of run_platform_maintenance_pipeline.sh --cadence monthly (cron rank 4); "
    "it is a process boundary invoked by bash, not an importable library — the same shape as "
    "siem_retention_purge.py and backup_verify.py in the same runner."
)

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "YoutubeTranscriptPurge@v1"
DEFAULT_RECEIPT = PROJECT_ROOT / "data" / "runtime" / "youtube_transcript_purge_last.json"
SQL_COUNT_UNDATED = "SELECT count(*) FROM youtube_transcripts WHERE purge_after IS NULL"
SQL_COUNT_EXPIRED = (
    "SELECT count(*) FROM youtube_transcripts WHERE purge_after IS NOT NULL AND purge_after < CURRENT_DATE"
)
SQL_DELETE_EXPIRED = (
    "DELETE FROM youtube_transcripts WHERE purge_after IS NOT NULL AND purge_after < CURRENT_DATE"
)


def _connect():
    """The inline cron's connection, taken from the module that owns it (never a second parser of .env)."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import transcript_processor  # noqa: WPS433 — process boundary, same as the cron's sys.path.insert

    return transcript_processor


def _count(cur, sql: str) -> int:
    cur.execute(sql)
    row = cur.fetchone()
    return int(row[0]) if row else 0


def purge(conn, *, apply: bool, set_purge_dates=None) -> dict:
    """One pass. Dry run: counts only. Apply: stamp undated rows, delete expired rows, commit."""
    cur = conn.cursor()
    undated_before = _count(cur, SQL_COUNT_UNDATED)
    expired_before = _count(cur, SQL_COUNT_EXPIRED)
    result = {
        "schema": SCHEMA,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "dry_run": not apply,
        "undated_before": undated_before,
        "expired_before": expired_before,
        "stamped": None,
        "deleted": 0,
    }
    if not apply:
        return result
    if set_purge_dates is not None:
        set_purge_dates()  # the cron's first program; it commits on its own connection
        result["stamped"] = undated_before - _count(cur, SQL_COUNT_UNDATED)
    cur.execute(SQL_DELETE_EXPIRED)
    result["deleted"] = int(cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0)
    conn.commit()
    return result


def write_receipt(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="stamp purge dates and DELETE expired rows (cron behaviour)")
    ap.add_argument("--receipt", default=str(DEFAULT_RECEIPT), help="receipt path written on --apply")
    args = ap.parse_args(argv)

    tp = _connect()
    conn = tp._get_conn()
    try:
        result = purge(conn, apply=args.apply, set_purge_dates=tp.set_purge_dates if args.apply else None)
    finally:
        conn.close()

    if args.apply:
        receipt = Path(args.receipt)
        result["receipt"] = str(receipt)
        write_receipt(result, receipt)
        print(f"Purged {result['deleted']} expired transcripts (stamped {result['stamped']}); receipt {receipt}")
    else:
        print(
            f"[DRY_RUN] would stamp {result['undated_before']} undated rows and delete "
            f"{result['expired_before']} expired transcripts; nothing written"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
