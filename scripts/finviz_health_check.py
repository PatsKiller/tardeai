#!/usr/bin/env python3
"""
finviz_health_check.py — Check Finviz availability and record health.

Usage:
    python finviz_health_check.py
    python finviz_health_check.py --telegram
"""
import argparse, json, os, sys, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

def _env(key, default=""):
    """tmpfs SM render → os.environ → disk .env (never logs values)."""
    try:
        _sec = PROJECT_ROOT / "scripts" / "secrets"
        if str(_sec) not in sys.path:
            sys.path.insert(0, str(_sec))
        from resolve_secret import resolve_secret
        return resolve_secret(key, default if default is not None else "")
    except Exception:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.strip().startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        return os.getenv(key, default)

def _get_conn():
    import psycopg2
    return psycopg2.connect(host="localhost", dbname="trade_ai",
                            user="trade_ai", password=_env("DB_PASSWORD"))

TEST_URL = "https://elite.finviz.com/export?v=152&f=sh_price_u5&ft=3&c=0,1,65&o=-price"


def _probe(url, headers):
    """(row_count, error) for one export request; error is None on a real CSV."""
    import urllib.request
    import finviz_throttle
    finviz_throttle.acquire(timeout=30)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    lines = [l for l in data.strip().split("\n") if l.strip()]
    rows = max(0, len(lines) - 1)
    if rows > 0 and "Ticker" in data[:400]:
        return rows, None
    return 0, "zero rows / login page"


def check(probe=None):
    """Check Finviz health: cookie first, then the Elite API token. Returns dict with status."""
    from finviz_auth import redact, with_auth_token

    probe = probe or _probe
    result = {"source_key": "finviz", "status": "unknown", "row_count": 0, "error": None,
              "credential": None}

    cookie = _env("FINVIZ_COOKIE", "")
    token = _env("FINVIZ_API_TOKEN", "")
    if not cookie and not token:
        result["status"] = "error"
        result["error"] = "No FINVIZ_COOKIE or FINVIZ_API_TOKEN in .env"
        return result

    result["has_cookie"] = bool(cookie)
    result["has_token"] = bool(token)
    ua = _env("FINVIZ_USER_AGENT") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    base = {"User-Agent": ua, "Accept": "text/csv,*/*", "Referer": "https://elite.finviz.com/"}

    attempts = []
    if cookie:
        attempts.append(("cookie", TEST_URL, {**base, "Cookie": cookie}))
    if token:
        attempts.append(("token", with_auth_token(TEST_URL, token), dict(base)))

    notes = []
    for name, url, headers in attempts:
        try:
            rows, err = probe(url, headers)
        except Exception as e:
            rows, err = 0, redact(e, cookie, token)[:160]
        if err is None:
            result.update(status="healthy", row_count=rows, credential=name)
            if notes:
                # Informational: the source works, but the cookie needs rotating eventually.
                result["error"] = "; ".join(notes + [f"{name} OK"])
            print(f"  [finviz] Healthy via {name}: {rows} rows" + (f" ({'; '.join(notes)})" if notes else ""))
            break
        notes.append(f"{name} failed: {err}")
    else:
        result["status"] = "degraded"
        result["error"] = "; ".join(notes) or "no credential attempted"
        print(f"  [finviz] DEGRADED: {result['error']}")

    # Record to DB
    try:
        conn = _get_conn()
        cur = conn.cursor()
        if result["status"] == "healthy":
            cur.execute("""
                UPDATE data_source_health SET status='healthy', last_success_at=NOW(),
                    last_row_count=%s, failure_count=0, degraded=false, last_error=%s, updated_at=NOW()
                WHERE source_key='finviz'
            """, (result["row_count"], result.get("error")))
        else:
            cur.execute("""
                UPDATE data_source_health SET status=%s, last_failure_at=NOW(),
                    failure_count=failure_count+1, degraded=true, last_error=%s, updated_at=NOW()
                WHERE source_key='finviz'
            """, (result["status"], result.get("error")))
        conn.commit()
        conn.close()
    except Exception:
        pass

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = check()

    if args.json:
        # Redact secrets
        r = {k: v for k, v in result.items() if k not in ("has_cookie", "has_token")}
        print(json.dumps(r, indent=2))

    if args.telegram and result["status"] != "healthy":
        try:
            from telegram_alert import send_telegram
            send_telegram(f"Finviz Health: {result['status']} — {result.get('error', 'unknown')}")
        except Exception:
            pass

    sys.exit(0 if result["status"] == "healthy" else 1)


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
