"""
portfolio_weekly_report.py — Weekly portfolio intelligence report
Version: 1.0 | April 16, 2026

Runs Sunday 8PM via run_portfolio_weekly.sh
Uses OAuth LLM via llm_lane (Grok → ChatGPT → local) for all narrative sections
Outputs: HTML report + Telegram summary + JSON data file

Sections:
  1. Portfolio performance (all 4 accounts, period returns)
  2. Top movers (gainers/losers this week)
  3. Cash utilization analysis
  4. Technical health summary (RSI/SMA from enrichment cache)
  5. Trade journal this week (P&L, wins/losses)
  6. Upcoming week (earnings dates, economic events)
  7. Action recommendation

Retention: last 8 weekly HTMLs kept (cleanup on monthly run)
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
WEEKLY_DIR.mkdir(parents=True, exist_ok=True)


def _load_state(filename: str) -> dict:
    """Load a state file safely."""
    try:
        p = STATE_DIR / filename
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def _load_data() -> Dict:
    """Load all required data files."""
    data = {}
    # Holdings
    h_path = STATE_DIR / "holdings.json"
    if h_path.exists():
        data["holdings"] = json.loads(h_path.read_text())
    else:
        data["holdings"] = {}
    # Performance history
    ph_path = STATE_DIR / "performance_history.json"
    if ph_path.exists():
        data["perf"] = json.loads(ph_path.read_text())
    else:
        data["perf"] = {}
    # Technical enrichment cache
    te_path = STATE_DIR / "ticker_enrichment_cache.json"
    if te_path.exists():
        data["enrichment"] = json.loads(te_path.read_text())
    else:
        data["enrichment"] = {}
    # Snapshots for weekly comparison
    snap_dir = STATE_DIR / "snapshots"
    data["snapshots"] = {}
    if snap_dir.exists():
        for snap_file in sorted(snap_dir.glob("*.json"))[-14:]:
            try:
                data["snapshots"][snap_file.stem] = json.loads(snap_file.read_text())
            except Exception:
                pass
    return data


def _report_llm(prompt: str, *, task_summary: str, timeout: int = 120) -> str:
    """OAuth narrative via portfolio_report_llm (Grok → ChatGPT → local)."""
    from portfolio_report_llm import PROCESS_WEEKLY, generate_oauth_narrative
    return generate_oauth_narrative(
        prompt, process_id=PROCESS_WEEKLY, task_summary=task_summary, timeout=timeout,
    )


def _clean_md(text: str) -> str:
    """Strip markdown artifacts before sending to Telegram."""
    import re
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)   # **bold** → bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)        # *italic* → italic
    text = re.sub(r'^#{1,4}\s*', '', text, flags=re.MULTILINE)  # ## headings
    text = re.sub(r'`([^`]+)`', r'\1', text)           # `code` → code
    text = re.sub(r'\n{3,}', '\n\n', text)             # collapse triple+ newlines
    return text.strip()


def _get_env(key: str) -> str:
    val = os.getenv(key, "")
    if val:
        return val
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def _send_telegram(message: str) -> None:
    from telegram_alert import send_telegram
    ok = send_telegram(message, bypass_router=True)
    if ok:
        print("  [weekly-report] Telegram sent")
        try:
            import sys as _sys
            from pathlib import Path as _P
            root = str(_P(__file__).resolve().parent.parent)
            if root not in _sys.path:
                _sys.path.insert(0, root)
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="portfolio_weekly_report", subject_key="ops:portfolio_weekly",
                retention_class="operational", severity="info",
                sanitized_body=message[:500], short_summary=message[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    else:
        print("  [weekly-report] Telegram not sent")


def _build_performance_section(data: Dict) -> Dict:
    """Build performance data dict for the report."""
    perf = data.get("perf", {})
    periods = perf.get("periods", {})
    accounts = perf.get("accounts", {})
    holdings = data.get("holdings", {})
    totals = holdings.get("portfolio_totals", {})

    acct_summaries = holdings.get("account_summaries", {})
    ACCT_LABELS = {
        "fidelity_401k": "Fidelity 401k",
        "schwab_rollover_ira": "Rollover IRA",
        "schwab_roth": "Roth IRA",
        "schwab_taxable": "Taxable",
    }

    # Per-account 1W
    acct_1w = {}
    for key, label in ACCT_LABELS.items():
        acct_data = accounts.get(key, {})
        w = acct_data.get("periods", {}).get("1W", {})
        val = acct_data.get("current_value") or acct_summaries.get(key, {}).get("total_value", 0)
        acct_1w[label] = {
            "value": val,
            "change_pct": w.get("change_pct") if w else None,
            "change": w.get("change") if w else None,
        }

    # Cash analysis
    CASH_SYMS = {"CASH", "--", "SNSXX", "SWVXX", "SPRXX", "VMFXX", "FDRXX"}
    cash_total = sum(
        h.get("market_value", 0) or 0
        for h in holdings.get("holdings", [])
        if h.get("symbol") in CASH_SYMS
    )
    total_val = totals.get("total_value", 0) or 0
    cash_pct = (cash_total / total_val * 100) if total_val else 0

    # Top movers: enrichment cache perf_week_pct (primary), snapshot delta (fallback)
    enrichment = data.get("enrichment", {})
    all_holdings = holdings.get("holdings", [])
    top_movers = []
    seen = set()
    for h in all_holdings:
        sym = h.get("symbol", "")
        if not sym or sym in CASH_SYMS or sym in seen:
            continue
        seen.add(sym)
        mv = h.get("market_value", 0) or 0
        if mv < 1:
            continue
        e = enrichment.get(sym, {})
        pw = e.get("perf_week_pct")
        if pw is not None:
            top_movers.append({"symbol": sym, "change_pct": round(pw, 2), "value": mv})
    # Fallback: snapshot-based deltas for tickers not in enrichment
    snaps = data.get("snapshots", {})
    snap_dates = sorted(snaps.keys())
    if len(snap_dates) >= 2:
        prev_snap = snaps.get(snap_dates[-2], {})
        curr_snap = snaps.get(snap_dates[-1], {})
        prev_h = {h.get("symbol"): h.get("market_value", 0) for h in prev_snap.get("holdings", {}).values() if isinstance(h, dict)}
        curr_h = {h.get("symbol"): h.get("market_value", 0) for h in curr_snap.get("holdings", {}).values() if isinstance(h, dict)}
        for sym in set(prev_h) & set(curr_h):
            if sym in seen:
                continue
            prev_v = prev_h[sym] or 0
            curr_v = curr_h[sym] or 0
            if prev_v > 0:
                chg = (curr_v - prev_v) / prev_v * 100
                top_movers.append({"symbol": sym, "change_pct": round(chg, 2), "value": curr_v})
    top_movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)

    # SPY benchmark (from enrichment cache)
    spy_data = enrichment.get("SPY", {})
    spy_benchmark = {
        "perf_week_pct": spy_data.get("perf_week_pct"),
        "perf_month_pct": spy_data.get("perf_month_pct"),
        "perf_ytd_pct": spy_data.get("perf_ytd_pct"),
        "perf_year_pct": spy_data.get("perf_year_pct"),
    }

    return {
        "total_value": total_val,
        "periods": periods,
        "accounts": acct_1w,
        "cash_total": cash_total,
        "cash_pct": round(cash_pct, 1),
        "top_movers": top_movers[:10],
        "spy_benchmark": spy_benchmark,
    }


def _build_technical_section(data: Dict) -> Dict:
    """Build technical health summary from enrichment cache."""
    enrichment = data.get("enrichment", {})
    holdings = data.get("holdings", {}).get("holdings", [])
    CASH_SYMS = {"CASH", "--", "SNSXX", "SWVXX"}

    tech_data = []
    for h in holdings:
        sym = h.get("symbol", "")
        if not sym or sym in CASH_SYMS or ("-" in sym and len(sym) > 5):
            continue
        e = enrichment.get(sym, {})
        if not e.get("rsi"):
            continue
        tech_data.append({
            "symbol": sym,
            "rsi": e.get("rsi"),
            "rsi_status": e.get("rsi_status", "neutral"),
            "sma200_pct": e.get("sma200_pct"),
            "trend": e.get("trend", "unknown"),
            "perf_week_pct": e.get("perf_week_pct"),
            "market_value": h.get("market_value", 0),
        })

    overbought = [t for t in tech_data if t["rsi_status"] == "overbought"]
    oversold = [t for t in tech_data if t["rsi_status"] == "oversold"]
    above_200 = [t for t in tech_data if (t.get("sma200_pct") or 0) > 0]
    below_200 = [t for t in tech_data if (t.get("sma200_pct") or 0) < 0]

    return {
        "positions": tech_data,
        "overbought": overbought,
        "oversold": oversold,
        "above_200_count": len(above_200),
        "below_200_count": len(below_200),
        "total": len(tech_data),
    }


def _build_journal_section(data: Dict) -> Dict:
    """Build trade journal weekly summary."""
    journal = data.get("holdings", {}).get("trade_journal", [])
    today = datetime.now()
    week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    week_trades = [
        t for t in journal
        if t.get("date", "") >= week_ago
        and t.get("action", "").lower() in ["sell", "buy"]
    ]

    closed = [t for t in week_trades if t.get("action", "").lower() == "sell"]
    pnl = sum(t.get("realized_pnl", 0) or 0 for t in closed)
    wins = sum(1 for t in closed if (t.get("realized_pnl", 0) or 0) > 0)

    return {
        "week_trades": len(week_trades),
        "closed_trades": len(closed),
        "pnl": pnl,
        "wins": wins,
        "win_rate": round(wins / len(closed) * 100, 1) if closed else 0,
    }


def _load_previous_weeklies(n: int = 3) -> list:
    """Load last N weekly JSON files for iterative context."""
    weeklies = []
    for f in sorted(WEEKLY_DIR.glob("weekly_*.json"))[-n:]:
        try:
            d = json.loads(f.read_text())
            weeklies.append(d)
        except Exception:
            pass
    return weeklies


def _load_previous_weeklies(n: int = 3) -> list:
    """Load last N weekly JSON files for iterative context."""
    weeklies = []
    for f in sorted(WEEKLY_DIR.glob("weekly_*.json"))[-n:]:
        try:
            d = json.loads(f.read_text())
            weeklies.append(d)
        except Exception:
            pass
    return weeklies


def _build_analyst_intelligence(holdings_data: Dict, enrichment: Dict) -> Dict:
    """Build analyst intelligence: ratings, targets, rebalancing WHY, Brave commentary."""
    holdings = holdings_data.get("holdings", [])
    CASH_SYMS = {"CASH","--","SNSXX","SWVXX","SPRXX","VMFXX","FDRXX"}

    analyst_data = []
    for h in sorted(holdings, key=lambda x: x.get("market_value",0), reverse=True):
        sym = h.get("symbol","")
        if not sym or sym in CASH_SYMS or ("-" in sym and len(sym) > 5):
            continue
        e = enrichment.get(sym, {})
        if not isinstance(e, dict):
            continue

        # Finviz consensus: 1=Strong Buy → 5=Strong Sell
        rating   = e.get("analyst_rating")          # text label we just added
        score    = e.get("recom_score")              # numeric 1.0-5.0
        pe       = e.get("pe")
        fwd_pe   = e.get("forward_pe")
        eps_next = e.get("eps_next_q")
        eps_next_y = e.get("eps_next_y")
        sma200   = e.get("sma200_pct")
        rsi      = e.get("rsi")
        inst_own = e.get("inst_own_pct")
        inst_txn = e.get("inst_trans_pct")          # +ve = buying, -ve = selling
        short_f  = e.get("short_float_pct")
        target   = e.get("target_price")             # from view 121 if available

        mv       = h.get("market_value", 0) or 0
        port_pct = h.get("portfolio_pct", 0) or 0
        cost     = h.get("cost_basis")
        gain_pct = h.get("gain_loss_pct")

        analyst_data.append({
            "symbol":      sym,
            "account":     h.get("account_display", h.get("account","")),
            "market_value": mv,
            "portfolio_pct": port_pct,
            "cost_basis":  cost,
            "gain_loss_pct": gain_pct,
            "analyst_rating": rating or "—",
            "recom_score": score,
            "target_price": target,
            "pe":          pe,
            "forward_pe":  fwd_pe,
            "eps_next_q":  eps_next,
            "eps_next_y":  eps_next_y,
            "sma200_pct":  sma200,
            "rsi":         rsi,
            "inst_own_pct": inst_own,
            "inst_trans_pct": inst_txn,
            "short_float_pct": short_f,
            "source": "Finviz Elite (consensus)"
        })

    # Sort: highest concern first (sell ratings, overbought, high concentration)
    def _concern_score(a):
        s = 0
        if a.get("recom_score") and a["recom_score"] >= 3.5: s += 30
        if a.get("rsi") and a["rsi"] > 70: s += 20
        if a.get("portfolio_pct", 0) > 15: s += 20
        if a.get("inst_trans_pct") and a["inst_trans_pct"] < -2: s += 10
        return s

    analyst_data.sort(key=_concern_score, reverse=True)
    return {"positions": analyst_data, "source": "Finviz Elite consensus ratings"}


def _build_rebalance_rationale(risk_data: Dict, holdings_data: Dict,
                                enrichment: Dict) -> list:
    """Build rebalancing WHY with drift explanation and analyst context."""
    positions = risk_data.get("positions", {})
    if not isinstance(positions, dict):
        return []

    rationale = []
    for sym, pos in positions.items():
        if not isinstance(pos, dict) or not pos.get("action"):
            continue
        action    = pos.get("action","")
        amount    = pos.get("amount", 0)
        note      = pos.get("note","")
        account   = pos.get("account","")
        e         = enrichment.get(sym, {}) if isinstance(enrichment.get(sym), dict) else {}
        rating    = e.get("analyst_rating","—")
        score     = e.get("recom_score")
        sma200    = e.get("sma200_pct")
        rsi       = e.get("rsi")
        inst_txn  = e.get("inst_trans_pct")

        # Build WHY explanation
        reasons = []
        if note:
            reasons.append(f"Drift: {note}")
        if score and score >= 3.5:
            reasons.append(f"Analyst consensus: {rating} ({score:.1f}/5.0) — unfavorable")
        elif score and score <= 2.0:
            reasons.append(f"Analyst consensus: {rating} ({score:.1f}/5.0) — favorable")
        if rsi and rsi > 70 and action == "SELL":
            reasons.append(f"Technically overbought (RSI {rsi:.0f})")
        if rsi and rsi < 30 and action == "BUY":
            reasons.append(f"Technically oversold (RSI {rsi:.0f}) — potential entry")
        if sma200 and sma200 > 0 and action == "BUY":
            reasons.append(f"Above SMA200 (+{sma200:.1f}%) — uptrend confirmed")
        if sma200 and sma200 < -5 and action == "SELL":
            reasons.append(f"Below SMA200 ({sma200:.1f}%) — downtrend risk")
        if inst_txn and inst_txn < -2:
            reasons.append(f"Institutions reducing position ({inst_txn:+.1f}%)")
        elif inst_txn and inst_txn > 2:
            reasons.append(f"Institutions increasing position ({inst_txn:+.1f}%)")

        rationale.append({
            "symbol":   sym,
            "account":  account,
            "action":   action,
            "amount":   amount,
            "analyst_rating": rating,
            "recom_score": score,
            "reasons":  reasons,
            "source":   "Finviz Elite (consensus rating, technical, institutional flow)"
        })

    return sorted(rationale, key=lambda x: abs(x.get("amount",0)), reverse=True)


def _get_brave_analyst_commentary(symbols: list, brave_api_key: str) -> Dict:
    """F2: Finviz/Yahoo headlines for key holdings — not Brave search API.

    Consumer: weekly DOCX narrative. ``brave_api_key`` retained for call-site
    compatibility but is unused; search API is residual-web only. Empty → {}.
    """
    if not symbols:
        return {}

    commentary: Dict = {}
    for sym in symbols[:5]:
        snippets = []
        try:
            from finviz_news import fetch_finviz_news
            for a in fetch_finviz_news(str(sym).upper(), lookback_hours=168)[:3]:
                title = (a.get("headline") or a.get("title") or "")[:100]
                url_r = a.get("url") or ""
                if title:
                    snippets.append({
                        "title": title,
                        "snippet": str(a.get("original_source") or a.get("source") or "finviz")[:200],
                        "source": "finviz_news",
                        "url": url_r,
                    })
        except Exception:
            pass
        if not snippets:
            try:
                from yahoo_news import fetch_yahoo_news
                for a in fetch_yahoo_news(str(sym).upper(), lookback_hours=168)[:3]:
                    title = (a.get("headline") or a.get("title") or "")[:100]
                    if title:
                        snippets.append({
                            "title": title,
                            "snippet": str(a.get("source") or "yahoo")[:200],
                            "source": "yahoo_news",
                            "url": a.get("url") or "",
                        })
            except Exception:
                pass
        if snippets:
            commentary[sym] = snippets

    return commentary


def _generate_narrative(
    perf_data: Dict,
    tech_data: Dict,
    journal_data: Dict,
    *,
    holdings_data: Optional[Dict] = None,
    enrichment: Optional[Dict] = None,
    risk_data: Optional[Dict] = None,
    analyst_intel: Optional[Dict] = None,
    rebal_rationale: Optional[List] = None,
    brave_commentary: Optional[Dict] = None,
) -> Dict:
    """Generate AI narratives with full data context + previous weekly deltas."""
    from portfolio_report_llm import (
        build_grounding,
        build_weekly_action_prompt,
        sanitize_action_text,
    )

    narratives = {}
    holdings_data = holdings_data or {}
    enrichment = enrichment or {}
    risk_data = risk_data or {}
    analyst_intel = analyst_intel or {}
    rebal_rationale = rebal_rationale or []
    brave_commentary = brave_commentary or {}
    grounding = build_grounding(holdings_data, enrichment, risk_data, rebal_rationale)
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
        prev_context = "PREVIOUS WEEKS CONTEXT (do not repeat — use for DELTA analysis only):\n"
        for pw in prev[-3:]:
            prev_context += (
                f"  Week {pw.get('date','?')}: total=${pw.get('total_value',0):,.0f} "
                f"1W={pw.get('1w_change_pct',0):+.2f}% "
                f"YTD={pw.get('ytd_change_pct',0):+.2f}% "
                f"above200={pw.get('tech_above_200','?')} "
                f"action: {str(pw.get('narratives',{}).get('action',''))[:80]}\n"
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
        tech_detail += f"  {sym}: RSI={rsi:.0f} SMA200={sma_str} trend={trend} ${mv:,.0f}\n"

    ob  = [t["symbol"] for t in tech_data.get("overbought", [])]
    os_ = [t["symbol"] for t in tech_data.get("oversold", [])]

    # Load enrichment for earnings / analyst data (if not passed in)
    if not enrichment:
        try:
            ep = STATE_DIR / "ticker_enrichment_cache.json"
            if ep.exists():
                enrichment = json.loads(ep.read_text())
        except Exception:
            enrichment = {}

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
    stops_near = [
        f"{s['symbol']} {s['dist_pct']:+.1f}%"
        for s in grounding.stops_near[:6]
    ]

    rebal_total = grounding.rebal_total or risk_data.get("total_to_rebalance", 0)
    beta = risk_data.get("portfolio_beta", 0.38)

    # Account lines
    acct_lines = ""
    for name, d in perf_data.get("accounts", {}).items():
        chg = d.get("change_pct")
        chg_str = f"{chg:+.2f}%" if chg is not None else "n/a"
        acct_lines += f"  {name}: ${d.get('value',0):,.0f} 1W={chg_str}\n"

    top_gainers = [t for t in perf_data.get("top_movers",[]) if t.get("change_pct",0) > 0][:5]
    top_losers  = [t for t in perf_data.get("top_movers",[]) if t.get("change_pct",0) < 0][-5:]

    # ── PROMPT 1: Performance (with delta from previous weeks) ────────────────
    prompt1 = f"""You are a professional wealth manager analyzing John W. Whiting's portfolio.
{grounding.positions_table}

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

    narratives["performance"] = _report_llm(prompt1, task_summary="weekly performance summary")

    # ── PROMPT 2: Technical Analysis ─────────────────────────────────────────
    prompt2 = f"""Portfolio technical health for John W. Whiting:
{grounding.positions_table}
{tech_detail}
Overbought (RSI>70): {ob if ob else 'none'}
Oversold (RSI<30): {os_ if os_ else 'none'}
{p1w.get('change_pct',0)-list(p[-1] for p in [prev] if p)[-1].get('1w_change_pct',0) if prev else 0:.1f}% momentum shift vs last week
Earnings coming: {earnings_soon[:5] if earnings_soon else 'none this week'}
Analyst ratings bullish on: {analyst_upgrades[:5] if analyst_upgrades else 'none flagged'}
Ex-dividend soon: {ex_div[:5] if ex_div else 'none'}

Write 3 sentences on technical posture. Be specific about which positions are at risk (RSI>70 = overbought, consider trim) vs opportunity (RSI<30, SMA200 support). Name the actual tickers."""

    narratives["technical"] = _report_llm(prompt2, task_summary="weekly technical health")

    # ── PROMPT 3: Risk & Rebalancing ─────────────────────────────────────────
    prompt3 = f"""Portfolio risk assessment for John W. Whiting:
{grounding.positions_table}
Beta: {beta:.3f} (target <0.5, conservative)
Rebalancing: ${rebal_total:,.0f} across {len(risk_data.get('positions',{}) if isinstance(risk_data.get('positions'),dict) else [])} positions
Stops near trigger (<5%): {stops_near if stops_near else 'none'}
Cash: {cash_pct:.1f}% (${perf_data.get('cash_total',0):,.0f})
V concentration: {next((h.get('portfolio_pct',0) for h in [] if h.get('symbol')=='V'), 'check holdings')}%

Write 2 sentences on risk posture. Is beta appropriate? Any stops about to trigger? Is rebalancing urgent or can it wait?
Be specific. No generic statements."""

    narratives["risk"] = _report_llm(prompt3, task_summary="weekly risk posture")

    # ── PROMPT 4: Income & Dividends ─────────────────────────────────────────
    prompt4 = f"""Dividend income analysis for John W. Whiting (SSDI $45,600/yr, needs income growth):
{grounding.positions_table}
Annual dividend income: ${annual_div:,.0f}/yr (${annual_div/12:,.0f}/mo)
Target: $28,000-$34,000/yr (2.5-3.0% yield)
Gap: ${max(0, 28000-annual_div):,.0f}/yr short of minimum target
Ex-dividend alerts: {ex_div if ex_div else 'none this week'}
Top dividend payers: {[d.get('symbol','') for d in div_data.get('holdings',[])[:5] if isinstance(d,dict)]}

Write 2 sentences. Is the income trajectory improving? What's the single best action to close the yield gap this week?"""

    narratives["dividends"] = _report_llm(prompt4, task_summary="weekly dividend income")

    # ── PROMPT 5: Action Recommendation (grounded + validated) ─────────────
    last_action = prev[-1].get("narratives", {}).get("action", "") if prev else ""
    action_context = (
        f"- 1W: {p1w.get('change_pct',0):+.2f}% | YTD: {pytd.get('change_pct',0):+.2f}%\n"
        f"- Rebalancing needed: ${rebal_total:,.0f}\n"
        f"- Overbought: {ob} | Stops near trigger: {stops_near}\n"
        f"- Earnings soon: {earnings_soon[:3]}\n"
        f"- Annual dividends: ${annual_div:,.0f} (target $28,000+)\n"
        f"- Roth conversion 2026: $35,000 done, sweet spot $25K/yr"
    )
    prompt5 = build_weekly_action_prompt(
        grounding, last_action=last_action, context_lines=action_context,
    )
    raw_action = _report_llm(prompt5, task_summary="weekly action recommendation")
    narratives["action"] = sanitize_action_text(raw_action, grounding, monthly=False)

    # ── PROMPT 6: Analyst Intelligence & Rebalancing WHY ─────────────────────
    # Build analyst context string
    analyst_lines = ""
    for p in analyst_intel.get("positions", [])[:8]:
        score = p.get("recom_score")
        score_str = f"{score:.1f}" if score else "—"
        analyst_lines += (
            f"  {p['symbol']}: {p['analyst_rating']} ({score_str}/5.0) "
            f"RSI={p.get('rsi') or '—'} SMA200={p.get('sma200_pct',0):+.1f}% "
            f"InstFlow={p.get('inst_trans_pct',0):+.1f}% "
            f"Port={p.get('portfolio_pct',0):.1f}%\n"
        )

    rebal_lines = ""
    for r in rebal_rationale[:5]:
        reasons_str = " | ".join(r.get("reasons", [])[:3])
        rebal_lines += (
            f"  {r['action']} {r['symbol']} ${abs(r.get('amount',0)):,.0f} "
            f"({r['analyst_rating']}) — {reasons_str}\n"
        )

    brave_lines = ""
    for sym, items in brave_commentary.items():
        for item in items[:1]:
            brave_lines += f"  {sym} ({item['source']}): {item['snippet'][:150]}\n"

    prompt6 = f"""You are a professional wealth manager. Analyze analyst consensus and rebalancing rationale for John W. Whiting.
{grounding.positions_table}

SOURCE: Finviz Elite consensus ratings (institutional, not individual advisor)

ANALYST RATINGS BY POSITION (1=Strong Buy, 3=Hold, 5=Strong Sell):
{analyst_lines if analyst_lines else "Run pipeline with Finviz Elite to populate"}

REBALANCING ORDERS WITH RATIONALE:
{rebal_lines if rebal_lines else "No rebalancing orders computed"}

RECENT ANALYST COMMENTARY (from public sources):
{brave_lines if brave_lines else "Brave search not configured or no results"}

Write 3 sentences:
1. Which positions have the strongest analyst support and why the data supports holding/buying
2. Which positions analysts are cautious on and why the rebalancing is recommended (cite the drift/technical/rating reason)
3. One contrarian note — where Finviz consensus might be wrong based on John's personal thesis (AI WWIII defense, Roth conversion priority)
Be specific. Cite Finviz as source. Never fabricate analyst firm names."""

    narratives["analyst_intelligence"] = _report_llm(prompt6, task_summary="weekly analyst intelligence")

    return narratives


def _generate_html(date_str: str, perf_data: Dict, tech_data: Dict,
                   journal_data: Dict, narratives: Dict) -> str:
    """Generate the weekly HTML report."""
    p1w = perf_data.get("periods", {}).get("1W", {})
    pytd = perf_data.get("periods", {}).get("YTD", {})
    p1y = perf_data.get("periods", {}).get("1Y", {})
    total = perf_data.get("total_value", 0)
    w_chg = p1w.get("change_pct", 0) or 0
    w_color = "#00e676" if w_chg >= 0 else "#ff5252"

    acct_rows = ""
    for name, d in perf_data.get("accounts", {}).items():
        chg = d.get("change_pct")
        chg_str = f"{chg:+.2f}%" if chg is not None else "n/a"
        color = "#00e676" if (chg or 0) >= 0 else "#ff5252"
        acct_rows += f"""
        <tr>
          <td>{name}</td>
          <td>${d.get('value', 0):,.0f}</td>
          <td style="color:{color}">{chg_str}</td>
          <td style="color:{color}">${abs(d.get('change', 0) or 0):,.0f}</td>
        </tr>"""

    tech_rows = ""
    for t in sorted(tech_data.get("positions", []),
                    key=lambda x: x.get("market_value", 0), reverse=True)[:10]:
        rsi = t.get("rsi", 0) or 0
        rsi_color = "#ff5252" if rsi > 70 else "#ffd740" if rsi < 30 else "#aaa"
        sma = t.get("sma200_pct")
        sma_str = f"{sma:+.1f}%" if sma is not None else "n/a"
        sma_color = "#00e676" if (sma or 0) > 0 else "#ff5252"
        tech_rows += f"""
        <tr>
          <td><b>{t['symbol']}</b></td>
          <td style="color:{rsi_color}">{rsi:.0f}</td>
          <td style="color:{sma_color}">{sma_str}</td>
          <td>{t.get('trend', '?')}</td>
        </tr>"""

    movers_rows = ""
    for t in perf_data.get("top_movers", [])[:8]:
        color = "#00e676" if t["change_pct"] >= 0 else "#ff5252"
        movers_rows += f"""
        <tr>
          <td><b>{t['symbol']}</b></td>
          <td style="color:{color}">{t['change_pct']:+.2f}%</td>
          <td>${t.get('value', 0):,.0f}</td>
        </tr>"""

    # SPY benchmark pre-computed for f-string
    _spy = perf_data.get("spy_benchmark", {})
    _spy_w = f"{_spy['perf_week_pct']:+.2f}%" if _spy.get("perf_week_pct") is not None else "n/a"
    _spy_m = f"{_spy['perf_month_pct']:+.2f}%" if _spy.get("perf_month_pct") is not None else "n/a"
    _spy_ytd = f"{_spy['perf_ytd_pct']:+.2f}%" if _spy.get("perf_ytd_pct") is not None else "n/a"
    _spy_y = f"{_spy['perf_year_pct']:+.2f}%" if _spy.get("perf_year_pct") is not None else "n/a"
    _p1m = perf_data.get("periods", {}).get("1M", {})
    _p1m_chg = _p1m.get("change_pct", 0) or 0
    _p1m_color = "#00e676" if _p1m_chg >= 0 else "#ff5252"
    _ytd_chg = pytd.get("change_pct", 0) or 0
    _ytd_color = "#00e676" if _ytd_chg >= 0 else "#ff5252"
    _p1y_chg = p1y.get("change_pct", 0) or 0
    _p1y_color = "#00e676" if _p1y_chg >= 0 else "#ff5252"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Weekly Portfolio Report — {date_str}</title>
<style>
  :root {{
    --bg: #0d0d1a; --bg2: #141428; --bg3: #1a1a30;
    --border: rgba(255,255,255,.08); --text: #e8e8f0;
    --text2: #b0b0c8; --text3: #7070a0;
    --up: #00e676; --dn: #ff5252; --warn: #ffd740;
    --accent: #2979ff; --mono: 'JetBrains Mono',monospace;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; padding: 24px; max-width: 900px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; color: var(--text); }}
  h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: var(--text3); margin: 24px 0 12px; }}
  .meta {{ font-size: 12px; color: var(--text3); margin-bottom: 24px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; margin-bottom: 24px; }}
  .kpi {{ background: var(--bg2); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }}
  .kpi .label {{ font-size: 10px; text-transform: uppercase; letter-spacing: .7px; color: var(--text3); margin-bottom: 6px; }}
  .kpi .value {{ font-size: 20px; font-weight: 700; }}
  .kpi .sub {{ font-size: 11px; color: var(--text3); margin-top: 4px; }}
  .narrative {{ background: var(--bg2); border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-bottom: 16px; font-size: 13px; line-height: 1.7; color: var(--text2); }}
  .action-box {{ background: rgba(41,121,255,.1); border: 1px solid rgba(41,121,255,.3); border-radius: 10px; padding: 16px; margin-bottom: 24px; font-size: 13px; line-height: 1.6; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ text-align: left; padding: 8px 10px; color: var(--text3); font-weight: 400; border-bottom: 1px solid var(--border); font-size: 10px; text-transform: uppercase; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,.04); }}
  .section {{ background: var(--bg2); border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-bottom: 16px; }}
  .up {{ color: var(--up); }} .dn {{ color: var(--dn); }}
  .footer {{ margin-top: 32px; font-size: 10px; color: var(--text3); text-align: center; }}
  @media (max-width: 600px) {{ .kpi-grid {{ grid-template-columns: repeat(2,1fr); }} }}
</style>
</head>
<body>
<h1>📊 Weekly Portfolio Report</h1>
<div class="meta">Week ending {date_str} · Generated by Local LLM · Trade AI v12</div>

<div class="kpi-grid">
  <div class="kpi">
    <div class="label">Total Value</div>
    <div class="value">${total:,.0f}</div>
    <div class="sub">Portfolio total</div>
  </div>
  <div class="kpi">
    <div class="label">1 Week</div>
    <div class="value" style="color:{w_color}">{w_chg:+.2f}%</div>
    <div class="sub">${abs(p1w.get('change',0) or 0):,.0f}</div>
  </div>
  <div class="kpi">
    <div class="label">YTD</div>
    <div class="value" style="color:{'#00e676' if (pytd.get('change_pct',0) or 0)>=0 else '#ff5252'}">{pytd.get('change_pct',0) or 0:+.2f}%</div>
    <div class="sub">${abs(pytd.get('change',0) or 0):,.0f}</div>
  </div>
  <div class="kpi">
    <div class="label">Cash</div>
    <div class="value">${perf_data.get('cash_total',0):,.0f}</div>
    <div class="sub">{perf_data.get('cash_pct',0):.1f}% of portfolio</div>
  </div>
</div>

<h2>Performance Summary</h2>
<div class="narrative">{narratives.get('performance', '—')}</div>

<div class="section">
  <table>
    <tr><th>Account</th><th>Value</th><th>1W Change</th><th>$ Change</th></tr>
    {acct_rows}
  </table>
</div>

<h2>vs SPY Benchmark</h2>
<div class="section">
  <table>
    <tr><th></th><th>1 Week</th><th>1 Month</th><th>YTD</th><th>1 Year</th></tr>
    <tr>
      <td><b>Your Portfolio</b></td>
      <td style="color:{w_color}">{w_chg:+.2f}%</td>
      <td style="color:{_p1m_color}">{_p1m_chg:+.2f}%</td>
      <td style="color:{_ytd_color}">{_ytd_chg:+.2f}%</td>
      <td style="color:{_p1y_color}">{_p1y_chg:+.2f}%</td>
    </tr>
    <tr style="color:var(--text3)">
      <td><b>SPY (S&amp;P 500)</b></td>
      <td>{_spy_w}</td>
      <td>{_spy_m}</td>
      <td>{_spy_ytd}</td>
      <td>{_spy_y}</td>
    </tr>
  </table>
</div>

<h2>Top Movers This Week</h2>
<div class="section">
  <table>
    <tr><th>Symbol</th><th>Change</th><th>Value</th></tr>
    {movers_rows if movers_rows else '<tr><td colspan="3" style="color:var(--text3)">No mover data available</td></tr>'}
  </table>
</div>

<h2>Technical Health</h2>
<div class="narrative">{narratives.get('technical', '—')}</div>
<div class="section">
  <table>
    <tr><th>Symbol</th><th>RSI</th><th>vs SMA200</th><th>Trend</th></tr>
    {tech_rows if tech_rows else '<tr><td colspan="4" style="color:var(--text3)">Run portfolio pipeline to populate technical data</td></tr>'}
  </table>
</div>

<h2>Cash Utilization</h2>
<div class="narrative">{narratives.get('cash', '—')}</div>

<h2>Trade Journal This Week</h2>
<div class="section">
  <table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Transactions</td><td>{journal_data.get('week_trades', 0)}</td></tr>
    <tr><td>Closed Trades</td><td>{journal_data.get('closed_trades', 0)}</td></tr>
    <tr><td>Net P&amp;L</td><td class="{'up' if journal_data.get('pnl',0)>=0 else 'dn'}">${journal_data.get('pnl',0):+,.2f}</td></tr>
    <tr><td>Win Rate</td><td>{journal_data.get('win_rate',0):.1f}%</td></tr>
  </table>
</div>

<h2>Action for Next Week</h2>
<div class="action-box">🎯 {narratives.get('action', '—')}</div>

<div class="footer">
  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · OAuth LLM (Grok/ChatGPT) · grounded action validation
  <br><a href="/reports/reports_hub.html" style="color:var(--accent)">← Back to Reports Hub</a>
</div>
</body>
</html>"""


def run_weekly_report(project_root: str = ".") -> Optional[Path]:
    """Main entry point. Generate weekly report and send Telegram summary."""
    global PROJECT_ROOT, STATE_DIR, WEEKLY_DIR
    PROJECT_ROOT = Path(project_root)
    STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
    WEEKLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "weekly"
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)


    print("[weekly-report] Starting weekly portfolio report...")
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Load data
    data = _load_data()

    # Build data sections
    perf_data = _build_performance_section(data)
    tech_data = _build_technical_section(data)
    journal_data = _build_journal_section(data)

    # Build analyst intelligence
    holdings_raw    = _load_state("holdings.json")
    risk_raw        = _load_state("risk_management.json")
    analyst_intel   = _build_analyst_intelligence(holdings_raw, data.get("enrichment", {}))
    rebal_rationale = _build_rebalance_rationale(risk_raw, holdings_raw, data.get("enrichment", {}))
    import os as _os
    brave_key = _os.getenv("BRAVE_API_KEY", "")
    top_syms  = [p["symbol"] for p in analyst_intel.get("positions", [])[:5]]
    brave_commentary = _get_brave_analyst_commentary(top_syms, brave_key)
    if brave_commentary:
        print(f"[weekly-report] Finviz/Yahoo: {len(brave_commentary)} symbols with commentary")

    print("[weekly-report] Generating OAuth narratives (6 sections)...")
    narratives = _generate_narrative(
        perf_data, tech_data, journal_data,
        holdings_data=holdings_raw,
        enrichment=data.get("enrichment", {}),
        risk_data=risk_raw,
        analyst_intel=analyst_intel,
        rebal_rationale=rebal_rationale,
        brave_commentary=brave_commentary,
    )

    # Generate HTML
    html = _generate_html(date_str, perf_data, tech_data, journal_data, narratives)

    # Save HTML
    html_path = WEEKLY_DIR / f"weekly_{date_str}.html"
    html_path.write_text(html)
    print(f"[weekly-report] HTML saved: {html_path}")

    # Save JSON data for monthly synthesis
    json_path = WEEKLY_DIR / f"weekly_{date_str}.json"
    p1w = perf_data.get("periods", {}).get("1W", {})
    pytd = perf_data.get("periods", {}).get("YTD", {})
    p1m_data  = perf_data.get("periods", {}).get("1M", {})
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
        "docx_path": "",
        "analyst_positions": analyst_intel.get("positions", [])[:10] if 'analyst_intel' in dir() else [],
        "rebal_rationale": rebal_rationale[:8] if 'rebal_rationale' in dir() else [],
        "brave_commentary": brave_commentary if 'brave_commentary' in dir() else {},
    }
    json_path.write_text(json.dumps(json_data, indent=2, default=str))

    # Generate DOCX brief — full sections (retirement, rebalancing, risk, tax)
    docx_path = None
    try:
        import sys as _sys, json as _json
        _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from portfolio_report import generate_portfolio_brief
        _sd = PROJECT_ROOT / "data" / "portfolios" / "state"
        def _load(f):
            p = _sd / f
            return _json.loads(p.read_text()) if p.exists() else {}
        holdings_data  = data.get("holdings", {})
        ai_analysis    = _load("ai_analysis_cache.json")
        tax_data       = _load("tax_projection.json")
        rebalance_data = _load("risk_management.json")
        risk_data      = _load("risk_management.json")
        docx_path = WEEKLY_DIR / f"weekly_{date_str}.docx"
        generate_portfolio_brief(
            holdings_data, ai_analysis, tax_data,
            rebalance_data, risk_data, docx_path,
            retirement=_load("retirement_roadmap.json"),
            perf_history=_load("performance_history.json"),
            stress=_load("stress_test.json"),
            technical=_load("technical_snapshot.json"),
            tax_projection=_load("tax_projection.json"),
            ai_analysis=ai_analysis,
        )
        print(f"[weekly-report] DOCX saved: {docx_path}")
        # Copy both HTML and DOCX to reports/weekly/ so server can serve them
        try:
            import shutil as _sh
            _sv = PROJECT_ROOT / "reports" / "weekly"
            _sv.mkdir(parents=True, exist_ok=True)
            _sh.copy2(html_path, _sv / html_path.name)
            _sh.copy2(docx_path, _sv / docx_path.name)
            print(f"[weekly-report] Copied to reports/weekly/ for serving")
        except Exception as _e:
            print(f"[weekly-report] Copy warning: {_e}")
    except Exception as e:
        print(f"[weekly-report] DOCX skipped: {e}")

    # Update CC dashboard (copy portfolio_live.html to reports/)
    try:
        import shutil as _sh
        live_src = PROJECT_ROOT / "data" / "portfolios" / "reports" / "portfolio_live.html"
        live_dst = PROJECT_ROOT / "reports" / "portfolio_live.html"
        if live_src.exists():
            _sh.copy2(live_src, live_dst)
            print(f"[weekly-report] CC dashboard updated")
    except Exception as e:
        print(f"[weekly-report] CC update skipped: {e}")

    # Cleanup old weekly reports (keep last 8)
    old_reports = sorted(WEEKLY_DIR.glob("weekly_*.html"))
    for old in old_reports[:-8]:
        old.unlink()
        old_json = old.with_suffix(".json")
        if old_json.exists():
            old_json.unlink()
        print(f"[weekly-report] Cleaned up {old.name}")

    # Send Telegram summary (re-validate action — never ship unheld tickers / bad prices)
    from portfolio_report_llm import build_grounding, sanitize_action_text
    _tg_grounding = build_grounding(
        holdings_raw, data.get("enrichment", {}), risk_raw, rebal_rationale,
    )
    safe_action = sanitize_action_text(
        narratives.get("action", ""), _tg_grounding, monthly=False,
    )
    if safe_action != narratives.get("action"):
        narratives["action"] = safe_action
        html_path.write_text(_generate_html(date_str, perf_data, tech_data, journal_data, narratives))
        try:
            json_data["narratives"]["action"] = safe_action
            json_path.write_text(json.dumps(json_data, indent=2))
        except Exception:
            pass
    w_chg = p1w.get("change_pct", 0) or 0
    ytd_chg = pytd.get("change_pct", 0) or 0
    tg_msg = (
        f"📊 <b>Weekly Report — {date_str}</b>\n\n"
        f"<b>${perf_data.get('total_value',0):,.0f}</b> | "
        f"1W: <b>{w_chg:+.2f}%</b> | YTD: {ytd_chg:+.2f}%\n\n"
        f"{_clean_md(narratives.get('performance',''))[:300]}\n\n"
        f"🎯 {_clean_md(safe_action)[:200]}\n\n"
        f"<a href='https://ms01-openclaw.tail163d14.ts.net/reports/weekly/weekly_{date_str}.html'>📄 Full Report</a>"
    )
    _send_telegram(tg_msg)
    if docx_path and Path(docx_path).exists():
        try:
            from telegram_alert import send_telegram_document
            ok = bool(send_telegram_document(
                str(docx_path),
                caption=f"Weekly portfolio DOCX — {date_str}",
                bypass_router=True,
            ))
            print("  [weekly-report] Telegram DOCX sent" if ok else "  [weekly-report] Telegram DOCX not sent")
        except Exception as e:
            print(f"  [weekly-report] Telegram DOCX error: {type(e).__name__}: {str(e)[:120]}")
    print(f"[weekly-report] Done. Report: {html_path}")
    return html_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    run_weekly_report(args.project_root)
