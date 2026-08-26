"""Librarian orchestrator — scope selection, per-scope caps, dry-run default, audit.

Runs the full librarian suite:
  - taxonomy: classify untagged research rows
  - graph: refresh co-occurrence edges, prune stale
  - freshness: flag stale content, detect stale embeddings
  - retention: apply retention policies
  - rag_health: embedding coverage, orphans, retrieval QA
  - backlog: legacy backlog-finding logic (from autonomous_librarian_backlog_loop)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import taxonomy, graph, freshness, retention, rag_health

ROOT = Path(__file__).resolve().parents[3]
KILL_HERMES = ROOT / "data" / "runtime" / "HERMES_DISABLED"
KILL_LIBRARIAN = ROOT / "data" / "runtime" / "LIBRARIAN_DISABLED"


SCOPE_CAPS = {
    "taxonomy": 200,
    "graph": 500,
    "freshness": 50,
    "retention": 100,
    "rag_health": 10,
    "backlog": 10,
    "epistemic": 50,
}

SCOPE_LIGHT = {"freshness", "retention"}  # every 15-min tick
SCOPE_DEEP = {"taxonomy", "graph", "rag_health", "epistemic"}  # nightly deep pass
SCOPE_ALL = set(SCOPE_CAPS.keys())


def run_librarian(*, apply: bool = False, scope: str = "all",
                  max_rows: int = 20) -> dict:
    """Run librarian scopes.

    Args:
        apply: if False, dry-run only
        scope: comma-separated scope names or 'all'
        max_rows: per-scope cap

    Returns:
        dict with per-scope results and overall summary
    """
    if KILL_HERMES.exists():
        return {"status": "kill_switch", "reason": "HERMES_DISABLED"}
    if KILL_LIBRARIAN.exists():
        return {"status": "kill_switch", "reason": "LIBRARIAN_DISABLED"}

    scopes = sorted(SCOPE_ALL) if scope == "all" else [s.strip() for s in scope.split(",")]
    scopes = [s for s in scopes if s in SCOPE_ALL]
    if not scopes:
        return {"status": "error", "reason": f"invalid scope: {scope}"}

    from psycopg2 import connect
    env_path = ROOT / ".env"
    db_pass = None
    for line in env_path.read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            db_pass = line.split("=", 1)[1]
    if not db_pass:
        return {"status": "error", "reason": "DB_PASSWORD not found"}
    conn = connect(host="localhost", dbname="trade_ai", user="trade_ai",
                   password=db_pass)
    cur = conn.cursor()

    results = {}
    start = time.time()

    # Autocommit: each statement is its own transaction.
    # One scope's error can't abort subsequent scopes.
    conn.autocommit = True

    for s in scopes:
        cap = min(SCOPE_CAPS.get(s, 50), max_rows)
        dry_run = not apply

        try:

            if s == "taxonomy":
                r = taxonomy.backfill_content_tags(conn, batch=cap, dry_run=dry_run)
            elif s == "graph":
                r = graph.refresh_cooccurrence(conn, dry_run=dry_run)
                # Also prune stale edges
                pruned = graph.prune_stale_edges(conn, dry_run=dry_run)
                r["pruned_stale"] = pruned
            elif s == "freshness":
                report = freshness.freshness_report(conn)
                flagged = freshness.flag_stale(conn, dry_run=dry_run)
                reembedded = freshness.reembed_stale(conn, dry_run=dry_run)
                r = {"report": report, "flagged": flagged, "reembedded": reembedded}
            elif s == "retention":
                r = retention.apply_retention(conn, dry_run=dry_run)
            elif s == "rag_health":
                health = rag_health.embedding_health(conn)
                qa = rag_health.retrieval_qa_sample(conn, n=min(cap, 10))
                r = {"health": health, "retrieval_qa": qa,
                     "qa_pass_rate": sum(1 for q in qa if q["passed"]) / max(len(qa), 1)}
            elif s == "backlog":
                # Run legacy backlog loop logic (inline here or call the existing script)
                r = _run_backlog_scope(conn, cur, apply=apply, max_rows=cap)
            elif s == "epistemic":
                from scripts.lib.librarian_assessment import assess_artifact
                r = {"status": "ok", "note": "LibrarianAssessment@v1 available; batch artifact critique is dry by default", "assess_fn": assess_artifact.__name__, "dry_run": dry_run}
            else:
                r = {"error": f"unknown scope: {s}"}

            # Audit
            if apply:
                cur.execute("""
                    INSERT INTO hermes_librarian_audit
                        (scope, action, detail, rows_affected, rollback_sql)
                    VALUES (%s, %s, %s::jsonb, %s, %s)
                """, (s, "librarian_tick",
                      json.dumps({"result": r, "scope": s, "dry_run": False}, default=str),
                      r.get("tagged", r.get("edge_count", r.get("total_affected",
                           r.get("enqueued", 0)))),
                      ""))

            results[s] = r

        except Exception as e:
            results[s] = {"error": str(e)[:200]}

    conn.commit()
    cur.close()
    conn.close()

    elapsed = time.time() - start
    error_scopes = [s for s, r in results.items() if "error" in r]

    return {
        "status": "ok",
        "mode": "apply" if apply else "dry-run",
        "scopes_run": scopes,
        "elapsed_s": round(elapsed, 1),
        "errors": len(error_scopes),
        "error_scopes": error_scopes,
        "results": results,
    }


def _run_backlog_scope(conn, cur, *, apply: bool, max_rows: int = 10) -> dict:
    """Legacy backlog-finding logic moved from autonomous_librarian_backlog_loop."""
    findings = []

    # 1. Weak backtest strategies
    try:
        cur.execute("""
            SELECT strategy_id, win_rate, profit_factor, sample_size
            FROM hermes_v_backtest_results_context
            WHERE win_rate < 40 AND sample_size >= 5
            ORDER BY win_rate ASC LIMIT 5
        """)
        for sid, wr, pf, ss in cur.fetchall():
            wr_f = float(wr) if wr is not None else 0.0
            findings.append({"type": "backtest_weak_strategy",
                           "detail": f"WR={wr_f*100 if wr_f<=1 else wr_f:.1f}% PF={pf} n={ss}",
                           "priority": "high" if (wr_f or 0) < 0.3 else "medium"})
    except Exception:
        pass

    # 2. Generic catalysts
    try:
        cur.execute("""
            SELECT COUNT(*) FROM hermes_v_catalyst_quality_context
            WHERE catalyst_type='other' AND confidence < 0.4
        """)
        generic = cur.fetchone()[0]
        if generic > 10:
            findings.append({"type": "catalyst_quality_gap",
                           "detail": f"{generic} generic low-conf catalysts",
                           "priority": "medium"})
    except Exception:
        pass

    # 3. Underfilled screeners
    try:
        cur.execute("""
            SELECT COUNT(*) FROM hermes_v_screener_context
            WHERE status='RUN_UNDERFILLED' AND run_date > CURRENT_DATE - INTERVAL '7 days'
        """)
        under = cur.fetchone()[0]
        if under > 2:
            findings.append({"type": "screener_underfilled",
                           "detail": f"{under} underfilled runs in 7d",
                           "priority": "low"})
    except Exception:
        pass

    if apply and findings:
        for f in findings[:max_rows]:
            cur.execute("""
                INSERT INTO hermes_research_intelligence (
                    source, hermes_agent_name, research_type, symbol, topic, summary, thesis, thesis_type,
                    evidence_json, confidence_score, freshness_date, source_urls_json, model_used,
                    context_type_used, status, quality_score, tags
                ) VALUES (
                    'hermes', 'librarian_v2', 'research_backlog', NULL,
                    %s, %s, 'Librarian v2 finding — operator review required.', 'neutral',
                    %s::jsonb, 0.30, %s, '[]'::jsonb, 'librarian_v2',
                    'librarian_v2', 'staged', 0.30,
                    ARRAY['research_backlog','librarian_v2']
                )
            """, (
                f"{f['type']}: {f['detail']}"[:200],
                f"Librarian v2 detected: {f['detail']}",
                json.dumps([{"type": "librarian_v2_finding", "finding_type": f["type"],
                            "priority": f["priority"], "detail": f["detail"]}]),
                datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            ))

    return {"findings": len(findings), "written": len(findings) if apply else 0,
            "types": [f["type"] for f in findings]}
