#!/usr/bin/env python3
"""broker_admin.py — Tier-2 authenticated broker credential admin app.

This is the SECURE place to configure broker API credentials — deliberately NOT the
read-only v3 dashboard. It is:

  - localhost-bound (127.0.0.1 only — never 0.0.0.0); not reachable off-box
  - password-gated (BROKER_ADMIN_PASSWORD env, or an auto-generated password written
    to apps/broker-admin/.admin_password on first run)
  - signed-session-cookie auth (HMAC, httponly); CSRF-token on every write
  - secrets written to config/broker_credentials.env (chmod 600, gitignored) which the
    broker adapters source; values are NEVER echoed back in full (masked to last 4) and
    NEVER logged

It drives the same connectors the v3 panel displays read-only:
Alpaca (live), Schwab, Tastytrade. A "Test" button instantiates the adapter with the
saved credentials and calls get_account()/get_status() to confirm connectivity.

Run:
    .venv/bin/python apps/broker-admin/broker_admin.py            # 127.0.0.1:8788
    BROKER_ADMIN_PORT=8790 .venv/bin/python apps/broker-admin/broker_admin.py
"""
import hashlib
import hmac
import html
import http.server
import json
import os
import secrets
import sys
import urllib.parse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

HOST = "127.0.0.1"
PORT = int(os.environ.get("BROKER_ADMIN_PORT", "8788"))
SECRETS_FILE = PROJECT_ROOT / "config" / "broker_credentials.env"
PASSWORD_FILE = Path(__file__).resolve().parent / ".admin_password"

# Per-process signing secret — restart invalidates existing sessions (fine for single admin)
_SIGNING_SECRET = secrets.token_bytes(32)
_CSRF_SECRET = secrets.token_bytes(32)

# Broker definitions — required credential fields per connector (label-safe; no secrets here)
BROKERS = {
    "alpaca": {
        "name": "Alpaca (paper — LIVE)",
        "fields": [
            ("ENABLE_ALPACA_PAPER", "Enable (true/false)", False),
            ("ALPACA_API_KEY", "API Key ID", True),
            ("ALPACA_SECRET_KEY", "Secret Key", True),
        ],
        "adapter": ("alpaca_paper_adapter", "AlpacaPaperAdapter"),
    },
    "schwab": {
        "name": "Charles Schwab (live — scaffolding)",
        "fields": [
            ("SCHWAB_APP_KEY", "App Key", True),
            ("SCHWAB_APP_SECRET", "App Secret", True),
            ("SCHWAB_REFRESH_TOKEN", "Refresh Token", True),
            ("SCHWAB_ACCT_SCHWAB_ROTH_IRA", "Roth IRA acct # (last 4 ok)", False),
            ("SCHWAB_ACCT_SCHWAB_ROLLOVER_IRA", "Rollover IRA acct # (last 4 ok)", False),
            ("SCHWAB_ACCT_SCHWAB_TAXABLE", "Taxable acct # (last 4 ok)", False),
        ],
        "adapter": ("schwab_adapter", "SchwabAdapter"),
    },
    "tastytrade": {
        "name": "Tastytrade (live — scaffolding)",
        "fields": [
            ("TASTYTRADE_USERNAME", "Username", False),
            ("TASTYTRADE_PASSWORD", "Password", True),
        ],
        "adapter": ("tastytrade_adapter", "TastytradeAdapter"),
    },
}


# ── secrets store ────────────────────────────────────────────────────────────

def load_secrets() -> dict:
    out = {}
    if SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def save_secrets(updates: dict):
    cur = load_secrets()
    for k, v in updates.items():
        if v == "":            # empty submission leaves the existing value untouched
            continue
        cur[k] = v
    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = "# broker_credentials.env — written by broker_admin.py. chmod 600. NEVER commit.\n"
    body += "\n".join(f"{k}={v}" for k, v in sorted(cur.items())) + "\n"
    SECRETS_FILE.write_text(body)
    os.chmod(SECRETS_FILE, 0o600)


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••" + value[-1:]
    return "••••" + value[-4:]


# ── auth ─────────────────────────────────────────────────────────────────────

def admin_password() -> str:
    pw = os.environ.get("BROKER_ADMIN_PASSWORD", "")
    if pw:
        return pw
    if PASSWORD_FILE.exists():
        return PASSWORD_FILE.read_text().strip()
    pw = secrets.token_urlsafe(18)
    PASSWORD_FILE.write_text(pw + "\n")
    os.chmod(PASSWORD_FILE, 0o600)
    print(f"\n*** broker-admin password generated: {pw}\n*** stored at {PASSWORD_FILE} (chmod 600)\n", flush=True)
    return pw


def _sign(secret: bytes, msg: str) -> str:
    return hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()


def make_session() -> str:
    return "authed." + _sign(_SIGNING_SECRET, "authed")


def valid_session(cookie: str) -> bool:
    if not cookie or not cookie.startswith("authed."):
        return False
    return hmac.compare_digest(cookie, make_session())


def csrf_token() -> str:
    return _sign(_CSRF_SECRET, "csrf")


def valid_csrf(tok: str) -> bool:
    return bool(tok) and hmac.compare_digest(tok, csrf_token())


# ── connection test ──────────────────────────────────────────────────────────

def test_broker(broker: str) -> dict:
    spec = BROKERS.get(broker)
    if not spec:
        return {"ok": False, "error": "unknown broker"}
    sec = load_secrets()
    # apply saved creds to the environment for the adapter, then instantiate
    for k, _, _ in spec["fields"]:
        if sec.get(k):
            os.environ[k] = sec[k]
    try:
        import importlib
        mod = importlib.import_module(spec["adapter"][0])
        mod = importlib.reload(mod)
        cls = getattr(mod, spec["adapter"][1])
        inst = cls(dry_run=True)
        status = inst.get_status() if hasattr(inst, "get_status") else {}
        acct = inst.get_account() if getattr(inst, "enabled", False) else {"status": "disabled (no creds)"}
        # never return secret values — only status booleans/labels
        return {"ok": True, "enabled": bool(getattr(inst, "enabled", False)),
                "status": {k: status.get(k) for k in ("authenticated", "configured", "dry_run")},
                "account_status": acct.get("status"), "broker": broker}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


# ── HTML ─────────────────────────────────────────────────────────────────────

PAGE_CSS = """
body{background:#0b0e14;color:#cdd3de;font:13px/1.5 system-ui,sans-serif;margin:0;padding:24px}
h1{font-size:18px}h2{font-size:14px;margin:18px 0 6px}
.card{background:#141925;border:1px solid #232a38;border-radius:10px;padding:16px;margin:12px 0;max-width:680px}
.field{display:flex;align-items:center;gap:10px;margin:6px 0}
.field label{width:230px;color:#8b94a6;font-size:11px}
input{background:#0b0e14;border:1px solid #2a3344;color:#e6ebf2;border-radius:6px;padding:7px 9px;flex:1;font:12px monospace}
.set{color:#22c55e;font-size:11px;font-family:monospace}
button{background:#1d4ed8;color:#fff;border:0;border-radius:6px;padding:8px 16px;font-weight:600;cursor:pointer}
button.ghost{background:#232a38}
.banner{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);color:#f59e0b;border-radius:8px;padding:10px 14px;font-size:11px;max-width:680px}
.warn{color:#ef4444}.muted{color:#6b7686;font-size:10px}.ok{color:#22c55e}
.result{font-family:monospace;font-size:11px;white-space:pre-wrap;background:#0b0e14;border:1px solid #232a38;border-radius:6px;padding:8px;margin-top:8px}
a{color:#60a5fa}
"""


def login_page(error: str = "") -> str:
    err = f'<p class="warn">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html><html><head><meta charset=utf-8><title>Broker Admin</title>
<style>{PAGE_CSS}</style></head><body>
<h1>Broker Admin · login</h1>
<div class=card><form method=post action=/login>
{err}<div class=field><label>Password</label><input type=password name=password autofocus></div>
<button type=submit>Sign in</button></form>
<p class=muted>Localhost-only credential console. Password is in apps/broker-admin/.admin_password (or BROKER_ADMIN_PASSWORD).</p>
</div></body></html>"""


def dashboard(msg: str = "", test_result: dict | None = None) -> str:
    sec = load_secrets()
    tok = csrf_token()
    parts = [f"""<!doctype html><html><head><meta charset=utf-8><title>Broker Admin</title>
<style>{PAGE_CSS}</style></head><body>
<h1>Broker Admin</h1>
<div class=banner><b>Secure credential console.</b> Localhost-only, password-gated. Secrets are written to
config/broker_credentials.env (chmod 600, gitignored) and never echoed back in full. The v3 dashboard only
<i>displays</i> connection status — this app is where credentials are set. <a href=/logout>Sign out</a></div>"""]
    if msg:
        parts.append(f'<div class=card><span class=ok>{html.escape(msg)}</span></div>')
    if test_result is not None:
        parts.append(f'<div class=card><b>Test result</b><div class=result>{html.escape(json.dumps(test_result, indent=2))}</div></div>')
    for bkey, spec in BROKERS.items():
        rows = []
        for k, label, _secret in spec["fields"]:
            cur = sec.get(k, "")
            shown = f'<span class=set>set · {html.escape(mask(cur))}</span>' if cur else '<span class=muted>not set</span>'
            rows.append(f'<div class=field><label>{html.escape(label)}<br><span class=muted>{k}</span></label>'
                        f'<input name="{k}" placeholder="leave blank to keep current"> {shown}</div>')
        parts.append(f"""<div class=card><h2>{html.escape(spec['name'])}</h2>
<form method=post action=/save>
<input type=hidden name=csrf value="{tok}"><input type=hidden name=broker value="{bkey}">
{''.join(rows)}
<button type=submit>Save {html.escape(bkey)}</button>
<button class=ghost type=submit formaction=/test formmethod=post>Test connection</button>
</form></div>""")
    return "".join(parts) + "</body></html>"


# ── HTTP handler ─────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "broker-admin"

    def log_message(self, *a):
        # minimal logging — and NEVER log POST bodies (they carry secrets)
        sys.stderr.write(f"[broker-admin] {self.command} {self.path}\n")

    def _cookie(self) -> str:
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            if part.strip().startswith("session="):
                return part.strip()[len("session="):]
        return ""

    def _authed(self) -> bool:
        return valid_session(self._cookie())

    def _send(self, body: str, code=200, headers=None):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (headers or {}):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location, cookie=None):
        self.send_response(303)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(n).decode() if n else ""
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

    def do_GET(self):
        if self.path == "/logout":
            self._redirect("/", cookie="session=; Max-Age=0; Path=/")
            return
        if not self._authed():
            self._send(login_page())
            return
        self._send(dashboard())

    def do_POST(self):
        if self.path == "/login":
            form = self._body()
            if hmac.compare_digest(form.get("password", ""), admin_password()):
                self._redirect("/", cookie=f"session={make_session()}; HttpOnly; Path=/; SameSite=Strict")
            else:
                self._send(login_page("Incorrect password"), code=401)
            return
        if not self._authed():
            self._send(login_page("Session expired"), code=401)
            return
        form = self._body()
        if not valid_csrf(form.get("csrf", "")):
            self._send(dashboard("CSRF validation failed — reload and retry."), code=400)
            return
        broker = form.get("broker", "")
        if self.path == "/save":
            spec = BROKERS.get(broker, {})
            updates = {k: form.get(k, "") for k, _, _ in spec.get("fields", [])}
            save_secrets(updates)
            self._send(dashboard(f"Saved {broker} credentials to config/broker_credentials.env (chmod 600)."))
            return
        if self.path == "/test":
            spec = BROKERS.get(broker, {})
            # save any newly-entered values first, then test
            updates = {k: form.get(k, "") for k, _, _ in spec.get("fields", [])}
            if any(updates.values()):
                save_secrets(updates)
            self._send(dashboard(test_result=test_broker(broker)))
            return
        self._send(dashboard("Unknown action."), code=404)


def main():
    admin_password()  # ensure a password exists + printed on first run
    httpd = http.server.HTTPServer((HOST, PORT), Handler)
    print(f"[broker-admin] secure credential console on http://{HOST}:{PORT}", flush=True)
    print(f"[broker-admin] secrets file: {SECRETS_FILE}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
