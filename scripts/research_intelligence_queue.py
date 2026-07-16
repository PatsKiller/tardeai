#!/usr/bin/env python3
"""Research Intelligence run-research queue (RI v3, Workstream D).

Thin operator-triggered queue in front of topic_ingestion.py — the desk's
"Run research" / "Queue refresh" buttons enqueue here during the day, and the
after-close cron drains the queue (content production stays post-close per the
RI desk rule). Never refactors or bypasses topic_ingestion internals.

Usage:
  python scripts/research_intelligence_queue.py --enqueue roth_conversion
  python scripts/research_intelligence_queue.py --enqueue-category macro_geo
  python scripts/research_intelligence_queue.py --list
  python scripts/research_intelligence_queue.py --drain           # cron entry
  python scripts/research_intelligence_queue.py --drain --cap 10
"""
from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LOCK_PATH = "/tmp/ri_research_queue.lock"
DRAIN_CAP_DEFAULT = 10
PER_TOPIC_TIMEOUT_S = 900

DDL = """
CREATE TABLE IF NOT EXISTS ri_research_queue (
    id            BIGSERIAL PRIMARY KEY,
    topic_id      TEXT NOT NULL,
    source        TEXT DEFAULT 'ri_desk',
    requested_by  TEXT DEFAULT 'operator',
    status        TEXT NOT NULL DEFAULT 'queued',
    requested_at  TIMESTAMPTZ DEFAULT NOW(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    result_note   TEXT
);
CREATE INDEX IF NOT EXISTS idx_ri_research_queue_status ON ri_research_queue (status);
"""


def _db():
    from db_adapter import _execute, USE_DB
    if not USE_DB:
        raise RuntimeError("DB unavailable")
    return _execute


def ensure_table() -> None:
    ex = _db()
    for stmt in DDL.strip().split(";"):
        if stmt.strip():
            ex(stmt, fetch="none")


def enqueue(topic_id: str, *, requested_by: str = "operator", source: str = "ri_desk") -> dict:
    """Queue one topic_monitor topic for the after-close drain. Dedupe on
    already queued/running rows so button mashing never stacks work."""
    ex = _db()
    ensure_table()
    topic_id = str(topic_id or "").strip()
    if not topic_id:
        return {"ok": False, "error": "topic_id required"}
    known = ex("SELECT 1 FROM topic_monitor WHERE topic_id = %s", (topic_id,), fetch="one")
    if not known:
        return {"ok": False, "error": f"unknown topic_id: {topic_id}"}
    dup = ex(
        "SELECT id, status FROM ri_research_queue WHERE topic_id = %s AND status IN ('queued','running') LIMIT 1",
        (topic_id,), fetch="one",
    )
    if dup:
        return {"ok": True, "queued": False, "already": dup["status"], "queue_id": dup["id"],
                "note": "already queued for the after-close drain"}
    row = ex(
        "INSERT INTO ri_research_queue (topic_id, source, requested_by) VALUES (%s,%s,%s) RETURNING id",
        (topic_id, source, requested_by), fetch="one",
    )
    return {"ok": True, "queued": True, "queue_id": row["id"] if row else None,
            "note": "queued for after close"}


def enqueue_category(category: str, *, cap: int = 3, requested_by: str = "operator") -> dict:
    """Coverage-gap action: queue the stalest enabled monitors whose classified
    primary category matches. Uses the same classifier as the feed."""
    from lib.research_intelligence import classify_primary_secondary
    ex = _db()
    ensure_table()
    rows = ex(
        """SELECT topic_id, display_name, strategy_tags, personal_context, last_searched
           FROM topic_monitor WHERE enabled IS TRUE OR enabled IS NULL
           ORDER BY last_searched ASC NULLS FIRST LIMIT 200""",
        fetch="all",
    ) or []
    queued = []
    for r in rows:
        cats = classify_primary_secondary(
            f"{r.get('display_name') or ''} {r.get('topic_id') or ''}",
            " ".join(r.get("strategy_tags") or []),
            r.get("personal_context"),
        )
        if (cats[0] if cats else "") != category:
            continue
        res = enqueue(r["topic_id"], requested_by=requested_by, source="coverage_gap")
        if res.get("queued"):
            queued.append(r["topic_id"])
        if len(queued) >= cap:
            break
    return {"ok": True, "category": category, "queued": queued,
            "note": "queued for after close" if queued else "no un-queued monitors matched"}


def list_queue(limit: int = 50) -> list[dict]:
    ex = _db()
    ensure_table()
    return ex(
        """SELECT id, topic_id, source, requested_by, status, requested_at, started_at,
                  finished_at, result_note
           FROM ri_research_queue
           ORDER BY (status = 'queued') DESC, requested_at DESC LIMIT %s""",
        (int(limit),), fetch="all",
    ) or []


def drain(cap: int = DRAIN_CAP_DEFAULT) -> dict:
    """Run queued topics through topic_ingestion --topic, one at a time,
    lockfile-guarded, capped per run. Telegram digest on completion."""
    ex = _db()
    ensure_table()
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return {"ok": False, "error": "drain already running (lock held)"}

    rows = ex(
        "SELECT id, topic_id FROM ri_research_queue WHERE status = 'queued' ORDER BY requested_at ASC LIMIT %s",
        (int(cap),), fetch="all",
    ) or []
    done, failed = [], []
    for r in rows:
        qid, tid = r["id"], r["topic_id"]
        ex("UPDATE ri_research_queue SET status='running', started_at=NOW() WHERE id=%s", (qid,), fetch="none")
        try:
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "topic_ingestion.py"), "--topic", tid, "--limit", "10"],
                cwd=str(ROOT), capture_output=True, text=True, timeout=PER_TOPIC_TIMEOUT_S,
            )
            ok = proc.returncode == 0
            note = (proc.stdout or proc.stderr or "")[-400:]
        except subprocess.TimeoutExpired:
            ok, note = False, f"timeout after {PER_TOPIC_TIMEOUT_S}s"
        except Exception as e:  # noqa: BLE001 — queue must record, not crash
            ok, note = False, str(e)[:400]
        ex(
            "UPDATE ri_research_queue SET status=%s, finished_at=NOW(), result_note=%s WHERE id=%s",
            ("done" if ok else "failed", note, qid), fetch="none",
        )
        (done if ok else failed).append(tid)

    remaining = ex(
        "SELECT count(*) AS n FROM ri_research_queue WHERE status='queued'", fetch="one",
    ) or {"n": 0}

    if done or failed:
        try:
            from telegram_alert import send_telegram
            msg = (
                f"🔬 RI research queue drained: {len(done)} ok"
                + (f", {len(failed)} failed" if failed else "")
                + (f", {remaining['n']} still queued" if remaining.get("n") else "")
                + "\n" + "\n".join(f"  ✓ {t}" for t in done[:8])
                + ("\n" + "\n".join(f"  ✗ {t}" for t in failed[:4]) if failed else "")
            )
            send_telegram(msg)
        except Exception:
            pass

    return {"ok": True, "processed": len(done) + len(failed), "done": done,
            "failed": failed, "still_queued": remaining.get("n")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enqueue", metavar="TOPIC_ID")
    ap.add_argument("--enqueue-category", metavar="CATEGORY")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--drain", action="store_true")
    ap.add_argument("--cap", type=int, default=DRAIN_CAP_DEFAULT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.enqueue:
        out = enqueue(args.enqueue)
    elif args.enqueue_category:
        out = enqueue_category(args.enqueue_category)
    elif args.drain:
        out = drain(cap=args.cap)
    elif args.list:
        out = {"ok": True, "queue": list_queue()}
    else:
        out = {"ok": False, "error": "one of --enqueue/--enqueue-category/--list/--drain required"}

    print(json.dumps({"as_of": datetime.now(timezone.utc).isoformat(), **out},
                     indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
