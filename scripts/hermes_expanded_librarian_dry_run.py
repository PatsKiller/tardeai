#!/usr/bin/env python3
"""Hermes Expanded Librarian Dry-Run — read-only analysis of journal/backtest/screener/catalyst.

Safety:
    - Read-only DB queries from safe views only
    - No DB writes, no embeddings, no promotions
    - File output only to docs/hermes/phase30_expanded_librarian_dryrun/
"""

import json, os, psycopg2
from pathlib import Path
from datetime import datetime, timezone

DB = {"host": "localhost", "dbname": "trade_ai", "user": "trade_ai",
      "password": os.environ.get("DB_PASSWORD", "***REMOVED***")}
OUT = Path(__file__).resolve().parent.parent / "docs" / "hermes" / "phase30_expanded_librarian_dryrun"
OUT.mkdir(parents=True, exist_ok=True)

MAX_PER_VIEW = 25
MAX_FINDINGS = 25
MAX_BACKLOG = 10


def query(sql):
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def run():
    journal_findings = []
    backtest_findings = []
    screener_findings = []
    catalyst_findings = []
    backlog = []
    rejected = []

    # === JOURNAL ===
    jrows = query("SELECT * FROM hermes_v_journal_learning_context LIMIT 25")
    if not jrows:
        journal_findings.append({"check": "JRN-ALL", "severity": "info",
            "detail": "Journal learning view is empty (0 rows). No thesis reviews exist yet. Trade journal learning is NOT ACTIVE.",
            "backlog_type": "journal_lesson_missing"})
        backlog.append({"check": "JRN-ALL", "backlog_type": "journal_lesson_missing",
            "title": "Trade journal learning system is empty — no thesis reviews generated",
            "priority": "medium", "owner": "hermes_librarian_agent",
            "detail": "hermes_v_journal_learning_context has 0 rows. The trade_thesis_reviews table is empty, meaning no post-trade learning is being captured."})

    # === BACKTEST ===
    btrows = query("SELECT * FROM hermes_v_backtest_results_context ORDER BY win_rate ASC NULLS LAST LIMIT 25")
    for r in btrows:
        sid = r.get("strategy_id", "?")
        sym = r.get("symbol", "ALL")
        wr = r.get("win_rate") or 0
        pf = r.get("profit_factor") or 0
        ss = r.get("sample_size") or 0
        cl = r.get("confidence_level", "")

        # BT-5: zero win rate
        if wr == 0 and ss >= 1:
            f = {"check": "BT-5", "severity": "high", "strategy": sid, "symbol": sym,
                 "detail": f"Win rate 0% (sample={ss})", "backlog_type": "backtest_contradiction"}
            backtest_findings.append(f)

        # BT-1: contradiction — low win rate with enough samples
        elif wr < 40 and ss >= 5:
            f = {"check": "BT-1", "severity": "high", "strategy": sid, "symbol": sym,
                 "detail": f"Win rate {wr}% < 40% (sample={ss}, pf={pf})", "backlog_type": "backtest_contradiction"}
            backtest_findings.append(f)

        # BT-3: underperformance
        if pf < 1.0 and pf > 0 and ss >= 10:
            f = {"check": "BT-3", "severity": "medium", "strategy": sid, "symbol": sym,
                 "detail": f"Profit factor {pf} < 1.0 (sample={ss})", "backlog_type": "strategy_underperformance"}
            backtest_findings.append(f)

        # BT-4: insufficient sample
        if cl == "INSUFFICIENT":
            f = {"check": "BT-4", "severity": "low", "strategy": sid, "symbol": sym,
                 "detail": f"Insufficient sample (n={ss})", "backlog_type": "backtest_contradiction"}
            backtest_findings.append(f)

    # Deduplicate backtest findings by strategy+check
    seen_bt = set()
    bt_deduped = []
    for f in backtest_findings:
        key = f"{f['strategy'][:30]}:{f['check']}"
        if key not in seen_bt:
            seen_bt.add(key)
            bt_deduped.append(f)
    backtest_findings = bt_deduped[:MAX_FINDINGS]

    # === SCREENER ===
    scrows = query("SELECT * FROM hermes_v_screener_context ORDER BY run_date DESC LIMIT 25")
    for r in scrows:
        label = r.get("run_label", "?")
        status = r.get("status", "?")
        go = r.get("go_count") or 0
        wait = r.get("wait_count") or 0
        nogo = r.get("no_go_count") or 0
        total = go + wait + nogo

        # MS-1: underfilled
        if status == "RUN_UNDERFILLED":
            screener_findings.append({"check": "MS-1", "severity": "medium",
                "run_label": label, "run_date": str(r.get("run_date")),
                "detail": f"Run underfilled: go={go}, wait={wait}, no_go={nogo}",
                "backlog_type": "momentum_scout_weak_catalyst"})

        # MS-3: no GO
        if go == 0 and total > 0:
            screener_findings.append({"check": "MS-3", "severity": "low",
                "run_label": label, "run_date": str(r.get("run_date")),
                "detail": f"Zero GO candidates (total={total})",
                "backlog_type": "momentum_scout_missing_news"})

    # Deduplicate screener by run_label+check
    seen_sc = set()
    sc_deduped = []
    for f in screener_findings:
        key = f"{f['run_label']}:{f['check']}"
        if key not in seen_sc:
            seen_sc.add(key)
            sc_deduped.append(f)
    screener_findings = sc_deduped[:MAX_FINDINGS]

    # === CATALYST ===
    catrows = query("""
        SELECT symbol, catalyst_type, severity, confidence, impact_score
        FROM hermes_v_catalyst_quality_context
        WHERE confidence < 0.4 OR catalyst_type = 'other'
        ORDER BY confidence ASC LIMIT 25
    """)
    # Count by type rather than listing all 345
    cat_stats = query("""
        SELECT catalyst_type, COUNT(*) as cnt,
               AVG(confidence) as avg_conf, AVG(impact_score) as avg_impact
        FROM hermes_v_catalyst_quality_context
        GROUP BY catalyst_type ORDER BY cnt DESC
    """)
    generic_count = sum(1 for r in catrows if r.get("catalyst_type") == "other")
    low_conf_count = sum(1 for r in catrows if (r.get("confidence") or 1) < 0.4)

    if generic_count > 0:
        catalyst_findings.append({"check": "CAT-2", "severity": "medium",
            "detail": f"{generic_count} catalysts with type='other' (generic, unclassified)",
            "backlog_type": "weak_trade_catalyst",
            "sample_symbols": list(set(r["symbol"] for r in catrows if r.get("catalyst_type") == "other"))[:5]})

    if low_conf_count > 0:
        catalyst_findings.append({"check": "CAT-1", "severity": "medium",
            "detail": f"{low_conf_count} catalysts with confidence < 0.4",
            "backlog_type": "weak_trade_catalyst",
            "sample_symbols": list(set(r["symbol"] for r in catrows if (r.get("confidence") or 1) < 0.4))[:5]})

    # === BUILD BACKLOG CANDIDATES ===
    all_findings = journal_findings + backtest_findings + screener_findings + catalyst_findings

    # Select top backlog candidates
    priority_map = {"high": 1, "medium": 2, "low": 3, "info": 4}
    sorted_findings = sorted(all_findings, key=lambda f: priority_map.get(f.get("severity", "low"), 3))

    for f in sorted_findings[:MAX_BACKLOG]:
        if f.get("backlog_type"):
            backlog.append({
                "check": f["check"],
                "backlog_type": f["backlog_type"],
                "title": f.get("detail", "")[:100],
                "priority": "high" if f["severity"] == "high" else "medium" if f["severity"] == "medium" else "low",
                "owner": "hermes_librarian_agent",
                "detail": f.get("detail", ""),
                "source_view": "backtest" if "BT" in f["check"] else "screener" if "MS" in f["check"] else "catalyst" if "CAT" in f["check"] else "journal",
            })

    # === WRITE OUTPUTS ===
    for name, data in [
        ("journal_findings.json", journal_findings),
        ("backtest_findings.json", backtest_findings),
        ("screener_findings.json", screener_findings),
        ("catalyst_findings.json", catalyst_findings),
        ("research_backlog_candidates.json", backlog[:MAX_BACKLOG]),
        ("rejected_or_low_value_findings.json", rejected),
    ]:
        (OUT / name).write_text(json.dumps(data, indent=2, default=str))

    # Summary
    lines = [
        "# Expanded Librarian Dry-Run Summary", "",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", "",
        f"**Journal rows:** 0 (empty — thesis reviews not yet generated)",
        f"**Backtest rows reviewed:** {len(btrows)}",
        f"**Screener rows reviewed:** {len(scrows)}",
        f"**Catalyst rows queried:** {len(catrows)} (low-conf/generic subset of 345)", "",
        "---", "",
        f"**Journal findings:** {len(journal_findings)}",
        f"**Backtest findings:** {len(backtest_findings)}",
        f"**Screener findings:** {len(screener_findings)}",
        f"**Catalyst findings:** {len(catalyst_findings)}",
        f"**Total findings:** {len(all_findings)}",
        f"**Backlog candidates:** {len(backlog)}", "",
        "**DB writes: ZERO | Embeddings: ZERO | Promotions: ZERO**", "",
        "---", "",
    ]

    for category, findings in [("Journal", journal_findings), ("Backtest", backtest_findings),
                                ("Screener", screener_findings), ("Catalyst", catalyst_findings)]:
        lines.append(f"## {category} Findings ({len(findings)})")
        for f in findings:
            lines.append(f"- [{f.get('severity','?')}] {f['check']}: {f['detail'][:80]}")
        lines.append("")

    lines.append("## Backlog Candidates")
    for b in backlog:
        lines.append(f"- [{b['priority']}] {b['backlog_type']}: {b['title'][:70]}")

    (OUT / "dry_run_summary.md").write_text("\n".join(lines))

    print(f"Journal: {len(journal_findings)}, Backtest: {len(backtest_findings)}, "
          f"Screener: {len(screener_findings)}, Catalyst: {len(catalyst_findings)}")
    print(f"Total findings: {len(all_findings)}, Backlog candidates: {len(backlog)}")
    print(f"DB writes: 0 | Embeddings: 0 | Promotions: 0")


if __name__ == "__main__":
    run()
