# Source Export: scripts/simulate_paper_proposal_approval.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/simulate_paper_proposal_approval.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `5f1f2befaf61d8d11fb3441237ed69e4bb46c9c2a9efe1d0171ca02a1848b226` |
| **File Size** | 9530 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""simulate_paper_proposal_approval.py — Read-only approval simulation.

Runs a proposal through all Phase 6 safety gates without:
- Creating paper trades
- Submitting Alpaca orders
- Mutating proposal status
- Writing approval audit records

Returns gate-by-gate results showing what WOULD happen if approved.

Usage:
    .venv/bin/python scripts/simulate_paper_proposal_approval.py --proposal-id 75 --verbose
    .venv/bin/python scripts/simulate_paper_proposal_approval.py --limit 10 --output-json results.json
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from phase6_proposal_staleness_policy import classify_proposal_staleness
from phase6_market_session_policy import classify_market_session
from paper_trade_logger import validate_paper_proposal_live_market
from market_quote_provider import get_best_quote


def get_conn():
    import psycopg2, psycopg2.extras
    env = {}
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
        user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""),
        cursor_factory=psycopg2.extras.RealDictCursor)


def simulate_proposal(conn, proposal: dict) -> dict:
    """Run read-only simulation of all approval gates on a single proposal.

    DOES NOT: create trades, submit orders, mutate proposal state, write audit.
    """
    now = datetime.now(timezone.utc)
    result = {
        "proposal_id": proposal.get("id"),
        "symbol": proposal.get("symbol"),
        "strategy_id": proposal.get("strategy_id"),
        "simulated_at": now.isoformat(),
        "overall_status": "error",
        "blocking_gate": None,
        "proposal_freshness": None,
        "market_session_policy": None,
        "market_revalidation": None,
        "risk_gate": None,
        "paper_order_preview": None,
        "operator_summary": "",
        "next_action": "investigate",
    }

    # ── Gate 1: Freshness ──
    freshness = classify_proposal_staleness(proposal, now)
    result["proposal_freshness"] = freshness

    if freshness.get("status") == "terminal":
        result["overall_status"] = "would_block"
        result["blocking_gate"] = "freshness"
        result["operator_summary"] = f"Proposal is {proposal.get('status')} — terminal state."
        result["next_action"] = "reject"
        return result

    if not freshness.get("fresh", False):
        result["overall_status"] = "needs_refresh"
        result["blocking_gate"] = "freshness"
        result["operator_summary"] = freshness.get("reason", "Proposal is stale.")
        result["next_action"] = "refresh_proposal"
        return result

    # ── Gate 2: Session Policy ──
    session = classify_market_session()
    result["market_session_policy"] = session

    if not session.get("allowed", False):
        result["overall_status"] = "would_block"
        result["blocking_gate"] = "session"
        result["operator_summary"] = session.get("reason", "Market session not allowed.")
        result["next_action"] = "wait_for_market"
        return result

    # ── Gate 3: Market Revalidation ──
    entry = float(proposal.get("proposed_entry") or 0)
    stop = float(proposal.get("proposed_stop") or 0)
    target = float(proposal.get("proposed_target1") or 0)
    shares = int(proposal.get("proposed_shares") or 0)

    if entry <= 0 or stop <= 0 or target <= 0:
        result["overall_status"] = "would_block"
        result["blocking_gate"] = "revalidation"
        result["operator_summary"] = "Missing entry/stop/target — cannot validate."
        result["next_action"] = "investigate"
        return result

    try:
        quote = get_best_quote(proposal["symbol"])
    except Exception as e:
        quote = {"last_price": None}

    reval = validate_paper_proposal_live_market(
        proposal["symbol"], entry, stop, target, shares, quote)
    result["market_revalidation"] = reval

    if not reval.get("ok", False):
        result["overall_status"] = "would_block"
        result["blocking_gate"] = "revalidation"
        result["operator_summary"] = reval.get("reason", "Market revalidation failed.")
        result["next_action"] = "refresh_proposal" if "drift" in (reval.get("reason") or "") else "reject"
        return result

    # ── Gate 4: Risk Gate ──
    risk_result = {"passed": True, "result": "APPROVED", "reason_codes": []}
    try:
        from risk_gate import RiskGate
        gate = RiskGate(conn)
        entry_price = reval.get("adjusted_entry") or entry
        dollar_size = round(float(shares) * float(entry_price), 2)
        decision = gate.check(
            proposal["symbol"], proposal.get("strategy_id"),
            {"stop_loss": float(stop), "dollar_size": dollar_size},
            proposal.get("proposed_account", "ALPACA_PAPER"), "paper", "paper_trade")
        risk_result = {
            "passed": decision.approved,
            "result": decision.result,
            "reason_codes": decision.reason_codes,
        }
    except Exception as e:
        risk_result = {"passed": False, "result": "ERROR", "reason_codes": [str(e)]}

    result["risk_gate"] = risk_result

    if not risk_result["passed"]:
        result["overall_status"] = "would_block"
        result["blocking_gate"] = "risk_gate"
        result["operator_summary"] = f"Risk gate: {risk_result['reason_codes']}"
        result["next_action"] = "investigate"
        return result

    # ── All gates passed — build order preview ──
    adjusted_entry = reval.get("adjusted_entry") or entry
    dollar_risk = round(abs(float(adjusted_entry) - float(stop)) * shares, 2)
    result["paper_order_preview"] = {
        "symbol": proposal["symbol"],
        "side": "buy",
        "shares": shares,
        "entry": adjusted_entry,
        "stop": stop,
        "target": target,
        "dollar_size": round(float(adjusted_entry) * shares, 2),
        "dollar_risk": dollar_risk,
        "rr": reval["checks"].get("rr"),
        "live_price": reval.get("live_price"),
        "account": proposal.get("proposed_account", "ALPACA_PAPER"),
    }

    result["overall_status"] = "would_pass"
    result["blocking_gate"] = None
    result["operator_summary"] = (
        f"All gates pass. {proposal['symbol']} at ${reval.get('live_price', '?')}, "
        f"R:R={reval['checks'].get('rr', '?')}:1. Ready to approve."
    )
    result["next_action"] = "approve_now"
    return result


def main():
    p = argparse.ArgumentParser(description="Simulate paper proposal approval (read-only)")
    p.add_argument("--proposal-id", type=int)
    p.add_argument("--symbol", type=str)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    # Load proposals
    if args.proposal_id:
        cur.execute("SELECT * FROM paper_trade_proposals WHERE id = %s", [args.proposal_id])
    elif args.symbol:
        cur.execute("SELECT * FROM paper_trade_proposals WHERE symbol = %s AND status = 'PENDING' ORDER BY created_at DESC LIMIT %s", [args.symbol, args.limit])
    else:
        cur.execute("SELECT * FROM paper_trade_proposals WHERE status = 'PENDING' ORDER BY created_at DESC LIMIT %s", [args.limit])

    proposals = cur.fetchall()
    results = []

    for prop in proposals:
        sim = simulate_proposal(conn, dict(prop))
        results.append(sim)
        if args.verbose:
            status_icon = {"would_pass": "✓", "would_block": "✗", "needs_refresh": "~", "error": "!"}
            icon = status_icon.get(sim["overall_status"], "?")
            print(f"  {icon} #{sim['proposal_id']} {sim['symbol']} [{sim['overall_status']}] "
                  f"gate={sim['blocking_gate'] or 'none'} → {sim['next_action']}")

    conn.close()

    summary = {
        "simulated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "would_pass": sum(1 for r in results if r["overall_status"] == "would_pass"),
        "would_block": sum(1 for r in results if r["overall_status"] == "would_block"),
        "needs_refresh": sum(1 for r in results if r["overall_status"] == "needs_refresh"),
        "results": results,
    }

    if args.verbose:
        print(f"\nSummary: {summary['total']} simulated — "
              f"{summary['would_pass']} pass, {summary['would_block']} block, "
              f"{summary['needs_refresh']} refresh")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(summary, indent=2, default=str))
    if args.output_md:
        md = [f"# Approval Simulation — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
              f"\n| ID | Symbol | Status | Gate | Action |",
              f"|---|--------|--------|------|--------|"]
        for r in results:
            md.append(f"| {r['proposal_id']} | {r['symbol']} | {r['overall_status']} | {r['blocking_gate'] or '-'} | {r['next_action']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
