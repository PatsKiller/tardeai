"""
weekly_summary_local.py — Weekly portfolio narrative using local LLM
Runs after portfolio_orchestrator.py in the weekly job.
Uses Ollama qwen3:14b → falls back to Claude Sonnet if unavailable.
Sends summary via Telegram.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add scripts to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def load_data():
    """Load portfolio state and performance history."""
    holdings = json.loads((STATE_DIR / "holdings.json").read_text())
    perf = {}
    ph_path = STATE_DIR / "performance_history.json"
    if ph_path.exists():
        perf = json.loads(ph_path.read_text())

    trade_journal = holdings.get("trade_journal", [])
    account_summaries = holdings.get("account_summaries", {})
    totals = holdings.get("portfolio_totals", {})

    return holdings, perf, trade_journal, account_summaries, totals


def build_weekly_prompt(perf, account_summaries, totals, trade_journal):
    """Build the prompt for weekly narrative."""
    periods = perf.get("periods", {})
    accounts = perf.get("accounts", {})

    # Aggregate periods
    p1w = periods.get("1W", {})
    pytd = periods.get("YTD", {})
    p1y = periods.get("1Y", {})

    # Per-account 1W
    acct_lines = []
    for key, label in [
        ("fidelity_401k", "Fidelity 401k"),
        ("schwab_rollover_ira", "Rollover IRA"),
        ("schwab_roth", "Roth IRA"),
        ("schwab_taxable", "Taxable"),
    ]:
        acct = accounts.get(key, {})
        val = acct.get("current_value", account_summaries.get(key, {}).get("total_value", 0))
        w = acct.get("periods", {}).get("1W", {})
        if w and w.get("change_pct") is not None:
            acct_lines.append(
                f"- {label}: ${val:,.0f} | 1W {w['change_pct']:+.2f}% (${w['change']:+,.0f})"
            )
        else:
            acct_lines.append(f"- {label}: ${val:,.0f} | 1W n/a")

    # Cash
    cash_syms = {"CASH", "--", "SNSXX", "SWVXX"}
    cash_total = sum(
        h.get("market_value", 0) or 0
        for h in holdings_global.get("holdings", [])
        if h.get("symbol") in cash_syms
    )

    # This week's trades from journal
    today = datetime.now()
    week_ago = (today.replace(hour=0, minute=0, second=0)
                .strftime("%Y-%m-%d"))
    week_txns = [
        t for t in trade_journal
        if t.get("date", "") >= week_ago
        and t.get("action", "").lower() in ["buy", "sell"]
    ]
    txn_summary = f"{len(week_txns)} buy/sell transactions this week" if week_txns else "No buy/sell transactions this week"

    prompt = f"""You are a portfolio analyst writing a weekly summary for John.
Be direct, concise, and use plain language. 3-4 sentences max.

PORTFOLIO DATA — Week ending {today.strftime('%B %d, %Y')}:
Total: ${totals.get('total_value', 0):,.0f}
1W: {p1w.get('change_pct', 0):+.2f}% (${p1w.get('change', 0):+,.0f})
YTD: {pytd.get('change_pct', 0):+.2f}% (${pytd.get('change', 0):+,.0f})
1Y: {p1y.get('change_pct', 0):+.2f}% (${p1y.get('change', 0):+,.0f})

BY ACCOUNT:
{chr(10).join(acct_lines)}

Cash on hand: ${cash_total:,.0f}
Activity: {txn_summary}

Write a 3-4 sentence weekly summary. Note the best and worst performing account.
Mention YTD context. Flag if cash is unusually high (>5% of portfolio)."""

    return prompt


def send_telegram(message: str):
    """Send message via Telegram."""
    import urllib.request
    import urllib.parse

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        # Try reading from .env
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    bot_token = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat_id = line.split("=", 1)[1].strip().strip('"')

    if not bot_token or not chat_id:
        print("  [weekly-summary] No Telegram credentials — printing only")
        print(message)
        return

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            print("  [weekly-summary] Telegram sent OK")
    except Exception as e:
        print(f"  [weekly-summary] Telegram error: {e}")


# Global for use in prompt builder
holdings_global = {}


def main():
    global holdings_global
    print("[weekly-summary] Starting local LLM weekly summary...")

    holdings, perf, trade_journal, account_summaries, totals = load_data()
    holdings_global = holdings

    if not perf.get("periods"):
        print("  [weekly-summary] No performance data — skipping")
        return

    # Build prompt
    prompt = build_weekly_prompt(perf, account_summaries, totals, trade_journal)

    # Generate with local LLM + fallback
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    # local_llm.py lives in scripts/
    script_dir = PROJECT_ROOT / "scripts"
    sys.path.insert(0, str(script_dir))

    try:
        from local_llm import generate
    except ImportError:
        # Try project root
        sys.path.insert(0, str(PROJECT_ROOT))
        from local_llm import generate

    summary = generate(prompt, timeout=120, fallback=True)

    if not summary:
        print("  [weekly-summary] No summary generated")
        return

    # Format for Telegram
    today = datetime.now().strftime("%B %d, %Y")
    periods = perf.get("periods", {})
    p1w = periods.get("1W", {})
    pytd = periods.get("YTD", {})

    message = (
        f"📊 <b>Weekly Portfolio Summary — {today}</b>\n\n"
        f"<b>${totals.get('total_value', 0):,.0f}</b> | "
        f"1W: {p1w.get('change_pct', 0):+.2f}% | "
        f"YTD: {pytd.get('change_pct', 0):+.2f}%\n\n"
        f"{summary}"
    )

    print(f"\n{message}\n")
    send_telegram(message)
    print("[weekly-summary] Done.")


if __name__ == "__main__":
    main()
