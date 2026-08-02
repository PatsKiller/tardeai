"""Re-Entry Decision Desk — deterministic broker-backed row builder.

READY / NEAR / BLOCK states are computed only from Data Broker stores + prefs.
No LLM on this path. RSI band matches rotation gates: 40 <= RSI < 70.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESISTANCE_KEY = "portfolio.reentry.resistance.v1"
STALE_HOURS = 96
NEAR_PCT = 3.0
RSI_READY_LOW = 40.0
RSI_READY_HIGH = 70.0
RSI_OVERSOLD = 30.0
WASH_DAYS = 30
RISK_PCT = 0.01          # 1% account risk rule
MAX_ALLOC_PCT = 0.10     # 10% max capital allocation
MA_TOUCH_PCT = 1.5       # within 1.5% of SMA counts as MA test/hold
DEFAULT_BOOK = 1_250_000.0


def _scripts_path() -> None:
    scripts = str(PROJECT_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def _f(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _age_hours(as_of: str | None) -> float | None:
    """Hours since quote timestamp. Accepts ISO and broker forms like '2026-08-01 07:35:12 ET'."""
    if not as_of:
        return None
    s = str(as_of).strip()
    if not s:
        return None
    try:
        import re
        from zoneinfo import ZoneInfo

        m = re.match(r"^(.+?)\s+(ET|EST|EDT|UTC|GMT|Z)$", s, re.I)
        if m:
            body, tz = m.group(1).strip(), m.group(2).upper()
            if "T" not in body and " " in body:
                body = body.replace(" ", "T", 1)
            naive = datetime.fromisoformat(body)
            if tz in ("ET", "EST", "EDT"):
                ts = naive.replace(tzinfo=ZoneInfo("America/New_York"))
            else:
                ts = naive.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                # Naive market quotes are Eastern unless explicitly UTC/Z
                try:
                    ts = ts.replace(tzinfo=ZoneInfo("America/New_York"))
                except Exception:
                    ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds() / 3600)
    except Exception:
        return None


def _weekend_fresh_ok(age_h: float | None, *, stale_hours: float = STALE_HOURS) -> bool:
    """True when quote is within stale_hours, or is a Friday RTH print held over Sat/Sun.

    Operators decide on weekends from last session quotes — do not fail freshness solely
    because the calendar crossed into Saturday/Sunday.
    """
    if age_h is None:
        return False
    if age_h <= stale_hours:
        return True
    try:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
        # Sat=5, Sun=6 — allow up to Fri 16:00 → Sun night (~56h) plus buffer to stale_hours
        if now_et.weekday() >= 5 and age_h <= max(stale_hours, 72.0):
            return True
    except Exception:
        pass
    return False


def derive_intel_state(
    *,
    price: float | None,
    rsi: float | None,
    as_of: str | None,
    entry_low: float | None,
    entry_high: float | None,
    held: bool,
    wash_blocked: bool = False,
) -> dict[str, Any]:
    """Canonical READY band: in zone + 40 <= RSI < 70 (matches rotation gates)."""
    age_h = _age_hours(as_of)
    stale = age_h is None or not _weekend_fresh_ok(age_h)

    distance_pct = None
    if price is not None and entry_low is not None and entry_high is not None and entry_low > 0 and entry_high > 0:
        if price > entry_high:
            distance_pct = ((price - entry_high) / entry_high) * 100
        elif price < entry_low:
            distance_pct = -((entry_low - price) / entry_low) * 100
        else:
            distance_pct = 0.0

    state = "WAIT"
    action = "Keep monitoring"
    reason = "Current price has not reached the validated entry conditions."

    if held:
        state, action, reason = (
            "CURRENTLY HELD",
            "Manage as an existing holding",
            "This symbol is currently held and is not a clean re-entry-only candidate.",
        )
    elif wash_blocked:
        state, action, reason = (
            "WASH BLOCK",
            "Wait for wash window",
            f"Exit within {WASH_DAYS} days — wash-sale window still open (deterministic).",
        )
    elif price is None or rsi is None:
        state, action, reason = (
            "MISSING MARKET",
            "Refresh market evidence",
            "Current price and RSI from the data broker are required before a re-entry review.",
        )
    elif stale:
        state, action, reason = (
            "STALE",
            "Refresh inputs",
            f"Market/technical evidence is stale ({age_h:.0f}h)." if age_h is not None
            else "Market/technical evidence timestamp is unavailable or too old.",
        )
    elif entry_low is None or entry_high is None:
        state, action, reason = (
            "MISSING PLAN",
            "Build a candidate entry zone",
            "Market evidence exists, but no current validated entry range is available.",
        )
    elif rsi >= RSI_READY_HIGH:
        state, action, reason = (
            "OVERBOUGHT WAIT",
            "Wait for RSI to cool",
            f"RSI {rsi:.1f} is overbought (>= {RSI_READY_HIGH:.0f}); not a re-entry review.",
        )
    elif distance_pct == 0 and rsi <= RSI_OVERSOLD:
        state, action, reason = (
            "OVERSOLD REVIEW",
            "Review with caution",
            f"Price is in zone but RSI {rsi:.1f} is oversold (<= {RSI_OVERSOLD:.0f}) — not full READY.",
        )
    elif distance_pct == 0 and RSI_READY_LOW <= rsi < RSI_READY_HIGH:
        state, action, reason = (
            "READY TO REVIEW",
            "Review re-entry now",
            f"Price is inside the entry zone and RSI {rsi:.1f} is in the constructive band "
            f"({RSI_READY_LOW:.0f}–{RSI_READY_HIGH:.0f}).",
        )
    elif distance_pct == 0 and rsi < RSI_READY_LOW:
        # Between oversold floor and READY band (e.g. RSI 31–39): not READY yet.
        state, action, reason = (
            "WAIT",
            "Wait for RSI to strengthen",
            f"Price is in zone but RSI {rsi:.1f} is below the constructive band "
            f"({RSI_READY_LOW:.0f}–{RSI_READY_HIGH:.0f}).",
        )
    elif distance_pct is not None and 0 < distance_pct <= NEAR_PCT and rsi < RSI_READY_HIGH:
        state, action, reason = (
            "NEAR ENTRY",
            "Prepare the review",
            f"Price is {distance_pct:.1f}% above the entry zone; RSI {rsi:.1f} is not overbought.",
        )
    elif distance_pct is not None and 0 < distance_pct <= NEAR_PCT and rsi >= RSI_READY_HIGH:
        state, action, reason = (
            "OVERBOUGHT WAIT",
            "Wait for RSI to cool",
            f"Near zone but RSI {rsi:.1f} is overbought.",
        )

    return {
        "state": state,
        "action": action,
        "reason": reason,
        "distance_pct": round(distance_pct, 3) if distance_pct is not None else None,
        "chips": [],
        "criteria": {
            "rsi_band": f"{RSI_READY_LOW:.0f} <= RSI < {RSI_READY_HIGH:.0f}",
            "near_pct": NEAR_PCT,
            "stale_hours": STALE_HOURS,
            "deterministic": True,
            "llm_in_path": False,
        },
    }


def _pref_json(db_query: Callable, key: str) -> dict[str, Any]:
    row = db_query("SELECT value FROM ui_prefs WHERE key=%s", (key,), fetch="one") or {}
    value = row.get("value")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _held_symbols() -> set[str]:
    path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out: set[str] = set()
    for row in data.get("holdings") or []:
        if row.get("is_cash"):
            continue
        try:
            if float(row.get("shares") or 0) > 0:
                out.add(str(row.get("symbol") or "").upper())
        except (TypeError, ValueError):
            pass
    return {s for s in out if s}


def _quote(symbol: str) -> dict[str, Any]:
    _scripts_path()
    try:
        from market_quote_provider import get_best_quote
        q = get_best_quote(symbol) or {}
        price = _f(q.get("last_price"))
        return {
            "price": price,
            "as_of": q.get("quote_timestamp") or datetime.now(timezone.utc).isoformat(),
            "source": q.get("provider") or "get_best_quote",
        }
    except Exception as e:
        return {"price": None, "as_of": None, "source": None, "error": str(e)[:120]}


def _action_label(state: str) -> str:
    if state == "READY TO REVIEW":
        return "Tactical Re-Entry / Buy Limit"
    if state == "NEAR ENTRY":
        return "Prepare Re-Entry / Watch Limit"
    if state == "OVERSOLD REVIEW":
        return "Caution Review — Oversold"
    if state == "WASH BLOCK":
        return "Blocked — Wash Window"
    if state == "OVERBOUGHT WAIT":
        return "Wait — Overbought"
    return "Monitor / No Action"


def _near_ma(price: float | None, ma: float | None) -> bool:
    if price is None or ma is None or ma <= 0:
        return False
    return abs(price - ma) / ma * 100 <= MA_TOUCH_PCT


def _load_fund_lookthrough_map() -> dict[str, Any]:
    """Per-fund sector weights + top holdings from phase3 fund_lookthrough.json."""
    path = PROJECT_ROOT / "data" / "portfolios" / "state" / "fund_lookthrough.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, entry in raw.items():
        if key.startswith("_") or not isinstance(entry, dict):
            continue
        ticker = str(entry.get("public_ticker") or key).upper().strip()
        if ticker:
            out[ticker] = entry
        out[str(key).upper()] = entry
    return out


def _lookthrough_payload(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    sectors_raw = entry.get("sector_weights") or {}
    holdings_raw = entry.get("top_holdings") or []
    sectors = []
    if isinstance(sectors_raw, dict):
        for name, pct in sorted(sectors_raw.items(), key=lambda kv: -float(kv[1] or 0)):
            try:
                sectors.append({"name": str(name), "pct": round(float(pct), 2)})
            except (TypeError, ValueError):
                continue
            if len(sectors) >= 8:
                break
    holdings = []
    if isinstance(holdings_raw, list):
        for row in holdings_raw[:10]:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or row.get("symbol") or "").upper()
            if not ticker:
                continue
            holdings.append({
                "ticker": ticker,
                "name": row.get("name"),
                "pct": _f(row.get("pct") or row.get("weight")),
            })
    if not sectors and not holdings:
        return {
            "available": False,
            "fund_name": entry.get("fund_name"),
            "fund_type": entry.get("fund_type") or entry.get("asset_class"),
            "as_of": entry.get("fetched_date"),
            "source": entry.get("data_source"),
            "sectors": [],
            "top_holdings": [],
            "note": "Fund/ETF recognized but look-through weights not on file yet",
        }
    return {
        "available": True,
        "fund_name": entry.get("fund_name"),
        "fund_type": entry.get("fund_type") or entry.get("asset_class"),
        "as_of": entry.get("fetched_date"),
        "source": entry.get("data_source"),
        "sectors": sectors,
        "top_holdings": holdings,
        "note": None,
    }


def build_advisory(
    *,
    symbol: str,
    state: str,
    price: float | None,
    entry_low: float | None,
    entry_high: float | None,
    stop: float | None,
    target: float | None,
    rr: float | None,
    rsi: float | None,
    sma_20: float | None,
    sma_50: float | None,
    sma_200: float | None,
    sma20_pct: float | None,
    sma50_pct: float | None,
    sma200_pct: float | None,
    macd_signal: str | None,
    alignment: str | None = None,
    obv_signal: str | None = None,
    obv_trend: str | None = None,
    cmf_signal: str | None = None,
    cmf_value: float | None = None,
    volume_ratio: float | None = None,
    instrument_type: str | None = None,
    resistance: dict[str, Any],
    catalyst: dict[str, Any] | None,
    wash_blocked: bool,
    wash_until: str | None,
    earnings_date: str | None,
    book_equity: float,
    why: list[str],
    company: str | None = None,
    lookthrough: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Broker-style advisory card payload (deterministic; no LLM prose)."""
    today = datetime.now(timezone.utc).date().isoformat()
    entry_mid = None
    if entry_low is not None and entry_high is not None:
        entry_mid = (entry_low + entry_high) / 2
    elif price is not None:
        entry_mid = price

    risk_lo = risk_hi = reward_lo = reward_hi = None
    if entry_low is not None and stop is not None and entry_low > stop:
        risk_hi = round(entry_low - stop, 4)
    if entry_high is not None and stop is not None and entry_high > stop:
        risk_lo = round(entry_high - stop, 4)
    if entry_high is not None and target is not None and target > entry_high:
        reward_lo = round(target - entry_high, 4)
    if entry_low is not None and target is not None and target > entry_low:
        reward_hi = round(target - entry_low, 4)

    risk_per_share = None
    if entry_mid is not None and stop is not None and entry_mid > stop:
        risk_per_share = round(entry_mid - stop, 4)

    max_dollar_risk = round(book_equity * RISK_PCT, 2)
    max_alloc = round(book_equity * MAX_ALLOC_PCT, 2)
    shares_1pct = None
    alloc = None
    sizing_note = "Need entry + stop to size"
    if risk_per_share and risk_per_share > 0:
        shares_1pct = int(max_dollar_risk // risk_per_share)
        alloc = round(shares_1pct * entry_mid, 2) if entry_mid and shares_1pct else None
        if alloc is not None and alloc > max_alloc and entry_mid and entry_mid > 0:
            shares_1pct = int(max_alloc // entry_mid)
            alloc = round(shares_1pct * entry_mid, 2)
            sizing_note = f"Capped at {MAX_ALLOC_PCT*100:.0f}% allocation"
        else:
            sizing_note = f"{RISK_PCT*100:.0f}% risk rule on ${book_equity:,.0f} book"

    ma_touch = None
    if _near_ma(price, sma_200):
        ma_touch = ("200-SMA", sma_200, sma200_pct)
    elif _near_ma(price, sma_50):
        ma_touch = ("50-SMA", sma_50, sma50_pct)
    elif _near_ma(price, sma_20):
        ma_touch = ("20-SMA", sma_20, sma20_pct)

    align = str(alignment or "").lower()
    above_structure = (
        price is not None and sma_20 is not None and price >= sma_20
        and (align in ("bullish", "aligned", "up") or (sma_50 is not None and sma_20 >= sma_50))
    )
    ma_met = bool(ma_touch) or bool(above_structure)
    if ma_touch:
        ma_name, ma_level, ma_pct = ma_touch
        ma_detail = f"Price holding {ma_name} @ ${ma_level:.2f}"
        if ma_pct is not None:
            ma_detail += f" ({ma_pct:+.1f}%)"
    elif above_structure:
        ma_detail = (
            f"Price above SMA20 @ ${sma_20:.2f}"
            + (f" · alignment {alignment}" if alignment else " · structure held")
        )
    else:
        ma_detail = "Not within 1.5% of SMA20/50/200 and not holding above SMA20"

    res_state = str((resistance or {}).get("state") or "UNAVAILABLE").upper()
    res_level = _f((resistance or {}).get("level"))

    earn_days = None
    if earnings_date:
        try:
            earn_days = (datetime.fromisoformat(str(earnings_date)[:10]).date()
                         - datetime.now(timezone.utc).date()).days
        except Exception:
            earn_days = None

    lt = _lookthrough_payload(lookthrough) if lookthrough else None
    is_fund = bool(lt) or str(instrument_type or "").lower() in (
        "fund", "mutualfund", "mutual_fund", "etf", "equityetf",
    ) or ("fund" in str(company or "").lower()) or ("etf" in str(company or "").lower())
    vol_met: bool | None
    if is_fund:
        vol_met = True
        vol_detail = "N/A — fund/ETF (no meaningful share volume); skipped"
    elif volume_ratio is not None:
        vol_met = float(volume_ratio) >= 1.0
        vol_detail = f"Volume ratio {float(volume_ratio):.2f}x avg"
    else:
        obv_ok = str(obv_signal or "").upper() in ("BULLISH", "POSITIVE") or str(obv_trend or "").lower() in ("up", "rising", "improving")
        cmf_ok = str(cmf_signal or "").upper() in ("BULLISH", "POSITIVE") or (cmf_value is not None and float(cmf_value) > 0)
        if obv_ok or cmf_ok:
            vol_met = True
            parts = []
            if obv_signal or obv_trend:
                parts.append(f"OBV {obv_signal or '—'} ({obv_trend or '—'})")
            if cmf_signal is not None or cmf_value is not None:
                parts.append(f"CMF {cmf_signal or '—'}{f' {float(cmf_value):+.3f}' if cmf_value is not None else ''}")
            vol_detail = " · ".join(parts) if parts else "Money-flow confirms"
        elif obv_signal is None and cmf_signal is None and cmf_value is None:
            vol_met = None
            vol_detail = "Volume/OBV/CMF unavailable in indicator cache"
        else:
            vol_met = False
            vol_detail = f"OBV {obv_signal or '—'} ({obv_trend or '—'}) · CMF {cmf_signal or '—'} — no accumulation"

    criteria = [
        {
            "id": "ma_bounce",
            "met": ma_met,
            "label": "Moving average bounce / hold",
            "detail": ma_detail,
        },
        {
            "id": "support",
            "met": res_state in ("ABOVE", "TESTING") or (entry_low is not None and price is not None and entry_low <= price <= (entry_high or entry_low)),
            "label": "Support / zone validation",
            "detail": (
                f"Resistance {res_state} @ ${res_level:.2f}" if res_level is not None
                else ("Inside entry zone" if entry_low is not None else "No support/resistance evidence")
            ),
        },
        {
            "id": "rsi_reset",
            "met": rsi is not None and RSI_READY_LOW <= rsi < RSI_READY_HIGH,
            "label": "Momentum oscillator reset (RSI)",
            "detail": f"RSI {rsi:.1f} (band {RSI_READY_LOW:.0f}–{RSI_READY_HIGH:.0f})" if rsi is not None else "RSI unavailable",
        },
        {
            "id": "macd",
            "met": bool(macd_signal) and str(macd_signal).upper() not in ("BEARISH", "NEGATIVE", "SELL"),
            "label": "MACD confirmation",
            "detail": f"MACD {macd_signal}" if macd_signal else "MACD unavailable",
        },
        {
            "id": "volume",
            "met": vol_met,
            "label": "Volume / money-flow confirmation",
            "detail": vol_detail,
        },
        {
            "id": "rr",
            "met": rr is not None and rr >= 2.0,
            "label": "Reward-to-risk (≥2:1 preferred; 3:1 ideal)",
            "detail": f"R:R {rr}:1" if rr is not None else "Need stop + target",
        },
        {
            "id": "invalidation",
            "met": stop is not None,
            "label": "Invalidation stop below structure",
            "detail": f"Stop ${stop:.2f}" if stop is not None else "No stop on entry plan",
        },
        {
            "id": "catalyst",
            "met": not (earn_days is not None and 0 <= earn_days <= 5),
            "label": "Catalyst / earnings window clear",
            "detail": (
                f"Earnings in {earn_days}d ({earnings_date})" if earn_days is not None and earn_days <= 5
                else (f"Next earnings {earnings_date}" if earnings_date
                      else ("Catalyst verified" if catalyst and catalyst.get("verified")
                            else "No near-term earnings on file"))
            ),
        },
        {
            "id": "wash",
            "met": not wash_blocked,
            "label": "Wash-sale window clear",
            "detail": f"Blocked until {wash_until}" if wash_blocked else "Clear (30d taxable)",
        },
    ]

    # Confirmations that must not stay amber/red for a clean READY badge.
    confirm_ids = {"ma_bounce", "volume", "rr", "invalidation", "wash"}
    confirm_fail = [c for c in criteria if c["id"] in confirm_ids and c.get("met") is False]
    confirm_check = [c for c in criteria if c["id"] in confirm_ids and c.get("met") is None]
    confirmations_complete = not confirm_fail and not confirm_check

    return {
        "date": today,
        "action": _action_label(state),
        "ticker": symbol,
        "company": company,
        "reentry_range_low": entry_low,
        "reentry_range_high": entry_high,
        "stop_loss": stop,
        "risk_per_share_low": risk_lo,
        "risk_per_share_high": risk_hi,
        "target": target,
        "reward_low": reward_lo,
        "reward_high": reward_hi,
        "rr": rr,
        "live_price": price,
        "earnings_date": earnings_date,
        "earnings_days": earn_days,
        "sizing": {
            "book_equity": round(book_equity, 2),
            "risk_pct": RISK_PCT,
            "max_alloc_pct": MAX_ALLOC_PCT,
            "max_dollar_risk": max_dollar_risk,
            "risk_per_share": risk_per_share,
            "shares": shares_1pct,
            "allocation": alloc,
            "note": sizing_note,
            "formula": "shares = (book × 1%) / (entry − stop); cap alloc ≤ 10% book",
        },
        "criteria": criteria,
        "rationale": why,
        "confirmations_complete": confirmations_complete,
        "confirmation_gaps": [c["id"] for c in confirm_fail + confirm_check],
        "is_fund": is_fund,
        "lookthrough": lt,
        "advisory_only": True,
    }


def build_decision_desk(
    db_query: Callable,
    symbols: list[str] | None = None,
    *,
    max_symbols: int = 250,
) -> dict[str, Any]:
    """Build deterministic Decision Desk payload for Re-Entry symbols."""
    _scripts_path()
    from lib.data_broker.indicator_snapshot import get_indicator_snapshot
    from lib.data_broker.catalyst_record import get_catalyst_record
    from lib.data_broker.portfolio_snapshot import get_portfolio_snapshot
    from lib.data_broker.symbol_profile import get_symbol_profiles
    from lib.data_broker.entry_plan import get_entry_plans

    resistance_pref = _pref_json(db_query, RESISTANCE_KEY)
    resistance_map = resistance_pref.get("symbols") or {}
    held = _held_symbols()

    if not symbols:
        sym_set = {str(s).upper() for s in resistance_map if s}
        try:
            exits = db_query(
                """SELECT DISTINCT upper(symbol) AS symbol
                   FROM trade_transactions
                   WHERE trade_date >= CURRENT_DATE - 365
                     AND (lower(coalesce(action,'')) IN
                            ('sell','sold','assigned','assignment','expired','exercise','exercised','close','closed')
                          OR lower(coalesce(action,'')) LIKE 'sell%%')
                   ORDER BY 1
                   LIMIT %s""",
                (max_symbols,),
            ) or []
            for row in exits:
                if row.get("symbol"):
                    sym_set.add(str(row["symbol"]).upper())
        except Exception:
            pass
        symbols = sorted(sym_set)[:max_symbols]
    else:
        symbols = [str(s).upper() for s in symbols if s][:max_symbols]

    snap = get_portfolio_snapshot()
    heat = (snap.get("risk") or {}).get("portfolio_heat_pct")
    book_equity = _f((snap.get("totals") or {}).get("total_value")) or DEFAULT_BOOK
    fund_lt_map = _load_fund_lookthrough_map()

    indicators = get_indicator_snapshot(symbols) if symbols else {"by_symbol": {}}
    by_ind = indicators.get("by_symbol") or {}

    earnings_map: dict[str, str] = {}
    company_map: dict[str, str] = {}
    instrument_map: dict[str, str] = {}
    if symbols:
        try:
            profiles = get_symbol_profiles(db_query, symbols)
            for sym, prof in profiles.items():
                if prof.get("next_earnings_date"):
                    ed = prof["next_earnings_date"]
                    earnings_map[sym] = ed.isoformat()[:10] if hasattr(ed, "isoformat") else str(ed)[:10]
                label = " · ".join(x for x in [prof.get("sector"), prof.get("industry")] if x)
                if label:
                    company_map[sym] = label[:80]
                instrument_map[sym] = str(prof.get("instrument_type") or "")
        except Exception:
            instrument_map = {}

    plans: dict[str, dict[str, Any]] = {}
    if symbols:
        try:
            plans = get_entry_plans(db_query, symbols)
        except Exception:
            plans = {}

    wash_until: dict[str, str] = {}
    if symbols:
        try:
            sells = db_query(
                """SELECT upper(symbol) AS symbol, max(trade_date) AS last_sell
                   FROM trade_transactions
                   WHERE upper(symbol) = ANY(%s)
                     AND trade_date >= CURRENT_DATE - %s
                     AND (lower(coalesce(action,'')) IN
                            ('sell','sold','assigned','assignment','expired','exercise','exercised','close','closed')
                          OR lower(coalesce(action,'')) LIKE 'sell%%')
                     AND NOT (lower(coalesce(account,'')) LIKE '%%paper%%'
                              OR lower(coalesce(account,'')) LIKE '%%roth%%'
                              OR lower(coalesce(account,'')) LIKE '%%ira%%')
                   GROUP BY 1""",
                (symbols, WASH_DAYS),
            ) or []
            for row in sells:
                sym = str(row.get("symbol") or "").upper()
                last = row.get("last_sell")
                if sym and last:
                    last_s = last.isoformat()[:10] if hasattr(last, "isoformat") else str(last)[:10]
                    try:
                        until = (datetime.fromisoformat(last_s).date() + timedelta(days=WASH_DAYS)).isoformat()
                        wash_until[sym] = until
                    except Exception:
                        pass
        except Exception:
            wash_until = {}

    today = datetime.now(timezone.utc).date().isoformat()
    rows_out: list[dict[str, Any]] = []
    for sym in symbols:
        quote = _quote(sym)
        ind = by_ind.get(sym) or {}
        plan = plans.get(sym) or {}
        res = resistance_map.get(sym) or {}
        try:
            cat = get_catalyst_record(db_query, sym)
        except Exception:
            cat = None

        price = quote.get("price")
        rsi = _f(ind.get("rsi"))
        entry_low = _f(plan.get("entry_zone_low"))
        entry_high = _f(plan.get("entry_zone_high"))
        stop = _f(plan.get("stop_price"))
        target = _f(plan.get("target_price"))
        wash_blocked = bool(wash_until.get(sym) and wash_until[sym] >= today)

        intel = derive_intel_state(
            price=price,
            rsi=rsi,
            as_of=quote.get("as_of"),
            entry_low=entry_low,
            entry_high=entry_high,
            held=sym in held,
            wash_blocked=wash_blocked,
        )
        if intel.get("state") == "MISSING MARKET" and price is not None and rsi is None:
            intel = {
                **intel,
                "reason": "Quote present but RSI missing from indicator_confluence_cache — run indicator_cache_refresh for exited symbols.",
                "action": "Refresh indicator cache",
            }

        chips = list(intel.get("chips") or [])
        res_state = str(res.get("state") or "UNAVAILABLE").upper()
        if res_state in ("BELOW", "UNAVAILABLE", "MISSING") or res.get("resistance") is None:
            chips.append({"tone": "amber", "label": "resistance not reclaimed", "detail": res_state})
        elif res_state == "ABOVE" and _f(res.get("hold_days")) is not None:
            chips.append({
                "tone": "green",
                "label": f"resistance hold {int(res.get('hold_days') or 0)}d",
                "detail": res_state,
            })
        if cat and not cat.get("verified"):
            chips.append({"tone": "info", "label": "catalyst unverified", "detail": (cat.get("headline") or "")[:80]})
        elif cat and cat.get("verified"):
            chips.append({"tone": "green", "label": "catalyst verified", "detail": (cat.get("headline") or "")[:80]})
        if heat is not None:
            try:
                if float(heat) >= 8:
                    chips.append({"tone": "amber", "label": f"portfolio heat {float(heat):.1f}%", "detail": "size carefully"})
            except (TypeError, ValueError):
                pass
        if ind.get("macd_signal"):
            chips.append({"tone": "info", "label": f"macd {ind.get('macd_signal')}", "detail": "indicator_snapshot"})
        if wash_blocked:
            chips.append({"tone": "red", "label": f"wash until {wash_until.get(sym)}", "detail": "deterministic 30d"})

        rr = None
        if price and stop and target and price > stop:
            risk = price - stop
            reward = target - price
            if risk > 0:
                rr = round(reward / risk, 2)

        age_h = _age_hours(quote.get("as_of"))
        in_zone = intel.get("distance_pct") == 0
        rsi_ok = rsi is not None and RSI_READY_LOW <= rsi < RSI_READY_HIGH
        fresh_ok = _weekend_fresh_ok(age_h)
        gates = [
            {"id": "fresh", "pass": fresh_ok, "label": "Fresh quote", "value": f"{age_h:.0f}h" if age_h is not None else "missing"},
            {"id": "zone", "pass": bool(in_zone), "label": "Inside entry zone", "value": (
                f"${price:.2f} in ${entry_low:.2f}–${entry_high:.2f}" if price and entry_low and entry_high and in_zone
                else (f"{intel.get('distance_pct'):+.1f}% vs zone" if intel.get("distance_pct") is not None else "no zone")
            )},
            {"id": "rsi", "pass": bool(rsi_ok), "label": f"RSI {RSI_READY_LOW:.0f}–{RSI_READY_HIGH:.0f}", "value": f"{rsi:.1f}" if rsi is not None else "missing"},
            {"id": "not_held", "pass": sym not in held, "label": "Not currently held", "value": "held" if sym in held else "flat"},
            {"id": "wash", "pass": not wash_blocked, "label": "Wash window clear", "value": wash_until.get(sym) or "clear"},
        ]
        why = []
        if in_zone and price is not None and entry_low is not None and entry_high is not None:
            why.append(f"Price ${price:.2f} is inside the validated entry zone ${entry_low:.2f}–${entry_high:.2f}.")
        elif intel.get("distance_pct") is not None and entry_high is not None:
            why.append(f"Price is {intel['distance_pct']:+.1f}% from the entry zone (near threshold {NEAR_PCT:.0f}%).")
        if rsi is not None:
            if rsi_ok:
                why.append(f"RSI {rsi:.1f} is in the constructive band ({RSI_READY_LOW:.0f} ≤ RSI < {RSI_READY_HIGH:.0f}).")
            elif rsi >= RSI_READY_HIGH:
                why.append(f"RSI {rsi:.1f} is overbought (≥ {RSI_READY_HIGH:.0f}) — wait to cool.")
            elif rsi <= RSI_OVERSOLD:
                why.append(f"RSI {rsi:.1f} is oversold (≤ {RSI_OVERSOLD:.0f}) — caution, not full READY.")
            else:
                why.append(f"RSI {rsi:.1f} is below the constructive band — wait for strength.")
        if stop is not None and target is not None and rr is not None:
            why.append(f"Plan risk: stop ${stop:.2f} → target ${target:.2f} (R:R {rr}).")
        if res_state == "BELOW":
            why.append(f"Closed-session resistance still ABOVE price at {res.get('resistance')} (not reclaimed).")
        elif res_state == "ABOVE":
            why.append(f"Price has reclaimed resistance; hold {int(res.get('hold_days') or 0)} closed sessions.")
        if wash_blocked:
            why.append(f"Taxable sell within {WASH_DAYS}d — wash blocked until {wash_until.get(sym)}.")
        if not why:
            why.append(intel.get("reason") or "Insufficient broker evidence for a re-entry review.")

        resistance_payload = {
            "state": res_state,
            "level": _f(res.get("resistance")),
            "distance_pct": _f(res.get("distance_pct")),
            "hold_days": _f(res.get("hold_days")),
            "as_of": res.get("as_of"),
            "live_price": _f(res.get("live_price")),
            "live_as_of": res.get("live_as_of"),
            "source": "CLOSED-SESSION CACHE",
        }
        try:
            advisory = build_advisory(
                symbol=sym,
                state=str(intel.get("state") or "WAIT"),
                price=price,
                entry_low=entry_low,
                entry_high=entry_high,
                stop=stop,
                target=target,
                rr=rr,
                rsi=rsi,
                sma_20=_f(ind.get("sma_20")),
                sma_50=_f(ind.get("sma_50")),
                sma_200=_f(ind.get("sma_200")),
                sma20_pct=_f(ind.get("sma20_pct")),
                sma50_pct=_f(ind.get("sma50_pct")),
                sma200_pct=_f(ind.get("sma200_pct")),
                macd_signal=ind.get("macd_signal"),
                alignment=ind.get("alignment"),
                obv_signal=ind.get("obv_signal"),
                obv_trend=ind.get("obv_trend"),
                cmf_signal=ind.get("cmf_signal"),
                cmf_value=_f(ind.get("cmf_value")),
                volume_ratio=_f(ind.get("volume_ratio")),
                instrument_type=instrument_map.get(sym),
                resistance=resistance_payload,
                catalyst=cat if isinstance(cat, dict) else None,
                wash_blocked=wash_blocked,
                wash_until=wash_until.get(sym),
                earnings_date=earnings_map.get(sym),
                book_equity=float(book_equity),
                why=why,
                company=company_map.get(sym),
                lookthrough=fund_lt_map.get(sym),
            )
        except Exception as adv_err:
            advisory = {
                "date": datetime.now(timezone.utc).date().isoformat(),
                "action": _action_label(str(intel.get("state") or "WAIT")),
                "ticker": sym,
                "company": company_map.get(sym),
                "reentry_range_low": entry_low,
                "reentry_range_high": entry_high,
                "stop_loss": stop,
                "target": target,
                "rr": rr,
                "live_price": price,
                "sizing": {"shares": None, "note": f"advisory build failed: {str(adv_err)[:80]}"},
                "criteria": [],
                "rationale": why,
                "confirmations_complete": False,
                "confirmation_gaps": ["advisory_error"],
                "advisory_only": True,
            }

        # Amber/red confirmations are NOT ready — downgrade hard READY until gaps clear.
        if intel.get("state") == "READY TO REVIEW" and not advisory.get("confirmations_complete", True):
            gaps = ", ".join(advisory.get("confirmation_gaps") or []) or "confirmations"
            intel = {
                **intel,
                "state": "NEAR ENTRY",
                "action": "Confirm setup before re-entry",
                "reason": (
                    f"Hard gates pass (zone + RSI), but confirmations incomplete ({gaps}). "
                    "Not marked READY until MA/volume/R:R/stop/wash are green."
                ),
            }
            advisory = {**advisory, "action": _action_label("NEAR ENTRY")}
            chips.append({"tone": "amber", "label": "confirmations incomplete", "detail": gaps})

        rows_out.append({
            "symbol": sym,
            "price": price,
            "price_as_of": quote.get("as_of"),
            "price_source": quote.get("source"),
            "price_age_h": age_h,
            "rsi": rsi,
            "rsi_status": ind.get("rsi_status"),
            "sma20_pct": ind.get("sma20_pct"),
            "sma50_pct": ind.get("sma50_pct"),
            "sma200_pct": ind.get("sma200_pct"),
            "sma_20": ind.get("sma_20"),
            "sma_50": ind.get("sma_50"),
            "sma_200": ind.get("sma_200"),
            "macd_signal": ind.get("macd_signal"),
            "macd_histogram_direction": ind.get("macd_histogram_direction"),
            "atr": ind.get("atr"),
            "alignment": ind.get("alignment"),
            "obv_signal": ind.get("obv_signal"),
            "obv_trend": ind.get("obv_trend"),
            "cmf_signal": ind.get("cmf_signal"),
            "volume_ratio": ind.get("volume_ratio"),
            "indicator_source": ind.get("source") or ("indicator_confluence_cache" if ind else None),
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop": stop,
            "target": target,
            "rr": rr,
            "plan_as_of": str(plan.get("created_at") or "")[:32] or None,
            "resistance": resistance_payload,
            "catalyst": cat,
            "wash_blocked": wash_blocked,
            "wash_until": wash_until.get(sym),
            "held": sym in held,
            "heat_pct": heat,
            "earnings_date": earnings_map.get(sym),
            "company": company_map.get(sym),
            "gates": gates,
            "why": why,
            "advisory": advisory,
            "intel": {**intel, "chips": chips},
            "research_summary": None,
        })

    order = {
        "READY TO REVIEW": 0,
        "NEAR ENTRY": 1,
        "OVERSOLD REVIEW": 2,
        "WAIT": 3,
        "OVERBOUGHT WAIT": 4,
        "STALE": 5,
        "MISSING PLAN": 6,
        "MISSING MARKET": 7,
        "WASH BLOCK": 8,
        "CURRENTLY HELD": 9,
    }
    rows_out.sort(key=lambda r: (order.get((r.get("intel") or {}).get("state"), 50), r.get("symbol") or ""))

    ages = [r.get("price_age_h") for r in rows_out if r.get("price_age_h") is not None]
    actionable = [
        r for r in rows_out
        if (r.get("intel") or {}).get("state") in ("READY TO REVIEW", "NEAR ENTRY", "OVERSOLD REVIEW")
    ]
    act_ages = [r.get("price_age_h") for r in actionable if r.get("price_age_h") is not None]
    stale_n = sum(1 for a in ages if a is not None and a > STALE_HOURS)
    return {
        "ok": True,
        "version": "reentry-decision-desk-v1",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "deterministic": True,
        "llm_in_path": False,
        "criteria": {
            "rsi_ready": f"{RSI_READY_LOW:.0f} <= RSI < {RSI_READY_HIGH:.0f}",
            "near_pct": NEAR_PCT,
            "stale_hours": STALE_HOURS,
            "wash_days": WASH_DAYS,
        },
        "freshness": {
            "resistance_generated_at": resistance_pref.get("generated_at"),
            # Use actionable median for the strip — max across all exits was poisoned by dead names (164d).
            "price_age_h_median": sorted(act_ages)[len(act_ages) // 2] if act_ages else (
                sorted(ages)[len(ages) // 2] if ages else None
            ),
            "price_age_h_max_actionable": max(act_ages) if act_ages else None,
            "price_age_h_max": max(ages) if ages else None,
            "stale_symbol_count": stale_n,
            "heat_pct": heat,
            "symbol_count": len(rows_out),
            "actionable_count": len(actionable),
        },
        "rows": rows_out,
    }
