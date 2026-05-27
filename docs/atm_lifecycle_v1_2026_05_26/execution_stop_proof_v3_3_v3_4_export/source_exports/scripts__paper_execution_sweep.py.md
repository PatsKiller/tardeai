# Source: scripts/paper_execution_sweep.py
| Commit | `08b5327b8652cc59d04ee25e75e1eab690bfd797` | SHA256 | `1109ebcb669dde98173ecbdbebbbc63de29e629dd0a68fd68b464d8065d8a940` | Size | 4579 bytes |

```python
#!/usr/bin/env python3
"""paper_execution_sweep.py — Safety net for approved proposals not yet submitted.

Runs every 5 minutes during market hours. Catches any approved proposals that
didn't get instant-submitted (e.g., server restart during approval, network blip).

This is NOT the primary execution path — instant execution on approval is.
This is the safety net that prevents missed trades.

Usage:
    .venv/bin/python scripts/paper_execution_sweep.py
    .venv/bin/python scripts/paper_execution_sweep.py --dry-run
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def _is_market_hours() -> bool:
    """Check if US market is currently open (9:30 AM - 4:00 PM ET, weekdays)."""
    from datetime import datetime
    import pytz
    try:
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et)
        if now.weekday() >= 5:  # Saturday/Sunday
            return False
        market_open = now.replace(hour=9, minute=30, second=0)
        market_close = now.replace(hour=16, minute=0, second=0)
        return market_open <= now <= market_close
    except Exception:
        # If pytz not available, use UTC approximation
        now = datetime.now(timezone.utc)
        if now.weekday() >= 5:
            return False
        # ET is UTC-4 during EDT
        et_hour = (now.hour - 4) % 24
        return 9 <= et_hour < 16


def sweep(dry_run=False):
    """Find approved proposals not yet submitted and submit them."""
    from session13_db import get_conn
    conn = get_conn()
    cur = conn.cursor()

    # Find approved proposals that haven't been submitted to Alpaca
    cur.execute("""
        SELECT id, symbol, strategy_id, proposed_entry, proposed_stop, proposed_target1,
               status, paper_submit_state, lifecycle_status, entry_zone_status
        FROM paper_trade_proposals
        WHERE status IN ('APPROVED', 'APPROVED_FOR_PAPER_TEST')
          AND (paper_submit_state IS NULL OR paper_submit_state = 'NOT_SUBMITTED')
          AND alpaca_paper_submit_enabled = false
          AND expires_at > NOW()
          AND lifecycle_status NOT IN ('EXPIRED', 'ENTRY_MISSED')
        ORDER BY approved_at ASC
    """)

    import psycopg2.extras
    cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur2.execute("""
        SELECT id, symbol, strategy_id, proposed_entry, proposed_stop, proposed_target1,
               status, paper_submit_state, lifecycle_status, entry_zone_status
        FROM paper_trade_proposals
        WHERE status IN ('APPROVED', 'APPROVED_FOR_PAPER_TEST')
          AND (paper_submit_state IS NULL OR paper_submit_state = 'NOT_SUBMITTED')
          AND alpaca_paper_submit_enabled = false
          AND expires_at > NOW()
          AND lifecycle_status NOT IN ('EXPIRED', 'ENTRY_MISSED')
        ORDER BY approved_at ASC
    """)
    proposals = cur2.fetchall()

    if not proposals:
        print(f"  No unsubmitted approved proposals found")
        return 0

    if not _is_market_hours():
        print(f"  {len(proposals)} approved proposals waiting — market is closed, holding until open")
        return 0

    submitted = 0
    for p in proposals:
        pid = p["id"]
        sym = p["symbol"]
        print(f"  [{sym}] Attempting paper submission for proposal #{pid}...")

        if dry_run:
            print(f"    [dry-run] Would submit {sym} (proposal #{pid})")
            submitted += 1
            continue

        try:
            from proposal_paper_submitter import submit_paper
            result = submit_paper(conn, pid, dry_run=False)
            status = result.get("status", "unknown")
            if status == "submitted":
                print(f"    Submitted to Alpaca: {sym}")
                submitted += 1
            else:
                print(f"    Submission result: {status} — {result.get('reason', result.get('error', ''))}")
        except Exception as e:
            print(f"    Error: {e}")

    conn.close()
    return submitted


def main():
    parser = argparse.ArgumentParser(description="Paper Execution Sweep")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"[paper_execution_sweep] {datetime.now().isoformat()}")
    submitted = sweep(dry_run=args.dry_run)
    print(f"  Submitted: {submitted}")


if __name__ == "__main__":
    main()
```
