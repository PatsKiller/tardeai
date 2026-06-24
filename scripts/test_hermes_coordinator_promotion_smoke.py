#!/usr/bin/env python3
"""test_hermes_coordinator_promotion_smoke.py — basic smoke + integration checks for coordinator + promotion path.

Run:
    .venv/bin/python scripts/test_hermes_coordinator_promotion_smoke.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

def test_imports_and_constants():
    import hermes_coordinator as coord
    assert hasattr(coord, "CAP_PROMOTE")
    assert hasattr(coord, "CAP_EMBED")
    assert coord.CAP_EMBED >= 10
    print("✓ imports and caps OK")

def test_killswitch_helper():
    from hermes_killswitch import is_hermes_disabled, describe_killswitch
    disabled, path = is_hermes_disabled()
    desc = describe_killswitch()
    assert "canonical_path" in desc
    print(f"✓ killswitch: disabled={disabled} path={path or '(off)'}")

def test_db_and_research_counts():
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM hermes_research_intelligence WHERE status='promoted'")
    promoted = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM hermes_embedding_queue WHERE embedding_status='pending'")
    pending = cur.fetchone()[0]
    assert promoted >= 0 and pending >= 0
    print(f"✓ DB reachable: promoted={promoted}, embed_pending={pending}")
    conn.close()

def test_maturity_dashboard_builds():
    # Re-uses the live builder (read-only)
    import psycopg2
    from dotenv import load_dotenv
    import hermes_maturity_dashboard as md
    load_dotenv(ROOT / ".env")
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    report = md.build_maturity_report(conn)
    conn.close()
    assert report.get("ok") is True or "layer_scores" in report
    assert "areas" in report and len(report["areas"]) > 5
    assert "directive_b_active" in report, "Directive B status must be reported"
    print(f"✓ maturity dashboard built: overall_autonomous={report.get('layer_scores', {}).get('overall_autonomous')}, directive_b={report.get('directive_b_active')}")

def test_enqueue_dry_logic():
    import psycopg2
    from dotenv import load_dotenv
    from hermes_embedding_enqueue import enqueue_research, backfill_promoted
    load_dotenv(ROOT / ".env")
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    cur = conn.cursor()
    # Just test the function doesn't blow up on a non-existing id (should return False safely)
    ok = enqueue_research(cur, 999999999, skip_existing=True)
    assert ok is False
    # backfill should be callable
    n = backfill_promoted(conn, limit=1, dry_run=True)
    assert n >= 0
    print("✓ enqueue/backfill logic smoke OK (dry)")
    conn.close()

if __name__ == "__main__":
    print("Hermes coordinator + promotion smoke tests")
    test_imports_and_constants()
    test_killswitch_helper()
    test_db_and_research_counts()
    test_maturity_dashboard_builds()
    test_enqueue_dry_logic()
    print("\nALL SMOKE TESTS PASSED")
