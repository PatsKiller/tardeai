"""monthly_advisory.py — Dual-AI monthly advisory analysis.
Generates two competing advisory perspectives from the full portfolio:
  1. Opus — Conservative, fiduciary, risk-aware, long-term
  2. Sonnet — Opportunity-focused, direct, conviction-driven
Both pull from the same live data. Monthly run only.
"""
import json, os, sys, time, requests
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from llm_net import post_retry
except Exception:
    def post_retry(url, json_payload, timeout=120, **_):  # fallback: plain post if helper missing
        return requests.post(url, json=json_payload, timeout=timeout)

OPUS   = "claude-opus-4-20250514"   # legacy paid (no longer the default — see free local lanes below)
GPT4O  = "gpt-4o"                    # legacy paid
# Gate 4 (2026-06-07): monthly advisory runs on FREE local Ollama models by default — no paid API.
# Dual perspective preserved: 27b (deep fiduciary) + 12b (alternative). Override via env.
FIDUCIARY_MODEL = os.environ.get("MONTHLY_ADVISORY_FIDUCIARY_MODEL", "gemma3:27b")
ALT_MODEL       = os.environ.get("MONTHLY_ADVISORY_ALT_MODEL", "gemma3:12b")


def _call_local(prompt, model, max_tokens=2500):
    """FREE local Ollama call (no paid API). Returns text or an error string (never raises)."""
    try:
        r = post_retry("http://127.0.0.1:11434/api/chat", {
            "model": model, "stream": False, "messages": [{"role": "user", "content": prompt}],
            "options": {"num_ctx": 16384, "num_predict": max_tokens, "temperature": 0.3}},
            timeout=600, attempts=2, base=2.0)
        return r.json().get("message", {}).get("content", "").strip() or "(empty local response)"
    except Exception as e:
        return f"Error (local {model}): {str(e)[:200]}"

def _get_key(provider):
    """Get API key for 'anthropic' or 'openai'."""
    env_var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    key = os.getenv(env_var, "").strip()
    if not key:
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith(f"{env_var}="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return key

def _call_claude(prompt, model, max_tokens=2000):
    key = _get_key("anthropic")
    if not key:
        return "Anthropic API key not available."
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=180)
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        return f"Error: {str(e)[:200]}"

def _call_openai(prompt, model=GPT4O, max_tokens=2000):
    key = _get_key("openai")
    if not key:
        return "OpenAI API key not available."
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=180)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Error: {str(e)[:200]}"

def _build_portfolio_context(portfolio, analysis, risk, perf_history,
                              retirement, tax_proj, rebalancing, dividends_cal):
    """Build comprehensive context string from all data sources."""
    totals = portfolio.get("portfolio_totals", {})
    holdings = portfolio.get("holdings", [])
    accts = portfolio.get("account_summaries", {})
    sectors = portfolio.get("resolved_sectors", [])
    periods = (perf_history or {}).get("periods", {})
    kd = (retirement or {}).get("key_dates", {})
    gw = (retirement or {}).get("golden_window", {})
    flags = (analysis or {}).get("critical_flags", [])
    divs = (analysis or {}).get("dividends", {})
    stops_data = {}
    try:
        sp = Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state" / "stops.json"
        if sp.exists():
            stops_data = json.loads(sp.read_text())
    except: pass

    # Top holdings
    by_sym = {}
    for h in holdings:
        s = h.get("symbol", "")
        by_sym[s] = by_sym.get(s, 0) + (h.get("market_value", 0) or 0)
    top = sorted(by_sym.items(), key=lambda x: -x[1])[:15]
    tv = totals.get("total_value", 0)

    top_lines = "\n".join(
        f"  {sym}: ${mv:,.0f} ({mv/tv*100:.1f}%)" for sym, mv in top if mv > 100
    )
    acct_lines = "\n".join(
        f"  {k}: ${v.get('total_value',0):,.0f} (gain: {v.get('gain_pct',0):.1f}%)"
        for k, v in accts.items() if v.get("total_value", 0) > 0
    )
    sector_lines = "\n".join(
        f"  {s['sector']}: {s['pct']:.1f}%" for s in sectors[:8]
    ) if sectors else "  Not populated"
    perf_lines = "\n".join(
        f"  {k}: {p.get('change_pct',0):+.2f}% (${p.get('change',0):+,.0f})"
        for k, p in periods.items()
        if isinstance(p, dict) and p.get("change_pct") is not None and k != "ALL"
    )
    flag_lines = "\n".join(
        f"  [{f.get('severity','?')}] {f.get('message','')[:100]}" for f in (flags or [])[:5]
    ) if flags else "  None"
    # stops.json also carries top-level freshness metadata.  Only mapping
    # values represent stop records; metadata must never abort the advisory
    # stage with an AttributeError.
    stop_lines = "\n".join(
        f"  {sym}: stop=${d.get('stop',0)} notes={d.get('notes','')}"
        for sym, d in stops_data.items()
        if isinstance(d, dict)
    ) if stops_data else "  None configured"
    if not stop_lines:
        stop_lines = "  None configured"

    div_total = divs.get("total_annual_income", 0) or 0
    if not div_total:
        try:
            dc = json.loads((Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state" / "dividend_calendar.json").read_text())
            div_total = sum(p.get("annual_income", 0) or 0 for p in dc.get("payers", []))
        except: pass

    rebal_total = (rebalancing or {}).get("total_to_rebalance", 0) or 0
    beta = 0.38  # pipeline-derived
    roth_bal = accts.get("schwab_roth", {}).get("total_value", 0)
    trad_bal = accts.get("schwab_rollover_ira", {}).get("total_value", 0) + accts.get("fidelity_401k", {}).get("total_value", 0)

    return f"""FULL PORTFOLIO DATA — {datetime.now().strftime('%Y-%m-%d')}

OWNER: John W. Whiting, age {(retirement or {}).get('current_age', 58.7):.1f}
Income: SSDI $45,600/yr + Schedule C ~$20K gross. MFS filing.
Conservative risk profile. Disability insurance to age 68.5.
Golden Window: {kd.get('golden_window_start','Feb 2036')} to {kd.get('golden_window_end','Aug 2040')}
2026 Roth conversion: $35K done, ~$16K remaining in 22% bracket.

PORTFOLIO: ${tv:,.0f}
All-Time Gain: ${totals.get('total_gain',0):+,.0f} (+{totals.get('total_gain_pct',0):.1f}%)
Day Change: ${totals.get('day_change',0):+,.0f}
Annual Dividends: ${div_total:,.0f} (target: $28,000)
Portfolio Beta: {beta:.2f} (pipeline-derived)
Rebalancing Needed: ${rebal_total:,.0f}

ACCOUNTS:
{acct_lines}

Roth IRA: ${roth_bal:,.0f}
Traditional/Pre-Tax: ${trad_bal:,.0f}

TOP HOLDINGS:
{top_lines}

SECTOR EXPOSURE:
{sector_lines}

PERFORMANCE:
{perf_lines}

CRITICAL FLAGS:
{flag_lines}

STOP-LOSS LEVELS:
{stop_lines}

TAX: Bracket 22% MFS. Estimated federal: ${(tax_proj or {}).get('tax',{}).get('estimated_federal',0) or 0:,.0f}
Roth ladder: ${gw.get('optimal_annual_conversion',50000):,.0f}/yr optimal during Golden Window
"""


def run_monthly_advisory(portfolio, analysis, risk, perf_history,
                         retirement, tax_proj, rebalancing, state_dir, root="."):
    """Generate dual-perspective monthly advisory. Returns dict with opus + sonnet results."""
    state_dir = Path(state_dir)
    div_cal = {}
    try:
        dc_path = state_dir / "dividend_calendar.json"
        if dc_path.exists():
            div_cal = json.loads(dc_path.read_text())
    except: pass

    ctx = _build_portfolio_context(portfolio, analysis, risk, perf_history,
                                    retirement, tax_proj, rebalancing, div_cal)

    # Curated-LLM wiring pilot (2026-06-07): inject Hermes self-learning context (promoted research +
    # recent trade lessons) so the monthly advisory benefits from accumulated Hermes intelligence and
    # improves over time. Advisory-only; fails open (never blocks the report).
    try:
        from llm_context_engine import get_hermes_knowledge
        _hk = get_hermes_knowledge(context_type='monthly_advisory', limit=6)
        if _hk:
            ctx = ctx + "\n\n" + _hk
    except Exception:
        pass

    # ── OPUS PROMPT: Conservative, fiduciary, risk-aware ──────────
    opus_prompt = f"""{ctx}

You are a fiduciary wealth advisor managing this portfolio for a conservative, SSDI-dependent client approaching retirement. Your duty is capital preservation, tax efficiency, and income reliability.

Provide a structured monthly advisory with these EXACT sections (use markdown headers):

## Market Context
2-3 sentences on macro regime, interest rates, valuations relevant to this portfolio.

## Sell / Trim Recommendations
For each recommendation, provide: Ticker, Current %, Reason, Suggested Trim $, Expected Outcome.
Format as a markdown table. Only recommend sells/trims you can justify from the data.

## New Buy / Watchlist
For each: Ticker, Category, Suggested $, Conviction (High/Medium/Low), Rationale, Expected Yield.
Format as a markdown table. Focus on income, diversification, and risk reduction.

## Top 3 Rebalancing Moves
Numbered list with $ impact and priority (Immediate/This Quarter/Monitor).

## Risk & Tax Alpha
Bulleted list of specific risk mitigations and tax opportunities with $ estimates.

## Executive Recommendation
3-4 decisive sentences. State the single most important action. Be specific with dollar amounts and tickers.

Rules:
- Conservative bias. Protect capital first.
- Every recommendation must reference specific data from above.
- Never invent tickers or numbers not in the data.
- Acknowledge data gaps honestly.
- End with: "For informational purposes only. Not investment advice."
"""

    # ── SONNET PROMPT: Opportunity-focused, direct ────────────────
    sonnet_prompt = f"""{ctx}

You are an aggressive but disciplined portfolio strategist focused on maximizing risk-adjusted returns and finding opportunities others miss. This client has 10 years before needing withdrawals — use that time horizon.

Provide a structured monthly advisory with these EXACT sections (use markdown headers):

## Market Context
2-3 bold sentences on where opportunities are and what risks to exploit or hedge.

## Sell / Trim Recommendations
For each: Ticker, Current %, Reason, Suggested Trim $, Expected Outcome.
Markdown table. Be decisive — if something should go, say it clearly.

## New Buy / Watchlist
For each: Ticker, Category, Suggested $, Conviction (High/Medium/Low), Rationale, Expected Edge.
Markdown table. Include at least one contrarian pick with clear thesis.

## Top 3 Rebalancing Moves
Numbered list with $ impact, priority, and why NOW matters.

## Quick Wins & Tax Alpha
Bulleted list of immediately actionable items with estimated $ impact.

## Executive Recommendation
3-4 sentences. Be direct. "Do this now" language. State your highest-conviction move.

Rules:
- Opportunity-focused but disciplined. Don't be reckless.
- Every recommendation backed by data above.
- Never invent tickers or numbers.
- Show conviction levels clearly.
- End with: "For informational purposes only. Not investment advice."
"""

    results = {
        "generated_at": datetime.now().isoformat(),
        "opus": None,
        "opus_model": FIDUCIARY_MODEL,
        "gpt4o": None,
        "gpt4o_model": ALT_MODEL,
    }

    print(f"  [advisory] Generating fiduciary advisory (conservative) — {FIDUCIARY_MODEL} (free local)...")
    results["opus"] = _call_local(opus_prompt, FIDUCIARY_MODEL, max_tokens=2500)
    time.sleep(1)

    print(f"  [advisory] Generating alternative advisory (opportunity-focused) — {ALT_MODEL} (free local)...")
    results["gpt4o"] = _call_local(sonnet_prompt, ALT_MODEL, max_tokens=2500)

    # Save to state
    cache_path = state_dir / "monthly_advisory.json"
    cache_path.write_text(json.dumps(results, indent=2))
    print(f"  [advisory] ✅ Dual advisory saved (Opus: {len(results['opus'] or '')} chars, GPT-4o: {len(results['gpt4o'] or '')} chars)")

    return results
