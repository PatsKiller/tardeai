#!/usr/bin/env python3
"""recommendation_registry_sync.py — register recommendations in recommendation_registry (backfill + incremental).

Learning loop PR1 (operator 2026-10-21). Reads each recommendation source of truth and upserts one row per
recommendation with a deterministic rec_id (scripts/lib/recommendation_registry.py):

  cio_opportunity       data/cio/cio_opportunity_assessments.jsonl (+ the projection, to re-confirm current plans)
  paper_trade_proposal  paper_trade_proposals
  scalp_alert           trade_ai_scans (decision GO) and scalp_scan_results (decision GO, alerted)
  entry_alert           alert_events (alert types in ENTRY_ALERT_TYPES)

DRY RUN BY DEFAULT: a READ ONLY session; prints counts per source and a sample. ``--apply`` is operator-run (backfill:
``--days 90 --apply``); it needs migrations/2026_10_21_learning_loop_pr1.sql applied and writes only
recommendation_registry, inside a SAVEPOINT. Idempotent: re-running changes nothing that has not changed.
No broker call, no send, no order (MBI_BEHAVIOR = 0).

  python3 scripts/recommendation_registry_sync.py [--days 90] [--apply] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import recommendation_registry as reg  # noqa: E402

RECEIPT_REL = "data/runtime/recommendation_registry_sync_latest.json"


def collect_db_recs(query: Callable[[str, tuple], list[dict[str, Any]]], since: datetime) -> list[dict[str, Any]]:
    """Recs from the DB-backed sources issued (or still active) since ``since``. ``query(sql, params)`` → dict rows."""
    recs: list[dict[str, Any]] = []
    for row in query(
        """SELECT id, symbol, side, status, origin, proposed_by, strategy_id, cio_view, created_at,
                  recommendation_created_at, expires_at, max_expires_at, proposed_entry, proposed_stop,
                  proposed_target1, final_entry, final_stop, final_target1, confidence_score, signal_score,
                  research_score
           FROM paper_trade_proposals
           WHERE created_at >= %s OR COALESCE(max_expires_at, expires_at) >= %s""", (since, since)):
        r = reg.proposal_rec(row)
        if r:
            recs.append(r)
    for row in query(
        """SELECT id, symbol, scanned_at, price, score, grade, decision, run_id, run_type, source
           FROM trade_ai_scans WHERE decision = 'GO' AND scanned_at >= %s""", (since - reg.TTL["scalp_alert"],)):
        r = reg.scalp_rec(row, "trade_ai_scans")
        if r:
            recs.append(r)
    for row in query(
        """SELECT id, symbol, scanned_at, price, score, grade, decision
           FROM scalp_scan_results WHERE decision = 'GO' AND alerted IS TRUE AND scanned_at >= %s""",
            (since - reg.TTL["scalp_alert"],)):
        r = reg.scalp_rec(row, "scalp_scan_results")
        if r:
            recs.append(r)
    for row in query(
        """SELECT alert_uid, alert_type, symbol, price, stop_price, confidence, decision, lifecycle_state,
                  source_script, parsed_payload, created_at
           FROM alert_events WHERE alert_type = ANY(%s) AND created_at >= %s""",
            (list(reg.ENTRY_ALERT_TYPES), since - reg.TTL["entry_alert"])):
        r = reg.alert_rec(row)
        if r:
            recs.append(r)
    return recs


def collect_opportunity_recs(event_path: Path, projection_path: Optional[Path], since: datetime
                             ) -> list[dict[str, Any]]:
    lin = reg.OpportunityLineage.from_jsonl(event_path)
    if projection_path and projection_path.exists():
        try:
            proj = json.loads(projection_path.read_text(encoding="utf-8"))
            at = reg._ts(proj.get("as_of"))
            if at:
                lin.confirm_current((proj.get("items") or {}).keys(), at)
        except (ValueError, OSError):
            pass
    return lin.rows(since=since)


def collect_all(query, since: datetime, event_path: Path, projection_path: Optional[Path]) -> list[dict[str, Any]]:
    return collect_opportunity_recs(event_path, projection_path, since) + collect_db_recs(query, since)


def _default_paths() -> tuple[Path, Path]:
    from scripts.lib.cio_opportunity_store import EVENT_PATH, PROJECTION_PATH

    return EVENT_PATH, PROJECTION_PATH


def _dict_query(conn):
    import psycopg2.extras

    def q(sql, params=()):
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    return q


def summarize(recs: list[dict[str, Any]], sample: int = 5) -> dict[str, Any]:
    ids = [r["rec_id"] for r in recs]
    return {
        "recs": len(recs), "unique_rec_ids": len(set(ids)),
        "by_source": dict(Counter(r["source"] for r in recs)),
        "with_plan_stop": sum(1 for r in recs if r.get("plan_stop") is not None),
        "with_plan_target": sum(1 for r in recs if r.get("plan_target") is not None),
        "sample": [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()
                    if k in ("rec_id", "source", "source_id", "symbol", "direction", "entry_low", "entry_high",
                             "plan_stop", "plan_target", "created_at", "expires_at", "conviction_at_issue")}
                   for r in sorted(recs, key=lambda r: str(r["created_at"]), reverse=True)[:sample]],
    }


def run(days: int, apply: bool, event_path: Optional[Path] = None, projection_path: Optional[Path] = None
        ) -> dict[str, Any]:
    from db_adapter import _get_conn

    ev, pj = _default_paths()
    event_path, projection_path = event_path or ev, projection_path or pj
    since = datetime.now(timezone.utc) - timedelta(days=days)
    conn = _get_conn()
    conn.rollback()
    if not apply:
        conn.set_session(readonly=True)          # a dry run cannot write, by construction
    recs = collect_all(_dict_query(conn), since, event_path, projection_path)
    report: dict[str, Any] = {"mode": "APPLY" if apply else "DRY-RUN", "days": days, "since": since.isoformat(),
                              "opportunity_history": str(event_path), **summarize(recs)}
    if apply:
        with conn.cursor() as cur:
            report["write"] = reg.upsert_recs(cur, recs)
        conn.commit()
        if report["write"].get("status") == "ok":
            from scripts.lib.persistent_state_root import resolve_durable_dir

            out = resolve_durable_dir("data/runtime", ROOT) / Path(RECEIPT_REL).name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({**report, "at": datetime.now(timezone.utc).isoformat()}, indent=1,
                                      default=str), encoding="utf-8")
            report["receipt"] = str(out)
    else:
        conn.rollback()
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--apply", action="store_true", help="write recommendation_registry (operator-run)")
    ap.add_argument("--opportunity-file", type=Path, default=None)
    ap.add_argument("--projection-file", type=Path, default=None)
    a = ap.parse_args(argv)
    rep = run(a.days, a.apply, a.opportunity_file, a.projection_file)
    print(json.dumps(rep, indent=1, default=str))
    w = rep.get("write") or {}
    return 1 if a.apply and w.get("status") not in ("ok", "disabled") else 0


if __name__ == "__main__":
    sys.exit(main())
