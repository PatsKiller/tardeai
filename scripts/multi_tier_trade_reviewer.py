#!/usr/bin/env python3
"""multi_tier_trade_reviewer.py — Multi-LLM trade review system.

Tier schedule:
  - REALTIME (qwen3:14b): Runs on every trade close. Fast, local.
  - OVERNIGHT (gemma3:27b): Runs nightly on all trades closed that day. Deeper analysis.
  - WEEKLY (OpenAI gpt-4o): Runs Sunday. Reviews all trades from the week. Pattern detection.
  - MONTHLY (Anthropic Claude): Runs 1st of month. Reviews all weekly summaries + flagged trades.

Each tier:
  1. Generates a structured review with agent-specific commentary
  2. Persists to paper_trade_multi_reviews table
  3. Indexes key findings into RAG (content_embeddings)
  4. Feeds back into agent_intelligence_rules for future decisions

Usage:
  .venv/bin/python scripts/multi_tier_trade_reviewer.py --tier realtime --trade-id 12
  .venv/bin/python scripts/multi_tier_trade_reviewer.py --tier overnight
  .venv/bin/python scripts/multi_tier_trade_reviewer.py --tier weekly
  .venv/bin/python scripts/multi_tier_trade_reviewer.py --tier monthly
"""
import argparse, json, logging, os, sys, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("multi_tier_reviewer")

# ── Advisory cloud review (ChatGPT+Grok) gating ──────────────────────────
# OFF by default; opt in with CLOUD_REVIEW=1. Capped per run to avoid slow fan-out.
CLOUD_REVIEW_ENABLED = os.getenv("CLOUD_REVIEW", "0") == "1"
CLOUD_REVIEW_MAX = 5
_cloud_review_count = 0

# ── Model configuration ──────────────────────────────────────────────────

TIER_CONFIG = {
    "realtime": {
        "model": os.getenv("LOCAL_LLM_MODEL", "gemma3:4b"),
        "provider": "ollama",
        "max_tokens": 400,
        "temperature": 0.3,
        "description": "Fast local review on trade close",
    },
    "overnight": {
        "model": "gemma3:27b",
        "provider": "ollama",
        "max_tokens": 800,
        "temperature": 0.4,
        "description": "Deeper overnight analysis with larger model",
    },
    "weekly": {
        "model": "deepseek-v4-flash",
        "provider": "openai",  # routed through llm_lane deepseek-flash
        "max_tokens": 1500,
        "temperature": 0.5,
        "description": "Weekly pattern analysis across all trades",
    },
    "monthly": {
        "model": "deepseek-v4-pro",
        "provider": "anthropic",  # routed through llm_lane deepseek-v4
        "max_tokens": 2000,
        "temperature": 0.5,
        "description": "Monthly strategic review of weekly summaries",
    },
}

AGENT_PERSPECTIVES = {
    "risk_agent": "Evaluate risk management: was the stop appropriate? Was position sizing correct? Was the risk/reward ratio honored?",
    "strategy_agent": "Evaluate strategy alignment: did this trade match the strategy's criteria? Was the setup valid? Would you take this trade again?",
    "execution_agent": "Evaluate execution quality: was entry timing good? Was slippage acceptable? Was the exit handled correctly?",
    "learning_agent": "What patterns emerge? What should the system remember for next time? What rules should change?",
}


def _get_conn():
    from session13_db import get_conn
    return get_conn()


def _generate_ollama(prompt, model, max_tokens=400, temperature=0.3):
    """Call Ollama directly. Handles qwen3 thinking mode."""
    import requests
    try:
        # Use /no_think prefix for qwen3 to get direct output, and increase token budget
        effective_prompt = f"/no_think\n{prompt}" if "qwen" in model.lower() else prompt
        effective_tokens = max_tokens * 3 if "qwen" in model.lower() else max_tokens

        resp = requests.post("http://localhost:11434/api/generate", json={
            "model": model, "prompt": effective_prompt, "stream": False,
            "options": {"temperature": temperature, "num_predict": effective_tokens},
        }, timeout=300)
        if resp.ok:
            data = resp.json()
            # Qwen3 may put content in 'thinking' field instead of 'response'
            result = data.get("response", "")
            if not result and data.get("thinking"):
                result = data["thinking"]
            return result
    except Exception as e:
        log.warning(f"Ollama {model} failed: {e}")
    return None


def _generate_openai_DEPRECATED(prompt, model, max_tokens=1500, temperature=0.5):
    """Deprecated — migrated to llm_lane.generate(lane='deepseek-flash')."""
    import requests
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        log.warning("No OPENAI_API_KEY set")
        return None
    try:
        resp = requests.post("https://api.openai.com/v1/chat/completions", json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": temperature,
        }, headers={"Authorization": f"Bearer {api_key}"}, timeout=120)
        if resp.ok:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning(f"OpenAI {model} failed: {e}")
    return None


def _generate_anthropic_DEPRECATED(prompt, model, max_tokens=2000, temperature=0.5):
    """Deprecated — migrated to llm_lane.generate(lane='deepseek-v4')."""
    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            log.warning("No ANTHROPIC_API_KEY set")
            return None
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text if msg.content else None
    except Exception as e:
        log.warning(f"Anthropic {model} failed: {e}")
    return None


def _generate(prompt, tier):
    """Route to correct provider. Paid APIs replaced with llm_lane.generate().
    - ollama → local Ollama (realtime, overnight)
    - openai → llm_lane deepseek-flash (weekly)
    - anthropic → llm_lane deepseek-v4 (monthly)"""
    cfg = TIER_CONFIG[tier]
    if cfg["provider"] == "ollama":
        return _generate_ollama(prompt, cfg["model"], cfg["max_tokens"], cfg["temperature"])
    elif cfg["provider"] == "openai":
        try:
            from llm_lane import generate
            return generate(prompt, lane="deepseek-flash", timeout=120)
        except Exception as e:
            log.warning(f"llm_lane deepseek-flash failed: {e}")
            return None
    elif cfg["provider"] == "anthropic":
        try:
            from llm_lane import generate
            # Expert tier: Flash by default; USE_PRO=1 for reasoner
            import os as _os
            use_pro = _os.getenv("USE_PRO", "").strip().lower() in {"1", "true", "yes", "on"}
            return generate(
                prompt,
                lane="deepseek-v4" if use_pro else "deepseek-flash",
                timeout=180 if use_pro else 120,
                process_id="multi_tier_trade_reviewer",
                task_summary="expert tier",
            )
        except Exception as e:
            log.warning(f"llm_lane deepseek-v4 failed: {e}")
            return None
    return None


def _get_closed_trades(conn, since_hours=None, since_date=None, trade_id=None):
    """Get closed trades for review."""
    cur = conn.cursor()
    if trade_id:
        cur.execute("SELECT * FROM paper_trades WHERE id = %s AND status = 'closed'", [trade_id])
    elif since_date:
        cur.execute("SELECT * FROM paper_trades WHERE status = 'closed' AND closed_at >= %s ORDER BY closed_at", [since_date])
    elif since_hours:
        cur.execute("SELECT * FROM paper_trades WHERE status = 'closed' AND closed_at >= NOW() - interval '%s hours' ORDER BY closed_at", [since_hours])
    else:
        cur.execute("SELECT * FROM paper_trades WHERE status = 'closed' ORDER BY closed_at DESC LIMIT 20")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _get_existing_reviews(conn, trade_id):
    """Get all prior reviews for a trade (all tiers)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT tier, model_used, review_text, agent_commentaries, created_at
        FROM paper_trade_multi_reviews WHERE paper_trade_id = %s ORDER BY created_at
    """, [trade_id])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _build_trade_prompt(trade, tier, prior_reviews=None):
    """Build review prompt for a single trade."""
    t = trade
    entry = float(t.get('entry_price') or 0)
    exit_p = float(t.get('exit_price') or 0)
    stop = float(t.get('stop_loss') or 0)
    target = float(t.get('target_1') or 0)
    pnl = float(t.get('pnl') or 0)
    r_mult = t.get('r_multiple')

    prior_context = ""
    if prior_reviews:
        prior_context = "\n=== PRIOR REVIEWS (lower-tier analyses) ===\n"
        for pr in prior_reviews:
            prior_context += f"[{pr['tier']} / {pr['model_used']}]: {str(pr.get('review_text',''))[:300]}\n"

    agent_section = "\n=== AGENT PERSPECTIVES REQUIRED ===\n"
    for agent, instruction in AGENT_PERSPECTIVES.items():
        agent_section += f"{agent}: {instruction}\n"

    return f"""You are a {TIER_CONFIG[tier]['description']} for an automated paper trading system.
Review this closed trade thoroughly. Provide specific, actionable analysis.

=== TRADE DATA ===
Symbol: {t.get('symbol')} | Strategy: {t.get('strategy_id')} | Setup: {t.get('setup_type') or 'N/A'}
Entry: ${entry:.2f} | Exit: ${exit_p:.2f} | Stop: ${stop:.2f} | Target: ${target:.2f}
P&L: ${pnl:+.2f} | R-Multiple: {f'{r_mult:.2f}R' if r_mult else 'N/A'}
Shares: {t.get('shares')} | Verdict: {t.get('outcome_verdict') or 'N/A'}
Hold time: {t.get('hold_time_min') or 'N/A'} min | Exit reason: {t.get('exit_reason') or 'N/A'}
Market regime: {t.get('market_regime') or 'N/A'} | VIX: {t.get('vix_at_entry') or 'N/A'}
Catalyst: {(t.get('catalyst_at_entry') or 'None')[:100]}
Catalyst verified: {t.get('catalyst_verified')} | RVOL: {t.get('rvol_at_entry') or 'N/A'}
MAE: {t.get('max_adverse_excursion') or 'N/A'}% | MFE: {t.get('max_favorable_excursion') or 'N/A'}%
Signal grade: {t.get('signal_grade') or 'N/A'} | Score: {t.get('score_at_entry') or 'N/A'}
{prior_context}
{agent_section}
Answer as JSON:
{{"summary":"2-3 sentence trade summary","what_worked":["specific thing 1"],"what_failed":["specific thing 1"],"lessons":["actionable lesson 1"],"risk_agent":"risk perspective (2-3 sentences)","strategy_agent":"strategy perspective","execution_agent":"execution perspective","learning_agent":"what the system should remember","should_repeat":true/false,"regime_fit":"was market regime appropriate for this strategy?","confidence":0.0-1.0,"recommended_rule_changes":["specific rule change if any"]}}"""


def _build_weekly_prompt(trades, prior_reviews_by_id, tier):
    """Build weekly summary prompt across all trades."""
    trade_summaries = []
    for t in trades:
        pnl = float(t.get('pnl') or 0)
        trade_summaries.append(
            f"  {t.get('symbol')} ({t.get('strategy_id')}): ${pnl:+.2f}, "
            f"R={t.get('r_multiple') or 'N/A'}, "
            f"verdict={t.get('outcome_verdict') or 'N/A'}, "
            f"regime={t.get('market_regime') or 'N/A'}"
        )

    total_pnl = sum(float(t.get('pnl') or 0) for t in trades)
    wins = sum(1 for t in trades if (float(t.get('pnl') or 0)) > 0)
    losses = sum(1 for t in trades if (float(t.get('pnl') or 0)) < 0)

    # Include overnight reviews
    all_reviews = []
    for t in trades:
        reviews = prior_reviews_by_id.get(t['id'], [])
        for r in reviews:
            all_reviews.append(f"[{t.get('symbol')} {r['tier']}]: {str(r.get('review_text',''))[:200]}")

    return f"""You are producing a WEEKLY TRADING REVIEW for an automated paper trading system.
Analyze ALL trades from this week as a portfolio. Find patterns, systemic issues, and strategic recommendations.

=== WEEK SUMMARY ===
Total trades: {len(trades)} | Wins: {wins} | Losses: {losses} | Net P&L: ${total_pnl:+.2f}

=== INDIVIDUAL TRADES ===
{chr(10).join(trade_summaries)}

=== PRIOR REVIEWS (overnight analyses) ===
{chr(10).join(all_reviews[:10]) if all_reviews else 'None available'}

Answer as JSON:
{{"weekly_summary":"3-5 sentence overview of trading week","patterns_detected":["pattern 1"],"systemic_issues":["issue 1"],"strategy_performance":{{"strategy_name":"assessment"}},"risk_management_grade":"A/B/C/D/F with explanation","best_trade":"symbol and why","worst_trade":"symbol and why","regime_assessment":"was the system trading in favorable conditions?","recommended_changes":["specific actionable change 1"],"learning_agent_memory":["key fact to remember for next week"],"confidence":0.0-1.0}}"""


def _save_review(conn, trade_id, tier, model, review_text, agent_commentaries, raw_response):
    """Save review to DB and index into RAG."""
    cur = conn.cursor()

    # Save to multi_reviews table
    try:
        cur.execute("""
            INSERT INTO paper_trade_multi_reviews
                (paper_trade_id, tier, model_used, review_text, agent_commentaries, raw_response, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (paper_trade_id, tier) DO UPDATE SET
                model_used = EXCLUDED.model_used, review_text = EXCLUDED.review_text,
                agent_commentaries = EXCLUDED.agent_commentaries, raw_response = EXCLUDED.raw_response,
                created_at = NOW()
        """, [trade_id, tier, model, review_text, json.dumps(agent_commentaries), raw_response])
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error(f"Failed to save review: {e}")
        return

    # Write agent commentaries to agent_curation_events
    if agent_commentaries:
        for agent, commentary in agent_commentaries.items():
            if commentary and len(str(commentary)) > 10:
                cur.execute("""
                    INSERT INTO agent_curation_events
                        (paper_trade_id, symbol, strategy_id, agent_name, event_type, event_summary, payload)
                    SELECT %s, symbol, strategy_id, %s, %s, %s, %s
                    FROM paper_trades WHERE id = %s
                """, [trade_id, agent, f'{tier.upper()}_REVIEW',
                      str(commentary)[:500], json.dumps({"tier": tier, "model": model}),
                      trade_id])

    # Index into RAG
    try:
        trade = None
        cur.execute("SELECT symbol, strategy_id, outcome_verdict, pnl FROM paper_trades WHERE id=%s", [trade_id])
        row = cur.fetchone()
        if row:
            sym, strat, verdict, pnl = row
            embed_text = f"{sym} {strat} {tier} review: {review_text[:500]}"
            title = f"{sym} {tier} review: {verdict} ${float(pnl or 0):+.2f} ({strat})"
            from rag_retrieval import embed_text as _embed
            vec = _embed(embed_text[:2000])
            if vec:
                # Use a deterministic integer ID for source_id (trade_id * 10 + tier offset)
                _tier_offset = {"realtime": 1, "overnight": 2, "weekly": 3, "monthly": 4}.get(tier, 0)
                _review_source_id = trade_id * 10 + _tier_offset
                cur.execute("""
                    INSERT INTO content_embeddings (source_type, source_id, title, embedding, embedding_model, embedding_dim, created_at)
                    VALUES ('trade_review', %s, %s, %s, 'nomic-embed-text', %s, NOW())
                    ON CONFLICT (source_type, source_id) DO UPDATE SET
                        title = EXCLUDED.title, embedding = EXCLUDED.embedding, created_at = NOW()
                """, [_review_source_id, title[:300], json.dumps(vec), len(vec)])
    except Exception as e:
        log.warning(f"RAG index failed: {e}")

    # Write learning to agent_intelligence_rules
    if agent_commentaries.get('learning_agent'):
        try:
            cur.execute("""
                INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
                VALUES ('trade_learning', %s, %s, %s, NOW())
                ON CONFLICT (rule_type, rule_key) DO UPDATE SET config=EXCLUDED.config, updated_at=NOW()
            """, [f"trade_{trade_id}_{tier}",
                  json.dumps({"learning": agent_commentaries['learning_agent'],
                              "tier": tier, "model": model, "trade_id": trade_id}),
                  f"multi_tier_{tier}"])
        except Exception:
            pass

    conn.commit()


def _save_weekly_summary(conn, tier, model, summary_text, trades_reviewed, raw_response):
    """Save weekly/monthly summary."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO paper_trade_multi_reviews
            (paper_trade_id, tier, model_used, review_text, agent_commentaries, raw_response, created_at)
        VALUES (0, %s, %s, %s, %s, %s, NOW())
    """, [tier, model, summary_text,
          json.dumps({"trades_reviewed": trades_reviewed}), raw_response])

    # Index weekly summary into RAG
    try:
        from rag_retrieval import embed_text as _embed
        week = datetime.now().strftime("%Y-W%V")
        vec = _embed(summary_text[:2000])
        if vec:
            cur.execute("""
                INSERT INTO content_embeddings (source_type, source_id, title, embedding, embedding_model, embedding_dim, created_at)
                VALUES ('weekly_review', %s, %s, %s, 'nomic-embed-text', %s, NOW())
                ON CONFLICT (source_type, source_id) DO UPDATE SET
                    title = EXCLUDED.title, embedding = EXCLUDED.embedding, created_at = NOW()
            """, [f"{tier}_{week}", f"{tier} trading review {week}"[:300], json.dumps(vec), len(vec)])
    except Exception:
        pass

    conn.commit()


def _cloud_review_trade(trade, summary, parsed):
    """ADVISORY ONLY: free-OAuth ChatGPT+Grok review of the LOCAL model's trade-review
    conclusion. Additive — never affects tier scores or any decision. Gated by
    CLOUD_REVIEW=1, guarded by availability, capped per run, and never raises."""
    global _cloud_review_count
    if not CLOUD_REVIEW_ENABLED or _cloud_review_count >= CLOUD_REVIEW_MAX:
        return None
    try:
        import cloud_review
        if not cloud_review.available():
            return None
        _cloud_review_count += 1
        symbol = trade.get('symbol')
        # Safe facts only — no dollar amounts, account ids, or P&L.
        context = {
            "symbol": symbol,
            "strategy": trade.get('strategy_id'),
            "setup": trade.get('setup_type'),
            "outcome_verdict": trade.get('outcome_verdict'),
            "market_regime": trade.get('market_regime'),
            "signal_grade": trade.get('signal_grade'),
            "catalyst_verified": trade.get('catalyst_verified'),
            "rvol_at_entry": trade.get('rvol_at_entry'),
            "exit_reason": trade.get('exit_reason'),
        }
        r = cloud_review.review(
            "trade_review",
            local_output=str(summary)[:4000] if summary else json.dumps(parsed, default=str)[:4000],
            context=context, symbol=symbol, source="multi_tier_trade_reviewer",
        )
        cons = (r or {}).get("consensus") or {}
        concerns = []
        for lane in (r or {}).get("lanes", {}).values():
            concerns.extend(lane.get("concerns") or [])
        return {"verdict": cons.get("verdict", "UNKNOWN"), "concerns": concerns[:8],
                "lanes_ok": cons.get("lanes_ok", 0)}
    except Exception as e:
        log.warning(f"cloud_review skipped: {e}")
        return None


def review_trade(conn, trade, tier, dry_run=False):
    """Review a single trade at the specified tier."""
    trade_id = trade['id']
    symbol = trade['symbol']
    cfg = TIER_CONFIG[tier]

    # Get prior reviews for context building
    prior_reviews = _get_existing_reviews(conn, trade_id)
    lower_reviews = [r for r in prior_reviews if r['tier'] != tier]

    prompt = _build_trade_prompt(trade, tier, lower_reviews if lower_reviews else None)

    if dry_run:
        log.info(f"[dry-run] Would review {symbol} #{trade_id} with {cfg['model']} ({tier})")
        return {"success": True, "dry_run": True}

    log.info(f"Reviewing {symbol} #{trade_id} with {cfg['model']} ({tier})...")
    raw = _generate(prompt, tier)
    if not raw:
        log.warning(f"LLM returned empty for {symbol} ({tier})")
        return {"success": False, "error": "empty_response"}

    # Parse JSON
    parsed = None
    try:
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end])
    except Exception:
        pass

    summary = parsed.get('summary', raw[:500]) if parsed else raw[:500]
    agent_commentaries = {}
    if parsed:
        for agent in AGENT_PERSPECTIVES:
            if parsed.get(agent):
                agent_commentaries[agent] = parsed[agent]
        if parsed.get('learning_agent'):
            agent_commentaries['learning_agent'] = parsed['learning_agent']

    _save_review(conn, trade_id, tier, cfg['model'], summary, agent_commentaries, raw[:2000])
    log.info(f"Review saved for {symbol} #{trade_id} ({tier}, {cfg['model']})")
    result = {"success": True, "symbol": symbol, "tier": tier, "model": cfg['model'], "parsed": parsed is not None}

    # ADVISORY extra tier: free-OAuth cloud review of the local model's conclusion.
    # Additive only — does not alter tier scoring or any pass/fail decision.
    cloud = _cloud_review_trade(trade, summary, parsed)
    if cloud:
        result["cloud_review"] = cloud
        log.info(f"Cloud review for {symbol} #{trade_id}: {cloud['verdict']} ({cloud['lanes_ok']} lanes)")
    return result


def run_tier(tier, trade_id=None, dry_run=False):
    """Run a specific review tier."""
    conn = _get_conn()
    cfg = TIER_CONFIG[tier]

    if tier == "realtime":
        if not trade_id:
            log.error("Realtime tier requires --trade-id")
            return {"error": "trade_id required"}
        trades = _get_closed_trades(conn, trade_id=trade_id)

    elif tier == "overnight":
        trades = _get_closed_trades(conn, since_hours=24)

    elif tier == "weekly":
        # All trades closed this week
        week_start = datetime.now(timezone.utc) - timedelta(days=7)
        trades = _get_closed_trades(conn, since_date=week_start)

        if not trades:
            log.info("No trades to review for weekly summary")
            return {"trades_reviewed": 0}

        # First do individual reviews, then aggregate
        results = []
        for trade in trades:
            r = review_trade(conn, trade, tier, dry_run)
            results.append(r)

        # Build weekly summary
        prior_by_id = {}
        for t in trades:
            prior_by_id[t['id']] = _get_existing_reviews(conn, t['id'])

        weekly_prompt = _build_weekly_prompt(trades, prior_by_id, tier)
        if not dry_run:
            raw = _generate(weekly_prompt, tier)
            if raw:
                _save_weekly_summary(conn, tier, cfg['model'], raw[:3000], len(trades), raw)
                log.info(f"Weekly summary saved ({len(trades)} trades, {cfg['model']})")

        conn.close()
        return {"tier": tier, "trades_reviewed": len(trades), "results": results}

    elif tier == "monthly":
        # Review all weekly summaries from past month + any flagged trades
        month_start = datetime.now(timezone.utc) - timedelta(days=30)
        trades = _get_closed_trades(conn, since_date=month_start)

        if not trades:
            log.info("No trades to review for monthly summary")
            return {"trades_reviewed": 0}

        # Get weekly summaries
        cur = conn.cursor()
        cur.execute("""
            SELECT tier, model_used, review_text, created_at
            FROM paper_trade_multi_reviews
            WHERE tier = 'weekly' AND created_at >= %s
            ORDER BY created_at
        """, [month_start])
        weekly_summaries = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]

        # Also get flagged daily trades (any with blockers/warnings in reviews)
        prior_by_id = {}
        for t in trades:
            prior_by_id[t['id']] = _get_existing_reviews(conn, t['id'])

        monthly_prompt = _build_weekly_prompt(trades, prior_by_id, tier)
        if not dry_run:
            raw = _generate(monthly_prompt, tier)
            if raw:
                _save_weekly_summary(conn, tier, cfg['model'], raw[:5000], len(trades), raw)
                log.info(f"Monthly summary saved ({len(trades)} trades, {cfg['model']})")

        conn.close()
        return {"tier": tier, "trades_reviewed": len(trades)}

    else:
        return {"error": f"Unknown tier: {tier}"}

    # For realtime/overnight: review each trade individually
    results = []
    for trade in trades:
        r = review_trade(conn, trade, tier, dry_run)
        results.append(r)

    conn.close()
    return {"tier": tier, "trades_reviewed": len(trades), "results": results}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    parser = argparse.ArgumentParser(description="Multi-tier trade reviewer")
    parser.add_argument("--tier", required=True, choices=["realtime", "overnight", "weekly", "monthly"])
    parser.add_argument("--trade-id", type=int, help="Specific trade ID (required for realtime)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = run_tier(args.tier, args.trade_id, args.dry_run)
    print(json.dumps(result, indent=2, default=str))
