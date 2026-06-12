#!/usr/bin/env python3
"""secret_validators.py — live provider validation for API keys (operator request 2026-06-12).

Born from a real failure: a dead ANTHROPIC_API_KEY showed "set" (green) in admin while every Claude
call 401'd silently for weeks. "Set" only means written to .env — THIS module asks the PROVIDER.

Design rules:
  • Key material is read server-side (env → .env fallback) and NEVER returned, logged, or echoed.
  • Each validator is the CHEAPEST authenticated call the provider offers (models/getMe/quote-style
    endpoints; zero or negligible quota). Brave consumes 1 search credit — noted in the result.
  • Fail honest: timeouts/network errors report check_failed, never valid.
  • Schwab app key/secret are NOT validatable statelessly (OAuth dance) — reported as such.

  python3 scripts/secret_validators.py [NAME ...]      # CLI: validate one/all known keys
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 12


def _key(name: str) -> str | None:
    import os
    v = os.getenv(name, "").strip()
    if v:
        return v
    try:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    except Exception:
        pass
    return None


def _get(url, headers=None):
    import requests
    return requests.get(url, headers=headers or {}, timeout=TIMEOUT)


def _ok(r, judge=None):
    if judge:
        return judge(r)
    return 200 <= r.status_code < 300


# name -> callable(key) -> (valid: bool|None, detail: str). None = cannot validate.
def _anthropic(k):
    r = _get("https://api.anthropic.com/v1/models",
             {"x-api-key": k, "anthropic-version": "2023-06-01"})
    return _ok(r), f"HTTP {r.status_code}"


def _openai(k):
    r = _get("https://api.openai.com/v1/models", {"Authorization": f"Bearer {k}"})
    return _ok(r), f"HTTP {r.status_code}"


def _xai(k):
    r = _get("https://api.x.ai/v1/models", {"Authorization": f"Bearer {k}"})
    return _ok(r), f"HTTP {r.status_code}"


def _gemini(k):
    r = _get(f"https://generativelanguage.googleapis.com/v1beta/models?key={k}&pageSize=1")
    return _ok(r), f"HTTP {r.status_code}"


def _telegram(k):
    r = _get(f"https://api.telegram.org/bot{k}/getMe")
    ok = r.status_code == 200 and r.json().get("ok") is True
    return ok, f"HTTP {r.status_code}" + (f" @{r.json()['result'].get('username')}" if ok else "")


def _finnhub(k):
    r = _get(f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={k}")
    return _ok(r), f"HTTP {r.status_code}"


def _fmp(k):
    r = _get(f"https://financialmodelingprep.com/api/v3/stock/list?limit=1&apikey={k}")
    bad = r.status_code in (401, 403)
    return (not bad and r.status_code == 200), f"HTTP {r.status_code}"


def _fred(k):
    r = _get(f"https://api.stlouisfed.org/fred/series?series_id=GNPCA&api_key={k}&file_type=json")
    return _ok(r), f"HTTP {r.status_code}"


def _polygon(k):
    r = _get(f"https://api.polygon.io/v3/reference/tickers?limit=1&apiKey={k}")
    return _ok(r), f"HTTP {r.status_code}"


def _newsapi(k):
    r = _get(f"https://newsapi.org/v2/top-headlines?country=us&pageSize=1&apiKey={k}")
    return _ok(r), f"HTTP {r.status_code}"


def _alphavantage(k):
    r = _get(f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=AAPL&apikey={k}")
    body = r.json() if r.status_code == 200 else {}
    if "Error Message" in body or "Information" in body and "rate limit" not in str(body).lower():
        return False, "rejected by provider"
    return r.status_code == 200, f"HTTP {r.status_code}"


def _brave(k):
    r = _get("https://api.search.brave.com/res/v1/web/search?q=test&count=1",
             {"X-Subscription-Token": k})
    note = " (consumed 1 search credit)" if r.status_code == 200 else ""
    if r.status_code == 429:
        return True, "HTTP 429 — key valid, quota exhausted"
    return _ok(r), f"HTTP {r.status_code}{note}"


def _youtube(k):
    r = _get(f"https://www.googleapis.com/youtube/v3/videos?part=id&chart=mostPopular&maxResults=1&key={k}")
    return _ok(r), f"HTTP {r.status_code}"


def _twocaptcha(k):
    r = _get(f"https://2captcha.com/res.php?key={k}&action=getbalance&json=1")
    ok = r.status_code == 200 and r.json().get("status") == 1
    return ok, ("balance OK" if ok else f"provider says: {r.json().get('request', r.status_code)}")


def _alpaca(k):
    sec = _key("ALPACA_SECRET_KEY")
    if not sec:
        return None, "needs ALPACA_SECRET_KEY too"
    r = _get("https://paper-api.alpaca.markets/v2/account",
             {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": sec})
    return _ok(r), f"HTTP {r.status_code} (paper endpoint)"


VALIDATORS = {
    "ANTHROPIC_API_KEY": _anthropic, "OPENAI_API_KEY": _openai, "XAI_API_KEY": _xai,
    "GEMINI_API_KEY": _gemini, "TELEGRAM_BOT_TOKEN": _telegram, "FINNHUB_API_KEY": _finnhub,
    "FMP_API_KEY": _fmp, "FRED_API_KEY": _fred, "POLYGON_API_KEY": _polygon,
    "NEWSAPI_KEY": _newsapi, "ALPHA_VANTAGE_API_KEY": _alphavantage,
    "BRAVE_SEARCH_API_KEY": _brave, "YOUTUBE_API_KEY": _youtube,
    "TWOCAPTCHA_API_KEY": _twocaptcha, "ALPACA_API_KEY": _alpaca,
}
NOT_VALIDATABLE = {
    "SCHWAB_APP_KEY": "OAuth flow required — proven by live reads (System→Brokers token health)",
    "SCHWAB_APP_SECRET": "OAuth flow required — proven by live reads",
    "ALPACA_SECRET_KEY": "validated as a pair via ALPACA_API_KEY",
    "DB_PASSWORD": "validated implicitly — this dashboard is reading the DB right now",
    "ADMIN_WRITE_TOKEN": "internal token — validated on every guarded config write",
    "SMTP_PASSWORD": "validated on next email send (no harmless ping available)",
    "TWILIO_AUTH_TOKEN": "validated on next SMS send",
    "FINVIZ_API_TOKEN": "elite-export token — validated by the nightly finviz_enrichment run",
    "FINVIZ_COOKIE": "session cookie — validated by the nightly finviz_enrichment run",
}


def validate(name: str) -> dict:
    name = (name or "").strip().upper()
    if name in NOT_VALIDATABLE:
        return {"name": name, "status": "not_validatable", "detail": NOT_VALIDATABLE[name]}
    fn = VALIDATORS.get(name)
    if not fn:
        return {"name": name, "status": "unknown_key", "detail": "no validator registered for this name"}
    k = _key(name)
    if not k:
        return {"name": name, "status": "not_set", "detail": "no value in env/.env"}
    try:
        ok, detail = fn(k)
        if ok is None:
            return {"name": name, "status": "not_validatable", "detail": detail}
        # 402/429 = the provider RECOGNIZED the key but quota/billing blocks it — distinct from invalid
        if not ok and ("402" in detail or "429" in detail):
            return {"name": name, "status": "quota_or_billing",
                    "detail": detail + " — key recognized; plan/quota issue, not an auth failure"}
        return {"name": name, "status": "valid" if ok else "INVALID", "detail": detail}
    except Exception as e:
        return {"name": name, "status": "check_failed", "detail": str(e)[:120]}


if __name__ == "__main__":
    names = [a.upper() for a in sys.argv[1:]] or sorted(VALIDATORS)
    for n in names:
        r = validate(n)
        print(f"{r['status']:>16}  {n:26} {r['detail']}")
