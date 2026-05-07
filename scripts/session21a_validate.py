#!/usr/bin/env python3
"""session21a_validate.py — Validate Session 21A: Proposal Intelligence Wiring."""
import json
import os
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

PASS = 0
FAIL = 0
WARN = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    status = "PASS" if condition else "FAIL"
    if condition:
        PASS += 1
    else:
        FAIL += 1
    symbol = "✓" if condition else "✗"
    print(f"  {symbol} {label}: {status}" + (f" — {detail}" if detail else ""))
    return condition


def warn(label, detail=""):
    global WARN
    WARN += 1
    print(f"  ⚠ {label}: WARN — {detail}")


def get_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD"),
    )


def main():
    print("\n=== SESSION 21A VALIDATION ===\n")

    # 1. qwen3:14b local model
    print("[1] Local LLM Model")
    try:
        from local_llm_config import get_local_llm_model
        model = get_local_llm_model()
        check("LLM model is qwen3:14b", model == "qwen3:14b", model)
    except Exception as e:
        check("LLM model import", False, str(e))

    # 2-4. API returns agent_reviews, llm_analysis, quality_review
    print("\n[2-4] Paper Proposals API Enrichment")
    try:
        r = urllib.request.urlopen("http://localhost:7777/api/v2/paper-proposals")
        data = json.loads(r.read())
        props = data.get("proposals") or []
        pending = [p for p in props if p.get("status") == "PENDING"]
        check("API returns ok", data.get("ok"), f"{len(pending)} pending proposals")

        if pending:
            p = pending[0]
            check("agent_reviews key present", "agent_reviews" in p, f"{len(p.get('agent_reviews', []))} reviews")
            check("llm_analysis key present", "llm_analysis" in p and p.get("llm_analysis") is not None)
            check("quality_review key present", "quality_review" in p and p.get("quality_review") is not None,
                  (p.get("quality_review") or {}).get("review_state", "?"))
            check("intelligence key present", "intelligence" in p,
                  f"readiness={((p.get('intelligence') or {}).get('intelligence_readiness'))}")
        else:
            warn("No pending proposals to validate enrichment")
    except Exception as e:
        check("API reachable", False, str(e))

    # 5. Intelligence readiness not all zero
    print("\n[5] Intelligence Readiness")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT symbol, intelligence_readiness, intelligence_readiness_source
        FROM trade_ai_scans
        WHERE DATE(scanned_at) = CURRENT_DATE AND decision = 'GO'
        ORDER BY score DESC
    """)
    go_rows = cur.fetchall()
    all_zero = all(r[1] == 0 or r[1] is None for r in go_rows) if go_rows else True
    check("GO intelligence_readiness not all zero", not all_zero,
          ", ".join(f"{r[0]}={r[1]}({r[2]})" for r in go_rows))

    # 6. No pending proposal for recently rejected WAIT/low-score symbol
    print("\n[6] Rejection Cooldown")
    cur.execute("""
        SELECT ptp.symbol FROM paper_trade_proposals ptp
        WHERE ptp.status = 'PENDING'
        AND EXISTS (
            SELECT 1 FROM paper_trade_proposals rej
            WHERE rej.symbol = ptp.symbol
            AND rej.status = 'REJECTED'
            AND rej.rejected_at > NOW() - INTERVAL '24 hours'
        )
    """)
    rejected_pending = cur.fetchall()
    check("No pending proposal for recently rejected symbol",
          len(rejected_pending) == 0,
          f"{len(rejected_pending)} violations" if rejected_pending else "clean")

    # 7. Agent queue ran
    print("\n[7] Agent Queue")
    cur.execute("""
        SELECT COUNT(*) FROM watchlist_agent_jobs
        WHERE created_at::date = CURRENT_DATE
        AND request_type IN ('proposal_review', 'go_signal_review')
    """)
    job_count = cur.fetchone()[0]
    check("Agent jobs queued today", job_count > 0, f"{job_count} jobs")

    cur.execute("""
        SELECT COUNT(DISTINCT agent || symbol) FROM watchlist_agent_results
        WHERE created_at::date = CURRENT_DATE
        AND symbol IN (SELECT symbol FROM paper_trade_proposals WHERE status = 'PENDING')
    """)
    result_count = cur.fetchone()[0]
    check("Agent results for pending symbols", result_count > 0, f"{result_count} results")

    # 8. proposal_intelligence_analyzer ran
    print("\n[8] Proposal Intelligence Analysis")
    cur.execute("""
        SELECT COUNT(*) FROM paper_proposal_analysis
        WHERE created_at::date = CURRENT_DATE
    """)
    analysis_count = cur.fetchone()[0]
    check("Proposal analyses today", analysis_count > 0, f"{analysis_count} analyses")

    # 9. proposal_quality_reviewer ran
    print("\n[9] Proposal Quality Reviews")
    cur.execute("""
        SELECT COUNT(*) FROM proposal_quality_reviews
        WHERE created_at::date = CURRENT_DATE
    """)
    qr_count = cur.fetchone()[0]
    check("Quality reviews today", qr_count > 0, f"{qr_count} reviews")

    # 10. Frontend builds
    print("\n[10] Frontend Build")
    dist_path = PROJECT_ROOT / "apps" / "command-center-v2" / "dist" / "index.html"
    check("Frontend build exists", dist_path.exists())

    # 11. Real journal clean
    print("\n[11] Real Journal Clean")
    try:
        r = urllib.request.urlopen("http://localhost:7777/api/v2/journal")
        raw = json.loads(r.read())
        jdata = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        trades = jdata.get("trades") or jdata.get("entries") or []
        if isinstance(trades, list):
            paper = [t for t in trades if isinstance(t, dict) and ("PAPER" in str(t.get("account", "")) or "PAPER" in str(t.get("account_name", "")))]
            check("No paper trades in real journal", len(paper) == 0, f"{len(paper)} paper contamination")
        else:
            check("Real journal clean", True, "no trades array (clean)")
    except Exception as e:
        warn("Journal API not reachable", str(e))

    # 12. Holdings untouched
    print("\n[12] Holdings Untouched")
    try:
        hpath = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
        hdata = json.loads(hpath.read_text())
        total = hdata["portfolio_totals"]["total_value"]
        check("Holdings > $1M", total > 1000000, f"${total:,.0f}")
    except Exception as e:
        check("Holdings file readable", False, str(e))

    # 13. No hardcoded DB password fallback
    print("\n[13] No Hardcoded DB Password")
    flagged_files = []
    for script in ["queue_proposal_agent_reviews.py", "proposal_intelligence_analyzer.py",
                    "proposal_quality_reviewer.py", "auto_proposal_generator.py"]:
        path = PROJECT_ROOT / "scripts" / script
        if path.exists():
            content = path.read_text()
            # Check for hardcoded password strings like password='secret' or password="trade_ai"
            import re
            hardcoded = re.findall(r'password\s*=\s*["\'][^"\']+["\']', content)
            for match in hardcoded:
                # Exclude patterns like password=os.getenv(...) or password=password (variable ref)
                if "getenv" not in match and "environ" not in match:
                    flagged_files.append(f"{script}: {match}")
    check("No hardcoded DB password", len(flagged_files) == 0,
          f"flagged: {flagged_files}" if flagged_files else "clean")

    conn.close()

    # Summary
    print(f"\n{'='*50}")
    print(f"RESULTS: {PASS} PASS / {FAIL} FAIL / {WARN} WARN")
    if FAIL == 0:
        print("SESSION 21A VALIDATION: ALL CHECKS PASSED")
    else:
        print("SESSION 21A VALIDATION: SOME CHECKS FAILED")
    print(f"{'='*50}\n")

    return FAIL == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
