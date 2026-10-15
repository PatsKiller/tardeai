#!/usr/bin/env python3
"""YouTube cookie health check → Telegram alert.

The YouTube auth cookies (~/.config/tradeai/youtube_cookies.txt; resolved by
scripts/lib/youtube_cookie_path.py, legacy fallback config/youtube_cookies.txt) are the single blocker for ALL
transcript ingestion, and they rotate/expire. When they go logged-out, ingestion silently
returns 0 (it froze for 14 days before anyone noticed). This pings the operator on Telegram
with the exact refresh steps when the cookies are missing/logged-out OR ingestion has gone stale.

Status mirrors the v3 Pipeline stoplight: red=logged-out, amber=authed-but-stale, green=ok.

    python3 scripts/youtube_cookie_health_check.py            # alert only if red/amber
    python3 scripts/youtube_cookie_health_check.py --always   # always send (test)
    python3 scripts/youtube_cookie_health_check.py --no-send  # report only: receipt, no Telegram
    python3 scripts/youtube_cookie_health_check.py --preview  # report only: no Telegram, no receipt (reads jar + DB)
    python3 scripts/youtube_cookie_health_check.py --dry-run  # offline plan: opens no jar, no DB, no env, no write
Cron: daily ~19:45 (after the 19:00 ingest).

Cookie location (2026-10-14): the jar lives outside any release, at the canonical path
``~/.config/tradeai/youtube_cookies.txt`` (``TRADEAI_YOUTUBE_COOKIE_FILE`` overrides). A jar found
only at the legacy release path ``config/youtube_cookies.txt`` still authenticates but is AMBER —
every promote builds a new release dir, so it will be lost on the next release. The status line
and receipt name the path used (``cookie_path`` / ``cookie_location``).

n8n refactor wave 1 (2026-10-10):
  * ``--no-send`` (alias ``--report``) computes and prints the status and writes the
    ScheduledJobReceipt (summary.status / summary.detail) but never calls Telegram, so the incident
    router can deliver through the host sender. ``--dry-run`` additionally writes no receipt.
  * Exit 0 = the check ran (red/amber are FINDINGS, carried in the receipt summary); non-zero only
    when the check itself raised. Before 2026-10-10 red/amber exited 1, so the lane "failed" daily.
  * The receipt gains ``ok_at`` (advances only on exit 0).
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
try:
    from lib.youtube_cookie_path import CANONICAL_DISPLAY, resolve_cookie_path
except ImportError:  # pragma: no cover - imported as scripts.youtube_cookie_health_check
    from scripts.lib.youtube_cookie_path import CANONICAL_DISPLAY, resolve_cookie_path
AUTH = {
    "SID",
    "HSID",
    "SSID",
    "SAPISID",
    "LOGIN_INFO",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
}
STALE_H = 72

REFRESH_STEPS = (
    "🔑 YouTube cookies need a refresh — transcript ingestion is blocked.\n\n"
    "Ops UI (preferred): Command Center → System → Pipeline → YouTube cookies\n"
    "  deep-link: /v3/system?tab=Pipeline&focus=youtube-cookies\n"
    "  paste or upload Netscape cookies.txt → Validate & write\n\n"
    "CLI fallback: export from a LOGGED-IN youtube.com tab and replace "
    f"{CANONICAL_DISPLAY} (outside any release; chmod 600):\n"
    "• Chrome ext 'Get cookies.txt LOCALLY', or\n"
    f"• yt-dlp --cookies-from-browser chrome --cookies {CANONICAL_DISPLAY}\n"
    "Must include auth cookies (e.g. SID / __Secure-1PSID / __Secure-3PSID / SAPISID / LOGIN_INFO).\n"
    "Then: .venv/bin/python scripts/youtube_transcript_ingest.py --all-channels\n\n"
    "n8n: MONITOR_ONLY — never fetch browser cookies or write this file."
)


def _auth_cookie_names(lines, *, now=None):
    """Classify Netscape rows, including the standard HttpOnly domain prefix.

    Cookie values are never returned; this pure helper is testable without opening a cookie file.
    """
    names = set()
    current = time.time() if now is None else now
    for ln in lines:
        if ln.startswith("#HttpOnly_"):
            ln = ln[len("#HttpOnly_") :]
        if ln.startswith("#") or "\t" not in ln:
            continue
        p = ln.split("\t")
        if len(p) != 7 or not p[6].strip():
            continue
        domain = p[0].lstrip(".").lower()
        if domain not in {"youtube.com", "google.com"} and not domain.endswith((".youtube.com", ".google.com")):
            continue
        try:
            expires = int(p[4])
        except ValueError:
            continue
        if expires == 0 or expires > current:
            names.add(p[5])
    return names & AUTH


def _auth_cookie_count(path):
    if not path.exists():
        return None
    return len(_auth_cookie_names(path.read_text().splitlines()))


def classify(auth, age_h, location):
    """(status, detail) — red: missing/logged-out; amber: legacy release path or stale; green: ok."""
    if auth is None or auth == 0:
        return "red", "cookie file missing or logged-out (0 auth cookies)"
    if location == "legacy":
        return "amber", (
            f"authenticated ({auth} auth cookies) but read from the legacy release path "
            f"config/youtube_cookies.txt — will be lost on next release; move to {CANONICAL_DISPLAY}"
        )
    if age_h is not None and age_h > STALE_H:
        return "amber", f"authenticated but ingestion {round(age_h)}h stale"
    return "green", f"authenticated ({auth} auth cookies), ingestion fresh"


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


def _send_telegram(msg, *, priority: str = "P2"):
    try:
        from telegram_alert import send_telegram

        ok = bool(send_telegram(msg, priority=priority, producer="youtube_cookie_health_check"))
        try:
            from lib.comms import CommunicationEvent, publish_communication

            publish_communication(
                CommunicationEvent(
                    direction="OUTBOUND",
                    event_type="alert",
                    message_class="ops",
                    producer="youtube_cookie_health_check",
                    subject_key="ops:youtube_cookies",
                    retention_class="operational",
                    severity="warning",
                    sanitized_body=msg[:500],
                    short_summary=msg[:120],
                )
            )
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        if not ok:
            print("[cookie-health] send_telegram returned False")
        return ok
    except Exception as e:
        print(f"[cookie-health] telegram error: {e}")
        return False


#: Result of the last main() call, folded into the receipt summary (status only — no cookie data).
_LAST: dict = {}


def _summary():
    return dict(_LAST)


def main():
    # load .env so TELEGRAM_* are present under cron
    envf = PROJECT_ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln and ln.split("=", 1)[0] not in os.environ:
                os.environ[ln.split("=", 1)[0]] = ln.split("=", 1)[1]

    res = resolve_cookie_path(PROJECT_ROOT)
    auth = _auth_cookie_count(res.path) if res.exists else None
    age = _transcript_age_h()
    status, detail = classify(auth, age, res.location)

    print(f"[cookie-health] {status.upper()}: {detail}")
    print(f"[cookie-health] cookie path: {res.path} ({res.location})")
    always = "--always" in sys.argv
    dry_run = "--preview" in sys.argv
    no_send = dry_run or "--no-send" in sys.argv or "--report" in sys.argv
    would_send = status in ("red", "amber") or always
    _LAST.clear()
    _LAST.update(
        {
            "status": status,
            "detail": detail,
            "auth_cookies": auth,
            "cookie_path": str(res.path),
            "cookie_location": res.location,
            "transcript_age_h": None if age is None else round(age, 1),
            "would_send": would_send,
            "sent": False,
        }
    )
    if would_send and not no_send:
        _LAST["sent"] = bool(
            _send_telegram(
                f"[{status.upper()}] YouTube cookies: {detail}\n\n{REFRESH_STEPS}",
                priority="P1" if status == "red" else "P2",
            )
        )
    elif would_send:
        print(f"[cookie-health] send suppressed ({'--preview' if dry_run else '--no-send'})")
    # Red/amber are findings, not a failed run (2026-10-10; was `0 if green else 1`).
    return 0


LANE_ID = "youtube-cookie-health-check"


def _live_with_lane_receipt() -> int:
    """The scheduled run: ScheduledJobReceipt (legacy, youtube_cookie_health_check_last.json) as before, plus the
    LaneRunReceipt@v1 the n8n row names (data/runtime/youtube-cookie-health-check_last.json; ok_at advances only
    on exit 0; produced_count 1 = one status classified)."""
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    from lib.scheduled_job_receipt import run_with_receipt

    started = now_iso()
    try:
        code = run_with_receipt(main, script="youtube_cookie_health_check", root=PROJECT_ROOT, summary_from=_summary)
    except BaseException:
        write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started, script="youtube_cookie_health_check.py",
                           output={"produced_count": 0, "attempted_count": 1}, error="cookie health check raised")
        raise
    ok = code == 0 and bool(_LAST.get("status"))
    write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=code,
        started_at=started,
        script="youtube_cookie_health_check.py",
        summary={k: _LAST.get(k) for k in ("status", "cookie_location", "transcript_age_h", "would_send", "sent")},
        output={"produced_count": 1 if ok else 0, "attempted_count": 1},
        error=None if ok else "cookie health check raised",
    )
    return code


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        # n8n onboarding (2026-10-15): the dispatcher's shadow fire. An offline plan before .env, the cookie jar
        # (operator-only credential file, AGENTS §24.7), the DB, Telegram or any receipt. Wins over --always.
        print(
            f"DRY-RUN {LANE_ID}: would classify the YouTube cookie jar (auth-cookie count only, never values) and "
            "transcript ingestion age, alert P1 red / P2 amber through the telegram_alert chokepoint, and write the "
            "lane receipt; no env, jar, DB, Telegram or write; inputs NOT_MEASURED"
        )
        sys.exit(0)
    if "--preview" in sys.argv:
        # A preview is not evidence the scheduled job ran: no receipt, no send (AGENTS.md §6).
        from lib.lane_last_receipt import dry_run_report
        from lib.scheduled_job_receipt import default_receipt

        _code = main()
        dry_run_report(
            LANE_ID,
            _summary(),
            receipt=default_receipt("youtube_cookie_health_check", PROJECT_ROOT),
            would_write=["send_telegram(cookie refresh steps)"] if _LAST.get("would_send") else [],
        )
        sys.exit(_code)
    sys.exit(_live_with_lane_receipt())
