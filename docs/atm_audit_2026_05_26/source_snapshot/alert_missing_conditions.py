#!/usr/bin/env python3
"""alert_missing_conditions.py — Check for conditions that should trigger alerts
but currently don't have dedicated alerting.

Runs daily (add to cron). Checks:
  1. Proposals stuck in PENDING > 7 days
  2. Anthropic API credit depletion
  3. Email digest not firing
  4. Pipeline self-monitoring failures

Uses alert_dispatcher for routing, dedup, and fatigue detection.
"""
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v


def _get_conn():
    import psycopg2
    pw = os.getenv("DB_PASSWORD", "")
    return psycopg2.connect(host="127.0.0.1", port=5432,
                            dbname="trade_ai", user="trade_ai", password=pw)


def check_stale_proposals(conn):
    """Alert for proposals stuck in PENDING > 7 days."""
    from alert_dispatcher import alert_proposal_aging
    cur = conn.cursor()
    cur.execute("""
        SELECT symbol, created_at::date as created,
               (CURRENT_DATE - created_at::date) as days_pending
        FROM paper_trade_proposals
        WHERE status = 'PENDING' AND created_at < NOW() - INTERVAL '7 days'
        ORDER BY created_at ASC
    """)
    stale = cur.fetchall()
    count = 0
    for sym, created, days in stale:
        result = alert_proposal_aging(sym, days, source="alert_missing_conditions")
        if result.get("sent"):
            count += 1
    return count


def check_api_credits(conn):
    """Check if Anthropic API is accessible."""
    from alert_dispatcher import alert_api_credits_depleted
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return 0

    try:
        import requests
        # Minimal POST to check credit status
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            },
            timeout=15
        )
        if resp.status_code == 400:
            body = resp.json()
            error_msg = body.get("error", {}).get("message", "")
            if "credit" in error_msg.lower() or "balance" in error_msg.lower():
                result = alert_api_credits_depleted("Anthropic", error_msg,
                                                     source="alert_missing_conditions")
                return 1 if result.get("sent") else 0
        # 200 = credits OK (will consume minimal tokens, but confirms access)
    except Exception:
        pass
    return 0


def check_email_digest(conn):
    """Alert if email digest hasn't fired in > 3 days."""
    from alert_dispatcher import dispatch_alert
    cur = conn.cursor()
    cur.execute("""
        SELECT MAX(sent_at)::date as last_sent
        FROM notification_log
        WHERE notification_type = 'daily_digest' AND channel = 'gmail'
    """)
    row = cur.fetchone()
    if not row or not row[0]:
        return 0

    last_sent = row[0]
    days_since = (date.today() - last_sent).days
    if days_since > 3:
        result = dispatch_alert(
            alert_type="email_digest_stale",
            title=f"Email Digest Stale ({days_since} days)",
            body=(f"*Email Digest Not Firing*\n\n"
                  f"Last email digest sent: {last_sent} ({days_since} days ago)\n"
                  f"Expected: daily\n\n"
                  f"Check email SMTP configuration and cron schedule."),
            tier="ALERT",
            source="alert_missing_conditions",
            dedupe_scope="global",
        )
        return 1 if result.get("sent") else 0
    return 0


def check_rebalance_staleness(conn):
    """Alert if rebalance data is > 14 days old."""
    from alert_dispatcher import dispatch_alert
    state_dir = PROJECT_ROOT / "data" / "portfolios" / "state"
    yo_path = state_dir / "yaml_advisor_output.json"
    if not yo_path.exists():
        return 0

    try:
        yo = json.loads(yo_path.read_text())
        generated = yo.get("generated_at", "")
        if generated:
            gen_dt = datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
            days = (datetime.now() - gen_dt.replace(tzinfo=None)).days
            if days > 14:
                result = dispatch_alert(
                    alert_type="rebalance_stale",
                    title=f"Rebalance Data Stale ({days} days)",
                    body=(f"*Rebalance Advisor Stale*\n\n"
                          f"Last generated: {generated[:10]} ({days} days ago)\n"
                          f"Requires Anthropic API credits to refresh.\n\n"
                          f"Run: .venv/bin/python scripts/portfolio_yaml_advisor.py"),
                    tier="ALERT",
                    source="alert_missing_conditions",
                    dedupe_scope="global",
                )
                return 1 if result.get("sent") else 0
    except Exception:
        pass
    return 0


def main():
    print(f"[alert_missing_conditions] Starting — {datetime.now().isoformat()}")
    conn = _get_conn()
    try:
        stale_proposals = check_stale_proposals(conn)
        print(f"  Stale proposal alerts: {stale_proposals}")

        api_credits = check_api_credits(conn)
        print(f"  API credit alerts: {api_credits}")

        email = check_email_digest(conn)
        print(f"  Email digest alerts: {email}")

        rebalance = check_rebalance_staleness(conn)
        print(f"  Rebalance staleness alerts: {rebalance}")

        print(f"[alert_missing_conditions] Complete — {datetime.now().isoformat()}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
