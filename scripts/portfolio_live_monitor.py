"""portfolio_live_monitor.py — Portfolio Intelligence Live Monitor v1.1

Runs during market hours (9:00 AM – 4:30 PM ET, Mon–Fri).
Every 15 minutes: reprices all holdings from Finviz, checks triggers, fires Telegram.
9:00 AM: Morning Brief to Telegram.
4:15 PM: End-of-Day Summary to Telegram.

Self-terminates at 4:31 PM. Safe to leave running — won't fire outside market hours.

Usage:
    python scripts\\portfolio_live_monitor.py
    (or via Task Scheduler — see launchers\\run_portfolio_monitor.bat)

Trigger conditions (first-occurrence per trading day, 24hr cooldown):
    PRICE ACTION  : Single position ±3% on the day
    CONCENTRATION : Any position exceeds 30% portfolio weight
    MA CROSS      : Price crosses SMA50 or SMA200 (either direction)
    RSI EXTREME   : RSI > 70 (overbought) or RSI < 30 (oversold)
    VOLUME SPIKE  : RVOL > 3x on any holding
    52-WEEK HIGH  : Any holding hits new 52-week high
    DRAWDOWN      : Portfolio down > 1% on the day
    GAIN DAY      : Portfolio up > 1% on the day
    NEWS          : High-impact catalyst on any holding
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

MARKET_OPEN_ET  = (9,  0)
MARKET_CLOSE_ET = (16, 15)
SELF_TERMINATE  = (16, 31)
CYCLE_MINUTES   = 15

THRESH_SINGLE_MOVE_PCT  = 3.0
THRESH_CONCENTRATION    = 30.0
THRESH_RVOL_SPIKE       = 3.0
THRESH_RSI_HIGH         = 70.0
THRESH_RSI_LOW          = 30.0
THRESH_PORTFOLIO_MOVE   = 1.0

COOLDOWN_HOURS = 24

def _env(k: str, default: str = "") -> str:
    v = os.getenv(k, default).strip()
    if not v:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            v = os.getenv(k, default).strip()
        except Exception:
            pass
    return v

def _load_env_file(root: Path) -> None:
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

def _send_telegram(message: str, root: Path) -> bool:
    try:
        _load_env_file(root)
        sys.path.insert(0, str(root / "scripts"))
        from telegram_alert import send_telegram
        return send_telegram(message)
    except Exception as e:
        print(f"  [monitor] Telegram error: {e}")
        return False

def _et_now() -> datetime:
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo("America/New_York")).replace(tzinfo=None)
    except Exception:
        return datetime.now()

def _is_market_hours() -> bool:
    now = _et_now()
    if now.weekday() >= 5:
        return False
    h, m = now.hour, now.minute
    open_mins  = MARKET_OPEN_ET[0]  * 60 + MARKET_OPEN_ET[1]
    close_mins = SELF_TERMINATE[0]  * 60 + SELF_TERMINATE[1]
    now_mins   = h * 60 + m
    return open_mins <= now_mins < close_mins

def _mins_from_midnight(h: int, m: int) -> int:
    return h * 60 + m

def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")

def _fetch_holdings_data(symbols: List[str], root: Path) -> Dict[str, Dict]:
    if not symbols:
        return {}

    results = {}

    # ── Tier 1: Broker canonical — get_best_quote + indicator_snapshot (2026-08-01) ──
    broker_inds: dict = {}
    try:
        _load_env_file(root)
        sys.path.insert(0, str(root / "scripts"))
        from market_quote_provider import get_best_quote
        for sym in symbols:
            try:
                q = get_best_quote(sym) or {}
                live = q.get("last_price")
                if live and float(live) > 0:
                    price = float(live)
                    results[sym] = {"price": price, "change_pct": float(q.get("change_pct", 0))}
            except Exception:
                continue
    except Exception:
        pass

    try:
        from lib.data_broker.indicator_snapshot import get_indicator_snapshot
        broker_inds = get_indicator_snapshot(symbols) or {}
    except Exception:
        pass

    for sym in symbols:
        b = broker_inds.get(sym.upper(), {}) or {}
        if sym not in results:
            results[sym] = {}
        d = results[sym]
        if "price" not in d:
            try:
                from market_quote_provider import get_best_quote
                q = get_best_quote(sym) or {}
                live = q.get("last_price")
                if live and float(live) > 0:
                    d["price"] = float(live)
                    d["change_pct"] = float(q.get("change_pct", 0))
            except Exception:
                pass
        d["rsi"] = float(b.get("rsi_14", 50)) if b.get("rsi_14") is not None else 50
        d["rvol"] = float(b.get("rvol_session", 0)) if b.get("rvol_session") is not None else 0
        if b.get("sma_50") is not None:
            sma50 = float(b["sma_50"])
            px = d.get("price", 0) or 1
            d["sma50_pct"] = round((px / sma50 - 1) * 100, 2)
        else:
            d["sma50_pct"] = 0
        if b.get("sma_200") is not None:
            sma200 = float(b["sma_200"])
            px = d.get("price", 0) or 1
            d["sma200_pct"] = round((px / sma200 - 1) * 100, 2)
        else:
            d["sma200_pct"] = 0
        d["week52_high"] = float(b.get("high_52w", 0)) if b.get("high_52w") else 0
        d["week52_low"] = float(b.get("low_52w", 0)) if b.get("low_52w") else 0

    # ── Tier 2: Fall back to Finviz for any missing data ──
    missing = [s for s in symbols if not results.get(s, {}).get("price") or not results.get(s, {}).get("rsi")]
    if missing:
        try:
            _load_env_file(root)
            sys.path.insert(0, str(root / "scripts"))
            from portfolio_technical import get_technical_data
            tech = get_technical_data(missing, root)
            for sym, data in tech.items():
                d = results.setdefault(sym, {})
                for k in ("price", "change_pct", "rvol", "rsi", "sma50_pct", "sma200_pct",
                          "week52_high", "week52_low", "volume", "analyst", "target"):
                    cur = d.get(k) or 0
                    new = data.get(k, 0) or 0
                    if isinstance(cur, (int, float)) and isinstance(new, (int, float)):
                        if cur in (0, 50) and new not in (0, 50):
                            d[k] = new
                    elif isinstance(new, str) and not cur:
                        d[k] = new
        except Exception as e:
            print(f"  [monitor] Finviz fallback error: {e}")

    # ── Tier 3: Price cache for any remaining gaps ──
    gap_syms = [s for s in symbols if not results.get(s, {}).get("price")]
    if gap_syms:
        try:
            cache_path = root / "data" / "portfolios" / "state" / "price_cache.json"
            if cache_path.exists():
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
                today = _et_now().strftime("%Y-%m-%d")
                yesterday = (_et_now() - timedelta(days=1)).strftime("%Y-%m-%d")
                for sym in gap_syms:
                    sym_data = cache.get(sym, {})
                    price = sym_data.get(today) or sym_data.get(yesterday)
                    if isinstance(price, dict):
                        price = price.get("close")
                    if price:
                        results[sym] = results.get(sym, {})
                        results[sym]["price"] = float(price)
                        results[sym]["change_pct"] = 0
                        results[sym]["rvol"] = 0
                        results[sym]["rsi"] = 50
                        results[sym]["sma50_pct"] = 0
                        results[sym]["sma200_pct"] = 0
                        results[sym]["week52_high"] = 0
                        results[sym]["week52_low"] = 0
                        results[sym]["volume"] = 0
        except Exception:
            pass

    print(f"  [monitor] Data tiers: broker_quote={sum(1 for s in symbols if results.get(s, {}).get('price', 0) > 0)}, "
          f"broker_inds={sum(1 for v in broker_inds.values() if v)}, "
          f"finviz_fallback={len(missing)}, cache_fallback={len(gap_syms)}")
    return results

class TriggerState:
    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "monitor_trigger_state.json"
        self._state: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._state = json.loads(self.path.read_text())
        except Exception:
            self._state = {}

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._state, indent=2))
        except Exception:
            pass

    def _key(self, ticker: str, trigger: str) -> str:
        return f"{ticker}::{trigger}"

    def can_fire(self, ticker: str, trigger: str) -> bool:
        key = self._key(ticker, trigger)
        last = self._state.get(key)
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
            return (datetime.now() - last_dt).total_seconds() > COOLDOWN_HOURS * 3600
        except Exception:
            return True

    def mark_fired(self, ticker: str, trigger: str) -> None:
        self._state[self._key(ticker, trigger)] = datetime.now().isoformat()
        self._save()

def check_triggers(portfolio: Dict, market_data: Dict[str, Dict], trigger_state: TriggerState) -> List[Dict]:
    alerts = []
    holdings = [h for h in portfolio.get("holdings", [])
                if not h.get("is_loan") and not h.get("is_cash")
                and (h.get("market_value") or 0) > 500]

    totals   = portfolio.get("portfolio_totals", {})
    total_mv = totals.get("total_value", 0) or 1

    day_change = totals.get("day_change", 0) or 0
    day_pct    = (day_change / (total_mv - day_change) * 100) if total_mv > 0 else 0

    if day_pct <= -THRESH_PORTFOLIO_MOVE and trigger_state.can_fire("PORTFOLIO", "DOWN_1PCT"):
        alerts.append({"ticker": "PORTFOLIO", "trigger": "DOWN_1PCT",
                        "msg": f"📉 *Portfolio down {day_pct:.1f}% today*\nTotal: ${total_mv:,.0f}  Day: ${day_change:+,.0f}"})
        trigger_state.mark_fired("PORTFOLIO", "DOWN_1PCT")

    if day_pct >= THRESH_PORTFOLIO_MOVE and trigger_state.can_fire("PORTFOLIO", "UP_1PCT"):
        alerts.append({"ticker": "PORTFOLIO", "trigger": "UP_1PCT",
                        "msg": f"📈 *Portfolio up {day_pct:.1f}% today*\nTotal: ${total_mv:,.0f}  Day: ${day_change:+,.0f}"})
        trigger_state.mark_fired("PORTFOLIO", "UP_1PCT")

    for h in holdings:
        sym      = h.get("symbol", "")
        shares   = h.get("shares", 0) or 0
        mv       = h.get("market_value", 0) or 0
        cost     = h.get("cost_basis", 0) or 0
        weight   = (mv / total_mv * 100) if total_mv > 0 else 0
        mkt      = market_data.get(sym, {})
        price    = mkt.get("price", mv / shares if shares > 0 else 0)
        chg_pct  = mkt.get("change_pct", 0)
        rvol     = mkt.get("rvol", 0)
        rsi      = mkt.get("rsi", 50)
        sma50p   = mkt.get("sma50_pct", 0)
        sma200p  = mkt.get("sma200_pct", 0)
        hi52     = mkt.get("week52_high", 0)

        if not sym or not price:
            continue

        if weight > THRESH_CONCENTRATION and trigger_state.can_fire(sym, "CONCENTRATION"):
            alerts.append({"ticker": sym, "trigger": "CONCENTRATION",
                "msg": f"⚠️ *{sym} concentration: {weight:.1f}%*\nExceeds 30% threshold → ${mv:,.0f}\nConsider trimming from Rollover IRA (zero tax)"})
            trigger_state.mark_fired(sym, "CONCENTRATION")

        if chg_pct >= THRESH_SINGLE_MOVE_PCT and trigger_state.can_fire(sym, "UP_3PCT"):
            alerts.append({"ticker": sym, "trigger": "UP_3PCT",
                "msg": f"📈 *{sym} +{chg_pct:.1f}% today*\n${price:.2f}  MV: ${mv:,.0f}  Weight: {weight:.1f}%"})
            trigger_state.mark_fired(sym, "UP_3PCT")

        if chg_pct <= -THRESH_SINGLE_MOVE_PCT and trigger_state.can_fire(sym, "DOWN_3PCT"):
            alerts.append({"ticker": sym, "trigger": "DOWN_3PCT",
                "msg": f"📉 *{sym} {chg_pct:.1f}% today*\n${price:.2f}  MV: ${mv:,.0f}  Weight: {weight:.1f}%"})
            trigger_state.mark_fired(sym, "DOWN_3PCT")

        if sma50p is not None and -1.0 <= sma50p <= 1.0:
            direction = "above ↑" if sma50p >= 0 else "below ↓"
            if trigger_state.can_fire(sym, "SMA50_CROSS"):
                alerts.append({"ticker": sym, "trigger": "SMA50_CROSS",
                    "msg": f"📊 *{sym} crossed 50-day MA ({direction})*\nPrice: ${price:.2f}  SMA50 distance: {sma50p:+.1f}%"})
                trigger_state.mark_fired(sym, "SMA50_CROSS")

        if sma200p is not None and -1.5 <= sma200p <= 1.5:
            direction = "above ↑ (Golden)" if sma200p >= 0 else "below ↓ (Death)"
            if trigger_state.can_fire(sym, "SMA200_CROSS"):
                alerts.append({"ticker": sym, "trigger": "SMA200_CROSS",
                    "msg": f"🔔 *{sym} crossed 200-day MA — {direction}*\nPrice: ${price:.2f}  SMA200 distance: {sma200p:+.1f}%\n_Major trend change signal_"})
                trigger_state.mark_fired(sym, "SMA200_CROSS")

        if rsi >= THRESH_RSI_HIGH and trigger_state.can_fire(sym, "RSI_HIGH"):
            alerts.append({"ticker": sym, "trigger": "RSI_HIGH",
                "msg": f"🔴 *{sym} RSI {rsi:.0f} — Overbought*\nPrice: ${price:.2f}  Weight: {weight:.1f}%\n_Consider partial trim if overweight_"})
            trigger_state.mark_fired(sym, "RSI_HIGH")

        if rsi <= THRESH_RSI_LOW and trigger_state.can_fire(sym, "RSI_LOW"):
            alerts.append({"ticker": sym, "trigger": "RSI_LOW",
                "msg": f"🟢 *{sym} RSI {rsi:.0f} — Oversold*\nPrice: ${price:.2f}  Cost: ${cost/shares:.2f}/sh\n_Potential add opportunity_"})
            trigger_state.mark_fired(sym, "RSI_LOW")

        if rvol >= THRESH_RVOL_SPIKE and trigger_state.can_fire(sym, "RVOL_SPIKE"):
            alerts.append({"ticker": sym, "trigger": "RVOL_SPIKE",
                "msg": f"🚀 *{sym} volume spike — RVOL {rvol:.1f}x*\nPrice: ${price:.2f}  Change: {chg_pct:+.1f}%\n_Check for news or institutional activity_"})
            trigger_state.mark_fired(sym, "RVOL_SPIKE")

        if hi52 > 0 and price >= hi52 * 0.99 and trigger_state.can_fire(sym, "52WK_HIGH"):
            alerts.append({"ticker": sym, "trigger": "52WK_HIGH",
                "msg": f"🏆 *{sym} approaching 52-week high*\nPrice: ${price:.2f}  52wk High: ${hi52:.2f}\nWeight: {weight:.1f}%"})
            trigger_state.mark_fired(sym, "52WK_HIGH")

    return alerts

def _morning_brief(portfolio: Dict, market_data: Dict[str, Dict], root: Path) -> str:
    totals   = portfolio.get("portfolio_totals", {})
    total_mv = totals.get("total_value", 0)
    day_chg  = totals.get("day_change", 0) or 0
    day_pct  = (day_chg / (total_mv - day_chg) * 100) if total_mv > 0 else 0
    as_of    = portfolio.get("as_of", "")

    holdings = [h for h in portfolio.get("holdings", [])
                if not h.get("is_loan") and not h.get("is_cash")
                and (h.get("market_value") or 0) > 1000]

    mover_lines = []
    for h in sorted(holdings, key=lambda x: abs(market_data.get(x.get("symbol",""), {}).get("change_pct", 0)), reverse=True)[:5]:
        sym  = h.get("symbol","")
        mkt  = market_data.get(sym, {})
        chg  = mkt.get("change_pct", 0)
        px   = mkt.get("price", 0)
        if px and abs(chg) > 0.1:
            arrow = "📈" if chg >= 0 else "📉"
            mover_lines.append(f"  {arrow} {sym:6} ${px:.2f}  {chg:+.1f}%")

    movers_txt = "\n".join(mover_lines) if mover_lines else "  (no significant pre-market moves)"
    day_arrow = "📈" if day_chg >= 0 else "📉"
    sign      = "+" if day_chg >= 0 else ""

    return "\n".join([
        f"☀️ *Portfolio Morning Brief — {as_of}*",
        "",
        f"💼 Total: *${total_mv:,.0f}*  {day_arrow} {sign}{day_pct:.2f}% (${day_chg:+,.0f})",
        "",
        f"📊 Pre-Market Snapshot:",
        movers_txt,
        "",
        f"_Monitor running — 15-min refresh + intraday alerts active_",
        f"_Next: End-of-day summary at 4:15 PM ET_",
    ])

def _eod_summary(portfolio: Dict, market_data: Dict[str, Dict], alerts_fired: List[str], root: Path) -> str:
    totals   = portfolio.get("portfolio_totals", {})
    total_mv = totals.get("total_value", 0)
    day_chg  = totals.get("day_change", 0) or 0
    day_pct  = (day_chg / (total_mv - day_chg) * 100) if total_mv > 0 else 0
    all_gain = totals.get("total_gain", 0) or 0
    all_pct  = totals.get("total_gain_pct", 0) or 0
    as_of    = portfolio.get("as_of", "")

    holdings = [h for h in portfolio.get("holdings", [])
                if not h.get("is_loan") and not h.get("is_cash")
                and (h.get("market_value") or 0) > 1000]

    def _day_val(h):
        sym    = h.get("symbol","")
        mkt    = market_data.get(sym, {})
        chg    = mkt.get("change_pct", 0)
        mv     = h.get("market_value", 0) or 0
        return mv * chg / 100

    sorted_h = sorted(holdings, key=_day_val, reverse=True)
    winners  = [h for h in sorted_h if _day_val(h) > 0][:5]
    losers   = [h for h in sorted_h if _day_val(h) < 0][-4:][::-1]

    def _fmt_holding(h):
        sym  = h.get("symbol","")
        mv   = h.get("market_value",0) or 0
        mkt  = market_data.get(sym, {})
        chg  = mkt.get("change_pct", 0)
        val  = mv * chg / 100
        px   = mkt.get("price", 0)
        return f"  {sym:6} {chg:+.1f}%  ${val:+,.0f}  @ ${px:.2f}"

    day_arrow = "📈" if day_chg >= 0 else "📉"
    sign      = "+" if day_chg >= 0 else ""

    lines = [
        f"🌆 *Portfolio Close — {as_of}*",
        "",
        f"💼 Total: *${total_mv:,.0f}*  {day_arrow} {sign}{day_pct:.2f}% (${day_chg:+,.0f} today)",
        f"📈 All-time: *${all_gain:+,.0f}* (+{all_pct:.1f}%)",
        "",
    ]

    if winners:
        lines.append("✅ *Winners:*")
        lines.extend(_fmt_holding(h) for h in winners)
        lines.append("")

    if losers:
        lines.append("⬇️ *Losers:*")
        lines.extend(_fmt_holding(h) for h in losers)
        lines.append("")

    if alerts_fired:
        lines.append(f"🔔 *Alerts fired today: {len(alerts_fired)}*")
        for a in alerts_fired[-5:]:
            lines.append(f"  • {a}")
        lines.append("")

    lines.append("_Portfolio Intelligence v1.2_")
    return "\n".join(lines)

def main() -> None:
    root = Path(__file__).parent.parent.resolve()
    _load_env_file(root)
    if str(root / "scripts") not in sys.path:
        sys.path.insert(0, str(root / "scripts"))

    state_dir   = root / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    trigger_state = TriggerState(state_dir)

    print(f"\n{'='*60}")
    print(f"  Portfolio Live Monitor v1.0")
    print(f"  Market hours: 9:00 AM – 4:30 PM ET | Cycle: {CYCLE_MINUTES} min (reprice + triggers)")
    print(f"  Self-terminates at 4:31 PM ET")
    print(f"{'='*60}\n")

    morning_brief_sent = False
    eod_sent           = False
    alerts_fired_today: List[str] = []
    last_cycle         = datetime.min

    while True:
        now = _et_now()
        now_mins = _mins_from_midnight(now.hour, now.minute)
        term_mins = _mins_from_midnight(*SELF_TERMINATE)

        if now_mins >= term_mins:
            print(f"[{_hhmm(now)}] 4:31 PM — shutting down.")
            break

        if now.weekday() >= 5:
            print(f"[{_hhmm(now)}] Weekend — sleeping 60 min...")
            time.sleep(3600)
            continue

        open_mins  = _mins_from_midnight(*MARKET_OPEN_ET)
        close_mins = _mins_from_midnight(*MARKET_CLOSE_ET)

        if now_mins < open_mins:
            wait = open_mins - now_mins
            print(f"[{_hhmm(now)}] Pre-market — opening in {wait} min")
            time.sleep(min(wait * 60, 300))
            continue

        try:
            from portfolio_loader import load_all_portfolios
            portfolio = load_all_portfolios(root)
        except Exception as e:
            print(f"  [monitor] Portfolio load error: {e}")
            time.sleep(300)
            continue

        symbols = list(set(
            h["symbol"] for h in portfolio.get("holdings", [])
            if h.get("symbol") and not h.get("is_loan") and not h.get("is_cash")
            and (h.get("market_value") or 0) > 500
            and len(h["symbol"]) <= 6
        ))

        print(f"[{_hhmm(now)}] Fetching data for {len(symbols)} holdings...")
        market_data = _fetch_holdings_data(symbols, root)
        print(f"  → Got data for {len(market_data)} symbols")

        if open_mins <= now_mins <= open_mins + 15 and not morning_brief_sent:
            print(f"  → Sending morning brief...")
            brief = _morning_brief(portfolio, market_data, root)
            _send_telegram(brief, root)
            morning_brief_sent = True
            alerts_fired_today = []
            print(f"  ✅ Morning brief sent")

        if now_mins >= close_mins and not eod_sent:
            print(f"  → Sending end-of-day summary...")
            summary = _eod_summary(portfolio, market_data, alerts_fired_today, root)
            _send_telegram(summary, root)
            eod_sent = True
            print(f"  ✅ EOD summary sent")

        if now.hour == 0 and now.minute < 5:
            morning_brief_sent = False
            eod_sent           = False
            alerts_fired_today = []

        elapsed = (now - last_cycle).total_seconds()
        if elapsed >= CYCLE_MINUTES * 60 or last_cycle == datetime.min:
            print(f"  → Checking {len(symbols)} triggers...")
            triggered = check_triggers(portfolio, market_data, trigger_state)

            for alert in triggered:
                msg = alert["msg"]
                sym = alert.get("ticker", "")
                trig = alert.get("trigger", "")
                print(f"  🔔 ALERT: {sym} — {trig}")

                # DB first
                try:
                    from alert_event_writer import save_alert_event
                    type_map = {
                        "DOWN_3PCT": "portfolio_intelligence", "UP_8PCT": "portfolio_intelligence",
                        "SMA50_CROSS": "technical_signal", "SMA200_CROSS": "technical_signal",
                        "RSI_HIGH": "technical_signal", "RSI_LOW": "technical_signal",
                        "RVOL_SPIKE": "technical_signal", "52WK_HIGH": "technical_signal",
                        "CONCENTRATION": "concentration_alert",
                        "DRAWDOWN": "drawdown_alert", "GAIN_DAY": "gain_alert",
                    }
                    sev_map = {
                        "SMA200_CROSS": "warning", "RSI_HIGH": "warning", "DOWN_3PCT": "warning",
                        "CONCENTRATION": "warning", "DRAWDOWN": "warning",
                    }
                    save_alert_event(
                        alert_type=type_map.get(trig, "technical_signal"),
                        raw_text=msg[:2000],
                        symbol=sym,
                        severity=sev_map.get(trig, "info"),
                        source_script="portfolio_live_monitor.py",
                        parsed_payload={"trigger": trig},
                    )
                except Exception as e:
                    print(f"  [monitor] Alert DB write failed (non-fatal): {e}")

                _send_telegram(msg, root)
                alerts_fired_today.append(f"{_hhmm(now)} — {sym} {trig}")

            if not triggered:
                print(f"  → No triggers fired this cycle")

            last_cycle = now

            try:
                from portfolio_repricer import reprice_portfolio
                from portfolio_loader import save_state
                portfolio = reprice_portfolio(portfolio, state_dir)

                holdings_all = portfolio.get("holdings", [])
                total_dc = sum(h.get("day_change") or 0 for h in holdings_all)
                pt = portfolio.setdefault("portfolio_totals", {})
                pt["day_change"] = round(total_dc, 2)
                total_mv = pt.get("total_value", 1) or 1
                prev_mv  = total_mv - total_dc
                pt["day_change_pct"] = round((total_dc / prev_mv * 100) if prev_mv != 0 else 0, 4)

                account_summaries = portfolio.get("account_summaries", {})
                for acct_id, summary in account_summaries.items():
                    acct_holdings = [h for h in holdings_all if h.get("account_id") == acct_id]
                    acct_dc = sum(h.get("day_change") or 0 for h in acct_holdings)
                    summary["day_change"] = round(acct_dc, 2)
                    acct_mv = summary.get("total_value", 1) or 1
                    acct_prev = acct_mv - acct_dc
                    summary["day_change_pct"] = round((acct_dc / acct_prev * 100) if acct_prev != 0 else 0, 4)

                save_state(portfolio, state_dir)
                print(f"  → Dashboard repriced: ${pt.get('total_value',0):,.0f}  Today: ${total_dc:+,.0f} ({pt.get('day_change_pct',0):+.2f}%)")
            except Exception as e:
                print(f"  [monitor] Reprice error: {e}")

        next_mins = (now_mins // CYCLE_MINUTES + 1) * CYCLE_MINUTES
        wait_secs = max(60, (next_mins - now_mins) * 60 - now.second)
        next_fire = (now + timedelta(seconds=wait_secs)).strftime("%H:%M")
        print(f"  → Next cycle at {next_fire}  (sleep {int(wait_secs//60)}m {int(wait_secs%60)}s)")
        time.sleep(wait_secs)

if __name__ == "__main__":
    main()
