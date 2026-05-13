#!/usr/bin/env python3
"""Run the deep overnight LLM queue using gemma3-overnight.

Processes queued items in priority order with time budgeting, checkpointing,
and hard stop enforcement.

Usage:
    .venv/bin/python scripts/run_deep_overnight_llm_queue.py --dry-run --limit 5
    .venv/bin/python scripts/run_deep_overnight_llm_queue.py --limit 100 --time-budget-min 240
    .venv/bin/python scripts/run_deep_overnight_llm_queue.py --hard-stop 03:00 --limit 100
    .venv/bin/python scripts/run_deep_overnight_llm_queue.py --force-job-types risk_synthesis --limit 1

Does NOT touch broker, holdings, execution, or trading behavior.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


def get_db_connection():
    import psycopg2
    env_path = PROJ / ".env"
    env_vars = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} [deep-queue] {msg}", flush=True)


def past_hard_stop(hard_stop_str):
    """Check if current time is past the hard stop time."""
    if not hard_stop_str:
        return False
    now = datetime.now()
    h, m = map(int, hard_stop_str.split(":"))
    # Handle midnight crossing: if hard_stop is 03:00 and now is 02:00, not past
    # If now is 04:00, past
    # If hard_stop is 03:00 and now is 23:00, not past (we haven't crossed midnight yet)
    stop_today = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if h < 12:  # stop is in early morning (e.g., 03:00)
        if now.hour >= 12:  # we're in the evening, haven't crossed midnight
            return False
        else:  # we're in early morning, compare directly
            return now >= stop_today
    return now >= stop_today


def build_prompt(job):
    """Build a gemma3-overnight prompt for the given job."""
    job_type = job["job_type"]
    symbol = job.get("symbol") or "N/A"
    reasons = job.get("reason_codes") or []
    qwen_summary = job.get("last_qwen_summary") or ""
    meta = job.get("metadata_json") or {}

    if job_type == "strategy_classification":
        # Load actual enrichment data to prevent hallucination
        enrich_ctx = ""
        try:
            conn_tmp = get_db_connection()
            c = conn_tmp.cursor()
            c.execute("""SELECT rsi, perf_week_pct, data->>'price' as price,
                                data->>'sector' as sector, data->>'div_yield' as div_yield,
                                data->>'rvol' as rvol, data->>'beta' as beta,
                                data->>'pe' as pe, data->>'sma200' as sma200
                         FROM ticker_snapshot_daily
                         WHERE symbol = %s ORDER BY snapshot_date DESC LIMIT 1""", [symbol])
            row = c.fetchone()
            if row:
                rsi, pw, price, sector, dy, rvol, beta, pe, sma200 = row
                enrich_ctx = (f"\nACTUAL DATA (use these numbers, do not invent):\n"
                              f"  Price: ${price} | RSI: {rsi} | RVOL: {rvol}x\n"
                              f"  Sector: {sector} | Beta: {beta} | P/E: {pe}\n"
                              f"  Week perf: {pw}% | Div yield: {dy}% | SMA200: {sma200}\n")
            # Current classification
            c.execute("""SELECT strategy_type, confidence, classification_source
                         FROM ticker_strategy_classifications
                         WHERE symbol=%s AND active=true LIMIT 1""", [symbol])
            cls = c.fetchone()
            if cls:
                enrich_ctx += f"  Current strategy: {cls[0]} (confidence: {cls[1]}, source: {cls[2]})\n"
            conn_tmp.close()
        except Exception:
            pass

        return f"""Analyze the trading strategy classification for {symbol}.

Current classification reasons: {', '.join(reasons)}
Prior summary: {qwen_summary[:1000] if qwen_summary else 'None available'}
{enrich_ctx}
Provide a structured deep review using ONLY the data above.
Do NOT invent prices, ratios, or metrics not provided.

1. CLASSIFICATION ASSESSMENT: Is the current strategy assignment appropriate?
2. EVIDENCE QUALITY: How strong is the evidence supporting this classification?
3. ALTERNATIVE STRATEGIES: Should any other strategies be considered?
4. RISK FLAGS: Any concerns about this position or classification?
5. RECOMMENDATION: Keep current classification, reclassify, or flag for manual review?

Be concise and direct. Use structured format."""

    elif job_type == "closed_trade_review":
        # Load actual trade data to prevent hallucination
        trade_ctx = ""
        history_ctx = ""
        try:
            conn_tmp = get_db_connection()
            c = conn_tmp.cursor()
            c.execute("""SELECT id, symbol, account, open_date, close_date, trade_type,
                                buy_price, sell_price, pnl, pnl_pct, hold_days, stop_used, r_multiple, setup, note
                         FROM trade_closed WHERE id = %s""", [job.get('trade_id')])
            row = c.fetchone()
            if row:
                tid, sym, acct, od, cd, tt, bp, sp, pnl_val, pp, hd, su, rm, setup, note = row
                trade_ctx = (f"\nACTUAL TRADE DATA (use these numbers, do not invent):\n"
                             f"  Entry: ${bp} on {od} | Exit: ${sp} on {cd}\n"
                             f"  Type: {tt} | Hold: {hd} days\n"
                             f"  P&L: ${pnl_val} ({pp}%)\n"
                             f"  Stop used: {'$' + str(su) if su else 'NONE'}\n"
                             f"  R-multiple: {rm or 'N/A'}\n"
                             f"  Setup: {setup or 'N/A'} | Note: {(note or '')[:100]}\n")
            # Past trades on this symbol
            c.execute("""SELECT pnl, pnl_pct, hold_days, stop_used, close_date
                         FROM trade_closed WHERE symbol = %s ORDER BY close_date DESC LIMIT 10""", [symbol])
            past = c.fetchall()
            if past:
                wins = sum(1 for r in past if (r[0] or 0) > 0)
                losses = sum(1 for r in past if (r[0] or 0) < 0)
                total_pnl = sum(r[0] or 0 for r in past)
                stops_used = sum(1 for r in past if r[3])
                history_ctx = (f"\nPAST {symbol} TRADES ({len(past)} total): {wins}W {losses}L, total ${total_pnl:.0f}\n"
                               f"  Stops used: {stops_used}/{len(past)} trades\n")
            conn_tmp.close()
        except Exception:
            pass

        return f"""Review the closed trade for {symbol}.

Trade ID: {job.get('trade_id')}
Account: {job.get('account', 'N/A')}
Review triggers: {', '.join(reasons)}
{trade_ctx}{history_ctx}
Provide a structured post-trade analysis using ONLY the data above.
Do NOT invent numbers, dates, or claim patterns not supported by the data.

1. OUTCOME ASSESSMENT: Was this trade well-executed given the setup?
2. ENTRY/EXIT QUALITY: Was timing and sizing appropriate?
3. RISK MANAGEMENT: Were stops and position sizing followed?
4. LESSONS LEARNED: What can be improved for similar setups?
5. PATTERN MATCH: Does this trade fit a recurring pattern based on the history above?

Be concise and direct. Focus on actionable lessons."""

    elif job_type in ("auto_journal_review", "manual_journal_review"):
        return f"""Review the trade journal entry for {symbol}.

Journal ID: {job.get('journal_id')}
Review type: {job_type}
Review triggers: {', '.join(reasons)}

Provide a structured journal analysis:
1. EXECUTION QUALITY: How well was the trade plan followed?
2. EMOTIONAL FACTORS: Were there emotional influences on decisions?
3. BEHAVIORAL PATTERNS: Does this entry reveal recurring patterns?
4. IMPROVEMENT AREAS: Specific actionable improvements for next trade.
5. COACHING NOTES: What would a trading coach highlight?

Be concise and direct. Focus on behavioral insights."""

    elif job_type == "proposal_review":
        prop_ctx = ""
        try:
            conn_tmp = get_db_connection()
            c = conn_tmp.cursor()
            c.execute("""SELECT proposed_entry, proposed_stop, proposed_target1, proposed_shares,
                                strategy_id, signal_score, signal_grade, catalyst, catalyst_verified,
                                screener_name, created_at
                         FROM paper_trade_proposals WHERE id = %s""", [job.get('trade_id')])
            row = c.fetchone()
            if row:
                pe, ps, pt, sh, sid, sc, sg, cat, cv, scr, ca = row
                rr = round((float(pt) - float(pe)) / (float(pe) - float(ps)), 1) if pe and ps and pt and float(pe) > float(ps) else 0
                risk = round(abs(float(pe) - float(ps)) * int(sh), 2) if pe and ps and sh else 0
                prop_ctx = (f"\nACTUAL PROPOSAL DATA:\n"
                            f"  Strategy: {sid} | Grade: {sg} | Score: {sc}\n"
                            f"  Entry: ${pe} | Stop: ${ps} | Target: ${pt}\n"
                            f"  Shares: {sh} | Risk: ${risk} | R:R: {rr}:1\n"
                            f"  Catalyst: {(str(cat) or 'None')[:80]} {'(verified)' if cv else '(unverified)'}\n"
                            f"  Source: {scr} | Created: {ca}\n")
            # RSI/RVOL for timing assessment
            c.execute("""SELECT rsi, data->>'rvol' as rvol, data->>'price' as price
                         FROM ticker_snapshot_daily WHERE symbol=%s ORDER BY snapshot_date DESC LIMIT 1""", [symbol])
            snap = c.fetchone()
            if snap:
                prop_ctx += f"  Current: price=${snap[2]} RSI={snap[0]} RVOL={snap[1]}x\n"
            conn_tmp.close()
        except Exception:
            pass

        return f"""Deep review of trade proposal for {symbol}.

Proposal ID: {job.get('trade_id')}
Account: {job.get('account', 'N/A')}
Review triggers: {', '.join(reasons)}
{prop_ctx}
Provide a structured proposal assessment using ONLY the data above.
Do NOT invent prices, scores, or catalyst details.

1. THESIS QUALITY: Is the trade thesis well-supported?
2. RISK/REWARD: Is the risk/reward ratio appropriate?
3. TIMING: Is the entry timing favorable given current RSI/RVOL?
4. SIZING: Is position sizing appropriate for the risk?
5. RECOMMENDATION: Approve, modify, or reject with specific reasons?

Be concise and direct."""

    elif job_type == "risk_synthesis":
        # Load portfolio context for risk synthesis
        portfolio_ctx = ""
        try:
            import json as _json
            hdata = _json.load(open(str(PROJ / "data/portfolios/state/holdings.json")))
            total_val = hdata["portfolio_totals"]["total_value"]
            top_holdings = sorted(hdata.get("holdings", []),
                                  key=lambda h: h.get("market_value", 0), reverse=True)[:20]
            lines = [f"  {h.get('symbol','?')}: ${h.get('market_value',0):,.0f} "
                     f"({h.get('portfolio_pct',0):.1f}%)" for h in top_holdings]
            portfolio_ctx = f"\nPortfolio: ${total_val:,.0f}\nTop holdings:\n" + "\n".join(lines)
        except Exception:
            portfolio_ctx = "\nPortfolio data unavailable."

        return f"""Synthesize current portfolio risk for overnight assessment.
{portfolio_ctx}

Provide a structured risk report:
1. CONCENTRATION RISK: Any over-concentrated positions or sectors?
2. CORRELATION RISK: Are positions too correlated?
3. DRAWDOWN RISK: Current drawdown vs max acceptable?
4. EVENT RISK: Any upcoming events that could impact the portfolio?
5. ACTION ITEMS: Specific risk-reduction recommendations.

Respond as JSON: {{"top_risks": [{{"symbol":"SYM","risk_type":"type","severity":"HIGH/MEDIUM/LOW","action":"action"}}], "narrative": "3 paragraph prose", "priority_action": "single most important action"}}"""

    elif job_type == "rag_content_curation":
        source_table = job.get("source_table") or meta.get("source_table", "")
        source_id = job.get("source_id") or meta.get("source_id", "")
        return f"""You are a financial intelligence curator. Evaluate this content for a trading RAG knowledge base.

Source: {source_table} ID {source_id}
Symbol: {symbol}
Queue reasons: {', '.join(reasons)}

Evaluate for: novelty, source credibility, relevance to active trading decisions, timeliness.

Respond as JSON: {{"verdict": "APPROVE_BOOST|APPROVE_STANDARD|LOW_QUALITY|SUPERSEDED", "weight": 1.5|1.0|0.0, "reason": "one sentence", "key_signal": "most important fact or null"}}

APPROVE_BOOST (1.5): High-quality, novel, clear trading signal.
APPROVE_STANDARD (1.0): Relevant, adequate. Normal weight.
LOW_QUALITY (0.0): Generic, repetitive, no signal.
SUPERSEDED (null): Already covered by better content."""

    elif job_type == "recovery_watch_review":
        recovery_ctx = ""
        try:
            conn_tmp = get_db_connection()
            c = conn_tmp.cursor()
            c.execute("""SELECT exit_price, stop_price, stopped_out_at, reason, thesis_at_exit,
                                status, setup_name, realized_pnl
                         FROM stopped_out_watch WHERE symbol=%s AND is_active=true LIMIT 1""", [symbol])
            sw = c.fetchone()
            if sw:
                recovery_ctx = (f"\nACTUAL RECOVERY DATA:\n"
                                f"  Exit price: ${sw[0]} | Stop: ${sw[1]} | Stopped: {sw[2]}\n"
                                f"  Reason: {sw[3]} | Setup: {sw[5]}\n"
                                f"  Thesis at exit: {(str(sw[4]) or 'N/A')[:200]}\n"
                                f"  Realized P&L: ${sw[7]}\n")
            c.execute("""SELECT data->>'price' as price, rsi, perf_week_pct
                         FROM ticker_snapshot_daily WHERE symbol=%s ORDER BY snapshot_date DESC LIMIT 1""", [symbol])
            snap = c.fetchone()
            if snap and sw:
                try:
                    cur_price = float(snap[0] or 0)
                    exit_p = float(sw[0] or 0)
                    recovery_pct = ((cur_price - exit_p) / exit_p * 100) if exit_p > 0 else 0
                    recovery_ctx += f"  Current: ${snap[0]} RSI={snap[1]} Week={snap[2]}% Recovery: {recovery_pct:+.1f}% from exit\n"
                except Exception:
                    pass
            conn_tmp.close()
        except Exception:
            pass

        return f"""You are a portfolio recovery analyst. Evaluate whether {symbol}'s original buy thesis remains valid after being stopped out.

Review triggers: {', '.join(reasons)}
{recovery_ctx}
Using ONLY the data above, evaluate:
1. Was the stop-out from temporary conditions or fundamental deterioration?
2. Has the situation improved, worsened, or stayed the same?
3. Is the original thesis still intact?
4. What is the re-entry risk?

Respond as JSON: {{"verdict": "THESIS_INTACT|THESIS_INVALIDATED|NEEDS_MORE_DATA", "confidence": 0.0-1.0, "reentry_risk": "HIGH|MEDIUM|LOW", "recommended_action": "REENTER_NOW|WAIT_FOR_CATALYST|STAY_CASH|CLOSE_WATCH", "key_factor": "single most important factor"}}"""

    elif job_type == "covered_call_scoring":
        cc_ctx = ""
        try:
            conn_tmp = get_db_connection()
            c = conn_tmp.cursor()
            c.execute("""SELECT data->>'price' as price, rsi, data->>'beta' as beta,
                                data->>'div_yield' as div_yield, data->>'rvol' as rvol,
                                perf_week_pct, data->>'sma50_pct' as sma50
                         FROM ticker_snapshot_daily WHERE symbol=%s ORDER BY snapshot_date DESC LIMIT 1""", [symbol])
            snap = c.fetchone()
            if snap:
                cc_ctx = (f"\nACTUAL DATA:\n"
                          f"  Price: ${snap[0]} | RSI: {snap[1]} | Beta: {snap[2]}\n"
                          f"  Div yield: {snap[3]}% | RVOL: {snap[4]}x | Week: {snap[5]}%\n"
                          f"  SMA50 distance: {snap[6]}%\n")
            c.execute("""SELECT recommendation, confidence_score FROM aegis_covered_call_candidates
                         WHERE symbol=%s LIMIT 1""", [symbol])
            cc = c.fetchone()
            if cc:
                cc_ctx += f"  Aegis recommendation: {cc[0]} (confidence: {cc[1]})\n"
            conn_tmp.close()
        except Exception:
            pass

        return f"""You are an options income specialist. Evaluate {symbol} for covered call selling.

Queue reasons: {', '.join(reasons)}
{cc_ctx}
Using ONLY the data above, evaluate:
1. Is this an appropriate time to sell covered calls?
2. What strike price OTM % would you target?
3. Estimated monthly premium yield?
4. Assignment risk?

Respond as JSON: {{"verdict": "FAVORABLE|MARGINAL|SKIP", "strike_target_pct_otm": 2.0-10.0, "estimated_monthly_yield_pct": 0.0-5.0, "assignment_risk": "HIGH|MEDIUM|LOW", "rationale": "two sentences", "timing": "NOW|WAIT_FOR_PULLBACK|NOT_SUITABLE"}}"""

    elif job_type == "weekly_behavioral_review":
        return f"""You are a trading coach reviewing behavioral patterns across closed trades.

Identify:
1. Time-of-day patterns
2. Strategy win/loss patterns
3. Hold duration patterns
4. Position sizing patterns
5. Emotional/behavioral patterns

Respond as JSON: {{"patterns": [{{"type": "pattern_type", "observation": "specific data", "severity": "HIGH|MEDIUM|LOW", "recommendation": "behavior change"}}], "top_strength": "best pattern", "top_weakness": "worst pattern", "summary": "two paragraph coaching"}}"""

    elif job_type == "rebalance_analysis":
        # Rebalance uses its own dedicated script with full context loading
        return None  # Signal to use dedicated handler instead of generic prompt

    elif job_type == "strategy_opportunity_scan":
        # Load top watchlist symbols with enrichment data
        try:
            import psycopg2.extras
            conn_tmp = get_db_connection()
            c = conn_tmp.cursor()
            c.execute("""
                SELECT DISTINCT sd.symbol, sd.rsi,
                       sd.data->>'sector' as sector,
                       sd.data->>'price' as price,
                       sd.data->>'div_yield' as div_yield,
                       sd.perf_week_pct,
                       sd.data->>'rvol' as rvol
                FROM ticker_snapshot_daily sd
                WHERE sd.snapshot_date = (SELECT MAX(snapshot_date) FROM ticker_snapshot_daily)
                  AND sd.symbol IN (
                      SELECT symbol FROM ticker_strategy_classifications WHERE active = true
                      UNION SELECT symbol FROM watchlist_items WHERE active = true
                  )
                ORDER BY CAST(NULLIF(sd.data->>'rvol','') AS FLOAT) DESC NULLS LAST
                LIMIT 40
            """)
            symbols = c.fetchall()
            conn_tmp.close()

            symbol_lines = []
            for sym, rsi, sector, price, div_yield, perf_week, rvol in symbols:
                symbol_lines.append(
                    f"  {sym}: sector={sector} price={price} rsi={rsi} "
                    f"div={div_yield}% week={perf_week}% rvol={rvol}x")
        except Exception:
            symbol_lines = ["  (data unavailable)"]

        underutilized = [
            "income_add", "sector_rotation", "defense_thesis",
            "covered_call_income", "dividend_growth_compounder",
            "high_yield_income_bdc", "recovery_watch", "core_growth_compounder",
            "reit_income", "bond_income", "tax_loss_harvest"
        ]

        return f"""You are a strategy diversification analyst. Review these watchlist symbols
and identify which ones fit UNDERUTILIZED strategies overlooked by momentum screening.

WATCHLIST SYMBOLS (top 40):
{chr(10).join(symbol_lines)}

UNDERUTILIZED STRATEGIES:
{chr(10).join(f'  - {s}' for s in underutilized)}

CRITERIA:
- income_add: div yield >3%, stable price, income-generating
- sector_rotation: outperforming sector peers, relative strength
- defense_thesis: aerospace/defense/govt contractor, macro tailwind
- covered_call_income: stable price, can sell premium, not too volatile
- dividend_growth_compounder: consistent dividend growth, 5yr+ history
- high_yield_income_bdc: BDC/CEF/REIT, >6% yield, institutional quality
- recovery_watch: recently sold off, thesis intact, waiting for catalyst
- core_growth_compounder: steady EPS growth, durable competitive advantage
- reit_income: REIT with stable yield and occupancy
- bond_income: bond ETF/fund, interest rate sensitive
- tax_loss_harvest: positions with unrealized losses for year-end harvesting

Only flag genuine fits. Respond as JSON:
{{"opportunities": [{{"symbol": "TICKER", "strategy": "strategy_id", "fit_score": 0-100, "rationale": "one sentence", "urgency": "HIGH|MEDIUM|LOW"}}], "summary": "2 sentence overview", "most_underutilized": "strategy with most opportunity"}}"""

    elif job_type == "income_strategy_scan":
        # Load income universe from snapshot data
        try:
            conn_tmp = get_db_connection()
            c = conn_tmp.cursor()
            c.execute("""
                SELECT DISTINCT sd.symbol, sd.data->>'div_yield' as div_yield,
                       sd.data->>'price' as price, sd.data->>'sector' as sector,
                       sd.data->>'beta' as beta, sd.data->>'pe' as pe
                FROM ticker_snapshot_daily sd
                WHERE sd.snapshot_date = (SELECT MAX(snapshot_date) FROM ticker_snapshot_daily)
                  AND (CAST(NULLIF(sd.data->>'div_yield','') AS FLOAT) > 2
                       OR sd.symbol IN (SELECT symbol FROM incubator_universe
                                        WHERE strategy_id IN ('income_add','dividend_growth_compounder',
                                                              'high_yield_income_bdc','covered_call_income')))
                ORDER BY CAST(NULLIF(sd.data->>'div_yield','') AS FLOAT) DESC NULLS LAST
                LIMIT 40
            """)
            symbols = c.fetchall()
            conn_tmp.close()
            lines = [f"  {s[0]}: yield={s[1]}% price={s[2]} sector={s[3]} beta={s[4]} pe={s[5]}" for s in symbols]
        except Exception:
            lines = ["  (data unavailable)"]

        return f"""You are an income investing specialist. Evaluate these symbols for 4 income strategies.

INCOME UNIVERSE ({len(lines)} symbols):
{chr(10).join(lines)}

STRATEGIES:
- income_add: yield 3-8%, stable/growing dividend, beta <0.8, fits IRA
- dividend_growth_compounder: dividend growth >5%/yr 5+ years, yield 2-4%, strong balance sheet
- high_yield_income_bdc: BDC/CEF/REIT >6% yield, institutional quality, covered distribution
- covered_call_income: stable price, liquid options, 1-3%/month premium potential

Respond as JSON:
{{"candidates": [{{"symbol": "TICKER", "strategy": "strategy_id", "fit_score": 0-100, "yield_assessment": "sustainable|at_risk", "rationale": "one sentence"}}], "top_pick": "best income add", "income_gap_assessment": "summary"}}"""

    elif job_type == "growth_strategy_scan":
        try:
            conn_tmp = get_db_connection()
            c = conn_tmp.cursor()
            c.execute("""
                SELECT DISTINCT sd.symbol, sd.data->>'sector' as sector,
                       sd.data->>'price' as price, sd.perf_week_pct,
                       sd.data->>'rvol' as rvol, sd.data->>'eps_growth_5yr' as eps_g
                FROM ticker_snapshot_daily sd
                WHERE sd.snapshot_date = (SELECT MAX(snapshot_date) FROM ticker_snapshot_daily)
                  AND (sd.perf_week_pct > 3
                       OR sd.symbol IN (SELECT symbol FROM incubator_universe
                                        WHERE strategy_id IN ('core_growth_compounder',
                                                              'sector_rotation','defense_thesis')))
                ORDER BY sd.perf_week_pct DESC NULLS LAST
                LIMIT 40
            """)
            symbols = c.fetchall()
            conn_tmp.close()
            lines = [f"  {s[0]}: sector={s[1]} price={s[2]} week={s[3]}% rvol={s[4]}x eps_g={s[5]}" for s in symbols]
        except Exception:
            lines = ["  (data unavailable)"]

        return f"""You are a growth equity analyst. Evaluate these symbols for 3 growth strategies.

GROWTH UNIVERSE ({len(lines)} symbols):
{chr(10).join(lines)}

STRATEGIES:
- core_growth_compounder: consistent EPS growth >10%/yr, strong ROE, durable moat, 10yr hold
- sector_rotation: leading its sector this week/month, relative strength vs peers
- defense_thesis: aerospace/defense/gov-IT, contract backlog, AI-defense exposure

Respond as JSON:
{{"candidates": [{{"symbol": "TICKER", "strategy": "strategy_id", "fit_score": 0-100, "thesis": "two sentences", "timeframe": "months|years", "rationale": "one sentence"}}], "sector_rotation_call": "which sector to rotate into", "top_growth_pick": "single best compounder"}}"""

    elif job_type == "reversion_strategy_scan":
        try:
            conn_tmp = get_db_connection()
            c = conn_tmp.cursor()
            c.execute("""
                SELECT DISTINCT sd.symbol, sd.rsi, sd.data->>'price' as price,
                       sd.data->>'sma200' as sma200, sd.perf_week_pct,
                       sd.data->>'div_yield' as div_yield
                FROM ticker_snapshot_daily sd
                WHERE sd.snapshot_date = (SELECT MAX(snapshot_date) FROM ticker_snapshot_daily)
                  AND (sd.rsi < 40
                       OR sd.symbol IN ('BND','TLT','IEF','SHY','VTIP','AGG','LQD',
                                        'SGOV','BIL','SHV','USFR')
                       OR sd.symbol IN (SELECT symbol FROM incubator_universe
                                        WHERE strategy_id IN ('swing_trade','recovery_watch',
                                                              'bond_income','cash_or_stable')))
                ORDER BY sd.rsi ASC NULLS LAST
                LIMIT 40
            """)
            symbols = c.fetchall()
            conn_tmp.close()
            lines = [f"  {s[0]}: rsi={s[1]} price={s[2]} sma200={s[3]} week={s[4]}% yield={s[5]}" for s in symbols]
        except Exception:
            lines = ["  (data unavailable)"]

        return f"""You are a mean-reversion and income analyst. Evaluate these symbols.

REVERSION UNIVERSE ({len(lines)} symbols):
{chr(10).join(lines)}

STRATEGIES:
- swing_trade retracement: RSI <40, above 200d SMA, pulling back from strength, buyable dip
- bond_income: treasury/bond ETFs, duration positioning for current rate environment
- cash_or_stable: money market alternatives, stable value, productive cash parking

Respond as JSON:
{{"retracement_candidates": [{{"symbol": "TICKER", "pullback_pct": -5.2, "thesis_intact": true, "rationale": "why buyable dip"}}], "bond_recommendation": {{"duration": "short|medium|long", "suggested_etf": "TICKER", "rationale": "rate reasoning"}}, "cash_parking": "best cash alternative", "top_retracement_pick": "best retracement setup"}}"""

    else:
        return f"""Deep LLM review for {symbol or 'portfolio'}.

Job type: {job_type}
Triggers: {', '.join(reasons)}

Provide a structured analysis with:
1. KEY FINDINGS
2. RISK FLAGS
3. RECOMMENDATIONS

Be concise and direct."""


def _safe_cc_float(val):
    """Safely convert LLM output to float for numeric DB columns.
    Handles range strings like '1.5-3.0' by taking the midpoint."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if '-' in s and not s.startswith('-'):
        parts = s.split('-')
        try:
            return round((float(parts[0]) + float(parts[1])) / 2, 2)
        except (ValueError, IndexError):
            return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def call_gemma(prompt, model="gemma3-overnight", timeout=300):
    """Call gemma3-overnight via Ollama. Returns (text, runtime_sec) or (None, 0)."""
    url = f"{OLLAMA_URL}/api/chat"
    payload = json.dumps({
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.2, "num_predict": 500},
    }).encode()

    start = time.monotonic()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            text = data.get("message", {}).get("content", "").strip()
            elapsed = round(time.monotonic() - start, 1)
            tokens = data.get("eval_count", 0)
            log(f"  gemma response: {elapsed}s, {tokens} tokens")
            return text, elapsed
    except Exception as e:
        elapsed = round(time.monotonic() - start, 1)
        log(f"  gemma ERROR: {e} ({elapsed}s)")
        return None, elapsed


def _apply_curation_verdict(cur, job, parsed):
    """Write curation verdict back to source content table."""
    source_table = job.get("source_table")
    source_id = job.get("source_id")
    verdict = parsed.get("verdict", "LOW_QUALITY")
    weight = parsed.get("weight")
    if not source_table or not source_id:
        return
    new_rag = "approved" if verdict in ("APPROVE_BOOST", "APPROVE_STANDARD") else None
    if source_table == "news_articles":
        sql = "UPDATE news_articles SET deep_curation_verdict=%s, deep_curation_at=NOW(), deep_curation_weight=%s"
        params = [verdict, weight]
        if new_rag:
            sql += ", rag_status=%s"
            params.append(new_rag)
        sql += " WHERE id=%s"
        params.append(source_id)
        cur.execute(sql, params)
    elif source_table == "youtube_transcripts":
        sql = "UPDATE youtube_transcripts SET deep_curation_verdict=%s, deep_curation_at=NOW(), deep_curation_weight=%s"
        params = [verdict, weight]
        if new_rag:
            sql += ", rag_status=%s"
            params.append(new_rag)
        sql += " WHERE id=%s"
        params.append(source_id)
        cur.execute(sql, params)


def _save_risk_synthesis(cur, queue_id, parsed):
    """Save risk synthesis narrative to dedicated results table."""
    try:
        hdata = json.load(open(str(PROJ / "data/portfolios/state/holdings.json")))
        total_val = hdata["portfolio_totals"]["total_value"]
    except Exception:
        total_val = None
    cur.execute("""
        INSERT INTO risk_synthesis_results
            (portfolio_value, top_risks, narrative, morning_brief_ready, queue_id)
        VALUES (%s, %s, %s, TRUE, %s)
    """, [total_val,
          json.dumps(parsed.get("top_risks", [])),
          parsed.get("narrative", ""),
          queue_id])


def recover_stale_running(cur):
    """Reset jobs stuck in 'running' from previous failed runs (>30 min old)."""
    cur.execute("""
        UPDATE deep_overnight_llm_queue
        SET status = 'pending',
            attempt_count = attempt_count,
            last_error = COALESCE(last_error, '') || ' [recovered from stale running]',
            updated_at = NOW()
        WHERE status = 'running'
        AND started_at < NOW() - INTERVAL '30 minutes'
        RETURNING id, job_type, symbol
    """)
    recovered = cur.fetchall()
    if recovered:
        log(f"Recovered {len(recovered)} stale running jobs")
        for rid, jtype, sym in recovered:
            log(f"  recovered: #{rid} {jtype} {sym}")
    return len(recovered)


def main():
    parser = argparse.ArgumentParser(description="Run deep overnight LLM queue")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run")
    parser.add_argument("--limit", type=int, default=100, help="Max jobs to process (default 100)")
    parser.add_argument("--time-budget-min", type=int, default=240, help="Time budget in minutes")
    parser.add_argument("--hard-stop", type=str, default="03:00", help="Hard stop time HH:MM")
    parser.add_argument("--job-types", type=str, default=None,
                        help="Comma-separated job types to process")
    parser.add_argument("--force-job-types", type=str, default=None,
                        help="Force specific job types to run (comma-separated), ignoring priority order")
    args = parser.parse_args()

    # Handle --force-job-types overriding --job-types
    if args.force_job_types:
        args.job_types = args.force_job_types

    model = os.getenv("LOCAL_LLM_MODEL", "gemma3-overnight")
    log(f"Queue runner starting — model={model}, limit={args.limit}, "
        f"budget={args.time_budget_min}m, hard_stop={args.hard_stop}"
        f"{', force_types=' + args.force_job_types if args.force_job_types else ''}")

    conn = get_db_connection()
    cur = conn.cursor()

    # Recover stale running jobs
    recovered = recover_stale_running(cur)
    conn.commit()

    # Build query for pending jobs
    type_filter = ""
    type_params = []
    if args.job_types:
        types = [t.strip() for t in args.job_types.split(",")]
        placeholders = ",".join(["%s"] * len(types))
        type_filter = f"AND job_type IN ({placeholders})"
        type_params = types

    cur.execute(f"""
        SELECT id, job_type, symbol, trade_id, journal_id, account,
               priority_tier, priority_score, reason_codes,
               last_qwen_summary, last_qwen_confidence, metadata_json,
               attempt_count, input_hash,
               source_table, source_id
        FROM deep_overnight_llm_queue
        WHERE status = 'pending'
        {type_filter}
        ORDER BY priority_score DESC, queued_at ASC
        LIMIT %s
    """, type_params + [args.limit])

    jobs = cur.fetchall()
    columns = [desc[0] for desc in cur.description]

    log(f"Found {len(jobs)} pending jobs")

    if args.dry_run:
        log("=== DRY RUN ===")
        for i, row in enumerate(jobs[:50]):
            job = dict(zip(columns, row))
            sym = job.get("symbol") or f"#{job.get('trade_id') or job.get('journal_id') or '?'}"
            reasons = job.get("reason_codes") or []
            log(f"  {i+1:>3}. [{job['priority_tier']}:{job['priority_score']:>3}] "
                f"{job['job_type']:>25} {sym:>8} — {','.join(reasons[:3])}")
        log(f"Would process up to {len(jobs)} jobs in {args.time_budget_min} minutes")
        conn.close()
        return

    # Process jobs
    start_time = time.monotonic()
    budget_sec = args.time_budget_min * 60
    processed = 0
    succeeded = 0
    failed = 0

    for row in jobs:
        job = dict(zip(columns, row))
        job_id = job["id"]
        elapsed = time.monotonic() - start_time

        # Time budget check
        if elapsed >= budget_sec:
            log(f"Time budget exhausted ({args.time_budget_min}m). Stopping.")
            break

        # Hard stop check
        if past_hard_stop(args.hard_stop):
            log(f"Hard stop {args.hard_stop} reached. Stopping.")
            break

        sym = job.get("symbol") or f"#{job.get('trade_id') or job.get('journal_id') or '?'}"
        log(f"Processing #{job_id}: {job['job_type']} {sym} "
            f"[{job['priority_tier']}:{job['priority_score']}] "
            f"(elapsed={int(elapsed)}s)")

        # Mark as running
        cur.execute("""
            UPDATE deep_overnight_llm_queue
            SET status = 'running', started_at = NOW(),
                attempt_count = attempt_count + 1, updated_at = NOW()
            WHERE id = %s
        """, (job_id,))
        conn.commit()

        # Special dispatch for rebalance_analysis (uses dedicated script)
        if job["job_type"] == "rebalance_analysis":
            try:
                from rebalance_deep_analyzer import run_analysis
                _start = time.monotonic()
                _res = run_analysis(conn, queue_id=job_id)
                runtime = round(time.monotonic() - _start, 1)
                if _res.get("error"):
                    text = None
                else:
                    text = _res.get("executive_summary", "Rebalance complete")
                    # Store in results table via the analyzer, skip generic insert
                    cur.execute("""
                        UPDATE deep_overnight_llm_queue
                        SET status = 'done', completed_at = NOW(),
                            last_gemma_model = %s, last_gemma_runtime_sec = %s,
                            result_table = 'rebalance_analysis_results',
                            result_id = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (model, runtime, _res.get("result_id"), job_id))
                    conn.commit()
                    succeeded += 1
                    log(f"  DONE #{job_id} — rebalance result_id={_res.get('result_id')}, {runtime}s")
                    processed += 1
                    continue
            except Exception as e:
                log(f"  FAILED #{job_id} — rebalance error: {e}")
                cur.execute("""
                    UPDATE deep_overnight_llm_queue
                    SET status = CASE WHEN attempt_count >= 3 THEN 'failed' ELSE 'pending' END,
                        last_error = %s, updated_at = NOW()
                    WHERE id = %s
                """, (str(e), job_id))
                conn.commit()
                failed += 1
                processed += 1
                continue

        # Build prompt and call gemma
        prompt = build_prompt(job)
        text, runtime = call_gemma(prompt, model=model)

        if text:
            # Parse JSON from response if present
            parsed = {}
            try:
                import re as _re
                match = _re.search(r'\{.+\}', text, _re.DOTALL)
                if match:
                    parsed = json.loads(match.group())
            except Exception:
                pass

            # Store result with expanded columns
            jtype = job["job_type"]
            cur.execute("""
                INSERT INTO deep_overnight_llm_results
                (queue_id, job_type, symbol, trade_id, journal_id, model,
                 prompt_version, summary, findings_json,
                 source_table, source_id,
                 curation_verdict, curation_weight,
                 risk_narrative, reentry_verdict,
                 cc_verdict, cc_strike_target, cc_yield_estimate,
                 behavioral_patterns, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'v1', %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
            """, (job_id, jtype, job.get("symbol"),
                  job.get("trade_id"), job.get("journal_id"),
                  model, text[:2000],
                  json.dumps(parsed if parsed else {"raw_response": text[:5000]}),
                  job.get("source_table"), job.get("source_id"),
                  parsed.get("verdict") if jtype == "rag_content_curation" else None,
                  parsed.get("weight") if jtype == "rag_content_curation" else None,
                  parsed.get("narrative") if jtype == "risk_synthesis" else None,
                  parsed.get("verdict") if jtype == "recovery_watch_review" else None,
                  parsed.get("verdict") if jtype == "covered_call_scoring" else None,
                  None,  # cc_strike_target computed below
                  _safe_cc_float(parsed.get("estimated_monthly_yield_pct")) if jtype == "covered_call_scoring" else None,
                  json.dumps(parsed.get("patterns")) if jtype == "weekly_behavioral_review" and parsed.get("patterns") else None,
                  ))
            result_id = cur.fetchone()[0]

            # Post-processing for specific job types
            if jtype == "rag_content_curation" and parsed.get("verdict"):
                _apply_curation_verdict(cur, job, parsed)
            elif jtype == "risk_synthesis" and parsed.get("narrative"):
                _save_risk_synthesis(cur, job_id, parsed)

            # Mark done
            cur.execute("""
                UPDATE deep_overnight_llm_queue
                SET status = 'done', completed_at = NOW(),
                    last_gemma_model = %s, last_gemma_runtime_sec = %s,
                    result_table = 'deep_overnight_llm_results', result_id = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (model, runtime, result_id, job_id))
            conn.commit()
            succeeded += 1
            log(f"  DONE #{job_id} — result_id={result_id}, runtime={runtime}s")
        else:
            # Mark failed
            cur.execute("""
                UPDATE deep_overnight_llm_queue
                SET status = CASE WHEN attempt_count >= 3 THEN 'failed' ELSE 'pending' END,
                    last_error = %s,
                    last_gemma_model = %s, last_gemma_runtime_sec = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (f"gemma returned no text after {runtime}s", model, runtime, job_id))
            conn.commit()
            failed += 1
            log(f"  FAILED #{job_id} — no response after {runtime}s")

        processed += 1

    total_elapsed = round((time.monotonic() - start_time) / 60, 1)

    # Summary
    log("=" * 60)
    log(f"Queue run complete:")
    log(f"  Processed:   {processed}")
    log(f"  Succeeded:   {succeeded}")
    log(f"  Failed:      {failed}")
    log(f"  Recovered:   {recovered}")
    log(f"  Total time:  {total_elapsed} min")
    log(f"  Model:       {model}")
    log(f"  Hard stop:   {args.hard_stop}")

    # Remaining pending
    cur.execute("SELECT count(*) FROM deep_overnight_llm_queue WHERE status = 'pending'")
    remaining = cur.fetchone()[0]
    log(f"  Remaining pending: {remaining}")
    log("=" * 60)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
