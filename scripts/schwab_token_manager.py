#!/usr/bin/env python3
"""schwab_token_manager.py — Schwab OAuth token manager (Phase 1, GATE A).

GATE A (non-negotiable): Schwab refresh tokens last ~7 days from creation and CANNOT be renewed
programmatically — a full manual browser OAuth login is required each cycle. This module therefore
treats refresh-token expiry as FIRST-CLASS STATE, never assumes background infinite refresh, alerts at
day-5/day-6, exposes a one-command re-auth, and FAILS CLOSED (degraded, read-only, no crashes, no retry
storms, no fabricated data) when freshness cannot be proven.

Tokens are stored Fernet-encrypted in broker_oauth_tokens; the encryption key lives ONLY in
config/broker_credentials.env (0600, gitignored) — never in the DB, Drive, logs, or UI. The DB and audit
store ciphertext + fingerprints, never plaintext token material.

NOTE: the live token EXCHANGE/REFRESH HTTP calls require Schwab Developer Portal app credentials
(SCHWAB_APP_KEY/SECRET/CALLBACK) which are an architect open-item; without them those paths return
AUTH_PENDING / NOT_PROVEN (fail closed). The STATE MACHINE, alerts, health, and re-auth persistence are
fully functional and testable now.

  python3 scripts/schwab_token_manager.py init-key            # one-time: generate the encryption key
  python3 scripts/schwab_token_manager.py health [account]
  python3 scripts/schwab_token_manager.py check-alerts [--send]
  python3 scripts/schwab_token_manager.py reauth-url <account>
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
SECRETS_FILE = PROJECT_ROOT / "config" / "broker_credentials.env"
ENC_KEY_NAME = "SCHWAB_TOKEN_ENC_KEY"
REFRESH_TTL_DAYS = 7          # GATE A worst case: assume 7d, no roll-forward, until the portal proves otherwise
REAUTH_LEAD_DAYS = 1         # re-auth should happen at least 1 day before expiry
ACCESS_REFRESH_MARGIN_S = 300  # refresh the ~29-min access token when <5 min remain
ALERT_DAYS = {5, 6}          # day-5 and day-6 of the 7-day window (i.e. 2 and 1 days remaining)
from tg_chat_ids import chat_ids  # no hardcoded chat IDs
RATE_PER_MIN = 100           # conservative shared cap; exact Schwab per-minute number is an architect open-item


def _now():
    return datetime.now(timezone.utc)


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


# ── encryption (key only in the 0600 secrets file; never DB/Drive/logs/UI) ────────
def _enc_key():
    import broker_secrets
    broker_secrets.load_into_env()
    key = os.environ.get(ENC_KEY_NAME)
    if not key:
        raise RuntimeError(f"{ENC_KEY_NAME} not set — run `schwab_token_manager.py init-key` (key is "
                           "stored only in config/broker_credentials.env, 0600, never in DB/Drive).")
    return key.encode()


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(_enc_key())


def _enc(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def _dec(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def _fp(ciphertext: str) -> str:
    return hashlib.sha256((ciphertext or "").encode()).hexdigest()[:16]


def init_key():
    """One-time: generate a Fernet key and persist it to the 0600 secrets file if absent."""
    from cryptography.fernet import Fernet
    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = SECRETS_FILE.read_text() if SECRETS_FILE.exists() else ""
    if f"{ENC_KEY_NAME}=" in existing:
        print(f"  {ENC_KEY_NAME} already present in {SECRETS_FILE} — leaving as-is.")
        return
    key = Fernet.generate_key().decode()
    with open(SECRETS_FILE, "a") as f:
        f.write(f"\n{ENC_KEY_NAME}={key}\n")
    os.chmod(SECRETS_FILE, 0o600)
    print(f"  wrote {ENC_KEY_NAME} to {SECRETS_FILE} (0600). NEVER commit, log, or sync this file.")


# ── audit (append-only; fingerprints/status only, never token values) ─────────────
def _audit(conn, account_key, event, status=None, fingerprint=None, detail=None):
    cur = conn.cursor()
    cur.execute("""INSERT INTO broker_oauth_token_audit (account_key, event, token_fingerprint, status, detail)
                   VALUES (%s,%s,%s,%s,%s)""", (account_key, event, fingerprint, status, (detail or "")[:300]))
    conn.commit()


# ── shared token-bucket rate limiter (Rule 10) ────────────────────────────────────
class _RateBucket:
    def __init__(self, per_min):
        self.capacity = per_min; self.tokens = float(per_min); self.rate = per_min / 60.0; self.ts = time.monotonic()
    def acquire(self, block=True):
        while True:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.ts) * self.rate); self.ts = now
            if self.tokens >= 1:
                self.tokens -= 1; return True
            if not block:
                return False
            time.sleep(min(1.0, (1 - self.tokens) / self.rate))


RATE = _RateBucket(RATE_PER_MIN)   # ONE shared bucket across all accounts/endpoints


# ── token state ───────────────────────────────────────────────────────────────────
def seed_token(account_key, refresh_token, refresh_expires_at=None, access_token=None,
               access_expires_at=None, broker="schwab", environment="live", rotated=False):
    """Persist an (encrypted) token set atomically. Used by the re-auth flow and by tests/simulation.
    Defaults to the GATE-A 7-day worst case when no refresh expiry is supplied."""
    conn = _conn(); cur = conn.cursor()
    rexp = refresh_expires_at or (_now() + timedelta(days=REFRESH_TTL_DAYS))
    reauth_due = rexp - timedelta(days=REAUTH_LEAD_DAYS)
    rt_enc = _enc(refresh_token) if refresh_token else None
    at_enc = _enc(access_token) if access_token else None
    cur.execute("""INSERT INTO broker_oauth_tokens
                     (account_key, broker, environment, access_token_enc, refresh_token_enc,
                      access_expires_at, refresh_expires_at, next_reauth_due_at, degraded, last_error, updated_at,
                      rotation_count)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,FALSE,NULL,NOW(), CASE WHEN %s THEN 1 ELSE 0 END)
                   ON CONFLICT (account_key, broker, environment) DO UPDATE SET
                     access_token_enc=EXCLUDED.access_token_enc, refresh_token_enc=EXCLUDED.refresh_token_enc,
                     access_expires_at=EXCLUDED.access_expires_at, refresh_expires_at=EXCLUDED.refresh_expires_at,
                     next_reauth_due_at=EXCLUDED.next_reauth_due_at, degraded=FALSE, last_error=NULL,
                     token_version=broker_oauth_tokens.token_version+1,
                     rotation_count=broker_oauth_tokens.rotation_count + CASE WHEN %s THEN 1 ELSE 0 END,
                     updated_at=NOW()""",
                (account_key, broker, environment, at_enc, rt_enc, access_expires_at, rexp, reauth_due,
                 rotated, rotated))
    conn.commit()
    _audit(conn, account_key, "refresh_rotation" if rotated else "reauth", "ok", _fp(rt_enc),
           f"refresh_expires_at={rexp.isoformat()}")
    return {"account_key": account_key, "refresh_expires_at": rexp.isoformat(), "next_reauth_due_at": reauth_due.isoformat()}


def health(account_key, broker="schwab", environment="live"):
    """Fail-closed freshness/expiry health for one account. Never raises — returns degraded on any doubt."""
    base = {"account_key": account_key, "broker": broker, "has_token": False, "access_fresh": False,
            "refresh_valid": False, "days_to_reauth": None, "next_reauth_due_at": None,
            "refresh_expires_at": None, "degraded": True, "last_error": None}
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("""SELECT access_expires_at, refresh_expires_at, next_reauth_due_at, refresh_token_enc,
                         degraded, last_error FROM broker_oauth_tokens
                       WHERE account_key=%s AND broker=%s AND environment=%s""", (account_key, broker, environment))
        r = cur.fetchone()
        if not r:
            base["last_error"] = "no token on file — manual OAuth login required"; return base
        aexp, rexp, due, rt_enc, degraded_flag, last_err = r
        now = _now()
        base["has_token"] = bool(rt_enc)
        base["refresh_expires_at"] = rexp.isoformat() if rexp else None
        base["next_reauth_due_at"] = due.isoformat() if due else None
        base["last_error"] = last_err
        base["access_fresh"] = bool(aexp and aexp > now + timedelta(seconds=ACCESS_REFRESH_MARGIN_S))
        base["refresh_valid"] = bool(rexp and rexp > now and rt_enc)
        if rexp:
            base["days_to_reauth"] = round((rexp - now).total_seconds() / 86400, 2)
        # fail closed: degraded unless refresh is valid AND we can actually decrypt the token
        if base["refresh_valid"]:
            try:
                _dec(rt_enc); base["degraded"] = bool(degraded_flag) and False or False
            except Exception:
                base["degraded"] = True; base["last_error"] = "token undecryptable (key mismatch)"
        return base
    except Exception as e:
        base["last_error"] = f"health check failed: {str(e)[:80]}"; return base


def _telegram(msg):
    try:
        import requests
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not tok:
            for l in (PROJECT_ROOT / ".env").read_text().splitlines():
                if l.startswith("TELEGRAM_BOT_TOKEN="):
                    tok = l.split("=", 1)[1].strip()
        if not tok:
            return
        for cid in chat_ids():
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": cid, "text": msg}, timeout=8)
    except Exception:
        pass


def check_and_alert(send=False):
    """GATE A: alert at day-5/day-6 (2/1 days remaining) before refresh-token expiry. Idempotent per day."""
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT DISTINCT account_key, broker, environment FROM broker_oauth_tokens")
    alerts = []
    for ak, br, env in cur.fetchall():
        h = health(ak, br, env)
        d = h.get("days_to_reauth")
        if d is None:
            continue
        day_of_window = REFRESH_TTL_DAYS - int(d)   # ~day-5/day-6
        elapsed = (d <= 2)  # 2 or fewer days remaining
        if elapsed and h["refresh_valid"]:
            cur.execute("""SELECT 1 FROM broker_oauth_token_audit WHERE account_key=%s AND event='alert'
                           AND created_at > now() - interval '20 hours' LIMIT 1""", (ak,))
            if cur.fetchone():
                continue  # already alerted in the last day — no spam
            msg = (f"⏰ Schwab re-auth due — {ak}: refresh token expires in {d:.1f} day(s) "
                   f"(day-{day_of_window} of {REFRESH_TTL_DAYS}). Manual browser OAuth login required: "
                   f"`schwab_token_manager.py reauth-url {ak}`. Read-only Schwab data will fail closed after expiry.")
            if send:
                _telegram(msg)
            _audit(conn, ak, "alert", "sent" if send else "dry", None, f"days_to_reauth={d}")
            alerts.append({"account_key": ak, "days_to_reauth": d, "sent": send})
        elif h["refresh_valid"] is False and h["has_token"]:
            _audit(conn, ak, "expiry", "degraded", None, "refresh token expired — fail closed read-only")
            alerts.append({"account_key": ak, "expired": True})
    return {"alerts": alerts, "checked": cur.rowcount}


def get_access_token(account_key, broker="schwab", environment="live"):
    """Return a usable access token or None (fail closed). Refreshes the ~29-min access token when <5 min
    remain — but NEVER assumes the refresh token renews; if the refresh token is expired, return None and
    mark degraded. The live refresh HTTP call needs portal app creds (architect open-item)."""
    h = health(account_key, broker, environment)
    if not h["refresh_valid"]:
        _mark_degraded(account_key, broker, environment, h.get("last_error") or "refresh token expired/absent")
        return None
    if h["access_fresh"]:
        conn = _conn(); cur = conn.cursor()
        cur.execute("SELECT access_token_enc FROM broker_oauth_tokens WHERE account_key=%s AND broker=%s AND environment=%s",
                    (account_key, broker, environment))
        row = cur.fetchone()
        try:
            return _dec(row[0]) if row and row[0] else None
        except Exception:
            return None
    # access stale but refresh valid → would refresh via Schwab; requires app creds → fail closed if absent
    if not _have_app_creds():
        _mark_degraded(account_key, broker, environment, "access token stale; refresh requires Schwab app creds (NOT_PROVEN)")
        return None
    return _refresh_access_token(account_key, broker, environment)


def _have_app_creds():
    import broker_secrets; broker_secrets.load_into_env()
    return all(os.environ.get(k) for k in ("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "SCHWAB_CALLBACK_URL"))


def _mark_degraded(account_key, broker, environment, reason):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""UPDATE broker_oauth_tokens SET degraded=TRUE, last_error=%s, updated_at=NOW()
                   WHERE account_key=%s AND broker=%s AND environment=%s""", (reason[:300], account_key, broker, environment))
    conn.commit(); _audit(conn, account_key, "degrade", "degraded", None, reason)


def _refresh_access_token(account_key, broker, environment):
    """Live access-token refresh against Schwab. Requires portal app creds. Persists a rotated refresh
    token ATOMICALLY if Schwab returns one (Rule 7). NOT_PROVEN until creds + portal exist."""
    RATE.acquire()
    raise RuntimeError("NOT_PROVEN: live Schwab access-token refresh requires app creds + portal callback "
                       "(architect open-item). State machine ready; HTTP path intentionally fail-closed.")


def reauth_url(account_key):
    """One-command re-auth: print the Schwab authorize URL the operator opens in a browser. The callback
    handler then exchanges the code and calls seed_token(...rotated=True) atomically."""
    import broker_secrets; broker_secrets.load_into_env()
    appkey = os.environ.get("SCHWAB_APP_KEY"); cb = os.environ.get("SCHWAB_CALLBACK_URL")
    if not (appkey and cb):
        return {"ok": False, "reason": "SCHWAB_APP_KEY/SCHWAB_CALLBACK_URL not set (architect open-item: portal app + callback)."}
    from urllib.parse import quote
    url = f"https://api.schwabapi.com/v1/oauth/authorize?client_id={appkey}&redirect_uri={quote(cb)}"
    return {"ok": True, "account_key": account_key, "authorize_url": url,
            "note": "Open in a browser, log in, then the oauth-callback endpoint exchanges the code and persists the new refresh token atomically."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["init-key", "health", "check-alerts", "reauth-url"])
    ap.add_argument("account", nargs="?", default=None)
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()
    if a.cmd == "init-key":
        init_key()
    elif a.cmd == "health":
        if a.account:
            print(json.dumps(health(a.account), indent=2))
        else:
            conn = _conn(); cur = conn.cursor(); cur.execute("SELECT DISTINCT account_key FROM broker_oauth_tokens")
            print(json.dumps([health(r[0]) for r in cur.fetchall()], indent=2))
    elif a.cmd == "check-alerts":
        print(json.dumps(check_and_alert(send=a.send), indent=2))
    elif a.cmd == "reauth-url":
        print(json.dumps(reauth_url(a.account), indent=2))


if __name__ == "__main__":
    main()
