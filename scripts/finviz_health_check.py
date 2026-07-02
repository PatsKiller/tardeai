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

def check():
    """Check Finviz health. Returns dict with status."""
    result = {"source_key": "finviz", "status": "unknown", "row_count": 0, "error": None}

    # Check credentials exist (redacted)
    cookie = _env("FINVIZ_COOKIE", "")
    token = _env("FINVIZ_API_TOKEN", "")
    if not cookie and not token:
        result["status"] = "error"
        result["error"] = "No FINVIZ_COOKIE or FINVIZ_API_TOKEN in .env"
        return result

    result["has_cookie"] = bool(cookie)
    result["has_token"] = bool(token)

    # Try a lightweight screener check
    try:
        import urllib.request
        # Use a minimal Finviz export URL to test connectivity
        test_url = "https://elite.finviz.com/export?v=152&f=sh_price_u5&ft=3&c=0,1,65&o=-price"
        ua = _env("FINVIZ_USER_AGENT") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        real_headers = {"User-Agent": ua, "Accept": "text/csv,*/*", "Referer": "https://elite.finviz.com/"}
        if cookie:
            real_headers["Cookie"] = cookie

        req = urllib.request.Request(test_url, headers=real_headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            lines = [l for l in data.strip().split("\n") if l.strip()]
            row_count = max(0, len(lines) - 1)  # minus header

            if row_count > 0 and "Ticker" in data[:400]:
                result["status"] = "healthy"
                result["row_count"] = row_count
                print(f"  [finviz] Healthy: {row_count} rows returned")
            else:
                result["status"] = "degraded"
                result["error"] = "Zero rows returned — cookie may be expired"
                print(f"  [finviz] DEGRADED: 0 rows (cookie expired?)")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:200]
        print(f"  [finviz] ERROR: {e}")

    # Record to DB
    try:
        conn = _get_conn()
        cur = conn.cursor()
        if result["status"] == "healthy":
            cur.execute("""
                UPDATE data_source_health SET status='healthy', last_success_at=NOW(),
                    last_row_count=%s, failure_count=0, degraded=false, last_error=NULL, updated_at=NOW()
                WHERE source_key='finviz'
            """, (result["row_count"],))
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
