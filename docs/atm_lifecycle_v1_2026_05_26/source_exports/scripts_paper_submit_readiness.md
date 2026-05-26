# Source Export: scripts/paper_submit_readiness.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/paper_submit_readiness.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `3c8a843e8c929f776c79f2e8f48c751c84710a56e0e8da9f2e297aad1bfec432` |
| **File Size** | 9693 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""paper_submit_readiness.py — Pre-submission readiness checker for paper proposals.

Validates all safety, data, and execution gates before a proposal can be
submitted to Alpaca paper trading.

SAFETY: Paper trading ONLY. Live trading is permanently blocked.

Usage:
    .venv/bin/python scripts/paper_submit_readiness.py --proposal-id 123
    .venv/bin/python scripts/paper_submit_readiness.py --best-candidates --limit 5
    .venv/bin/python scripts/paper_submit_readiness.py --proposal-id 123 --apply
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

os.environ.setdefault("DOTENV_LOADED", "0")
if os.environ["DOTENV_LOADED"] == "0":
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        os.environ["DOTENV_LOADED"] = "1"
    except Exception:
        pass

import psycopg2
import psycopg2.extras

log = logging.getLogger("paper_submit_readiness")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Hard safety locks
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
ALPACA_MODE = os.getenv("ALPACA_MODE", "paper").lower()


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def check_readiness(conn, proposal_id: int) -> dict:
    """Run all readiness checks for a proposal. Returns structured result."""
    cur = conn.cursor()

    # Load proposal
    cur.execute("""
        SELECT id, symbol, strategy_id, status, proposed_entry, proposed_stop,
               proposed_target1, proposed_shares, proposed_dollar_risk, proposed_rr,
               risk_gate_result, approval_allowed, intel_readiness,
               action_state, latest_execution_readiness
        FROM paper_trade_proposals WHERE id = %s
    """, [proposal_id])
    p = cur.fetchone()
    if not p:
        return {
            "proposal_id": proposal_id,
            "submit_state": "BLOCKED",
            "blockers": [f"Proposal {proposal_id} not found"],
            "warnings": [],
        }

    blockers = []
    warnings = []

    # Check 1: LIVE_TRADING_ENABLED != true
    if LIVE_TRADING_ENABLED:
        blockers.append("LIVE_TRADING_ENABLED is true -- paper submitter blocked")

    # Check 2: ALPACA_MODE = paper
    if ALPACA_MODE != "paper":
        blockers.append(f"ALPACA_MODE={ALPACA_MODE}, must be 'paper'")

    # Check 3: Proposal status must be submittable
    SUBMITTABLE_STATUSES = ('PENDING', 'APPROVED', 'APPROVED_FOR_PAPER_TEST')
    if p["status"] not in SUBMITTABLE_STATUSES:
        blockers.append(f"Proposal status is {p['status']}, must be one of {SUBMITTABLE_STATUSES}")

    # Check 4: action_state executable
    action_state = p.get("action_state") or ""
    if action_state == "BLOCKED":
        blockers.append(f"action_state is BLOCKED")
    elif action_state not in ("PAPER_READY", "CAUTION", ""):
        warnings.append(f"action_state is {action_state}")

    # Check 5: execution_readiness ready
    er = p.get("latest_execution_readiness") or {}
    if isinstance(er, str):
        try:
            er = json.loads(er)
        except Exception:
            er = {}
    readiness_state = er.get("readiness_state", "")
    if readiness_state and "BLOCKED" in readiness_state.upper():
        blockers.append(f"Execution readiness: {readiness_state}")
    elif readiness_state and readiness_state not in ("READY_FOR_PAPER_SUBMIT", "READY_ORB_CONFIRMED", "CAUTION_EXECUTABLE"):
        warnings.append(f"Execution readiness: {readiness_state}")

    # Check 6: quote_execution_eligible
    if er.get("quote_execution_eligible") is False:
        blockers.append("Quote not execution-eligible (display-only data)")

    # Check 7: risk gate
    rg = p.get("risk_gate_result") or ""
    if rg in ("REJECTED", "FAIL", "BLOCKED"):
        blockers.append(f"Risk gate: {rg}")
    elif rg and rg not in ("APPROVED", "PASS", ""):
        warnings.append(f"Risk gate: {rg}")

    # Check 8: entry zone not missed
    try:
        cur.execute("""
            SELECT lifecycle_status, entry_zone_status FROM paper_trade_proposals WHERE id = %s
        """, [proposal_id])
        lc = cur.fetchone()
        if lc:
            ls = lc.get("lifecycle_status") or lc.get("entry_zone_status") or ""
            if ls == "ENTRY_MISSED":
                blockers.append("Entry zone missed -- price has moved away")
            elif ls == "EXPIRED":
                blockers.append("Proposal has expired")
    except Exception:
        pass

    # Check 9: no duplicate client_order_id
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    client_order_id = f"tradeai-paper-{proposal_id}-{p['symbol']}-{today}"
    cur.execute("""
        SELECT COUNT(*) as cnt FROM paper_trades
        WHERE broker_order_id LIKE %s OR broker_order_id = %s
    """, [f"%{client_order_id}%", client_order_id])
    dup = cur.fetchone()
    if (dup.get("cnt") or 0) > 0:
        blockers.append(f"Duplicate client_order_id: {client_order_id}")

    # Check 10: stop/target/shares valid
    entry = float(p["proposed_entry"] or 0)
    stop = float(p["proposed_stop"] or 0)
    target = float(p["proposed_target1"] or 0)
    shares = int(p["proposed_shares"] or 0)

    if entry <= 0:
        blockers.append("Entry price is zero or missing")
    if stop <= 0:
        blockers.append("Stop price is zero or missing")
    if target <= 0:
        blockers.append("Target price is zero or missing")
    if shares <= 0:
        blockers.append("Shares is zero or missing")
    if entry > 0 and stop > 0 and stop >= entry:
        blockers.append(f"Stop (${stop}) >= entry (${entry})")
    if entry > 0 and target > 0 and target <= entry:
        warnings.append(f"Target (${target}) <= entry (${entry})")

    # Determine submit state
    if len(blockers) > 0:
        submit_state = "BLOCKED"
    elif len(warnings) > 0:
        submit_state = "CAUTION_EXECUTABLE"
    else:
        submit_state = "READY_FOR_PAPER_SUBMIT"

    return {
        "proposal_id": proposal_id,
        "symbol": p["symbol"],
        "strategy_id": p["strategy_id"],
        "submit_state": submit_state,
        "blockers": blockers,
        "warnings": warnings,
        "client_order_id": client_order_id,
        "entry": entry,
        "stop": stop,
        "target": target,
        "shares": shares,
        "alpaca_mode": ALPACA_MODE,
        "live_trading_enabled": LIVE_TRADING_ENABLED,
    }


def find_best_candidates(conn, limit: int = 5) -> list:
    """Find top proposals ready for paper submission."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM paper_trade_proposals
        WHERE status IN ('PENDING', 'APPROVED', 'APPROVED_FOR_PAPER_TEST')
          AND (expires_at IS NULL OR expires_at > NOW())
        ORDER BY signal_score DESC NULLS LAST, created_at DESC
        LIMIT %s
    """, [limit * 3])  # Fetch extra, then filter
    rows = cur.fetchall()

    candidates = []
    for row in rows:
        result = check_readiness(conn, row["id"])
        result["rank_score"] = (
            100 if result["submit_state"] == "READY_FOR_PAPER_SUBMIT"
            else 50 if result["submit_state"] == "CAUTION_EXECUTABLE"
            else 0
        )
        candidates.append(result)

    # Sort by rank, then fewer blockers
    candidates.sort(key=lambda c: (-c["rank_score"], len(c["blockers"]), len(c["warnings"])))
    return candidates[:limit]


def apply_readiness_state(conn, proposal_id: int, result: dict):
    """Write readiness check result back to the proposal."""
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE paper_trade_proposals
            SET action_state = %s, updated_at = NOW()
            WHERE id = %s
        """, [result["submit_state"], proposal_id])
        conn.commit()
        log.info(f"Updated proposal {proposal_id} action_state -> {result['submit_state']}")
    except Exception as e:
        conn.rollback()
        log.error(f"Failed to update proposal {proposal_id}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Paper submit readiness checker")
    parser.add_argument("--proposal-id", type=int, help="Check one proposal")
    parser.add_argument("--best-candidates", action="store_true", help="Find top candidates")
    parser.add_argument("--limit", type=int, default=5, help="Number of candidates")
    parser.add_argument("--apply", action="store_true", help="Write readiness state to DB")
    args = parser.parse_args()

    conn = get_db()
    try:
        if args.best_candidates:
            candidates = find_best_candidates(conn, args.limit)
            if args.apply:
                for c in candidates:
                    apply_readiness_state(conn, c["proposal_id"], c)
            print(json.dumps({"candidates": candidates}, indent=2, default=str))
        elif args.proposal_id:
            result = check_readiness(conn, args.proposal_id)
            if args.apply:
                apply_readiness_state(conn, args.proposal_id, result)
            print(json.dumps(result, indent=2, default=str))
        else:
            parser.error("Specify --proposal-id or --best-candidates")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```
