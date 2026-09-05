#!/usr/bin/env python3
"""YouTube cookie health check → Telegram alert.

The YouTube auth cookies (config/youtube_cookies.txt) are the single blocker for ALL
transcript ingestion, and they rotate/expire. When they go logged-out, ingestion silently
returns 0 (it froze for 14 days before anyone noticed). This pings the operator on Telegram
with the exact refresh steps when the cookies are missing/logged-out OR ingestion has gone stale.

Status mirrors the v3 Pipeline stoplight: red=logged-out, amber=authed-but-stale, green=ok.

    python3 scripts/youtube_cookie_health_check.py            # alert only if red/amber
    python3 scripts/youtube_cookie_health_check.py --always   # always send (test)
Cron: daily ~19:45 (after the 19:00 ingest).
"""
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
COOKIE = PROJECT_ROOT / "config" / "youtube_cookies.txt"
AUTH = {"SID", "HSID", "SSID", "SAPISID", "LOGIN_INFO",
        "__Secure-1PSID", "__Secure-3PSID",
        "__Secure-1PAPISID", "__Secure-3PAPISID"}
STALE_H = 72

REFRESH_STEPS = (
    "🔑 YouTube cookies need a refresh — transcript ingestion is blocked.\n\n"
    "Fix: export cookies from a LOGGED-IN youtube.com tab and replace "
    "config/youtube_cookies.txt:\n"
    "• Chrome ext 'Get cookies.txt LOCALLY', or\n"
    "• yt-dlp --cookies-from-browser chrome --cookies config/youtube_cookies.txt\n"
    "Must include auth cookies (e.g. SID / __Secure-1PSID / __Secure-3PSID / SAPISID / LOGIN_INFO).\n"
    "Then: .venv/bin/python scripts/youtube_transcript_ingest.py --all-channels"
)


def _auth_cookie_count():
    if not COOKIE.exists():
        return None
    names = set()
    for ln in COOKIE.read_text().splitlines():
        if ln.startswith("#") or "\t" not in ln:
            continue
        p = ln.split("\t")
        if len(p) >= 6:
            names.add(p[5])
    return len(names & AUTH)


def _transcript_age_h():
    try:
        from db_adapter import _execute
        r = _execute("SELECT MAX(ingested_at) FROM youtube_transcripts", fetch="one")
        ts = list(r.values())[0] if isinstance(r, dict) else (r[0] if r else None)
        if not ts:
            return None
        return (datetime.now(ts.tzinfo) - ts).total_seconds() / 3600
    except Exception:
        return None


def _send_telegram(msg):
    try:
        from telegram_alert import send_telegram
        ok = bool(send_telegram(msg))
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="youtube_cookie_health_check",
                subject_key="ops:youtube_cookies",
                retention_class="operational", severity="warning",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        if not ok:
            print("[cookie-health] send_telegram returned False")
        return ok
    except Exception as e:
        print(f"[cookie-health] telegram error: {e}")
        return False


def main():
    # load .env so TELEGRAM_* are present under cron
    envf = PROJECT_ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln and ln.split("=", 1)[0] not in os.environ:
                os.environ[ln.split("=", 1)[0]] = ln.split("=", 1)[1]

    auth = _auth_cookie_count()
    age = _transcript_age_h()
    if auth is None or auth == 0:
        status, detail = "red", "cookie file missing or logged-out (0 auth cookies)"
    elif age is not None and age > STALE_H:
        status, detail = "amber", f"authenticated but ingestion {round(age)}h stale"
    else:
        status, detail = "green", f"authenticated ({auth} auth cookies), ingestion fresh"

    print(f"[cookie-health] {status.upper()}: {detail}")
    always = "--always" in sys.argv
    if status in ("red", "amber") or always:
        _send_telegram(f"[{status.upper()}] YouTube cookies: {detail}\n\n{REFRESH_STEPS}")
    return 0 if status == "green" else 1


if __name__ == "__main__":
    sys.exit(main())
