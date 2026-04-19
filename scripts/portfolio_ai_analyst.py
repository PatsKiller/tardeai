"""portfolio_ai_analyst.py — Trade AI v12 Portfolio Intelligence
Deep wealth management analysis using Claude Sonnet 4.6.
Provides stock-level insights, ETF look-through, and specific recommendations.
Refreshes monthly. Daily runs use cached analysis.
"""
from __future__ import annotations
import json, os, time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

def _get_api_key():
    key = os.getenv("ANTHROPIC_API_KEY","").strip()
    if not key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.getenv("ANTHROPIC_API_KEY","").strip()
        except: pass
    return key

HAIKU  = os.getenv("CLAUDE_CHEAP_MODEL",    "claude-haiku-4-5-20251001")
SONNET = os.getenv("CLAUDE_ESCALATION_MODEL","claude-sonnet-4-20250514")
OLLAMA_MODEL = "qwen3:1.7b"  # 1.7b for weekly AI sections (fast, no think tokens)
_USE_OLLAMA = False  # set True when run_type=="weekly"

_AI_RULES = """/no_think
STRICT AI ANALYST PAGE REBUILD RULES — APPLY TO EVERY SECTION EVERY RUN:

1. TOP OF PAGE: Actionable Checklist (4–6 bullets) with ✅/❌ status + one-click buttons.
2. Professional card layout only — no walls of text. Max 3–5 bullets per card + "Why it matters" + "Action".
3. Graphics required where useful:
   - Sector Exposure → Tailwind CSS pie chart (colored segments)
   - P&L Performance → simple horizontal bar chart (contributors green, detractors red)
   - Risk Assessment → gauge-style beta + protected/unprotected split
   - All Holdings → clean sortable table with color-coded gain %
4. Fidelity 401k handling: If fidelity_401k data is missing or $0, explicitly state: "Fidelity 401k data unavailable — refresh NetBenefits export" in Account Structure and Executive Summary.
5. Rating logic: Explain BEARISH rating even when returns are positive (concentration risk, worthless positions, stop-loss gaps, rule-based signals).
6. No repetition of Personal Financial Situation. No $0 placeholders.
7. Dark professional theme, neon accents, consistent card borders, scannable hierarchy.
8. End every output with: "For informational purposes only. Not investment advice."

STRICT RULES — READ FIRST:
1. Pull EVERY number from the portfolio data passed. NEVER default to $0.
2. If a number is missing, say "Data unavailable" — never substitute zero.
3. Personal Financial Situation appears ONCE only in executive_summary.
   All other sections say: "Given John's conservative profile and SSDI income..."
4. Every section must reference specific tickers and real percentages from the data.
5. Defense section: respect the AI WWIII defense portfolio thesis. Only flag
   actual violations (stop breach, revoked registration, >15% single position).
6. Max 300 words per section (400 for executive summary and Roth conversion).
7. End full output with: For informational purposes only. Not investment advice.
8. Rating BULLISH/NEUTRAL/BEARISH must be justified by actual SMA200/VIX/beta data.
"""

def _ollama(prompt: str, max_tokens: int = 500) -> str:
    import re as _re, requests as _req
    if len(prompt) > 6000: prompt = prompt[:6000] + "\n[Be concise.]"
    try:
        r = _req.post("http://127.0.0.1:11434/api/generate",
            json={"model":"qwen3:1.7b","stream":False,"prompt":prompt,
                  "think":False,
                  "options":{"temperature":0.3,"num_predict":800,"num_ctx":4096}},
            timeout=120)
        text = r.json().get("response","").strip()
        return _re.sub(r"<think>.*?</think>","",text,flags=_re.DOTALL).strip()
    except Exception as e:
        return f"Ollama error: {e}"

def _ai(prompt: str, model: str = None, max_tokens: int = 1500) -> str:
    """Route to Ollama (weekly) or Claude (monthly/manual)."""
    if _USE_OLLAMA:
        return _ollama(prompt, max_tokens=min(max_tokens, 600))
    return _claude(prompt, model=model, max_tokens=max_tokens)

def _claude(prompt: str, model: str = None, max_tokens: int = 1500) -> str:
    key = _get_api_key()
    if not key: return "AI analysis unavailable — ANTHROPIC_API_KEY not set."
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model or SONNET, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=90)
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        return f"Error: {str(e)[:100]}"

# ── Build portfolio context string ────────────────────────────────────────────


# ── Module-level root path (set by run_ai_analysis) ──────────────────────────
_CURRENT_ROOT = "."


def _mini_context(portfolio: Dict, analysis: Dict = None, rebalancing: Dict = None) -> str:
    """Compact portfolio context for Ollama (fits in ~800 tokens).
    No biographical dump — just key numbers the model needs to analyze."""
    totals = portfolio.get("portfolio_totals", {})
    accounts = portfolio.get("account_summaries", {})
    holdings = [h for h in portfolio.get("holdings", [])
                if (h.get("market_value") or 0) > 200 and not h.get("is_loan")]
    holdings.sort(key=lambda h: -(h.get("market_value") or 0))
    divs = (analysis or {}).get("dividends", {})

    top_h = "\n".join(
        f"  {h['symbol']:8} ${(h.get('market_value') or 0):>9,.0f}  "
        f"{(h.get('portfolio_pct') or 0):5.1f}%  "
        f"gl={'+' if (h.get('gain_loss') or 0) >= 0 else ''}{(h.get('gain_loss') or 0):,.0f}"
        for h in holdings[:15]
    )

    acct_lines = "\n".join(
        f"  {k}: ${v.get('total_value',0):,.0f}"
        for k, v in accounts.items() if v.get("total_value", 0) > 0
    )

    flags = (analysis or {}).get("critical_flags", [])
    flag_lines = "\n".join(f"  [{f['severity']}] {f['message']}" for f in flags[:4]) if flags else "  None"

    return f"""PORTFOLIO: ${totals.get('total_value',0):,.0f} | Gain: ${totals.get('total_gain',0):+,.0f}
Dividends: ${divs.get('total_annual_income',0):,.0f}/yr
Owner: John Whiting, age 58, SSDI income $45,600/yr, conservative

ACCOUNTS:
{acct_lines}

TOP HOLDINGS:
{top_h}

FLAGS:
{flag_lines}

REBALANCING: ${(rebalancing or {}).get('total_to_rebalance',0):,.0f} needed
{portfolio.get('_weekly_trajectory', '')}"""


def _get_context(portfolio, analysis=None, rebalancing=None):
    """Return mini context for Ollama, full context for Claude."""
    if _USE_OLLAMA:
        return _mini_context(portfolio, analysis, rebalancing)
    return _portfolio_context(portfolio, analysis or {}, rebalancing or {})


def _load_fidelity_constraint(root: str = ".") -> str:
    """
    Load Fidelity 401k plan fund universe and inject as constraint into AI prompts.

    ACTIVE: Until 2027 rollover. constraint_active=True in portfolio_accounts.yaml.
    INACTIVE: After rollover — returns "" so AI analyst sees no restriction.

    What this prevents:
      AI suggesting BND, VXUS, JEPI, individual stocks for the Fidelity 401k.
    What this enables:
      AI recommending exchanges between actual plan funds (SP500-D, SS-GACEQ, etc.)

    Reads: assets/portfolio_accounts.yaml
      → fidelity_401k_constraints (constraint_active, preferred, avoid, strategy)
      → fidelity_available_funds (all 15 Omnicom plan funds with performance)
    """
    try:
        import yaml
        from pathlib import Path as _P
        p = _P(root) / "assets" / "portfolio_accounts.yaml"
        if not p.exists():
            return ""
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        constraints = data.get("fidelity_401k_constraints", {})
        if not constraints.get("constraint_active", False):
            return ""  # Post-2027 rollover: constraint off, full Schwab universe
        funds = data.get("fidelity_available_funds", [])
        if not funds:
            return ""
        rollover_date = constraints.get("rollover_target_date", "2027")
        preferred     = constraints.get("preferred_for_rebalance", [])
        avoid         = constraints.get("avoid_for_rebalance", [])
        pre_strategy  = constraints.get("pre_rollover_strategy", "").strip()
        lines = []
        for f in funds:
            held    = f.get("current_value", 0) > 0
            is_pref = f["internal_code"] in preferred
            is_avoid = f["internal_code"] in avoid
            if not held and not is_pref and not is_avoid:
                continue  # skip unused/unimportant funds
            tag = " [⭐ PREFERRED — lowest cost/best performer]" if is_pref else ""
            avoid_tag = " [⚠️ AVOID — poor performance]" if is_avoid else ""
            held_tag  = f" [CURRENTLY {f.get('current_pct',0):.1f}% of 401k]" if held else " [available, not held]"
            lines.append(
                f"  {f['internal_code']:15} {f['name']:26} "
                f"1yr:{f.get('perf_1yr',0):+.1f}% "
                f"ER:{f.get('expense_ratio','?')}%"
                f"{held_tag}{tag}{avoid_tag}"
            )
        return (
            "\n╔══════════════════════════════════════════════════════════════════╗"
            "\n║  ⚠️  FIDELITY 401K — CLOSED-UNIVERSE CONSTRAINT                   ║"
            f"\n║  Active until {rollover_date} rollover to Schwab                         ║"
            "\n╠══════════════════════════════════════════════════════════════════╣"
            "\n║  ALL 401k suggestions MUST use ONLY these plan funds.            ║"
            "\n║  DO NOT suggest BND, VXUS, JEPI, ETFs, or stocks for 401k.      ║"
            "\n║  Rebalance via Fidelity NetBenefits Exchange function.           ║"
            "\n╚══════════════════════════════════════════════════════════════════╝"
            f"\n\nFIDELITY OMNICOM 401K — AVAILABLE FUNDS ONLY:\n"
            + "\n".join(lines)
            + f"\n\nAVOID: {', '.join(avoid)}"
            + f"\nSTRATEGY: {pre_strategy}"
            + f"\nAfter {rollover_date} rollover to Schwab Rollover IRA → full ETF/stock universe opens.\n"
        )
    except Exception as e:
        return f"  [fidelity constraint: {e}]"


def _portfolio_context(portfolio: Dict, analysis: Dict, rebalancing: Dict) -> str:
    totals = portfolio.get("portfolio_totals", {})
    accounts = portfolio.get("account_summaries", {})
    holdings = [h for h in portfolio.get("holdings", [])
                if (h.get("market_value") or 0) > 200 and not h.get("is_loan")]
    holdings.sort(key=lambda h: -(h.get("market_value") or 0))
    etf_exposure = analysis.get("etf_ticker_exposure", {})

    # Top holdings
    top_h = "\n".join(
        f"  {h['symbol']:8} {h.get('account_display','')[:22]:22} "
        f"${(h.get('market_value') or 0):>9,.0f}  {(h.get('portfolio_pct') or 0):5.1f}%  "
        f"gl=${(h.get('gain_loss') or 0):>8,.0f} ({(h.get('gain_loss_pct') or 0):+.0f}%)"
        for h in holdings[:20]
    )

    # ETF look-through top 10
    etf_top = "\n".join(
        f"  {sym:8} ${mv:>9,.0f}  {mv/totals.get('total_value',1)*100:4.1f}% of portfolio (via ETFs/funds)"
        for sym, mv in list(etf_exposure.items())[:10]
    ) if etf_exposure else "  (not computed)"

    # V scenario
    v_data = rebalancing.get("v_to_schd_scenario", {})
    v_scenarios = "\n".join(
        f"  Sell {s['scenario_pct']}% ({s['sell_v_shares']:.0f} shares, ${s['sell_v_mv']:,.0f}) → "
        f"buy {s['buy_schd_shares']:.0f} SCHD = +${s['net_div_change']:,.0f}/yr dividends, "
        f"V drops to {s['remaining_v_pct']}%"
        for s in v_data.get("scenarios", [])
    ) if v_data else ""

    divs = analysis.get("dividends", {})
    flags = "\n".join(f"  [{f['severity']}] {f['message']}" for f in analysis.get("critical_flags", [])[:6])

    # ── v48: Resolved sector look-through ────────────────────────────────────
    resolved_sectors = portfolio.get("resolved_sectors", [])
    lookthrough_date = portfolio.get("lookthrough_as_of", "")
    if resolved_sectors:
        sector_lines = "\n".join(
            f"  {s['sector']:30s} ${s['value']:>10,.0f}  {s['pct']:5.1f}%"
            for s in resolved_sectors[:10]
        )
        sector_block = f"Look-through as of {lookthrough_date}:\n{sector_lines}"
    else:
        sector_block = "  (not yet computed — run portfolio_performance_history.py)"

    # ── v48: Fund overlap analysis ────────────────────────────────────────────
    overlap_analysis = portfolio.get("overlap_analysis", {})
    overlaps = overlap_analysis.get("overlaps", [])
    if overlaps:
        overlap_lines = "\n".join(
            f"  {o['ticker']:8} direct ${o['direct_value']:>8,.0f} "
            f"+ {o['indirect_via']} ${o['indirect_value']:>8,.0f} "
            f"= ${o['combined_value']:>8,.0f} combined"
            for o in overlaps[:5]
        )
    else:
        overlap_lines = "  (none detected)"

    return f"""=== PORTFOLIO OVERVIEW ===
Owner: John W. Whiting | DOB: 8/21/1967 (turns 59 August 2026)
Total Value: ${totals.get('total_value',0):,.0f}
Total All-Time Gain: ${totals.get('total_gain',0):,.0f} (+{totals.get('total_gain_pct',0):.1f}%)
Annual Dividend Income: ${divs.get('total_annual_income',0):,.2f}/yr (${divs.get('total_monthly_income',0):,.2f}/mo)
Day Change: ${totals.get('day_change',0):+,.0f}

=== PERSONAL FINANCIAL SITUATION ===
Income sources:
  - SSDI: $3,800/month ($45,600/yr) — converts to SS retirement at FRA age 67
  - Schedule C: ~$20,000/yr gross (business income, deductions reduce taxable net)
  - Private disability insurance: ACTIVE until age 68.5 (recertify 2x/yr medically)
  - NO need to withdraw from investments until age 68.5 — 10+ years uninterrupted compounding

Filing: MFS (Married Filing Separately, lived-apart rule)
  - Mortgage interest: ~$16,011/yr (declining ~$150/yr as balance pays down)
  - Property tax: $7,670/yr (Bronxwood, NYC)
  - Total federal itemized: ~$21,011 | NY itemized: ~$23,681
  - SE tax deduction: ~$1,413/yr (from ~$20K Schedule C gross)

Housing: Bronxwood NYC (owned)
  - Mortgage balance: ~$408,347 @ 4% fixed, matures 09/2042


=== ROTH CONVERSION STRATEGY ===
GOLDEN WINDOW TIMELINE:
  Age 58-68.5: SSDI $45,600 + Sch C $20K → convert $25-50K/yr low tax
  Age 68.5-73: Disability stops, ONLY SS retirement (very low bracket!) → MAX conversions
  Age 73+:     RMDs kick in → want Roth as large as possible before this

2026 tax math ($20K Sch C + $45,600 SSDI):
  Income base: $65,600 → after SE deduction: $64,187
  Federal itemized: $21,011 → taxable pre-conversion: $43,176
  22% bracket ceiling MFS: ~$94,300 → room for $51,124 more before 24%
  Already converted $35K → remaining safe room in 2026: ~$16K
  Adding $16K: ~$3,520 incremental tax — highly efficient

SCHD 12.3% historical growth:
  $25K/yr → $500K Roth by 2035 (break-even 1.1 yrs)
  $50K/yr → $1,000K Roth by 2035 (break-even 2.3 yrs)

2027: Omnicom 401k ($501K) → Rollover IRA → total conversion pool ~$1,032K

=== ACCOUNTS ===
Fidelity 401k (Omnicom):   $501,155  [TERMINATED — rolling to Rollover IRA in 2027]
Schwab Rollover IRA ...258: $531,268  [WARNING: V=49.6% of this account, +702% unrealized gain]
Schwab Roth IRA ...415:     $40,422   [V + SCHG only — TARGET ACCOUNT for Roth conversions]
Schwab Taxable ...469:      $71,773   [AI WWIII defense portfolio + income ETFs + BDCs]

=== TOP HOLDINGS (with unrealized gain) ===
{top_h}

=== TRUE STOCK EXPOSURE (including through ETFs/Funds) ===
{etf_top}

=== SECTOR ALLOCATION (look-through, 18 funds/ETFs) ===
{sector_block}

=== FUND OVERLAP EXPOSURE ===
Stocks held directly AND inside funds:
{overlap_lines}

=== CRITICAL FLAGS ===
{flags}

=== V (VISA) SCENARIOS ===
Current: {v_data.get('current_v_shares',0):.0f} shares, ${v_data.get('current_v_mv',0):,.0f}, {v_data.get('current_v_pct_portfolio',0):.1f}% of portfolio
V yield: {v_data.get('v_yield_pct',0.83):.2f}% = ${v_data.get('current_v_annual_div',0):,.0f}/yr
SCHD yield: {v_data.get('schd_yield_pct',3.58):.2f}%
{v_scenarios}

=== REBALANCING ===
Net to rebalance: ${rebalancing.get('total_to_rebalance',0):,.0f}

{_load_fidelity_constraint(_CURRENT_ROOT)}
"""

# ── Section 1: Executive Summary ──────────────────────────────────────────────

def _exec_summary(portfolio: Dict, analysis: Dict, rebalancing: Dict) -> str:
    """Haiku quick executive summary for daily runs."""
    totals = portfolio.get("portfolio_totals", {})
    flags  = analysis.get("critical_flags", [])
    high_flags = [f for f in flags if f.get("severity") in ("HIGH","CRITICAL")]

    prompt = f"""Portfolio morning brief for John W. Whiting (age 58, turns 59 Aug 2026):
Total: ${totals.get('total_value',0):,.0f} | Gain: +${totals.get('total_gain',0):,.0f} (+{totals.get('total_gain_pct',0):.1f}%)
Annual dividends: ${analysis.get('dividends',{}).get('total_annual_income',0):,.0f}/yr
Rebalancing needed: ${rebalancing.get('total_to_rebalance',0):,.0f} net
Income: SSDI $45,600/yr only. MFS lived-apart filing. Prop tax + mortgage interest itemized.
Roth conversion: $35K done in 2026. Sweet spot $25K/yr ($3,547 tax).
High priority flags: {len(high_flags)}
Top flags: {chr(10).join(f['message'] for f in high_flags[:3])}

Write a 3-sentence executive portfolio brief a wealth manager would send.
Include the single most important action item considering his Roth conversion strategy and income situation."""
    return _ai(prompt, model=HAIKU, max_tokens=250)


def _roth_conversion_analysis(portfolio: Dict) -> str:
    """Sonnet: annual Roth conversion advice — how much to convert and what to buy."""
    rollover_mv = portfolio.get("account_summaries",{}).get("schwab_rollover_ira",{}).get("total_value",531268)
    fidelity_mv = portfolio.get("account_summaries",{}).get("fidelity_401k",{}).get("total_value",501155)
    roth_mv     = portfolio.get("account_summaries",{}).get("schwab_roth",{}).get("total_value",40422)

    return _ai(_AI_RULES + f"""JOHN'S ROTH CONVERSION — ANNUAL ADVISOR ANALYSIS

FULL INCOME PICTURE 2026:
  SSDI: $45,600/yr (converts to SS retirement at FRA age 67)
  Schedule C: ~$20,000/yr gross (business write-offs reduce net taxable)
  Private disability insurance: continues to age 68.5 (recertify 2x/yr medically)
  NO need to draw from investments until 68.5 — 10+ years uninterrupted compounding
  Already converted: $35,000 in 2026

TAX MATH:
  Base income: $65,600 → SE deduction ~$1,413 → adjusted: $64,187
  Federal itemized deductions: ~$21,011 (mort int $16,011 + prop tax $7,670)
  Taxable income pre-conversion: ~$43,176
  22% bracket tops at ~$94,300 MFS → room for ~$51K total conversion before 24%
  Already did $35K → ~$16K safe room remaining in 2026 at 22%

IRA POOL:
  Rollover IRA: ${rollover_mv:,.0f} (current)
  Fidelity 401k: ${fidelity_mv:,.0f} (rolls to Rollover IRA in 2027)
  NOTE: Until rollover, Fidelity 401k can ONLY exchange between plan funds
  listed in the constraint block above. Recommend exchanges within plan to
  optimize for lowest-cost and best-performing available funds.
  Current Roth: ${roth_mv:,.0f}
  2027 total pool: ~$1,032,000

GOLDEN WINDOW STRATEGY:
  Age 58-68.5: Convert $25-50K/yr while disability + SSDI + Sch C provides income
  Age 68.5-73: Disability stops → ONLY SS income → LOWEST TAX BRACKET WINDOW
                 → could convert $50-100K/yr at 10-12% federal
  Age 73+: RMDs begin → Roth should be as large as possible by then

Schedule C business write-offs (deduct from $20K gross to reduce net taxable):
  Home office, equipment, software, internet, phone, mileage, professional services

You are a CPA and fee-only financial advisor. Answer these ANNUAL ADVISORY questions:

1. HOW MUCH TO CONVERT IN 2026?
   John has done $35K. Should he convert more before Dec 31?
   Give exact tax at different additional amounts: $0 more, $10K more, $16K more.
   What is the OPTIMAL additional amount given his situation?

2. WHAT TO BUY INSIDE THE ROTH AFTER CONVERSION?
   Roth should hold highest-return assets (tax-free growth).
   Rank these in order for Roth: SCHG (0.4%), JEPQ (9.5%), JEPI (7.8%), SCHD (3.58%), O/REIT (5.7%)
   Explain why for his specific situation.

3. 2027 PLAN (401K ROLLS OVER)
   When $501K Omnicom 401k moves to Rollover IRA in 2027 (+ existing $531K):
   How much to convert in 2027? What's the optimal sequence?
   
4. GOLDEN WINDOW AT 68.5-73
   Model the projected balances at 68.5 and optimal conversion strategy in that window.
   How much could John realistically convert tax-free in that low-bracket window?

5. SCHEDULE C WRITE-OFF STRATEGY
   What deductions should John maximize each year to reduce net Sch C income?
   How does each $1K in write-offs affect Roth conversion capacity?

Be specific: exact dollar amounts, tax estimates, investment tickers.
Format as numbered advisory points.""",
    model=SONNET, max_tokens=1400)

# ── Section 2: Deep Stock-Level Analysis ─────────────────────────────────────

def _deep_holdings_analysis(portfolio: Dict, analysis: Dict, rebalancing: Dict) -> str:
    ctx = _get_context(portfolio, analysis, rebalancing)

    return _ai(_AI_RULES + f"""TASK: Deep stock-level analysis of John's top holdings.
For each of these 8 positions, provide: recommendation (HOLD/TRIM/ADD/ROTATE), rationale, and key risk.
Focus on: V, FCNTX, SCHD, CSWC, PFLT, AVAV, RKLB, BND.
Write in prose paragraphs, not dashed lists. Be specific with percentages and dollar amounts from the data below.

{ctx}""",
    model=SONNET, max_tokens=1400)

# ── Section 3: Dividend Strategy ─────────────────────────────────────────────

def _dividend_strategy(portfolio: Dict, analysis: Dict) -> str:
    ctx = _get_context(portfolio, analysis)
    divs = analysis.get("dividends", {})
    by_holding = divs.get("by_holding", [])
    div_table = "\n".join(
        f"  {d['symbol']:8} yield={d.get('yield_pct',0):.1f}%  "
        f"annual=${d.get('annual_income',0):,.0f}  "
        f"freq={d.get('frequency','?'):12}"
        for d in by_holding[:10]
    ) if by_holding else "  (no dividend data)"
    total_annual = divs.get("total_annual_income", 0)
    total_mv = portfolio.get("portfolio_totals",{}).get("total_value",1)

    return _ai(_AI_RULES + f"""TASK: Dividend income strategy for John's portfolio.
Current yield: {total_annual/total_mv*100:.2f}% (${total_annual:,.0f}/yr). Target: $28,000/yr.
Analyze: yield adequacy, top 3 upgrade trades (specific tickers+amounts), BDC sustainability (CSWC 10.5%, PFLT 11.2%).
Write in prose paragraphs. Use real numbers from the data below.

DIVIDEND HOLDINGS:
{div_table}

{ctx}""",
    model=SONNET, max_tokens=1400)

# ── Section 4: Bond Strategy ──────────────────────────────────────────────────

def _bond_strategy(portfolio: Dict, rebalancing: Dict) -> str:
    ctx = _get_context(portfolio, rebalancing=rebalancing)
    rollover_mv = portfolio.get("account_summaries",{}).get("schwab_rollover_ira",{}).get("total_value",531268)

    return _ai(_AI_RULES + f"""TASK: Bond allocation strategy for John's Rollover IRA (${rollover_mv:,.0f}).
Current bonds: BND only. Target: 25% of IRA in bonds.
Recommend specific bond ETF allocation (BND, AGG, VCIT, VGIT, SGOV) with dollar amounts.
Assess duration risk for a 10-15 year retirement horizon. Write in prose paragraphs.

{ctx}""",
    model=SONNET, max_tokens=1400)

# ── Section 5: IRA Rollover Strategic Options ────────────────────────────────

def _ira_opportunities(portfolio: Dict) -> str:
    ctx = _get_context(portfolio)
    rollover_mv = portfolio.get("account_summaries",{}).get("schwab_rollover_ira",{}).get("total_value",531268)

    return _ai(_AI_RULES + f"""TASK: Rollover IRA opportunities for John's ${rollover_mv:,.0f} account.
This is a tax-deferred IRA with full investment access (stocks, bonds, REITs, BDCs, ETFs).
Identify: 3 missing asset classes to add, specific REIT recommendations, covered call ETF opportunity (JEPI/JEPQ).
Write in prose paragraphs with specific tickers and dollar amounts.

{ctx}""",
    model=SONNET, max_tokens=1500)

# ── Section 6: V Concentration Strategy ──────────────────────────────────────

def _v_strategy(portfolio: Dict, rebalancing: Dict) -> str:
    ctx = _get_context(portfolio, rebalancing=rebalancing)
    v_data = rebalancing.get("v_to_schd_scenario", {})
    v_mv     = v_data.get("current_v_mv", 0) or 0
    v_shares = v_data.get("current_v_shares", 0) or 0
    v_pct    = v_data.get("current_v_pct_portfolio", 0) or 0
    v_price  = v_data.get("v_price", 0) or 0
    # Dynamic per-account breakdown from holdings
    holdings = portfolio.get("holdings", [])
    v_rollover = [(h.get("shares") or 0, h.get("market_value") or 0, h.get("cost_basis") or 0)
                  for h in holdings if h.get("symbol","").upper()=="V" and h.get("account","")=="schwab_rollover_ira"]
    v_roth     = [(h.get("shares") or 0, h.get("market_value") or 0, h.get("cost_basis") or 0)
                  for h in holdings if h.get("symbol","").upper()=="V" and h.get("account","")=="schwab_roth"]
    v_roll_sh  = sum(x[0] for x in v_rollover)
    v_roll_mv  = sum(x[1] for x in v_rollover)
    v_roll_cb  = sum(x[2] for x in v_rollover)
    v_roth_sh  = sum(x[0] for x in v_roth)
    v_roth_mv  = sum(x[1] for x in v_roth)
    v_roth_cb  = sum(x[2] for x in v_roth)
    v_cost_approx = (v_roll_cb + v_roth_cb) or 71989
    v_gain    = v_mv - v_cost_approx if v_cost_approx > 0 else 0
    v_gain_pct = (v_gain / v_cost_approx * 100) if v_cost_approx > 0 else 0

    return _ai(_AI_RULES + f"""TASK: V (Visa) concentration strategy. John holds {v_shares:.0f} shares (${v_mv:,.0f}, {v_pct:.1f}% of portfolio).
Recommend: HOLD ALL / TRIM 30% / TRIM 50%. If trimming, what to buy (SCHD? JEPI? bonds?).
Write in prose paragraphs with specific share counts and dollar amounts.

V (VISA) DEEP DIVE:
Total shares: {v_shares:.1f} across 2 accounts
  - Rollover IRA: {v_roll_sh:.1f} shares @ ${v_price:.2f} = ${v_roll_mv:,.0f} (tax-deferred, NO cap gains on sale)
  - Roth IRA:     {v_roth_sh:.1f} shares @ ${v_price:.2f} = ${v_roth_mv:,.0f} (tax-FREE, NO cap gains on sale)
  - Combined cost basis: ~${v_cost_approx:,.0f}
  - Unrealized gain: ~${v_gain:,.0f} (+{v_gain_pct:.0f}%)
  - Portfolio weight: {v_pct:.1f}%
  - Dividend yield: 0.83% = ~$2,513/yr
  - Forward P/E: ~32x (April 2026)

VISA BUSINESS ANALYSIS:
- Processed $14+ trillion in payment volume in FY2024
- Net revenue margin: ~52% — extraordinarily high
- Duopoly with Mastercard in card payment networks
- BNPL risk: Klarna, Affirm operating on bank rails (V still earns fees)
- Crypto settlement risk: minimal near-term — stablecoin settlement still uses V rails
- Price target consensus: ~$325-350 (April 2026)
- Key risk: DOJ antitrust investigation into debit card routing

ALTERNATIVES ANALYSIS:
- Keep V: Quality compounder, low yield, but dominant franchise
- Rotate to MA (Mastercard): Similar business, slightly higher growth, similar yield
- Rotate to SCHD: 3.58% yield, 100-stock quality screen, lower volatility
- Rotate to VFH: Vanguard Financials ETF — diversify within financials
- Rotate to JEPI: Covered calls on S&P 500, 7-8% yield
- Rotate to BND+VCIT: Fixed income, reduce equity risk

You are a senior portfolio manager at Fidelity. Answer:

1. HOLD/TRIM/SELL RECOMMENDATION
   Given the full picture, what should John do with V?
   Be direct: HOLD ALL / TRIM 30% / TRIM 50% / SELL ALL
   Give your reasoning in 3 sentences max.

2. OPTIMAL ROTATION TARGET
   If trimming V, what exactly to buy?
   Give: specific ticker, shares to buy, expected yield change, expected return change
   Account for BOTH accounts (Rollover IRA and Roth IRA separately)

3. 5-YEAR SCENARIO ANALYSIS
   Scenario A: Hold all V
   Scenario B: Sell 30%, rotate to SCHD + VCIT
   Scenario C: Sell 50%, build diversified income portfolio
   For each: estimated portfolio value in 5 years and annual income

4. TIMING AND EXECUTION
   If selling, what's the optimal execution strategy?
   All at once? Systematic over 6 months? Dollar-cost averaging out?
   Any tax-loss harvesting angles (SRNE, LPIH in IRA)?

5. EMOTIONAL RISK
   V is a +700% winner. What psychological mistake do investors make with positions like this?
   What should John tell himself when V drops 15% after he sells?

Be direct, specific, and honest about the tradeoffs.""",
    model=SONNET, max_tokens=1500)

# ── Section 7: Defense Portfolio (Taxable) ───────────────────────────────────

def _defense_analysis(portfolio: Dict) -> str:
    taxable = [h for h in portfolio.get("holdings",[])
               if h.get("account")=="schwab_taxable" and not h.get("is_loan")
               and (h.get("market_value") or 0) > 200]
    taxable.sort(key=lambda h: -(h.get("market_value") or 0))
    holdings_str = "\n".join(
        f"  {h['symbol']:6} ${h.get('market_value',0):>8,.0f}  "
        f"gl=${h.get('gain_loss',0):>7,.0f} ({h.get('gain_loss_pct',0):+.0f}%)"
        for h in taxable
    )
    total_taxable = sum(h.get("market_value",0) for h in taxable)

    return _ai(_AI_RULES + f"""TAXABLE PORTFOLIO — AI WWIII Defense Strategy:
Total: ${total_taxable:,.0f}

Holdings:
{holdings_str}

Strategy: "AI WWIII" — defense tech, autonomous systems, satellite/SATCOM, 
           income ETFs (SCHD, DIV), BDCs (CSWC, PFLT)

Current defense holdings are very small ($500-900 each) — position-building phase.
Income holdings: SCHD $12,288, DIV $7,660, CSWC $9,059, PFLT $8,377
High-conviction speculative: RKLB (Rocket Lab, $1,707), ARKQ (autonomous tech ETF, $11,399)

You are a defense sector analyst and portfolio strategist. Provide:

1. DEFENSE PORTFOLIO CRITIQUE
   Are the current positions (AVAV, BAH, CACI, DRS, IRDM, KBR, KTOS, LDOS, LHX, LMT, NOC, RTX, TDG)
   the RIGHT names for an AI/autonomous defense strategy?
   Which 3 would you DROP and why?
   Which 2 would you ADD that aren't here?

2. CONCENTRATION BUILDING PLAN
   Current positions are $500-900 each — too small to matter.
   Given $71K total taxable account, how to build meaningful positions?
   Recommend: consolidate to 5-7 names, give specific allocation per name.

3. RKLB ASSESSMENT (Rocket Lab)
   High risk, high conviction bet on commercial space.
   Should John add here or is the position sizing appropriate?
   Price target? Key catalysts to watch?

4. CSWC + PFLT (BDC Income)
   These are in the taxable account — dividends are taxed as ordinary income.
   Would they be better in the IRA?
   Tax drag analysis: is the yield worth it in a taxable account?

5. INCOME vs GROWTH BALANCE
   Current taxable split: ~$17K income ETFs, ~$17K BDCs, ~$9K pure defense, ~$14K growth ETF
   Is this allocation logical given the stated "AI WWIII" strategy?
   Recommended target allocation across buckets.

Be direct. Give specific tickers, share counts, and dollar amounts.""",
    model=SONNET, max_tokens=1300)

# ── Cache Management ──────────────────────────────────────────────────────────

def _should_refresh(state_dir: Path, key: str, max_days: int = 30) -> bool:
    f = Path(state_dir) / f"ai_{key}.json"
    if not f.exists(): return True
    try:
        d = json.loads(f.read_text())
        age = (datetime.now() - datetime.fromisoformat(d.get("ts","2000-01-01"))).days
        return age >= max_days
    except: return True

def _load_cache(state_dir: Path, key: str) -> Optional[str]:
    f = Path(state_dir) / f"ai_{key}.json"
    try: return json.loads(f.read_text()).get("text","") if f.exists() else None
    except: return None

def _save_cache(state_dir: Path, key: str, text: str):
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    (Path(state_dir) / f"ai_{key}.json").write_text(
        json.dumps({"key":key,"text":text,"ts":datetime.now().isoformat()},indent=2))

# ── Main Entry Point ──────────────────────────────────────────────────────────

def run_ai_analysis(portfolio, analysis, rebalancing, state_dir, force_refresh=False, run_type="daily", root="."):
    results = {}
    state_dir = Path(state_dir)
    # Make root available to all section functions via module-level variable
    # so Fidelity constraint can be loaded without changing every function signature
    import portfolio_ai_analyst as _self_mod
    _self_mod._CURRENT_ROOT = str(root)
    global _USE_OLLAMA
    _USE_OLLAMA = (run_type == "weekly")
    print(f"  [ai] Running AI analysis (mode: {run_type}, engine: {'Ollama qwen3:1.7b' if _USE_OLLAMA else 'Claude Sonnet'})...")

    # Load previous weekly reports for monthly context
    _weekly_context = ""
    if run_type in ("monthly", "manual"):
        try:
            _weekly_dir = Path(root) / "data" / "portfolios" / "reports" / "weekly"
            _weekly_jsons = sorted(_weekly_dir.glob("weekly_*.json"))[-4:]
            if _weekly_jsons:
                _wk_lines = []
                for _wf in _weekly_jsons:
                    _wd = json.loads(_wf.read_text())
                    _wk_lines.append(
                        f"  {_wd.get('date','?')}: ${_wd.get('total_value',0):,.0f} "
                        f"1W={_wd.get('1w_change_pct',0) or 0:+.2f}% "
                        f"YTD={_wd.get('ytd_change_pct',0) or 0:+.2f}% "
                        f"beta={_wd.get('beta',0) or 0:.2f} "
                        f"action: {str(_wd.get('narratives',{}).get('action',''))[:60]}"
                    )
                _weekly_context = "\n\nMONTH'S WEEKLY TRAJECTORY (use for trend analysis):\n" + "\n".join(_wk_lines) + "\n"
                print(f"  [ai] Loaded {len(_weekly_jsons)} weekly reports for monthly context")
        except Exception as _e:
            print(f"  [ai] Weekly context load: {_e}")

    # Inject weekly context into portfolio context for monthly runs
    if _weekly_context:
        portfolio = dict(portfolio)
        portfolio["_weekly_trajectory"] = _weekly_context

    # Daily: executive summary (Haiku, cheap)
    print(f"  [ai] Executive summary ({'Ollama qwen3:1.7b' if _USE_OLLAMA else 'Haiku'})...")
    results["executive_summary"] = _exec_summary(portfolio, analysis, rebalancing)

    if run_type in ("monthly","manual","weekly") or force_refresh:
        sections = [
            ("deep_holdings",    "Deep Holdings Analysis",       _deep_holdings_analysis, 3),
            ("dividend_strategy","Dividend Strategy",            _dividend_strategy,      2),
            ("bond_strategy",    "Bond Strategy",                _bond_strategy,          2),
            ("ira_opportunities","IRA Rollover Opportunities",   _ira_opportunities,      1),
            ("v_strategy",       "V Concentration Strategy",     _v_strategy,             2),
            ("defense_analysis", "Defense Portfolio Analysis",   _defense_analysis,       1),
            ("roth_conversion",  "Roth Conversion Strategy",     _roth_conversion_analysis,1),
        ]
        for key, label, fn, n_args in sections:
            if force_refresh or _should_refresh(state_dir, key, 30):
                print(f"  [ai] {label} ({'Ollama qwen3:14b' if _USE_OLLAMA else 'Sonnet 4.6'})...")
                try:
                    if n_args == 3: text = fn(portfolio, analysis, rebalancing)
                    elif n_args == 2:
                        if key == "dividend_strategy": text = fn(portfolio, analysis)
                        else: text = fn(portfolio, rebalancing)
                    else: text = fn(portfolio)
                    _save_cache(state_dir, key, text)
                    results[key] = text
                    time.sleep(0.3)
                except Exception as e:
                    print(f"  [ai] {label} error: {e}")
                    results[key] = f"Analysis error: {str(e)[:120]}"
            else:
                cached = _load_cache(state_dir, key)
                if cached:
                    results[key] = cached
                    print(f"  [ai] {label} — cached")
    else:
        # Daily: load all cached sections
        for key in ["deep_holdings","dividend_strategy","bond_strategy",
                    "ira_opportunities","v_strategy","defense_analysis"]:
            cached = _load_cache(state_dir, key)
            if cached: results[key] = cached

    results["generated_at"] = datetime.now().isoformat()
    results["run_type"] = run_type
    n = len([k for k in results if k not in ("generated_at","run_type")])
    print(f"  [ai] ✅ {n} AI sections")
    return results

if __name__ == "__main__":
    import argparse, sys
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--run-type", default="weekly")
    args = ap.parse_args()
    root = Path(args.project_root).resolve()
    sd = root / "data" / "portfolios" / "state"
    port = json.load(open(sd / "holdings.json"))
    analysis = json.load(open(sd / "ai_analysis_cache.json")) if (sd/"ai_analysis_cache.json").exists() else {}
    risk = json.load(open(sd / "risk_management.json")) if (sd/"risk_management.json").exists() else {}
    result = run_ai_analysis(port, analysis, risk, sd, force_refresh=True, run_type=args.run_type, root=str(root))
    out = sd / "ai_analysis_cache.json"
    json.dump(result, open(out,"w"), indent=2)
    print(f"[ai_analyst] Done — {len(result)} sections → {out}")
