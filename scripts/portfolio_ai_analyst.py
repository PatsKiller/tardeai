"""portfolio_ai_analyst.py — Trade AI v12 Portfolio Intelligence
Deep wealth management analysis using Claude Sonnet 4.6.
Provides stock-level insights, ETF look-through, and specific recommendations.
Refreshes monthly. Daily runs use cached analysis.
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from cio_agent_contract import (
    build_portfolio_brief_json_schema,
    format_portfolio_brief_display,
    parse_portfolio_brief_result,
)

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
from local_llm_config import get_local_llm_model as _get_llm_model, get_local_llm_base_url as _get_llm_base_url
OLLAMA_MODEL = _get_llm_model()
_OLLAMA_BASE = _get_llm_base_url().rstrip("/")
_USE_OLLAMA = True  # default to local LLM (GPU-accelerated qwen3:14b)

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
    """Use centralized local_llm.generate() with toll gate and GPU.
    Uses higher num_predict (800) for narrative sections."""
    import re as _re
    if len(prompt) > 6000: prompt = prompt[:6000] + "\n[Be concise.]"
    try:
        from local_llm import generate, model_used, _gate, _try_ollama, OLLAMA_MODEL
        import json as _j
        # Use toll gate but with higher num_predict for narrative output
        if not _gate.acquire():
            # Fall through to cloud
            from local_llm import _try_openai, _try_anthropic, FALLBACK_OPENAI, FALLBACK_ANTHROPIC
            result = _try_openai(prompt) or _try_anthropic(prompt)
            return result or "Analysis unavailable — all LLMs failed"
        try:
            import urllib.request
            from local_llm import OLLAMA_URL
            payload = _j.dumps({
                "model": OLLAMA_MODEL, "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "think": False,
                "options": {"temperature": 0.3, "num_predict": 1200}
            }).encode()
            req = urllib.request.Request(
                OLLAMA_URL, data=payload,
                headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = _j.loads(resp.read())
                text = data.get("message", {}).get("content", "").strip()
                duration = round(data.get("total_duration", 0) / 1e9, 1)
                tokens = data.get("eval_count", 0)
                print(f"  [local-llm] Ollama OK — {duration}s, {tokens} tokens")
                if text:
                    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()
                return text or "Analysis unavailable — LLM returned empty"
        finally:
            _gate.release()
    except Exception as e:
        return f"LLM error: {e}"

def _ai(prompt: str, model: str = None, max_tokens: int = 1500) -> str:
    """Route to local LLM (daily/weekly) or Claude (monthly/manual)."""
    if _USE_OLLAMA:
        return _ollama(prompt, max_tokens=min(max_tokens, 600))
    return _claude(prompt, model=model, max_tokens=max_tokens)

def _claude(prompt: str, model: str = None, max_tokens: int = 1500) -> str:
    """Claude via the GOVERNED lane. Was a direct api.anthropic.com POST.

    Read ANTHROPIC_API_KEY and POSTed straight to api.anthropic.com/v1/messages
    with no reservation, no ledger row and no cap, while being reachable from
    portfolio_orchestrator (cron 07:15 weekdays). Audited 2026-08-30.

    The lane also fixes a second problem: this module's SONNET constant is
    claude-sonnet-4-20250514, which is RETIRED on the first-party API
    (Bedrock/Google Cloud only). The lane resolves to a current model instead,
    so the call can actually succeed.
    """
    want = str(model or "").lower()
    lane = "haiku" if "haiku" in want else "sonnet"
    try:
        from llm_lane import generate
    except Exception:                                            # noqa: BLE001
        from scripts.llm_lane import generate                    # type: ignore
    try:
        return (generate(prompt, lane=lane, max_tokens=max_tokens,
                         process_id="portfolio_ai_analyst",
                         task_summary=f"portfolio_ai_analyst:{lane}") or "").strip()
    except Exception as e:                                       # noqa: BLE001
        return f"Error: {str(e)[:100]}"

# ── Build portfolio context string ────────────────────────────────────────────


# ── Module-level root path (set by run_ai_analysis) ──────────────────────────
_CURRENT_ROOT = "."

# ── Market intelligence: news, social, agent views, LLM health ──────────────

def _fetch_market_intelligence(symbols: List[str]) -> str:
    """Fetch news, social, agent views, and LLM health for portfolio holdings.
    Returns compact text block for LLM context injection."""
    try:
        from session13_db import get_conn
        conn = get_conn()
        cur = conn.cursor()
    except Exception:
        return ""

    lines = []

    # 1. Recent news for held symbols (top 3 per symbol, last 3 days)
    try:
        cur.execute("""
            SELECT symbol, title, sentiment, published_at
            FROM news_articles
            WHERE symbol = ANY(%s) AND published_at > NOW() - INTERVAL '3 days'
            ORDER BY published_at DESC LIMIT 20
        """, [symbols])
        news = cur.fetchall()
        if news:
            lines.append("RECENT NEWS:")
            by_sym: Dict[str, list] = {}
            for r in news:
                by_sym.setdefault(r[0], []).append(r)
            for sym in sorted(by_sym.keys()):
                for n in by_sym[sym][:2]:
                    lines.append(f"  {sym}: {str(n[1])[:60]} ({n[2] or '?'})")
    except Exception:
        pass

    # 2. Social mentions for held symbols (last 3 days)
    try:
        cur.execute("""
            SELECT symbol, text, sentiment, post_date
            FROM (
                SELECT unnest(string_to_array(
                    (SELECT string_agg(DISTINCT s2.symbol, ',')
                     FROM unnest(%s::text[]) AS s2(symbol)
                     WHERE sp.text ILIKE '%%' || s2.symbol || '%%'
                    ), ',')) AS symbol,
                    text, sentiment, post_date
                FROM social_posts sp
                WHERE post_date > NOW() - INTERVAL '3 days'
                ORDER BY post_date DESC LIMIT 30
            ) sub WHERE symbol IS NOT NULL
            LIMIT 15
        """, [symbols])
        social = cur.fetchall()
        if social:
            lines.append("SOCIAL:")
            for s in social[:8]:
                lines.append(f"  {s[0]}: {str(s[1])[:50]} ({s[2] or '?'})")
    except Exception:
        # Fallback: simple text match
        try:
            cur.execute("""
                SELECT text, sentiment, post_date
                FROM social_posts
                WHERE post_date > NOW() - INTERVAL '3 days'
                ORDER BY post_date DESC LIMIT 10
            """)
            social = cur.fetchall()
            if social:
                lines.append("SOCIAL (general):")
                for s in social[:5]:
                    lines.append(f"  {str(s[0])[:60]} ({s[1] or '?'})")
        except Exception:
            pass

    # 3. Agent views (latest per symbol from Maria, Steph, Risk)
    try:
        cur.execute("""
            SELECT DISTINCT ON (symbol, agent)
                   symbol, agent, recommendation, confidence, summary
            FROM watchlist_agent_results
            WHERE symbol = ANY(%s) AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY symbol, agent, created_at DESC
            LIMIT 30
        """, [symbols])
        agents = cur.fetchall()
        if agents:
            lines.append("AGENT VIEWS:")
            for a in agents:
                lines.append(f"  {a[0]} {a[1]}:{a[2] or '?'}({a[3] or '?'}) {str(a[4] or '')[:40]}")
    except Exception:
        pass

    # 4. Holdings LLM health
    try:
        cur.execute("""
            SELECT symbol, holdings_llm_health, holdings_llm_action, holdings_llm_confidence
            FROM watchlist_items
            WHERE source = 'portfolio' AND symbol = ANY(%s) AND holdings_llm_health IS NOT NULL
        """, [symbols])
        health = cur.fetchall()
        if health:
            lines.append("AI HEALTH:")
            for h in health:
                action_str = f" →{h[2]}" if h[2] and h[2] != 'HOLD' else ''
                lines.append(f"  {h[0]}: {h[1]}{action_str} ({h[3]}%)")
    except Exception:
        pass

    # 5. Alex recent alerts
    try:
        cur.execute("""
            SELECT symbol, alert_type, message
            FROM alex_daily_alerts
            WHERE created_at > NOW() - INTERVAL '24 hours'
            AND symbol = ANY(%s)
            ORDER BY created_at DESC LIMIT 8
        """, [symbols])
        alerts = cur.fetchall()
        if alerts:
            lines.append("ALEX ALERTS:")
            for a in alerts:
                lines.append(f"  {a[0]}: [{a[1]}] {str(a[2])[:50]}")
    except Exception:
        pass

    try:
        conn.close()
    except Exception:
        pass

    # 6. Live web news (Brave Search API) for top holdings
    try:
        from web_news_fetcher import fetch_web_news_batch, format_news_for_prompt
        top_syms = symbols[:8]  # limit API calls
        web_news = fetch_web_news_batch(top_syms, max_per_symbol=2)
        if web_news:
            web_text = format_news_for_prompt(web_news, max_chars=400)
            if web_text:
                lines.append(web_text)
    except Exception:
        pass

    return "\n".join(lines) if lines else ""


def _mini_context(portfolio: Dict, analysis: Dict = None, rebalancing: Dict = None, personal: Dict = None) -> str:
    """Compact portfolio context for local LLM enriched with market intelligence.
    Includes news, social, agent views, and LLM health assessments."""
    if personal is None:
        personal = {}
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

    # Fetch market intelligence (news, social, agents, LLM health)
    held_symbols = [h.get('symbol', '') for h in holdings[:20] if h.get('symbol') and '-' not in h.get('symbol', '')]
    market_intel = _fetch_market_intelligence(held_symbols) if held_symbols else ""

    from datetime import date as _d
    base = f"""DATE: {_d.today().strftime('%B %d, %Y')}
PORTFOLIO: ${totals.get('total_value',0):,.0f} | Gain: ${totals.get('total_gain',0):+,.0f}
Dividends: ${divs.get('total_annual_income',0):,.0f}/yr
Owner: {personal.get('owner','John Whiting')}, age {personal.get('age','?')}, SSDI income ${personal.get('ssdi_annual',0) or 0:,.0f}/yr, conservative

ACCOUNTS:
{acct_lines}

TOP HOLDINGS:
{top_h}

FLAGS:
{flag_lines}

REBALANCING: ${(rebalancing or {}).get('total_to_rebalance',0):,.0f} needed
{portfolio.get('_weekly_trajectory', '')}"""

    if market_intel:
        base += f"\n\nMARKET INTELLIGENCE:\n{market_intel}"

    return base


def _get_context(portfolio, analysis=None, rebalancing=None, personal=None):
    """Return mini context for Ollama, full context for Claude."""
    if _USE_OLLAMA:
        return _mini_context(portfolio, analysis, rebalancing, personal)
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


# ── Personal Situation helpers ────────────────────────────────────────────────

def _load_personal_situation(server_url: str = "http://localhost:7777") -> Dict:
    """Load personal situation via server API (authoritative for computed fields).
    Falls back to direct file read if server unavailable.
    Returns flattened dict {field_name: current_value, ...} plus 'owner' key.
    """
    import urllib.request

    # Try API first — server has authoritative computed-fields logic
    try:
        with urllib.request.urlopen(f"{server_url}/api/personal/read", timeout=3) as r:
            data = json.loads(r.read().decode())
            if data.get("ok"):
                fields = data.get("data", {}).get("fields", {})
                result = {"owner": data["data"].get("owner", "John W. Whiting")}
                for key, field in fields.items():
                    result[key] = field.get("current")
                result["_source"] = "api"
                result["_raw_fields"] = fields
                return result
    except Exception as e:
        print(f"  [ai] personal situation API unavailable ({e}) - falling back to file")

    # Fallback: direct file read, no computed fields
    ps_path = Path("data/portfolios/state/personal_situation.json")
    if not ps_path.exists():
        print("  [ai] WARNING: personal_situation.json not found")
        return {}

    try:
        data = json.loads(ps_path.read_text())
        fields = data.get("fields", {})
        result = {"owner": data.get("owner", "John W. Whiting")}
        for key, field in fields.items():
            result[key] = field.get("current")
        result["_source"] = "file"
        result["_raw_fields"] = fields
        return result
    except Exception as e:
        print(f"  [ai] personal_situation.json parse error: {e}")
        return {}


def _staleness_warning(ps: Dict, days_threshold: int = 30) -> str:
    """Return warning text if personal_situation fields haven't been updated recently."""
    if not ps:
        return "NOTE: Personal financial context unavailable - analysis may use outdated assumptions.\n"

    raw_fields = ps.get("_raw_fields", {})
    if not raw_fields:
        return ""

    from datetime import date as _date, timedelta
    cutoff = (_date.today() - timedelta(days=days_threshold)).isoformat()

    stale = []
    for key, field in raw_fields.items():
        if not isinstance(field, dict):
            continue
        if not field.get("editable", True):
            continue
        last_updated = field.get("last_updated", "")
        if last_updated and last_updated < cutoff:
            stale.append(key)

    if not stale:
        return ""

    if len(stale) <= 5:
        stale_list = ", ".join(stale)
    else:
        stale_list = f"{', '.join(stale[:5])}, and {len(stale)-5} others"

    return (
        f"NOTE: Personal financial fields not updated in {days_threshold}+ days: {stale_list}. "
        f"Caveat time-sensitive recommendations (taxes, conversions, contributions) accordingly.\n"
    )


def _personal_historical_context(ps: dict, days_back: int = 90, threshold_fields: int = 5) -> str:
    """Build HISTORICAL CONTEXT block from personal_history if enough data exists.

    Returns empty string if fewer than threshold_fields have >=2 entries
    in the last days_back window, OR if Postgres is unavailable.
    """
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return ""
    except Exception:
        return ""

    rows = _execute(
        """SELECT field_name, value, effective_date, recorded_at, source
           FROM personal_history
           WHERE recorded_at >= (CURRENT_DATE - INTERVAL '%s days')
           ORDER BY field_name, recorded_at ASC""" % int(days_back),
        fetch="all"
    )
    if not rows or not isinstance(rows, list):
        return ""

    # Group by field
    by_field: Dict[str, list] = {}
    for row in rows:
        fn = row.get("field_name")
        if fn:
            by_field.setdefault(fn, []).append(row)

    # Filter to fields with >=2 entries
    qualifying = {fn: entries for fn, entries in by_field.items() if len(entries) >= 2}

    if len(qualifying) < threshold_fields:
        return ""

    # Build narrative lines
    raw_fields = ps.get("_raw_fields", {})
    lines = []

    for fn in sorted(qualifying.keys()):
        entries = qualifying[fn]
        first_val = entries[0].get("value")
        last_val = entries[-1].get("value")
        first_date = entries[0].get("effective_date")
        last_date = entries[-1].get("effective_date")
        n_changes = len(entries)
        data_type = raw_fields.get(fn, {}).get("data_type", "unknown")

        if data_type in ("currency", "percentage", "integer"):
            try:
                fv = float(first_val) if first_val is not None else 0
                lv = float(last_val) if last_val is not None else 0
                delta = lv - fv
                days_span = (last_date - first_date).days if first_date and last_date and first_date != last_date else 0

                if days_span >= 7:
                    monthly_rate = delta / (days_span / 30.44)
                    if data_type == "currency":
                        line = f"  - {fn}: ${fv:,.0f} -> ${lv:,.0f} (delta ${delta:+,.0f} over {days_span}d, ~${monthly_rate:+,.0f}/mo)"
                    elif data_type == "percentage":
                        line = f"  - {fn}: {fv:.2f}% -> {lv:.2f}% (delta {delta:+.2f}pp over {days_span}d)"
                    else:
                        line = f"  - {fn}: {fv:,.0f} -> {lv:,.0f} (delta {delta:+,.0f} over {days_span}d)"
                else:
                    if data_type == "currency":
                        line = f"  - {fn}: ${fv:,.0f} -> ${lv:,.0f} ({n_changes} changes within {days_span}d)"
                    elif data_type == "percentage":
                        line = f"  - {fn}: {fv:.2f}% -> {lv:.2f}% ({n_changes} changes within {days_span}d)"
                    else:
                        line = f"  - {fn}: {fv:,.0f} -> {lv:,.0f} ({n_changes} changes within {days_span}d)"
            except (TypeError, ValueError):
                line = f"  - {fn}: {first_val} -> {last_val} ({n_changes} entries)"
        elif data_type in ("enum", "boolean"):
            if first_val != last_val:
                line = f"  - {fn}: {first_val!r} -> {last_val!r} (changed {n_changes-1}x in window)"
            else:
                line = f"  - {fn}: {first_val!r} (stable, {n_changes} entries)"
        elif data_type == "date":
            line = f"  - {fn}: {first_val} -> {last_val} ({n_changes} entries)"
        else:
            line = f"  - {fn}: {first_val} -> {last_val} ({n_changes} entries)"

        lines.append(line)

    header = f"=== HISTORICAL CONTEXT (last {days_back} days, {len(qualifying)} fields with multi-entry history) ==="
    return header + "\n" + "\n".join(lines)


def _personal_context(ps: Dict, include_staleness: bool = True) -> str:
    """Format personal financial situation for prompt interpolation.
    Produces a multi-line block from personal_situation.json values."""
    if not ps:
        return "=== PERSONAL FINANCIAL SITUATION ===\n(personal_situation.json unavailable - check /api/personal/read)\n"

    owner = ps.get("owner", "John W. Whiting")
    age = ps.get("age", "?")
    dob = ps.get("dob", "?")

    ssdi = ps.get("ssdi_annual") or 0
    ssdi_mo = ps.get("ssdi_monthly_computed") or 0
    sch_c = ps.get("schedule_c_gross") or 0
    se_ded = ps.get("se_tax_deduction") or 0

    filing = ps.get("filing_status", "MFS")
    bracket = ps.get("current_tax_bracket_pct", 22)
    ceiling = ps.get("next_bracket_ceiling") or 0
    fed_ded = ps.get("federal_itemized") or 0
    ny_ded = ps.get("ny_itemized") or 0

    disability_active = ps.get("private_disability_active", True)
    disability_end = ps.get("disability_end_age", 68.5)
    fra = ps.get("fra_age", 67)
    rmd = ps.get("rmd_age", 73)

    mort_bal = ps.get("mortgage_balance") or 0
    mort_rate = ps.get("mortgage_rate_pct") or 0
    mort_int = ps.get("mortgage_annual_interest") or 0
    mort_mat = ps.get("mortgage_maturity", "?")
    prop_tax = ps.get("property_tax_annual") or 0

    roth_ytd = ps.get("roth_conversion_ytd_2026") or 0
    roth_remaining = ps.get("roth_conversion_remaining_2026") or 0
    roth_sweet = ps.get("roth_target_sweet_spot", 25000)
    roth_upper = ps.get("roth_target_upper", 50000)
    rollover_year = ps.get("plan_401k_rollover_year", 2027)

    gw_open = ps.get("golden_window_open", "?")
    gw_close = ps.get("golden_window_close", "?")

    # Compute derived figures
    income_base = ssdi + sch_c
    adjusted_income = income_base - se_ded
    taxable_ssdi_portion = ssdi * 0.85
    taxable_pre_conversion = taxable_ssdi_portion + sch_c - fed_ded - se_ded

    disability_status = "ACTIVE" if disability_active else "ENDED"

    blocks = []

    if include_staleness:
        warning = _staleness_warning(ps)
        if warning:
            blocks.append(warning.rstrip())

    blocks.append(f"""=== PERSONAL FINANCIAL SITUATION ===
Owner: {owner} | DOB: {dob} | Age: {age}

Income: SSDI ${ssdi:,.0f}/yr (${ssdi_mo:,.0f}/mo) + Schedule C ~${sch_c:,.0f}/yr gross
Private disability: {disability_status} - ends at age {disability_end}
No need to withdraw from investments until age {disability_end}

Filing: {filing} | Current bracket: {bracket}%
Federal itemized: ${fed_ded:,.0f} (mortgage interest ${mort_int:,.0f} + property tax ${prop_tax:,.0f})
NY itemized: ${ny_ded:,.0f}
SE tax deduction: ${se_ded:,.0f}/yr

Housing: Mortgage ${mort_bal:,.0f} @ {mort_rate}% fixed, matures {mort_mat}

=== RETIREMENT TIMELINE ===
FRA (SS transition): age {fra}
Disability insurance ends: age {disability_end}
Golden Window: {gw_open} to {gw_close} (ages {disability_end}-{rmd})
RMDs begin: age {rmd}
401k rollover: COMPLETE 2026-06-18 (Omnicom 401k → Fidelity Rollover IRA #***199, ~$568K, now ~100% cash)

=== ROTH CONVERSION STATUS ===
2026 YTD converted: ${roth_ytd:,.0f}
Remaining room in {bracket}% bracket: ${roth_remaining:,.0f}
Sweet spot target: ${roth_sweet:,.0f}/yr | Upper target: ${roth_upper:,.0f}/yr
{bracket}% bracket ceiling ({filing}): ${ceiling:,.0f}

=== TAX MATH (pre-conversion) ===
Income base: ${income_base:,.0f} (SSDI + Schedule C)
After SE deduction: ${adjusted_income:,.0f}
After 85% SSDI taxability + SE deduction + federal itemized: ${taxable_pre_conversion:,.0f} taxable
Remaining {bracket}% capacity: ${roth_remaining:,.0f}""")

    # Phase 8D-3c: Historical context if enough data accumulated
    historical = _personal_historical_context(ps)
    if historical:
        blocks.append(historical)

    return "\n\n".join(blocks)


def _portfolio_context(portfolio: Dict, analysis: Dict, rebalancing: Dict, personal: Dict = None) -> str:
    if personal is None:
        personal = _load_personal_situation()
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

    # Live account balances from portfolio data (never hardcoded)
    acct = portfolio.get("account_summaries", {}) or {}
    fidelity_mv = acct.get("fidelity_rollover_ira", {}).get("total_value") or 0
    rollover_mv = acct.get("schwab_rollover_ira", {}).get("total_value") or 0
    roth_mv = acct.get("schwab_roth", {}).get("total_value") or 0
    taxable_mv = acct.get("schwab_taxable", {}).get("total_value") or 0

    accounts_block = f"""=== ACCOUNTS (live values) ===
Fidelity Rollover IRA: ${fidelity_mv:,.0f} [Omnicom 401k rollover COMPLETE 2026-06-18; held at Fidelity, ~100% cash awaiting deployment; READ-ONLY in this system]
Schwab Rollover IRA: ${rollover_mv:,.0f}
Schwab Roth IRA: ${roth_mv:,.0f} [Roth conversion target account]
Schwab Taxable: ${taxable_mv:,.0f}
Total: ${(fidelity_mv + rollover_mv + roth_mv + taxable_mv):,.0f}
Combined traditional-IRA rollover pool (Fidelity + Schwab): ~${(fidelity_mv + rollover_mv):,.0f}"""

    return f"""=== PORTFOLIO OVERVIEW ===
Total Value: ${totals.get('total_value',0):,.0f}
Total All-Time Gain: ${totals.get('total_gain',0):,.0f} (+{totals.get('total_gain_pct',0):.1f}%)
Annual Dividend Income: ${divs.get('total_annual_income',0):,.2f}/yr (${divs.get('total_monthly_income',0):,.2f}/mo)
Day Change: ${totals.get('day_change',0):+,.0f}

{_personal_context(personal)}

{accounts_block}

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

def _exec_summary(portfolio: Dict, analysis: Dict, rebalancing: Dict, personal: Dict = None) -> tuple:
    """Daily executive summary enriched with market intelligence."""
    if personal is None:
        personal = {}
    totals = portfolio.get("portfolio_totals", {})
    flags  = analysis.get("critical_flags", [])
    high_flags = [f for f in flags if f.get("severity") in ("HIGH","CRITICAL")]

    owner = personal.get('owner', 'John W. Whiting')
    age = personal.get('age', '?')
    ssdi = personal.get('ssdi_annual', 0) or 0
    filing = personal.get('filing_status', 'MFS')
    roth_ytd = personal.get('roth_conversion_ytd_2026', 0) or 0
    roth_sweet = personal.get('roth_target_sweet_spot', 25000)

    # Fetch market intelligence for top holdings
    holdings = [h for h in portfolio.get("holdings", [])
                if (h.get("market_value") or 0) > 200 and not h.get("is_loan") and h.get("symbol") and '-' not in h.get("symbol", "")]
    holdings.sort(key=lambda h: -(h.get("market_value") or 0))
    held_symbols = [h['symbol'] for h in holdings[:15]]
    market_intel = _fetch_market_intelligence(held_symbols) if held_symbols else ""

    from datetime import date as _d
    _today = _d.today().strftime('%B %d, %Y')
    prompt = f"""Portfolio morning brief for {owner} (age {age}).
TODAY'S DATE: {_today}. All references must use this date. Do not reference old dates as current.
Total: ${totals.get('total_value',0):,.0f} | Gain: +${totals.get('total_gain',0):,.0f} (+{totals.get('total_gain_pct',0):.1f}%)
Annual dividends: ${analysis.get('dividends',{}).get('total_annual_income',0):,.0f}/yr
Rebalancing needed: ${rebalancing.get('total_to_rebalance',0):,.0f} net
Income: SSDI ${ssdi:,.0f}/yr only. {filing} filing. Prop tax + mortgage interest itemized.
Roth conversion: ${roth_ytd:,.0f} done in 2026. Sweet spot ${roth_sweet:,.0f}/yr.
High priority flags: {len(high_flags)}
Top flags: {chr(10).join(f['message'] for f in high_flags[:3])}
{chr(10) + market_intel if market_intel else ''}
Write a portfolio brief a wealth manager would send. Include:
1. Portfolio health summary (2-3 sentences)
2. Key news/catalyst impacts on holdings (reference specific tickers and news if available)
3. Most important action item considering Roth strategy, tax situation, and any agent alerts
4. Any holdings the AI flagged as WATCH or CONCERN with reasoning

{build_portfolio_brief_json_schema()}"""
    raw = _ai(prompt, max_tokens=500)
    parsed = parse_portfolio_brief_result(raw)
    if parsed:
        return format_portfolio_brief_display(parsed), parsed
    return raw, None


def _roth_conversion_analysis(portfolio: Dict, personal: Dict = None) -> str:
    """Sonnet: annual Roth conversion advice — how much to convert and what to buy."""
    if personal is None:
        personal = _load_personal_situation()
    rollover_mv = portfolio.get("account_summaries",{}).get("schwab_rollover_ira",{}).get("total_value", 0)
    fidelity_mv = portfolio.get("account_summaries",{}).get("fidelity_rollover_ira",{}).get("total_value", 0)
    roth_mv     = portfolio.get("account_summaries",{}).get("schwab_roth",{}).get("total_value", 0)
    total_pool = fidelity_mv + rollover_mv
    roth_ytd = personal.get("roth_conversion_ytd_2026", 0) or 0
    sch_c = personal.get("schedule_c_gross", 0) or 0

    return _ai(_AI_RULES + f"""JOHN'S ROTH CONVERSION — ANNUAL ADVISOR ANALYSIS

{_personal_context(personal)}

IRA POOL (live values):
  Schwab Rollover IRA: ${rollover_mv:,.0f} (current)
  Fidelity Rollover IRA: ${fidelity_mv:,.0f} (Omnicom 401k rollover COMPLETE 2026-06-18; now a
    self-directed Rollover IRA held at FIDELITY, ~100% cash. Full ETF/stock universe — the old
    401k plan-fund constraint NO LONGER APPLIES. READ-ONLY in this system / advisory only.)
  Current Roth: ${roth_mv:,.0f} (at Schwab)
  Combined traditional-IRA rollover pool (both custodians): ~${total_pool:,.0f}
  NOTE: the rollover pool is now SPLIT across two custodians (Fidelity IRA + Schwab IRA). Roth
  conversions are easiest within a single custodian; flag whether consolidating to one custodian
  would simplify the conversion sequence.

Schedule C business write-offs (deduct from ${sch_c:,.0f} gross to reduce net taxable):
  Home office, equipment, software, internet, phone, mileage, professional services

You are a CPA and fee-only financial advisor. Answer these ANNUAL ADVISORY questions:

1. HOW MUCH TO CONVERT IN 2026?
   John has done ${roth_ytd:,.0f}. Should he convert more before Dec 31?
   Give exact tax at different additional amounts: $0 more, $10K more, $16K more.
   What is the OPTIMAL additional amount given his situation?

2. WHAT TO BUY INSIDE THE ROTH AFTER CONVERSION?
   Roth should hold highest-return assets (tax-free growth).
   Rank these in order for Roth: SCHG (0.4%), JEPQ (9.5%), JEPI (7.8%), SCHD (3.58%), O/REIT (5.7%)
   Explain why for his specific situation.

3. ROLLOVER POOL DEPLOYMENT (ROLLOVER COMPLETE 2026-06-18)
   The Omnicom 401k has ALREADY rolled over into the Fidelity Rollover IRA (${fidelity_mv:,.0f},
   ~100% cash) — combined with the existing Schwab Rollover IRA (${rollover_mv:,.0f}) the traditional
   pool (~${total_pool:,.0f}) is available NOW, not in a future year. How much of this pool to convert
   in 2026 vs. defer to the Golden Window? What's the optimal multi-year sequence, and does the
   two-custodian split argue for consolidating before converting?

4. GOLDEN WINDOW
   Model the projected balances at disability end and optimal conversion strategy in that window.
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
    rollover_mv = portfolio.get("account_summaries",{}).get("schwab_rollover_ira",{}).get("total_value", 0)

    return _ai(_AI_RULES + f"""TASK: Bond allocation strategy for John's Rollover IRA (${rollover_mv:,.0f}).
Current bonds: BND only. Target: 25% of IRA in bonds.
Recommend specific bond ETF allocation (BND, AGG, VCIT, VGIT, SGOV) with dollar amounts.
Assess duration risk for a 10-15 year retirement horizon. Write in prose paragraphs.

{ctx}""",
    model=SONNET, max_tokens=1400)

# ── Section 5: IRA Rollover Strategic Options ────────────────────────────────

def _ira_opportunities(portfolio: Dict) -> str:
    ctx = _get_context(portfolio)
    rollover_mv = portfolio.get("account_summaries",{}).get("schwab_rollover_ira",{}).get("total_value", 0)

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

def _current_holdings_hash(state_dir: Path) -> str:
    """Read holdings_hash from _freshness.json (written by orchestrator)."""
    try:
        fp = Path(state_dir) / "_freshness.json"
        if fp.exists():
            return json.loads(fp.read_text()).get("holdings_hash", "")
    except Exception:
        pass
    return ""


def _should_refresh(state_dir: Path, key: str, max_days: int = 30) -> bool:
    f = Path(state_dir) / f"ai_{key}.json"
    if not f.exists(): return True
    try:
        d = json.loads(f.read_text())
        # Time-based: refresh if older than max_days
        age = (datetime.now() - datetime.fromisoformat(d.get("ts","2000-01-01"))).days
        if age >= max_days:
            return True
        # Holdings-change-based: refresh if portfolio composition changed
        cached_hash = d.get("holdings_hash", "")
        if cached_hash and cached_hash != _current_holdings_hash(state_dir):
            return True
        return False
    except: return True

def _load_cache(state_dir: Path, key: str) -> Optional[str]:
    f = Path(state_dir) / f"ai_{key}.json"
    try: return json.loads(f.read_text()).get("text","") if f.exists() else None
    except: return None

# Sentinels this module emits when a run produces no analysis. They are status
# messages, not analysis, and must never be cached over real content.
_FAILURE_PREFIXES = (
    "Analysis unavailable",     # _ollama: all LLMs failed / returned empty
    "LLM error:",               # _ollama: exception path
    "Analysis error:",          # run_ai_analysis: section raised
)


def _is_failure_text(text) -> bool:
    """True when `text` is a failure sentinel or empty rather than an analysis."""
    t = str(text or "").strip()
    return not t or t.startswith(_FAILURE_PREFIXES)


def _save_cache(state_dir: Path, key: str, text: str):
    """Persist an analysis. FAILS CLOSED: a failed run never destroys good content.

    This used to write whatever it was handed. When the LLM lane was down the
    caller passed "Analysis unavailable — all LLMs failed" and that string was
    written straight over the last good analysis — no version, no backup, no
    skip. Observed 2026-09-01: all seven ai_*.json caches overwritten between
    07:32 and 07:33, destroying analyses from 2026-08-11. Every subsequent run
    destroyed another copy, and the only reason the originals survived at all is
    that a second, diverging state tree was not written by this job.

    A cache that fails OPEN converts a transient outage into permanent data loss,
    and it does so silently, because the file keeps its normal shape and mtime.
    """
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    path = Path(state_dir) / f"ai_{key}.json"

    if _is_failure_text(text):
        prior = None
        try:
            prior = json.loads(path.read_text()) if path.exists() else None
        except Exception:
            prior = None
        if isinstance(prior, dict) and not _is_failure_text(prior.get("text")):
            # Keep the analysis; record the failure beside it so the outage is
            # visible in-band rather than inferred from a missing refresh.
            prior["last_failure_ts"] = datetime.now().isoformat()
            prior["last_failure_text"] = str(text or "")[:200]
            prior["stale_since_failure"] = True
            path.write_text(json.dumps(prior, indent=2))
            print(f"  [ai] {key}: run failed — prior analysis PRESERVED, not overwritten")
            return

    h_hash = _current_holdings_hash(state_dir)
    (Path(state_dir) / f"ai_{key}.json").write_text(
        json.dumps({"key":key,"text":text,"ts":datetime.now().isoformat(),
                    "holdings_hash":h_hash},indent=2))

# ── Main Entry Point ──────────────────────────────────────────────────────────

def run_ai_analysis(portfolio, analysis, rebalancing, state_dir, force_refresh=False, run_type="daily", root="."):
    results = {}
    state_dir = Path(state_dir)
    # Make root available to all section functions via module-level variable
    # so Fidelity constraint can be loaded without changing every function signature
    import portfolio_ai_analyst as _self_mod
    _self_mod._CURRENT_ROOT = str(root)
    global _USE_OLLAMA
    _USE_OLLAMA = run_type in ("daily", "weekly")  # local LLM for daily+weekly, Claude for monthly/manual
    print(f"  [ai] Running AI analysis (mode: {run_type}, engine: {'Local ' + OLLAMA_MODEL if _USE_OLLAMA else 'Claude Sonnet'})...")

    # ── Freshness check (Phase 0) ────────────────────────────────────────────
    _freshness_warning = ""
    try:
        _fp = state_dir / "_freshness.json"
        if _fp.exists():
            _fm = json.loads(_fp.read_text())
            _completed = datetime.fromisoformat(_fm.get("completed_at", "2000-01-01"))
            _age_hours = (datetime.now() - _completed).total_seconds() / 3600
            if _age_hours > 26:
                _freshness_warning = (
                    f"\n⚠️ DATA STALENESS WARNING: Portfolio data is {_age_hours:.0f} hours old "
                    f"(last pipeline: {_fm.get('completed_at', 'unknown')[:16]}). "
                    f"Analysis may not reflect current positions or prices.\n"
                )
                print(f"  [ai] ⚠️  Data is {_age_hours:.0f}h stale — injecting warning")
        else:
            _freshness_warning = (
                "\n⚠️ DATA STALENESS WARNING: No pipeline freshness manifest found. "
                "Unable to verify data recency. Analysis may be based on stale data.\n"
            )
            print("  [ai] ⚠️  No freshness manifest — injecting warning")
    except Exception:
        pass  # Don't block AI on freshness check failure

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

    # Inject freshness warning into portfolio for prompt context
    if _freshness_warning:
        portfolio = dict(portfolio) if not isinstance(portfolio.get("_weekly_trajectory"), str) else portfolio
        portfolio["_freshness_warning"] = _freshness_warning

    # Load personal situation once, reused across all section builders
    personal = _load_personal_situation()

    # Daily: executive summary (Haiku, cheap)
    print(f"  [ai] Executive summary ({'Ollama ' + OLLAMA_MODEL if _USE_OLLAMA else 'Haiku'})...")
    exec_text, exec_structured = _exec_summary(portfolio, analysis, rebalancing, personal)
    results["executive_summary"] = exec_text
    if exec_structured:
        results["executive_summary_structured"] = exec_structured
    if _freshness_warning:
        results["executive_summary"] = _freshness_warning + results["executive_summary"]
        results["_freshness_warning"] = _freshness_warning

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
                print(f"  [ai] {label} ({'Ollama ' + OLLAMA_MODEL if _USE_OLLAMA else 'Sonnet 4.6'})...")
                try:
                    if n_args == 3: text = fn(portfolio, analysis, rebalancing)
                    elif n_args == 2:
                        if key == "dividend_strategy": text = fn(portfolio, analysis)
                        else: text = fn(portfolio, rebalancing)
                    elif key == "roth_conversion": text = fn(portfolio, personal)
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
    results["model"] = OLLAMA_MODEL if _USE_OLLAMA else SONNET
    n = len([k for k in results if k not in ("generated_at","run_type","model")])
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
    # Load dividend data into analysis if not already present
    if not analysis.get("dividends"):
        div_path = sd / "dividend_calendar.json"
        if div_path.exists():
            div_data = json.load(open(div_path))
            analysis["dividends"] = {
                "total_annual_income": div_data.get("total_annual") or sum(
                    (p.get("annual_income") or 0) for p in div_data.get("payers", [])
                ),
                "qualified_annual": div_data.get("qualified_annual", 0),
                "payers": len(div_data.get("payers", [])),
            }
            print(f"  [ai] Dividend data loaded: ${analysis['dividends']['total_annual_income']:,.0f}/yr from {analysis['dividends']['payers']} payers")
    result = run_ai_analysis(port, analysis, risk, sd, force_refresh=True, run_type=args.run_type, root=str(root))
    out = sd / "ai_analysis_cache.json"
    json.dump(result, open(out,"w"), indent=2)
    print(f"[ai_analyst] Done — {len(result)} sections → {out}")
