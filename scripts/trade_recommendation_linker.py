#!/usr/bin/env python3
"""trade_recommendation_linker.py — link each closed Schwab round trip to the recommendation it most plausibly came
from, and attribute its R multiple.

Learning loop PR1 (operator 2026-10-21). Reads schwab_round_trips (the broker-synced round trips the journal builder
already wrote — no broker call here, ever) and recommendation_registry; writes trade_recommendation_links, one row per
round trip keyed by schwab_round_trips.dedupe_key. Matching and R rules: scripts/lib/trade_recommendation_linkage.py.
A trade with no plausible recommendation is written origin='operator_initiated' — explicitly, never null.

DRY RUN BY DEFAULT (a READ ONLY session). ``--from-sources`` builds the recommendations in memory from their sources
(scripts/recommendation_registry_sync.py collectors) instead of reading recommendation_registry, so the linker can be
measured before the migration is applied. ``--apply`` requires the migration and reads the registry; it is idempotent
(a row is rewritten only when its link or attribution changed). Runs after the journal build (see the PR body for the
proposed cron line).

  python3 scripts/trade_recommendation_linker.py [--days 90] [--from-sources] [--apply] [--sample 5]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import trade_recommendation_linkage as lk  # noqa: E402

RECEIPT_NAME = "trade_recommendation_linker_latest.json"

TRADES_SQL = """
SELECT s.id AS round_trip_id, s.dedupe_key AS round_trip_key, s.account, UPPER(s.symbol) AS symbol,
       s.entry_time, s.exit_time, s.entry_price, s.exit_price, s.qty, s.net_pnl, s.classification,
       tc.stop_used AS journal_stop
FROM schwab_round_trips s
LEFT JOIN trade_closed tc ON tc.dedupe_key = 'srt:' || s.id
WHERE s.entry_time IS NOT NULL AND s.exit_time >= %s
  AND s.basis_status IS NULL AND s.canary IS NOT TRUE
ORDER BY s.exit_time"""

REGISTRY_SQL = """
SELECT rec_id, source, symbol, direction, entry_low, entry_high, plan_stop, plan_target, created_at, expires_at
FROM recommendation_registry WHERE expires_at >= %s AND created_at <= %s"""

LINK_COLS = ("round_trip_key", "round_trip_id", "trade_source", "symbol", "account", "direction", "entry_time",
             "exit_time", "entry_price", "exit_price", "qty", "origin", "rec_id", "rec_source", "link_confidence",
             "link_method", "link_detail", "plan_entry_low", "plan_entry_high", "plan_stop", "plan_target",
             "stop_source", "r_multiple", "r_null_reason", "planned_rr", "target_hit", "stop_hit", "hit_basis",
             "linker_version", "linked_at")
_CHANGE_COLS = ("rec_id", "link_confidence", "origin", "r_multiple", "r_null_reason", "planned_rr", "plan_stop",
                "plan_target", "target_hit", "stop_hit", "stop_source", "exit_price", "entry_price")
UPSERT_SQL = (
    "INSERT INTO trade_recommendation_links (" + ", ".join(LINK_COLS) + ") VALUES %s "
    "ON CONFLICT (round_trip_key) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in LINK_COLS if c not in ("round_trip_key", "linked_at"))
    + ", linked_at = CASE WHEN trade_recommendation_links.rec_id IS DISTINCT FROM EXCLUDED.rec_id "
      "THEN EXCLUDED.linked_at ELSE trade_recommendation_links.linked_at END, updated_at = now() WHERE "
    + " OR ".join(f"trade_recommendation_links.{c} IS DISTINCT FROM EXCLUDED.{c}" for c in _CHANGE_COLS)
)


def _dict_query(conn):
    import psycopg2.extras

    def q(sql, params=()):
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    return q


def _table_exists(q, name: str) -> bool:
    return bool(q("SELECT to_regclass(%s) IS NOT NULL AS ok", (name,))[0]["ok"])


def summarize(links: list[dict[str, Any]], sample: int) -> dict[str, Any]:
    linked = [x for x in links if x["origin"] == "recommendation"]
    rs = [x["r_multiple"] for x in links if x["r_multiple"] is not None]
    pick = sorted(linked, key=lambda x: (lk.CONFIDENCE_RANK[x["link_confidence"]], str(x["exit_time"])))[:sample]
    if len(pick) < sample:
        pick += [x for x in links if x["origin"] == "operator_initiated"][: sample - len(pick)]
    return {
        "closed_trades": len(links), "linked": len(linked),
        "operator_initiated": sum(1 for x in links if x["origin"] == "operator_initiated"),
        "by_confidence": dict(Counter(x["link_confidence"] for x in links)),
        "by_rec_source": dict(Counter(x["rec_source"] for x in linked)),
        "with_r_multiple": len(rs), "r_null_reasons": dict(Counter(x["r_null_reason"] for x in links
                                                                   if x["r_multiple"] is None)),
        "mean_r": round(sum(rs) / len(rs), 3) if rs else None,
        "sample": [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in x.items()
                    if k in ("symbol", "account", "entry_time", "entry_price", "exit_price", "origin", "rec_id",
                             "rec_source", "link_confidence", "link_detail", "plan_entry_low", "plan_entry_high",
                             "plan_stop", "plan_target", "r_multiple", "r_null_reason", "planned_rr",
                             "target_hit", "stop_hit")} for x in pick],
    }


def run(days: int, apply: bool, from_sources: bool, sample: int = 5, event_path: Optional[Path] = None,
        projection_path: Optional[Path] = None) -> dict[str, Any]:
    from db_adapter import _get_conn

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    conn = _get_conn()
    conn.rollback()
    if not apply:
        conn.set_session(readonly=True)          # a dry run cannot write, by construction
    q = _dict_query(conn)
    report: dict[str, Any] = {"mode": "APPLY" if apply else "DRY-RUN", "days": days, "since": since.isoformat(),
                              "linker_version": lk.LINKER_VERSION, "grace_days": lk.GRACE.days}
    has_registry = _table_exists(q, "recommendation_registry")
    has_links = _table_exists(q, "trade_recommendation_links")
    report["tables"] = {"recommendation_registry": has_registry, "trade_recommendation_links": has_links}
    if apply and (from_sources or not (has_registry and has_links)):
        conn.rollback()
        report["refused"] = ("--apply links against recommendation_registry only: apply "
                             "migrations/2026_10_21_learning_loop_pr1.sql and run recommendation_registry_sync.py "
                             "--apply first; --from-sources is dry-run only")
        return report
    trades = q(TRADES_SQL, (since,))
    rec_since = since - timedelta(days=60)       # a recommendation issued before the window can still be active in it
    if from_sources or not has_registry:
        import recommendation_registry_sync as sync

        ev, pj = sync._default_paths()
        recs = sync.collect_all(q, rec_since, event_path or ev, projection_path or pj)
        report["recs_from"] = "sources (in memory)"
    else:
        recs = q(REGISTRY_SQL, (rec_since, now))
        report["recs_from"] = "recommendation_registry"
    report["recs_considered"] = len(recs)
    report["recs_by_source"] = dict(Counter(r["source"] for r in recs))
    links = lk.link_all(trades, recs, now=now)
    report.update(summarize(links, sample))
    if apply:
        from psycopg2.extras import execute_values

        rows = [tuple(json.dumps(x[c], default=str) if c == "link_detail" else x[c] for c in LINK_COLS)
                for x in links]
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT trade_rec_links")
            try:
                report["written"] = 0
                if rows:
                    execute_values(cur, UPSERT_SQL, rows, page_size=500)
                    report["written"] = max(cur.rowcount, 0)
                cur.execute("RELEASE SAVEPOINT trade_rec_links")
            except Exception as e:  # noqa: BLE001
                cur.execute("ROLLBACK TO SAVEPOINT trade_rec_links")
                report["write_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        conn.commit()
        if "write_error" not in report:
            from scripts.lib.persistent_state_root import resolve_durable_dir

            out = resolve_durable_dir("data/runtime", ROOT) / RECEIPT_NAME
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({**report, "at": now.isoformat()}, indent=1, default=str), encoding="utf-8")
            report["receipt"] = str(out)
    else:
        conn.rollback()
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--apply", action="store_true", help="write trade_recommendation_links (needs the migration)")
    ap.add_argument("--from-sources", action="store_true", help="dry run: build recs in memory from their sources")
    ap.add_argument("--sample", type=int, default=5)
    ap.add_argument("--opportunity-file", type=Path, default=None)
    ap.add_argument("--projection-file", type=Path, default=None)
    a = ap.parse_args(argv)
    rep = run(a.days, a.apply, a.from_sources, a.sample, a.opportunity_file, a.projection_file)
    print(json.dumps(rep, indent=1, default=str))
    return 1 if (a.apply and ("refused" in rep or "write_error" in rep)) else 0


if __name__ == "__main__":
    sys.exit(main())
