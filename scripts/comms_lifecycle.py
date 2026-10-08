#!/usr/bin/env python3
"""comms_lifecycle.py — classify, expire and archive-then-remove Communications messages by TTL.

Operator 2026-10-07: every Command Center message has an enforceable TTL by category (operational 72 h,
security/market/securities 96 h, intelligence 1 week — config/comms_categories.yaml). Expired messages leave
every active view without manual work, then are archived and removed. Decisions: approvals, protection incidents
and broker facts follow the same TTLs; removal is ARCHIVE-THEN-DELETE (AGENTS.md §0 rule 6) — every row and its
delivery/outbox/link/thread rows are written to
<state root>/archive/comms_lifecycle/<table>/<UTC stamp>.jsonl.gz and the delete runs only when the archived
counts equal the rows selected. Admin override: legal_hold (keep indefinitely) or retain_until (keep until).

Steps (each idempotent; dry run unless --apply):
  1. classify — rows written before 2026-10-07 (category IS NULL) get category/priority/scores and their TTL
                counted from created_at.
  2. expire   — status -> 'expired' where the effective expiry (greater of expires_at and retain_until) passed
                and no legal hold. The portal hides expired rows by default, so this is only the record.
  3. purge    — archive then delete expired rows (children first), in batches, one transaction per batch.

  comms_lifecycle.py                 # dry run: counts per step
  comms_lifecycle.py --apply         # do it
  comms_lifecycle.py --apply --steps classify,expire
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

RECEIPT_REL = Path("data") / "runtime" / "comms_lifecycle_latest.json"
EXPIRED_WHERE = ("NOT legal_hold AND expires_at IS NOT NULL "
                 "AND GREATEST(expires_at, COALESCE(retain_until, expires_at)) < now()")


def purge_where(grace_hours: float) -> str:
    """Expired AND past the grace window (expired items stay viewable under the "expired" filters until then)."""
    g = float(grace_hours)
    return ("NOT legal_hold AND expires_at IS NOT NULL AND "
            f"GREATEST(expires_at, COALESCE(retain_until, expires_at)) < now() - interval '{g:g} hours'")


def grace_hours() -> float:
    try:
        from scripts.lib.comms import classify as cl
        return float(((cl.load_config().get("lifecycle") or {}).get("purge_grace_hours")) or 24)
    except Exception:
        return 24.0
# (table, key column) — children first; communication_entity_links would cascade, archived anyway for the record.
CHILDREN = (("communication_deliveries", "event_id"), ("communication_outbox", "event_id"),
            ("communication_entity_links", "event_id"), ("communication_thread_membership", "event_id"))


def _conn():
    from db_adapter import _get_conn  # type: ignore
    return _get_conn()


def archive_root() -> Path:
    base = os.getenv("TRADEAI_STATE_ROOT")
    root = Path(base) if base else Path.home() / "trade-ai-releases" / "persistent-state"
    return root / "archive" / "comms_lifecycle"


# ── 1. classify ─────────────────────────────────────────────────────────────

def step_classify(cur, *, apply: bool, batch: int = 2000, max_rows: int = 200000) -> dict:
    from scripts.lib.comms import classify as cl
    cur.execute("SELECT count(*) FROM communication_events WHERE category IS NULL")
    pending = cur.fetchone()[0]
    if not apply or not pending:
        return {"unclassified": pending, "classified": 0}
    done = 0
    while done < max_rows:
        cur.execute("""SELECT event_id, direction, severity, message_class,
                              COALESCE(sanitized_body, short_summary, ''), created_at
                         FROM communication_events WHERE category IS NULL ORDER BY created_at LIMIT %s""", (batch,))
        rows = cur.fetchall()
        if not rows:
            break
        for eid, direction, sev, mclass, body, created in rows:   # oldest first: newer rows supersede older
            c = cl.classify(body=body, direction=direction, severity=sev, message_class=mclass)
            params = cl.update_params(eid, c, created)
            cur.execute(cl.UPDATE_SQL, params)
            cur.execute(cl.SUPERSEDE_SQL, params)
        cur.connection.commit()
        done += len(rows)
    return {"unclassified": pending, "classified": done}


# ── 2. expire ───────────────────────────────────────────────────────────────

def step_expire(cur, *, apply: bool) -> dict:
    cur.execute(f"SELECT count(*) FROM communication_events WHERE status <> 'expired' AND {EXPIRED_WHERE}")
    n = cur.fetchone()[0]
    if apply and n:
        # A re-entry item that runs out of time is an EXPIRED re-entry (unless it was already invalidated).
        cur.execute(f"""UPDATE communication_events
                           SET status = 'expired', actionable = FALSE,
                               reentry_status = CASE WHEN category = 're_entry' AND reentry_status <> 'invalidated'
                                                     THEN 'expired' ELSE reentry_status END
                         WHERE status <> 'expired' AND {EXPIRED_WHERE}""")
        cur.connection.commit()
    return {"to_expire": n, "expired": n if apply else 0}


# ── 3. purge (archive then delete) ──────────────────────────────────────────

def _archive(cur, table: str, col: str, ids: list[str], stamp: str) -> tuple[int, str]:
    d = archive_root() / table
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{stamp}.jsonl.gz"
    cur.execute(f"SELECT row_to_json(t) FROM {table} t WHERE t.{col} = ANY(%s)", (ids,))
    n = 0
    with gzip.open(path, "at", encoding="utf-8") as fh:        # append: one file per run, many batches
        for (row,) in cur:
            fh.write(json.dumps(row, default=str) + "\n")
            n += 1
    return n, str(path)


def step_purge(cur, *, apply: bool, batch: int = 2000, max_rows: int = 200000) -> dict:
    where = purge_where(grace_hours())
    cur.execute(f"SELECT count(*) FROM communication_events WHERE status IN ('expired', 'superseded') AND {where}")
    eligible = cur.fetchone()[0]
    out: dict[str, Any] = {"eligible": eligible, "archived": {}, "deleted": {}, "archive_files": []}
    if not apply or not eligible:
        return out
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    total = 0
    while total < max_rows:
        cur.execute(f"""SELECT event_id FROM communication_events
                         WHERE status IN ('expired', 'superseded') AND {where} ORDER BY expires_at LIMIT %s""", (batch,))
        ids = [r[0] for r in cur.fetchall()]
        if not ids:
            break
        try:
            for table, col in CHILDREN + (("communication_events", "event_id"),):
                cur.execute(f"SELECT count(*) FROM {table} WHERE {col} = ANY(%s)", (ids,))
                expect = cur.fetchone()[0]
                n, path = _archive(cur, table, col, ids, stamp)
                if n != expect:
                    raise RuntimeError(f"{table}: archived {n} != selected {expect}; delete refused ({path})")
                if path not in out["archive_files"] and n:
                    out["archive_files"].append(path)
                out["archived"][table] = out["archived"].get(table, 0) + n
            for table, col in CHILDREN + (("communication_events", "event_id"),):
                cur.execute(f"DELETE FROM {table} WHERE {col} = ANY(%s)", (ids,))
                out["deleted"][table] = out["deleted"].get(table, 0) + cur.rowcount
            cur.connection.commit()
        except Exception:
            cur.connection.rollback()
            raise
        total += len(ids)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--steps", default="classify,expire,purge")
    ap.add_argument("--batch", type=int, default=2000)
    a = ap.parse_args(argv)
    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    conn = _conn()
    report: dict[str, Any] = {"mode": "APPLY" if a.apply else "DRY-RUN", "at": datetime.now(timezone.utc).isoformat()}
    with conn.cursor() as cur:
        if "classify" in steps:
            report["classify"] = step_classify(cur, apply=a.apply, batch=a.batch)
        if "expire" in steps:
            report["expire"] = step_expire(cur, apply=a.apply)
        if "purge" in steps:
            report["purge"] = step_purge(cur, apply=a.apply, batch=a.batch)
    conn.rollback()
    if a.apply:
        p = ROOT / RECEIPT_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
