#!/usr/bin/env python3
"""credential_monitor.py — Monitor API keys and cookies for expiry/failure.

Checks all credentials, sends Telegram alert on failure, and accepts
Telegram replies to update .env credentials.

Usage:
    python3 scripts/credential_monitor.py --check      # Check all credentials
    python3 scripts/credential_monitor.py --check --telegram  # Check + alert on failure
    python3 scripts/credential_monitor.py --update KEY VALUE  # Update .env key

Cron: runs daily at 6:00 AM (before any data pipeline starts)
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _env(key: str) -> str:
    """tmpfs SM render → os.environ → disk .env (never logs values)."""
    try:
        _sec = PROJECT_ROOT / "scripts" / "secrets"
        if str(_sec) not in sys.path:
            sys.path.insert(0, str(_sec))
        from resolve_secret import resolve_secret
        return resolve_secret(key, "")
    except Exception:
        try:
            for line in (PROJECT_ROOT / ".env").read_text().splitlines():
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except Exception:
            pass
        return os.getenv(key, "").strip()


def _send_tg(msg: str):
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception:
        pass


def _get_conn():
    import psycopg2
    pw = _env("DB_PASSWORD")
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def check_finviz() -> dict:
    """Check Finviz cookie validity."""
    cookie = _env("FINVIZ_COOKIE")
    if not cookie:
        return {"name": "Finviz", "status": "missing", "error": "FINVIZ_COOKIE not set in .env"}
    try:
        url = "https://elite.finviz.com/export?v=152&f=sh_price_u5&ft=3&c=0,1,65&o=-price"
        # Credential probe: still throttled, but a short wait so monitoring
        # reports rather than hangs behind a bulk consumer.
        import finviz_throttle
        finviz_throttle.acquire(timeout=30)
        req = urllib.request.Request(url, headers={
            "Cookie": cookie, "User-Agent": "Mozilla/5.0"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("utf-8", errors="ignore")
            if "Ticker" in data and len(data) > 50:
                return {"name": "Finviz", "status": "ok", "detail": f"{len(data)} bytes"}
            if "login" in data.lower() or "sign in" in data.lower():
                return {"name": "Finviz", "status": "expired", "error": "Cookie expired — login page returned"}
            return {"name": "Finviz", "status": "error", "error": f"Unexpected response ({len(data)} bytes)"}
    except urllib.error.HTTPError as e:
        return {"name": "Finviz", "status": "error", "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"name": "Finviz", "status": "error", "error": str(e)}


def check_youtube_cookie() -> dict:
    """Check YouTube cookie validity."""
    cookie_path = PROJECT_ROOT / "config" / "youtube_cookies.txt"
    if not cookie_path.exists():
        return {"name": "YouTube Cookie", "status": "missing", "error": "config/youtube_cookies.txt not found"}
    try:
        import http.cookiejar
        jar = http.cookiejar.MozillaCookieJar(str(cookie_path))
        jar.load(ignore_discard=True, ignore_expires=True)
        auth_names = {"SID", "HSID", "SSID", "LOGIN_INFO", "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PAPISID", "__Secure-3PAPISID"}
        auth_cookies = [c for c in jar if c.name in auth_names]
        if not auth_cookies:
            return {"name": "YouTube Cookie", "status": "expired", "error": "No auth cookies — re-export from browser"}
        # Check cookie file age
        age_days = (datetime.now() - datetime.fromtimestamp(cookie_path.stat().st_mtime)).days
        if age_days > 14:
            return {"name": "YouTube Cookie", "status": "warning", "error": f"Cookie file is {age_days} days old — may need refresh"}
        return {"name": "YouTube Cookie", "status": "ok", "detail": f"{len(auth_cookies)} auth cookies, {age_days}d old"}
    except Exception as e:
        return {"name": "YouTube Cookie", "status": "error", "error": str(e)}


def check_youtube_api() -> dict:
    """Check YouTube Data API key."""
    key = _env("YOUTUBE_API_KEY")
    if not key:
        return {"name": "YouTube API", "status": "missing", "error": "YOUTUBE_API_KEY not set"}
    try:
        url = f"https://www.googleapis.com/youtube/v3/search?part=id&q=test&maxResults=1&key={key}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if "items" in data:
                return {"name": "YouTube API", "status": "ok"}
            return {"name": "YouTube API", "status": "error", "error": "Unexpected response"}
    except urllib.error.HTTPError as e:
        if e.code == 403:
            body = json.loads(e.read())
            reason = body.get("error", {}).get("errors", [{}])[0].get("reason", "")
            if reason == "quotaExceeded":
                return {"name": "YouTube API", "status": "quota", "error": "Daily quota exceeded — resets at midnight PT"}
            return {"name": "YouTube API", "status": "error", "error": f"403: {reason}"}
        return {"name": "YouTube API", "status": "error", "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"name": "YouTube API", "status": "error", "error": str(e)}


def check_fred() -> dict:
    """Check FRED API key."""
    key = _env("FRED_API_KEY")
    if not key:
        return {"name": "FRED", "status": "missing", "error": "FRED_API_KEY not set"}
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFF&api_key={key}&file_type=json&sort_order=desc&limit=1"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("observations"):
                return {"name": "FRED", "status": "ok", "detail": f"DFF={data['observations'][0].get('value')}"}
        return {"name": "FRED", "status": "error", "error": "No observations returned"}
    except Exception as e:
        return {"name": "FRED", "status": "error", "error": str(e)}


def check_brave() -> dict:
    """Check Brave Search API."""
    key = _env("BRAVE_SEARCH_API_KEY")
    if not key:
        return {"name": "Brave Search", "status": "missing", "error": "BRAVE_SEARCH_API_KEY not set"}
    # Counted, never denied — see secret_validators._brave. A liveness probe
    # consumes a real credit, so it must reach the ledger; denying it would
    # report a healthy key as dead, which is the worse failure.
    try:
        from scripts.lib.search_budget import note as _sb_note
        _sb_note("brave", "credential_monitor")
    except Exception:
        pass
    try:
        url = "https://api.search.brave.com/res/v1/web/search?q=test&count=1"
        req = urllib.request.Request(url, headers={
            "X-Subscription-Token": key, "Accept": "application/json"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"name": "Brave Search", "status": "ok"}
    except urllib.error.HTTPError as e:
        if e.code == 402:
            return {"name": "Brave Search", "status": "expired", "error": "402 — Usage limit. Add $5 credit at search.brave.com/account"}
        return {"name": "Brave Search", "status": "error", "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"name": "Brave Search", "status": "error", "error": str(e)}


def check_finnhub() -> dict:
    """Check Finnhub API key."""
    key = _env("FINNHUB_API_KEY")
    if not key:
        return {"name": "Finnhub", "status": "missing", "error": "FINNHUB_API_KEY not set"}
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={key}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("c", 0) > 0:
                return {"name": "Finnhub", "status": "ok", "detail": f"AAPL=${data['c']}"}
        return {"name": "Finnhub", "status": "error", "error": "No quote data"}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"name": "Finnhub", "status": "expired", "error": "401 — API key invalid or expired"}
        return {"name": "Finnhub", "status": "error", "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"name": "Finnhub", "status": "error", "error": str(e)}


def check_fmp() -> dict:
    """Check FMP API key."""
    key = _env("FMP_API_KEY")
    if not key:
        return {"name": "FMP", "status": "missing", "error": "FMP_API_KEY not set"}
    try:
        url = f"https://financialmodelingprep.com/api/v3/quote-short/AAPL?apikey={key}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            if isinstance(data, list) and len(data) > 0:
                return {"name": "FMP", "status": "ok", "detail": f"AAPL=${data[0].get('price',0)}"}
        return {"name": "FMP", "status": "error", "error": "Empty response"}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"name": "FMP", "status": "expired", "error": f"HTTP {e.code} — key invalid"}
        return {"name": "FMP", "status": "error", "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"name": "FMP", "status": "error", "error": str(e)}


def check_alpha_vantage() -> dict:
    """Check Alpha Vantage API key."""
    key = _env("ALPHA_VANTAGE_API_KEY")
    if not key:
        return {"name": "Alpha Vantage", "status": "missing", "error": "ALPHA_VANTAGE_API_KEY not set"}
    try:
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=AAPL&apikey={key}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("Global Quote", {}).get("05. price"):
                return {"name": "Alpha Vantage", "status": "ok"}
            if "Note" in data or "Information" in data:
                return {"name": "Alpha Vantage", "status": "quota", "error": "Rate limited — 5 calls/min"}
        return {"name": "Alpha Vantage", "status": "error", "error": "No quote data"}
    except Exception as e:
        return {"name": "Alpha Vantage", "status": "error", "error": str(e)}


def check_db() -> dict:
    """Check database connectivity."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
        count = cur.fetchone()[0]
        conn.close()
        return {"name": "PostgreSQL", "status": "ok", "detail": f"{count} tables"}
    except Exception as e:
        return {"name": "PostgreSQL", "status": "error", "error": str(e)}


def check_ollama() -> dict:
    """Check Ollama LLM server."""
    try:
        from local_llm_config import get_local_llm_base_url
        url = get_local_llm_base_url().rstrip("/") + "/api/tags"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return {"name": "Ollama", "status": "ok", "detail": ", ".join(models)}
    except Exception as e:
        return {"name": "Ollama", "status": "error", "error": str(e)}


ALL_CHECKS = [
    check_finviz, check_youtube_cookie, check_youtube_api,
    check_fred, check_brave, check_finnhub, check_fmp,
    check_alpha_vantage, check_db, check_ollama,
]

ENV_KEY_MAP = {
    "Finviz": "FINVIZ_COOKIE",
    "YouTube API": "YOUTUBE_API_KEY",
    "FRED": "FRED_API_KEY",
    "Brave Search": "BRAVE_SEARCH_API_KEY",
    "Finnhub": "FINNHUB_API_KEY",
    "FMP": "FMP_API_KEY",
    "Alpha Vantage": "ALPHA_VANTAGE_API_KEY",
}


def run_checks(send_telegram: bool = False) -> list:
    """Run all credential checks. Alert on failures."""
    results = []
    failures = []

    for check_fn in ALL_CHECKS:
        r = check_fn()
        results.append(r)
        status_icon = {"ok": "✅", "warning": "⚠️", "expired": "🔴", "missing": "⬜", "error": "❌", "quota": "🟡"}.get(r["status"], "❓")
        print(f"  {status_icon} {r['name']}: {r['status']}" + (f" — {r.get('detail', r.get('error', ''))}" if r.get('detail') or r.get('error') else ""))

        if r["status"] in ("expired", "error", "missing"):
            failures.append(r)

    if failures and send_telegram:
        lines = ["🔑 *Credential Health Check*", ""]
        for r in results:
            icon = {"ok": "✅", "warning": "⚠️", "expired": "🔴", "missing": "⬜", "error": "❌", "quota": "🟡"}.get(r["status"], "❓")
            lines.append(f"{icon} *{r['name']}*: {r['status']}")
            if r.get("error"):
                lines.append(f"   _{r['error']}_")

        lines.append("")
        lines.append("*To update a credential, reply:*")
        for f in failures:
            env_key = ENV_KEY_MAP.get(f["name"])
            if env_key:
                lines.append(f"`update {env_key} YOUR_NEW_VALUE`")

        _send_tg("\n".join(lines))

    ok_count = sum(1 for r in results if r["status"] in ("ok", "quota", "warning"))
    fail_count = len(failures)
    print(f"\n  Summary: {ok_count} OK, {fail_count} failed")
    return results


def update_env_key(key: str, value: str) -> bool:
    """Update a key in .env file. Returns True on success."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return False

    lines = env_path.read_text().splitlines()
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n")
    print(f"  [credential] Updated {key} in .env")
    return True


if __name__ == "__main__":
    if "--check" in sys.argv:
        tg = "--telegram" in sys.argv
        print("=== Credential Health Check ===\n")
        run_checks(send_telegram=tg)
    elif "--update" in sys.argv:
        idx = sys.argv.index("--update")
        if idx + 2 < len(sys.argv):
            key = sys.argv[idx + 1]
            value = sys.argv[idx + 2]
            if update_env_key(key, value):
                print(f"Updated {key}")
                _send_tg(f"✅ Credential updated: `{key}` — restart services to apply")
            else:
                print("Failed to update")
        else:
            print("Usage: --update KEY VALUE")
    else:
        print("Usage:")
        print("  --check [--telegram]     Check all credentials")
        print("  --update KEY VALUE       Update .env credential")
