#!/usr/bin/env python3
"""alex_retirement_advisor.py — Proactive Retirement Advisor Agent.

Alex is triggered by:
1. Price alerts (SMA cross, RSI extreme, stop triggered, 52-week events)
2. Telegram commands routed from Maria or directly
3. Daily research topic iteration
4. Manual analysis requests

For each trigger, Alex provides:
- Current P&L by account (Roth/IRA/Taxable)
- Optimum sell/hold/add price analysis
- Analyst target comparison
- Rotation suggestions
- Tax implications
- Retirement-plan-aligned recommendation

Usage:
    python3 scripts/alex_retirement_advisor.py --alert SYMBOL [--json]
    python3 scripts/alex_retirement_advisor.py --analyze SYMBOL [--json]
    python3 scripts/alex_retirement_advisor.py --scan-portfolio [--telegram] [--json]
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _build_position_context(symbol: str) -> dict:
    """Build full position context for retirement-aware analysis."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Holdings by account
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    acct_summaries = holdings.get("account_summaries", {})
    total_portfolio = sum(info.get("total_value", 0) for info in acct_summaries.values())
    acct_display = {aid: info.get("display_name", aid) for aid, info in acct_summaries.items()}

    positions = []
    total_mv = 0
    total_cost = 0
    for h in holdings.get("holdings", []):
        if h.get("symbol") != symbol:
            continue
        aid = h.get("account_id") or h.get("account", "unknown")
        acct_type = "Roth" if "roth" in aid.lower() else "IRA" if "rollover" in aid.lower() or "ira" in aid.lower() else "401k" if "401k" in aid.lower() else "Taxable"
        mv = float(h.get("market_value", 0) or 0)
        cost = float(h.get("cost_basis", 0) or 0)
        shares = float(h.get("shares", 0) or 0)
        gl = float(h.get("gain_loss", 0) or 0)
        gl_pct = float(h.get("gain_loss_pct", 0) or 0)
        total_mv += mv
        total_cost += cost
        positions.append({
            "account": acct_display.get(aid, aid),
            "account_type": acct_type,
            "shares": round(shares, 2),
            "market_value": round(mv, 2),
            "cost_basis": round(cost, 2),
            "gain_loss": round(gl, 2),
            "gain_loss_pct": round(gl_pct, 2),
        })

    weight = round(total_mv / total_portfolio * 100, 2) if total_portfolio > 0 else 0

    # Enrichment (RSI, SMA, etc.)
    enrichment = json.loads((STATE_DIR / "ticker_enrichment_cache.json").read_text()) if (STATE_DIR / "ticker_enrichment_cache.json").exists() else {}
    e = enrichment.get(symbol, {}) if isinstance(enrichment.get(symbol), dict) else {}

    # Strategy card
    cur.execute("SELECT * FROM watchlist_strategy_cards WHERE symbol=%s", (symbol,))
    sc = cur.fetchone()

    # Classification
    cur.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE", (symbol,))
    cls = cur.fetchone()

    # Income profile
    cur.execute("SELECT * FROM income_asset_profiles WHERE symbol=%s", (symbol,))
    income = cur.fetchone()

    # Dividend data
    cur.execute("SELECT * FROM ticker_dividend_data WHERE symbol=%s", (symbol,))
    div_data = cur.fetchone()

    conn.close()

    return {
        "symbol": symbol,
        "positions": positions,
        "total_market_value": round(total_mv, 2),
        "total_cost_basis": round(total_cost, 2),
        "total_gain_loss": round(total_mv - total_cost, 2),
        "portfolio_weight": weight,
        "rsi": float(e.get("rsi", 0) or 0),
        "sma20_pct": float(e.get("sma20_pct", 0) or 0),
        "sma50_pct": float(e.get("sma50_pct", 0) or 0),
        "sma200_pct": float(e.get("sma200_pct", 0) or 0),
        "price": float(sc.get("latest_price", 0) or 0) if sc else 0,
        "support": float(sc.get("support", 0) or 0) if sc else 0,
        "resistance": float(sc.get("resistance", 0) or 0) if sc else 0,
        "strategy_type": cls["strategy_type"] if cls else "unknown",
        "annual_income": float(income.get("annual_income", 0) or 0) if income else 0,
        "yield_pct": float(div_data.get("dividend_yield_pct", 0) or 0) if div_data else 0,
        "payout_safety": income.get("payout_safety", "unknown") if income else "unknown",
    }


def _format_tax_context() -> str:
    """Format current tax situation for Alex's prompt including Medicare."""
    try:
        import psycopg2.extras as _pxe
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=_pxe.RealDictCursor)
        cur.execute("SELECT * FROM personal_tax_history WHERE tax_year=2026")
        s26 = cur.fetchone()
        cur.execute("SELECT * FROM personal_tax_history WHERE tax_year=2025")
        s25 = cur.fetchone()
        conn.close()
        if not s26:
            return "Tax data unavailable"
        agi = float(s26.get("agi", 0) or 0)
        roth_ytd = float(s26.get("roth_conversions_total", 0) or 0)
        std = float(s26.get("standard_deduction", 15700) or 15700)
        item = float(s26.get("itemized_deductions", 0) or 0)
        ded = max(item, std)
        ded_type = "itemized" if item > std else "standard"
        top22 = 100525 + ded
        room = max(0, top22 - agi)
        bracket = 22 if agi - ded > 47150 else 12
        biz_loss = abs(float(s25.get("business_loss", 0) or 0)) if s25 and float(s25.get("business_loss", 0) or 0) < 0 else 0
        prior_agi = float(s25["agi"]) if s25 else None
        ps = _load_personal()
        medicare = ps.get("medicare_start_date", "2026-12-01")
        medicare_note = ps.get("medicare_start_note", "")
        lines = [
            f"2026 estimated AGI: ${agi:,.0f}",
            f"Roth conversions YTD: ${roth_ytd:,.0f}",
            f"Current bracket: {bracket}%",
            f"Remaining 22% bracket room: ${room:,.0f} (using {ded_type} deduction ${ded:,.0f})",
            f"Max additional Roth conversion at 22%: ${room:,.0f}",
            f"2025 business loss carryforward: ${biz_loss:,.0f} (extra conversion capacity)",
            f"MEDICARE: Eligible {medicare}. {medicare_note}",
            f"CRITICAL: 2024 income determines 2026 IRMAA. 2026 income determines 2028 IRMAA.",
            f"DISABILITY STATUS: On SSDI ($3,800/mo). MFS filer. Private disability insurance to age 68.5.",
            f"  - SSDI converts to SS retirement at FRA 67. No 10% early withdrawal penalty (disability exemption).",
            f"  - Investment income does NOT affect SSDI (not SGA). Roth conversions do NOT threaten SSDI.",
            f"  - MFS: Cannot contribute directly to Roth ($0 income limit). Use backdoor Roth if IRA is clean.",
            f"  - Schedule C ~$20K/yr = earned income → eligible for IRA contributions ($7,000/yr).",
            f"MEDICAID PLANNING: After Medicare starts Dec 2026, Medicaid may supplement for extra benefits.",
            f"  - Medicaid Asset Protection Trust (MAPT) has 5-year lookback in NY (must be funded by ~2022 to be safe now).",
            f"  - Roth conversions INCREASE MAGI, which can disqualify Medicaid (income limits ~$1,677/mo or ~$20,124/yr for MFS in NY 2026).",
            f"  - Aggressive conversions ($50K+/yr) will likely push MAGI well above Medicaid income thresholds.",
            f"  - TRADEOFF: Higher Roth conversions = better long-term tax efficiency BUT may delay/prevent Medicaid eligibility.",
            f"  - Asset spend-down: Medicaid counts most assets; Roth IRAs ARE countable in NY. MAPT assets are exempt after 5yr lookback.",
            f"  - DISABILITY + MEDICAID: Disabled persons on SSDI may qualify for Medicaid through disability pathway (different income limits).",
            f"SPOUSAL IRA LOOPHOLE: If married, working spouse can make spousal IRA contributions ($7,500/$8,600 in 2026) to your account even though SSDI is not earned income.",
        ]
        if prior_agi is not None:
            lines.append(f"Prior year AGI (2025): ${prior_agi:,.0f}")
        # Trust transfers
        try:
            cur2 = conn.cursor(cursor_factory=_pxe.RealDictCursor)
            cur2.execute("SELECT event_date, amount, trust_type, five_year_lookback_start, protected_amount, trust_notes FROM tax_events WHERE event_type='trust_transfer' ORDER BY event_date DESC")
            transfers = cur2.fetchall()
            if transfers:
                lines.append(f"TRUST TRANSFERS ({len(transfers)} recorded):")
                for t in transfers:
                    from datetime import date as _date
                    lookback = t.get("five_year_lookback_start")
                    if lookback:
                        if isinstance(lookback, str):
                            lookback = _date.fromisoformat(lookback)
                        elapsed = (_date.today() - lookback).days / 365.25
                        remaining = max(0, 5 - elapsed)
                        status = "PROTECTED" if remaining <= 0 else f"{remaining:.1f}yr remaining"
                    else:
                        status = "no lookback date"
                    lines.append(f"  {t['trust_type'] or 'MAPT'}: ${float(t.get('amount',0)):,.0f} on {t['event_date']} — lookback: {status}")
            else:
                lines.append("TRUST TRANSFERS: None recorded. Consider starting MAPT to begin 5-year lookback clock.")
        except Exception:
            pass
        return "\n".join(lines)
    except Exception:
        return "Tax data unavailable"


def _get_intel_context(symbol: str = None) -> str:
    """Pull recent intelligence + cross-agent context + outcome feedback for Alex's prompt."""
    parts = []

    # Scored intelligence (news, YouTube, social)
    try:
        from intel_query import get_intel_summary, get_outcome_feedback
        summary = get_intel_summary(agent="Alex", symbol=symbol, min_quality=40, max_chars=1200, source_hint="high_value")
        if summary:
            parts.append(summary)
        # Past decision outcomes (learning loop)
        if symbol:
            feedback = get_outcome_feedback(symbol, limit=3)
            if feedback:
                parts.append(feedback)
    except Exception:
        pass

    # Cross-agent context (Maria, Steph, Risk latest analysis)
    if symbol:
        try:
            from agent_collab import get_agent_context, check_escalation
            agent_ctx = get_agent_context(symbol, requesting_agent="Alex")
            if agent_ctx:
                parts.append(agent_ctx)
            # Check for escalation flags
            esc = check_escalation(symbol)
            if esc["needs_escalation"]:
                parts.append(f"ESCALATION FLAG: {'; '.join(esc['reasons'])}")
        except Exception:
            pass

    return "\n\n".join(parts)


def analyze_for_retirement(symbol: str, trigger: str = "manual") -> dict:
    """Full retirement-aware analysis of a symbol position."""
    ctx = _build_position_context(symbol)

    if not ctx["positions"]:
        return {"symbol": symbol, "error": "Not held in portfolio"}

    # Build Alex's analysis prompt
    pos_text = "\n".join(
        f"  {p['account']} ({p['account_type']}): {p['shares']} shares, ${p['market_value']:,.0f}, "
        f"cost=${p['cost_basis']:,.0f}, P&L=${p['gain_loss']:,.0f} ({p['gain_loss_pct']:+.1f}%)"
        for p in ctx["positions"]
    )

    prompt = f"""/no_think You are Alex, a certified retirement planner and fiduciary advisor with 20+ years experience specializing in DISABILITY-OPTIMIZED retirement planning. You are warm, professional, conservative, and client-focused. Always prioritize the client's retirement income goal, tax efficiency, risk tolerance, and disability benefit preservation.

TRIGGER: {trigger}

CLIENT DISABILITY PROFILE (PERMANENT — APPLIES TO EVERY ANALYSIS):
- Status: On SSDI (Social Security Disability Insurance), $3,800/mo (~$45,600/yr)
- Private disability insurance: continues to age 68.5 (recertify 2x/year)
- Filing status: MFS (Married Filing Separately, lived apart)
- SSDI converts to SS retirement at FRA age 67
- No 10% early withdrawal penalty (age 58.5+ AND disability exemption under IRC §72(t)(2)(A)(iii))
- IRA contributions: CAN contribute to IRA while on SSDI if have earned income (Schedule C ~$20K/yr)
- Roth conversions: DO count as MAGI — can affect Medicaid eligibility and IRMAA
- MFS special rules: Roth contribution income limit is $0 for MFS (CANNOT contribute directly to Roth)
- MFS workaround: Backdoor Roth (contribute to Traditional IRA → convert) IS allowed for MFS filers
- 401k rollover: Omnicom 401k ($526K) rolls to Schwab IRA in 2027 — timing matters for disability planning
- Key risk: Aggressive Roth conversions increase MAGI → can affect SSDI trial work period evaluation, Medicaid, IRMAA

POSITION: {symbol}
{pos_text}
Total: ${ctx['total_market_value']:,.0f} ({ctx['portfolio_weight']:.1f}% of portfolio)
Total P&L: ${ctx['total_gain_loss']:,.0f}

MARKET DATA:
Price: ${ctx['price']:.2f} | RSI: {ctx['rsi']:.0f} | SMA20: {ctx['sma20_pct']:+.1f}% | SMA50: {ctx['sma50_pct']:+.1f}% | SMA200: {ctx['sma200_pct']:+.1f}%
Support: ${ctx['support']:.2f} | Resistance: ${ctx['resistance']:.2f}
Strategy: {ctx['strategy_type']} | Yield: {ctx['yield_pct']:.1f}% | Income: ${ctx['annual_income']:,.0f}/yr | Payout: {ctx['payout_safety']}

PORTFOLIO CONTEXT:
Income target: $55,000/yr. Current: $14,342/yr. Gap: $40,658. Timeline: 4-8 years.
Accounts: Fidelity 401k (~$526K, rolls to IRA 2027), Schwab Rollover IRA (~$556K), Schwab Roth IRA (~$42K), Schwab Taxable (~$75K).
SSDI income: $45,600/yr. Schedule C: ~$20K/yr gross.

TAX SITUATION (LIVE FROM DB):
{_format_tax_context()}

{_get_intel_context(symbol)}

Provide a retirement-advisor analysis covering:
1. ACCOUNT-SPECIFIC P&L: Gain/loss in each account type (Roth, IRA, Taxable) with cost basis.
2. HOLD/SELL/ADD RECOMMENDATION: Based on strategy type, income goal, and technical levels.
3. OPTIMUM ACTION PRICE: Specific entry/exit price levels with share counts.
4. DETAILED TAX IMPLICATIONS:
   - Roth: Tax-free growth, no RMDs, conversions from IRA create taxable event
   - IRA/401k: Tax-deferred, gains not taxed until withdrawal, RMDs at 73
   - Taxable: Long-term vs short-term capital gains rates, qualified dividend treatment
   - Wash sale risk if selling and rebuying within 30 days (across ALL accounts)
   - Roth conversion ladder impact: Does this action affect the conversion schedule?
5. ROTATION SUGGESTION: Tax-efficient redeployment to close income gap. Specify which account to buy in.
6. ROTH CONVERSION CONSIDERATION: If applicable, how does this position fit the Roth conversion ladder? Should gains be converted? What's the tax cost?
   - DISABILITY NOTE: Client is MFS — cannot contribute directly to Roth. Must use Backdoor Roth.
   - Consider: Is it better to leave this in 401k/IRA (creditor protected, disability exemption) or convert to Roth?
   - For disabled persons: 401k/IRA has creditor protection benefits that Roth may not in all states.
7. DISABILITY BENEFIT IMPACT: How does this action affect:
   - SSDI benefit continuation (investment income does NOT count as SGA, but earned income does)
   - Medicaid eligibility (MAGI-based — Roth conversions count). NY limit: ~$20,124/yr
   - IRMAA Medicare surcharge: MFS threshold $103,000. Project MAGI with and without this action.
   - Medicaid 5-year lookback: Would large IRA distributions start a new lookback period?
   - Private disability insurance recertification
   - MFS filing status implications — avoid large taxable events pushing MAGI into higher bracket
8. RISK ASSESSMENT: What changes this recommendation?

Use warm, supportive tone: "Here's what I recommend for you..." Be specific with dollar amounts, share counts, and tax rates. Always mention disability-specific considerations."""

    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from llm_router import get_llm_response
        high_impact = ctx["portfolio_weight"] > 5 or ctx["total_market_value"] > 50000
        result = get_llm_response("cio_synthesis" if high_impact else "agent_narrative",
                                   prompt, max_tokens=800, high_impact=high_impact)
        if not result.get("success") and high_impact:
            import time; time.sleep(1)  # Brief pause before local fallback
            result = get_llm_response("agent_narrative", prompt[:4000], max_tokens=600, high_impact=False)
            if not result.get("success"):
                # Last resort: minimal prompt to local
                import time; time.sleep(1)
                mini = f"/no_think Analyze {symbol} for retirement. Brief: {prompt[:1500]}"
                result = get_llm_response("agent_narrative", mini, max_tokens=500)

        if result.get("success"):
            analysis = result["response"]

            # Save to DB
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO portfolio_intelligence_events
                    (symbol, strategy_type, event_type, severity, source, payload)
                VALUES (%s, %s, 'alex_analysis', %s, 'alex_retirement_advisor.py', %s)
            """, (symbol, ctx["strategy_type"],
                  "high" if high_impact else "info",
                  json.dumps({"trigger": trigger, "provider": result.get("provider"),
                              "weight": ctx["portfolio_weight"], "pnl": ctx["total_gain_loss"]}, default=str)))
            conn.commit()
            conn.close()

            return {
                "symbol": symbol,
                "trigger": trigger,
                "analysis": analysis,
                "provider": result.get("provider"),
                "cost": result.get("cost_estimate", 0),
                "high_impact": high_impact,
                "context": {
                    "weight": ctx["portfolio_weight"],
                    "pnl": ctx["total_gain_loss"],
                    "accounts": len(ctx["positions"]),
                    "strategy": ctx["strategy_type"],
                    "income": ctx["annual_income"],
                },
            }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

    return {"symbol": symbol, "error": "LLM failed"}


def _load_personal() -> dict:
    """Load personal situation from DB."""
    try:
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT key, value FROM personal_situation")
        data = {r["key"]: r["value"] for r in cur.fetchall()}
        conn.close()
        return data
    except Exception:
        return {}


def roth_conversion_analysis() -> dict:
    """Generate a Roth conversion ladder analysis with IRMAA calculations."""
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    acct_summaries = holdings.get("account_summaries", {})
    ira_value = sum(v.get("total_value", 0) for k, v in acct_summaries.items() if "rollover" in k.lower() or ("ira" in k.lower() and "roth" not in k.lower()))
    roth_value = sum(v.get("total_value", 0) for k, v in acct_summaries.items() if "roth" in k.lower())
    k401_value = sum(v.get("total_value", 0) for k, v in acct_summaries.items() if "401k" in k.lower())
    taxable_value = sum(v.get("total_value", 0) for k, v in acct_summaries.items() if "taxable" in k.lower() or "individual" in k.lower())

    ps = _load_personal()
    dob = ps.get("dob", "1967-08-21")
    age = ps.get("age", "58")
    ss_annual = ps.get("social_security_annual", "40000")
    ss_start = ps.get("social_security_start_age", "67")
    bracket = ps.get("current_bracket", "22")
    roth_ytd = ps.get("roth_conversion_ytd", "35000")
    roth_target = ps.get("roth_conversion_target", "51000")
    safe_room = ps.get("roth_safe_room_22pct", "16000")
    filing = ps.get("filing_status", "single")

    prompt = f"""/no_think You are Alex, a certified retirement planner specializing in Roth conversion, IRMAA optimization, and DISABILITY-OPTIMIZED retirement strategies.

CLIENT PROFILE:
DOB: {dob} (age {age})
Filing status: {filing} (Married Filing Separately — lived apart)
DISABILITY STATUS: On SSDI ($3,800/mo = $45,600/yr). Private disability insurance to age 68.5.
SSDI converts to SS retirement at FRA age {ss_start}: ~${ss_annual}/yr
Schedule C income: ~$20K/yr gross (this IS earned income — counts for IRA contributions)
No 10% early withdrawal penalty (age 58.5+ AND disability exemption IRC §72(t)(2)(A)(iii))
Current tax bracket: {bracket}%
Roth conversions YTD: ${roth_ytd}
Target conversion this year: ${roth_target} (safe room at 22%: ${safe_room})

DISABILITY-SPECIFIC RULES FOR ROTH LADDER:
- MFS filers: Roth contribution income limit is $0 → CANNOT contribute directly to Roth IRA
- Workaround: Backdoor Roth (Traditional IRA contribution → immediate conversion) IS allowed
- SSDI income is NOT earned income for IRA purposes — but Schedule C income IS
- Investment income (dividends, capital gains) does NOT affect SSDI (not SGA)
- Roth conversions increase MAGI → affects IRMAA, Medicaid, but NOT SSDI eligibility
- 401k rollover to IRA in 2027: timing matters — once rolled, no longer employer-plan protected
- Creditor protection: 401k has ERISA protection; IRA protection varies by state (NY: unlimited)
- KEY QUESTION: Should disabled person prioritize Roth ladder OR leave money in 401k/IRA for creditor protection + lower MAGI?

PORTFOLIO:
Rollover IRA: ${ira_value:,.0f}
Roth IRA: ${roth_value:,.0f}
401k: ${k401_value:,.0f}
Taxable: ${taxable_value:,.0f}
Total: ${ira_value + roth_value + k401_value + taxable_value:,.0f}

INCOME CONTEXT:
Current income: $14,342/yr from dividends. Target: $55,000/yr. Gap: $40,658.
Roth conversions YTD: ${roth_ytd}. Target: ${roth_target}. Safe room at {bracket}%: ${safe_room}.
Social Security at age {ss_start}: ~${ss_annual}/yr.

{_get_intel_context()}

Create a detailed 5-year Roth Conversion Ladder projection including:
1. Year-by-year conversion amounts and estimated federal tax at {bracket}% bracket
2. Cumulative penalty-free accessible amounts (5-year rule from each conversion year)
3. IRMAA MEDICARE SURCHARGE ANALYSIS (CRITICAL):
   - 2026 IRMAA thresholds for single filers:
     MAGI $103,000-$129,000: +$65.90/mo Part B, +$12.90/mo Part D
     MAGI $129,000-$161,000: +$164.80/mo Part B, +$33.30/mo Part D
     MAGI $161,000-$193,000: +$263.70/mo Part B, +$53.80/mo Part D
     MAGI $193,000-$500,000: +$362.60/mo Part B, +$74.20/mo Part D
     MAGI >$500,000: +$395.60/mo Part B, +$81.00/mo Part D
   - IRMAA uses 2-year lookback: 2026 conversions affect 2028 Medicare premiums
   - Calculate the MAGI impact of each year's conversion and the resulting IRMAA tier
   - Show the annual IRMAA surcharge cost vs the tax savings from Roth conversion
   - Recommend conversion amounts that stay below key IRMAA thresholds
4. How conversion affects retirement income strategy with Social Security at age {ss_start}
5. Tax bracket management: fill {bracket}% bracket optimally each year
6. Which IRA holdings to convert first (highest growth potential = convert early for max tax-free growth)
7. MEDICAID PLANNING IMPACT (CRITICAL FOR NY RESIDENTS):
   - Client may pursue Medicaid after Medicare (Dec 2026) for supplemental benefits
   - NY Medicaid income limit for single: ~$1,677/mo (~$20,124/yr) in 2026
   - Roth conversions count as MAGI income and WILL push above Medicaid thresholds
   - Medicaid Asset Protection Trust (MAPT) has 5-year lookback in NY
   - Show a table: for each conversion year, projected MAGI vs Medicaid income limit
   - Clearly state whether each year's conversion would disqualify Medicaid
   - TRADEOFF ANALYSIS: Quantify tax savings from Roth conversion vs value of potential Medicaid benefits
   - Recommend: should client prioritize Roth conversions OR Medicaid eligibility? Or is there a middle path?
   - Note: Roth IRAs ARE countable assets for NY Medicaid; MAPT-held assets are exempt after 5yr lookback
8. DISABILITY-SPECIFIC ROTH LADDER ANALYSIS:
   - Should you prioritize the Roth ladder OR leave money in 401k/IRA?
   - PRO-ROTH: Tax-free income in retirement, no RMDs, hedge against future tax increases
   - PRO-LEAVE: Creditor protection (ERISA for 401k), lower MAGI preserves Medicaid, simpler
   - Can you still contribute to IRA while on SSDI? YES — if you have earned income (Schedule C $20K)
   - MFS backdoor Roth strategy: contribute $7,000/yr to Traditional → convert (pro-rata rule applies if IRA has pre-tax funds)
   - Pro-rata warning: With $556K in Rollover IRA, backdoor Roth has massive pro-rata tax hit — NOT recommended until IRA is significantly reduced via conversions
   - Optimal disability strategy: Convert enough to fill 12%/22% bracket from IRA, then backdoor Roth becomes clean
   - Impact on private disability insurance: Roth conversions are not earned income — should NOT affect disability recertification
   - Impact on SSDI: Investment income and conversions do NOT count as SGA — SSDI is safe
9. Risks: tax law changes, bracket creep, IRMAA tier jumps, opportunity cost, Medicaid rule changes, disability benefit changes

Include clear tables. Use warm, professional, fiduciary tone. Address client as "you". Always address the Roth-vs-leave-in-401k question for disabled persons."""

    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from llm_router import get_llm_response
        result = get_llm_response("cio_synthesis", prompt, max_tokens=1000, high_impact=True)
        if result.get("success"):
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""INSERT INTO portfolio_intelligence_events (event_type, severity, source, payload)
                VALUES ('roth_conversion_analysis', 'high', 'alex_retirement_advisor.py', %s)""",
                (json.dumps({"ira": ira_value, "roth": roth_value, "provider": result.get("provider")}, default=str),))
            conn.commit()
            conn.close()
            return {"analysis": result["response"], "provider": result.get("provider"), "cost": result.get("cost_estimate", 0)}
    except Exception as e:
        return {"error": str(e)}
    return {"error": "LLM failed"}


def monthly_retirement_report(send_telegram: bool = False) -> dict:
    """Generate monthly retirement performance report with YTD vs scenarios, gap analysis, suggestions."""
    try:
        # get_tax_context is defined later in this file — query DB directly
        import psycopg2.extras
        _tc = _get_conn()
        _tcur = _tc.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        _tcur.execute("SELECT * FROM personal_tax_history WHERE tax_year=2026")
        _ts = _tcur.fetchone()
        _tc.close()
        bracket = 12
        room = 66883
        roth_ytd = 35000
        if _ts:
            agi = float(_ts.get("agi", 0) or 0)
            ded = max(float(_ts.get("itemized_deductions", 0) or 0), float(_ts.get("standard_deduction", 15700) or 15700))
            taxable = max(0, agi - ded)
            for low, high, rate in [(0,11600,10),(11600,47150,12),(47150,100525,22),(100525,191950,24)]:
                if taxable >= low: bracket = rate
            room = max(0, 100525 + ded - agi)
            roth_ytd = float(_ts.get("roth_conversions_total", 0) or 0)

        # Load current portfolio data
        holdings = json.loads((PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        totals = holdings.get("portfolio_totals", {})
        current_value = totals.get("total_value", 0)

        # Load roadmap for scenario projections
        roadmap = json.loads((PROJECT_ROOT / "data" / "portfolios" / "state" / "retirement_roadmap.json").read_text())
        tl = roadmap.get("timeline", [])
        rates = roadmap.get("rate_assumptions", {"conservative": 0.055, "base": 0.075, "aggressive": 0.096})

        # Find 2026 projections
        proj_2026 = next((r for r in tl if r.get("year") == 2026), None)
        start_value = tl[0].get("base", current_value) if tl else current_value
        ytd_return_pct = ((current_value / start_value) - 1) * 100 if start_value > 0 else 0

        # Income data
        div_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "dividend_calendar.json"
        annual_income = 14285
        if div_path.exists():
            dc = json.loads(div_path.read_text())
            annual_income = float(dc.get("total_annual", 14285))
        income_gap = 55000 - annual_income

        # Macro context
        macro = ""
        try:
            from external_market_data_ingest import get_macro_context
            macro = get_macro_context() or ""
        except Exception:
            pass

        # Outcome lessons for "What the System Learned" section
        lessons_text = ""
        try:
            import psycopg2.extras as _px2
            _lconn = _get_conn()
            _lcur = _lconn.cursor(cursor_factory=_px2.RealDictCursor)
            _lcur.execute("SELECT config FROM agent_intelligence_rules WHERE rule_type='outcome_lessons' AND rule_key='latest'")
            _lr = _lcur.fetchone()
            _lconn.close()
            if _lr and _lr.get("config"):
                cfg = _lr["config"]
                if isinstance(cfg, str):
                    cfg = json.loads(cfg)
                lessons_text = cfg.get("text", "")
        except Exception:
            pass

        from datetime import datetime as _dt
        month_name = _dt.now().strftime("%B %Y")

        prompt = f"""/no_think You are Alex, a disability-optimized retirement planner. Generate a Monthly Retirement Performance Report for {month_name}.

CLIENT: Age 58, SSDI $3,800/mo, MFS filing, Medicare Dec 2026, permanent disability.
Portfolio: ${current_value:,.0f} (started 2026 at ${start_value:,.0f}).
YTD return: {ytd_return_pct:+.1f}%
Annual income: ${annual_income:,.0f}/yr vs $55K target (gap: ${income_gap:,.0f}).
Tax: {bracket}% bracket, ${room:,.0f} room in 22%, Roth YTD: ${roth_ytd:,.0f}.
{macro}
2026 scenario projections (year-end):
  Conservative ({rates.get('conservative',0.055)*100:.1f}%): ${proj_2026.get('conservative',0) if proj_2026 else 0:,.0f}
  Base ({rates.get('base',0.075)*100:.1f}%): ${proj_2026.get('base',0) if proj_2026 else 0:,.0f}
  Aggressive ({rates.get('aggressive',0.096)*100:.1f}%): ${proj_2026.get('aggressive',0) if proj_2026 else 0:,.0f}

Provide MONTHLY RETIREMENT PERFORMANCE REPORT (under 400 words):

1. YTD PERFORMANCE: Actual ${current_value:,.0f} vs 3 scenarios. Which scenario are we tracking? On/ahead/behind pace?
2. MONTHLY TREND: Estimate Jan-{_dt.now().strftime('%b')} 2026 monthly values. Highlight best/worst months.
3. REST OF 2026 NEEDED: What return is needed rest-of-year to hit base scenario? Is it achievable given macro?
4. INCOME GAP ANALYSIS: ${income_gap:,.0f} gap to $55K. Progress this month. What closes it?
5. 3-5 ACTIONABLE SUGGESTIONS (disability/SSDI/IRMAA aware):
   - Specific dollar amounts and account names
   - Roth conversion pacing recommendation for rest of 2026
   - Any rebalancing moves with SSDI impact assessment
   - Medicaid/IRMAA implications of each suggestion
6. WHAT THE SYSTEM LEARNED THIS MONTH: Summarize key lessons from past decisions.
{f'   Agent outcome lessons: {lessons_text}' if lessons_text else '   No outcome lessons yet — decisions still accumulating.'}

Be specific with numbers. Use warm tone. Address disability implications for every suggestion."""

        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from llm_router import get_llm_response
        result = get_llm_response("cio_synthesis", prompt, max_tokens=800, high_impact=True)
        if not result.get("success"):
            # Fallback to local model if cloud providers unavailable
            result = get_llm_response("agent_narrative", prompt[:4000], max_tokens=600, high_impact=False)
        report = result.get("response", "Report unavailable") if result.get("success") else "Report generation failed"

        # Store in ai_reports
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""INSERT INTO ai_reports (report_type, title, content, provider)
                VALUES ('monthly_retirement', %s, %s, %s)""",
                (f"Monthly Retirement Report — {month_name}", report, result.get("provider", "")))
            conn.commit()
            conn.close()
        except Exception:
            pass

        if send_telegram:
            try:
                from telegram_alert import send_telegram as _tg
                divider = "\u2501" * 24
                _tg(f"\U0001F4CA *Alex: Monthly Retirement Report*\n_{month_name}_\n{divider}\n\n{report[:1800]}\n\n{divider}\n_via {result.get('provider','?')}_")
            except Exception:
                pass

        print(f"[alex] Monthly report generated via {result.get('provider', '?')}")
        return {"report": report, "provider": result.get("provider"), "cost": result.get("cost", 0)}
    except Exception as e:
        print(f"[alex] Monthly report error: {e}")
        return {"error": str(e)}


def scan_portfolio_for_alerts(send_telegram: bool = False) -> list:
    """Scan portfolio for significant moves and generate Alex analysis for each."""
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    enrichment = json.loads((STATE_DIR / "ticker_enrichment_cache.json").read_text()) if (STATE_DIR / "ticker_enrichment_cache.json").exists() else {}

    alerts = []
    seen = set()

    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        if not sym or sym in seen or h.get("is_cash"):
            continue
        seen.add(sym)
        mv = float(h.get("market_value", 0) or 0)
        if mv < 500:
            continue

        e = enrichment.get(sym, {}) if isinstance(enrichment.get(sym), dict) else {}
        rsi = float(e.get("rsi", 50) or 50)
        sma20 = float(e.get("sma20_pct", 0) or 0)
        sma50 = float(e.get("sma50_pct", 0) or 0)
        day_chg = float(h.get("day_change_pct", 0) or 0)

        trigger = None
        if abs(day_chg) > 3:
            trigger = f"Significant daily move: {day_chg:+.1f}%"
        elif rsi > 75:
            trigger = f"RSI overbought: {rsi:.0f}"
        elif rsi < 25:
            trigger = f"RSI oversold: {rsi:.0f}"
        elif abs(sma20) < 1.0 and abs(sma50) > 2:
            trigger = f"Crossing 20-day MA (SMA20: {sma20:+.1f}%)"

        if trigger:
            print(f"  [alex] Alert: {sym} — {trigger}")
            result = analyze_for_retirement(sym, trigger)
            if result.get("analysis"):
                alerts.append(result)

                if send_telegram:
                    msg = f"*Alex (Retirement Advisor): {sym}*\n_{trigger}_\n\n{result['analysis'][:1500]}\n\n_via {result.get('provider')} (${result.get('cost', 0):.4f})_"
                    try:
                        from telegram_alert import send_telegram as _send
                        _send(msg)
                    except Exception:
                        pass

    return alerts


if __name__ == "__main__":
    if "--medicare-estimate" in sys.argv:
        import psycopg2.extras as _pxe
        _c = _get_conn(); _cr = _c.cursor(cursor_factory=_pxe.RealDictCursor)
        _cr.execute("SELECT * FROM personal_tax_history WHERE tax_year=2026"); _s = _cr.fetchone()
        _c.close()
        _agi = float(_s.get("agi", 0) or 0) if _s else 0
        _roth = float(_s.get("roth_conversions_total", 0) or 0) if _s else 0
        ps = _load_personal()
        _medicare_date = ps.get("medicare_start_date", "2026-12-01")

        # IRMAA thresholds 2026 (single filer)
        irmaa_tiers = [
            (103000, 0, 0, "Base"),
            (103000, 65.90, 12.90, "Tier 1"),
            (129000, 164.80, 33.30, "Tier 2"),
            (161000, 263.70, 53.80, "Tier 3"),
            (193000, 362.60, 74.20, "Tier 4"),
            (500000, 395.60, 81.00, "Tier 5"),
        ]

        # NY Medicaid income limit (single, 2026 est)
        medicaid_income_limit = 20124  # ~$1,677/mo

        print(f"=== Medicare & Medicaid Estimate ===")
        print(f"Medicare eligibility: {_medicare_date}")
        print(f"Current 2026 estimated MAGI: ${_agi:,.0f}")
        print(f"  Roth conversions YTD: ${_roth:,.0f}")
        print()

        # Determine current IRMAA tier (2024 income affects 2026 premiums)
        print(f"--- 2026 IRMAA (based on 2024 MAGI) ---")
        print(f"  2024 MAGI determines 2026 premiums (2-year lookback)")
        print(f"  Standard Part B (2026): ~$185/mo")
        print(f"  Standard Part D: varies by plan")
        print()
        print(f"  IRMAA Surcharge Tiers (single filer):")
        print(f"  {'MAGI Range':<28} {'Part B Extra':>12} {'Part D Extra':>12} {'Annual Cost':>12}")
        print(f"  {'-'*28} {'-'*12} {'-'*12} {'-'*12}")
        for i, (threshold, part_b, part_d, label) in enumerate(irmaa_tiers):
            if i == 0:
                print(f"  {'< $103,000':<28} {'$0.00':>12} {'$0.00':>12} {'$0':>12}  ← Base")
            elif i < len(irmaa_tiers) - 1:
                next_t = irmaa_tiers[i+1][0] if i+1 < len(irmaa_tiers) else 0
                annual = (part_b + part_d) * 12
                rng = f"${threshold:,}–${next_t:,}"
                print(f"  {rng:<28} {'${:.2f}'.format(part_b):>12} {'${:.2f}'.format(part_d):>12} {'${:,.0f}'.format(annual):>12}")
            else:
                annual = (part_b + part_d) * 12
                print(f"  {'> $500,000':<28} {'${:.2f}'.format(part_b):>12} {'${:.2f}'.format(part_d):>12} {'${:,.0f}'.format(annual):>12}")

        # Project MAGI scenarios
        print()
        print(f"--- MAGI Projection Scenarios (2026) ---")
        scenarios = [
            ("No more conversions", _agi),
            ("Convert $15K more", _agi + 15000),
            ("Convert $35K more", _agi + 35000),
            ("Convert $50K more", _agi + 50000),
            ("Convert $67K more (fill 22%)", _agi + 67000),
        ]
        for label, magi in scenarios:
            tier_label = "Base"
            surcharge = 0
            for i in range(len(irmaa_tiers) - 1, 0, -1):
                if magi >= irmaa_tiers[i][0]:
                    tier_label = irmaa_tiers[i][3]
                    surcharge = (irmaa_tiers[i][1] + irmaa_tiers[i][2]) * 12
                    break
            medicaid_ok = "YES" if magi <= medicaid_income_limit else "NO"
            print(f"  {label:<30} MAGI: ${magi:,.0f}  IRMAA: {tier_label:<8} +${surcharge:,.0f}/yr  Medicaid eligible: {medicaid_ok}")

        print()
        print(f"--- Medicaid Planning (NY) ---")
        print(f"  Income limit (single, 2026 est): ${medicaid_income_limit:,}/yr (~$1,677/mo)")
        print(f"  Your projected 2026 MAGI: ${_agi:,.0f} → {'ELIGIBLE' if _agi <= medicaid_income_limit else 'NOT ELIGIBLE'}")
        print(f"  ANY Roth conversion income pushes MAGI above Medicaid threshold.")
        print(f"  Asset limit: Most assets countable (including Roth IRA).")
        print(f"  MAPT (Medicaid Asset Protection Trust): 5-year lookback in NY.")
        print(f"  If considering Medicaid, discuss MAPT timing with elder law attorney.")
        sys.exit(0)

    if "--tax-situation" in sys.argv:
        # Inline tax calc (get_tax_context defined later in file)
        import psycopg2.extras as _pxe
        _c = _get_conn(); _cr = _c.cursor(cursor_factory=_pxe.RealDictCursor)
        _cr.execute("SELECT * FROM personal_tax_history WHERE tax_year=2026"); _s = _cr.fetchone()
        _cr.execute("SELECT * FROM personal_tax_history WHERE tax_year=2025"); _p = _cr.fetchone()
        _c.close()
        _agi = float(_s.get("agi",0) or 0) if _s else 0
        _roth = float(_s.get("roth_conversions_total",0) or 0) if _s else 0
        _std = float(_s.get("standard_deduction",15700) or 15700) if _s else 15700
        _item = float(_s.get("itemized_deductions",0) or 0) if _s else 0
        _ded = max(_item, _std)
        _room = max(0, 100525 + _ded - _agi)
        _biz = abs(float(_p.get("business_loss",0) or 0)) if _p and float(_p.get("business_loss",0) or 0) < 0 else 0
        _br = 22 if _agi - _ded > 47150 else 12
        tc = {"agi":_agi,"roth_conversions_ytd":_roth,"current_bracket":_br,"bracket_room_22pct":_room,"max_additional_conversion":_room,"extra_from_loss":_biz}
        if tc.get('error'):
            print(f'Error: {tc["error"]}')
        else:
            print(f'=== 2026 Tax Situation ===')
            print(f'Estimated AGI: ${tc["agi"]:,.0f}')
            print(f'Roth conversions YTD: ${tc["roth_conversions_ytd"]:,.0f}')
            print(f'Current bracket: {tc["current_bracket"]}%')
            print(f'22% bracket room: ${tc["bracket_room_22pct"]:,.0f}')
            print(f'Max additional conversion at 22%: ${tc["max_additional_conversion"]:,.0f}')
            print(f'Business loss carryforward: ${tc["extra_from_loss"]:,.0f}')
            ps = _load_personal()
            print(f'Medicare starts: {ps.get("medicare_start_date", "unknown")}')
            print(f'Note: {ps.get("medicare_start_note", "")}')
            print(f'\n=== Disability Status ===')
            print(f'SSDI: $3,800/mo ($45,600/yr)')
            print(f'Filing: MFS (Married Filing Separately)')
            print(f'Private disability ins: to age 68.5')
            print(f'Early withdrawal: No 10% penalty (disability + age 58.5+)')
            print(f'IRA contributions: YES with Schedule C earned income ($7K/yr max)')
            print(f'Roth contributions: NO (MFS $0 limit) — use Backdoor Roth')
            print(f'Roth conversions: OK but increase MAGI (affects Medicaid, IRMAA)')
            print(f'SSDI impact: Investment income does NOT affect SSDI eligibility')
        sys.exit(0)
    if "--alert" in sys.argv:
        sym = sys.argv[sys.argv.index("--alert") + 1].upper()
        r = analyze_for_retirement(sym, "manual_alert")
        if r.get("analysis"):
            print(f"*Alex: {sym}*\n\n{r['analysis']}")
            print(f"\n_Provider: {r.get('provider')} | Cost: ${r.get('cost', 0):.4f}_")
        else:
            print(f"Error: {r.get('error')}")
    elif "--roth-ladder" in sys.argv:
        r = roth_conversion_analysis()
        if r.get("analysis"):
            print(r["analysis"])
            print(f"\n_Provider: {r.get('provider')} | Cost: ${r.get('cost', 0):.4f}_")
        else:
            print(f"Error: {r.get('error')}")
    elif "--analyze" in sys.argv:
        sym = sys.argv[sys.argv.index("--analyze") + 1].upper()
        r = analyze_for_retirement(sym, "manual_analysis")
        if r.get("analysis"):
            print(r["analysis"])
        else:
            print(f"Error: {r.get('error')}")
    elif "--monthly-report" in sys.argv:
        tg = "--telegram" in sys.argv
        r = monthly_retirement_report(send_telegram=tg)
        if r.get("report"):
            print(r["report"])
            print(f"\n_Provider: {r.get('provider')} | Cost: ${r.get('cost', 0):.4f}_")
        else:
            print(f"Error: {r.get('error')}")
    elif "--scan-portfolio" in sys.argv:
        tg = "--telegram" in sys.argv
        alerts = scan_portfolio_for_alerts(send_telegram=tg)
        print(f"[alex] Generated {len(alerts)} retirement advisor alerts")
    elif "--json" in sys.argv and len(sys.argv) > 2:
        pass
    else:
        print("Usage:")
        print("  --alert SYMBOL       Analyze a price alert")
        print("  --analyze SYMBOL     Full retirement analysis")
        print("  --roth-ladder        5-year Roth conversion ladder with IRMAA + Medicaid")
        print("  --monthly-report     Monthly retirement performance report")
        print("  --tax-situation      Current tax bracket and conversion room")
        print("  --medicare-estimate  Medicare/IRMAA premium + Medicaid eligibility estimate")
        print("  --scan-portfolio     Scan all holdings for alerts")
        print("  Add --telegram to send results via Telegram")
        print("  Add --json for JSON output")


def get_tax_context(tax_year: int = 2026) -> dict:
    """Load current tax situation for Alex's analysis."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Current year summary
    cur.execute("SELECT * FROM personal_tax_history WHERE tax_year=%s", (tax_year,))
    summary = cur.fetchone()

    # Tax events this year
    cur.execute("SELECT * FROM tax_events WHERE tax_year=%s ORDER BY event_date", (tax_year,))
    events = cur.fetchall()

    # Prior year for comparison
    cur.execute("SELECT * FROM personal_tax_history WHERE tax_year=%s", (tax_year - 1,))
    prior = cur.fetchone()

    conn.close()

    if not summary:
        return {"error": f"No tax data for {tax_year}"}

    agi = float(summary.get("agi", 0) or 0)
    itemized = float(summary.get("itemized_deductions", 0) or 0)
    std_ded = float(summary.get("standard_deduction", 15700) or 15700)
    deduction = max(itemized, std_ded)
    roth_ytd = float(summary.get("roth_conversions_total", 0) or 0)

    # 2026 single brackets
    brackets = [
        (0, 11600, 10), (11600, 47150, 12), (47150, 100525, 22),
        (100525, 191950, 24), (191950, 243725, 32), (243725, 609350, 35), (609350, float('inf'), 37)
    ]

    taxable = max(0, agi - deduction)
    current_bracket = 10
    for low, high, rate in brackets:
        if taxable >= low:
            current_bracket = rate

    # Room to top of 22% bracket
    top_22 = 100525 + deduction  # AGI at which taxable income hits top of 22%
    bracket_room = max(0, top_22 - agi)

    # Business loss carryforward
    biz_loss = float(prior.get("business_loss", 0) or 0) if prior else 0

    return {
        "tax_year": tax_year,
        "agi": agi,
        "deduction": deduction,
        "deduction_type": "itemized" if itemized > std_ded else "standard",
        "taxable_income": taxable,
        "current_bracket": current_bracket,
        "roth_conversions_ytd": roth_ytd,
        "bracket_room_22pct": bracket_room,
        "max_additional_conversion": bracket_room,
        "top_of_22pct_agi": top_22,
        "business_loss_prior": biz_loss,
        "extra_from_loss": abs(biz_loss) if biz_loss < 0 else 0,
        "events": [dict(e) for e in events],
        "prior_year_agi": float(prior["agi"]) if prior else None,
    }
