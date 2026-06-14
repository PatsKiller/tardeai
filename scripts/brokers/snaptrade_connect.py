"""snaptrade_connect.py — one-time operator connect flow for SnapTrade.

Two steps, operator-driven:
  1. register_user(user_id)   → mints a userSecret (stored via snaptrade_credentials.save_user)
  2. login_link()             → returns a redirect URL; open it, link the brokerage (e.g. Fidelity 401k)

Needs the client keys saved first (UI modal) and `pip install snaptrade-python-sdk`. No trading; this only
establishes the read connection. After linking, run scripts/snaptrade_sync.py.

  python3 scripts/brokers/snaptrade_connect.py register --user-id john
  python3 scripts/brokers/snaptrade_connect.py login
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brokers import snaptrade_credentials as creds


def _client():
    st = creds.status()
    if not st.get("ready"):
        raise RuntimeError("Client keys not set — add them in the UI modal first (Schwab Accounts → "
                           "Connect SnapTrade).")
    try:
        from snaptrade_client import SnapTrade  # type: ignore
    except Exception as e:
        raise RuntimeError(f"snaptrade-python-sdk not installed ({e}). `pip install snaptrade-python-sdk`.")
    return SnapTrade(consumer_key=os.environ.get(creds.CONSUMER_KEY_KEY, ""),
                     client_id=os.environ.get(creds.CLIENT_ID_KEY, ""))


def register_user(user_id: str) -> dict:
    """Register the end-user with SnapTrade → store the returned userSecret. Idempotent-ish: re-registering
    an existing user_id returns a fresh secret (SnapTrade behavior)."""
    c = _client()
    resp = c.authentication.register_snap_trade_user(body={"userId": user_id})
    body = getattr(resp, "body", resp) or {}
    secret = body.get("userSecret")
    if not secret:
        raise RuntimeError(f"registerUser returned no userSecret: {body}")
    creds.save_user(user_id, secret)
    return {"user_id": user_id, "saved": True}


def login_link(*, redirect_immediate: bool = False) -> str:
    """Return a SnapTrade Connection-Portal URL. Open it in a browser to link a brokerage account."""
    c = _client()
    u = creds.user_status()
    if not u.get("ready"):
        raise RuntimeError("No connected user yet — run `register` first.")
    resp = c.authentication.login_snap_trade_user(
        query_params={"userId": os.environ.get(creds.USER_ID_KEY, ""),
                      "userSecret": os.environ.get(creds.USER_SECRET_KEY, "")})
    body = getattr(resp, "body", resp) or {}
    return body.get("redirectURI") or body.get("redirect_uri") or str(body)


def main():
    ap = argparse.ArgumentParser(description="SnapTrade connect flow (read-only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register"); r.add_argument("--user-id", required=True)
    sub.add_parser("login")
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "register":
        print(register_user(a.user_id))
    elif a.cmd == "login":
        print("Open this URL and link your brokerage:\n", login_link())
    elif a.cmd == "status":
        import json
        print(json.dumps({"client": creds.status(), "user": creds.user_status()}, indent=2))


if __name__ == "__main__":
    main()
