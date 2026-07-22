#!/usr/bin/env python3
"""schwab_auto_reauth.py — true 7-day auto-reauth for the Schwab OAuth login.

Schwab refresh tokens have a FIXED 7-day lifetime from the browser login (rotation does NOT
extend it — proven from broker_oauth_token_audit, 2026-07-22). This agent re-does the browser
login automatically BEFORE expiry:

  1. Anchors the real 7-day clock to the last true login (audit event='reauth').
  2. On day 6 (or immediately if the token is already degraded/dead), inside operator hours,
     it FIRST notifies Telegram + email — the operator has Schwab 2FA and must know the
     login is legitimate before approving the prompt on their device — then waits, then
  3. drives a persistent-profile Chromium through the OAuth authorize flow (credentials come
     ONLY from Bitwarden SM via the tmpfs render — never from repo files), waits for the
     operator's 2FA approval, captures the ?code= callback, and
  4. seeds the token manager (exchange_code → seed_token), live-probes, and reports the
     outcome on both channels.

The persistent browser profile opts into "remember this device", so later weekly logins may
skip 2FA entirely. Fail-safe: any error leaves the existing token untouched, screenshots the
page for forensics, and sends the manual-fallback instructions.

CLI:
  --check        cron mode: run only if due + allowed hours + rate limits (quiet otherwise)
  --now          force an attempt immediately (still notifies first)
  --status       print schedule/token state as JSON
  --notify-test  send a test message on both channels and exit
  --no-wait      shorten the pre-login notice wait (interactive testing)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from env_bootstrap import load_env  # noqa: E402

ACCOUNT_KEY = os.environ.get("SCHWAB_TOKEN_ACCOUNT_KEY", "schwab_taxable")  # canonical token row
PROFILE_DIR = ROOT / "data" / "runtime" / "schwab_browser_profile"
DEBUG_DIR = ROOT / "data" / "runtime" / "schwab_reauth_debug"
STATE_PATH = ROOT / "data" / "runtime" / "schwab_auto_reauth_state.json"

REAUTH_AT_DAYS = 6.0          # proactive login on day 6 of the 7-day window
ALLOWED_HOURS = (8, 22)       # local hours the operator can realistically approve 2FA
MIN_GAP_MIN = 120             # between attempts
MAX_PER_DAY = 4
NOTICE_WAIT_S = 120           # heads-up lead time before the browser touches Schwab
LOGIN_TIMEOUT_S = 420         # includes waiting for the operator's 2FA approval
STEP_POLL_S = 2.0


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _log(msg: str) -> None:
    print(f"[{_now().isoformat(timespec='seconds')}] {msg}", flush=True)


# ── notifications (both channels, per operator requirement) ──────────────────────────────
def _notify(subject: str, body: str) -> None:
    ok_t = ok_e = False
    try:
        from telegram_alert import send_telegram
        ok_t = send_telegram(f"🔐 {subject}\n{body}", bypass_router=True)
    except Exception as e:
        _log(f"telegram notify failed: {e}")
    try:
        from email_notifier import send_email
        ok_e = send_email(f"[Trade AI] {subject}", body)
    except Exception as e:
        _log(f"email notify failed: {e}")
    _log(f"notified telegram={ok_t} email={ok_e}: {subject}")


# ── schedule state ───────────────────────────────────────────────────────────────────────
def _last_true_login():
    import schwab_token_manager as tm
    conn = tm._conn(); cur = conn.cursor()
    cur.execute("""SELECT max(created_at) FROM broker_oauth_token_audit
                   WHERE broker='schwab' AND event='reauth' AND status='ok'""")
    r = cur.fetchone()
    return r[0] if r and r[0] else None


def _token_state() -> dict:
    import schwab_token_manager as tm
    h = tm.health(ACCOUNT_KEY, "schwab", "live") or {}
    last_login = _last_true_login()
    expires = (last_login + dt.timedelta(days=7)) if last_login else None
    due_at = (last_login + dt.timedelta(days=REAUTH_AT_DAYS)) if last_login else None
    dead = bool(h.get("degraded")) or not h.get("has_token")
    return {"last_true_login": last_login.isoformat() if last_login else None,
            "true_expiry": expires.isoformat() if expires else None,
            "proactive_due_at": due_at.isoformat() if due_at else None,
            "degraded": bool(h.get("degraded")), "has_token": bool(h.get("has_token")),
            "due_now": dead or (due_at is not None and _now() >= due_at),
            "reason": ("token degraded/missing" if dead
                       else f"day-{REAUTH_AT_DAYS:g} proactive window" if due_at and _now() >= due_at
                       else "not due")}


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(update: dict) -> None:
    s = _load_state(); s.update(update)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(s, indent=2, default=str))


def _rate_limited() -> str | None:
    s = _load_state()
    last = s.get("last_attempt_at")
    if last:
        try:
            gap = (_now() - dt.datetime.fromisoformat(last)).total_seconds() / 60
            if gap < MIN_GAP_MIN:
                return f"last attempt {gap:.0f}m ago (< {MIN_GAP_MIN}m)"
        except Exception:
            pass
    today = _now().date().isoformat()
    if s.get("attempts_day") == today and int(s.get("attempts_count", 0)) >= MAX_PER_DAY:
        return f"{MAX_PER_DAY} attempts already today"
    return None


def _mark_attempt() -> None:
    s = _load_state()
    today = _now().date().isoformat()
    n = int(s.get("attempts_count", 0)) + 1 if s.get("attempts_day") == today else 1
    _save_state({"last_attempt_at": _now().isoformat(), "attempts_day": today, "attempts_count": n})


# ── the browser flow ─────────────────────────────────────────────────────────────────────
LOGIN_ID_SEL = ["#loginIdInput", "input[name='loginId']", "#loginId", "input[autocomplete='username']"]
PASSWORD_SEL = ["#passwordInput", "input[name='password']", "input[type='password']"]
SUBMIT_SEL = ["#btnLogin", "button[type='submit']", "#submit-btn"]
OTP_INPUT_SEL = ["#securityCode", "input[name='securityCode']", "input[autocomplete='one-time-code']",
                 "#otp_sms", "input[name='pinNumber']"]
CONTINUE_SEL = ["#submit-btn", "#btn-continue", "#continueButton", "button[type='submit']"]
REMEMBER_SEL = ["#rememberDevice", "input[name='rememberDevice']", "#checkbox-remember-device"]
ACCEPT_SEL = ["#acceptTerms", "input[name='acceptTerms']"]


def _first_visible(frame, selectors):
    for sel in selectors:
        try:
            el = frame.query_selector(sel)
            if el and el.is_visible():
                return el
        except Exception:
            continue
    return None


def _totp_code() -> str | None:
    secret = os.environ.get("SCHWAB_TOTP_SECRET", "").strip()
    if not secret:
        return None
    try:
        import pyotp
        return pyotp.TOTP(secret).now()
    except Exception:
        return None


def _attempt_login(authorize_url: str, callback_url: str) -> dict:
    """Drive the OAuth login. Returns {ok, redirect_url?, error?, log: [...]}."""
    from playwright.sync_api import sync_playwright
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(PROFILE_DIR, 0o700)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []
    captured: dict = {}

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=True,
            viewport={"width": 1280, "height": 900}, locale="en-US",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
            args=["--disable-blink-features=AutomationControlled"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

            # Intercept the 127.0.0.1 callback BEFORE any connection attempt — capture ?code=
            # and serve a friendly page instead of ERR_CONNECTION_REFUSED.
            def _route(route):
                captured["url"] = route.request.url
                route.fulfill(status=200, content_type="text/html",
                              body="<h3>Trade AI: login captured — this window can close.</h3>")
            cb_base = callback_url.rstrip("/")
            ctx.route(lambda url: str(url).startswith(cb_base), _route)

            page.goto(authorize_url, wait_until="domcontentloaded", timeout=60_000)
            actions.append(f"opened authorize page → {page.url[:80]}")

            filled_login = clicked_submit = False
            deadline = time.time() + LOGIN_TIMEOUT_S
            while time.time() < deadline and "url" not in captured:
                if "code=" in (page.url or ""):
                    captured["url"] = page.url
                    break
                for frame in page.frames:
                    try:
                        if not filled_login:
                            uid = _first_visible(frame, LOGIN_ID_SEL)
                            pwd = _first_visible(frame, PASSWORD_SEL)
                            if uid and pwd:
                                uid.fill(os.environ["SCHWAB_LOGIN_ID"])
                                pwd.fill(os.environ["SCHWAB_LOGIN_PASSWORD"])
                                remember = _first_visible(frame, REMEMBER_SEL)
                                if remember:
                                    try:
                                        remember.check()
                                        actions.append("checked remember-device")
                                    except Exception:
                                        pass
                                filled_login = True
                                btn = _first_visible(frame, SUBMIT_SEL)
                                if btn:
                                    btn.click(); clicked_submit = True
                                else:
                                    pwd.press("Enter"); clicked_submit = True
                                actions.append("submitted credentials")
                                break
                        else:
                            otp_el = _first_visible(frame, OTP_INPUT_SEL)
                            code = _totp_code()
                            if otp_el and code:
                                otp_el.fill(code)
                                actions.append("filled TOTP code")
                                cont = _first_visible(frame, CONTINUE_SEL)
                                if cont:
                                    cont.click(); actions.append("continued after TOTP")
                                break
                            # consent / terms / account-selection pages: accept + continue
                            acc = _first_visible(frame, ACCEPT_SEL)
                            if acc:
                                try:
                                    acc.check(); actions.append("accepted terms")
                                except Exception:
                                    pass
                            if acc or (clicked_submit and not otp_el):
                                cont = _first_visible(frame, CONTINUE_SEL)
                                if cont:
                                    txt = ""
                                    try:
                                        txt = (cont.inner_text() or "").strip().lower()
                                    except Exception:
                                        pass
                                    if "cancel" not in txt and "deny" not in txt:
                                        cont.click()
                                        actions.append(f"clicked continue ({txt[:24] or 'submit'})")
                                        break
                    except Exception:
                        continue
                time.sleep(STEP_POLL_S)

            if "url" not in captured:
                shot = DEBUG_DIR / f"reauth_fail_{_now().strftime('%Y%m%d_%H%M%S')}.png"
                try:
                    page.screenshot(path=str(shot), full_page=True)
                    actions.append(f"screenshot: {shot}")
                except Exception:
                    pass
                return {"ok": False, "error": f"no callback within {LOGIN_TIMEOUT_S}s "
                                              f"(last page: {page.url[:100]})", "log": actions}
            return {"ok": True, "redirect_url": captured["url"], "log": actions}
        finally:
            ctx.close()


# ── orchestration ────────────────────────────────────────────────────────────────────────
def run_attempt(notice_wait: int = NOTICE_WAIT_S) -> int:
    load_env()
    missing = [k for k in ("SCHWAB_LOGIN_ID", "SCHWAB_LOGIN_PASSWORD") if not os.environ.get(k)]
    if missing:
        _notify("Schwab auto-reauth BLOCKED",
                f"Missing {', '.join(missing)} in Bitwarden SM. "
                f"Run: .venv/bin/python scripts/secrets/store_schwab_login.py")
        return 1
    import schwab_token_manager as tm
    url_info = tm.reauth_url(ACCOUNT_KEY)
    if not url_info.get("ok"):
        _notify("Schwab auto-reauth BLOCKED", f"reauth_url failed: {url_info.get('reason')}")
        return 1
    st = _token_state()
    _mark_attempt()
    _notify("Schwab auto-reauth starting",
            f"Reason: {st['reason']}. In ~{notice_wait // 60 or 1} min I will log in to Schwab "
            f"with the stored credentials. If your phone shows a Schwab 2FA prompt, IT IS ME — "
            f"please APPROVE it. Nothing else is touched (login only, token refresh).")
    time.sleep(notice_wait)

    cb = os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
    _log("starting browser login…")
    res = _attempt_login(url_info["authorize_url"], cb)
    if not res["ok"]:
        _save_state({"last_result": "fail", "last_error": res["error"]})
        _notify("Schwab auto-reauth FAILED",
                f"{res['error']}\nSteps taken: {'; '.join(res['log'][-6:]) or 'none'}\n"
                f"Manual fallback:\n1) open the login link on any device:\n{url_info['authorize_url']}\n"
                f"2) after login, copy the full 127.0.0.1 redirect URL and run:\n"
                f"{url_info['step2_command']}")
        return 1

    ex = tm.exchange_code(ACCOUNT_KEY, res["redirect_url"])
    if not ex.get("ok"):
        _save_state({"last_result": "fail", "last_error": f"exchange: {ex.get('reason')}"})
        _notify("Schwab auto-reauth FAILED at token exchange", str(ex.get("reason"))[:300])
        return 1
    probe = {}
    try:
        probe = tm.live_probe(ACCOUNT_KEY) or {}
    except Exception as e:
        probe = {"error": str(e)[:120]}
    _save_state({"last_result": "ok", "last_success_at": _now().isoformat(), "last_error": None})
    nxt = (_now() + dt.timedelta(days=REAUTH_AT_DAYS)).strftime("%a %b %d %H:%M UTC")
    _notify("Schwab auto-reauth SUCCESS ✅",
            f"New 7-day token seeded and verified (live_probe ok={probe.get('live_ok', probe)}). "
            f"Stops/quotes/journal reads are back. Next automatic login ≈ {nxt} "
            f"(you'll get this same heads-up first).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--now", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--notify-test", action="store_true")
    ap.add_argument("--no-wait", action="store_true")
    a = ap.parse_args()
    load_env()

    if a.notify_test:
        _notify("Schwab auto-reauth notification test",
                "Both channels working. This is only a test — no login attempted.")
        return 0
    if a.status:
        print(json.dumps({**_token_state(), "state": _load_state()}, indent=2, default=str))
        return 0
    wait = 5 if a.no_wait else NOTICE_WAIT_S
    if a.now:
        return run_attempt(notice_wait=wait)
    if a.check:
        st = _token_state()
        if not st["due_now"]:
            return 0
        hour = dt.datetime.now().hour
        if not (ALLOWED_HOURS[0] <= hour < ALLOWED_HOURS[1]):
            _log(f"due ({st['reason']}) but outside operator hours ({hour}h) — waiting")
            return 0
        rl = _rate_limited()
        if rl:
            _log(f"due but rate-limited: {rl}")
            return 0
        _log(f"due: {st['reason']} — attempting")
        return run_attempt(notice_wait=wait)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
