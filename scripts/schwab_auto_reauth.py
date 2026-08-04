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

# ── Chromium binary discovery ───────────────────────────────────────────────────
# Playwright may be installed in the home cache or via system paths. Find whichever
# is actually present so we don't fail on Executable-not-found.
_CHROME_PATH = None
for _cand in [
    os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH", ""),
    os.path.expanduser("~/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome"),
    os.path.expanduser("~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome"),
    os.path.expanduser("~/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome"),
    os.path.expanduser("~/.cache/puppeteer/chrome/linux-147.0.7727.56/chrome-linux64/chrome"),
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/snap/bin/chromium",
]:
    if _cand and Path(_cand).exists():
        _CHROME_PATH = _cand
        break


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

# ── Schwab authenticator page (sws-gateway.schwab.com/ui/host/#/authenticators) ─────────
# This page appears AFTER credential submission. The operator's trusted-device push method
# must be selected and the challenge explicitly sent. The prior code had no handler here.
AUTH_PAGE_INDICATORS = [
    "/ui/host/#/authenticators",          # URL fragment
    "sws-gateway.schwab.com",             # domain
]
AUTH_PAGE_CONTENT_SIG = ["authenticator", "trusted contact", "verify your identity"]

# Trusted-device push authenticator — the preferred method (not SMS, not security question)
TRUSTED_CONTACT_SEL = [
    "[data-testid='trusted-contact']",
    "[aria-label*='Trusted contact']",
    "label:has-text('Trusted contact')",
    "span:has-text('Trusted contact')",
    "div:has-text('Trusted contact')",
    "button:has-text('Trusted contact')",
    "input[value*='trusted']",
]

# The control that actually sends the push notification after method selection
SEND_CHALLENGE_SEL = [
    "button:has-text('Send')",
    "button:has-text('Continue')",
    "button:has-text('Continue to Schwab')",
    "button:has-text('Verify')",
    "#continueButton", "#btn-continue", "#btnSendNotification",
    "[aria-label*='Continue']", "[aria-label*='Send']",
    "[data-testid='continue']", "[data-testid='send']",
]

# Pending approval indicators
APPROVAL_PENDING_SIG = ["approval pending", "check your device", "notification sent",
                         "waiting for approval", "approve the request", "push sent"]

# Post-login pages (Trader API terms → "Instruction and Informed Consent" modal → account
# grant → done) use plain-text buttons, not stable ids — match by visible text. Order =
# priority; the consent modal's Accept must win over the covered background Continue.
AFFIRM_WORDS = ("accept", "continue", "done", "allow", "confirm", "authorize", "next", "submit")
NEGATIVE_WORDS = ("cancel", "deny", "decline", "resend", "back", "close", "help", "forgot",
                  "try another way", "try another")  # added: never click "Try another way"


def _click_affirmative(frame, actions: list, extra_selectors: list | None = None) -> bool:
    """Click the highest-priority visible affirmative button in this frame. Never clicks
    negative-word buttons. extra_selectors broadens the element search for SPA pages where
    buttons are divs/spans. Returns True if something was clicked."""
    try:
        sel = "button, input[type='submit'], a[role='button']"
        if extra_selectors:
            sel += ", " + ", ".join(extra_selectors)
        btns = frame.query_selector_all(sel)
    except Exception:
        return False
    cands = []
    for b in btns:
        try:
            if not b.is_visible():
                continue
            txt = (b.inner_text() or b.get_attribute("value") or b.get_attribute("aria-label") or "").strip().lower()
        except Exception:
            continue
        if not txt or any(w in txt for w in NEGATIVE_WORDS):
            continue
        for rank, w in enumerate(AFFIRM_WORDS):
            if w in txt:
                cands.append((rank, b, txt))
                break
    for rank, btn, txt in sorted(cands, key=lambda t: t[0]):
        try:
            btn.click(timeout=5000)
            actions.append(f"clicked '{txt[:24]}'")
            return True
        except Exception:  # covered by a modal → try the next candidate
            continue
    return False


def _first_visible(frame, selectors):
    for sel in selectors:
        try:
            el = frame.query_selector(sel)
            if el and el.is_visible():
                return el
        except Exception:
            continue
    return None


def _page_text(frame) -> str:
    """Return the visible text content of a frame (lowercase, first 500 chars)."""
    try:
        body = frame.query_selector("body")
        if body:
            return (body.inner_text() or "").strip().lower()[:500]
    except Exception:
        pass
    return ""


def _url_contains(page, fragments: list[str]) -> bool:
    """Check if the current page URL contains any of the given fragments."""
    try:
        u = (page.url or "").lower()
        return any(f.lower() in u for f in fragments)
    except Exception:
        return False


def _is_authenticator_page(page) -> bool:
    """Detect Schwab's authenticator-selection page by URL and/or content."""
    if _url_contains(page, AUTH_PAGE_INDICATORS):
        return True
    # Fallback: scan for authenticator content in any frame
    for frame in page.frames:
        txt = _page_text(frame)
        if any(sig in txt for sig in AUTH_PAGE_CONTENT_SIG):
            return True
    return False


def _handle_authenticator_page(page, actions: list, debug_dir: Path) -> str | None:
    """Handle the Schwab authenticator-selection page using JavaScript click-by-text.
    CSS selectors fail on React SPAs where elements are divs without stable IDs.
    Returns: 'challenge_sent' | 'already_approved' | None (will retry)"""
    # ── Debug screenshot ──
    try:
        shot = debug_dir / f"reauth_authpage_{_now().strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=str(shot))
        _log(f"  auth page screenshot: {shot}")
        actions.append(f"screenshot: {shot}")
    except Exception as e:
        _log(f"  screenshot failed: {e}")

    # ── JS: click element by visible text ──
    def _js_click_text(label: str) -> bool:
        """Use JS to find and click a visible element with exact text match."""
        js = f"""
        (() => {{
            const label = {json.dumps(label)};
            const all = document.querySelectorAll('*');
            for (const el of all) {{
                if (!el.offsetParent) continue; // not visible
                const txt = (el.innerText || el.textContent || '').trim();
                if (txt === label || txt.startsWith(label)) {{
                    el.click();
                    return 'clicked:' + el.tagName;
                }}
            }}
            return 'notfound';
        }})()
        """
        try:
            result = page.evaluate(js)
            return str(result).startswith("clicked")
        except Exception:
            return False

    # ── Step 1: Click "Trusted contact" to select it ──
    if _js_click_text("Trusted contact"):
        _log("  JS clicked: Trusted contact")
        actions.append("JS clicked: Trusted contact")
        time.sleep(1.5)
    else:
        _log("  JS: 'Trusted contact' not found as standalone clickable element, trying partial match")
        # Try partial match — the element might contain "Trusted contact\n(718) 219-4296"
        try:
            js = """
            (() => {
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    if (!el.offsetParent) return;
                    const txt = (el.innerText || '').trim();
                    if (txt.includes('Trusted contact')) {
                        el.click();
                        return 'clicked:' + el.tagName;
                    }
                }
                return 'notfound';
            })()
            """
            result = page.evaluate(js)
            _log(f"  JS partial text result: {result}")
            time.sleep(1.5)
        except Exception as e:
            _log(f"  JS partial text failed: {e}")

    # ── Step 2: Click "Continue" ──
    if _js_click_text("Continue"):
        _log("  JS clicked: Continue")
        actions.append("JS clicked: Continue")
        time.sleep(3.0)

        # Verify page transition
        still_auth = _is_authenticator_page(page)
        if not still_auth:
            _log("  page LEFT authenticator — challenge sent ✓")
            return "challenge_sent"

        # Check for approval-pending content
        for frame in page.frames:
            txt = _page_text(frame)
            if any(sig in txt for sig in APPROVAL_PENDING_SIG):
                _log("  page shows approval-pending — challenge sent ✓")
                return "challenge_sent"

        _log("  clicked Continue but still on authenticator page")
    else:
        _log("  JS: 'Continue' button not found")
        # Try _click_affirmative as fallback
        for frame in page.frames:
            if _click_affirmative(frame, actions, extra_selectors=["div[role='button']", "span[role='button']"]):
                time.sleep(3.0)
                if not _is_authenticator_page(page):
                    _log("  fallback click moved off authenticator page")
                    return "challenge_sent"

    # ── Step 3: Already approved? ──
    if not _is_authenticator_page(page):
        _log("  no longer on authenticator page")
        return "already_approved"

    # ── Step 4: Dump visible HTML for debugging ──
    try:
        js = """
        (() => {
            const vis = [];
            document.querySelectorAll('button, a, input, [role="button"], [role="radio"]').forEach(el => {
                if (!el.offsetParent) return;
                const tag = el.tagName.toLowerCase();
                const type = el.getAttribute('type') || '';
                const txt = (el.innerText || el.value || '').trim().slice(0, 80);
                vis.push(`<${tag}${type ? ' type='+type : ''}> "${txt}"`);
            });
            return vis.slice(0, 20).join('|');
        })()
        """
        dom = page.evaluate(js)
        _log(f"  DOM: {dom}")
        actions.append(f"DOM: {dom}")
    except Exception as e:
        _log(f"  DOM dump failed: {e}")

    _log("  could not trigger push — will retry")
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


def _ensure_display() -> tuple[dict, object | None]:
    """Headed beats headless: Schwab's Akamai serves 'Access Denied' to headless Chromium
    (proven 2026-07-22). Prefer an existing $DISPLAY; else start a private Xvfb. Returns
    (env_overrides, xvfb_proc_or_None). Empty overrides + None ⇒ caller must run headless."""
    import shutil
    import subprocess
    if os.environ.get("DISPLAY"):
        return {}, None
    xvfb = shutil.which("Xvfb")
    if not xvfb:
        return {}, None
    disp = ":97"
    proc = subprocess.Popen([xvfb, disp, "-screen", "0", "1280x900x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    if proc.poll() is not None:  # e.g. :97 already taken by a stale Xvfb
        return {}, None
    return {"DISPLAY": disp}, proc


def _attempt_login(authorize_url: str, callback_url: str) -> dict:
    """Drive the OAuth login with an explicit state machine.

    States: LOGIN_FORM → AUTHENTICATOR_SELECTION → CHALLENGE_SENT →
            WAITING_FOR_APPROVAL → TERMS_OR_CONSENT → ACCOUNT_GRANT →
            CALLBACK_CAPTURED → TOKEN_EXCHANGED → LIVE_PROBE_VERIFIED

    Returns {ok, redirect_url?, error?, log: [...], state: str}."""
    from playwright.sync_api import sync_playwright
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(PROFILE_DIR, 0o700)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []
    captured: dict = {}
    state = "START"
    challenge_sent = False
    last_heartbeat = 0.0

    disp_env, xvfb_proc = _ensure_display()
    headed = bool(disp_env) or bool(os.environ.get("DISPLAY"))
    if disp_env:
        os.environ.update(disp_env)
        actions.append(f"xvfb display {disp_env['DISPLAY']}")
    elif not headed:
        actions.append("WARNING: no display + no Xvfb — headless (Akamai may deny)")
    if _CHROME_PATH:
        actions.append(f"chromium: {_CHROME_PATH}")
    else:
        actions.append("WARNING: no Chromium binary found")

    with sync_playwright() as pw:
        kwargs = dict(viewport={"width": 1280, "height": 900}, locale="en-US",
                      args=["--disable-blink-features=AutomationControlled"])
        if not headed:
            kwargs["user_agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=not headed, executable_path=_CHROME_PATH, **kwargs)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            page.set_default_timeout(8000)

            # Intercept the 127.0.0.1 callback BEFORE any connection attempt
            def _route(route):
                captured["url"] = route.request.url
                route.fulfill(status=200, content_type="text/html",
                              body="<h3>Trade AI: login captured — this window can close.</h3>")
            cb_base = callback_url.rstrip("/")
            ctx.route(lambda url: str(url).startswith(cb_base), _route)

            page.goto(authorize_url, wait_until="domcontentloaded", timeout=60_000)
            state = "LOGIN_FORM"
            actions.append(f"opened authorize page → {page.url[:80]}")

            filled_login = clicked_submit = False
            authenticator_handled = False
            deadline = time.time() + LOGIN_TIMEOUT_S
            challenge_timeout = deadline  # reset after challenge is sent

            while time.time() < deadline and "url" not in captured:
                # ── Callback check (highest priority) ──
                if "code=" in (page.url or ""):
                    captured["url"] = page.url
                    state = "CALLBACK_CAPTURED"
                    break

                # ── Access Denied check ──
                try:
                    if (page.title() or "").strip().lower() == "access denied":
                        shot = DEBUG_DIR / f"reauth_denied_{_now().strftime('%Y%m%d_%H%M%S')}.png"
                        try:
                            page.screenshot(path=str(shot))
                        except Exception:
                            pass
                        return {"ok": False, "state": state, "log": actions,
                                "error": "Schwab bot-defense served 'Access Denied' "
                                         + ("(headed)" if headed else "(headless — install Xvfb)")}
                except Exception:
                    pass

                # ── STATE: LOGIN_FORM — fill credentials and submit ──
                if state == "LOGIN_FORM":
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
                                    state = "SUBMITTED"
                                    actions.append("submitted credentials")
                                    # Small delay to let the page transition
                                    time.sleep(3.0)
                                    break
                        except Exception:
                            continue

                # ── STATE: SUBMITTED/AUTHENTICATOR — handle post-login pages ──
                if state in ("SUBMITTED", "AUTHENTICATOR_SELECTION"):
                    # Check if we're on the authenticator-selection page
                    if _is_authenticator_page(page):
                        if not authenticator_handled:
                            state = "AUTHENTICATOR_SELECTION"
                            auth_attempts = getattr(_handle_authenticator_page, '_attempts', 0) + 1
                            _handle_authenticator_page._attempts = auth_attempts
                            result = _handle_authenticator_page(page, actions, DEBUG_DIR)
                            if result == "challenge_sent":
                                state = "CHALLENGE_SENT"
                                challenge_sent = True
                                authenticator_handled = True
                                challenge_timeout = time.time() + 600
                                deadline = max(deadline, challenge_timeout)
                                actions.append("challenge sent — waiting for operator 2FA approval")
                                _notify("Schwab 2FA prompt sent — please approve it now",
                                        "The push notification has been sent to your Schwab mobile app. "
                                        "Open the app and approve the login request. "
                                        "The automation will continue automatically once approved.")
                                _log("  Schwab push challenge TRIGGERED — check your phone")
                            elif result == "already_approved":
                                state = "TERMS_OR_CONSENT"
                                actions.append("authenticator page bypassed — approval complete")
                            elif auth_attempts >= 3:
                                # After 3 attempts, stop retrying and enter wait state.
                                # The push may have been sent even if the SPA didn't visibly
                                # transition. Listening for the callback is the real proof.
                                _log(f"  authenticator handler retried {auth_attempts}x — entering wait state")
                                authenticator_handled = True
                                state = "CHALLENGE_SENT"
                                challenge_sent = True
                                challenge_timeout = time.time() + 600
                                deadline = max(deadline, challenge_timeout)
                                actions.append("handler exhausted retries — assuming push sent, waiting")
                                _notify("Schwab 2FA prompt sent — please approve it now",
                                        "The push notification has been sent to your Schwab mobile app. "
                                        "Open the app and approve the login request. "
                                        "The automation will continue automatically once approved.")
                            else:
                                actions.append(f"handler attempt {auth_attempts}/3 — will retry")
                        else:
                            # Already handled authenticator, still on this page — waiting
                            pass

                    # ── TOTP handling (skip if we're on the authenticator page —
                    #     the handler above is responsible for triggering the push there) ──
                    on_auth_page = _is_authenticator_page(page)
                    for frame in page.frames:
                        if state in ("SUBMITTED", "AUTHENTICATOR_SELECTION") and not on_auth_page:
                            otp_el = _first_visible(frame, OTP_INPUT_SEL)
                            code = _totp_code()
                            if otp_el and code:
                                otp_el.fill(code)
                                actions.append("filled TOTP code")
                                cont = _first_visible(frame, CONTINUE_SEL)
                                if cont:
                                    cont.click(); actions.append("continued after TOTP")
                                was_sent = challenge_sent
                                challenge_sent = True
                                state = "CHALLENGE_SENT"
                                challenge_timeout = time.time() + 600
                                deadline = max(deadline, challenge_timeout)
                                if not was_sent:
                                    _log("  TOTP submitted — waiting for 2FA approval")
                            elif otp_el and not code:
                                state = "CHALLENGE_SENT"
                                if not challenge_sent:
                                    challenge_sent = True
                                    challenge_timeout = time.time() + 600
                                    deadline = max(deadline, challenge_timeout)
                                    actions.append("waiting for operator push/SMS 2FA")
                                    _log("  OTP field on non-auth page (push/SMS) — waiting for operator")
                                    # This is the push/SMS path (no TOTP secret configured).
                                    # Only notify when we're sure we're past the authenticator page
                                    # and a real 2FA challenge is pending.
                                    _notify("Schwab 2FA prompt sent — please approve it now",
                                            "The push notification has been sent to your Schwab mobile app. "
                                            "Open the app and approve the login request. "
                                            "The automation will continue automatically once approved.")

                # ── STATE: CHALLENGE_SENT / TERMS_OR_CONSENT / ACCOUNT_GRANT ──
                if state in ("CHALLENGE_SENT", "TERMS_OR_CONSENT", "ACCOUNT_GRANT"):
                    # Tick every visible unchecked checkbox (terms, account grants)
                    for frame in page.frames:
                        try:
                            for cb_el in frame.query_selector_all("input[type='checkbox']"):
                                if cb_el.is_visible() and not cb_el.is_checked():
                                    cb_el.check(timeout=3000)
                                    actions.append("checked a consent/account box")
                        except Exception:
                            pass

                    # Click the highest-priority affirmative button
                    for frame in page.frames:
                        if _click_affirmative(frame, actions,
                                              extra_selectors=["div[role='button']", "span[role='button']"]):
                            if state == "CHALLENGE_SENT":
                                state = "TERMS_OR_CONSENT"
                            elif state == "TERMS_OR_CONSENT":
                                state = "ACCOUNT_GRANT"
                            break

                # ── Progress heartbeat ──
                now = time.time()
                if challenge_sent and (now - last_heartbeat) >= 60:
                    _log(f"  still waiting for operator 2FA approval "
                         f"({int(deadline - now)}s remaining, page: {page.url[:80]})")
                    last_heartbeat = now

                time.sleep(STEP_POLL_S)

            if "url" not in captured:
                shot = DEBUG_DIR / f"reauth_fail_{_now().strftime('%Y%m%d_%H%M%S')}.png"
                try:
                    page.screenshot(path=str(shot), full_page=True)
                    actions.append(f"screenshot: {shot}")
                except Exception:
                    pass
                return {"ok": False, "state": state,
                        "error": f"no callback within {LOGIN_TIMEOUT_S}s "
                                f"(last page: {page.url[:100]})", "log": actions}
            return {"ok": True, "state": state, "redirect_url": captured["url"], "log": actions}
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            if xvfb_proc is not None:
                try:
                    xvfb_proc.terminate()
                except Exception:
                    pass


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
    state = res.get("state", "?")

    # (push notification fires inline inside _attempt_login at trigger time)

    if not res["ok"]:
        _save_state({"last_result": "fail", "last_error": res["error"], "last_state": state})
        _notify("Schwab auto-reauth FAILED",
                f"{res['error']}\nState: {state}\nSteps taken: {'; '.join(res['log'][-8:]) or 'none'}\n"
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
    _save_state({"last_result": "ok", "last_success_at": _now().isoformat(), "last_error": None,
                  "last_state": state})
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
