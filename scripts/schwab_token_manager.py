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

NOTE: live access-token REFRESH HTTP is implemented but GATED behind an operator approval lock in
system_controls — refresh cannot touch Schwab until the operator runs approve-refresh-http with a
typed phrase. Without approval (or app creds) those paths fail closed. exchange-code (manual re-auth)
works independently. The STATE MACHINE, alerts, health, and re-auth persistence are fully functional.

  python3 scripts/schwab_token_manager.py init-key            # one-time: generate the encryption key
  python3 scripts/schwab_token_manager.py health [account]
  python3 scripts/schwab_token_manager.py check-alerts [--send]
  python3 scripts/schwab_token_manager.py refresh-http-status
  python3 scripts/schwab_token_manager.py approve-refresh-http --confirm "APPROVE SCHWAB HTTP REFRESH <YYYY-MM-DD>"
  python3 scripts/schwab_token_manager.py revoke-refresh-http --confirm "REVOKE SCHWAB HTTP REFRESH"
  python3 scripts/schwab_token_manager.py reauth-url <account>                       # STEP 1: get login URL
  python3 scripts/schwab_token_manager.py exchange-code <account> "<redirect URL>"    # STEP 2: SAVE the token
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
SECRETS_FILE = PROJECT_ROOT / "config" / "broker_credentials.env"
ENC_KEY_NAME = "SCHWAB_TOKEN_ENC_KEY"


def _load_broker_secrets_env() -> None:
    """Load local broker credential env names without overriding systemd/tmpfs values.

    Exact-main releases do not copy gitignored broker_credentials.env. Resolve
    the Fernet key from ~/.config/tradeai, this tree, CURRENT, then the
    canonical rebuild file. Values are never logged. Never mint a key here.
    """
    try:
        import broker_secrets
        broker_secrets.load_into_env(force=True)
        return
    except Exception:
        pass
    for path in (
        Path.home() / ".config" / "tradeai" / "broker_credentials.env",
        SECRETS_FILE,
        Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "config" / "broker_credentials.env",
        Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/broker_credentials.env"),
    ):
        try:
            if not path.is_file():
                continue
            for line in path.read_text(errors="replace").splitlines():
                if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key and key not in os.environ:
                    os.environ[key] = value.strip().strip(chr(39) + chr(34))
            break
        except OSError:
            continue


_load_broker_secrets_env()
REFRESH_TTL_DAYS = 7          # GATE A worst case: assume 7d, no roll-forward, until the portal proves otherwise
REAUTH_LEAD_DAYS = 1         # re-auth should happen at least 1 day before expiry
ACCESS_REFRESH_MARGIN_S = 300  # refresh the ~29-min access token when <5 min remain
HTTP_REFRESH_APPROVAL_KEY = "schwab_http_refresh_approved"  # system_controls gate — operator must approve
ALERT_DAYS = {5, 6}          # day-5 and day-6 of the 7-day window (i.e. 2 and 1 days remaining)

RATE_PER_MIN = 100           # conservative shared cap; exact Schwab per-minute number is an architect open-item


def _now():
    return datetime.now(timezone.utc)


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


# ── REFRESH SERIALIZATION (operator 2026-06-21) ──────────────────────────────────────────────────────
# Schwab uses ROTATING refresh tokens: each access-token refresh mints a NEW refresh token and invalidates
# the prior one. Multiple processes share ONE token (server + crons + watchers), and they all woke on the
# same */15 cadence — on 2026-06-16 three refresh tokens were minted within <1s, a classic concurrent-refresh
# race. When a second process refreshes with a now-superseded token, Schwab's reuse-detection revokes the
# WHOLE family (invalid_grant) — exactly what killed the token. Fix: a cross-process Postgres advisory lock
# so only ONE process refreshes at a time; the others wait, then re-read the freshly-rotated token instead
# of racing. Best-effort + self-freeing (statement/idle timeouts) so it can NEVER hang a read.
import threading as _threading
_REFRESH_LOCK_TL = _threading.local()


def _refresh_lock_key(broker, environment):
    h = hashlib.sha256(f"schwab_token_refresh:{broker}:{environment}".encode()).digest()
    return int.from_bytes(h[:8], "big") & 0x7FFFFFFFFFFFFFFF   # stable positive bigint


def _open_lock_conn():
    import psycopg2
    c = psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
                         dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                         password=os.getenv("DB_PASSWORD", ""), connect_timeout=10)
    c.autocommit = True
    try:
        cur = c.cursor()
        cur.execute("SET statement_timeout = 20000")     # never block a read more than 20s waiting for the lock
        cur.execute("SET idle_session_timeout = 60000")  # PG14+: auto-free a leaked lock after 60s idle
    except Exception:
        pass
    return c


def _acquire_refresh_lock(broker="schwab", environment="live"):
    """Take the cross-process refresh lock on a DEDICATED connection. Reentrant: releases any prior lock first
    so a leak from a failed refresh can't accumulate. Best-effort — on timeout/error, proceed WITHOUT the lock
    rather than hang (degrades to old behavior). Held across the schwab-py refresh; released in write_oauth_token."""
    _release_refresh_lock()
    c = None
    try:
        key = _refresh_lock_key(broker, environment)
        c = _open_lock_conn()
        cur = c.cursor()
        cur.execute("SELECT pg_advisory_lock(%s)", (key,)); cur.fetchone()
        _REFRESH_LOCK_TL.conn = c
        _REFRESH_LOCK_TL.key = key
        return True
    except Exception:
        try:
            if c is not None:
                c.close()
        except Exception:
            pass
        return False


def _release_refresh_lock():
    c = getattr(_REFRESH_LOCK_TL, "conn", None)
    if c is None:
        return
    try:
        cur = c.cursor(); cur.execute("SELECT pg_advisory_unlock(%s)", (getattr(_REFRESH_LOCK_TL, "key", None),)); cur.fetchone()
    except Exception:
        pass
    try:
        c.close()
    except Exception:
        pass
    _REFRESH_LOCK_TL.conn = None
    _REFRESH_LOCK_TL.key = None


# ── HTTP REFRESH OPERATOR APPROVAL (fail closed until typed phrase confirms) ─────
def _ensure_system_controls(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS system_controls (
                     key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMPTZ DEFAULT NOW())""")


def _http_refresh_approved():
    """True only when the operator has explicitly armed HTTP access-token refresh via system_controls."""
    try:
        conn = _conn(); cur = conn.cursor()
        _ensure_system_controls(cur)
        cur.execute("SELECT value FROM system_controls WHERE key=%s", (HTTP_REFRESH_APPROVAL_KEY,))
        r = cur.fetchone()
        return bool(r and str(r[0]).lower() == "true")
    except Exception:
        return False


def http_refresh_status():
    """Operator-facing status for the HTTP refresh approval gate."""
    today = _now().date().isoformat()
    approved = _http_refresh_approved()
    return {
        "http_refresh_approved": approved,
        "approval_key": HTTP_REFRESH_APPROVAL_KEY,
        "has_app_creds": _have_app_creds(),
        "approve_phrase": f"APPROVE SCHWAB HTTP REFRESH {today}",
        "revoke_phrase": "REVOKE SCHWAB HTTP REFRESH",
        "note": "Until approved, stale access tokens fail closed — no Schwab refresh HTTP is sent. "
                "Manual re-auth (exchange-code) is unaffected.",
    }


def approve_http_refresh(confirm: str):
    """Arm the HTTP refresh path. Requires today's exact typed phrase — irreversible without revoke."""
    today = _now().date().isoformat()
    want = f"APPROVE SCHWAB HTTP REFRESH {today}"
    if confirm != want:
        return {"ok": False, "error": f"typed confirmation mismatch — must be exactly: {want!r}"}
    if not _have_app_creds():
        return {"ok": False, "error": "SCHWAB_APP_KEY/SECRET/CALLBACK_URL must be set before approving HTTP refresh"}
    conn = _conn(); cur = conn.cursor()
    _ensure_system_controls(cur)
    cur.execute(f"""INSERT INTO system_controls (key, value) VALUES (%s,'true')
                    ON CONFLICT (key) DO UPDATE SET value='true', updated_at=NOW()""",
                (HTTP_REFRESH_APPROVAL_KEY,))
    conn.commit()
    key = canonical_token_key()
    if key:
        _audit(conn, key, "http_refresh_approved", "armed", None, f"operator_phrase={today}")
    return {"ok": True, "http_refresh_approved": True, "status": http_refresh_status(),
            "note": "HTTP refresh ARMED — stale access tokens will refresh against Schwab when requested."}


def revoke_http_refresh(confirm: str):
    """Disarm HTTP refresh — returns to fail-closed until re-approved."""
    if confirm != "REVOKE SCHWAB HTTP REFRESH":
        return {"ok": False, "error": "typed confirmation mismatch — must be exactly: 'REVOKE SCHWAB HTTP REFRESH'"}
    conn = _conn(); cur = conn.cursor()
    _ensure_system_controls(cur)
    cur.execute(f"""INSERT INTO system_controls (key, value) VALUES (%s,'')
                    ON CONFLICT (key) DO UPDATE SET value='', updated_at=NOW()""",
                (HTTP_REFRESH_APPROVAL_KEY,))
    conn.commit()
    key = canonical_token_key()
    if key:
        _audit(conn, key, "http_refresh_revoked", "disarmed", None, "operator_revoke")
    return {"ok": True, "http_refresh_approved": False, "status": http_refresh_status(),
            "note": "HTTP refresh DISARMED — no Schwab refresh HTTP will be sent until re-approved."}


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


def read_oauth_token(account_key, broker="schwab", environment="live"):
    """schwab-py token_read_func target. Returns the token in schwab-py's TokenMetadata-wrapped shape
    {creation_timestamp, token:{...}} (decrypted in-memory) or None. The manager stays system-of-record;
    the wrapper only borrows the live token, never stores it."""
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT access_token_enc, refresh_token_enc, access_expires_at, updated_at, degraded
                   FROM broker_oauth_tokens WHERE account_key=%s AND broker=%s AND environment=%s""",
                (account_key, broker, environment))
    row = cur.fetchone()
    if not row or not row[1]:
        _release_refresh_lock()
        return None
    # Rotating-refresh-token race guard: if the access token is still fresh, NO refresh is coming → don't
    # hold the lock. If it's stale/expiring, a refresh is imminent → take the cross-process lock so only one
    # process refreshes; then RE-READ so if a peer just rotated the token while we waited, we use the new one
    # (and schwab-py sees a fresh access token → skips its own refresh). Released in write_oauth_token.
    # Skip the lock when the token is already degraded (a known-dead token won't refresh — don't stall peers).
    fresh = bool(row[0] and row[2] and row[2] > _now() + timedelta(seconds=ACCESS_REFRESH_MARGIN_S))
    if fresh or row[4]:
        _release_refresh_lock()
    elif not _http_refresh_approved():
        # Operator has not armed HTTP refresh — fail closed; do NOT hand back a stale token for refresh.
        _release_refresh_lock()
        return None
    else:
        # Stale → a refresh is imminent. SINGLE-REFRESHER invariant: only one process/thread may refresh at a
        # time. A peer that refreshes with a now-superseded rotating token trips Schwab's reuse-detection and
        # revokes the WHOLE family (invalid_grant) — the 2026-06-28 21:54 death. So we MUST hold the lock.
        if _acquire_refresh_lock(broker, environment):
            cur.execute("""SELECT access_token_enc, refresh_token_enc, access_expires_at, updated_at, degraded
                           FROM broker_oauth_tokens WHERE account_key=%s AND broker=%s AND environment=%s""",
                        (account_key, broker, environment))
            row = cur.fetchone()
            if not row or not row[1]:
                _release_refresh_lock()
                return None
            # Won the lock — double-check: a peer may have rotated the token while we waited. If it is now
            # fresh, NO refresh will follow, so release the lock immediately (else it leaks until the idle
            # timeout and stalls other refreshers); schwab-py sees a fresh access token and skips its refresh.
            if bool(row[0] and row[2] and row[2] > _now() + timedelta(seconds=ACCESS_REFRESH_MARGIN_S)):
                _release_refresh_lock()
            # else: keep the lock held across schwab-py's refresh; write_oauth_token releases it in finally.
        else:
            # Could NOT serialize within the wait budget (lock held/contended, or lock infra unavailable).
            # FAIL CLOSED: do NOT hand back a stale token for an UNSERIALIZED refresh — that concurrent
            # refresh is exactly what revokes the family. Returning None makes this one read degrade
            # gracefully; the stored token is untouched and the next poll retries once the lock is free.
            return None
    inner = {"token_type": "Bearer", "refresh_token": _dec(row[1])}
    if row[0]:
        inner["access_token"] = _dec(row[0])
    if row[2]:
        inner["expires_at"] = int(row[2].timestamp())
    creation = int(row[3].timestamp()) if row[3] else int(_now().timestamp())
    return {"creation_timestamp": creation, "token": inner}


def write_oauth_token(token, account_key, broker="schwab", environment="live"):
    """schwab-py token_write_func target. schwab-py passes the metadata-wrapped token
    {creation_timestamp, token:{...}}; persist the inner token THROUGH the manager (atomic, encrypted,
    rotation-counted, alerts/health intact) — NEVER the wrapper's own store. Preserves the existing refresh
    token if the refresh response omits it."""
    if not isinstance(token, dict):
        return
    inner = token["token"] if ("token" in token and "creation_timestamp" in token) else token
    rt = inner.get("refresh_token")
    if not rt:
        prior = read_oauth_token(account_key, broker, environment) or {}
        rt = (prior.get("token") or {}).get("refresh_token")
    aexp = inner.get("expires_at")
    a_exp_dt = datetime.fromtimestamp(int(aexp), tz=timezone.utc) if aexp else None
    try:
        return seed_token(account_key, refresh_token=rt, access_token=inner.get("access_token"),
                          access_expires_at=a_exp_dt, broker=broker, environment=environment, rotated=True)
    finally:
        # refresh persisted (or attempted) → release the cross-process refresh lock taken in read_oauth_token
        _release_refresh_lock()


def canonical_token_key(broker="schwab", environment="live"):
    """Schwab issues ONE OAuth token per login covering ALL the user's accounts. Return the account_key that
    holds that live (non-degraded) token, so every account's reads share it (the account HASH distinguishes
    accounts). Avoids refresh-token-rotation conflicts from per-account token copies."""
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT account_key FROM broker_oauth_tokens
                   WHERE broker=%s AND environment=%s AND refresh_token_enc IS NOT NULL AND NOT degraded
                   ORDER BY updated_at DESC LIMIT 1""", (broker, environment))
    r = cur.fetchone()
    return r[0] if r else None


# ── ground-truth degraded marking (operator 2026-06-21) ──────────────────────────────────────────────
# The DB freshness timestamps can say "valid" while Schwab has actually REVOKED the refresh token server-
# side (it returns invalid_grant on use). A pure timestamp health check shows green and never warns. So
# whenever a live Schwab call fails with an auth signature, persist that into the token row — health()
# then reflects reality and the UI can show "re-auth needed" BEFORE the next order attempt.
_AUTH_FAIL_SIGNATURES = ("invalid_grant", "unsupported_token_type", "refresh token is invalid",
                         "expired or revoked", "invalid_client", "token is invalid", "unauthorized_client")


def is_auth_failure(text) -> bool:
    """True if an error string looks like a Schwab OAuth/refresh-token failure (needs manual re-auth)."""
    t = str(text or "").lower()
    return any(sig in t for sig in _AUTH_FAIL_SIGNATURES)


def mark_degraded(error, broker="schwab", environment="live", account_key=None):
    """Mark the (canonical) Schwab token row degraded with last_error. Idempotent; never raises. Called
    reactively when a live call returns an auth failure, so health()/the UI reflect server-side revocation
    that the freshness timestamps alone cannot see. Cleared automatically by a successful re-auth (seed_token)."""
    try:
        conn = _conn(); cur = conn.cursor()
        key = account_key or canonical_token_key(broker, environment)
        if not key:
            return False
        cur.execute("""UPDATE broker_oauth_tokens SET degraded=TRUE, last_error=%s, updated_at=NOW()
                       WHERE account_key=%s AND broker=%s AND environment=%s""",
                    (str(error)[:300], key, broker, environment))
        conn.commit()
        try:
            _audit(conn, key, "degraded_mark", "degraded", None, str(error)[:200])
        except Exception:
            pass
        return True
    except Exception:
        return False


def record_auth_failure(error, broker="schwab", environment="live", account_key=None, source=None):
    """First-line response to Schwab OAuth/refresh failure: mark degraded immediately, alert operator once
    per 4h (stops retry storms + surfaces re-auth need). Never raises."""
    key = account_key or canonical_token_key(broker, environment)
    detail = str(error)[:300]
    mark_degraded(detail, broker, environment, key)
    if not key:
        return False
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("""SELECT 1 FROM broker_oauth_token_audit WHERE account_key=%s AND event='auth_failure_alert'
                       AND created_at > now() - interval '4 hours' LIMIT 1""", (key,))
        if cur.fetchone():
            return True
        src = source or "unknown"
        msg = (f"🚨 Schwab auth failure — {key}: manual re-auth likely required.\n"
               f"Source: {src}\n"
               f"Error: {detail[:120]}\n"
               f"Fix: python3 scripts/schwab_token_manager.py reauth-url {key}")
        _telegram(msg)
        _audit(conn, key, "auth_failure_alert", "sent", None, f"source={src}; {detail[:120]}")
        conn.commit()
    except Exception:
        pass
    return True


def _clear_degraded(account_key, broker="schwab", environment="live"):
    """Clear a degraded flag after a live call proves the token works again. Never raises."""
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("""UPDATE broker_oauth_tokens SET degraded=FALSE, last_error=NULL, updated_at=NOW()
                       WHERE account_key=%s AND broker=%s AND environment=%s AND degraded=TRUE""",
                    (account_key, broker, environment))
        conn.commit()
    except Exception:
        pass


def live_probe(account_key=None, broker="schwab", environment="live"):
    """Ground-truth probe: exercise the SAME authenticated read path an order uses (schwab_transport read
    → schwab-py refresh via the manager hooks) to learn whether the refresh token actually still works,
    WITHOUT placing an order. On an auth failure it marks the token degraded so subsequent health() calls
    are accurate. Returns {probed, live_ok, needs_reauth, error}. Never raises. NOTE: makes one live read
    call — cache the result upstream (the API endpoint does, 5-min TTL) so the UI doesn't probe per render."""
    out = {"probed": False, "live_ok": False, "needs_reauth": False, "error": None}
    try:
        key = account_key or canonical_token_key(broker, environment)
        if not key:
            out["error"] = "no token on file — manual OAuth login required"; out["needs_reauth"] = True
            return out
        import schwab_transport as st
        res = st.get_orders_raw(key)
        out["probed"] = True
        if isinstance(res, list):
            out["live_ok"] = True
            _clear_degraded(key, broker, environment)   # proved usable → self-heal a stale degraded flag
            return out
        # dict ⇒ degraded/NOT_PROVEN/error — inspect for an auth signature
        detail = ""
        if isinstance(res, dict):
            detail = " ".join(str(res.get(k, "")) for k in ("error", "reason", "detail", "body", "status"))
        if is_auth_failure(detail):
            out["needs_reauth"] = True; out["error"] = detail[:240]
            record_auth_failure(detail, broker, environment, key, source="live_probe")
        else:
            out["error"] = (detail or "live read not proven")[:240]
        return out
    except Exception as e:
        if is_auth_failure(str(e)):
            out["needs_reauth"] = True
            record_auth_failure(str(e), broker, environment, account_key, source="live_probe")
        out["error"] = str(e)[:240]
        return out


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
        base["http_refresh_approved"] = _http_refresh_approved()
        # fail closed: degraded unless refresh timestamp is valid AND we can decrypt the token AND the
        # persisted degraded flag is clear. HONOR degraded_flag (was previously masked to False by a buggy
        # `bool(x) and False or False` — that let a server-side-revoked token read 'healthy' on a still-
        # valid timestamp, the exact NOC failure 2026-06-21). A successful re-auth/probe clears the flag.
        if base["refresh_valid"]:
            try:
                _dec(rt_enc); base["degraded"] = bool(degraded_flag)
            except Exception:
                base["degraded"] = True; base["last_error"] = "token undecryptable (key mismatch)"
        return base
    except Exception as e:
        base["last_error"] = f"health check failed: {str(e)[:80]}"; return base


def _telegram(msg):
    """Send via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="schwab_token_manager", subject_key="ops:schwab_token",
                retention_class="operational", severity="urgent",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
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
    mark degraded. HTTP refresh requires operator approval (approve-refresh-http) plus portal app creds."""
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
    # access stale but refresh valid → refresh only when operator has armed HTTP refresh
    if not _http_refresh_approved():
        return None  # fail closed; do NOT mark degraded — waiting for operator approval
    if not _have_app_creds():
        _mark_degraded(account_key, broker, environment, "access token stale; refresh requires Schwab app creds")
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
    """Live access-token refresh against Schwab. Requires operator approval + portal app creds. Persists a
    rotated refresh token ATOMICALLY if Schwab returns one (Rule 7). Serialized via advisory lock."""
    if not _http_refresh_approved():
        return None
    if not _have_app_creds():
        return None
    import base64, requests
    import broker_secrets
    broker_secrets.load_into_env()
    appkey = os.environ.get("SCHWAB_APP_KEY"); secret = os.environ.get("SCHWAB_APP_SECRET")
    RATE.acquire()
    lock_held = False
    try:
        if not _acquire_refresh_lock(broker, environment):
            return None
        lock_held = True
        conn = _conn(); cur = conn.cursor()
        cur.execute("""SELECT access_token_enc, refresh_token_enc, access_expires_at, refresh_expires_at, degraded
                       FROM broker_oauth_tokens WHERE account_key=%s AND broker=%s AND environment=%s""",
                    (account_key, broker, environment))
        row = cur.fetchone()
        if not row or not row[1]:
            return None
        if row[4]:
            return None
        if row[2] and row[2] > _now() + timedelta(seconds=ACCESS_REFRESH_MARGIN_S):
            try:
                return _dec(row[0]) if row[0] else None
            except Exception:
                return None
        rexp = row[3]
        if rexp and rexp <= _now():
            _mark_degraded(account_key, broker, environment, "refresh token expired")
            return None
        try:
            refresh_token = _dec(row[1])
        except Exception:
            _mark_degraded(account_key, broker, environment, "refresh token undecryptable")
            return None
        auth = base64.b64encode(f"{appkey}:{secret}".encode()).decode()
        try:
            resp = requests.post("https://api.schwabapi.com/v1/oauth/token",
                                 headers={"Authorization": f"Basic {auth}",
                                          "Content-Type": "application/x-www-form-urlencoded"},
                                 data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                                 timeout=20)
        except Exception as e:
            _audit(conn, account_key, "access_refresh", "failed", None, str(e)[:200])
            return None
        if resp.status_code != 200:
            detail = f"HTTP {resp.status_code} {resp.text[:140]}"
            if is_auth_failure(detail):
                mark_degraded(detail, broker, environment, account_key)
            _audit(conn, account_key, "access_refresh", "failed", None, detail)
            return None
        tok = resp.json()
        rt = tok.get("refresh_token") or refresh_token
        at = tok.get("access_token")
        exp = tok.get("expires_in")
        if not at:
            _audit(conn, account_key, "access_refresh", "failed", None, "no access_token in response")
            return None
        a_exp = _now() + timedelta(seconds=int(exp)) if exp else None
        seed_token(account_key, refresh_token=rt, access_token=at, access_expires_at=a_exp,
                   broker=broker, environment=environment, rotated=True)
        return at
    finally:
        if lock_held:
            _release_refresh_lock()


def reauth_url(account_key):
    """One-command re-auth: build the Schwab authorize URL the operator opens in a browser. Manual-paste
    flow (works with a 127.0.0.1 callback behind Tailscale — no listening server): log in, copy the full
    redirect URL from the address bar, then `exchange_code(account_key, redirect_url)` seeds the token."""
    import broker_secrets; broker_secrets.load_into_env()
    appkey = os.environ.get("SCHWAB_APP_KEY"); secret = os.environ.get("SCHWAB_APP_SECRET")
    cb = os.environ.get("SCHWAB_CALLBACK_URL")
    if not (appkey and cb):
        return {"ok": False, "reason": "SCHWAB_APP_KEY/SCHWAB_CALLBACK_URL not set (architect open-item: portal app + callback)."}
    # Build the URL the SAME way schwab-py/authlib does — fully percent-encoding the redirect_uri
    # (the prior hand-built URL left the // unencoded as https%3A//127.0.0.1, which Schwab rejects).
    try:
        from authlib.integrations.httpx_client import OAuth2Client
        url, _state = OAuth2Client(appkey, secret, redirect_uri=cb).create_authorization_url(
            "https://api.schwabapi.com/v1/oauth/authorize")
    except Exception:
        from urllib.parse import quote
        url = (f"https://api.schwabapi.com/v1/oauth/authorize?client_id={appkey}"
               f"&redirect_uri={quote(cb, safe='')}&response_type=code")
    return {"ok": True, "account_key": account_key, "authorize_url": url,
            "note": "STEP 1 of 2. Open authorize_url in a browser and log in. Schwab redirects to the callback "
                    "with ?code=... (the page may not load — that's fine). Copy the FULL redirect URL from the "
                    "address bar, then run STEP 2 to actually SAVE the token:",
            "step2_command": f"python3 scripts/schwab_token_manager.py exchange-code {account_key} \"<FULL redirect URL with ?code=...>\""}


def exchange_code(account_key, redirect_url, broker="schwab", environment="live"):
    """Complete the OAuth bootstrap: take the full browser redirect URL (contains ?code=...), exchange the
    authorization code at Schwab for the first access+refresh token, and persist ATOMICALLY via seed_token
    (encrypted system-of-record — no wrapper token file). LIVE call; runs only with real creds + a real code.
    The code/redirect are never logged. Schwab access tokens last ~30 min; refresh tokens ~7 days (Gate A)."""
    import broker_secrets, base64, requests
    from urllib.parse import urlparse, parse_qs
    broker_secrets.load_into_env()
    appkey = os.environ.get("SCHWAB_APP_KEY"); secret = os.environ.get("SCHWAB_APP_SECRET")
    cb = os.environ.get("SCHWAB_CALLBACK_URL")
    if not (appkey and secret and cb):
        return {"ok": False, "reason": "SCHWAB_APP_KEY/SECRET/CALLBACK_URL not set"}
    # Remote/headless friendly: accept EITHER the full https://127.0.0.1/?code=... redirect URL (the page
    # never has to load — we only read the code out of it) OR the bare code pasted directly. Handles the
    # code in the query or the fragment, and URL-decodes a bare code (Schwab codes end with %40 → '@').
    from urllib.parse import unquote
    code = (redirect_url or "").strip().strip('"').strip("'")
    if "code=" in code:
        parsed = urlparse(code)
        q = parse_qs(parsed.query) or parse_qs(parsed.fragment)
        code = (q.get("code") or [""])[0]
    else:
        code = unquote(code)
    if not code:
        return {"ok": False, "reason": "no authorization code found in the redirect URL"}
    RATE.acquire()
    auth = base64.b64encode(f"{appkey}:{secret}".encode()).decode()
    try:
        resp = requests.post("https://api.schwabapi.com/v1/oauth/token",
                             headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
                             data={"grant_type": "authorization_code", "code": code, "redirect_uri": cb}, timeout=20)
    except Exception as e:
        return {"ok": False, "reason": f"token endpoint unreachable: {str(e)[:120]}"}
    if resp.status_code != 200:
        return {"ok": False, "reason": f"Schwab token exchange failed: HTTP {resp.status_code} {resp.text[:140]}"}
    tok = resp.json()
    rt = tok.get("refresh_token"); at = tok.get("access_token"); exp = tok.get("expires_in")
    if not rt:
        return {"ok": False, "reason": "Schwab response had no refresh_token"}
    a_exp = _now() + timedelta(seconds=int(exp)) if exp else None
    res = seed_token(account_key, refresh_token=rt, access_token=at, access_expires_at=a_exp,
                     broker=broker, environment=environment, rotated=False)
    return {"ok": True, "account_key": account_key, "refresh_expires_at": res["refresh_expires_at"],
            "next_reauth_due_at": res["next_reauth_due_at"], "scope": tok.get("scope"),
            "note": "First token seeded via the manager (Fernet-encrypted, atomic). No wrapper token file."}


def _load_dotenv():
    """Load PROJECT_ROOT/.env into the environment so the CLI works standalone over SSH (the portal creds
    SCHWAB_APP_KEY/SECRET/CALLBACK live there; broker_secrets does not read .env). setdefault = never
    override an already-exported value. Best-effort."""
    try:
        envf = PROJECT_ROOT / ".env"
        if not envf.exists():
            return
        for line in envf.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


def main():
    _load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["init-key", "health", "check-alerts", "reauth-url", "exchange-code",
                                    "refresh-http-status", "approve-refresh-http", "revoke-refresh-http"])
    ap.add_argument("account", nargs="?", default=None)
    ap.add_argument("redirect_url", nargs="?", default=None,
                    help="for exchange-code: the FULL browser redirect URL containing ?code=...")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--confirm", default="", help="typed phrase for approve-refresh-http / revoke-refresh-http")
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
    elif a.cmd == "refresh-http-status":
        print(json.dumps(http_refresh_status(), indent=2))
    elif a.cmd == "approve-refresh-http":
        print(json.dumps(approve_http_refresh(a.confirm), indent=2, default=str))
    elif a.cmd == "revoke-refresh-http":
        print(json.dumps(revoke_http_refresh(a.confirm), indent=2, default=str))
    elif a.cmd == "reauth-url":
        print(json.dumps(reauth_url(a.account), indent=2))
    elif a.cmd == "exchange-code":
        # STEP 2 of re-auth: exchange the browser ?code=... for tokens + persist (this is what actually
        # saves the new login — reauth-url alone does NOT). Redirect URL is never logged.
        if not (a.account and a.redirect_url):
            print(json.dumps({"ok": False, "reason": "usage: exchange-code <account> \"<full redirect URL with ?code=...>\""}, indent=2))
        else:
            res = exchange_code(a.account, a.redirect_url)
            res.pop("redirect_url", None)
            print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
