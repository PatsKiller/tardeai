"""portfolio_technical.py v2.0 — Technical Intelligence Engine
Portfolio Intelligence v1.2 | Trade AI v12

Architecture (3-tier, never crashes):
  TIER 1 — Finviz API Token  : price, change%, analyst target, volume (v=152)
                                + performance week/month/quarter/YTD (v=141)
                                Zero-expiry. Batch 20 tickers per request.
  TIER 2 — Finviz Cookie     : RSI(14), SMA20/50/200%, ATR(14), Beta, 52wk H/L
                                via quote.ashx per ticker. Expires with browser session.
                                On failure: fires Telegram alert once/day, uses Tier 3.
  TIER 3 — Stale Snapshot    : technical_snapshot.json with age tracking.
                                Dashboard shows staleness badge. Alerts suppressed
                                for SMA/RSI triggers when data > 1 trading day old.

Fidelity 401k funds: internal codes mapped to real tickers via
  assets/portfolio_accounts.yaml → fidelity_ticker_map section.

Holdings coverage: all Finviz-queryable positions (target ~28 vs prior 13).
  Skips: revoked securities, CASH, 401K-LOAN, internal codes without mapping.

Cookie expiry Telegram alert format:
  🍪 FINVIZ COOKIE EXPIRED
  Technical data (RSI/SMA/ATR) unavailable.
  Last good data: YYYY-MM-DD (N days ago)
  → Open env_manager.html → paste fresh cookie → save .env to project root
  Positions affected: N | Alerts: SMA/RSI triggers suppressed

Changes from v1.0:
  - Graceful degradation: never exits code 1 due to Finviz failure
  - Cookie health check on startup (single test request before batch)
  - Telegram expiry alert (24hr cooldown, max 1/day)
  - Staleness tracking: data_age_days + cookie_ok in snapshot
  - Fidelity ticker map: reads fidelity_ticker_map from portfolio_accounts.yaml
  - Expanded coverage: ~28 positions vs prior 13 (4 new Fidelity + 11 uncovered)
  - v=141 performance columns added to Tier 1 API pull
  - Hourly monitor: uses cached RSI/SMA from morning snapshot (no re-scrape)
    Fresh cookie scrape only triggered by price-based alerts (DOWN_3PCT etc.)
"""
from __future__ import annotations

import json
import os
import sys
import time
import requests
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from finviz_http import finviz_get, finviz_probe  # global Finviz throttle (2026-07-20)

# ── Constants ─────────────────────────────────────────────────────────────────

# Finviz export view numbers
FV_VIEW_FUNDAMENTAL = 152  # price, analyst, PE, volume, change%
FV_VIEW_PERFORMANCE = 141  # week/month/quarter/YTD performance, volatility

# Staleness threshold — suppress SMA/RSI triggers if data older than this
STALE_HOURS = 26  # ~1 trading day + buffer

# Cookie expiry alert cooldown — fire at most once per day
COOKIE_ALERT_COOLDOWN_HOURS = 24

# Batch size for Finviz export requests (URL length limit)
BATCH_SIZE = 20

# Symbols never queryable via Finviz or Yahoo (always skip)
SKIP_SYMBOLS = {
    "SRNE", "CDEX", "LPIH", "628518102", "CASH", "401K-LOAN",
    "ARKG",   # ARK ETF — skip (low MV, not meaningful for technicals)
    "AMANX",  # Amana mutual fund — Finviz has limited data
}

# Mutual fund tickers — Finviz quote.ashx returns 404 (NAV-priced, not exchange-traded)
# Tier 1 API (screener export) still works for price/perf. RSI/SMA/ATR = N/A.
MUTUAL_FUND_TICKERS = {
    "FCNTX", "FXAIX", "TILCX", "VFTNX", "ABSZX",
    "FDIVX", "JLGMX", "WBSNX", "AMANX",
}

# Internal Fidelity code prefixes — skip unless mapped
FIDELITY_PREFIXES = ("FID-", "SS-", "TRP-", "JPM-", "VANG-", "WM-", "AB-", "SP500-")

# ── Environment helpers ───────────────────────────────────────────────────────

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
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def _f(s, default: float = 0.0) -> float:
    try:
        return float(str(s).replace(",", "").replace("%", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return default

# ── Config loaders ────────────────────────────────────────────────────────────

def load_intent(root: Path) -> Dict[str, str]:
    """Load position intent map → {SYMBOL: intent_category}"""
    intent_file = root / "assets" / "portfolio_intent.yaml"
    if not intent_file.exists():
        return {}
    try:
        raw = yaml.safe_load(intent_file.read_text())
    except Exception:
        return {}
    result = {}
    skip = {"covered_call_settings", "stop_settings", "benchmark", "fidelity_funds"}
    for category, tickers in (raw or {}).items():
        if category in skip or not isinstance(tickers, list):
            continue
        for t in tickers:
            result[str(t).upper()] = category
    return result


def load_fidelity_ticker_map(root: Path) -> Dict[str, str]:
    """
    Load Fidelity internal code → real ticker mapping from portfolio_accounts.yaml.

    Map location: portfolio_accounts.yaml → fidelity_ticker_map (top-level section)

    Example YAML:
        fidelity_ticker_map:
          FID-CONTRA-F:  FCNTX
          TRP-LVAL:      TILCX
          VANG-FTSE-SOC: VFTNX

    Returns: {internal_code: real_ticker}  e.g. {"FID-CONTRA-F": "FCNTX"}
    """
    cfg_file = root / "assets" / "portfolio_accounts.yaml"
    if not cfg_file.exists():
        return {}
    try:
        raw = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
        raw_map = raw.get("fidelity_ticker_map", {})
        return {str(k).upper(): str(v).upper() for k, v in raw_map.items()}
    except Exception:
        return {}

# ── Staleness / snapshot ──────────────────────────────────────────────────────

def _load_prior_snapshot(state_dir: Path) -> Dict:
    p = state_dir / "technical_snapshot.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_snapshot(data: Dict, state_dir: Path) -> None:
    (state_dir / "technical_snapshot.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8")


def _snapshot_age_hours(prior: Dict) -> Optional[float]:
    """Return age of snapshot in hours, or None if no timestamp."""
    ts = prior.get("_meta", {}).get("last_updated")
    if not ts:
        return None
    try:
        dt = datetime.strptime(ts[:16], "%Y-%m-%d %H:%M")
        return (datetime.now() - dt).total_seconds() / 3600
    except Exception:
        return None


def _is_stale(prior: Dict) -> bool:
    """Return True if snapshot is older than STALE_HOURS."""
    age = _snapshot_age_hours(prior)
    return age is None or age > STALE_HOURS


def _cookie_alert_fired_today(state_dir: Path) -> bool:
    """Check if cookie expiry alert was already sent today."""
    p = state_dir / "monitor_trigger_state.json"
    if not p.exists():
        return False
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
        ts_str = state.get("COOKIE_EXPIRED_ALERT")
        if not ts_str:
            return False
        dt = datetime.fromisoformat(ts_str)
        return (datetime.now() - dt).total_seconds() < COOKIE_ALERT_COOLDOWN_HOURS * 3600
    except Exception:
        return False


def _mark_cookie_alert_fired(state_dir: Path) -> None:
    """Record that cookie expiry alert was sent."""
    p = state_dir / "monitor_trigger_state.json"
    try:
        state = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        state = {}
    state["COOKIE_EXPIRED_ALERT"] = datetime.now().isoformat()
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")

# ── Telegram alert ────────────────────────────────────────────────────────────

def _send_telegram(message: str, root: Path) -> bool:
    """Send via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    try:
        scripts_dir = str(root / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram
        ok = bool(send_telegram(message))
        try:
            root_s = str(root)
            if root_s not in sys.path:
                sys.path.insert(0, root_s)
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="portfolio_technical",
                subject_key="ops:finviz_cookie",
                retention_class="operational", severity="warning",
                sanitized_body=message[:500], short_summary=message[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        return ok
    except Exception:
        return False


def _send_cookie_expiry_alert(
    root: Path,
    state_dir: Path,
    last_good_date: Optional[str],
    affected_count: int
) -> None:
    """
    Send Telegram alert when Finviz cookie has expired.
    Fires at most once per COOKIE_ALERT_COOLDOWN_HOURS (24hr).
    """
    if _cookie_alert_fired_today(state_dir):
        return

    age_str = ""
    if last_good_date:
        try:
            dt = datetime.strptime(last_good_date[:10], "%Y-%m-%d")
            days = (datetime.now() - dt).days
            age_str = f"\nLast good data: {last_good_date[:10]} ({days} day{'s' if days != 1 else ''} ago)"
        except Exception:
            age_str = f"\nLast good data: {last_good_date[:10]}"

    msg = (
        f"🍪 <b>FINVIZ COOKIE EXPIRED</b>\n\n"
        f"Technical data (RSI/SMA/ATR) is unavailable.{age_str}\n\n"
        f"<b>To fix:</b>\n"
        f"1. Open finviz.com in Chrome (logged into Elite)\n"
        f"2. F12 → Application → Cookies → finviz.com\n"
        f"3. Copy full cookie string\n"
        f"4. Open <code>env_manager.html</code> → paste → Save .env\n"
        f"5. Move downloaded .env to project root\n\n"
        f"Positions affected: {affected_count}\n"
        f"⚠️ SMA/RSI alert triggers suppressed until resolved."
    )

    if _send_telegram(msg, root):
        _mark_cookie_alert_fired(state_dir)
        print(f"  [technical] 🍪 Cookie expiry alert sent to Telegram")
    else:
        print(f"  [technical] ⚠️ Cookie expired — Telegram alert failed to send")

# ── Finviz API Token — Tier 1 ─────────────────────────────────────────────────

def _finviz_api_batch(
    tickers: List[str],
    root: Path
) -> Dict[str, Dict]:
    """
    TIER 1: Finviz Elite API token export.
    Returns: price, change%, analyst, target, volume from v=152
             + week/month/quarter/YTD performance from v=141
    No cookie required. Never expires.
    Rate limit: ~100 req/hour. Batch 20 tickers = ~2 requests for 28 positions.

    Column map v=152:
        [1]  Ticker
        [43] Analyst recommendation (Strong Buy / Buy / Hold / Sell)
        [44] Analyst price target ($)
        [45] Price
        [46] Change %
        [47] Volume

    Column map v=141:
        [1]  Ticker
        [2]  Performance (Week) %
        [3]  Performance (Month) %
        [4]  Performance (Quarter) %
        [5]  Performance (Half Year) %
        [6]  Performance (YTD) %
        [7]  Performance (Year) %
        [11] Volatility (Week) %
        [12] Volatility (Month) %
        [14] Relative Volume
        [15] Price
    """
    _load_env_file(root)
    token = _env("FINVIZ_API_TOKEN")
    if not token:
        print("  [technical] No FINVIZ_API_TOKEN — skipping Tier 1")
        return {}

    ua = _env("FINVIZ_USER_AGENT",
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    headers = {"User-Agent": ua}
    results: Dict[str, Dict] = {}

    # ── v=152: fundamental + price ────────────────────────────────────────────
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        ticker_str = ",".join(batch)
        url = (f"https://elite.finviz.com/export.ashx"
               f"?v={FV_VIEW_FUNDAMENTAL}&t={ticker_str}&auth={token}")
        try:
            # Global cooldown is published by finviz_get on 429, so the retry
            # below blocks on the shared throttle instead of a local sleep.
            resp = finviz_get(url, headers=headers, timeout=20, raise_on_429=False)
            if resp.status_code == 429:
                print("  [technical] Finviz 429 — global cooldown set, retrying")
                resp = finviz_get(url, headers=headers, timeout=20, raise_on_429=False)
            if not resp.ok or not resp.text.strip():
                print(f"  [technical] v=152 HTTP {resp.status_code} for batch {i//BATCH_SIZE+1}")
                continue
            lines = resp.text.strip().split("\n")
            for line in lines[1:]:  # skip header
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) < 2:  # COL-FIX: was 47, v=152 now returns 11 cols
                    continue
                sym = parts[1].upper()
                if not sym:
                    continue
                results[sym] = {
                    "symbol":       sym,
                    # COL-FIX 2026-05-06: Finviz v=152 now returns 15 cols
                    # No[0] Ticker[1] Company[2] Sector[3] Industry[4] Country[5]
                    # MCap[6] PE[7] SharesFloat[8] Gap[9] AvgVol[10] RelVol[11]
                    # Price[12] Change[13] Volume[14]
                    "price":        _f(parts[12] if len(parts) > 12 else ""),
                    "change_pct":   _f((parts[13] if len(parts) > 13 else "").replace("%","")),
                    "analyst":      "",
                    "target":       0.0,
                    "volume":       _f(parts[14] if len(parts) > 14 else ""),
                    "gap_pct":      _f((parts[9] if len(parts) > 9 else "").replace("%","")),
                    "relative_volume": _f(parts[11] if len(parts) > 11 else ""),
                    "shares_float": _f(parts[8] if len(parts) > 8 else ""),
                    "data_source":  "api_v152",
                }
        except Exception as e:
            print(f"  [technical] v=152 batch error: {e}")
        time.sleep(0.5)

    # ── v=141: performance + volatility ───────────────────────────────────────
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        ticker_str = ",".join(batch)
        url = (f"https://elite.finviz.com/export.ashx"
               f"?v={FV_VIEW_PERFORMANCE}&t={ticker_str}&auth={token}")
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 429:
                time.sleep(30)
                resp = requests.get(url, headers=headers, timeout=20)
            if not resp.ok or not resp.text.strip():
                continue
            lines = resp.text.strip().split("\n")
            for line in lines[1:]:
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) < 15:
                    continue
                sym = parts[1].upper()
                if sym not in results:
                    results[sym] = {"symbol": sym}
                results[sym].update({
                    "perf_week":     _f(parts[2].replace("%", "")) if len(parts) > 2 else None,
                    "perf_month":    _f(parts[3].replace("%", "")) if len(parts) > 3 else None,
                    "perf_quarter":  _f(parts[4].replace("%", "")) if len(parts) > 4 else None,
                    "perf_halfyr":   _f(parts[5].replace("%", "")) if len(parts) > 5 else None,
                    "perf_ytd":      _f(parts[6].replace("%", "")) if len(parts) > 6 else None,
                    "perf_year":     _f(parts[7].replace("%", "")) if len(parts) > 7 else None,
                    "volatility_w":  _f(parts[11].replace("%", "")) if len(parts) > 11 else None,
                    "volatility_m":  _f(parts[12].replace("%", "")) if len(parts) > 12 else None,
                    "relative_volume": _f(parts[14]) if len(parts) > 14 else None,
                })
        except Exception as e:
            print(f"  [technical] v=141 batch error: {e}")
        time.sleep(0.5)

    return results

# ── Finviz Cookie — Tier 2 ────────────────────────────────────────────────────

def _cookie_health_check(cookie: str, ua: str) -> bool:
    """
    Quick health check: fetch one ticker via quote.ashx.
    Returns True if cookie is valid, False if expired/invalid.
    Uses V (Visa) as test ticker — always in portfolio.
    """
    try:
        headers = {
            "User-Agent": ua,
            "Cookie": cookie,
            "Referer": "https://elite.finviz.com/",
        }
        resp = requests.get(
            "https://elite.finviz.com/quote.ashx?t=V&ty=l&ta=1&p=d",
            headers=headers, timeout=15
        )
        if not resp.ok:
            return False
        # Cookie is dead if response is login page or empty
        html = resp.text
        if "login" in html.lower()[:500] or len(html) < 1000:
            return False
        # Check for known technical data markers
        return "RSI" in html or "SMA" in html or "snapshot" in html.lower()
    except Exception:
        return False


def _parse_finviz_html(html: str, ticker: str) -> Dict:
    """
    Extract RSI, SMA20/50/200%, ATR, Beta, 52wk H/L from Finviz quote page HTML.

    Finviz snapshot table format:
        <td>FIELD_NAME</td><td><span>VALUE</span></td>
        or
        <td>FIELD_NAME</td><td>VALUE</td>

    SMA values are returned as % distance from price:
        positive = price is above the MA by X%
        negative = price is below the MA by X%

    Returns dict with keys: rsi, sma20_pct, sma50_pct, sma200_pct,
                            52wk_high, 52wk_low, atr, beta
    """
    import re
    result = {}

    field_map = {
        "RSI (14)":  "rsi",
        "SMA20":     "sma20_pct",
        "SMA50":     "sma50_pct",
        "SMA200":    "sma200_pct",
        "52W High":  "52wk_high",
        "52W Low":   "52wk_low",
        "ATR (14)":  "atr",
        "Beta":      "beta",
    }

    for field_name, out_key in field_map.items():
        patterns = [
            rf'<td[^>]*>\s*{re.escape(field_name)}\s*</td>\s*<td[^>]*>\s*<[^>]+>([^<]+)<',
            rf'<td[^>]*>\s*{re.escape(field_name)}\s*</td>\s*<td[^>]*>([^<]+)</td>',
            rf'{re.escape(field_name)}[^<]*</td>[^<]*<td[^>]*>([^<]+)</',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
            if m:
                raw = m.group(1).strip().replace("%", "").replace("+", "")
                try:
                    result[out_key] = float(raw)
                    break
                except (ValueError, TypeError):
                    pass

    return result


def _finviz_cookie_batch(
    tickers: List[str],
    root: Path,
    state_dir: Path,
    prior: Dict
) -> Tuple[Dict[str, Dict], bool]:
    """
    TIER 2: Finviz cookie-based scrape of quote.ashx per ticker.
    Returns (results_dict, cookie_ok).

    cookie_ok=False triggers:
      - Telegram expiry alert (once/day)
      - Caller falls back to Tier 3 (stale snapshot)
      - Dashboard staleness badge
      - Monitor suppresses SMA/RSI triggers

    Rate: 1 request per ticker + 0.3s delay = ~28 requests/batch
    Recommended: daily pipeline only (not hourly monitor)
    """
    _load_env_file(root)
    cookie = _env("FINVIZ_COOKIE") or _env("FINVIZ_SESSION")
    ua = _env("FINVIZ_USER_AGENT",
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    if not cookie:
        print("  [technical] No FINVIZ_COOKIE — Tier 2 skipped")
        return {}, False

    # ── Cookie health check ───────────────────────────────────────────────────
    print("  [technical] Checking Finviz cookie health...")
    cookie_ok = _cookie_health_check(cookie, ua)

    if not cookie_ok:
        print("  [technical] ⚠️ Finviz cookie expired or invalid")
        # Get last good date from prior snapshot
        last_good = prior.get("_meta", {}).get("last_updated")
        affected = len(tickers)
        _send_cookie_expiry_alert(root, state_dir, last_good, affected)
        return {}, False

    print("  [technical] Cookie valid — fetching RSI/SMA/ATR...")
    headers = {
        "User-Agent": ua,
        "Cookie": cookie,
        "Referer": "https://elite.finviz.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    results: Dict[str, Dict] = {}

    for ticker in tickers:
        # Skip mutual funds — Finviz has no quote.ashx page (returns 404)
        # Price/performance still available via Tier 1 API export
        if ticker in MUTUAL_FUND_TICKERS:
            continue
        try:
            url = f"https://elite.finviz.com/quote.ashx?t={ticker}&ty=l&ta=1&p=d"
            resp = requests.get(url, headers=headers, timeout=15)
            if not resp.ok:
                print(f"  [technical] {ticker}: HTTP {resp.status_code}")
                continue
            parsed = _parse_finviz_html(resp.text, ticker)
            if parsed:
                results[ticker] = parsed
            time.sleep(0.3)
        except Exception as e:
            print(f"  [technical] {ticker} quote error: {e}")

    return results, True


def get_technical_data(symbols: List[str], root: Path) -> Dict[str, Dict]:
    """
    Public interface for portfolio_live_monitor.py.
    Returns Tier 1 data only (price, change, RVOL) — no cookie scrape.
    Monitor uses cached RSI/SMA from morning snapshot.
    """
    results = _finviz_api_batch(symbols, root)
    return results

# ── Derived indicators ────────────────────────────────────────────────────────

def _derive_indicators(data: Dict, current_price: float) -> Dict:
    """
    Calculate all derived technical indicators from raw Finviz data.

    Input fields (from cookie scrape):
        sma20_pct, sma50_pct, sma200_pct  — % distance price is above/below MA
        rsi                                 — RSI(14) value 0-100
        atr                                 — Average True Range dollar value
        52wk_high, 52wk_low                — Dollar values
        beta                                — Market beta

    Derived outputs:
        sma20, sma50, sma200               — Actual dollar MA levels
        bb_upper, bb_lower                  — Bollinger Bands (SMA20 ± 2×ATR)
        bb_position_pct                     — Price position in BB (0-100%)
        macd_signal                         — bullish/bearish/neutral (SMA20 vs SMA50)
        cross                               — golden/death/none (SMA50 vs SMA200)
        above_sma20/50/200                  — Boolean price vs MA
        pct_from_high, pct_from_low         — Distance from 52wk extremes
        rsi_status                          — overbought/oversold/neutral classification
        supports, resistances               — Key S/R levels with labels
        tech_score                          — 0-100 composite score
        tech_grade                          — green/yellow/red
    """
    price = current_price or data.get("price", 0)
    if not price:
        return data

    sma20_pct  = data.get("sma20_pct")
    sma50_pct  = data.get("sma50_pct")
    sma200_pct = data.get("sma200_pct")

    # Convert % distance to dollar MA level
    # Finviz: positive % = price is above MA, negative = price is below MA
    # MA = price / (1 + pct/100)
    sma20  = round(price / (1 + sma20_pct  / 100), 2) if sma20_pct  is not None else None
    sma50  = round(price / (1 + sma50_pct  / 100), 2) if sma50_pct  is not None else None
    sma200 = round(price / (1 + sma200_pct / 100), 2) if sma200_pct is not None else None

    atr    = data.get("atr", 0) or 0
    high52 = data.get("52wk_high")
    low52  = data.get("52wk_low")
    rsi    = data.get("rsi")

    # Support / resistance levels
    supports: List[Dict] = []
    if sma200: supports.append({"level": sma200, "label": "SMA200", "type": "support", "strength": "strong"})
    if sma50:  supports.append({"level": sma50,  "label": "SMA50",  "type": "support", "strength": "medium"})
    if low52:  supports.append({"level": low52,  "label": "52wk Low", "type": "support", "strength": "floor"})

    resistances: List[Dict] = []
    if sma20  and sma20  > price: resistances.append({"level": sma20,  "label": "SMA20",    "type": "resistance"})
    if sma50  and sma50  > price: resistances.append({"level": sma50,  "label": "SMA50",    "type": "resistance"})
    if high52 and high52 > price: resistances.append({"level": high52, "label": "52wk High","type": "resistance"})

    # Bollinger Bands: SMA20 ± 2×ATR
    bb_upper = round(sma20 + 2 * atr, 2) if sma20 and atr else None
    bb_lower = round(sma20 - 2 * atr, 2) if sma20 and atr else None
    bb_pos   = None
    if bb_upper and bb_lower and bb_upper != bb_lower:
        bb_pos = round((price - bb_lower) / (bb_upper - bb_lower) * 100, 1)

    # MACD signal approximation (SMA20 vs SMA50 crossover direction)
    macd_signal = "neutral"
    if sma20 and sma50:
        macd_signal = "bullish" if sma20 > sma50 else "bearish"

    # Golden / Death Cross (SMA50 vs SMA200)
    cross = "none"
    if sma50 and sma200:
        cross = "golden" if sma50 > sma200 else "death"

    # Price vs MA booleans
    above_sma20  = price > sma20  if sma20  is not None else None
    above_sma50  = price > sma50  if sma50  is not None else None
    above_sma200 = price > sma200 if sma200 is not None else None

    # Distance from 52-week extremes
    pct_from_high = round((price - high52) / high52 * 100, 1) if high52 else None
    pct_from_low  = round((price - low52)  / low52  * 100, 1) if low52  else None

    # RSI classification
    rsi_status = "neutral"
    if rsi is not None:
        if rsi >= 75:   rsi_status = "overbought_extreme"
        elif rsi >= 70: rsi_status = "overbought"
        elif rsi <= 25: rsi_status = "oversold_extreme"
        elif rsi <= 30: rsi_status = "oversold"

    # Composite technical score
    score = _tech_score(price, sma20, sma50, sma200, rsi, pct_from_high, cross, bb_pos)

    data.update({
        "sma20":            sma20,
        "sma50":            sma50,
        "sma200":           sma200,
        "bb_upper":         bb_upper,
        "bb_lower":         bb_lower,
        "bb_position_pct":  bb_pos,
        "macd_signal":      macd_signal,
        "cross":            cross,
        "above_sma20":      above_sma20,
        "above_sma50":      above_sma50,
        "above_sma200":     above_sma200,
        "pct_from_high":    pct_from_high,
        "pct_from_low":     pct_from_low,
        "rsi_status":       rsi_status,
        "supports":         sorted(supports,     key=lambda x: x["level"], reverse=True),
        "resistances":      sorted(resistances,  key=lambda x: x["level"]),
        "tech_score":       score,
        "tech_grade":       "green" if score >= 70 else ("yellow" if score >= 40 else "red"),
        "week52_high":      high52,
        "week52_low":       low52,
    })
    return data


def _tech_score(
    price: float,
    sma20: Optional[float],
    sma50: Optional[float],
    sma200: Optional[float],
    rsi: Optional[float],
    pct_from_high: Optional[float],
    cross: str,
    bb_pos: Optional[float]
) -> int:
    """
    Composite technical score 0-100.

    Scoring matrix:
    ┌─────────────────────┬──────────┬────────────────────────────────┐
    │ Factor              │ Weight   │ Rationale                      │
    ├─────────────────────┼──────────┼────────────────────────────────┤
    │ Price vs SMA200     │ ±20 pts  │ Institutional support level    │
    │ Golden/Death Cross  │ ±15 pts  │ Long-term trend confirmation   │
    │ Price vs SMA50      │ ±10 pts  │ Intermediate trend             │
    │ Price vs SMA20      │ ±5 pts   │ Short-term momentum            │
    │ RSI zone            │ ±5-10 pts│ Overbought/oversold signal     │
    │ 52wk high distance  │ ±5 pts   │ Proximity to resistance        │
    │ Bollinger position  │ ±5 pts   │ Volatility band extremes       │
    └─────────────────────┴──────────┴────────────────────────────────┘
    Neutral baseline: 50 pts
    Max: 100 | Min: 0
    """
    score = 50
    if sma200:
        score += 20 if price > sma200 else -20
    if sma50:
        score += 10 if price > sma50 else -10
    if sma20:
        score += 5 if price > sma20 else -5
    if cross == "golden":
        score += 15
    elif cross == "death":
        score -= 15
    if rsi is not None:
        if 40 <= rsi <= 65:   score += 5    # ideal zone
        elif rsi > 75:        score -= 10   # overbought extreme
        elif rsi < 25:        score -= 10   # oversold extreme (may fall further)
        elif rsi < 35:        score += 5    # potentially bouncing
    if pct_from_high is not None:
        if pct_from_high > -5:    score -= 5   # near 52wk high = resistance
        elif pct_from_high < -20: score += 5   # far below high = room to run
    if bb_pos is not None:
        if bb_pos > 95:   score -= 5   # above upper band
        elif bb_pos < 5:  score += 5   # below lower band (oversold signal)
    return max(0, min(100, score))

# ── Stop suggestions ──────────────────────────────────────────────────────────

def _suggest_stop(data: Dict, intent: str, intent_cfg: Dict) -> Optional[float]:
    """
    Intent-based stop suggestion.

    Stop logic by intent:
    ┌──────────────────────────┬─────────────────────────────────────────────┐
    │ Intent                   │ Stop Logic                                  │
    ├──────────────────────────┼─────────────────────────────────────────────┤
    │ long_term_hold           │ SMA200 − 1.0×ATR (or SMA200×0.97 fallback) │
    │ covered_call_candidate   │ SMA200 − 1.0×ATR                           │
    │ etf_broad                │ SMA200 − 1.0×ATR                           │
    │ growth_speculative       │ tighter of: SMA50−0.5×ATR or price×0.92    │
    │ income                   │ SMA50 − 1.0×ATR                            │
    │ day_trade                │ SMA20 − 1.0×ATR                            │
    │ unclassified (default)   │ SMA50 × 0.97                               │
    └──────────────────────────┴─────────────────────────────────────────────┘
    """
    price  = data.get("price", 0)
    sma20  = data.get("sma20")
    sma50  = data.get("sma50")
    sma200 = data.get("sma200")
    atr    = data.get("atr", 0) or 0
    stop_cfg = intent_cfg.get("stop_settings", {})

    if intent in ("covered_call_candidate", "long_term_hold", "etf_broad"):
        mult = stop_cfg.get(f"{intent}_multiplier", 1.0)
        if sma200 and atr:
            return round(sma200 - mult * atr, 2)
        elif sma200:
            return round(sma200 * 0.97, 2)
    elif intent == "growth_speculative":
        mult  = stop_cfg.get("growth_speculative_multiplier", 0.5)
        trail = stop_cfg.get("trail_pct_speculative", 8.0)
        if sma50 and atr:
            return max(round(sma50 - mult * atr, 2), round(price * (1 - trail / 100), 2))
        elif price:
            return round(price * (1 - trail / 100), 2)
    elif intent == "income":
        if sma50 and atr:
            return round(sma50 - atr, 2)
    elif intent == "day_trade":
        if sma20 and atr:
            return round(sma20 - atr, 2)
        elif price:
            return round(price * 0.92, 2)

    # Default: SMA50 conservative
    if sma50:
        return round(sma50 * 0.97, 2)
    return None

# ── Signal change detection ───────────────────────────────────────────────────

def _load_stops(state_dir: Path) -> Dict[str, Dict]:
    p = state_dir / "stops.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _detect_changes(current: Dict, prior: Dict, cookie_ok: bool) -> List[Dict]:
    """
    Detect significant technical signal changes vs prior snapshot.

    Signal types detected:
    ┌───────────────────┬──────────────────────────────────────────────────────┐
    │ Signal            │ Condition                                            │
    ├───────────────────┼──────────────────────────────────────────────────────┤
    │ SMA200_CROSS      │ Price crosses above/below SMA200                     │
    │ GOLDEN_CROSS      │ SMA50 crosses above SMA200                           │
    │ DEATH_CROSS       │ SMA50 crosses below SMA200                           │
    │ RSI_OVERBOUGHT    │ RSI enters ≥70 zone or hits ≥75                      │
    │ RSI_OVERSOLD      │ RSI enters ≤30 zone or hits ≤25                      │
    │ NEAR_52WK_LOW     │ Price within 5% of 52-week low (position > $1K)      │
    │ STOP_TRIGGERED    │ Price at or below set stop level                      │
    └───────────────────┴──────────────────────────────────────────────────────┘

    NOTE: SMA/RSI signals suppressed when cookie_ok=False (stale data).
    STOP_TRIGGERED always fires regardless of data staleness.
    """
    changes = []
    stops = _load_stops(Path("."))

    for sym, curr in current.items():
        if sym not in prior or sym == "_meta":
            continue
        prev  = prior[sym]
        price = curr.get("price", 0)
        mv    = curr.get("market_value", 0)

        # STOP_TRIGGERED — always check, regardless of staleness
        current_stop = stops.get(sym, {}).get("stop")
        if current_stop and price and price <= current_stop:
            changes.append({
                "symbol":       sym,
                "type":         "STOP_TRIGGERED",
                "severity":     "CRITICAL",
                "msg":          f"🚨 {sym} @ ${price:.2f} triggered stop @ ${current_stop:.2f}",
                "market_value": mv,
            })

        # SMA/RSI signals — only when cookie data is fresh
        if not cookie_ok:
            continue

        # SMA200 cross
        prev_above = prev.get("above_sma200")
        curr_above = curr.get("above_sma200")
        if prev_above is not None and curr_above is not None and prev_above != curr_above:
            direction = "crossed ABOVE" if curr_above else "crossed BELOW"
            sma200 = curr.get("sma200", 0)
            changes.append({
                "symbol":       sym,
                "type":         "SMA200_CROSS",
                "severity":     "CRITICAL" if mv > 10000 else "HIGH",
                "msg":          f"{sym} price {direction} SMA200 (${sma200:.2f})",
                "market_value": mv,
            })

        # Golden / Death Cross
        prev_cross = prev.get("cross")
        curr_cross = curr.get("cross")
        if prev_cross != curr_cross and curr_cross in ("golden", "death"):
            changes.append({
                "symbol":       sym,
                "type":         f"{curr_cross.upper()}_CROSS",
                "severity":     "HIGH",
                "msg":          (f"{sym} {'Golden Cross 🌟' if curr_cross=='golden' else 'Death Cross ☠️'} — "
                                 f"SMA50 {'above' if curr_cross=='golden' else 'below'} SMA200"),
                "market_value": mv,
            })

        # RSI extremes
        prev_rsi = prev.get("rsi", 50) or 50
        curr_rsi = curr.get("rsi", 50) or 50
        if abs(curr_rsi - prev_rsi) > 5:
            if (prev_rsi < 70 and curr_rsi >= 70) or curr_rsi >= 75:
                changes.append({
                    "symbol": sym, "type": "RSI_OVERBOUGHT", "severity": "WARNING",
                    "msg": f"{sym} RSI={curr_rsi:.0f} — overbought, consider reducing",
                    "market_value": mv,
                })
            elif (prev_rsi > 30 and curr_rsi <= 30) or curr_rsi <= 25:
                changes.append({
                    "symbol": sym, "type": "RSI_OVERSOLD", "severity": "WARNING",
                    "msg": f"{sym} RSI={curr_rsi:.0f} — oversold, potential bounce",
                    "market_value": mv,
                })

        # Approaching 52-week low
        pct_from_low = curr.get("pct_from_low")
        if pct_from_low is not None and 0 < pct_from_low < 5 and mv > 1000:
            low_price = curr.get("week52_low", 0) or 0
            changes.append({
                "symbol": sym, "type": "NEAR_52WK_LOW", "severity": "HIGH",
                "msg": (f"{sym} within {pct_from_low:.1f}% of 52wk low"
                        + (f" (${price:.2f} / low ${low_price:.2f})" if low_price else "")),
                "market_value": mv,
            })

    return sorted(
        changes,
        key=lambda x: {"CRITICAL": 0, "HIGH": 1, "WARNING": 2}.get(x["severity"], 3)
    )

# ── Holdings resolver ─────────────────────────────────────────────────────────

def _resolve_tickers(portfolio: Dict, fidelity_map: Dict) -> Tuple[Dict[str, Dict], Dict[str, str]]:
    """
    Build holdings map for technical analysis.

    Includes:
      - All Schwab positions > $1,000 MV (excluding revoked/cash/loan)
      - Fidelity positions where internal code has a real ticker mapping
      - Deduplicates: same ticker across multiple accounts → keep highest MV

    Excludes:
      - SKIP_SYMBOLS (revoked, cash, loan, illiquid ARK funds)
      - Fidelity internal codes without ticker mapping
      - Positions < $1,000 market value

    Returns:
      holdings_map: {real_ticker: {symbol, account, price, shares, mv, gain_loss}}
      ticker_aliases: {internal_code: real_ticker}  for display

    Coverage target: ~28 positions vs prior 13
    """
    holdings_map: Dict[str, Dict] = {}
    ticker_aliases: Dict[str, str] = {}

    for h in portfolio.get("holdings", []):
        internal_sym = h.get("symbol", "").upper()
        mv = h.get("market_value", 0) or 0

        if mv < 1000:
            continue
        if h.get("is_loan") or h.get("is_cash"):
            continue
        if internal_sym in SKIP_SYMBOLS:
            continue

        # Resolve ticker — Fidelity internal codes → real tickers
        real_ticker = internal_sym
        is_fidelity_internal = any(internal_sym.startswith(p) for p in FIDELITY_PREFIXES)

        if is_fidelity_internal:
            mapped = fidelity_map.get(internal_sym)
            if not mapped:
                continue  # No mapping — skip
            real_ticker = mapped
            ticker_aliases[internal_sym] = real_ticker

        # Deduplicate: same real ticker in multiple accounts → keep highest MV
        if real_ticker not in holdings_map or holdings_map[real_ticker]["market_value"] < mv:
            holdings_map[real_ticker] = {
                "symbol":       real_ticker,
                "internal_sym": internal_sym,
                "account":      h.get("account_display", h.get("account", "")),
                "price":        h.get("price", 0),
                "shares":       h.get("shares", 0),
                "market_value": mv,
                "gain_loss":    h.get("gain_loss", 0),
                "is_fidelity":  is_fidelity_internal,
            }

    return holdings_map, ticker_aliases

# ── Main entry point ──────────────────────────────────────────────────────────

def run_technical_analysis(portfolio: Dict, root: Path, state_dir: Path) -> Dict:
    """
    Main entry point for portfolio_orchestrator.py.

    Execution flow:
    ┌─────────────────────────────────────────────────────────────────────────┐
    │ Step 1: Load config (intent map, Fidelity ticker map, stops, prior)      │
    │ Step 2: Resolve tickers from all 4 accounts (~28 positions)              │
    │ Step 3: TIER 1 — API token batch (price, analyst, performance)           │
    │ Step 4: TIER 2 — Cookie scrape (RSI, SMA, ATR, 52wk) with health check  │
    │         └── On failure: send Telegram alert, set cookie_ok=False         │
    │ Step 5: Merge Tier 1 + Tier 2 data per ticker                           │
    │         └── If cookie_ok=False: use prior snapshot values for SMA/RSI   │
    │ Step 6: Derive indicators (BB, MACD, crosses, score)                     │
    │ Step 7: Detect signal changes vs prior snapshot                          │
    │ Step 8: Save snapshot with metadata (timestamp, cookie_ok flag)          │
    │ Step 9: Return results dict                                               │
    └─────────────────────────────────────────────────────────────────────────┘

    Returns dict with keys:
        positions          — {ticker: full technical data dict}
        signal_changes     — list of detected signal changes
        portfolio_score    — 0-100 weighted composite score
        portfolio_grade    — green/yellow/red
        analyzed_count     — number of positions analyzed
        critical_signals   — filtered CRITICAL severity changes
        high_signals       — filtered HIGH severity changes
        last_updated       — datetime string
        tickers_analyzed   — list of tickers
        cookie_ok          — bool: was cookie valid this run?
        data_age_days      — float: how old is the technical data
    """
    _load_env_file(root)

    # ── Step 1: Load config ───────────────────────────────────────────────────
    intent_map  = load_intent(root)
    fidelity_map = load_fidelity_ticker_map(root)
    intent_cfg  = {}
    try:
        intent_cfg = yaml.safe_load(
            (root / "assets" / "portfolio_intent.yaml").read_text()
        ) or {}
    except Exception:
        pass

    stops = _load_stops(state_dir)
    prior = _load_prior_snapshot(state_dir)

    # ── Step 2: Resolve tickers ───────────────────────────────────────────────
    holdings_map, ticker_aliases = _resolve_tickers(portfolio, fidelity_map)
    tickers = sorted(holdings_map.keys())

    print(f"  [technical] Analyzing {len(tickers)} positions via Finviz Elite...")
    if ticker_aliases:
        mapped_display = ", ".join(f"{k}→{v}" for k, v in list(ticker_aliases.items())[:5])
        print(f"  [technical] Fidelity mapped: {mapped_display}"
              + (f" + {len(ticker_aliases)-5} more" if len(ticker_aliases) > 5 else ""))

    # ── Step 3: Tier 1 — API token ────────────────────────────────────────────
    api_data = _finviz_api_batch(tickers, root)

    # ── Step 3.5: Tier 1.5 — Finviz enrichment (RSI/SMA via v=171, no cookie) ──
    enrichment_data = {}
    try:
        import sys as _sys
        _sys.path.insert(0, str(root / "scripts"))
        from finviz_enrichment import enrich_tickers as _enrich
        _syms = [s for s in tickers if s not in MUTUAL_FUND_TICKERS]
        _enriched = _enrich(_syms, project_root=str(root), skip_fundamentals=True)
        for sym, e in _enriched.items():
            if e.get("rsi") is not None:
                enrichment_data[sym] = {
                    "rsi":         e.get("rsi"),
                    "sma20_pct":   e.get("sma20_pct"),
                    "sma50_pct":   e.get("sma50_pct"),
                    "sma200_pct":  e.get("sma200_pct"),
                    "52wk_high":   e.get("week52_high_pct"),
                    "52wk_low":    e.get("week52_low_pct"),
                    "atr":         e.get("atr"),
                    "beta":        e.get("beta"),
                }
        print(f"  [technical] Enrichment v=171: {len(enrichment_data)} tickers with RSI/SMA")
    except Exception as _e:
        print(f"  [technical] Enrichment fallback: {_e}")

    # ── Step 4: Tier 2 — Cookie scrape (fallback if enrichment missing data) ──
    # Only scrape tickers that enrichment didn't cover
    missing = [s for s in tickers if s not in enrichment_data and s not in MUTUAL_FUND_TICKERS]
    if missing:
        cookie_data_raw, cookie_ok = _finviz_cookie_batch(missing, root, state_dir, prior)
    else:
        cookie_data_raw, cookie_ok = {}, True
    # Merge: enrichment takes priority, cookie fills gaps
    cookie_data = {**cookie_data_raw, **enrichment_data}

    if not cookie_ok and not enrichment_data:
        print("  [technical] Using prior snapshot for RSI/SMA/ATR (cookie unavailable)")
        # Backfill from prior snapshot
        for sym in tickers:
            if sym in prior and sym != "_meta":
                p = prior[sym]
                cookie_data[sym] = {
                    k: p.get(k) for k in [
                        "rsi", "sma20_pct", "sma50_pct", "sma200_pct",
                        "52wk_high", "52wk_low", "atr", "beta"
                    ]
                }

    # ── Step 5: Merge data ────────────────────────────────────────────────────
    results: Dict[str, Dict] = {}

    for sym in tickers:
        h    = holdings_map[sym]
        data = {}

        # Start with API data (Tier 1)
        if sym in api_data:
            data.update(api_data[sym])

        # Overlay cookie data (Tier 2 or backfilled from snapshot)
        if sym in cookie_data:
            data.update(cookie_data[sym])

        # Always inject portfolio context
        data["symbol"]       = sym
        data["market_value"] = h["market_value"]
        data["shares"]       = h["shares"]
        data["account"]      = h["account"]
        data["gain_loss"]    = h["gain_loss"]
        data["is_fidelity"]  = h["is_fidelity"]

        # Use portfolio price as fallback
        if not data.get("price"):
            data["price"] = h["price"]

        # ── Step 6: Derive indicators ─────────────────────────────────────────
        data = _derive_indicators(data, h["price"])

        # Intent classification
        data["intent"] = intent_map.get(sym, "unclassified")

        # Stop suggestion
        data["suggested_stop"] = _suggest_stop(data, data["intent"], intent_cfg)

        # Compare to current stop
        current_stop = stops.get(sym, {}).get("stop")
        data["current_stop"] = current_stop
        if current_stop and data.get("suggested_stop"):
            gap = abs(current_stop - data["suggested_stop"]) / data["suggested_stop"] * 100
            data["stop_gap_pct"]       = round(gap, 1)
            data["stop_needs_update"]  = gap > 15
        else:
            data["stop_gap_pct"]      = None
            data["stop_needs_update"] = current_stop is None

        # Cookie status flag for dashboard
        data["cookie_ok"] = cookie_ok

        results[sym] = data

    # ── Step 7: Detect signal changes ────────────────────────────────────────
    signal_changes = _detect_changes(results, prior, cookie_ok)

    # ── Step 8: Portfolio score ───────────────────────────────────────────────
    total_mv = sum(d.get("market_value", 0) for d in results.values())
    weighted_score = (
        sum(d.get("tech_score", 50) * d.get("market_value", 0) for d in results.values())
        / total_mv if total_mv else 50
    )

    # ── Step 9: Save snapshot ─────────────────────────────────────────────────
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    snapshot = dict(results)
    snapshot["_meta"] = {
        "last_updated":  now_str,
        "cookie_ok":     cookie_ok,
        "analyzed_count": len(results),
        "tickers":       tickers,
    }
    _save_snapshot(snapshot, state_dir)

    # Data age calculation
    age_hours = _snapshot_age_hours(prior)
    data_age_days = round(age_hours / 24, 1) if age_hours is not None else None

    grade_label = "green" if weighted_score >= 70 else ("yellow" if weighted_score >= 40 else "red")
    print(f"  [technical] ✅ {len(results)} positions | score={weighted_score:.0f} | "
          f"cookie={'✅' if cookie_ok else '⚠️ expired'} | "
          f"{len(signal_changes)} signals")

    return {
        "positions":        results,
        "signal_changes":   signal_changes,
        "portfolio_score":  round(weighted_score, 1),
        "portfolio_grade":  grade_label,
        "analyzed_count":   len(results),
        "critical_signals": [c for c in signal_changes if c["severity"] == "CRITICAL"],
        "high_signals":     [c for c in signal_changes if c["severity"] == "HIGH"],
        "last_updated":     now_str,
        "tickers_analyzed": tickers,
        "cookie_ok":        cookie_ok,
        "data_age_days":    data_age_days,
        "fidelity_mapped":  len(ticker_aliases),
    }
