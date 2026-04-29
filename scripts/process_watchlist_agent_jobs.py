#!/usr/bin/env python3
"""process_watchlist_agent_jobs.py — Agent processing with maturity tracking + full narratives.

Polls watchlist_agent_jobs for queued items, routes to the appropriate agent,
captures full narratives, updates maturity state, and triggers synthesis when ready.

Cron: */15 * * * * python3 scripts/process_watchlist_agent_jobs.py --limit 10

Agents:
- maria: catalyst/news/research review
- steph: allocation/account-fit review
- risk_agent: technical/risk/stop review
- tax_agent: tax/location review
- full_chain: orchestrated multi-agent review
"""
import json, os, sys, re, hashlib, urllib.request
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "qwen3:1.7b"

# Agent name normalization (risk_agent/tax_agent → risk/tax for maturity tracking)
AGENT_TO_MATURITY = {
    "maria": "maria", "steph": "steph",
    "risk_agent": "risk", "risk": "risk",
    "tax_agent": "tax", "tax": "tax",
    "full_chain": "full_chain",
}


def _get_conn():
    import psycopg2
    pw = os.environ.get("DB_PASSWORD", "")
    if not pw:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _llm(prompt: str, max_tokens: int = 800, task_type: str = "agent_narrative",
         high_impact: bool = False) -> str:
    """Call LLM via router with fallback hierarchy.

    Routes through: local Ollama → Grok → Claude → OpenAI based on task type.
    """
    try:
        from llm_router import get_llm_response
        result = get_llm_response(
            task_type=task_type,
            prompt=prompt,
            max_tokens=max_tokens,
            high_impact=high_impact,
        )
        if result.get("success"):
            # Track which model was used
            _llm._last_model = result.get("model_used", OLLAMA_MODEL)
            _llm._last_provider = result.get("provider", "local")
            _llm._last_cost = result.get("cost_estimate", 0)
            return result["response"]
        else:
            return f"LLM error: {result.get('error', 'all providers failed')}"
    except ImportError:
        # Fallback to direct Ollama if router not available
        try:
            payload = json.dumps({"model": OLLAMA_MODEL, "stream": False, "think": False,
                                  "prompt": prompt,
                                  "options": {"temperature": 0.3, "num_predict": max_tokens}}).encode()
            req = urllib.request.Request(OLLAMA_URL, data=payload,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read()).get("response", "").strip()
        except Exception as e:
            return f"LLM error: {e}"

# Track last model used for logging
_llm._last_model = OLLAMA_MODEL
_llm._last_provider = "local"
_llm._last_cost = 0


def _get_context(conn, symbol: str) -> dict:
    """Build rich portfolio context for the agent. Returns dict + formatted string."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    pos = [h for h in holdings.get("holdings", []) if h.get("symbol") == symbol]
    enrichment = json.loads((STATE_DIR / "ticker_enrichment_cache.json").read_text()) if (STATE_DIR / "ticker_enrichment_cache.json").exists() else {}
    e = enrichment.get(symbol, {}) if isinstance(enrichment.get(symbol), dict) else {}

    # Strategy card from DB
    cur.execute("SELECT * FROM watchlist_strategy_cards WHERE symbol=%s", (symbol,))
    sc = cur.fetchone()

    # Recent prices from DB
    cur.execute("SELECT close_price, price_date FROM ticker_prices WHERE symbol=%s ORDER BY price_date DESC LIMIT 5", (symbol,))
    prices = cur.fetchall()

    # Risk data
    rm = json.loads((STATE_DIR / "risk_management.json").read_text()) if (STATE_DIR / "risk_management.json").exists() else {}
    stop_data = next((p for p in rm.get("positions", []) if p.get("symbol") == symbol), {})

    snapshot = {
        "symbol": symbol,
        "position": pos[0] if pos else None,
        "enrichment": {k: e.get(k) for k in ["rsi", "beta", "sector", "industry", "sma20_pct", "sma50_pct", "sma200_pct", "atr", "pe", "forward_pe", "company"]} if e else {},
        "strategy_card": dict(sc) if sc else None,
        "recent_prices": [{"price": float(p["close_price"]), "date": str(p["price_date"])} for p in prices] if prices else [],
        "stop": stop_data if stop_data else None,
    }

    ctx = f"Symbol: {symbol}\n"
    if pos:
        p = pos[0]
        ctx += f"Position: ${p.get('market_value', 0):,.0f}, {p.get('shares', 0):.1f} shares, {p.get('portfolio_pct', 0):.1f}% allocation, account: {p.get('account_name', '?')}\n"
    if e:
        ctx += f"RSI: {e.get('rsi', '?')}, Beta: {e.get('beta', '?')}, Sector: {e.get('sector', '?')}, Industry: {e.get('industry', '?')}\n"
        ctx += f"SMA20: {e.get('sma20_pct', '?')}%, SMA50: {e.get('sma50_pct', '?')}%, SMA200: {e.get('sma200_pct', '?')}%\n"
        ctx += f"PE: {e.get('pe', '?')}, Forward PE: {e.get('forward_pe', '?')}, ATR: {e.get('atr', '?')}\n"
    if sc:
        ctx += f"Strategy: {sc.get('strategy_type', '?')}, Support: ${sc.get('support', '?')}, Resistance: ${sc.get('resistance', '?')}\n"
        ctx += f"Stop: ${sc.get('stop_loss', '?')}, Target: ${sc.get('target_price', '?')}, R:R: {sc.get('risk_reward', '?')}\n"
        ctx += f"Account fit: {sc.get('account_fit', '?')}\n"
    if stop_data:
        ctx += f"Active stop: ${stop_data.get('stop_price', '?')} (status: {stop_data.get('status', '?')})\n"
    if prices:
        price_strs = [f"${float(p['close_price']):.2f}" for p in prices[:5]]
        ctx += f"Recent prices: {', '.join(price_strs)}\n"

    cur.close()
    return {"text": ctx, "snapshot": snapshot}


# ── Agent prompts (narrative-grade) ──────────────────────────────────

def _get_other_agent_views(symbol: str, current_agent: str) -> str:
    """Pull what other agents already said about this symbol (for collaboration)."""
    try:
        import psycopg2.extras as _pxe
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=_pxe.RealDictCursor)
        cur.execute("""
            SELECT DISTINCT ON (agent) agent, recommendation, confidence, summary
            FROM watchlist_agent_results
            WHERE symbol = %s AND agent != %s AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY agent, created_at DESC
        """, (symbol, current_agent))
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return ""
        lines = ["OTHER AGENT VIEWS (consider but form your own opinion):"]
        for r in rows:
            lines.append(f"  {r['agent']}: {r['recommendation']} (conf:{float(r['confidence'] or 0):.1f}) — {(r['summary'] or '')[:80]}")
        return "\n".join(lines) + "\n"
    except Exception:
        return ""


def _get_recent_intel(symbol: str) -> str:
    """Pull recent scored intelligence for this symbol."""
    try:
        from intel_query import get_intel_summary
        summary = get_intel_summary(symbol=symbol, min_quality=40, max_chars=300, days=7)
        return summary + "\n" if summary else ""
    except Exception:
        return ""


def _build_prompt(agent: str, symbol: str, context_text: str, note: str = "") -> str:
    # Inject cross-agent views and intel
    other_views = _get_other_agent_views(symbol, agent)
    intel = _get_recent_intel(symbol)

    base_instruction = f"""Respond in JSON format with these fields:
- "summary": 1-2 sentence executive summary
- "full_narrative": detailed 3-5 paragraph analysis (this is the primary output)
- "recommendation": one of BUY, HOLD, AVOID, ADD, TRIM, SELL, NEUTRAL, RESEARCH_MORE
- "confidence": decimal 0.0-1.0
- "reason_codes": array of short reason tags (e.g. ["strong_dividend", "overvalued", "technical_support"])
- "next_action": what should happen next

Context:
{context_text}
{other_views}{intel}"""
    if note:
        base_instruction += f"Additional note: {note}\n"

    prompts = {
        "maria": f"""/no_think You are Maria, a senior research analyst covering equities. Your job is to provide a thorough fundamental and catalyst analysis.

Analyze {symbol}. Cover:
1. Business quality and competitive position
2. Valuation relative to peers and history
3. Upcoming catalysts (earnings, product launches, regulation)
4. News sentiment and analyst consensus
5. Key risks to the thesis

{base_instruction}""",

        "steph": f"""/no_think You are Steph, a senior wealth advisor managing a ~$1.2M multi-account portfolio. Your job is to evaluate allocation and account fit.

Review {symbol}. Cover:
1. Current allocation vs target — is it overweight/underweight?
2. Account location optimization (taxable vs IRA vs Roth)
3. Rebalance recommendation — add, hold, or trim?
4. How this fits the broader portfolio construction
5. Income vs growth classification and its role

{base_instruction}""",

        "risk_agent": f"""/no_think You are a risk analyst. Your job is to evaluate technical risk and position management.

Assess {symbol}. Cover:
1. Technical trend — above/below key moving averages
2. RSI and momentum signals
3. Support/resistance levels and current price position
4. Stop loss recommendation with reasoning
5. Position sizing guidance based on volatility (ATR, beta)

{base_instruction}""",

        "tax_agent": f"""/no_think You are a tax-aware investment advisor. Your job is to optimize after-tax returns.

Review {symbol}. Cover:
1. Optimal account location for this holding
2. Tax-loss harvesting opportunities
3. Dividend tax implications
4. Capital gains considerations
5. Any wash sale concerns

{base_instruction}""",

        "full_chain": f"""/no_think You are a portfolio investment committee synthesizing multiple analyst perspectives.

Comprehensive review of {symbol}. Cover:
1. Fundamental case (bull/bear/base)
2. Technical setup and risk levels
3. Allocation and account fit
4. Key risks and mitigants
5. Final committee recommendation with confidence

{base_instruction}""",
    }
    return prompts.get(agent, prompts["maria"])


def _parse_result(raw: str) -> dict:
    """Parse LLM response — try JSON first, fall back to text extraction."""
    # Try JSON parse
    try:
        # Find JSON block
        for start_char in ['{', '```json\n{', '```\n{']:
            idx = raw.find(start_char)
            if idx >= 0:
                end = raw.rfind('}')
                if end > idx:
                    candidate = raw[idx:end + 1]
                    if candidate.startswith('```'):
                        candidate = candidate.split('\n', 1)[1] if '\n' in candidate else candidate
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and "recommendation" in parsed:
                        return {
                            "summary": str(parsed.get("summary", ""))[:500],
                            "full_narrative": str(parsed.get("full_narrative", parsed.get("summary", "")))[:3000],
                            "recommendation": str(parsed.get("recommendation", "RESEARCH_MORE")).upper(),
                            "confidence": min(1.0, max(0.0, float(parsed.get("confidence", 0.5)))),
                            "reason_codes": parsed.get("reason_codes", []) if isinstance(parsed.get("reason_codes"), list) else [],
                            "next_action": str(parsed.get("next_action", ""))[:200],
                        }
    except (json.JSONDecodeError, ValueError, KeyError):
        pass

    # Fallback: text extraction
    summary = raw[:300]
    full_narrative = raw[:3000]
    recommendation = "RESEARCH_MORE"
    confidence = 0.5
    reason_codes = []

    for line in raw.split("\n"):
        l = line.lower()
        if "recommend" in l:
            for r in ["STRONG_BUY", "BUY", "HOLD", "AVOID", "TRIM", "ADD", "SELL", "NEUTRAL", "RESEARCH_MORE"]:
                if r.lower() in l:
                    recommendation = r
                    break
        if "confidence" in l:
            m = re.search(r'(\d+\.?\d*)', l)
            if m:
                v = float(m.group(1))
                confidence = v if v <= 1 else v / 100

    return {
        "summary": summary,
        "full_narrative": full_narrative,
        "recommendation": recommendation,
        "confidence": confidence,
        "reason_codes": reason_codes,
        "next_action": "",
    }


def _update_maturity(conn, symbol: str, agent: str, status: str):
    """Update the analysis maturity record for a symbol after an agent completes/fails."""
    mat_col = AGENT_TO_MATURITY.get(agent, agent) + "_status"
    valid_cols = ["maria_status", "steph_status", "risk_status", "tax_status", "full_chain_status"]
    if mat_col not in valid_cols:
        return

    cur = conn.cursor()

    # Update agent-specific status
    cur.execute(f"""
        UPDATE watchlist_analysis_maturity
        SET {mat_col} = %s, updated_at = now()
        WHERE symbol = %s
    """, (status, symbol))

    if status == "completed":
        # Update completed_agents array and last_completed
        cur.execute("""
            UPDATE watchlist_analysis_maturity
            SET completed_agents = array_append(
                    COALESCE(array_remove(completed_agents, %s), ARRAY[]::text[]),
                    %s
                ),
                last_completed_agent = %s,
                last_completed_at = now(),
                updated_at = now()
            WHERE symbol = %s
        """, (AGENT_TO_MATURITY.get(agent, agent), AGENT_TO_MATURITY.get(agent, agent), agent, symbol))

    # Recompute stage
    import psycopg2.extras
    rcur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    rcur.execute("SELECT * FROM watchlist_analysis_maturity WHERE symbol = %s", (symbol,))
    mat = rcur.fetchone()
    if not mat:
        rcur.close()
        cur.close()
        return

    required = mat.get("required_agents") or []
    completed = mat.get("completed_agents") or []
    missing = [a for a in required if a not in completed]

    # Determine new stage
    if mat.get("final_synthesis_status") == "completed":
        stage = "final_synthesis_complete"
    elif mat.get("full_chain_status") == "completed":
        stage = "full_chain_complete"
    elif required and not missing:
        stage = "specialist_review_complete"
    elif completed:
        stage = "specialist_review_partial"
    elif mat.get("strategy_card_ready"):
        stage = "strategy_card_ready"
    else:
        stage = "raw_data_only"

    # Check for any failed
    agent_statuses = [mat.get(f"{a}_status", "not_required") for a in ["maria", "steph", "risk", "tax", "full_chain"]]
    if "failed" in agent_statuses and not completed:
        stage = "failed"

    needs_iter = bool(missing) or stage in ("raw_data_only", "strategy_card_ready", "routed", "failed")

    cur.execute("""
        UPDATE watchlist_analysis_maturity
        SET analysis_stage = %s,
            missing_agents = %s,
            needs_iteration = %s,
            iteration_reason = %s,
            updated_at = now()
        WHERE symbol = %s
    """, (stage, missing if missing else None,
          needs_iter,
          f"Missing: {', '.join(missing)}" if missing else None,
          symbol))

    rcur.close()
    cur.close()


def _apply_escalation_policy(conn, symbol: str) -> list:
    """Look up strategy type and set required agents in maturity table. Returns required agents."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get strategy type from strategy card
    cur.execute("SELECT strategy_type FROM watchlist_strategy_cards WHERE symbol=%s", (symbol,))
    sc = cur.fetchone()
    strategy_type = sc["strategy_type"] if sc else "core_holding"

    # Get policy
    cur.execute("SELECT required_agents, optional_agents FROM watchlist_escalation_policies WHERE strategy_type=%s", (strategy_type,))
    policy = cur.fetchone()
    required = policy["required_agents"] if policy else ["steph", "risk"]
    optional = policy["optional_agents"] if policy else ["maria"]

    # Ensure maturity row exists
    cur.execute("""
        INSERT INTO watchlist_analysis_maturity (symbol, escalation_policy, required_agents, analysis_stage, raw_data_ready, strategy_card_ready)
        VALUES (%s, %s, %s, 'routed', TRUE, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            escalation_policy = EXCLUDED.escalation_policy,
            required_agents = EXCLUDED.required_agents,
            analysis_stage = 'routed',
            updated_at = now()
    """, (symbol, strategy_type, required, sc is not None))

    # Set required agent statuses
    for agent in required:
        col = agent + "_status"
        if col in ["maria_status", "steph_status", "risk_status", "tax_status", "full_chain_status"]:
            cur.execute(f"""
                UPDATE watchlist_analysis_maturity
                SET {col} = CASE WHEN {col} IN ('not_required', 'required') THEN 'required' ELSE {col} END
                WHERE symbol = %s
            """, (symbol,))

    conn.commit()
    cur.close()
    return list(required)


def _check_synthesis_ready(conn, symbol: str) -> bool:
    """Check if all required agents completed and synthesis should be triggered."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT required_agents, completed_agents, final_synthesis_status FROM watchlist_analysis_maturity WHERE symbol=%s", (symbol,))
    mat = cur.fetchone()
    cur.close()
    if not mat:
        return False
    required = mat.get("required_agents") or []
    completed = mat.get("completed_agents") or []
    if mat.get("final_synthesis_status") in ("completed", "processing", "queued"):
        return False
    return all(a in completed for a in required)


# ── Strategy-aware synthesis weighting ───────────────────────────────

STRATEGY_WEIGHTS = {
    "income": {
        "allocation": 0.35, "account_location": 0.25,
        "fundamentals": 0.20, "technicals": 0.10, "alerts": 0.10,
        "rules": [
            "RSI alone is NOT a reason to TRIM an income/dividend ETF",
            "High RSI on income ETF = wait for pullback to ADD, not SELL",
            "TRIM only if: allocation exceeds target by >3%, thesis deteriorated, or better replacement exists",
            "Underweight = HOLD or ADD_ON_PULLBACK",
            "Overweight = HOLD unless >15% portfolio weight",
        ],
    },
    "defense_thesis": {
        "allocation": 0.25, "account_location": 0.15,
        "fundamentals": 0.25, "technicals": 0.15, "alerts": 0.20,
        "rules": [
            "Evaluate as basket exposure, not individual picks",
            "Geopolitical thesis and valuation dominate",
            "Position sizing based on total defense allocation",
        ],
    },
    "speculative_growth": {
        "allocation": 0.15, "account_location": 0.10,
        "fundamentals": 0.20, "technicals": 0.30, "alerts": 0.25,
        "rules": [
            "Catalyst + risk control required",
            "Technicals heavily influence entry/exit timing",
            "Position size should be limited (max 3-5% portfolio)",
        ],
    },
    "growth_etf": {
        "allocation": 0.30, "account_location": 0.20,
        "fundamentals": 0.25, "technicals": 0.15, "alerts": 0.10,
        "rules": [
            "Overbought = do not chase, wait for pullback",
            "TRIM only if allocation too high or thesis weakens",
            "Use trend + valuation + overlap analysis",
        ],
    },
    "core_holding": {
        "allocation": 0.35, "account_location": 0.20,
        "fundamentals": 0.25, "technicals": 0.10, "alerts": 0.10,
        "rules": [
            "Allocation and thesis dominate",
            "Technicals are timing signals only, NOT recommendation drivers",
            "TRIM only for rebalancing, not technical signals",
        ],
    },
    "swing_trade": {
        "allocation": 0.10, "account_location": 0.05,
        "fundamentals": 0.15, "technicals": 0.40, "alerts": 0.30,
        "rules": [
            "Technicals dominate entry/exit",
            "Entry/stop/target required before position",
            "Time-bound thesis — exit if thesis expires",
        ],
    },
}


def _get_portfolio_context(conn, symbol: str) -> dict:
    """Get portfolio position context for synthesis weighting."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    acct_summaries = holdings.get("account_summaries", {})
    total_portfolio = sum(info.get("total_value", 0) for info in acct_summaries.values())

    sym_holdings = [h for h in holdings.get("holdings", []) if h.get("symbol") == symbol]
    total_shares = sum(float(h.get("shares", 0) or 0) for h in sym_holdings)
    total_mv = sum(float(h.get("market_value", 0) or 0) for h in sym_holdings)
    weight = round(total_mv / total_portfolio * 100, 2) if total_portfolio > 0 else 0

    accounts = []
    for h in sym_holdings:
        aid = h.get("account_id") or h.get("account", "unknown")
        acct_type = "Roth IRA" if "roth" in aid.lower() else "Rollover IRA" if "rollover" in aid.lower() or "ira" in aid.lower() else "401k" if "401k" in aid.lower() else "Taxable"
        accounts.append({"id": aid, "type": acct_type, "shares": float(h.get("shares", 0) or 0), "value": float(h.get("market_value", 0) or 0)})

    # Strategy type
    cur.execute("SELECT strategy_type FROM watchlist_strategy_cards WHERE symbol=%s", (symbol,))
    sc = cur.fetchone()
    strategy_type = sc["strategy_type"] if sc else "core_holding"

    # Recent alerts (last 24h)
    cur.execute("""
        SELECT alert_type, severity, data_quality_status, created_at
        FROM alert_events WHERE symbol = %s AND created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC LIMIT 10
    """, (symbol,))
    recent_alerts = cur.fetchall()

    # Data quality issues
    cur.execute("""
        SELECT COUNT(*) as cnt FROM alert_events
        WHERE symbol = %s AND data_quality_status NOT IN ('valid', 'unknown')
        AND created_at > NOW() - INTERVAL '7 days'
    """, (symbol,))
    dq_issues = cur.fetchone()["cnt"]

    # Income profile
    cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur2.execute("SELECT * FROM income_asset_profiles WHERE symbol=%s", (symbol,))
    income_profile = cur2.fetchone()

    # Income goals
    cur2.execute("SELECT * FROM portfolio_income_goals LIMIT 1")
    income_goals = cur2.fetchone()

    # Layer allocation
    cur2.execute("""
        SELECT layer_id, SUM(annual_income) as layer_income
        FROM income_asset_profiles GROUP BY layer_id
    """)
    layer_income = {r["layer_id"]: float(r["layer_income"] or 0) for r in cur2.fetchall()}

    # Total portfolio income
    cur2.execute("SELECT SUM(annual_income) as total FROM income_asset_profiles")
    total_income = float((cur2.fetchone() or {}).get("total", 0) or 0)

    cur2.close()
    cur.close()

    income_ctx = {}
    if income_profile:
        ip = income_profile
        income_ctx = {
            "layer": ip.get("layer_id"),
            "annual_income": float(ip.get("annual_income", 0) or 0),
            "yield_pct": float(ip.get("dividend_yield_pct", 0) or 0),
            "forward_yield_pct": float(ip.get("forward_yield_pct", 0) or 0),
            "yield_on_cost_pct": float(ip.get("yield_on_cost_pct", 0) or 0) if ip.get("yield_on_cost_pct") else None,
            "dividend_growth_5yr": float(ip.get("dividend_growth_5yr_pct", 0) or 0) if ip.get("dividend_growth_5yr_pct") else None,
            "payout_safety": ip.get("payout_safety", "unknown"),
            "income_reliability": ip.get("income_reliability", "unknown"),
            "preferred_account": ip.get("preferred_account"),
            "income_goal_contribution_pct": float(ip.get("income_goal_contribution_pct", 0) or 0),
            "portfolio_income_pct": float(ip.get("portfolio_income_pct", 0) or 0),
        }

    return {
        "total_shares": total_shares,
        "total_value": total_mv,
        "portfolio_weight": weight,
        "accounts": accounts,
        "strategy_type": strategy_type,
        "recent_alerts": [dict(a) for a in recent_alerts],
        "has_active_alerts": len(recent_alerts) > 0,
        "has_stop_triggered": any(a["alert_type"] == "stop_triggered" for a in recent_alerts),
        "data_quality_issues": dq_issues,
        "position_tiny": weight < 0.5,
        "position_small": weight < 2.0,
        "income": income_ctx,
        "total_portfolio_income": total_income,
        "income_target": float(income_goals.get("target_income", 55000)) if income_goals else 55000,
        "income_gap": max(0, float(income_goals.get("target_income", 55000)) - total_income) if income_goals else 0,
    }


def _build_layer_status(conn) -> str:
    """Build layer allocation status string for synthesis prompt."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT pl.layer_id, pl.layer_name, pl.target_min_pct, pl.target_max_pct,
               COALESCE(SUM(iap.annual_income), 0) as layer_income,
               COUNT(iap.symbol) as symbol_count
        FROM portfolio_layers pl
        LEFT JOIN income_asset_profiles iap ON iap.layer_id = pl.layer_id
        GROUP BY pl.layer_id, pl.layer_name, pl.target_min_pct, pl.target_max_pct
    """)
    layers = cur.fetchall()

    # Get total portfolio value from holdings
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    total_portfolio = sum(info.get("total_value", 0) for info in holdings.get("account_summaries", {}).values())

    # Get actual allocation per layer
    cur.execute("SELECT layer_id, SUM(iap.annual_income) as income FROM income_asset_profiles iap GROUP BY layer_id")
    # Need market value by layer — get from holdings
    layer_values = {}
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        mv = float(h.get("market_value", 0) or 0)
        if h.get("is_cash"):
            continue
        cur.execute("SELECT layer_id FROM income_asset_profiles WHERE symbol=%s", (sym,))
        lr = cur.fetchone()
        lid = lr["layer_id"] if lr else "core_compounders"
        layer_values[lid] = layer_values.get(lid, 0) + mv

    cur.close()

    lines = []
    for l in layers:
        lid = l["layer_id"]
        actual_pct = round(layer_values.get(lid, 0) / total_portfolio * 100, 1) if total_portfolio > 0 else 0
        target_min = float(l["target_min_pct"] or 0)
        target_max = float(l["target_max_pct"] or 100)
        status = "IN RANGE" if target_min <= actual_pct <= target_max else ("OVERWEIGHT" if actual_pct > target_max else "UNDERWEIGHT")
        lines.append(f"  {l['layer_name']:25} actual={actual_pct:>5.1f}%  target={target_min:.0f}-{target_max:.0f}%  [{status}]  income=${float(l['layer_income']):,.0f}/yr")
    return "\n".join(lines)


def run_synthesis(conn, symbol: str):
    """Run strategy-aware final synthesis combining all analyst narratives."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get all completed narratives
    cur.execute("""
        SELECT agent, full_narrative, summary, recommendation, confidence, reason_codes, created_at
        FROM watchlist_agent_results
        WHERE symbol = %s AND status = 'completed'
        ORDER BY created_at DESC
    """, (symbol,))
    results = cur.fetchall()

    if not results:
        cur.close()
        return

    # Mark synthesis as processing
    cur.execute("UPDATE watchlist_analysis_maturity SET final_synthesis_status='processing', updated_at=now() WHERE symbol=%s", (symbol,))
    conn.commit()

    # Get portfolio context and strategy weights
    port_ctx = _get_portfolio_context(conn, symbol)
    strategy_type = port_ctx["strategy_type"]
    weights = STRATEGY_WEIGHTS.get(strategy_type, STRATEGY_WEIGHTS["core_holding"])
    rules = weights.get("rules", [])

    # Build narratives section
    narratives = ""
    for r in results:
        narratives += f"\n--- {r['agent'].upper()} ({r['created_at'].strftime('%Y-%m-%d') if r.get('created_at') else '?'}) ---\n"
        narratives += f"Recommendation: {r.get('recommendation', '?')}, Confidence: {r.get('confidence', '?')}\n"
        narratives += f"Narrative: {r.get('full_narrative') or r.get('summary', 'No narrative')}\n"
        if r.get('reason_codes'):
            narratives += f"Reason codes: {', '.join(r['reason_codes'])}\n"

    context = _get_context(conn, symbol)

    # Build portfolio position summary
    position_summary = f"""
PORTFOLIO POSITION:
Total shares: {port_ctx['total_shares']:.1f}
Total value: ${port_ctx['total_value']:,.0f}
Portfolio weight: {port_ctx['portfolio_weight']:.1f}%
Accounts: {', '.join(f"{a['type']} ({a['shares']:.0f} sh, ${a['value']:,.0f})" for a in port_ctx['accounts'])}
"""
    if port_ctx["position_tiny"]:
        position_summary += "NOTE: Position is <0.5% of portfolio — actions have minimal impact.\n"

    # Income context
    income_context = ""
    inc = port_ctx.get("income", {})
    if inc:
        _ai = float(inc.get('annual_income') or 0)
        _yp = float(inc.get('yield_pct') or 0)
        _fy = float(inc.get('forward_yield_pct') or 0)
        _yoc = float(inc.get('yield_on_cost_pct') or 0)
        _igc = float(inc.get('income_goal_contribution_pct') or 0)
        _tpi = float(port_ctx.get('total_portfolio_income') or 0)
        _tig = float(port_ctx.get('income_target') or 55000)
        _gap = float(port_ctx.get('income_gap') or 0)
        income_context = f"""
INCOME PROFILE:
Layer: {inc.get('layer', 'unknown')}
Annual income: ${_ai:,.0f} | Yield: {_yp:.1f}% | Forward: {_fy:.1f}% | YoC: {_yoc:.1f}%
Payout: {inc.get('payout_safety', 'unknown')} | Reliability: {inc.get('income_reliability', 'unknown')}
Preferred account: {inc.get('preferred_account', 'any')}
Contributes {_igc:.1f}% of income target (${_tig:,.0f})
Total portfolio income: ${_tpi:,.0f} — gap: ${_gap:,.0f}
"""

    # Build alert context
    alert_context = ""
    if port_ctx["has_active_alerts"]:
        alert_context = "\nACTIVE ALERTS (last 24h):\n"
        for a in port_ctx["recent_alerts"]:
            alert_context += f"- {a['alert_type']} (severity: {a['severity']})\n"
        if port_ctx["has_stop_triggered"]:
            alert_context += "CRITICAL: Stop was triggered — risk assessment should be weighted heavily.\n"

    # Data quality warning
    dq_note = ""
    if port_ctx["data_quality_issues"] > 0:
        dq_note = f"\nDATA QUALITY WARNING: {port_ctx['data_quality_issues']} data quality issue(s) detected in last 7 days. Lower confidence accordingly but still produce a recommendation.\n"

    # Strategy rules
    rules_text = "\n".join(f"- {r}" for r in rules)

    prompt = f"""/no_think You are the Chief Investment Officer performing final synthesis for the portfolio committee.

STRATEGY TYPE: {strategy_type}
DECISION WEIGHTS for {strategy_type}:
- Allocation/position sizing: {weights['allocation']:.0%}
- Account location: {weights['account_location']:.0%}
- Fundamentals: {weights['fundamentals']:.0%}
- Technicals: {weights['technicals']:.0%}
- Alerts/events: {weights['alerts']:.0%}

STRATEGY-SPECIFIC RULES (you MUST follow these):
{rules_text}

{context['text']}
{position_summary}
{income_context}
{alert_context}
{dq_note}

PORTFOLIO MANDATE:
Goal: Build sustainable retirement income. Target $55K/yr. Current: ${port_ctx.get('total_portfolio_income', 0):,.0f}/yr. Gap: ${port_ctx.get('income_gap', 0):,.0f}. Timeline: 4-8 years.

LAYER ALLOCATION STATUS:
{_build_layer_status(conn)}

ALLOCATION-FIRST RULE: If a layer is outside its target range, the recommendation MUST prioritize fixing layer allocation. Underweight income_generators = ADD income assets. Overweight core_compounders = consider rebalancing INTO income layer.

INCOME PROTECTION RULE: For income assets, TRIM is BLOCKED unless:
- Position exceeds max allocation (>15% portfolio weight)
- Income deterioration detected (payout safety = at_risk/unsafe)
- Superior income replacement identified with better yield/safety

RSI OVERRIDE: RSI cannot trigger SELL/TRIM for income assets. RSI only informs ADD timing (buy on pullback).

INCOME IMPACT: This position provides {float(inc.get('portfolio_income_pct') or 0):.1f}% of total portfolio income. If >20%, require elevated justification for any reduction.

ANALYST NARRATIVES:
{narratives}

CRITICAL INSTRUCTIONS:
1. Your recommendation MUST be consistent with the strategy type and rules above.
2. For income/dividend ETFs: DO NOT recommend TRIM/SELL based solely on RSI or technical overbought signals.
3. For tiny positions (<0.5% weight): downgrade action priority — HOLD or IGNORE unless thesis broken.
4. If recent stop alert exists, weight risk assessment heavily.
5. Account location matters: IRA positions have different tax implications than taxable.
6. State explicitly which analyst you agree with and why you disagree with others.
7. PAST PERFORMANCE GUARDRAIL: Historical returns are evidence/context, NOT predictions. Distinguish between:
   - Historical evidence (what happened before)
   - Current facts (price, yield, allocation now)
   - Forward assumptions (scenario-based, labeled conservative/base/aggressive)
   - Your recommendation (based on all three, not just history)
   Do NOT use "it returned X% before" as the sole rationale. Instead reference current fundamentals, payout quality, and strategy fit.

Respond in JSON format:
- "recommendation": one of BUY, HOLD, SELL, ADD, ADD_ON_PULLBACK, TRIM, REBALANCE_TRIM, AVOID, IGNORE
- "confidence": 0.0-1.0
- "action": specific next action with price levels and share counts where possible
- "account_action": which account to act in and why (e.g. "Add in IRA for tax-deferred income")
- "income_goal_impact": how this action affects the $55K income target (e.g. "Maintains $4,438/yr income stream")
- "reason_codes": array of reason tags
- "conflicts": array of disagreements between analysts (empty if none)
- "unresolved": array of questions that still need answers
- "what_changes_view": what new information would change this recommendation
- "synthesis_narrative": 2-3 paragraph final assessment explaining the weighting
- "next_review_date": ISO date for when to re-review
"""

    raw = _llm(prompt, max_tokens=1000, task_type="cio_synthesis", high_impact=True)
    parsed = _parse_result(raw)

    # Extract synthesis-specific fields
    try:
        j = json.loads(raw[raw.find('{'):raw.rfind('}') + 1])
        conflicts = j.get("conflicts", []) if isinstance(j.get("conflicts"), list) else []
        unresolved = j.get("unresolved", []) if isinstance(j.get("unresolved"), list) else []
        action = str(j.get("action", ""))[:200]
        next_review = j.get("next_review_date")
        synthesis_narrative = str(j.get("synthesis_narrative", parsed["full_narrative"]))[:3000]
    except (json.JSONDecodeError, ValueError):
        conflicts = []
        unresolved = []
        action = parsed.get("next_action", "")
        next_review = None
        synthesis_narrative = parsed["full_narrative"]

    # ── POST-LLM GATING RULES (hard overrides) ──────────────────────
    rec = parsed["recommendation"].upper()
    inc = port_ctx.get("income", {})

    # Rule 1: Income protection — block TRIM/SELL on safe income assets
    if rec in ("TRIM", "SELL") and inc.get("layer") == "income_generators":
        payout = inc.get("payout_safety", "unknown")
        weight_pct = port_ctx.get("portfolio_weight", 0)
        if payout in ("safe", "moderate") and weight_pct <= 15:
            # Override: income asset with safe payout, not overweight
            parsed["recommendation"] = "HOLD"
            parsed["confidence"] = min(parsed["confidence"], 0.5)
            action = f"HOLD — income protection rule: {payout} payout, {weight_pct:.1f}% weight (<=15% max). Original LLM said {rec}."
            conflicts.append(f"GATING OVERRIDE: LLM recommended {rec} but income protection rule blocked it (payout={payout}, weight={weight_pct:.1f}%)")
            synthesis_narrative = f"[GATED] Original recommendation {rec} overridden by income protection rule. Position has {payout} payout safety and {weight_pct:.1f}% weight (within 15% max). " + synthesis_narrative

    # Rule 2: RSI cannot trigger SELL for income assets
    if rec in ("TRIM", "SELL") and strategy_type == "income":
        reason_codes = parsed.get("reason_codes", [])
        tech_reasons = {"overbought", "rsi_high", "technical_overbought", "overvalued"}
        if reason_codes and set(r.lower() for r in reason_codes) <= tech_reasons:
            parsed["recommendation"] = "HOLD"
            parsed["confidence"] = min(parsed["confidence"], 0.5)
            action = f"HOLD — RSI override: technical signals alone cannot trigger TRIM on income ETF. Original: {rec}."
            conflicts.append(f"GATING OVERRIDE: RSI/technical-only {rec} blocked for income strategy")

    # Rule 3: Income impact >20% requires elevated justification
    income_pct = inc.get("portfolio_income_pct", 0)
    if rec in ("TRIM", "SELL", "AVOID") and income_pct > 20:
        if parsed["confidence"] < 0.8:
            # Not confident enough to reduce major income source
            parsed["recommendation"] = "HOLD"
            action = f"HOLD — position provides {income_pct:.0f}% of portfolio income. Requires >80% confidence to reduce. Original: {rec} at {parsed['confidence']:.0%}."
            conflicts.append(f"GATING OVERRIDE: {income_pct:.0f}% income concentration requires elevated justification (conf was {parsed['confidence']:.0%} < 80%)")

    # Update rec after gating
    rec = parsed["recommendation"].upper()

    # Store synthesis
    cur.execute("""
        INSERT INTO watchlist_final_synthesis
            (symbol, recommendation, confidence, action, reason_codes, conflicts, unresolved,
             next_review_date, synthesis_narrative, input_agents, model_used, raw_response)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            recommendation=EXCLUDED.recommendation, confidence=EXCLUDED.confidence,
            action=EXCLUDED.action, reason_codes=EXCLUDED.reason_codes,
            conflicts=EXCLUDED.conflicts, unresolved=EXCLUDED.unresolved,
            next_review_date=EXCLUDED.next_review_date,
            synthesis_narrative=EXCLUDED.synthesis_narrative,
            input_agents=EXCLUDED.input_agents, model_used=EXCLUDED.model_used,
            raw_response=EXCLUDED.raw_response, updated_at=now()
    """, (symbol, parsed["recommendation"], parsed["confidence"], action,
          parsed.get("reason_codes", []), conflicts, unresolved,
          next_review, synthesis_narrative,
          [r["agent"] for r in results], OLLAMA_MODEL, raw))

    # Update maturity
    cur.execute("""
        UPDATE watchlist_analysis_maturity
        SET final_synthesis_status = 'completed',
            analysis_stage = 'final_synthesis_complete',
            needs_iteration = FALSE,
            iteration_reason = NULL,
            updated_at = now()
        WHERE symbol = %s
    """, (symbol,))

    # Update research card with synthesis
    cur.execute("""
        UPDATE watchlist_research_cards
        SET latest_summary = %s, latest_recommendation = %s, confidence = %s,
            research_status = 'synthesis_complete', needs_iteration = FALSE, updated_at = now()
        WHERE symbol = %s
    """, (parsed["summary"][:500], parsed["recommendation"], parsed["confidence"], symbol))

    # Event
    cur.execute("""
        INSERT INTO watchlist_events (event_type, symbol, agent, status, message)
        VALUES ('synthesis_complete', %s, 'synthesis', 'completed', %s)
    """, (symbol, f"Final: {parsed['recommendation']} (conf={parsed['confidence']:.0%}), conflicts={len(conflicts)}, unresolved={len(unresolved)}"))

    conn.commit()

    # ── AUTO-ESCALATION: Detect conflicts and flag for human review ────
    needs_escalation = False
    escalation_reasons = []

    # Check 1: LLM detected conflicts between agents
    if conflicts:
        needs_escalation = True
        escalation_reasons.append(f"{len(conflicts)} agent conflict(s)")

    # Check 2: Low confidence after synthesis
    if parsed["confidence"] < 0.4:
        needs_escalation = True
        escalation_reasons.append(f"Low confidence: {parsed['confidence']:.0%}")

    # Check 3: Gating override happened (agents wanted one thing, rules blocked it)
    gating_overrides = [c for c in conflicts if "GATING OVERRIDE" in c]
    if gating_overrides:
        needs_escalation = True
        escalation_reasons.append(f"{len(gating_overrides)} safety gate override(s)")

    # Check 4: Unresolved questions
    if unresolved and len(unresolved) >= 2:
        needs_escalation = True
        escalation_reasons.append(f"{len(unresolved)} unresolved questions")

    if needs_escalation:
        try:
            from agent_collab import log_handoff
            log_handoff(
                from_agent="synthesis",
                to_agent="human_review",
                symbol=symbol,
                intent=f"Auto-escalation: {'; '.join(escalation_reasons)}",
                confidence=parsed["confidence"],
                response_summary=f"{parsed['recommendation']} — {action[:100]}",
                escalated=True,
            )
            # Telegram notification for high-priority escalations
            if parsed["confidence"] < 0.3 or len(conflicts) >= 3:
                try:
                    from telegram_alert import send_telegram
                    send_telegram(
                        f"\U0001F6A8 *Escalation: {symbol}*\n"
                        f"Synthesis: {parsed['recommendation']} ({parsed['confidence']:.0%} confidence)\n"
                        f"Reasons: {', '.join(escalation_reasons)}\n"
                        f"Review at: /v2/watchlist?symbol={symbol}"
                    )
                except Exception:
                    pass
        except Exception:
            pass
        print(f"  \u26A0 {symbol}: ESCALATED — {', '.join(escalation_reasons)}")

    cur.close()
    print(f"  \u2605 {symbol}: SYNTHESIS {parsed['recommendation']} conf={parsed['confidence']:.0%}")


def process_jobs(limit: int = 10):
    conn = _get_conn()
    cur = conn.cursor()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get queued jobs
    cur.execute("SELECT * FROM watchlist_agent_jobs WHERE status = 'queued' ORDER BY priority, created_at LIMIT %s", (limit,))
    jobs = cur.fetchall()

    if not jobs:
        print(f"[watchlist-agent] No queued jobs")
        # Still check for symbols ready for synthesis
        _check_pending_synthesis(conn)
        conn.close()
        return 0

    print(f"[watchlist-agent] Processing {len(jobs)} jobs...")
    completed = 0

    for job in jobs:
        job_id = job["id"]
        symbol = job["symbol"]
        agent = job["requested_agent"]
        request_type = job["request_type"]
        note = job.get("note", "")

        # Apply escalation policy if not already set
        _apply_escalation_policy(conn, symbol)

        # Mark processing
        cur.execute("UPDATE watchlist_agent_jobs SET status='processing', started_at=now() WHERE id=%s", (job_id,))
        _update_maturity(conn, symbol, agent, "processing")
        cur.execute("INSERT INTO watchlist_events (event_type, symbol, agent, status, message) VALUES ('processing', %s, %s, 'processing', %s)",
                    (symbol, agent, f"Started {agent} {request_type}"))
        conn.commit()

        # Build context and prompt
        context = _get_context(conn, symbol)
        prompt = _build_prompt(agent, symbol, context["text"], note)
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]

        # Call LLM
        raw = _llm(prompt)

        if not raw or raw.startswith("LLM error"):
            cur.execute("UPDATE watchlist_agent_jobs SET status='failed', completed_at=now() WHERE id=%s", (job_id,))
            cur.execute("UPDATE watchlist_items SET status='active', updated_at=now() WHERE symbol=%s AND status='queued'", (symbol,))
            _update_maturity(conn, symbol, agent, "failed")
            cur.execute("INSERT INTO watchlist_events (event_type, symbol, agent, status, message) VALUES ('failed', %s, %s, 'failed', %s)",
                        (symbol, agent, raw or "Empty LLM response"))
            conn.commit()
            print(f"  ✗ {symbol} ({agent}): FAILED — {(raw or 'empty')[:50]}")
            continue

        # Parse result
        parsed = _parse_result(raw)

        # Store result with full narrative
        result_id = f"res-{job_id}"
        cur.execute("""
            INSERT INTO watchlist_agent_results
                (id, job_id, symbol, agent, request_type, status, confidence,
                 summary, full_narrative, recommendation, reason_codes,
                 next_action, full_result, model_used, prompt_hash,
                 input_data_snapshot, raw_response, started_at, completed_at)
            VALUES (%s, %s, %s, %s, %s, 'completed', %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE SET
                summary=EXCLUDED.summary, full_narrative=EXCLUDED.full_narrative,
                recommendation=EXCLUDED.recommendation, confidence=EXCLUDED.confidence,
                reason_codes=EXCLUDED.reason_codes, raw_response=EXCLUDED.raw_response,
                model_used=EXCLUDED.model_used, completed_at=now()
        """, (result_id, job_id, symbol, agent, request_type, parsed["confidence"],
              parsed["summary"][:500], parsed["full_narrative"][:3000],
              parsed["recommendation"], parsed["reason_codes"],
              parsed.get("next_action", ""),
              json.dumps({"raw": raw, "model": OLLAMA_MODEL}),
              OLLAMA_MODEL, prompt_hash,
              json.dumps(context["snapshot"], default=str),
              raw,
              job.get("started_at")))

        # Update job
        cur.execute("UPDATE watchlist_agent_jobs SET status='completed', completed_at=now(), result_id=%s WHERE id=%s", (result_id, job_id))

        # Update watchlist item status
        cur.execute("UPDATE watchlist_items SET status='researched', updated_at=now() WHERE symbol=%s AND status IN ('queued','active')", (symbol,))

        # Upsert research card
        cur.execute("""
            INSERT INTO watchlist_research_cards (symbol, card, research_status, latest_summary, latest_recommendation, confidence, needs_iteration, updated_at)
            VALUES (%s, %s, 'partial', %s, %s, %s, TRUE, now())
            ON CONFLICT (symbol) DO UPDATE SET
                card=EXCLUDED.card, latest_summary=EXCLUDED.latest_summary,
                latest_recommendation=EXCLUDED.latest_recommendation,
                confidence=EXCLUDED.confidence, updated_at=now()
        """, (symbol, json.dumps({"agent": agent, "summary": parsed["summary"], "recommendation": parsed["recommendation"]}),
              parsed["summary"][:500], parsed["recommendation"], parsed["confidence"]))

        # Update maturity
        _update_maturity(conn, symbol, agent, "completed")

        # Event
        cur.execute("INSERT INTO watchlist_events (event_type, symbol, agent, status, message) VALUES ('completed', %s, %s, 'completed', %s)",
                    (symbol, agent, f"{parsed['recommendation']} conf={parsed['confidence']:.0%} codes={parsed['reason_codes']}"))
        conn.commit()
        completed += 1
        print(f"  ✓ {symbol} ({agent}): {parsed['recommendation']} conf={parsed['confidence']:.0%}")

        # Check if synthesis is now ready
        if _check_synthesis_ready(conn, symbol):
            print(f"  → {symbol}: All required reviews complete, running synthesis...")
            try:
                run_synthesis(conn, symbol)
                # Run safety assessment immediately after synthesis
                try:
                    from synthesis_safety import assess_synthesis_safety, persist_safety
                    safety = assess_synthesis_safety(symbol)
                    persist_safety(symbol, safety)
                    print(f"  ⛨ {symbol}: Safety={safety['decision_safety']} actionable={safety['actionable_allowed']}")
                except Exception as se:
                    print(f"  [safety] {symbol}: assessment failed: {se}")
            except Exception as e:
                print(f"  ✗ {symbol}: Synthesis failed: {e}")
                cur.execute("UPDATE watchlist_analysis_maturity SET final_synthesis_status='failed', updated_at=now() WHERE symbol=%s", (symbol,))
                conn.commit()

    # Also check for any other symbols that became ready for synthesis
    _check_pending_synthesis(conn)

    conn.close()
    print(f"[watchlist-agent] Done: {completed}/{len(jobs)} completed")
    return completed


def _check_pending_synthesis(conn):
    """Check all symbols that have all required reviews done but no synthesis yet."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT symbol FROM watchlist_analysis_maturity
        WHERE analysis_stage = 'specialist_review_complete'
        AND final_synthesis_status = 'pending'
    """)
    ready = [r["symbol"] for r in cur.fetchall()]
    cur.close()

    for sym in ready:
        print(f"  → {sym}: Pending synthesis detected, running...")
        try:
            run_synthesis(conn, sym)
            from synthesis_safety import assess_synthesis_safety, persist_safety
            safety = assess_synthesis_safety(sym)
            persist_safety(sym, safety)
            print(f"  ⛨ {sym}: Safety={safety['decision_safety']}")
        except Exception as e:
            print(f"  ✗ {sym}: Synthesis failed: {e}")


def _auto_queue_new_symbols():
    """Auto-queue agent jobs for watchlist symbols that have no analysis yet.

    Runs every 15 minutes as part of the agent processing cycle.
    New symbols get Maria + Steph + Risk queued automatically.
    """
    conn = _get_conn()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find active watchlist symbols with NO agent jobs at all
    cur.execute("""
        SELECT wi.symbol, tsc.strategy_type
        FROM watchlist_items wi
        LEFT JOIN ticker_strategy_classifications tsc ON wi.symbol = tsc.symbol AND tsc.active = TRUE
        WHERE wi.status = 'active'
          AND wi.symbol NOT IN (SELECT DISTINCT symbol FROM watchlist_agent_jobs)
        LIMIT 5
    """)
    new_symbols = cur.fetchall()

    if not new_symbols:
        return 0

    import uuid
    queued = 0
    agents_to_queue = ["maria", "steph", "risk_agent"]

    for row in new_symbols:
        symbol = row["symbol"]
        strategy_type = row.get("strategy_type") or "unknown"
        for agent in agents_to_queue:
            job_id = f"auto_{symbol.lower()}_{agent}_{uuid.uuid4().hex[:6]}"
            cur.execute("""
                INSERT INTO watchlist_agent_jobs
                    (id, symbol, requested_agent, request_type, priority, note, status)
                VALUES (%s, %s, %s, 'full_analysis', 2, %s, 'queued')
                ON CONFLICT DO NOTHING
            """, (job_id, symbol, agent, f"Auto-queued for new watchlist symbol (strategy: {strategy_type})"))
            queued += 1

    conn.commit()
    conn.close()
    if queued > 0:
        print(f"[watchlist-agent] Auto-queued {queued} jobs for {len(new_symbols)} new symbol(s)")
    return queued


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    _auto_queue_new_symbols()  # Check for new symbols first
    process_jobs(args.limit)
