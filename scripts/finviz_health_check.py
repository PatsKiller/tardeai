#!/usr/bin/env python3
"""
finviz_health_check.py — Check Finviz availability and record health.

Usage:
    python finviz_health_check.py
    python finviz_health_check.py --telegram
    python finviz_health_check.py --dry-run     # read-only: no probe, no DB write, no send, no receipt

n8n refactor (2026-10-10, wave 1):
- ``--dry-run`` reports which credentials would be tried, in what order, the current
  data_source_health row (read-only SELECT) and the UPDATE each outcome would run. It never calls
  the export probe (each probe advances the shared finviz_throttle state file and spends a Finviz
  request), never opens a write, never sends (AGENTS.md §6: the dry-run branch is ``plan()``, a
  different function; ``check()`` is not reachable from it).
- A real run writes ``<state_root>/data/runtime/finviz_health_check_last.json`` (LaneRunReceipt@v1;
  ``ok_at`` only when the probe was healthy AND the health row was recorded).
- Exit: 0 healthy and recorded; 1 degraded (unchanged); 3 the health row could not be recorded
  (previously swallowed by a bare ``except: pass``, so the registry's db_max signal froze silently).
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
            cur.execute(SQL_HEALTHY, (result["row_count"], result.get("error")))
        else:
            cur.execute(SQL_DEGRADED, (result["status"], result.get("error")))
        rowcount = getattr(cur, "rowcount", -1)
        conn.commit()
        conn.close()
        # rowcount 0 = no 'finviz' row: the UPDATE succeeded and recorded nothing.
        result["recorded"] = rowcount != 0
        if rowcount == 0:
            result["record_error"] = "no data_source_health row for source_key='finviz'"
    except Exception as exc:  # noqa: BLE001 -- reported, no longer swallowed (exit 3)
        result["recorded"] = False
        result["record_error"] = type(exc).__name__

    return result


SQL_HEALTHY = """
                UPDATE data_source_health SET status='healthy', last_success_at=NOW(),
                    last_row_count=%s, failure_count=0, degraded=false, last_error=%s, updated_at=NOW()
                WHERE source_key='finviz'
            """
SQL_DEGRADED = """
                UPDATE data_source_health SET status=%s, last_failure_at=NOW(),
                    failure_count=failure_count+1, degraded=true, last_error=%s, updated_at=NOW()
                WHERE source_key='finviz'
            """


def _read_health_row():
    """Current finviz data_source_health row, via a READ ONLY transaction. None when unreadable."""
    try:
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN READ ONLY")
            cur.execute("SELECT status, last_success_at, last_failure_at, failure_count, degraded, updated_at"
                        " FROM data_source_health WHERE source_key='finviz'")
            row = cur.fetchone()
            conn.rollback()
        finally:
            conn.close()
        if not row:
            return {"present": False}
        keys = ("status", "last_success_at", "last_failure_at", "failure_count", "degraded", "updated_at")
        return {"present": True, **{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in zip(keys, row)}}
    except Exception as exc:  # noqa: BLE001
        return {"present": None, "error": type(exc).__name__}


def plan():
    """The dry run: what check() would do, computed without the probe or any write."""
    cookie = _env("FINVIZ_COOKIE", "")
    token = _env("FINVIZ_API_TOKEN", "")
    attempts = [name for name, have in (("cookie", cookie), ("token", token)) if have]
    return {
        "mode": "dry_run",
        "source_key": "finviz",
        "would_probe": attempts,
        "would_probe_url": TEST_URL,
        "current_row": _read_health_row(),
        "would_update_on_healthy": " ".join(SQL_HEALTHY.split()),
        "would_update_on_degraded": " ".join(SQL_DEGRADED.split()),
        "would_status_without_credentials": None if attempts else "error",
        "would_write_receipt": "data/runtime/finviz_health_check_last.json",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="read-only plan: no probe, no write, no send")
    args = parser.parse_args()

    if args.dry_run:
        print(json.dumps(plan(), indent=2, default=str))
        print("(dry run — no probe, nothing written, nothing sent)")
        sys.exit(0)  # AGENTS.md §6: check(), the send and the receipt are below this line

    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).isoformat()
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

    healthy = result["status"] == "healthy"
    recorded = result.get("recorded", False)
    code = 0 if healthy and recorded else (1 if not healthy else 3)
    if healthy and not recorded:
        print(f"  [finviz] health row NOT recorded: {result.get('record_error')}", file=sys.stderr)
    from lib.lane_last_receipt import write_lane_receipt
    write_lane_receipt("finviz_health_check", ok=code == 0, exit_code=code, started_at=started,
                       summary={"status": result["status"], "credential": result.get("credential"),
                                "row_count": result.get("row_count"), "recorded": recorded,
                                "record_error": result.get("record_error")})
    sys.exit(code)


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
