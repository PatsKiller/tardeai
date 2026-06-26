#!/usr/bin/env python3
"""
live_trading_gate.py — Enforces paper-only trading until all validation gates pass.

Fail-closed: if anything is unknown, trading is BLOCKED.

Usage:
    python live_trading_gate.py --status
    python live_trading_gate.py --status --json
    python live_trading_gate.py --assert-safe
    python live_trading_gate.py --evaluate
"""
import argparse, json, os, sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

def _env(key, default=""):
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.getenv(key, default)

def _get_conn():
    import psycopg2
    return psycopg2.connect(host="localhost", dbname="trade_ai",
                            user="trade_ai", password=_env("DB_PASSWORD"))


def evaluate():
    """Evaluate all trading gates. Returns dict with allowed + blocked_reasons."""
    result = {
        "allowed": False,
        "mode": "PAPER",
        "blocked_reasons": [],
        "gates": {},
    }

    # Gate 1: .env ALPACA_MODE
    alpaca_mode = _env("ALPACA_MODE", "paper").lower()
    result["gates"]["alpaca_mode"] = alpaca_mode
    if alpaca_mode != "paper":
        result["blocked_reasons"].append("alpaca_mode_not_paper")

    # Gate 2: .env LIVE_TRADING
    live_flag = _env("LIVE_TRADING_ENABLED", "false").lower()
    result["gates"]["live_trading_env"] = live_flag
    if live_flag not in ("false", "no", "0", ""):
        result["blocked_reasons"].append("env_live_trading_not_false")

    # Gate 3: DB policy
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT validation_start_date, minimum_validation_days,
                   minimum_closed_trades, minimum_win_rate, minimum_profit_factor,
                   requires_governance_approval, live_trading_allowed
            FROM paper_validation_policy
            WHERE policy_key='live_trading_gate_v1' AND active=true
        """)
        policy = cur.fetchone()
        if policy:
            start_date, min_days, min_trades, min_wr, min_pf, req_gov, db_allowed = policy

            # Gate 3a: DB policy live_trading_allowed
            result["gates"]["policy_live_trading_allowed"] = db_allowed
            if not db_allowed:
                result["blocked_reasons"].append("policy_live_trading_allowed_false")

            # Gate 3b: Validation days
            if start_date:
                elapsed = (date.today() - start_date).days
                result["gates"]["validation_days_elapsed"] = elapsed
                result["gates"]["validation_days_required"] = min_days
                if elapsed < min_days:
                    result["blocked_reasons"].append("validation_days_insufficient")
            else:
                result["gates"]["validation_days_elapsed"] = 0
                result["blocked_reasons"].append("validation_start_date_not_set")

            # Gate 3c: Closed trades
            cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed'")
            closed = cur.fetchone()[0]
            result["gates"]["closed_trades"] = closed
            result["gates"]["closed_trades_required"] = min_trades
            if closed < min_trades:
                result["blocked_reasons"].append("closed_trade_sample_insufficient")

            # Gate 3d: Win rate
            if closed > 0:
                cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed' AND pnl > 0")
                wins = cur.fetchone()[0]
                win_rate = round(wins / closed, 4) if closed > 0 else 0
                result["gates"]["win_rate"] = win_rate
                result["gates"]["win_rate_required"] = float(min_wr)
                if win_rate < float(min_wr):
                    result["blocked_reasons"].append("win_rate_below_threshold")
            else:
                result["gates"]["win_rate"] = 0
                result["blocked_reasons"].append("win_rate_below_threshold")

            # Gate 3e: Profit factor
            cur.execute("""
                SELECT COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0)
                FROM paper_trades WHERE status='closed'
            """)
            gross_profit, gross_loss = cur.fetchone()
            pf = round(float(gross_profit) / float(gross_loss), 4) if gross_loss > 0 else 0
            result["gates"]["profit_factor"] = pf
            result["gates"]["profit_factor_required"] = float(min_pf)
            if pf < float(min_pf):
                result["blocked_reasons"].append("profit_factor_below_threshold")

            # Gate 3f: Governance approval
            if req_gov:
                cur.execute("""
                    SELECT approved FROM governance_approvals
                    WHERE approval_key='live_trading_v1' AND approved=true
                """)
                gov = cur.fetchone()
                result["gates"]["governance_approved"] = bool(gov)
                if not gov:
                    result["blocked_reasons"].append("governance_not_approved")
        else:
            result["blocked_reasons"].append("no_active_policy_found")

        conn.close()
    except Exception as e:
        result["blocked_reasons"].append(f"db_error: {str(e)[:100]}")

    # Final determination — autonomous Alpaca path only (Schwab operator+2FA is separate)
    if not result["blocked_reasons"]:
        result["allowed"] = True
        result["mode"] = "LIVE_ELIGIBLE"
    else:
        result["allowed"] = False
        result["mode"] = "PAPER"

    try:
        import execution_state as es
        labels = es.live_trading_labels()
        result["autonomous_live_trading_allowed"] = labels.get("autonomous_live_trading_allowed")
        result["operator_live_via_2fa_allowed"] = labels.get("operator_live_via_2fa_allowed")
        result["operator_approved_live_submit_possible"] = labels.get("operator_approved_live_submit_possible")
        result["operator_status_label"] = labels.get("operator_status_label")
        result["autonomous_status_label"] = labels.get("autonomous_status_label")
        result["per_order_2fa_required"] = True
        result["note"] = (
            "Autonomous Alpaca live requires all gates above. "
            "Schwab operator live via standing unlock + per-order 2FA is a separate path."
        )
    except Exception as e:
        result["operator_path_inspect_error"] = str(e)[:120]

    return result


def main():
    parser = argparse.ArgumentParser(description="Live Trading Gate")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--assert-safe", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = evaluate()

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    elif args.status or args.evaluate:
        print(f"\n  Live Trading Gate: {'ALLOWED' if result['allowed'] else 'BLOCKED'}")
        print(f"  Mode: {result['mode']}")
        if result["blocked_reasons"]:
            print(f"  Blocked reasons:")
            for r in result["blocked_reasons"]:
                print(f"    - {r}")
        print(f"\n  Gates:")
        for k, v in result["gates"].items():
            print(f"    {k}: {v}")

    if args.assert_safe:
        if result["allowed"]:
            print("FATAL: Live trading would be ALLOWED. This should not happen in paper mode.")
            sys.exit(1)
        else:
            print(f"SAFE: Trading blocked ({len(result['blocked_reasons'])} reasons). Paper mode enforced.")
            sys.exit(0)


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
