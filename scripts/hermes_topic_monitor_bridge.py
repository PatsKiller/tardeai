#!/usr/bin/env python3
"""Hermes topic bridge (2026-06-04) — the reverse of hermes_news_bridge.

Wires the Research Topic Registry's owner mapping to Hermes: topics in topic_monitor with
owner IN ('hermes','shared') are enqueued as staged rows in hermes_research_intelligence
(research_type='topic_research'), which Hermes's existing pipeline (hermes_coordinator
auto-promote + embedding) then researches — the same enqueue mechanism the autonomous
librarian uses.

Symmetry: TradeAI's topic_ingestion.py researches owner IN ('tradeai','shared'); this bridge
feeds owner IN ('hermes','shared') to Hermes. A 'shared' topic is therefore researched by BOTH
engines (co-owned). 'hermes' = Hermes only; 'tradeai' = TradeAI only.

Two steps per run:
  1. RECONCILE COMPLETIONS — when Hermes has promoted/reviewed a topic_research row (its
     completion), stamp topic_monitor.last_searched with the row's ACTUAL completion time. So
     last_searched reflects "Hermes finished researching it", not merely "enqueued".
  2. ENQUEUE — feed new stale hermes/shared topics as staged rows (no last_searched stamp here;
     completion drives it via step 1).
Dedup: skip topics already enqueued (recent topic_research row for that topic_monitor_id).

Usage:
  python3 scripts/hermes_topic_monitor_bridge.py [--apply] [--max-rows 5] [--lookback-days 7] [--json]
  (default is dry-run; --apply writes; --dry-run wins over --apply.)

A dry run opens a READ ONLY session and counts the completions it would reconcile with a SELECT (the
UPDATE is not reachable from it). An --apply run writes the lane receipt
<state_root>/data/runtime/hermes-topic-monitor-bridge_last.json; it exits 1 (ok_at not advanced) when any
enqueue insert failed.
"""
import os, sys, json
from datetime import datetime, timezone, date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


LANE_ID = "hermes-topic-monitor-bridge"


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.hermes_topic_monitor_bridge
        from scripts.lib import lane_last_receipt as lr
    return lr


def _dry_report(lane_id, summary, *, would_write, json_stdout=False):
    """lane_last_receipt.dry_run_report, sent to stderr when stdout carries the script's JSON report."""
    import contextlib
    with contextlib.redirect_stdout(sys.stderr) if json_stdout else contextlib.nullcontext():
        return _receipt_lib().dry_run_report(lane_id, summary, would_write=would_write)


_RECONCILE_FROM = """
            FROM (
                SELECT (evidence_json->>'topic_monitor_id') AS tid, max(updated_at) AS completed_at
                FROM hermes_research_intelligence
                WHERE research_type = 'topic_research'
                  AND status IN ('promoted','reviewed')
                  AND evidence_json->>'topic_monitor_id' IS NOT NULL
                GROUP BY 1
            ) sub"""


def run(apply=False, max_rows=5, lookback_days=7, as_json=False):
    load_env()
    conn = db()
    if not apply:
        _receipt_lib().enforce_readonly(conn)
    cur = conn.cursor()

    # STEP 1 — RECONCILE COMPLETIONS: Hermes promotes/reviews a topic_research row when it has
    # researched it; stamp topic_monitor.last_searched with that actual completion time (only if
    # newer). This is how "Hermes stamps topic_monitor on completion" — read-side reconciliation,
    # no surgery on the live hermes_coordinator.
    reconciled = 0
    insert_errors = 0
    if not apply:
        # read-only twin of the UPDATE below: how many topics it WOULD stamp
        cur.execute("SELECT count(*) FROM topic_monitor tm JOIN (SELECT * " + _RECONCILE_FROM
                    + ") s2 ON tm.topic_id = s2.tid WHERE tm.last_searched IS NULL OR s2.completed_at > tm.last_searched")
        reconciled = int(cur.fetchone()[0] or 0)
    if apply:
        cur.execute("""
            UPDATE topic_monitor tm
            SET last_searched = sub.completed_at, updated_at = now()
            FROM (
                SELECT (evidence_json->>'topic_monitor_id') AS tid, max(updated_at) AS completed_at
                FROM hermes_research_intelligence
                WHERE research_type = 'topic_research'
                  AND status IN ('promoted','reviewed')
                  AND evidence_json->>'topic_monitor_id' IS NOT NULL
                GROUP BY 1
            ) sub
            WHERE tm.topic_id = sub.tid
              AND (tm.last_searched IS NULL OR sub.completed_at > tm.last_searched)
        """)
        reconciled = cur.rowcount
        conn.commit()

    # STEP 2 — ENQUEUE new stale hermes/shared topics
    cur.execute("""
        SELECT topic_id, display_name, owner, search_queries, video_queries, priority, max_age_days
        FROM topic_monitor t
        WHERE enabled = true
          AND owner IN ('hermes','shared')
          AND (last_searched IS NULL OR last_searched < now() - interval '%s days')
          AND NOT EXISTS (
              SELECT 1 FROM hermes_research_intelligence h
              WHERE h.research_type = 'topic_research'
                AND (h.evidence_json->>'topic_monitor_id') = t.topic_id
                AND h.created_at > now() - interval '%s days'
          )
        ORDER BY last_searched ASC NULLS FIRST, priority, topic_id
        LIMIT %s
    """, (lookback_days, lookback_days, max_rows))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    enqueued = []
    for t in rows:
        sq = t.get("search_queries") or []
        vq = t.get("video_queries") or []
        if isinstance(sq, str):
            try: sq = json.loads(sq)
            except Exception: sq = [sq]
        evidence = {"topic_monitor_id": t["topic_id"], "owner": t["owner"],
                    "search_queries": sq, "video_queries": vq, "priority": t.get("priority"),
                    "bridged_by": "hermes_topic_monitor_bridge.py"}
        summary = (f"Research topic '{t['display_name']}' from the Research Topic Registry "
                   f"(owner={t['owner']}). {len(sq)} search queries. Hermes to research and stage findings.")
        if not apply:
            enqueued.append({"topic_id": t["topic_id"], "owner": t["owner"], "dry_run": True})
            continue
        try:
            # One write module per store (SoT Phase 9): SQL lives in lib.writers.hermes_research_writer.
            from lib.writers.hermes_research_writer import write_research_rows
            rc = write_research_rows(cur, [{
                "source": "hermes", "hermes_agent_name": "topic_monitor_bridge", "research_type": "topic_research",
                "symbol": None, "topic": t["display_name"], "summary": summary,
                "thesis": f"Investigate '{t['display_name']}' for trading-relevant developments.",
                "thesis_type": "neutral", "evidence_json": evidence, "confidence_score": 0.5,
                "freshness_date": date.today().isoformat(), "model_used": "topic_monitor_bridge", "status": "staged",
            }], producer="topic_monitor_bridge")
            if not rc.ids:
                raise RuntimeError(f"rejected: {rc.rows_rejected}")
            hid = rc.ids[0]
            # No last_searched stamp here — completion (step 1 reconcile) drives last_searched.
            enqueued.append({"topic_id": t["topic_id"], "owner": t["owner"], "hermes_id": hid})
        except Exception as e:
            conn.rollback()
            insert_errors += 1
            print(f"  [bridge] {t['topic_id']}: insert error — {str(e)[:90]}")
            continue
    if apply:
        conn.commit()
    report = {"run_at": datetime.now(timezone.utc).isoformat(), "reconciled": reconciled,
              "candidates": len(rows), "enqueued": len([e for e in enqueued if not e.get("dry_run")]),
              "applied": apply, "insert_errors": insert_errors, "rows": enqueued[:20]}
    conn.close()
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"[hermes-topic-bridge] {'reconciled' if apply else 'would reconcile'} {reconciled} completion(s); "
              f"{report['enqueued'] if apply else len(rows)} "
              f"{'enqueued' if apply else 'candidates (dry-run)'} of {len(rows)} eligible")
        for e in enqueued[:15]:
            tag = f"hermes#{e['hermes_id']}" if e.get("hermes_id") else "(dry-run)"
            print(f"  {e['topic_id']:<24} owner={e['owner']:<7} -> {tag}")
    return report


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in a and "--dry-run" not in a
    kwargs = dict(max_rows=int(a[a.index("--max-rows") + 1]) if "--max-rows" in a else 5,
                  lookback_days=int(a[a.index("--lookback-days") + 1]) if "--lookback-days" in a else 7,
                  as_json="--json" in a)
    if not apply:
        report = run(apply=False, **kwargs)
        _dry_report(LANE_ID, {k: report[k] for k in ("reconciled", "candidates")},
                                      would_write=["topic_monitor.last_searched (reconcile)",
                                                   "hermes_research_intelligence (topic_research, staged)"],
            json_stdout=kwargs["as_json"])
        return 0
    started = datetime.now(timezone.utc).isoformat()
    try:
        report = run(apply=True, **kwargs)
    except Exception as exc:
        _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                          script="hermes_topic_monitor_bridge.py",
                                          error=f"{type(exc).__name__}: {exc}")
        raise
    rc = 1 if report["insert_errors"] else 0
    _receipt_lib().write_lane_receipt(LANE_ID, ok=(rc == 0), exit_code=rc, started_at=started,
                                      script="hermes_topic_monitor_bridge.py",
                                      summary={k: report[k] for k in ("reconciled", "candidates", "enqueued",
                                                                      "insert_errors")})
    return rc


if __name__ == "__main__":
    sys.exit(main())
