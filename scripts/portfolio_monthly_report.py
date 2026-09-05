"""
portfolio_monthly_report.py — Monthly portfolio intelligence report
Version: 1.0 | April 17, 2026

Runs 1st of month via linux_launchers/run_portfolio_monthly.sh
Uses OAuth LLM via llm_lane (Grok → ChatGPT → local) for deep multi-section analysis
Reads last 4 weekly JSONs + all state files for comprehensive context

Sections:
  1. Executive summary with 4-week trend analysis
  2. Per-account performance vs benchmarks
  3. Month-over-month changes (what changed)
  4. Top analyst calls (Finviz consensus)
  5. Rebalancing priority
  6. Roth conversion progress
  7. Golden Window countdown
  8. Action plan for next month

Outputs: HTML + DOCX + JSON + Telegram (summary + DOCX attachment)
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
WEEKLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "weekly"
MONTHLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "monthly"
MONTHLY_DIR.mkdir(parents=True, exist_ok=True)

# Benchmark returns (approximate monthly, for context only)
BENCHMARKS = {
    "S&P 500": {"1M": -5.2, "YTD": -8.1, "1Y": 10.5},
    "60/40 Portfolio": {"1M": -3.1, "YTD": -4.8, "1Y": 7.2},
}


def _get_env(key: str) -> str:
    """Get env var from environment or .env file."""
    val = os.getenv(key, "")
    if val:
        return val
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def _load_state(filename: str) -> dict:
    """Load a state file safely."""
    try:
        p = STATE_DIR / filename
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def _load_weekly_reports(n: int = 4) -> List[Dict]:
    """Load last N weekly JSON reports for synthesis."""
    if not WEEKLY_DIR.exists():
        return []
    reports = sorted(WEEKLY_DIR.glob("weekly_*.json"))[-n:]
    result = []
    for r in reports:
        try:
            result.append(json.loads(r.read_text()))
        except Exception:
            pass
    return result


def _clean_narrative(text: str) -> str:
    """Strip surviving markdown artifacts from LLM output."""
    import re
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'^#{1,4}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _oauth_llm(prompt: str, *, task_summary: str, timeout: int = 120) -> str:
    """OAuth narrative via portfolio_report_llm (Grok → ChatGPT → local)."""
    from portfolio_report_llm import PROCESS_MONTHLY, generate_oauth_narrative
    out = generate_oauth_narrative(
        prompt, process_id=PROCESS_MONTHLY, task_summary=task_summary, timeout=timeout,
    )
    return _clean_narrative(out) if out else "[Report LLM unavailable]"


def _send_telegram(message: str) -> None:
    """Send Telegram message via the shared chokepoint (captures to Reports portal)."""
    from telegram_alert import send_telegram
    ok = send_telegram(message, bypass_router=True)
    try:
        from lib.comms import CommunicationEvent, publish_communication
        publish_communication(CommunicationEvent(
            direction="OUTBOUND", event_type="alert", message_class="report",
            producer="portfolio_monthly_report", subject_key="ops:monthly_report",
            retention_class="operational", severity="info",
            sanitized_body=message[:500], short_summary=message[:120],
        ))
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass
    if ok:
        print("  [monthly-report] Telegram sent")
    else:
        print("  [monthly-report] Telegram not sent")


def _send_telegram_doc(doc_path: Path, caption: str = "") -> None:
    """Send DOCX via telegram_alert.send_telegram_document chokepoint."""
    if not doc_path.exists():
        print(f"  [monthly-report] DOCX not found: {doc_path}")
        return
    note = caption or f"Monthly portfolio DOCX ready: {doc_path.name}"
    try:
        from telegram_alert import send_telegram_document
        ok = bool(send_telegram_document(str(doc_path), caption=note, bypass_router=True))
        print("  [monthly-report] Telegram document sent" if ok else "  [monthly-report] Telegram document not sent")
    except Exception as e:
        print(f"  [monthly-report] Telegram document error: {type(e).__name__}: {str(e)[:120]}")
        return
    try:
        from lib.comms import CommunicationEvent, publish_communication
        publish_communication(CommunicationEvent(
            direction="OUTBOUND", event_type="alert", message_class="report",
            producer="portfolio_monthly_report", subject_key="ops:monthly_report",
            retention_class="operational", severity="info",
            sanitized_body=note[:500], short_summary=note[:120],
        ))
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def _build_weekly_context(weeklies: List[Dict]) -> str:
    """Build rich context string from weekly reports for Sonnet prompts."""
    if not weeklies:
        return "No weekly reports available yet."
    lines = []
    for w in weeklies:
        date = w.get("date", "?")
        total = w.get("total_value", 0)
        w1 = w.get("1w_change_pct", 0) or 0
        ytd = w.get("ytd_change_pct", 0) or 0
        cash = w.get("cash_pct", 0) or 0
        beta = w.get("beta", 0) or 0
        ob = w.get("overbought", [])
        os_ = w.get("oversold", [])
        rebal = w.get("rebal_total", 0) or 0
        j_pnl = w.get("journal_pnl", 0) or 0

        lines.append(
            f"Week {date}: ${total:,.0f} | 1W {w1:+.2f}% | YTD {ytd:+.2f}% | "
            f"Cash {cash:.1f}% | Beta {beta:.3f} | Rebal ${rebal:,.0f} | "
            f"Journal P&L ${j_pnl:+,.2f}"
        )

        # Account breakdown
        accts = w.get("accounts", {})
        if accts:
            acct_parts = []
            for name, ad in accts.items():
                val = ad.get("value", 0) or 0
                chg = ad.get("change_pct")
                chg_s = f"{chg:+.2f}%" if chg is not None else "n/a"
                acct_parts.append(f"{name} ${val:,.0f} ({chg_s})")
            lines.append(f"  Accounts: {' | '.join(acct_parts)}")

        # Overbought/oversold
        if ob or os_:
            lines.append(f"  Technical: OB={ob[:3]} OS={os_[:3]}")

        # Narratives (abbreviated)
        narr = w.get("narratives", {})
        if narr.get("performance"):
            lines.append(f"  AI: {narr['performance'][:150]}")
        if narr.get("action"):
            lines.append(f"  Action: {narr['action'][:120]}")

    return "\n".join(lines)


def _build_analyst_context(weeklies: List[Dict]) -> str:
    """Extract analyst intelligence from weekly JSONs."""
    # Use the most recent weekly that has analyst data
    for w in reversed(weeklies):
        positions = w.get("analyst_positions", [])
        if positions:
            lines = []
            for p in positions[:10]:
                sym = p.get("symbol", "")
                rating = p.get("analyst_rating", "—")
                score = p.get("recom_score")
                score_s = f"{score:.1f}" if score else "—"
                rsi = p.get("rsi")
                rsi_s = f"{rsi:.0f}" if rsi else "—"
                inst = p.get("inst_trans_pct")
                inst_s = f"{inst:+.1f}%" if inst else "—"
                port = p.get("portfolio_pct", 0) or 0
                lines.append(
                    f"  {sym}: {rating} ({score_s}/5) RSI={rsi_s} "
                    f"InstFlow={inst_s} Port={port:.1f}%"
                )
            return "\n".join(lines)
    return "No analyst data available in recent weeklies."


def _build_rebal_context(weeklies: List[Dict]) -> str:
    """Extract rebalancing rationale from most recent weekly."""
    for w in reversed(weeklies):
        rationale = w.get("rebal_rationale", [])
        if rationale:
            lines = []
            for r in rationale[:6]:
                sym = r.get("symbol", "")
                action = r.get("action", "")
                amount = r.get("amount", 0)
                reasons = r.get("reasons", [])
                lines.append(
                    f"  {action} {sym} ${abs(amount):,.0f} — "
                    f"{'; '.join(reasons[:2])}"
                )
            return "\n".join(lines)
    return "No rebalancing orders in recent weeklies."


def _generate_monthly_sections(weeklies: List[Dict], holdings: Dict,
                                perf: Dict, risk: Dict, dividends: Dict,
                                retirement: Dict, enrichment: Dict) -> Dict:
    """Generate all 8 monthly report sections using OAuth LLM."""
    from portfolio_report_llm import (
        build_grounding,
        build_monthly_action_prompt,
        sanitize_action_text,
    )

    weekly_context = _build_weekly_context(weeklies)
    analyst_context = _build_analyst_context(weeklies)
    rebal_context = _build_rebal_context(weeklies)
    rebal_rationale = []
    for w in reversed(weeklies):
        rebal_rationale = w.get("rebal_rationale") or []
        if rebal_rationale:
            break
    grounding = build_grounding(holdings, enrichment, risk, rebal_rationale)

    totals = holdings.get("portfolio_totals", {})
    total_val = totals.get("total_value", 0) or 0
    periods = perf.get("periods", {})
    accounts = perf.get("accounts", {})
    p1m = periods.get("1M", {})
    pytd = periods.get("YTD", {})
    p1y = periods.get("1Y", {})
    month_name = datetime.now().strftime("%B %Y")

    # Account summaries
    ACCT_LABELS = {
        "fidelity_401k": "Fidelity 401k",
        "schwab_rollover_ira": "Rollover IRA",
        "schwab_roth": "Roth IRA",
        "schwab_taxable": "Taxable",
    }
    acct_lines = ""
    for key, label in ACCT_LABELS.items():
        ad = accounts.get(key, {}) or {}
        ap = ad.get("periods", {}) or {}
        val = ad.get("current_value", 0) or 0
        a1m = ap.get("1M") or {}
        aytd = ap.get("YTD") or {}
        a1y = ap.get("1Y") or {}
        acct_lines += (
            f"  {label}: ${val:,.0f} | "
            f"1M {a1m.get('change_pct', 0) or 0:+.2f}% | "
            f"YTD {aytd.get('change_pct', 0) or 0:+.2f}% | "
            f"1Y {a1y.get('change_pct', 0) or 0:+.2f}%\n"
        )

    # Cash analysis
    CASH_SYMS = {"CASH", "--", "SNSXX", "SWVXX", "SPRXX", "VMFXX", "FDRXX"}
    cash_total = sum(
        h.get("market_value", 0) or 0
        for h in holdings.get("holdings", [])
        if h.get("symbol") in CASH_SYMS
    )
    cash_pct = (cash_total / total_val * 100) if total_val else 0

    # Retirement/Golden Window data
    key_dates = retirement.get("key_dates", {})
    roth_acct = retirement.get("accounts", {})
    loan = retirement.get("loan", {})

    # Dividend data
    annual_div = dividends.get("total_annual", 0) or 0

    # Risk data — compute weighted beta from enrichment (with coverage disclosure)
    rebal_total = grounding.rebal_total or risk.get("total_to_rebalance", 0) or 0
    _non_cash = [h for h in holdings.get("holdings", [])
                 if h.get("market_value", 0) > 0
                 and h.get("symbol") not in CASH_SYMS]
    _beta_w, _beta_sum_w, _beta_count = 0.0, 0.0, 0
    for _h in _non_cash:
        _b = enrichment.get(_h.get("symbol", ""), {}).get("beta") if isinstance(enrichment.get(_h.get("symbol", "")), dict) else None
        if _b and not isinstance(_b, str):
            try:
                _bf = float(_b)
                _beta_w += _bf * (_h.get("market_value", 0) or 0)
                _beta_sum_w += (_h.get("market_value", 0) or 0)
                _beta_count += 1
            except (ValueError, TypeError):
                pass
    beta = (_beta_w / _beta_sum_w) if _beta_sum_w > 0 else 0.0
    beta_coverage = f"{_beta_count}/{len(_non_cash)} positions"
    _total_non_cash_mv = sum(h.get("market_value", 0) or 0 for h in _non_cash)
    beta_coverage_pct = round(_beta_sum_w / _total_non_cash_mv * 100) if _total_non_cash_mv > 0 else 0

    narratives = {}

    # ── SECTION 1: Executive Summary ────────────────────────────────────────
    print("  [monthly-report] Section 1/8: Executive Summary...")
    prompt1 = f"""You are a senior wealth manager writing the executive summary for John W. Whiting's {month_name} portfolio report.

{grounding.positions_table}

INVESTOR PROFILE:
- Age 58 (turns 59 Aug 2026) | SSDI $45,600/yr only | Conservative risk target (beta <0.5)
- "AI WWIII defense portfolio" thesis for taxable account
- Roth conversion in progress ($35K done 2026, target zero Traditional IRA by RMD age 73)
- Annual dividends: ${annual_div:,.0f}/yr (target $28,000-$34,000/yr)

WEEKLY PERFORMANCE TREND (last 4 weeks):
{weekly_context}

CURRENT STATE:
Total: ${total_val:,.0f}
1M: {p1m.get('change_pct', 0) or 0:+.2f}% (${p1m.get('change', 0) or 0:+,.0f})
YTD: {pytd.get('change_pct', 0) or 0:+.2f}% (${pytd.get('change', 0) or 0:+,.0f})
1Y: {p1y.get('change_pct', 0) or 0:+.2f}% (${p1y.get('change', 0) or 0:+,.0f})
Beta: {beta:.3f} ({beta_coverage}, {beta_coverage_pct}% MV coverage) | Cash: {cash_pct:.1f}% (${cash_total:,.0f})
Rebalancing needed: ${rebal_total:,.0f}

BENCHMARKS (approximate):
S&P 500: 1M {BENCHMARKS['S&P 500']['1M']:+.1f}% | YTD {BENCHMARKS['S&P 500']['YTD']:+.1f}%
60/40: 1M {BENCHMARKS['60/40 Portfolio']['1M']:+.1f}% | YTD {BENCHMARKS['60/40 Portfolio']['YTD']:+.1f}%

Write a 5-6 sentence executive summary. Cover:
1. Monthly performance vs prior month trend (improving/deteriorating/stable)
2. How John's portfolio performed vs benchmarks
3. What drove the results (specific positions/sectors)
4. Key risk observation
5. One-sentence outlook for next month
Be direct, use real numbers. No generic disclaimers. No "Data unavailable"."""

    narratives["executive_summary"] = _oauth_llm(prompt1, task_summary="monthly executive summary")

    # ── SECTION 2: Per-Account Performance vs Benchmarks ────────────────────
    print("  [monthly-report] Section 2/8: Account Performance...")
    prompt2 = f"""Analyze per-account performance for John W. Whiting's portfolio in {month_name}.

ACCOUNT PERFORMANCE:
{acct_lines}

BENCHMARKS (approximate monthly):
S&P 500: 1M {BENCHMARKS['S&P 500']['1M']:+.1f}% | YTD {BENCHMARKS['S&P 500']['YTD']:+.1f}% | 1Y {BENCHMARKS['S&P 500']['1Y']:+.1f}%
60/40: 1M {BENCHMARKS['60/40 Portfolio']['1M']:+.1f}% | YTD {BENCHMARKS['60/40 Portfolio']['YTD']:+.1f}% | 1Y {BENCHMARKS['60/40 Portfolio']['1Y']:+.1f}%

CONTEXT:
- Fidelity 401k: Omnicom proprietary funds (OIGAX, OIFMX, OEMIX) — rolling to Schwab 2027. No Yahoo price history = 0/7 periods. This is known/expected.
- Rollover IRA: SCHD-heavy, conservative income strategy
- Roth IRA: Growth positions, $35K converted 2026 (target $42K+)
- Taxable: AI WWIII defense thesis (RTX, LMT, V, IRDM etc.)

Write 4-5 sentences analyzing each account:
1. Which account outperformed/underperformed benchmarks and by how much
2. Is the Rollover IRA (largest at ~$550K) pulling its weight?
3. Is the Taxable defense thesis working?
4. Roth growth trajectory
Note: Skip Fidelity 401k period returns (proprietary funds, no price data). Report its value only."""

    narratives["account_performance"] = _oauth_llm(prompt2, task_summary="monthly account performance")

    # ── SECTION 3: Month-Over-Month Changes ─────────────────────────────────
    print("  [monthly-report] Section 3/8: Month-Over-Month Changes...")
    # Compare first and last weekly for MoM delta
    first_w = weeklies[0] if weeklies else {}
    last_w = weeklies[-1] if weeklies else {}
    mom_delta = (last_w.get("total_value", 0) or 0) - (first_w.get("total_value", 0) or 0)

    prompt3 = f"""What changed month-over-month in John W. Whiting's portfolio ({month_name})?

START OF MONTH:
  Total: ${first_w.get('total_value', 0):,.0f} | YTD: {first_w.get('ytd_change_pct', 0) or 0:+.2f}%
  Cash: {first_w.get('cash_pct', 0) or 0:.1f}% | Beta: {first_w.get('beta', 0) or 0:.3f}
  Overbought: {first_w.get('overbought', [])} | Oversold: {first_w.get('oversold', [])}

END OF MONTH:
  Total: ${last_w.get('total_value', 0):,.0f} | YTD: {last_w.get('ytd_change_pct', 0) or 0:+.2f}%
  Cash: {last_w.get('cash_pct', 0) or 0:.1f}% | Beta: {last_w.get('beta', 0) or 0:.3f}
  Overbought: {last_w.get('overbought', [])} | Oversold: {last_w.get('oversold', [])}

NET CHANGE: ${mom_delta:+,.0f}

WEEKLY TREND:
{weekly_context}

Write 3-4 sentences on what specifically changed:
1. Dollar and percentage portfolio change
2. Which positions moved from one technical state to another (overbought→neutral, etc.)
3. Cash deployment or accumulation
4. Any new risks that appeared this month
Be specific. Name tickers. Use numbers."""

    narratives["month_over_month"] = _oauth_llm(prompt3, task_summary="monthly MoM changes")

    # ── SECTION 4: Top Analyst Calls ────────────────────────────────────────
    print("  [monthly-report] Section 4/8: Analyst Intelligence...")
    prompt4 = f"""Analyze Finviz Elite consensus analyst ratings for John W. Whiting's top holdings.

ANALYST DATA (source: Finviz Elite consensus, 1=Strong Buy → 5=Strong Sell):
{analyst_context}

REBALANCING ORDERS WITH RATIONALE:
{rebal_context}

CONTEXT: John is 58, conservative, SSDI income only. His taxable account runs an "AI WWIII defense" thesis (defense contractors + critical infrastructure). He needs holdings that are both analytically sound AND thesis-consistent.

Write 4-5 sentences covering:
1. Top 3 positions with strongest analyst support (score <2.0) — why they're consensus favorites
2. Any positions with concerning ratings (score >3.5) — what analysts are worried about
3. Institutional flow signals — who's buying/selling and what it means
4. One contrarian opportunity where John's thesis may override consensus
Cite "Finviz Elite consensus" as source. Never fabricate analyst firm names."""

    narratives["analyst_calls"] = _oauth_llm(prompt4, task_summary="monthly analyst calls")

    # ── SECTION 5: Rebalancing Priority ─────────────────────────────────────
    print("  [monthly-report] Section 5/8: Rebalancing Priority...")
    # Get position concentrations
    top_positions = sorted(
        [h for h in holdings.get("holdings", [])
         if h.get("symbol") not in CASH_SYMS and h.get("market_value", 0) > 0],
        key=lambda x: x.get("market_value", 0), reverse=True
    )[:10]
    position_lines = ""
    for p in top_positions:
        sym = p.get("symbol", "")
        mv = p.get("market_value", 0) or 0
        pct = p.get("portfolio_pct", 0) or 0
        gain = p.get("gain_loss_pct")
        gain_s = f"{gain:+.1f}%" if gain is not None else "n/a"
        position_lines += f"  {sym}: ${mv:,.0f} ({pct:.1f}%) gain={gain_s}\n"

    prompt5 = f"""Rebalancing priority for John W. Whiting's portfolio in {month_name}.

TOP 10 POSITIONS BY SIZE:
{position_lines}

CURRENT REBALANCING ORDERS:
{rebal_context}

CONSTRAINTS:
- Total rebalancing needed: ${rebal_total:,.0f}
- Cash available: ${cash_total:,.0f} ({cash_pct:.1f}%)
- V (Visa) concentration threshold: 15% (currently ~12.5%)
- Target beta: <0.5 (current: {beta:.3f})
- SSDI income — cannot afford large tax hits from selling appreciated positions
- Roth conversion $35K done this year — watch tax bracket impact of realized gains

Write 3-4 sentences:
1. Is rebalancing urgent or can it wait? Why?
2. What's the single highest-priority rebalancing action this month?
3. Tax-aware sequencing — what to sell/buy in which account to minimize tax impact
4. Any position approaching dangerous concentration (>15%)?
Be specific. Name tickers and dollar amounts."""

    narratives["rebalancing"] = _oauth_llm(prompt5, task_summary="monthly rebalancing priority")

    # ── SECTION 6: Roth Conversion Progress ─────────────────────────────────
    print("  [monthly-report] Section 6/8: Roth Conversion...")
    trad_val = roth_acct.get("traditional", 0) or 0
    roth_val = roth_acct.get("roth", 0) or 0
    roth_pct = roth_acct.get("roth_pct", 0) or 0

    prompt6 = f"""Roth conversion progress report for John W. Whiting — {month_name}.

CONVERSION STATUS:
- 2026 conversions done: $35,000
- Sweet spot options: $25K/yr (~$3,547 tax) OR $50K/yr (~$15,027 tax)
- Current Traditional IRA balance: ${trad_val:,.0f}
- Current Roth IRA balance: ${roth_val:,.0f}
- Roth % of total: {roth_pct:.1f}%
- Target: Zero Traditional IRA by RMD age 73 (2040)
- Years remaining: ~14 years

TAX CONTEXT:
- Filing: MFS (married filing separately, lived apart)
- SSDI: $45,600/yr (partially taxable at this income)
- Private disability: continues to age 68.5
- Golden Window (ages 68.5-73): lowest bracket for large conversions
- Current marginal bracket: 22% (with $35K conversion)

PORTFOLIO CONTEXT:
- YTD performance: {pytd.get('change_pct', 0) or 0:+.2f}%
- Market down → conversions are TAX-EFFICIENT (convert more shares at lower values)

Write 3-4 sentences:
1. Is John on track for the year? Should he convert more before Dec 31?
2. Tax bracket analysis — room for more conversion without jumping brackets?
3. Market timing insight — is the current drawdown an opportunity to convert more?
4. What's the optimal conversion amount for remainder of 2026?
Be specific with numbers. This is critical financial planning."""

    narratives["roth_conversion"] = _oauth_llm(prompt6, task_summary="monthly Roth conversion")

    # ── SECTION 7: Golden Window Countdown ──────────────────────────────────
    print("  [monthly-report] Section 7/8: Golden Window Countdown...")
    days_to_golden = key_dates.get("days_to_golden", 0)
    years_to_golden = key_dates.get("years_to_golden", 0)
    golden_start = key_dates.get("golden_window_start", "2036-02-19")
    golden_end = key_dates.get("golden_window_end", "2040-08-20")
    loan_balance = loan.get("balance", 0) or 0
    loan_deadline = loan.get("deadline", "2027-12-31")
    loan_monthly = loan.get("monthly_to_payoff", 0) or 0

    prompt7 = f"""Golden Window retirement countdown for John W. Whiting — {month_name}.

GOLDEN WINDOW: {golden_start} to {golden_end} (ages 68.5 to 73)
  - Private disability income STOPS at 68.5
  - RMDs BEGIN at 73
  - Window = lowest tax bracket for massive Roth conversions
  - Days until Golden Window: {days_to_golden} ({years_to_golden:.1f} years)

CURRENT STATE:
  - Age: 58.7
  - Traditional IRA: ${trad_val:,.0f} (must be $0 by window end)
  - Roth IRA: ${roth_val:,.0f}
  - 401k loan: ${loan_balance:,.0f} (payoff deadline: {loan_deadline}, ${loan_monthly:,.0f}/mo)
  - Annual dividends: ${annual_div:,.0f}/yr (target $28K-$34K for income replacement)
  - Portfolio total: ${total_val:,.0f}

MILESTONES AHEAD:
  - Age 59 (Aug 2026): No early withdrawal penalty
  - Omnicom 401k → Rollover IRA: planned 2027
  - Age 62: SS early claiming option (won't use — SSDI converts at FRA 67)
  - Loan payoff deadline: {loan_deadline}

Write 3-4 sentences:
1. Progress check — is John on track to zero the Traditional IRA by the Golden Window?
2. Pre-Golden preparation — what should he be doing NOW to maximize the window?
3. Loan status — on track for payoff?
4. Income replacement readiness — will dividends + SS cover expenses by 68.5?
Be specific and encouraging. This is John's North Star."""

    narratives["golden_window"] = _oauth_llm(prompt7, task_summary="monthly golden window")

    # ── SECTION 8: Action Plan ──────────────────────────────────────────────
    print("  [monthly-report] Section 8/8: Action Plan...")
    # Get last month's action if available
    prev_monthly = sorted(MONTHLY_DIR.glob("monthly_*.json"))
    last_action = ""
    if prev_monthly:
        try:
            prev = json.loads(prev_monthly[-1].read_text())
            last_action = prev.get("narratives", {}).get("action_plan", "")[:200]
        except Exception:
            pass

    action_context = (
        f"- Portfolio: ${total_val:,.0f} | YTD: {pytd.get('change_pct', 0) or 0:+.2f}%\n"
        f"- 1M change: {p1m.get('change_pct', 0) or 0:+.2f}% (${p1m.get('change', 0) or 0:+,.0f})\n"
        f"- Cash: ${cash_total:,.0f} ({cash_pct:.1f}%)\n"
        f"- Rebalancing needed: ${rebal_total:,.0f}\n"
        f"- Roth conversion 2026: $35K done (room for more at 22% bracket)\n"
        f"- 401k loan: ${loan_balance:,.0f} remaining\n"
        f"- Annual dividends: ${annual_div:,.0f} (gap to $28K target: ${max(0, 28000-annual_div):,.0f})\n"
        f"- Beta: {beta:.3f} ({beta_coverage}, {beta_coverage_pct}% MV coverage; target <0.5)\n"
        f"- Weekly trend: {weekly_context[:400]}"
    )
    prompt8 = build_monthly_action_prompt(
        grounding, last_action=last_action, context_lines=action_context,
    )
    raw_action = _oauth_llm(prompt8, task_summary="monthly action plan", timeout=150)
    narratives["action_plan"] = sanitize_action_text(raw_action, grounding, monthly=True)

    return narratives


def _sc(v):
    """Sign color helper."""
    return "var(--up)" if v is not None and v >= 0 else "var(--dn)" if v is not None else "var(--text3)"

def _sd(v):
    """Signed dollar helper."""
    if v is None: return "n/a"
    return f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"

def _sp(v):
    """Signed percent helper."""
    return f"{v:+.2f}%" if v is not None else "n/a"

def _sigc(s):
    """Signal color helper."""
    return {"EXIT":"var(--dn)","TRIM":"#ff7043","WATCH":"var(--warn)","MONITOR":"var(--text3)","ADD":"var(--up)","HOLD":"var(--text2)"}.get(s,"var(--text)")


def _generate_html(date_str: str, weeklies: List[Dict], holdings: Dict,
                   perf: Dict, narratives: Dict, signals_data: Dict,
                   mtd_data: Dict, retirement: Dict, dividends: Dict,
                   enrichment: Dict, gw_note: str) -> str:
    """Generate monthly HTML with Commander's Summary + restructured legacy sections."""
    import re as _re
    totals = holdings.get("portfolio_totals", {})
    total_val = totals.get("total_value", 0) or 0
    periods = perf.get("periods", {})
    p1m = periods.get("1M") or {}
    pytd = periods.get("YTD") or {}
    month_name = datetime.now().strftime("%B %Y")
    annual_div = dividends.get("total_annual", 0) or 0
    golden_days = retirement.get("key_dates", {}).get("days_to_golden", 0)

    # Beta (weighted from enrichment + overrides)
    CASH_S = {"CASH","--","SNSXX","SWVXX","SPRXX","VMFXX","FDRXX"}
    hlds = [h for h in holdings.get("holdings",[]) if (h.get("market_value",0) or 0) > 0 and h.get("symbol") not in CASH_S]
    bw, bsw, bc = 0.0, 0.0, 0
    for h in hlds:
        b = (enrichment.get(h.get("symbol","")) or {}).get("beta")
        if b and not isinstance(b, str):
            try: bw += float(b)*(h.get("market_value",0) or 0); bsw += (h.get("market_value",0) or 0); bc += 1
            except: pass
    beta_val = bw/bsw if bsw > 0 else 0

    # Account breakdown
    acct_data = perf.get("accounts", {})
    AL = {"fidelity_401k":"Fidelity 401k","schwab_rollover_ira":"Rollover IRA","schwab_roth":"Roth IRA","schwab_taxable":"Taxable"}
    acct_lines = []
    for key, label in AL.items():
        ad = (acct_data.get(key) or {}); ap = (ad.get("periods") or {}); a1m = ap.get("1M") or {}
        acct_lines.append({"label": label, "change": a1m.get("change"), "pct": a1m.get("change_pct")})
    acct_lines.sort(key=lambda a: a.get("change") or 0, reverse=True)

    # Signals
    sigs = signals_data.get("signals", [])
    actionable = [s for s in sigs if s.get("signal") not in ("HOLD",)]
    hold_thesis = [s for s in sigs if s.get("signal") == "HOLD" and "R7" in s.get("rule","")]
    hold_other = [s for s in sigs if s.get("signal") == "HOLD" and "R7" not in s.get("rule","")]

    # MTD attribution
    mtd_tl = mtd_data.get("top_line", {})
    mtd_cov = mtd_data.get("coverage", {})
    mtd_attr = mtd_data.get("attribution", [])
    top_pos = mtd_attr[-5:][::-1]

    # Negative contributors column
    neg_covered = [r for r in mtd_attr if r.get("mtd_dollar_change",0) < 0]
    neg_rows = ""
    if neg_covered:
        for r in neg_covered[:5]:
            neg_rows += f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:11px"><span><b style="color:var(--accent2)">{r["symbol"]}</b> <span style="color:var(--text3)">{r.get("account","")[:12]}</span></span><span style="color:var(--dn)">{_sd(r["mtd_dollar_change"])} ({r.get("perf_month_pct",0):+.1f}%)</span></div>'
    else:
        fid_res = mtd_data.get("fidelity_401k_residual", 0)
        neg_rows += f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:11px"><span style="color:var(--text2)">Fidelity 401k (aggregate)</span><span style="color:var(--dn)">{_sd(fid_res)}</span></div>'
        neg_rows += '<div style="font-size:9px;color:var(--text3);margin-top:4px">Position-level attribution unavailable for proprietary funds</div>'

    # Positive contributors
    pos_rows = ""
    for r in top_pos:
        pos_rows += f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:11px"><span><b style="color:var(--accent2)">{r["symbol"]}</b> <span style="color:var(--text3)">{r.get("account","")[:12]}</span></span><span style="color:var(--up)">{_sd(r.get("mtd_dollar_change",0))} ({r.get("perf_month_pct",0):+.1f}%)</span></div>'

    # Signal table rows
    sig_rows = ""
    for s in actionable:
        sig_rows += f'<tr style="border-bottom:1px solid rgba(255,255,255,.04)"><td style="padding:5px 6px;white-space:nowrap"><span style="color:{_sigc(s["signal"])};font-weight:700">{s["signal"]}</span></td><td style="padding:5px 6px;color:var(--accent2);font-weight:700;white-space:nowrap">{s["symbol"]}</td><td style="padding:5px 6px;color:var(--text2);white-space:nowrap">{s["rule"]}</td><td style="padding:5px 6px;color:var(--text2);word-wrap:break-word;max-width:350px">{s.get("note","")}</td><td style="padding:5px 6px;color:var(--text3);font-size:10px">{s.get("accounts_context","")[:60]}</td></tr>'

    # Account grid
    acct_grid = ""
    for a in acct_lines:
        acct_grid += f'<div style="padding:6px 8px;background:rgba(255,255,255,.03);border-radius:6px"><div style="font-size:9px;color:var(--text3)">{a["label"]}</div><div style="font-size:12px;font-weight:700;color:{_sc(a["change"])}">{_sd(a["change"]) if a["change"] is not None else "n/a"}</div><div style="font-size:9px;color:var(--text3)">{_sp(a["pct"]) if a["pct"] is not None else "no data"}</div></div>'

    # Rebalancing from signals
    rebal_sigs = [s for s in sigs if s.get("signal") in ("TRIM","EXIT")]
    rebal_html = ""
    for s in rebal_sigs:
        col = _sigc(s["signal"])
        rebal_html += f'<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:12px"><b style="color:{col}">{s["signal"]}</b> <b style="color:var(--accent2)">{s["symbol"]}</b> <span style="color:var(--text2)"> &mdash; {s.get("note","")}</span></div>'
    if not rebal_html:
        rebal_html = '<div style="font-size:11px;color:var(--text3)">No concentration or trim signals active.</div>'

    # Weekly rows
    weekly_rows = ""
    for w in weeklies:
        wc = w.get("1w_change_pct", 0) or 0
        color = "#00e676" if wc >= 0 else "#ff5252"
        accts = w.get("accounts", {}); top_acct = ""
        if accts:
            best = max(accts.items(), key=lambda x: x[1].get("change_pct") or -999)
            if best[1].get("change_pct") is not None: top_acct = f'{best[0]} {best[1]["change_pct"]:+.1f}%'
        weekly_rows += f'<tr><td>{w.get("date","?")}</td><td>${w.get("total_value",0):,.0f}</td><td style="color:{color}">{wc:+.2f}%</td><td>{w.get("ytd_change_pct",0) or 0:+.2f}%</td><td>{w.get("cash_pct",0) or 0:.1f}%</td><td>{top_acct}</td></tr>'

    # Cleaned narratives
    exec_text = _clean_narrative(narratives.get("executive_summary", ""))
    exec_sents = [s.strip() for s in _re.split(r'(?<=[.!?])\s+', exec_text) if s.strip()]
    exec_short = " ".join(exec_sents[:3]) if exec_sents else exec_text[:400]
    acct_text = _clean_narrative(narratives.get("account_performance", ""))
    roth_text = _clean_narrative(narratives.get("roth_conversion", ""))
    golden_text = _clean_narrative(narratives.get("golden_window", ""))

    # Hold details
    hold_detail = " ".join(f'{s["symbol"]} ({s["rule"]})' for s in hold_other)
    thesis_count = len(hold_thesis)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monthly Portfolio Report — {month_name}</title>
<style>
  :root {{ --bg:#0d0d1a;--bg2:#141428;--border:rgba(255,255,255,.08);--text:#e8e8f0;--text2:#b0b0c8;--text3:#7070a0;--up:#00e676;--dn:#ff5252;--warn:#ffd740;--accent:#2979ff;--gold:#ffd700;--accent2:#00b8d4; }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:24px;max-width:960px;margin:0 auto}}
  h1{{font-size:24px;margin-bottom:4px}} h2{{font-size:13px;text-transform:uppercase;letter-spacing:1.2px;color:var(--text3);margin:28px 0 12px}}
  .meta{{font-size:12px;color:var(--text3);margin-bottom:24px}}
  .narrative{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:18px;margin-bottom:16px;font-size:13px;line-height:1.75;color:var(--text2)}}
  .highlight{{background:rgba(41,121,255,.08);border:1px solid rgba(41,121,255,.25);border-radius:10px;padding:18px;margin-bottom:16px;font-size:13px;line-height:1.75}}
  .roth-box{{background:rgba(0,230,118,.06);border:1px solid rgba(0,230,118,.2);border-radius:10px;padding:18px;margin-bottom:16px;font-size:13px;line-height:1.75}}
  .golden-box{{background:rgba(255,215,0,.06);border:1px solid rgba(255,215,0,.25);border-radius:10px;padding:18px;margin-bottom:16px;font-size:13px;line-height:1.75}}
  .section{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:16px}}
  table{{width:100%;border-collapse:collapse;font-size:12px}}
  th{{text-align:left;padding:8px 10px;color:var(--text3);font-weight:400;border-bottom:1px solid var(--border);font-size:10px;text-transform:uppercase}}
  td{{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.04)}}
  .footer{{margin-top:36px;font-size:10px;color:var(--text3);text-align:center}}
</style>
</head>
<body>
<h1>Monthly Portfolio Report</h1>
<div class="meta">{month_name} &middot; Claude Sonnet + rules engine v3 &middot; {len(weeklies)} weekly reports &middot; Trade AI v12</div>

<!-- COMMANDER'S SUMMARY -->
<div style="background:linear-gradient(135deg, rgba(41,121,255,.06), rgba(0,184,212,.04));border:2px solid rgba(41,121,255,.2);border-radius:16px;padding:24px;margin-bottom:32px">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:20px">
    <h1 style="font-size:22px;margin:0;color:var(--text)">COMMANDER'S SUMMARY</h1>
    <span style="font-size:11px;color:var(--text3)">{month_name} &middot; Rules-based signals v3</span>
  </div>
  <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:20px">
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px"><div style="font-size:8px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px">MTD</div><div style="font-size:16px;font-weight:800;color:{_sc(mtd_tl.get('dollar'))}">{_sd(mtd_tl.get('dollar'))}</div><div style="font-size:10px;color:{_sc(mtd_tl.get('pct'))}">{_sp(mtd_tl.get('pct'))}</div></div>
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px"><div style="font-size:8px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px">YTD</div><div style="font-size:16px;font-weight:800;color:{_sc(pytd.get('change'))}">{_sd(pytd.get('change'))}</div><div style="font-size:10px;color:{_sc(pytd.get('change_pct'))}">{_sp(pytd.get('change_pct'))}</div></div>
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px"><div style="font-size:8px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px">PORTFOLIO</div><div style="font-size:16px;font-weight:800;color:var(--text)">${total_val:,.0f}</div><div style="font-size:10px;color:var(--text3)">Total value</div></div>
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px"><div style="font-size:8px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px">DIVIDENDS</div><div style="font-size:16px;font-weight:800;color:var(--gold)">${annual_div:,.0f}<span style="font-size:10px">/yr</span></div><div style="font-size:10px;color:var(--text3)">Target $28K (gap ${max(0,28000-annual_div):,.0f})</div></div>
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px"><div style="font-size:8px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px">GOLDEN WINDOW</div><div style="font-size:16px;font-weight:800;color:var(--gold)">{golden_days:,}<span style="font-size:10px"> days</span></div><div style="font-size:10px;color:var(--text3)">{golden_days/365.25:.1f} years</div></div>
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px"><div style="font-size:8px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px">BETA</div><div style="font-size:16px;font-weight:800;color:{'var(--warn)' if beta_val > 0.5 else 'var(--up)'}">{beta_val:.3f}</div><div style="font-size:10px;color:var(--text3)">{bc}/{len(hlds)} pos, target &lt;0.5</div></div>
  </div>
  <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:14px">
    <div style="font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.7px;margin-bottom:8px">WHY THIS MONTH</div>
    <div style="font-size:14px;font-weight:800;color:{_sc(mtd_tl.get('dollar'))};margin-bottom:6px">{_sd(mtd_tl.get('dollar'))} / {_sp(mtd_tl.get('pct'))}</div>
    <div style="font-size:11px;color:var(--text2);line-height:1.6;margin-bottom:8px">Of this, Finviz-covered Schwab positions contributed <b style="color:var(--up)">{_sd(mtd_data.get('attribution_total',0))}</b> in gains. Fidelity 401k (no position-level data) accounted for <b style="color:var(--dn)">{_sd(mtd_data.get('fidelity_401k_residual',0))}</b>.</div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px">{acct_grid}</div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px">
      <div style="font-size:10px;font-weight:700;color:var(--up);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Top Positive Contributors (Finviz-covered)</div>{pos_rows}
    </div>
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px">
      <div style="font-size:10px;font-weight:700;color:var(--dn);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px">Top Negative Contributors</div>
      <div style="font-size:8px;color:var(--text3);margin-bottom:6px">Covered positions + account-level residuals where attribution unavailable</div>{neg_rows}
    </div>
  </div>
  <div style="font-size:9px;color:var(--text3);margin-bottom:14px;text-align:center">Position-level attribution covers {mtd_cov.get('positions_covered',0)}/{mtd_cov.get('positions_total',0)} holdings, {mtd_cov.get('pct_mv',0)}% of ${total_val/1e6:.2f}M portfolio MV.</div>
  <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:14px">
    <div style="font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.7px;margin-bottom:8px">ACTION SIGNALS</div>
    <table style="width:100%;border-collapse:collapse;font-size:11px">
      <thead><tr style="border-bottom:1px solid var(--border)"><th style="text-align:left;padding:4px 6px;color:var(--text3);font-size:9px;font-weight:400;text-transform:uppercase;white-space:nowrap">Signal</th><th style="text-align:left;padding:4px 6px;color:var(--text3);font-size:9px;font-weight:400;text-transform:uppercase;white-space:nowrap">Ticker</th><th style="text-align:left;padding:4px 6px;color:var(--text3);font-size:9px;font-weight:400;text-transform:uppercase;white-space:nowrap">Rule</th><th style="text-align:left;padding:4px 6px;color:var(--text3);font-size:9px;font-weight:400;text-transform:uppercase">Note</th><th style="text-align:left;padding:4px 6px;color:var(--text3);font-size:9px;font-weight:400;text-transform:uppercase;white-space:nowrap">Accounts</th></tr></thead>
      <tbody>{sig_rows}</tbody>
    </table>
    {f'<div style="font-size:10px;color:var(--text3);margin-top:6px">{thesis_count} thesis HOLD positions (defense + income).</div>' if thesis_count else ''}
    <details style="margin-top:6px"><summary style="font-size:10px;color:var(--text3);cursor:pointer">{len(hold_other)} positions in HOLD status. Expand for details.</summary><div style="margin-top:4px;font-size:10px;color:var(--text3);line-height:1.6">{hold_detail}</div></details>
  </div>
  <div style="background:rgba(255,215,0,.04);border:1px solid rgba(255,215,0,.15);border-radius:8px;padding:10px;margin-bottom:14px;font-size:11px;color:var(--text2);line-height:1.6"><span style="color:var(--gold);font-weight:700">GOLDEN WINDOW:</span> {gw_note}</div>
  <div style="font-size:9px;color:var(--text3);line-height:1.5;border-top:1px solid var(--border);padding-top:10px"><b>Disclosure:</b> These signals are mechanical applications of John W. Whiting's personal rules framework &mdash; concentration limits, technical thresholds, thesis alignment, and stop-loss proximity. They are NOT investment advice. All decisions remain John's. Source data: Finviz Elite consensus, portfolio state files, risk management stops.</div>
</div>

<h2>Executive Summary</h2>
<div class="narrative">{exec_short}</div>

<h2>Weekly Performance Trend</h2>
<div class="section">
  <table>
    <tr><th>Week</th><th>Total</th><th>1W</th><th>YTD</th><th>Cash</th><th>Top Account</th></tr>
    {weekly_rows if weekly_rows else '<tr><td colspan="6" style="color:var(--text3)">No weekly data</td></tr>'}
  </table>
</div>

<h2>Account Performance vs Benchmarks</h2>
<div class="narrative">{acct_text}</div>

<h2>Rebalancing Priority</h2>
<div class="highlight"><div style="font-size:11px;color:var(--text2);line-height:1.7">{rebal_html}</div></div>

<h2>Roth Conversion Progress</h2>
<div class="roth-box">{roth_text}</div>

<h2>Golden Window Countdown</h2>
<div class="golden-box">{golden_text}</div>

<div class="footer">
  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} &middot; Claude Sonnet + Rules Engine v3
  <br>Cost: ~$0.08 (8 Sonnet calls + rules engine)
  <br><a href="/reports/reports_hub.html" style="color:var(--accent)">&larr; Back to Reports Hub</a>
</div>
</body>
</html>'''


def _build_telegram_payload(month_name, date_str, holdings, periods,
                            dividends, retirement, mtd_data, signals_data, gw_note):
    """Build the Telegram HTML payload for Commander's Summary format."""
    totals = holdings.get("portfolio_totals", {})
    total_val = totals.get("total_value", 0) or 0
    _div = dividends.get("total_annual", 0) or 0
    _golden_days = retirement.get("key_dates", {}).get("days_to_golden", 0)
    _mtd_d = mtd_data.get("top_line", {}).get("dollar", 0)
    _mtd_p = mtd_data.get("top_line", {}).get("pct", 0)
    _ytd_d = (periods.get("YTD") or {}).get("change", 0)
    _ytd_p = (periods.get("YTD") or {}).get("change_pct", 0)
    fid_res = mtd_data.get("fidelity_401k_residual", 0)

    tg_actionable = [s for s in signals_data.get("signals", []) if s.get("signal") not in ("HOLD",)]
    _sig_emojis = {"TRIM": "\U0001f53b", "WATCH": "\u26a0\ufe0f", "MONITOR": "\U0001f441", "ADD": "\U0001f7e2", "EXIT": "\U0001f534"}
    tg_sig_lines = ""
    for s in tg_actionable:
        e = _sig_emojis.get(s["signal"], "")
        note = s.get('note', '')
        tg_sig_lines += f"{e} <b>{s['signal']}</b> {s['symbol']} \u2014 {s['rule']}\n   {note}\n"

    tg_mover_lines = ""
    for r in (mtd_data.get("attribution") or [])[-3:][::-1]:
        tg_mover_lines += f"  \u2191 {r['symbol']} {_sd(r.get('mtd_dollar_change',0))} ({r.get('perf_month_pct',0):+.1f}%)\n"
    if fid_res and fid_res < 0:
        tg_mover_lines += f"  \u2193 Fidelity 401k {_sd(fid_res)} (aggregate)\n"

    return (
        f"\U0001f4c8 <b>COMMANDER'S SUMMARY \u2014 {month_name}</b>\n\n"
        f"<code>Portfolio   ${total_val:>12,.0f}\n"
        f"MTD         {_sd(_mtd_d):>12s}  {_sp(_mtd_p)}\n"
        f"YTD         {_sd(_ytd_d):>12s}  {_sp(_ytd_p)}\n"
        f"Dividends   ${_div:>12,.0f}/yr  (gap ${max(0,28000-_div):,.0f})\n"
        f"Golden Win  {_golden_days:>10,} days  ({_golden_days/365.25:.1f}yr)</code>\n\n"
        f"<b>\U0001f4ca WHY THIS MONTH</b>\n"
        f"Portfolio: <b>{_sd(_mtd_d)}</b> ({_sp(_mtd_p)})\n"
        f"Schwab (Finviz-covered): {_sd(mtd_data.get('attribution_total',0))}\n"
        f"Fidelity 401k (account-level): {_sd(fid_res)}\n\n"
        f"<b>\u26a1 ACTION SIGNALS</b>\n"
        f"{tg_sig_lines}\n"
        f"<b>\U0001f3af GOLDEN WINDOW</b>\n{gw_note}\n\n"
        f"<b>\U0001f4cb TOP MOVERS</b>\n{tg_mover_lines}\n"
        f"<i>Signals are mechanical rules, not investment advice.</i>\n\n"
        f"<a href='https://ms01-openclaw.tail163d14.ts.net/reports/monthly/monthly_{date_str}.html'>\U0001f4c4 Full Report</a>"
    )


def run_monthly_report(project_root: str = ".", dry_run: bool = False,
                       output_path: str = None) -> Optional[Path]:
    """Main entry point. Generate comprehensive monthly report.
    dry_run=True: save HTML/Telegram to output_path, skip Telegram send + DOCX.
    """
    global PROJECT_ROOT, STATE_DIR, WEEKLY_DIR, MONTHLY_DIR
    PROJECT_ROOT = Path(project_root)
    STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
    WEEKLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "weekly"
    MONTHLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "monthly"
    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)

    print("[monthly-report] Starting comprehensive monthly portfolio report...")
    date_str = datetime.now().strftime("%Y-%m-%d")
    month_name = datetime.now().strftime("%B %Y")

    # Load weekly reports
    weeklies = _load_weekly_reports(4)
    print(f"[monthly-report] Loaded {len(weeklies)} weekly reports for synthesis")

    # Load all state files
    holdings = _load_state("holdings.json")
    perf = _load_state("performance_history.json")
    risk = _load_state("risk_management.json")
    dividends = _load_state("dividend_calendar.json")
    retirement = _load_state("retirement_roadmap.json")
    enrichment = _load_state("ticker_enrichment_cache.json")

    print(f"[monthly-report] Portfolio: ${holdings.get('portfolio_totals', {}).get('total_value', 0):,.0f}")
    print("[monthly-report] Generating OAuth analysis (8 sections)...")

    # Generate all narrative sections
    narratives = _generate_monthly_sections(
        weeklies, holdings, perf, risk, dividends, retirement, enrichment
    )

    # Generate signals + MTD attribution for Commander's Summary
    try:
        from portfolio_signals import (
            generate_action_signals, compute_position_mtd_pl,
            golden_window_roth_note, compute_coverage_summary
        )
        signals_list = generate_action_signals(holdings, enrichment, risk, retirement, dividends,
                                                _load_state("watchlist.json"))
        signals_data = {
            "signals": [{
                "symbol": s["symbol"], "signal": s["signal"], "rule": s["rule"],
                "note": s["note"], "accounts_context": s.get("accounts_context", ""),
                "thesis_groups": s["thesis_groups"],
            } for s in signals_list]
        }
        mtd_data = compute_position_mtd_pl(holdings, enrichment, perf)
        gw_note = golden_window_roth_note(retirement, perf)
    except Exception as e:
        print(f"[monthly-report] Signals/MTD error (falling back): {e}")
        signals_data = {"signals": []}
        mtd_data = {"top_line": {"dollar": (perf.get("periods",{}).get("1M") or {}).get("change",0), "pct": (perf.get("periods",{}).get("1M") or {}).get("change_pct",0)}, "attribution": [], "attribution_total": 0, "fidelity_401k_residual": 0, "coverage": {"positions_covered":0,"positions_total":0,"pct_mv":0}}
        gw_note = ""

    # Generate HTML
    html = _generate_html(date_str, weeklies, holdings, perf, narratives,
                          signals_data, mtd_data, retirement, dividends, enrichment, gw_note)
    if dry_run and output_path:
        html_path = Path(output_path)
        html_path.write_text(html)
        # Also save Telegram preview alongside
        tg_preview_path = html_path.with_suffix(".telegram.txt")
    else:
        html_path = MONTHLY_DIR / f"monthly_{date_str}.html"
        html_path.write_text(html)
    print(f"[monthly-report] HTML saved: {html_path}")

    # Dry-run: save Telegram preview and exit early
    periods = perf.get("periods", {})
    if dry_run:
        # Build Telegram payload for preview (same logic as below)
        tg_preview = _build_telegram_payload(
            month_name, date_str, holdings, periods, dividends, retirement,
            mtd_data, signals_data, gw_note)
        tg_path = Path(output_path).with_suffix(".telegram.txt") if output_path else Path("/tmp/track_a_final_telegram.txt")
        tg_path.write_text(tg_preview)
        print(f"[monthly-report] DRY RUN — Telegram preview saved: {tg_path}")
        print(f"[monthly-report] DRY RUN — HTML saved: {html_path}")
        print(f"[monthly-report] DRY RUN — No Telegram sent, no DOCX, no deploy.")
        return html_path

    # Copy to served directory
    try:
        import shutil
        served_dir = PROJECT_ROOT / "reports" / "monthly"
        served_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(html_path, served_dir / html_path.name)
        print(f"[monthly-report] Copied to reports/monthly/ for serving")
    except Exception as e:
        print(f"[monthly-report] Copy to served dir warning: {e}")

    # Save JSON data
    json_path = MONTHLY_DIR / f"monthly_{date_str}.json"
    periods = perf.get("periods", {})
    json_data = {
        "date": date_str,
        "month": month_name,
        "total_value": holdings.get("portfolio_totals", {}).get("total_value", 0),
        "1m_change_pct": periods.get("1M", {}).get("change_pct"),
        "ytd_change_pct": periods.get("YTD", {}).get("change_pct"),
        "1y_change_pct": periods.get("1Y", {}).get("change_pct"),
        "weekly_reports_used": len(weeklies),
        "narratives": narratives,
        "html_path": str(html_path),
        "docx_path": "",
    }

    # Generate DOCX
    docx_path = None
    try:
        from portfolio_report import generate_portfolio_brief
        docx_path = MONTHLY_DIR / f"monthly_{date_str}.docx"
        generate_portfolio_brief(
            holdings,
            _load_state("ai_analysis_cache.json"),
            _load_state("tax_projection.json"),
            risk,
            risk,
            docx_path,
            retirement=retirement,
            perf_history=perf,
        )
        json_data["docx_path"] = str(docx_path)
        print(f"[monthly-report] DOCX saved: {docx_path}")
    except Exception as e:
        print(f"[monthly-report] DOCX generation skipped: {e}")

    json_path.write_text(json.dumps(json_data, indent=2, default=str))
    print(f"[monthly-report] JSON saved: {json_path}")

    # Cleanup old monthly reports (keep last 6)
    old_reports = sorted(MONTHLY_DIR.glob("monthly_*.html"))
    for old in old_reports[:-6]:
        old.unlink()
        old_json = old.with_suffix(".json")
        if old_json.exists():
            old_json.unlink()
        old_docx = old.with_suffix(".docx")
        if old_docx.exists():
            old_docx.unlink()
        print(f"[monthly-report] Cleaned up {old.name}")

    # Send Telegram summary (both chat IDs)
    tg_msg = _build_telegram_payload(month_name, date_str, holdings, periods,
                                      dividends, retirement, mtd_data, signals_data, gw_note)
    _send_telegram(tg_msg)

    # Send DOCX attachment
    if docx_path and docx_path.exists():
        caption = f"📈 Monthly Portfolio Report — {month_name} | ${total_val:,.0f}"
        _send_telegram_doc(docx_path, caption)

    print(f"[monthly-report] Done. Report: {html_path}")
    return html_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate comprehensive monthly portfolio report using Claude Sonnet"
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate HTML + Telegram preview without sending or replacing files")
    parser.add_argument("--output-path", default=None,
                        help="Save HTML to this path instead of the default monthly dir")
    args = parser.parse_args()
    run_monthly_report(args.project_root, dry_run=args.dry_run,
                       output_path=args.output_path)
