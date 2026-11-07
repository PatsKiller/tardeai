#!/usr/bin/env python3
"""incubator_llm_screener.py — Lightweight LLM screen for top incubator candidates.

Runs governed DeepSeek Flash on incubator symbols (score >= 40) enriched with catalyst, news,
social, and technical data. Sets llm_screen_grade (A-F) and llm_screen_verdict
(PROMOTE/HOLD/DROP) before the promoter runs.

Usage:
    .venv/bin/python3 scripts/incubator_llm_screener.py --dry-run
    .venv/bin/python3 scripts/incubator_llm_screener.py --run --limit 10

Governed bridge (2026-10-15, n8n llm lane batch 1): with TRADEAI_LLM_VIA_BRIDGE=1 (bound by the n8n run executor from
the allowlist ``llm_route`` of lane incubator-llm-screener) the screen is ONE governed-bridge request as process
``incubator_llm_screener`` (grok -> chatgpt -> DeepSeek server-side); llm_lane is never imported and the optional
in-process cloud_review (CLOUD_REVIEW=1) is skipped, so no provider client is reachable. A refusal is a per-symbol
``error`` (no UPDATE). --dry-run makes no model call. The cron line is unchanged.

Refusal is named once, at run level (LQ-20261107-86, 2026-11-07): the process was registered ``default_mode:
manual`` and ``llm_consumption._seed_registry`` rewrites ``llm_process_config.mode`` from that registry value on
every process start, so the in-process lane was refused ``manual_mode`` for the whole run. From 2026-08-27
to 2026-11-07 that produced ten identical ``screen failed`` warnings per weekday run, a log mtime that read as a
healthy lane, and exit 0 — 10 weeks of silence. ``preflight()`` asks the governor once and, when it refuses, logs
ONE line naming the gate and the operator decision that would change it, skips the per-symbol loop entirely and
exits ``EXIT_REFUSED``. A run the governor allows that screens nothing exits ``EXIT_NO_SCREENS``. The gate itself is
not bypassed here: arming an LLM lane is the operator's decision (AGENTS.md §17), and ``default_mode`` is set in
config/llm_process_registry.json.

Route (operator 2026-11-07: "use the free Anthropic API lanes (lower model OK)"): the row's ``default_mode`` is now
``automated``, so the governor allows the cron run, and because the row is ``anthropic_first`` and its id is in
``bulk_processes`` the gate serves it from the promotional credit lane as ``claude-haiku-5-5`` (tier ``bulk``) before
it would ever consider paid DeepSeek. This script does not pick a provider — ``lib.llm_consumption.gate_and_generate``
does — so ``preflight()`` reports the lane the gate will pick and ``served_lane()`` reads the provider/model the
gate's own provenance says actually answered, instead of the constant "deepseek-flash" this file used to write into
``incubator_universe.llm_screen_model``.

Receipt: the lane's registry ``output_signal`` is ``data/runtime/incubator-llm-screener_last.json`` (json_key
``ok_at``) and no code wrote it, so the lane's only evidence was the cron redirect's log mtime. Every real exit now
writes it through ``lib.lane_last_receipt`` — success, a governor refusal, and zero screens alike, with
produced/attempted counts and the providers that answered. A ``--dry-run`` writes nothing.
"""
import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (LQ-20261107-25, 2026-11-07): --dry-run is an OFFLINE plan and wins over --run. It returns here,
    # before the .env load, before argparse and before get_db(), so an onboarding dry run needs no database password
    # and reaches no provider: the executor runs this arm as the lane's write-free shadow step (AGENTS §23 onboarding
    # steps 3-8). Before this arm the flag existed but the DB connection came first, so the shadow step failed with
    # `psycopg2.OperationalError: no password supplied` -- a dry run that cannot run is not a proof.
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "incubator-llm-screener"
    _dr_would = (
        "fetch up to --limit incubator candidates at score >= 40, enrich each (catalyst, news, social, technical), "
        "screen it as process incubator_llm_screener on whichever route this run would take (the governed bridge when "
        "TRADEAI_LLM_VIA_BRIDGE is bound by the n8n executor, else the in-process gate and its credit/DeepSeek lane), "
        "and write llm_screen_grade / llm_screen_verdict back to incubator_universe"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="incubator_candidate"))
    raise SystemExit(0)

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

os.environ.setdefault("DOTENV_LOADED", "0")
if os.environ["DOTENV_LOADED"] == "0":
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        os.environ["DOTENV_LOADED"] = "1"
    except Exception:
        pass

log = logging.getLogger("incubator_screener")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

MIN_SCORE = 40

# Advisory cloud-review cap (ADDITIVE — gated behind CLOUD_REVIEW=1)
_CLOUD_REVIEW_CAP = 5
_cloud_review_count = 0

# ── Strategy group constants for strategy-aware grading ──────────────────

INCOME_STRATEGIES = {
    'income_add', 'dividend_growth_compounder',
    'high_yield_income_bdc', 'covered_call_income',
}

GROWTH_STRATEGIES = {
    'core_growth_compounder', 'sector_rotation',
    'defense_thesis', 'speculative_growth',
}

REVERSION_STRATEGIES = {
    'swing_trade', 'recovery_watch', 'bond_income', 'cash_or_stable',
}

MOMENTUM_STRATEGIES = {
    'momentum_scalp', 'gap_and_go', 'swing_breakout',
    'earnings_catalyst',
}


def get_db():
    import psycopg2, psycopg2.extras
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def fetch_candidates(conn, limit=10):
    """Get top incubator candidates needing LLM screen."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (symbol) symbol, strategy_id, latest_score, best_score,
               catalyst, catalyst_verified, sector, industry,
               rvol_latest, gap_latest, days_active, evidence_payload,
               lifecycle_state, score_delta
        FROM incubator_universe
        WHERE status = 'ACTIVE'
          AND latest_score >= %s
          AND promoted_to_proposal_at IS NULL
          AND (llm_screen_at IS NULL OR llm_screen_at < NOW() - INTERVAL '24 hours')
        ORDER BY symbol, latest_score DESC
        LIMIT %s
    """, [MIN_SCORE, limit])
    candidates = [dict(r) for r in cur.fetchall()]

    # Enrich with latest scan decision (GO/WAIT/AVOID)
    if candidates:
        syms = [c['symbol'] for c in candidates]
        cur.execute("""
            SELECT DISTINCT ON (symbol) symbol, decision, score, grade
            FROM trade_ai_scans
            WHERE symbol = ANY(%s) AND run_date >= CURRENT_DATE - INTERVAL '2 days'
            ORDER BY symbol, scanned_at DESC
        """, [syms])
        scan_map = {r['symbol']: dict(r) for r in cur.fetchall()}
        for c in candidates:
            scan = scan_map.get(c['symbol'], {})
            c['scan_decision'] = scan.get('decision')
            c['scan_score'] = scan.get('score')
            c['scan_grade'] = scan.get('grade')

    # Sort: GO first, then WAIT, then others — highest score within each group
    decision_priority = {'GO': 0, 'WAIT': 1}
    candidates.sort(key=lambda c: (
        decision_priority.get(c.get('scan_decision', ''), 2),
        -(c.get('latest_score') or 0)
    ))

    return candidates


def fetch_news(conn, symbol, limit=5):
    """Get recent news headlines for symbol."""
    cur = conn.cursor()
    cur.execute("""
        SELECT title, source, sentiment, published_at
        FROM news_articles
        WHERE symbol = %s AND published_at > NOW() - INTERVAL '7 days'
        ORDER BY published_at DESC LIMIT %s
    """, [symbol, limit])
    return [dict(r) for r in cur.fetchall()]


def fetch_social(conn, symbol, limit=5):
    """Get recent social mentions."""
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT text, platform, sentiment, post_date
            FROM social_posts
            WHERE symbols_mentioned @> %s::jsonb
              AND post_date > NOW() - INTERVAL '7 days'
            ORDER BY post_date DESC LIMIT %s
        """, [json.dumps([symbol]), limit])
        rows = [dict(r) for r in cur.fetchall()]
        # Normalize field names
        for r in rows:
            r['body'] = r.pop('text', '')
            r['source'] = r.pop('platform', '')
        return rows
    except Exception:
        conn.rollback()
        # Fallback: try simple text match
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT text as body, platform as source, sentiment, post_date
                FROM social_posts
                WHERE text ILIKE %s
                  AND post_date > NOW() - INTERVAL '7 days'
                ORDER BY post_date DESC LIMIT %s
            """, [f'%{symbol}%', limit])
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            conn.rollback()
            return []


def fetch_technical(conn, symbol):
    """Get latest technical snapshot from confluence cache."""
    cur = conn.cursor()
    cur.execute("""
        SELECT confluence_score, confluence_tier, atr, adx_regime,
               entry_quality, full_result
        FROM indicator_confluence_cache
        WHERE symbol = %s ORDER BY computed_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if not row:
        return {}
    result = dict(row)
    # Extract key indicators from full_result JSON
    fr = result.get('full_result')
    if fr:
        if isinstance(fr, str):
            try:
                fr = json.loads(fr)
            except Exception:
                fr = {}
        if isinstance(fr, dict):
            result['rsi_14'] = fr.get('rsi') or fr.get('rsi_14')
            result['rvol'] = fr.get('rvol')
            result['vwap_distance_pct'] = fr.get('vwap_distance_pct')
            result['technical_grade'] = fr.get('technical_grade') or result.get('confluence_tier')
    return result


def build_screen_prompt(candidate, news, social, technical, web_news_line=""):
    """Build lightweight screening prompt — single chunk, ~200 tokens output."""
    symbol = candidate['symbol']
    score = candidate['latest_score']
    catalyst = candidate.get('catalyst') or 'None'
    cat_v = candidate.get('catalyst_verified', False)
    sector = candidate.get('sector') or '?'
    rvol = candidate.get('rvol_latest') or '?'
    gap = candidate.get('gap_latest') or '?'
    days = candidate.get('days_active') or 0
    delta = candidate.get('score_delta') or 0
    lifecycle = candidate.get('lifecycle_state') or '?'

    # News summary
    news_lines = "No recent news."
    if news:
        news_lines = " | ".join([
            f"{n['title'][:60]} ({n.get('sentiment', '?')})"
            for n in news[:3]
        ])

    # Social summary
    social_lines = "No social mentions."
    if social:
        social_lines = f"{len(social)} posts. " + " | ".join([
            f"{str(s.get('body', ''))[:50]}({s.get('sentiment', '?')})"
            for s in social[:2]
        ])

    # Technical
    tech_line = "No technical data."
    if technical:
        t = technical
        parts = []
        if t.get('rsi_14'): parts.append(f"RSI:{t['rsi_14']:.0f}")
        if t.get('atr_14'): parts.append(f"ATR:${t['atr_14']:.2f}")
        if t.get('rvol'): parts.append(f"RVOL:{t['rvol']:.1f}x")
        if t.get('technical_grade'): parts.append(t['technical_grade'])
        if t.get('adx_regime'): parts.append(f"ADX:{t['adx_regime']}")
        tech_line = " ".join(parts) if parts else tech_line

    scan_decision = candidate.get('scan_decision') or '?'
    scan_grade = candidate.get('scan_grade') or '?'

    return f"""Incubator screening. Grade this stock for paper trade promotion readiness.
{symbol} score={score} delta={delta:+.0f} days={days:.0f} lifecycle={lifecycle}
Scan:{scan_decision} grade={scan_grade}
Sector:{sector} RVOL:{rvol} Gap:{gap}
Catalyst:{str(catalyst)[:80]}{'(V)' if cat_v else '(UV)'}
Tech:{tech_line}
News:{news_lines[:200]}
{web_news_line[:200] if web_news_line else ''}
Social:{social_lines[:150]}
If scan=AVOID, verdict should be DROP unless strong catalyst overrides.
JSON only:
{{"screen_grade":"A|B|C|D|F","verdict":"PROMOTE|HOLD|DROP","confidence":0-100,"reasoning":"1-2 sentences","catalyst_assessment":"strong|moderate|weak|none","momentum":"building|stable|fading"}}"""


def _build_income_grade_prompt(candidate, news_lines, social_lines, tech_line, web_news_line=""):
    """Grade income/dividend candidates. Does NOT penalize low RVOL or missing catalyst."""
    symbol = candidate['symbol']
    score = candidate['latest_score']
    sector = candidate.get('sector') or '?'
    strategy = candidate.get('strategy_id') or 'income_add'
    delta = candidate.get('score_delta') or 0
    days = candidate.get('days_active') or 0
    lifecycle = candidate.get('lifecycle_state') or '?'

    return f"""Income strategy screening. Grade for income/dividend suitability.
{symbol} score={score} delta={delta:+.0f} days={days:.0f} lifecycle={lifecycle}
Strategy:{strategy} Sector:{sector}
News:{news_lines[:200]}
{web_news_line[:200] if web_news_line else ''}

GRADE ON INCOME CRITERIA (not momentum):
A: Yield 3-8%, stable/growing dividend, low beta, large/mid cap, strong balance sheet
B: Yield 2-4%, good dividend history, reasonable valuation, retirement income fit
C: Marginal yield or valuation concern
D: Yield unsustainable or too volatile for income
F: Yield trap or completely wrong fit

Low RVOL is FINE. No catalyst is FINE. Grade on yield quality and stability.
JSON only:
{{"screen_grade":"A|B|C|D|F","verdict":"PROMOTE|HOLD|DROP","confidence":0-100,"reasoning":"1-2 sentences","yield_quality":"sustainable|at_risk|unknown"}}"""


def _build_growth_grade_prompt(candidate, news_lines, social_lines, tech_line, web_news_line=""):
    """Grade growth/compounder/sector candidates on growth criteria."""
    symbol = candidate['symbol']
    score = candidate['latest_score']
    sector = candidate.get('sector') or '?'
    strategy = candidate.get('strategy_id') or 'core_growth_compounder'
    delta = candidate.get('score_delta') or 0
    days = candidate.get('days_active') or 0
    lifecycle = candidate.get('lifecycle_state') or '?'

    return f"""Growth strategy screening. Grade for growth/compounder/sector suitability.
{symbol} score={score} delta={delta:+.0f} days={days:.0f} lifecycle={lifecycle}
Strategy:{strategy} Sector:{sector}
Tech:{tech_line}
News:{news_lines[:200]}
{web_news_line[:200] if web_news_line else ''}

GRADE ON GROWTH CRITERIA:
For core_growth_compounder: consistent EPS growth >10%/yr, strong ROE, durable moat
For sector_rotation: leading sector this week/month, relative strength vs peers
For defense_thesis: defense/aerospace/gov-IT, contract backlog, AI-defense exposure

A: Exceptional fit — clear compounder or sector leader
B: Good fit — above-average growth or sector strength
C: Marginal — some growth but not compelling
D: Poor fit — growth decelerating or wrong sector
F: Wrong strategy fit entirely

JSON only:
{{"screen_grade":"A|B|C|D|F","verdict":"PROMOTE|HOLD|DROP","confidence":0-100,"reasoning":"1-2 sentences","growth_quality":"accelerating|stable|decelerating|unknown"}}"""


def _build_reversion_grade_prompt(candidate, news_lines, social_lines, tech_line, web_news_line=""):
    """Grade reversion/pullback candidates. Rewards oversold quality."""
    symbol = candidate['symbol']
    score = candidate['latest_score']
    sector = candidate.get('sector') or '?'
    strategy = candidate.get('strategy_id') or 'swing_trade'
    rvol = candidate.get('rvol_latest') or '?'
    delta = candidate.get('score_delta') or 0
    days = candidate.get('days_active') or 0
    lifecycle = candidate.get('lifecycle_state') or '?'

    return f"""Reversion strategy screening. Grade for pullback/value suitability.
{symbol} score={score} delta={delta:+.0f} days={days:.0f} lifecycle={lifecycle}
Strategy:{strategy} Sector:{sector} RVOL:{rvol}
Tech:{tech_line}
News:{news_lines[:200]}
{web_news_line[:200] if web_news_line else ''}

GRADE ON REVERSION CRITERIA (opposite of momentum):
For swing_trade retracement: RSI <45, above 200d SMA, pulling back from strength
For recovery_watch: recently sold off, thesis intact, waiting for catalyst
For bond_income: yield vs current rates, duration fit, credit quality

A: Excellent reversion — oversold quality, clear support, buyable dip
B: Good — pulling back but thesis intact
C: Marginal — oversold but fundamentals unclear
D: Broken — falling for good reason, avoid
F: Extended/overbought (opposite of what we want)

Low RVOL is FINE. No catalyst is FINE. Grade on oversold quality.
JSON only:
{{"screen_grade":"A|B|C|D|F","verdict":"PROMOTE|HOLD|DROP","confidence":0-100,"reasoning":"1-2 sentences","setup_quality":"textbook|decent|marginal|broken"}}"""


#: Registered process (config/llm_process_registry.json) and its governed-bridge route
#: (scripts/lib/governed_process_routes.py advisory_desk / incubator_llm_screener).
LLM_PROCESS_ID = "incubator_llm_screener"
#: The lane id its registry ``output_signal`` names (data/runtime/<lane>_last.json, json_key ok_at).
LANE_ID = "incubator-llm-screener"
#: The flag the n8n run executor binds from the allowlist llm_route. Read directly so a failed import with the flag
#: ON can never fall through to the in-process provider path.
VIA_BRIDGE_ENV = "TRADEAI_LLM_VIA_BRIDGE"


def _via_bridge():
    return os.environ.get(VIA_BRIDGE_ENV, "off").strip().lower() in {"1", "on", "bridge"}


#: How this run reaches a model. ``bridge`` = the n8n executor bound the flag; ``in_process`` = the
#: governor allows the DeepSeek lane; ``unknown`` = the governor could not be read (per-symbol path decides);
#: ``dry_run`` = no model call at all.
ROUTE_ENV = "env_bridge"
ROUTE_IN_PROCESS = "in_process"
ROUTE_UNKNOWN = "unknown"
ROUTE_DRY = "dry_run"

#: A run its own governance gate refuses — it screened nothing by design, not by accident.
EXIT_REFUSED = 3
#: The run was allowed to screen, and not one symbol produced a screen.
EXIT_NO_SCREENS = 4


#: The governor could not be asked at all. An explicit unknown, never a falsey "no".
UNREADABLE = "unreadable"


def governor_decision(process_id=LLM_PROCESS_ID):
    """The governor's answer dict for this process's in-process lane, or ``UNREADABLE``."""
    try:
        from lib.llm_consumption import should_call
    except Exception:
        try:
            # same module, flat import: this script puts scripts/ on sys.path itself
            from llm_consumption import should_call  # type: ignore -- flat-module fallback, see scripts/lib/llm_consumption.py
        except Exception:
            return UNREADABLE
    try:
        return should_call(process_id, "deepseek-flash")
    except Exception:
        return UNREADABLE


def promo_route_label(process_id=LLM_PROCESS_ID):
    """The promotional-credit lane this process will be served by, or '' when it will not be.

    Same three questions ``lib.llm_consumption.gate_and_generate`` asks before it hands a call to
    ``lib.anthropic_routing.generate_in_process`` (``eligible`` -> ``credit_admitted`` -> ``active``), asked here once so
    the run can SAY which lane it used. Read-only: no reservation, no provider, no file write. An exception is '' —
    an unreadable credit book is never reported as a route.
    """
    try:
        from lib import anthropic_routing as promo
        from lib import llm_consumption as lc
    except ImportError:  # pragma: no cover - flat layout
        return ""
    try:
        cfg = lc.get_process_config(process_id)
        if not promo.active(process_id, cfg):
            return ""
        tier = promo.tier_for("FAST", process_id=process_id)
        model = str((promo.load_policy().get("models") or {}).get(tier) or "")
        return f"anthropic promotional credit [{tier}:{model}]" if model else "anthropic promotional credit"
    except Exception:  # noqa: BLE001 -- a label must never change the run
        return ""


def paid_route_label():
    """The lane an allowed run falls to when the credit lane is not usable."""
    return "deepseek-flash paid (per-process caps; queued off-peak while LLM_DEFER_OFFPEAK=1)"


def preflight():
    """One decision for the whole run, asked before the first symbol. Never calls a provider.

    Returns ``(route, refusal, lane_label)``. A refusal is a one-line cause: the run cannot screen anything, and
    saying so once with the gate named is the difference between "the lane is off on purpose" and ten identical
    ``screen failed`` warnings that read as a provider outage. It does NOT route around the gate: arming an
    LLM lane is the operator's decision (AGENTS.md §17), and ``default_mode`` lives in
    config/llm_process_registry.json.
    """
    if _via_bridge():
        return ROUTE_ENV, None, "governed bridge (n8n llm_route)"
    decision = governor_decision()
    if decision is UNREADABLE:
        return ROUTE_UNKNOWN, None, "unknown (governor unreadable; the per-symbol path decides)"
    if decision.get("allow"):
        return ROUTE_IN_PROCESS, None, promo_route_label() or paid_route_label()
    why = str(decision.get("reason") or "denied")
    mode = decision.get("mode")
    return ROUTE_IN_PROCESS, (
        f"governor refuses process {LLM_PROCESS_ID} lane deepseek-flash "
        f"(reason={why}, mode={mode}); llm_process_config.mode is re-seeded from "
        f"config/llm_process_registry.json default_mode on every process start, so unblocking this run is an "
        f"operator decision: register the lane as automated, or retire the cron line"
    ), ""


def served_lane(provenance):
    """``(provider, model)`` the answer actually came from, read from the gate's own provenance.

    The credit lane answers as an Anthropic model while the script asks for the ``deepseek-flash`` lane, so a
    constant "deepseek-flash" in ``incubator_universe.llm_screen_model`` would be a screen saying something untrue.
    Both values are ``unknown`` when the gate returned no provenance — never a guess.
    """
    prov = dict(provenance or {})
    provider = str(prov.get("provider") or "").strip().lower()
    model = str(prov.get("returned_model") or prov.get("requested_model_id") or "").strip()
    if not provider:
        provider = "deepseek" if model.lower().startswith("deepseek") else "unknown"
    return provider, (model or "unknown")



def screen_one(conn, candidate, dry_run=False, via_bridge=None):
    """Run LLM screen on one incubator candidate."""
    symbol = candidate['symbol']

    if dry_run:
        log.info(f"[dry-run] Would screen {symbol} (score={candidate['latest_score']})")
        return {'symbol': symbol, 'status': 'dry_run'}

    # Gather enrichment data
    news = fetch_news(conn, symbol)
    social = fetch_social(conn, symbol)
    technical = fetch_technical(conn, symbol)

    # Live web news (supplements DB-stored news)
    web_news_line = ""
    try:
        from web_news_fetcher import fetch_web_news
        web_results = fetch_web_news(symbol, max_results=3)
        if web_results:
            web_news_line = "LiveWeb: " + " | ".join(
                f"{r['title'][:50]} ({r.get('age', '?')})" for r in web_results[:2]
            )
    except Exception:
        pass

    # Select strategy-appropriate prompt based on strategy_id
    strategy_id = candidate.get('strategy_id') or ''
    if strategy_id in INCOME_STRATEGIES:
        # Build condensed enrichment strings for strategy-aware prompts
        news_str = "No recent news."
        if news:
            news_str = " | ".join(f"{n['title'][:60]} ({n.get('sentiment','?')})" for n in news[:3])
        social_str = f"{len(social)} posts" if social else "No social mentions."
        tech_str = ""
        if technical:
            parts = []
            if technical.get('rsi_14'): parts.append(f"RSI:{technical['rsi_14']:.0f}")
            if technical.get('technical_grade'): parts.append(technical['technical_grade'])
            tech_str = " ".join(parts) if parts else "No technical data."
        prompt = _build_income_grade_prompt(candidate, news_str, social_str, tech_str, web_news_line)
    elif strategy_id in GROWTH_STRATEGIES:
        news_str = "No recent news."
        if news:
            news_str = " | ".join(f"{n['title'][:60]} ({n.get('sentiment','?')})" for n in news[:3])
        social_str = f"{len(social)} posts" if social else "No social mentions."
        tech_str = ""
        if technical:
            parts = []
            if technical.get('rsi_14'): parts.append(f"RSI:{technical['rsi_14']:.0f}")
            if technical.get('rvol'): parts.append(f"RVOL:{technical['rvol']:.1f}x")
            if technical.get('technical_grade'): parts.append(technical['technical_grade'])
            tech_str = " ".join(parts) if parts else "No technical data."
        prompt = _build_growth_grade_prompt(candidate, news_str, social_str, tech_str, web_news_line)
    elif strategy_id in REVERSION_STRATEGIES:
        news_str = "No recent news."
        if news:
            news_str = " | ".join(f"{n['title'][:60]} ({n.get('sentiment','?')})" for n in news[:3])
        social_str = f"{len(social)} posts" if social else "No social mentions."
        tech_str = ""
        if technical:
            parts = []
            if technical.get('rsi_14'): parts.append(f"RSI:{technical['rsi_14']:.0f}")
            if technical.get('technical_grade'): parts.append(technical['technical_grade'])
            if technical.get('adx_regime'): parts.append(f"ADX:{technical['adx_regime']}")
            tech_str = " ".join(parts) if parts else "No technical data."
        prompt = _build_reversion_grade_prompt(candidate, news_str, social_str, tech_str, web_news_line)
    else:
        # Default: existing momentum prompt (unchanged)
        prompt = build_screen_prompt(candidate, news, social, technical, web_news_line)

    via_bridge = _via_bridge() if via_bridge is None else bool(via_bridge)
    provider = "unknown"
    try:
        if via_bridge:
            from lib.llm_bridge_route import require_text_via_bridge
            raw = require_text_via_bridge(LLM_PROCESS_ID, prompt, timeout_s=120)
        else:
            # The gate (not this script) decides the provider: for an ``anthropic_first`` process whose promotional
            # credit is usable it walks provider_order and answers as an Anthropic model, and only then falls to the
            # DeepSeek lane. ``return_provenance`` is how the run learns WHICH one answered instead of assuming.
            from lib.llm_consumption import gate_and_generate
            raw, provenance = gate_and_generate(
                prompt,
                lane="deepseek-flash",
                process_id=LLM_PROCESS_ID,
                task_summary=f"incubator screen {symbol}",
                timeout=120,
                max_tokens=2048,
                return_provenance=True,
            )
            provider, model = served_lane(provenance)
        if not raw:
            log.warning(f"  {symbol}: LLM returned empty")
            return {'symbol': symbol, 'status': 'empty', 'provider': provider}

        # Parse JSON
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start < 0 or end <= start:
            log.warning(f"  {symbol}: no JSON in response")
            return {'symbol': symbol, 'status': 'parse_error', 'provider': provider}

        result = json.loads(raw[start:end])
        grade = result.get('screen_grade', 'C')
        verdict = result.get('verdict', 'HOLD')
        confidence = min(100, max(0, int(result.get('confidence', 50))))

        if via_bridge:
            model, provider = "governed-bridge", "cio_governed_bridge"

        # Validate
        if grade not in ('A', 'B', 'C', 'D', 'F'):
            grade = 'C'
        if verdict not in ('PROMOTE', 'HOLD', 'DROP'):
            verdict = 'HOLD'

        # Save to DB
        cur = conn.cursor()
        cur.execute("""
            UPDATE incubator_universe
            SET llm_screen_grade = %s,
                llm_screen_verdict = %s,
                llm_screen_confidence = %s,
                llm_screen_model = %s,
                llm_screen_result = %s,
                llm_screen_at = NOW()
            WHERE symbol = %s AND status = 'ACTIVE'
        """, [grade, verdict, confidence, model,
              json.dumps(result, default=str), symbol])
        conn.commit()

        log.info(f"  {symbol}: grade={grade} verdict={verdict} conf={confidence} model={model}")

        # ── ADVISORY: free-OAuth cloud models review the primary model's pick ──
        # Additive + advisory only — never changes grade/verdict/selection.
        # Gated behind CLOUD_REVIEW=1; only PROMOTE/HOLD picks; capped per run.
        cloud_verdict = None
        global _cloud_review_count
        # Never on the governed-bridge path: cloud_review calls OAuth providers in-process.
        if (not via_bridge and os.getenv("CLOUD_REVIEW") == "1" and verdict in ("PROMOTE", "HOLD")
                and _cloud_review_count < _CLOUD_REVIEW_CAP):
            try:
                import cloud_review
                if cloud_review.available():
                    _cloud_review_count += 1
                    cr = cloud_review.review(
                        "incubator_pick_review",
                        local_output=(result.get("reasoning") or "")
                            + f" [primary: grade={grade} verdict={verdict} conf={confidence}]",
                        context={
                            "symbol": symbol,
                            "sector": candidate.get("sector"),
                            "strategy_id": candidate.get("strategy_id"),
                            "score": candidate.get("latest_score"),
                            "scan_decision": candidate.get("scan_decision"),
                            "catalyst": str(candidate.get("catalyst") or "")[:120],
                            "catalyst_verified": candidate.get("catalyst_verified"),
                            "grade": grade, "verdict": verdict,
                        },
                        symbol=symbol,
                        source="incubator_llm_screener",
                    )
                    cloud_verdict = (cr.get("consensus") or {}).get("verdict")
                    if cloud_verdict:
                        result["cloud_review_verdict"] = cloud_verdict
                        try:
                            cur.execute("""
                                UPDATE incubator_universe
                                SET llm_screen_result = %s
                                WHERE symbol = %s AND status = 'ACTIVE'
                            """, [json.dumps(result, default=str), symbol])
                            conn.commit()
                        except Exception:
                            conn.rollback()
                        log.info(f"  {symbol}: cloud_review consensus={cloud_verdict}")
            except Exception as e:
                log.debug(f"  {symbol}: cloud_review skipped — {e}")

        return {'symbol': symbol, 'status': 'screened', 'grade': grade,
                'verdict': verdict, 'confidence': confidence, 'model': model, 'provider': provider,
                'result': result, 'cloud_review_verdict': cloud_verdict}

    except Exception as e:
        log.warning(f"  {symbol}: screen failed — {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return {'symbol': symbol, 'status': 'error', 'error': str(e), 'provider': provider}


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # pragma: no cover - flat layout
        from scripts.lib import lane_last_receipt as lr  # type: ignore[no-redef] -- flat layout: scripts/ is on sys.path, repo root is not
    return lr


def write_receipt(*, ok, exit_code, started_at, produced, attempted, skipped, empty_reason, summary, error=None):
    """Write this lane's declared ``output_signal`` (data/runtime/<lane>_last.json, json_key ok_at).

    The registry declares that file; before 2026-11-07 no code wrote it, so the lane's only output evidence was the
    cron redirect's log mtime — which a refused run updates just as happily as a good one. Never raises and never
    changes the run's own result (AGENTS.md rail 8: exit 0 is not evidence). A dry run does not call this.
    """
    try:
        return _receipt_lib().write_lane_receipt(
            LANE_ID, ok=ok, exit_code=exit_code, started_at=started_at,
            script="incubator_llm_screener.py", summary=summary, error=error,
            produced_count=produced, attempted_count=attempted,
            skipped_reasons=skipped, empty_reason=empty_reason)
    except Exception as e:  # noqa: BLE001 -- the run's result comes first
        log.warning(f"lane receipt not written: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Incubator LLM screener")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--symbol", type=str, help="Screen specific symbol")
    args = parser.parse_args()

    started = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        candidates = fetch_candidates(conn, limit=args.limit)
        if args.symbol:
            candidates = [c for c in candidates if c['symbol'] == args.symbol.upper()]

        log.info(f"Found {len(candidates)} candidates for LLM screening")

        route, refusal, lane_label = (ROUTE_DRY, None, "dry run (no model call)") if args.dry_run else preflight()
        via_bridge = route == ROUTE_ENV
        log.info(f"Route: {lane_label or route} [{route}]")

        results = []
        if refusal:
            # One run-level line naming the gate, instead of one identical per-symbol warning per candidate.
            log.error(f"REFUSED: {refusal}")
        else:
            for c in candidates:
                r = screen_one(conn, c, dry_run=args.dry_run, via_bridge=via_bridge)
                results.append(r)

        # Summary
        screened = sum(1 for r in results if r.get('status') == 'screened')
        errors = sum(1 for r in results if r.get('status') == 'error')
        promotes = sum(1 for r in results if r.get('verdict') == 'PROMOTE')
        holds = sum(1 for r in results if r.get('verdict') == 'HOLD')
        drops = sum(1 for r in results if r.get('verdict') == 'DROP')
        providers = {}
        for r in results:
            p = str(r.get('provider') or '')
            if p:
                providers[p] = providers.get(p, 0) + 1

        print("\nIncubator LLM Screener")
        print(f"{'=' * 40}")
        print(f"  Route:      {lane_label or route} [{route}]")
        print(f"  Refused:    {len(candidates) if refusal else 0}")
        print(f"  Candidates: {len(candidates)}")
        print(f"  Screened:   {screened}")
        print(f"  Errors:     {errors}")
        print(f"  PROMOTE:    {promotes}")
        print(f"  HOLD:       {holds}")
        print(f"  DROP:       {drops}")
        for r in results:
            v = r.get('verdict', r.get('status', '?'))
            g = r.get('grade', '')
            print(f"  {r['symbol']}: {v} {g}")

        # Telegram notification (only if we screened something)
        if screened > 0 and args.run:
            try:
                from telegram_alert import send_telegram
                lines = ["*Incubator LLM Screen*"]
                lines.append(f"Screened: {screened} | PROMOTE: {promotes} | HOLD: {holds} | DROP: {drops}")
                if promotes > 0:
                    lines.append("\n*Ready to promote:*")
                    for r in results:
                        if r.get('verdict') == 'PROMOTE':
                            reasoning = (r.get('result') or {}).get('reasoning', '')
                            catalyst = (r.get('result') or {}).get('catalyst_assessment', '')
                            momentum = (r.get('result') or {}).get('momentum', '')
                            lines.append(f"  {r['symbol']} grade={r.get('grade')} conf={r.get('confidence')} — {reasoning}")
                            if catalyst or momentum:
                                lines.append(f"    catalyst={catalyst} momentum={momentum}")
                if drops > 0:
                    lines.append("\n*Dropped:*")
                    for r in results:
                        if r.get('verdict') == 'DROP':
                            reasoning = (r.get('result') or {}).get('reasoning', '')
                            lines.append(f"  {r['symbol']} grade={r.get('grade')} — {reasoning}")
                send_telegram("\n".join(lines), priority="P2", producer="incubator_llm_screener")
            except Exception as e:
                log.debug(f"Telegram notification failed: {e}")

        # Exit 0 is not evidence of work: a refused run and a run that screened nothing are both failures,
        # and the cron line's log mtime cannot tell either from a healthy run.
        first_error = next((r.get('error') for r in results if r.get('status') == 'error'), None)
        skipped = {}
        if refusal:
            skipped["governor_refused"] = len(candidates)
        elif errors:
            skipped["screen_error"] = errors
        if refusal:
            code, empty_reason = EXIT_REFUSED, "governor_refused"
            log.error(f"NO SCREENS: governor refused the run ({refusal})")
        elif args.run and candidates and screened == 0:
            code, empty_reason = EXIT_NO_SCREENS, "no_screens"
            log.error(f"NO SCREENS: 0 of {len(candidates)} symbols screened — first cause: {first_error or 'no result rows'}")
        else:
            code, empty_reason = 0, (None if screened else "no_candidates_or_dry_run")

        if not args.dry_run:
            write_receipt(
                ok=code == 0, exit_code=code, started_at=started,
                produced=screened, attempted=len(candidates), skipped=skipped, empty_reason=empty_reason,
                summary={"route": lane_label or route, "screened": screened, "errors": errors,
                         "promote": promotes, "hold": holds, "drop": drops, "providers": providers},
                error=None if code == 0 else (refusal or first_error or "no_screens"),
            )
        return code

    except BaseException as exc:
        if not args.dry_run:
            write_receipt(ok=False, exit_code=1, started_at=started, produced=0, attempted=0,
                          skipped={"run_failed": 1}, empty_reason="run_failed",
                          summary={"route": "unknown"}, error=type(exc).__name__)
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
