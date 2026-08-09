"""stop_decision_brief.py — Automated Stop Alert Decision Brief Generator
Transforms raw stop alerts into actionable portfolio decision briefs
by synthesizing holdings, news, technicals, sector context, and sentiment.

Called by: portfolio_alerts.py when a stop alert triggers
Output: Structured decision brief sent via Telegram + saved to state
"""
import json, os, time, requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from local_llm_config import get_local_llm_model, get_local_llm_base_url
OLLAMA_URL = get_local_llm_base_url().rstrip("/") + "/api/chat"
OLLAMA_MODEL = get_local_llm_model()


def _env(key, default=""):
    val = os.getenv(key, "").strip()
    if val:
        return val
    try:
        for line in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except:
        pass
    return default


def _ollama(prompt, max_tokens=800):
    import re
    try:
        from local_llm import generate
        text = generate(prompt, timeout=90,
                        caller="stop_decision_brief", process_type="STANDARD") or ""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    except Exception as e:
        return f"LLM unavailable: {e}"


def _load_state(state_dir, filename):
    p = Path(state_dir) / filename
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except:
        return {}


def generate_stop_brief(symbol: str, alert_data: Dict, state_dir: str, root: str = ".") -> Dict:
    """Generate a complete stop decision brief for a triggered alert.

    Args:
        symbol: Ticker symbol (e.g. 'LMT')
        alert_data: Dict with price, stop_price, dist_pct, etc.
        state_dir: Path to portfolios/state/
        root: Project root

    Returns:
        Dict with brief text, recommendation, confidence, and metadata
    """
    sd = Path(state_dir)

    # ── Load all data sources ────────────────────────────────────
    holdings = _load_state(sd, "holdings.json")
    enrichment = _load_state(sd, "ticker_enrichment_cache.json")
    stops = _load_state(sd, "stops.json")
    news = _load_state(sd, "portfolio_news.json")
    risk = _load_state(sd, "risk_management.json")
    technical = _load_state(sd, "technical_snapshot.json")
    signals_raw = _load_state(sd, "action_signals.json")
    earnings = _load_state(sd, "earnings_dates.json")

    # ── Holding data ─────────────────────────────────────────────
    sym_holdings = [h for h in holdings.get("holdings", []) if h.get("symbol") == symbol]
    total_mv = sum(h.get("market_value", 0) or 0 for h in sym_holdings)
    total_shares = sum(h.get("shares", 0) or 0 for h in sym_holdings)
    total_gl = sum(h.get("gain_loss", 0) or 0 for h in sym_holdings)
    total_cost = sum(h.get("cost_basis", 0) or 0 for h in sym_holdings)
    accounts = list(set(h.get("account", "") for h in sym_holdings))
    portfolio_total = holdings.get("portfolio_totals", {}).get("total_value", 1)
    weight = (total_mv / portfolio_total * 100) if portfolio_total > 0 else 0
    gl_pct = (total_gl / total_cost * 100) if total_cost > 0 else 0

    price = alert_data.get("price", alert_data.get("current_price", 0))
    stop_price = alert_data.get("stop_price", alert_data.get("stop", stops.get(symbol, {}).get("stop", 0)))
    # Fallback: if price is 0, try to get from enrichment cache or holdings
    _e = enrichment.get(symbol, {})
    if not price and _e:
        price = _e.get("price", _e.get("close", 0))
    if not price and sym_holdings:
        shares = sum(h.get("shares", 0) or 0 for h in sym_holdings)
        if shares > 0:
            price = total_mv / shares
    if not stop_price:
        stop_price = stops.get(symbol, {}).get("stop", stops.get(symbol, {}).get("stop_price", 0))
    dist_pct = alert_data.get("dist_pct", ((price - stop_price) / price * 100) if price > 0 else 0)

    # ── Enrichment / technicals ──────────────────────────────────
    e = enrichment.get(symbol, {})
    rsi = e.get("rsi")
    sma20_pct = e.get("sma20_pct")
    sma50_pct = e.get("sma50_pct")
    sma200_pct = e.get("sma200_pct")
    beta = e.get("beta")
    perf_week = e.get("perf_week_pct")
    perf_month = e.get("perf_month_pct")
    perf_ytd = e.get("perf_ytd_pct")
    atr = e.get("atr")
    rvol = e.get("rvol")
    short_float = e.get("short_float_pct")
    insider_trans = e.get("insider_trans_pct")
    inst_trans = e.get("inst_trans_pct")
    sector = e.get("sector", "Unknown")
    industry = e.get("industry", "Unknown")

    tech = technical.get("positions", {}).get(symbol, {})
    tech_score = tech.get("tech_score")
    cross = tech.get("cross")
    macd = tech.get("macd_signal")

    # ── News / catalysts ─────────────────────────────────────────
    sym_catalysts = [c for c in news.get("catalysts", []) if c.get("portfolio_symbol") == symbol]
    sym_catalysts.sort(key=lambda x: -x.get("llm_score", 0))
    top_catalysts = sym_catalysts[:5]
    has_negative = any(c.get("llm_urgency") in ("immediate", "watch") and c.get("llm_score", 0) >= 60 for c in top_catalysts)
    has_positive = any(c.get("llm_category") in ("earnings", "company") and c.get("llm_score", 0) >= 70 for c in top_catalysts)

    # ── Sector peers ─────────────────────────────────────────────
    # Find peers in same sector
    peers = []
    for sym2, e2 in enrichment.items():
        if e2.get("sector") == sector and sym2 != symbol and e2.get("perf_week_pct") is not None:
            peers.append({
                "symbol": sym2,
                "perf_week": e2.get("perf_week_pct", 0),
                "perf_month": e2.get("perf_month_pct", 0),
                "rsi": e2.get("rsi", 50),
            })
    peers.sort(key=lambda x: x["perf_week"])
    peer_avg_week = sum(p["perf_week"] for p in peers) / len(peers) if peers else 0
    sector_weak = peer_avg_week < -2

    # ── Signals ──────────────────────────────────────────────────
    sigs = signals_raw if isinstance(signals_raw, list) else signals_raw.get("signals", [])
    sym_signals = [s for s in sigs if isinstance(s, dict) and s.get("symbol") == symbol]
    thesis_groups = []
    for s in sym_signals:
        thesis_groups.extend(s.get("thesis_groups", []))

    # ── Earnings proximity ───────────────────────────────────────
    earnings_date = None
    ed = earnings.get("dates", earnings)
    if isinstance(ed, dict):
        earnings_date = ed.get(symbol)

    # ── Build decision context for LLM ───────────────────────────
    catalyst_text = "\n".join(
        f"  - [{c.get('llm_score',0)}] {c.get('llm_category','?')}/{c.get('llm_urgency','?')}: {c.get('title','')[:70]}"
        for c in top_catalysts
    ) if top_catalysts else "  None found (7 API sources searched)"

    peer_text = "\n".join(
        f"  {p['symbol']}: 1W={p['perf_week']:+.1f}% 1M={p['perf_month']:+.1f}% RSI={p['rsi']:.0f}"
        for p in peers[:6]
    ) if peers else "  No sector peers available"

    decision_prompt = f"""/no_think
You are a portfolio risk manager making a stop-loss decision.

ALERT: {symbol} is {dist_pct:.1f}% from stop (${price:.2f} vs stop ${stop_price:.2f})

POSITION:
  Shares: {total_shares:.2f} | Value: ${total_mv:,.0f} | Weight: {weight:.2f}%
  Gain/Loss: ${total_gl:+,.0f} ({gl_pct:+.1f}%) | Account: {', '.join(accounts)}
  Thesis: {', '.join(thesis_groups) if thesis_groups else 'No thesis tag'}

TECHNICALS:
  RSI: {rsi or 'N/A'} | SMA20: {f'{sma20_pct:+.1f}%' if sma20_pct else 'N/A'} | SMA50: {f'{sma50_pct:+.1f}%' if sma50_pct else 'N/A'} | SMA200: {f'{sma200_pct:+.1f}%' if sma200_pct else 'N/A'}
  Beta: {beta or 'N/A'} | ATR: ${atr or 0:.2f} | RVOL: {rvol or 'N/A'}x
  1W: {f'{perf_week:+.1f}%' if perf_week else 'N/A'} | 1M: {f'{perf_month:+.1f}%' if perf_month else 'N/A'} | YTD: {f'{perf_ytd:+.1f}%' if perf_ytd else 'N/A'}
  Short float: {short_float or 'N/A'}% | Insider: {insider_trans or 'N/A'}% | Inst: {inst_trans or 'N/A'}%

NEWS/CATALYSTS:
{catalyst_text}

SECTOR PEERS ({sector} / {industry}):
{peer_text}
  Sector avg 1W: {peer_avg_week:+.1f}%

EARNINGS: {earnings_date or 'Not scheduled'}

DECISION RULES:
- No catalyst + sector rotation + oversold RSI → HOLD/DELAY
- Validated negative catalyst + analyst deterioration → HONOR STOP
- Mixed signals + small position → HOLD/WATCH
- Thesis break confirmed → HONOR STOP immediately

Respond with EXACTLY this JSON:
{{
  "recommendation": "<HOLD|HOLD_WATCH|PARTIAL_TRIM|HONOR_STOP|DELAY_STOP|OVERRIDE_TEMPORARY>",
  "confidence": <50-95>,
  "reasoning": "<2-3 sentences explaining decision>",
  "what_changed": ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
  "news_tone": "<positive|negative|mixed|absent|inconclusive>",
  "sector_context": "<rotation|specific|macro|stable>",
  "technical_read": "<oversold|deteriorating|neutral|strong>",
  "monitor_next": ["<what to watch 1>", "<what to watch 2>"],
  "new_stop_suggestion": <number or null>,
  "urgency": "<low|medium|high|critical>"
}}"""

    # Call LLM
    llm_response = _ollama(decision_prompt, max_tokens=600)

    # Parse response
    import re
    decision = {
        "recommendation": "HOLD_WATCH",
        "confidence": 60,
        "reasoning": "Insufficient data for definitive recommendation.",
        "what_changed": [],
        "news_tone": "inconclusive",
        "sector_context": "unknown",
        "technical_read": "neutral",
        "monitor_next": [],
        "new_stop_suggestion": None,
        "urgency": "medium",
    }
    try:
        json_match = re.search(r'\{[\s\S]*\}', llm_response)
        if json_match:
            parsed = json.loads(json_match.group())
            decision.update(parsed)
    except:
        decision["reasoning"] = llm_response[:300]

    # ── Build formatted brief ────────────────────────────────────
    rec_emoji = {
        "HOLD": "🟢", "HOLD_WATCH": "🟡", "PARTIAL_TRIM": "🟠",
        "HONOR_STOP": "🔴", "DELAY_STOP": "🟡", "OVERRIDE_TEMPORARY": "🔵"
    }
    rec = decision["recommendation"]
    emoji = rec_emoji.get(rec, "⚪")

    brief_lines = [
        f"### STOP DECISION BRIEF — {symbol}",
        "",
        f"**Alert**",
        f"- Price: ${price:.2f}",
        f"- Stop: ${stop_price:.2f}",
        f"- Distance: {dist_pct:.1f}%",
        f"- Position: {total_shares:.1f} shares / ${total_mv:,.0f} / {weight:.2f}% of portfolio",
        f"- Unrealized: ${total_gl:+,.0f} ({gl_pct:+.1f}%)",
        f"- Technical: RSI {rsi or '?'} | SMA200 {f'{sma200_pct:+.1f}%' if sma200_pct else '?'}",
        "",
        f"**What changed**",
    ]
    for bullet in decision.get("what_changed", ["No specific catalyst identified"]):
        brief_lines.append(f"- {bullet}")

    brief_lines.extend([
        "",
        f"**News/Catalysts** — Tone: {decision.get('news_tone', '?').upper()}",
    ])
    if top_catalysts:
        for c in top_catalysts[:3]:
            brief_lines.append(f"- [{c.get('llm_score',0)}] {c.get('title','')[:65]}")
    else:
        brief_lines.append("- No catalysts found (7 sources searched)")

    brief_lines.extend([
        "",
        f"**Sector** — {decision.get('sector_context', '?').upper()}",
        f"- {sector} / {industry}",
        f"- Peer avg 1W: {peer_avg_week:+.1f}%",
    ])
    for p in peers[:3]:
        brief_lines.append(f"- {p['symbol']}: {p['perf_week']:+.1f}% 1W, RSI {p['rsi']:.0f}")

    brief_lines.extend([
        "",
        f"{emoji} **DECISION: {rec.replace('_', ' ')}** (Confidence: {decision['confidence']}%)",
        f"{decision['reasoning']}",
        "",
        f"**Monitor next 24-72h:**",
    ])
    for item in decision.get("monitor_next", ["Price action at stop level"]):
        brief_lines.append(f"- {item}")

    if decision.get("new_stop_suggestion"):
        brief_lines.append(f"- Suggested new stop: ${decision['new_stop_suggestion']:.2f}")

    brief_text = "\n".join(brief_lines)

    # ── Build Telegram message ───────────────────────────────────
    tg_msg = (
        f"{emoji} <b>STOP BRIEF — {symbol}</b>\n\n"
        f"Price: ${price:.2f} | Stop: ${stop_price:.2f} | Gap: {dist_pct:.1f}%\n"
        f"Position: ${total_mv:,.0f} ({weight:.2f}%) | P&L: ${total_gl:+,.0f}\n\n"
        f"<b>Decision: {rec.replace('_', ' ')}</b> ({decision['confidence']}% confidence)\n"
        f"{decision['reasoning']}\n\n"
        f"News: {decision.get('news_tone','?').upper()} | "
        f"Sector: {decision.get('sector_context','?').upper()} | "
        f"Technical: {decision.get('technical_read','?').upper()}\n\n"
        f"{''.join(f'• {m}' + chr(10) for m in decision.get('monitor_next', []))}"
    )

    # ── Save to state ────────────────────────────────────────────
    result = {
        "symbol": symbol,
        "generated_at": datetime.now().isoformat(),
        "alert": {
            "price": price, "stop": stop_price, "dist_pct": round(dist_pct, 2),
            "market_value": total_mv, "weight": round(weight, 3),
            "gain_loss": total_gl, "gain_pct": round(gl_pct, 1),
        },
        "decision": decision,
        "brief_text": brief_text,
        "telegram_msg": tg_msg,
        "data_sources": {
            "catalysts_found": len(top_catalysts),
            "peers_compared": len(peers),
            "has_enrichment": bool(e),
            "has_technical": bool(tech),
            "earnings_date": earnings_date,
            "thesis_groups": thesis_groups,
        },
    }

    # Save latest brief
    briefs_dir = sd / "stop_briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    brief_path = briefs_dir / f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    brief_path.write_text(json.dumps(result, indent=2, default=str))

    # Also save as current for CC display
    current_path = sd / "stop_brief_latest.json"
    current_path.write_text(json.dumps(result, indent=2, default=str))

    return result


def send_stop_brief_telegram(result: Dict):
    """Send the decision brief via the shared chokepoint (captures to Reports portal)."""
    msg = result.get("telegram_msg", "")
    if not msg:
        return

    from telegram_alert import send_telegram
    send_telegram(msg, bypass_router=True)


def process_stop_alerts(danger_list: List[Dict], state_dir: str, root: str = ".") -> List[Dict]:
    """Process all danger-level stop alerts and generate briefs.
    Called from portfolio_alerts.py when stops trigger."""
    results = []
    for d in danger_list:
        sym = d.get("symbol", "")
        if not sym:
            continue
        print(f"  [stop-brief] Generating decision brief for {sym}...")
        try:
            result = generate_stop_brief(sym, d, state_dir, root)

            # DB first, Telegram second
            try:
                from alert_event_writer import save_alert_event
                price = result.get("price", d.get("price", 0))
                stop_p = result.get("stop_price", d.get("stop_price", 0))
                dec = result.get("decision", {})
                save_alert_event(
                    alert_type="stop_brief",
                    raw_text=result.get("telegram_msg", "")[:2000],
                    symbol=sym,
                    severity="warning" if dec.get("recommendation") != "SELL" else "urgent",
                    source_script="stop_decision_brief.py",
                    price=price if price else None,
                    stop_price=stop_p if stop_p else None,
                    gap_pct=result.get("dist_pct"),
                    position_value=result.get("market_value"),
                    pnl=result.get("total_gl"),
                    decision=dec.get("recommendation"),
                    confidence=dec.get("confidence"),
                    parsed_payload={"accounts": result.get("accounts", []),
                                    "rsi": result.get("rsi"),
                                    "beta": result.get("beta")},
                    requires_agent_review=True,
                )
            except Exception as e:
                print(f"  [stop-brief] Alert DB write failed (non-fatal): {e}")

            send_stop_brief_telegram(result)
            rec = result.get("decision", {}).get("recommendation", "?")
            conf = result.get("decision", {}).get("confidence", 0)
            print(f"  [stop-brief] {sym}: {rec} ({conf}% confidence)")
            results.append(result)
        except Exception as e:
            print(f"  [stop-brief] {sym} error: {e}")
    return results
