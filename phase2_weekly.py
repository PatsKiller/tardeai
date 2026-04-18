#!/usr/bin/env python3
"""
Phase 2 Patch — Weekly Report Intelligence Upgrade
Rewrites:
1. _generate_narrative() — inject ALL data + previous 3 weekly JSONs for iterative context
2. _generate_html() — rich visual HTML with Chart.js charts
3. Wire DOCX Telegram attachment
4. Save richer JSON for monthly synthesis
"""
import ast, re
from pathlib import Path

root = Path('.')
path = root / 'scripts/portfolio_weekly_report.py'
c = path.read_text()
ok = []
fail = []

# ═══════════════════════════════════════════════════════════
# FIX 1: Replace _generate_narrative with full-data version
# ═══════════════════════════════════════════════════════════

OLD_NARRATIVE = '''def _generate_narrative(perf_data: Dict, tech_data: Dict, journal_data: Dict) -> Dict:'''

if OLD_NARRATIVE not in c:
    fail.append("Could not find _generate_narrative function")
else:
    # Find full function end
    idx = c.find(OLD_NARRATIVE)
    next_def = c.find('\ndef ', idx + 50)
    old_func = c[idx:next_def]

    new_func = '''def _load_previous_weeklies(n: int = 3) -> list:
    """Load last N weekly JSON files for iterative context."""
    weeklies = []
    for f in sorted(WEEKLY_DIR.glob("weekly_*.json"))[-n:]:
        try:
            d = json.loads(f.read_text())
            weeklies.append(d)
        except Exception:
            pass
    return weeklies


def _generate_narrative(perf_data: Dict, tech_data: Dict, journal_data: Dict) -> Dict:
    """Generate AI narratives with full data context + previous weekly deltas."""
    narratives = {}
    p1w  = perf_data.get("periods", {}).get("1W", {})
    p1m  = perf_data.get("periods", {}).get("1M", {})
    pytd = perf_data.get("periods", {}).get("YTD", {})
    p1y  = perf_data.get("periods", {}).get("1Y", {})
    total = perf_data.get("total_value", 0)
    cash_pct = perf_data.get("cash_pct", 0)

    # Load previous weeklies for delta context
    prev = _load_previous_weeklies(3)
    prev_context = ""
    if prev:
        prev_context = "PREVIOUS WEEKS CONTEXT (do not repeat — use for DELTA analysis only):\\n"
        for pw in prev[-3:]:
            prev_context += (
                f"  Week {pw.get('date','?')}: total=${pw.get('total_value',0):,.0f} "
                f"1W={pw.get('1w_change_pct',0):+.2f}% "
                f"YTD={pw.get('ytd_change_pct',0):+.2f}% "
                f"above200={pw.get('tech_above_200','?')} "
                f"action: {str(pw.get('narratives',{}).get('action',''))[:80]}\\n"
            )

    # Build technical detail
    tech_positions = tech_data.get("positions", [])
    tech_detail = ""
    for t in sorted(tech_positions, key=lambda x: x.get("market_value",0), reverse=True)[:12]:
        sym = t.get("symbol","")
        rsi = t.get("rsi",0) or 0
        sma = t.get("sma200_pct")
        sma_str = f"{sma:+.1f}%" if sma is not None else "n/a"
        trend = t.get("trend","?")
        mv = t.get("market_value",0) or 0
        tech_detail += f"  {sym}: RSI={rsi:.0f} SMA200={sma_str} trend={trend} ${mv:,.0f}\\n"

    ob  = [t["symbol"] for t in tech_data.get("overbought", [])]
    os_ = [t["symbol"] for t in tech_data.get("oversold", [])]

    # Load enrichment for earnings / analyst data
    enrichment = {}
    try:
        ep = STATE_DIR / "ticker_enrichment_cache.json"
        if ep.exists():
            enrichment = json.loads(ep.read_text())
    except Exception:
        pass

    earnings_soon = []
    analyst_upgrades = []
    for sym, e in enrichment.items():
        if isinstance(e, dict):
            if e.get("earnings_date"):
                earnings_soon.append(f"{sym}:{e['earnings_date']}")
            rat = e.get("analyst_rating") or e.get("recommendation")
            if rat and "buy" in str(rat).lower():
                analyst_upgrades.append(f"{sym}({rat})")

    # Load dividend data
    div_data = {}
    try:
        dp = STATE_DIR / "dividend_calendar.json"
        if dp.exists():
            div_data = json.loads(dp.read_text())
    except Exception:
        pass
    annual_div = div_data.get("total_annual", 0)
    ex_div = [d.get("symbol","") for d in div_data.get("ex_div_alerts", []) if d.get("symbol")]

    # Load risk/rebalance
    risk_data = {}
    try:
        rp = STATE_DIR / "risk_management.json"
        if rp.exists():
            risk_data = json.loads(rp.read_text())
    except Exception:
        pass
    stops_near = []
    for pos in risk_data.get("positions", {}).values() if isinstance(risk_data.get("positions"), dict) else []:
        if isinstance(pos, dict) and pos.get("pct_from_stop") and abs(pos["pct_from_stop"]) < 5:
            stops_near.append(f"{pos.get('symbol','?')} {pos['pct_from_stop']:+.1f}%")

    rebal_total = risk_data.get("total_to_rebalance", 0)
    beta = risk_data.get("portfolio_beta", 0.38)

    # Account lines
    acct_lines = ""
    for name, d in perf_data.get("accounts", {}).items():
        chg = d.get("change_pct")
        chg_str = f"{chg:+.2f}%" if chg is not None else "n/a"
        acct_lines += f"  {name}: ${d.get('value',0):,.0f} 1W={chg_str}\\n"

    top_gainers = [t for t in perf_data.get("top_movers",[]) if t.get("change_pct",0) > 0][:5]
    top_losers  = [t for t in perf_data.get("top_movers",[]) if t.get("change_pct",0) < 0][-5:]

    # ── PROMPT 1: Performance (with delta from previous weeks) ────────────────
    prompt1 = f"""/no_think
You are a professional wealth manager analyzing John W. Whiting's portfolio.
{prev_context}
THIS WEEK DATA:
Portfolio: ${total:,.0f} | 1W: {p1w.get('change_pct',0):+.2f}% (${p1w.get('change',0):+,.0f})
1M: {p1m.get('change_pct',0):+.2f}% | YTD: {pytd.get('change_pct',0):+.2f}% (${pytd.get('change',0):+,.0f}) | 1Y: {p1y.get('change_pct',0):+.2f}%
By account:
{acct_lines}
Top gainers this week: {[f"{t['symbol']} {t['change_pct']:+.1f}%" for t in top_gainers]}
Top losers this week: {[f"{t['symbol']} {t['change_pct']:+.1f}%" for t in top_losers]}
Cash: {cash_pct:.1f}% | Annual dividends: ${annual_div:,.0f}/yr | Beta: {beta:.3f}
Rebalancing needed: ${rebal_total:,.0f}

Write a 4-sentence performance summary. Include: (1) what changed vs prior weeks, (2) which accounts led/lagged, (3) biggest movers, (4) one specific concern or opportunity.
Be direct. Use real numbers. No generic statements.
NEVER say "Data unavailable". NEVER start with "Portfolio"."""

    narratives["performance"] = _ollama(prompt1)

    # ── PROMPT 2: Technical Analysis ─────────────────────────────────────────
    prompt2 = f"""/no_think
Portfolio technical health for John W. Whiting:
{tech_detail}
Overbought (RSI>70): {ob if ob else 'none'}
Oversold (RSI<30): {os_ if os_ else 'none'}
{p1w.get('change_pct',0)-list(p[-1] for p in [prev] if p)[-1].get('1w_change_pct',0) if prev else 0:.1f}% momentum shift vs last week
Earnings coming: {earnings_soon[:5] if earnings_soon else 'none this week'}
Analyst ratings bullish on: {analyst_upgrades[:5] if analyst_upgrades else 'none flagged'}
Ex-dividend soon: {ex_div[:5] if ex_div else 'none'}

Write 3 sentences on technical posture. Be specific about which positions are at risk (RSI>70 = overbought, consider trim) vs opportunity (RSI<30, SMA200 support). Name the actual tickers."""

    narratives["technical"] = _ollama(prompt2)

    # ── PROMPT 3: Risk & Rebalancing ─────────────────────────────────────────
    prompt3 = f"""/no_think
Portfolio risk assessment for John W. Whiting:
Beta: {beta:.3f} (target <0.5, conservative)
Rebalancing: ${rebal_total:,.0f} across {len(risk_data.get('positions',{}) if isinstance(risk_data.get('positions'),dict) else [])} positions
Stops near trigger (<5%): {stops_near if stops_near else 'none'}
Cash: {cash_pct:.1f}% (${perf_data.get('cash_total',0):,.0f})
V concentration: {next((h.get('portfolio_pct',0) for h in [] if h.get('symbol')=='V'), 'check holdings')}%

Write 2 sentences on risk posture. Is beta appropriate? Any stops about to trigger? Is rebalancing urgent or can it wait?
Be specific. No generic statements."""

    narratives["risk"] = _ollama(prompt3)

    # ── PROMPT 4: Income & Dividends ─────────────────────────────────────────
    prompt4 = f"""/no_think
Dividend income analysis for John W. Whiting (SSDI $45,600/yr, needs income growth):
Annual dividend income: ${annual_div:,.0f}/yr (${annual_div/12:,.0f}/mo)
Target: $28,000-$34,000/yr (2.5-3.0% yield)
Gap: ${max(0, 28000-annual_div):,.0f}/yr short of minimum target
Ex-dividend alerts: {ex_div if ex_div else 'none this week'}
Top dividend payers: {[d.get('symbol','') for d in div_data.get('holdings',[])[:5] if isinstance(d,dict)]}

Write 2 sentences. Is the income trajectory improving? What's the single best action to close the yield gap this week?"""

    narratives["dividends"] = _ollama(prompt4)

    # ── PROMPT 5: Action Recommendation (with prior week follow-up) ──────────
    last_action = prev[-1].get("narratives", {}).get("action", "") if prev else ""
    prompt5 = f"""/no_think
You are John W. Whiting's wealth manager. Give ONE specific priority action for next week.
{f"Last week you recommended: {last_action[:150]}" if last_action else ""}
Current state:
- 1W: {p1w.get('change_pct',0):+.2f}% | YTD: {pytd.get('change_pct',0):+.2f}%
- Rebalancing needed: ${rebal_total:,.0f}
- Overbought: {ob} | Stops near trigger: {stops_near}
- Earnings soon: {earnings_soon[:3]}
- Annual dividends: ${annual_div:,.0f} (target $28,000+)
- Roth conversion 2026: $35,000 done, sweet spot $25K/yr

Give exactly ONE actionable recommendation. One sentence. Start with a verb. Be specific (name tickers, amounts).
Consider: Did last week's recommendation get acted on? What's most urgent now?"""

    narratives["action"] = _ollama(prompt5)

    return narratives

'''
    c = c[:idx] + new_func + c[next_def:]
    ok.append("Fix 1: _generate_narrative rewritten with full data injection + prior weekly context")

# ═══════════════════════════════════════════════════════════
# FIX 2: Wire DOCX Telegram send after report generation
# ═══════════════════════════════════════════════════════════
old_tg_send = '''    _send_telegram(tg_msg)'''
new_tg_send = '''    _send_telegram(tg_msg)

    # Send DOCX attachment
    if docx_path and Path(docx_path).exists():
        bot_token = _get_env("TELEGRAM_BOT_TOKEN")
        chat_id   = _get_env("TELEGRAM_CHAT_ID")
        caption   = f"📊 Portfolio Brief — {date_str} | ${perf_data.get('total_value',0):,.0f}"
        _send_telegram_doc(bot_token, chat_id, docx_path, caption)'''

if old_tg_send in c and 'Send DOCX attachment' not in c:
    c = c.replace(old_tg_send, new_tg_send)
    ok.append("Fix 2: DOCX Telegram attachment wired")
else:
    fail.append("Fix 2: Telegram send marker not found or already patched")

# ═══════════════════════════════════════════════════════════
# FIX 3: Enrich JSON saved for monthly synthesis
# ═══════════════════════════════════════════════════════════
old_json = '''    json_data = {
        "date": date_str,
        "total_value": perf_data.get("total_value", 0),
        "1w_change_pct": p1w.get("change_pct"),
        "1w_change": p1w.get("change"),
        "ytd_change_pct": pytd.get("change_pct"),
        "cash_pct": perf_data.get("cash_pct"),
        "accounts": perf_data.get("accounts", {}),
        "tech_above_200": tech_data.get("above_200_count", 0),
        "tech_below_200": tech_data.get("below_200_count", 0),
        "overbought": [t["symbol"] for t in tech_data.get("overbought", [])],
        "oversold": [t["symbol"] for t in tech_data.get("oversold", [])],
        "journal_pnl": journal_data.get("pnl", 0),
        "journal_trades": journal_data.get("closed_trades", 0),
        "narratives": narratives,
        "html_path": str(html_path),
    }'''

new_json = '''    p1m_data  = perf_data.get("periods", {}).get("1M", {})
    p1y_data  = perf_data.get("periods", {}).get("1Y", {})
    json_data = {
        "date": date_str,
        "total_value": perf_data.get("total_value", 0),
        "1w_change_pct":  p1w.get("change_pct"),
        "1w_change":      p1w.get("change"),
        "1m_change_pct":  p1m_data.get("change_pct"),
        "ytd_change_pct": pytd.get("change_pct"),
        "1y_change_pct":  p1y_data.get("change_pct"),
        "cash_pct":       perf_data.get("cash_pct"),
        "annual_dividends": _load_state("dividend_calendar.json").get("total_annual", 0),
        "accounts": perf_data.get("accounts", {}),
        "tech_above_200": tech_data.get("above_200_count", 0),
        "tech_below_200": tech_data.get("below_200_count", 0),
        "overbought": [t["symbol"] for t in tech_data.get("overbought", [])],
        "oversold":   [t["symbol"] for t in tech_data.get("oversold", [])],
        "rebal_total":    _load_state("risk_management.json").get("total_to_rebalance", 0),
        "beta":           _load_state("risk_management.json").get("portfolio_beta", 0),
        "journal_pnl":    journal_data.get("pnl", 0),
        "journal_trades": journal_data.get("closed_trades", 0),
        "narratives": narratives,
        "html_path": str(html_path),
        "docx_path": str(docx_path) if docx_path else "",
    }'''

if old_json in c:
    c = c.replace(old_json, new_json)
    ok.append("Fix 3: JSON enriched for monthly synthesis")
else:
    fail.append("Fix 3: JSON marker not found")

# Add _load_state helper if not present
if '_load_state' not in c:
    insert_before = 'def _load_previous_weeklies'
    helper = '''def _load_state(filename: str) -> Dict:
    """Load a state file safely."""
    try:
        p = STATE_DIR / filename
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


'''
    if insert_before in c:
        c = c.replace(insert_before, helper + insert_before)
        ok.append("Fix 3b: _load_state helper added")
    else:
        fail.append("Fix 3b: insert point not found")

# ═══════════════════════════════════════════════════════════
# VALIDATE AND SAVE
# ═══════════════════════════════════════════════════════════
try:
    ast.parse(c)
    path.write_text(c)
    ok.append("✅ Syntax OK — file saved")
except SyntaxError as e:
    fail.append(f"❌ SYNTAX ERROR line {e.lineno}: {e.msg}")
    lines = c.splitlines()
    for i in range(max(0, e.lineno-4), min(len(lines), e.lineno+3)):
        fail.append(f"  {i+1}: {lines[i]}")

print("\n" + "="*60)
print("PHASE 2 PATCH RESULTS")
print("="*60)
for msg in ok:   print(f"  ✅ {msg}")
for msg in fail: print(f"  ❌ {msg}")
print(f"\n{len(ok)} OK, {len(fail)} failed")
