#!/usr/bin/env python3
"""Hermes Autonomous Librarian/Backlog Loop — capped daily research management.

Usage:
    python scripts/hermes_autonomous_librarian_backlog_loop.py [--apply] [--max-rows N]

Default: dry-run (file output only). --apply writes to hermes_research_intelligence.

Safety:
    - Max 5 rows/day
    - Max runtime 600s
    - Kill switch: data/runtime/HERMES_DISABLED or data/runtime/LIBRARIAN_DISABLED
    - No broker/proposal/trade/journal/holdings
    - No embeddings, no promotions
"""
import argparse, json, os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

PR = Path(__file__).resolve().parent.parent
OUT_DR = PR / "docs" / "hermes" / "librarian_loop_dryruns"
OUT_DR.mkdir(parents=True, exist_ok=True)

MAX_ROWS = 5
MAX_RUNTIME = 600

# Engine Room v1 (WS-4): every backlog row carries the surface that produced it,
# so the health check can attribute intake instead of reporting "unknown".
SURFACE_BY_FINDING = {
    "backtest_weak_strategy": "backtest_results",
    "catalyst_quality_gap": "catalyst_quality",
    "screener_underfilled": "screener_registry",
    "stale_source_discovery": "source_discovery",
}
OWNER_BY_FINDING = {
    "backtest_weak_strategy": "strategy_research_agent",
    "catalyst_quality_gap": "catalyst_research_agent",
    "screener_underfilled": "screener_quality_agent",
    "stale_source_discovery": "source_discovery_agent",
}
BACKLOG_TYPE_BY_FINDING = {
    "backtest_weak_strategy": "strategy_validation",
    "catalyst_quality_gap": "catalyst_quality",
    "screener_underfilled": "screener_coverage",
    "stale_source_discovery": "source_freshness",
}
QUESTION_BY_FINDING = {
    "backtest_weak_strategy": "Does the strategy retain evidence after governed out-of-sample validation?",
    "catalyst_quality_gap": "Which primary source can classify this catalyst without inference?",
    "screener_underfilled": "Which deterministic eligibility or feed constraint caused the underfill?",
    "stale_source_discovery": "Is there a current approved source that resolves this freshness gap?",
}

def get_db():
    """Credentials from the canonical loader, not from a tree-relative path.

    `(PR/".env")` resolves inside whatever tree this runs from, and a RELEASE has
    no .env because secrets are deliberately not deployed — so running this from
    a release raised FileNotFoundError before it reached a query. It survived
    only because the timer happens to set WorkingDirectory to the dev tree; any
    invocation from CURRENT died. Fifth instance of this shape (2026-09-06).
    """
    import psycopg2

    db_pass = os.environ.get("DB_PASSWORD")
    if not db_pass:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
            from env_bootstrap import load_env  # noqa: PLC0415
            load_env()
            db_pass = os.environ.get("DB_PASSWORD")
        except Exception as exc:
            print(f"WARN: env_bootstrap unavailable ({type(exc).__name__})", file=sys.stderr)
    if not db_pass:
        raise RuntimeError("DB_PASSWORD not resolvable (env, tmpfs render, or .env)")
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)

def check_kill_switch():
    for f in ["HERMES_DISABLED", "LIBRARIAN_DISABLED"]:
        if (PR / "data" / "runtime" / f).exists():
            return True
    return False

#: How long a filed backlog item suppresses re-detection of the same class.
#:
#: Measured 2026-09-06: the loop had reported "0 findings" on every run since
#: 2026-07-14 while its own detectors matched 1,673 weak strategies, 108,102
#: generic low-confidence catalysts and 315 underfilled screener runs. The cause
#: was three research_backlog rows filed on 2026-06-02: the catalyst guard fires
#: only when fewer than 2 exist (there were exactly 2) and the screener guard only
#: when none exist (there was 1). Both conditions became permanently false, so two
#: of four detectors were switched off for 96 days by three rows, and
#: hermes_advisory_events — whose only automatic producer is this loop — took its
#: last write on 2026-07-14.
#:
#: A filed backlog item means "this was already raised RECENTLY", which expires.
#: Dedup without a shelf life is not dedup, it is a permanent mute. Same defect as
#: taxonomy_tagger's no_match sentinel; see AGENTS.md.
BACKLOG_DEDUP_TTL_DAYS = int(os.environ.get("LIBRARIAN_BACKLOG_DEDUP_TTL_DAYS", "30"))


def main():
    start = time.time()
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS)
    args = parser.parse_args()
    dry = not args.apply
    now = datetime.now(timezone.utc)
    ds = now.strftime("%Y-%m-%d")

    if check_kill_switch():
        print("Kill switch ACTIVE. Exiting.")
        return

    conn = get_db()
    cur = conn.cursor()

    findings = []

    # 1. Check backtest results for weak strategies
    cur.execute("""
        SELECT strategy_id, win_rate, profit_factor, sample_size
        FROM hermes_v_backtest_results_context
        WHERE win_rate < 40 AND sample_size >= 5
        ORDER BY win_rate ASC LIMIT 5
    """)
    for sid, wr, pf, ss in cur.fetchall():
        key = f"bt_weak_{(sid or 'unknown')[:20]}"
        # Check not already in backlog
        cur.execute(
            "SELECT COUNT(*) FROM hermes_research_intelligence "
            "WHERE research_type='research_backlog' AND topic LIKE %s "
            "AND created_at > now() - make_interval(days => %s)",
            (f"%{(sid or '')[:20]}%", BACKLOG_DEDUP_TTL_DAYS))
        if cur.fetchone()[0] == 0:
            wr_f = float(wr) if wr is not None else 0.0
            wr_pct = wr_f * 100 if wr_f <= 1 else wr_f
            pf_f = float(pf) if pf is not None else 0.0
            strat = (sid[:50] if sid else "unknown")
            findings.append({"type": "backtest_weak_strategy", "strategy": strat,
                "detail": f"WR={wr_pct:.1f}% PF={pf_f:.2f} n={ss}",
                "priority": "high" if wr_pct < 30 else "medium"})

    # 2. Check catalyst quality gaps
    cur.execute("""
        SELECT COUNT(*) FROM hermes_v_catalyst_quality_context WHERE catalyst_type='other' AND confidence < 0.4
    """)
    generic_count = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM hermes_research_intelligence "
        "WHERE research_type='research_backlog' AND topic LIKE '%%catalyst%%' "
        "AND created_at > now() - make_interval(days => %s)",
        (BACKLOG_DEDUP_TTL_DAYS,))
    existing_cat = cur.fetchone()[0]
    if generic_count > 10 and existing_cat < 2:
        findings.append({"type": "catalyst_quality_gap", "detail": f"{generic_count} generic low-conf catalysts", "priority": "medium"})

    # 3. Check screener underfilled runs (last 7 days)
    cur.execute("""
        SELECT COUNT(*) FROM hermes_v_screener_context
        WHERE status='RUN_UNDERFILLED' AND run_date > CURRENT_DATE - INTERVAL '7 days'
    """)
    underfilled = cur.fetchone()[0]
    if underfilled > 2:
        cur.execute(
            "SELECT COUNT(*) FROM hermes_research_intelligence "
            "WHERE research_type='research_backlog' AND topic LIKE '%%screener%%underfill%%' "
            "AND created_at > now() - make_interval(days => %s)",
            (BACKLOG_DEDUP_TTL_DAYS,))
        if cur.fetchone()[0] == 0:
            findings.append({"type": "screener_underfilled", "detail": f"{underfilled} underfilled runs in 7 days", "priority": "low"})

    # 4. Check stale source discovery (>14 days)
    cur.execute("""
        SELECT id, symbol, freshness_date FROM hermes_research_intelligence
        WHERE research_type='source_discovery' AND status='staged'
        AND freshness_date < CURRENT_DATE - INTERVAL '14 days'
    """)
    stale_sources = cur.fetchall()
    for sid, sym, fd in stale_sources[:2]:
        findings.append({"type": "stale_source_discovery", "detail": f"id={sid} {sym} freshness={fd}", "priority": "low"})

    # Dedup (2026-06-11): the loop re-detected the same stale items every invocation and re-filed them
    # forever (2,475 duplicate NULL-symbol rows/30d). Skip findings already filed as backlog rows, and
    # enforce a TRUE daily cap (the old cap was per-invocation; the coordinator invokes this repeatedly).
    try:
        cur.execute("""SELECT COALESCE(topic,'') FROM hermes_research_intelligence
                       WHERE research_type='research_backlog' AND created_at > NOW() - INTERVAL '14 days'""")
        _already = {r[0] for r in cur.fetchall()}
        findings = [f for f in findings
                    if (f"{f.get('type','')}: {f.get('detail','')}"[:200]) not in _already]
        cur.execute("""SELECT count(*) FROM hermes_research_intelligence
                       WHERE research_type='research_backlog' AND created_at::date = CURRENT_DATE""")
        _today = cur.fetchone()[0] or 0
        _room = max(0, args.max_rows - _today)
    except Exception:
        _room = args.max_rows
    findings = findings[:_room]

    # Write dry-run report
    report = {
        "date": ds, "timestamp": now.isoformat(),
        "mode": "dry-run" if dry else "apply",
        "findings": len(findings), "max_rows": args.max_rows,
        "details": findings,
        "db_writes": 0 if dry else len(findings),
        "runtime_sec": round(time.time() - start, 1),
    }

    (OUT_DR / "latest_librarian_loop_dryrun.json").write_text(json.dumps(report, indent=2, default=str))
    (OUT_DR / f"{ds}_librarian_loop_dryrun.md").write_text(
        f"# Librarian Loop {'Dry-Run' if dry else 'Apply'} — {ds}\n\n"
        f"Findings: {len(findings)}\nMode: {'DRY-RUN' if dry else 'APPLY'}\n"
        f"Runtime: {report['runtime_sec']}s\n\n"
        + "\n".join(f"- [{f['priority']}] {f['type']}: {f['detail']}" for f in findings)
        + f"\n\n**DB writes: {report['db_writes']}**\n")

    if dry or not findings:
        print(f"{'DRY-RUN' if dry else 'NO FINDINGS'}: {len(findings)} findings in {report['runtime_sec']}s")
        cur.close(); conn.close()
        return

    # APPLY mode — stage findings as backlog items
    inserted = 0
    for f in findings:
        if time.time() - start > MAX_RUNTIME:
            print(f"Runtime limit {MAX_RUNTIME}s reached. Stopping.")
            break
        cur.execute("""
            INSERT INTO hermes_research_intelligence (
                source, hermes_agent_name, research_type, symbol, topic, summary, thesis, thesis_type,
                evidence_json, confidence_score, freshness_date, source_urls_json, model_used,
                context_type_used, status, quality_score, tags
            ) VALUES (
                'hermes', 'autonomous_librarian_loop', 'research_backlog', NULL,
                %s, %s,
                'Autonomous Librarian finding — operator review required.',
                'neutral',
                %s::jsonb,
                0.30, %s, '[]'::jsonb,
                'librarian_loop', 'autonomous_librarian', 'staged', 0.30,
                ARRAY['research_backlog','autonomous_librarian','phase_49']
            ) RETURNING id
        """, (
            (f"{f['type']}:{f['strategy']}: {f['detail']}" if f.get("strategy") else f"{f['type']}: {f['detail']}")[:200],
            f"Autonomous Librarian detected: {f['detail']}. Requires operator review.",
            json.dumps([{"type":"autonomous_librarian_finding","finding_type":f["type"],"priority":f["priority"],
                        "owner_agent":OWNER_BY_FINDING.get(f["type"], "research_triage_agent"),
                        "backlog_type":BACKLOG_TYPE_BY_FINDING.get(f["type"], "research_triage"),
                        "research_questions":[QUESTION_BY_FINDING.get(
                            f["type"], "What evidence is required to resolve this research backlog item?"
                        )],
                        "source_surface":SURFACE_BY_FINDING.get(f["type"], "librarian_loop"),
                        "advisory_only":True,"not_execution":True,"operator_review_required":True,
                        "source_phase":"49","detail":f["detail"]}]),
            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        ))
        rid = cur.fetchone()[0]
        # Enqueue advisory event
        cur.execute("""
            INSERT INTO hermes_advisory_events (event_type, source_table, source_id, priority, advisory_only, not_execution)
            VALUES ('librarian_backlog_created', 'hermes_research_intelligence', %s, %s, true, true)
        """, (rid, f["priority"]))
        inserted += 1

    conn.commit()
    cur.close(); conn.close()
    print(f"APPLY: {inserted} rows staged, {inserted} events enqueued in {round(time.time()-start,1)}s")

if __name__ == "__main__":
    main()
