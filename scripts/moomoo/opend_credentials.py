#!/usr/bin/env python3
"""opend_credentials.py — put moomoo OpenD credentials in Bitwarden Secrets Manager.

Stores the MD5 of the login password, never the plaintext: OpenD accepts
-login_pwd_md5 natively, so the reusable password never has to live on this host.
The plaintext is read from a prompt (or stdin), hashed, and discarded.

Before this existed the credential sat in cleartext in OpenD.xml — and the value
there was the vendor placeholder "123456", which is why OpenD logged
"Password does not match" and exited on 2026-07-23.

  .venv/bin/python scripts/moomoo/opend_credentials.py --set
  .venv/bin/python scripts/moomoo/opend_credentials.py --status
  echo -n 'pw' | .venv/bin/python scripts/moomoo/opend_credentials.py --set --account you@x.com --stdin

Writes go through secrets_admin._sm_upsert (bws → project trade-ai-prod), then the
tmpfs render is refreshed so resolve_secret / opend_launch.sh see them immediately.
Values are never printed or logged.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))

KEY_ACCOUNT = "MOOMOO_OPEND_LOGIN_ACCOUNT"
KEY_PWD_MD5 = "MOOMOO_OPEND_LOGIN_PWD_MD5"


def _status() -> int:
    from resolve_secret import resolve_secret, render_env_path
    print(f"render: {render_env_path()} (exists={render_env_path().exists()})")
    ok = True
    for k in (KEY_ACCOUNT, KEY_PWD_MD5):
        v = resolve_secret(k, "")
        print(f"  {k:32s} present={bool(v)}")
        ok = ok and bool(v)
    xml = Path.home() / ".local/opt/trade-ai-lab/moomoo/opend/current/OpenD.xml"
    if xml.exists():
        body = re.sub(r"<!--.*?-->", "", xml.read_text(errors="replace"), flags=re.S)
        for tag in ("login_pwd", "login_pwd_md5", "login_account"):
            if re.search(rf"<{tag}>\s*\S", body):
                print(f"  ⚠ OpenD.xml still carries <{tag}> — credentials belong in Bitwarden")
    return 0 if ok else 1


def _set(account: str | None, use_stdin: bool) -> int:
    import secrets_admin

    if not account:
        account = input("moomoo login account (user id or email): ").strip()
    if not account:
        print("no account supplied", file=sys.stderr)
        return 2

    if use_stdin:
        pwd = sys.stdin.read().strip("\n")
    else:
        pwd = getpass.getpass("moomoo login password (hashed locally, never stored): ")
        confirm = getpass.getpass("confirm: ")
        if pwd != confirm:
            print("passwords do not match", file=sys.stderr)
            return 2
    if not pwd:
        print("empty password", file=sys.stderr)
        return 2
    if pwd == "123456":
        print("that is the vendor placeholder from OpenD.xml, not your real password",
              file=sys.stderr)
        return 2

    md5 = hashlib.md5(pwd.encode("utf-8")).hexdigest()
    del pwd  # plaintext does not outlive this call

    # set_secret = Bitwarden SM upsert → tmpfs render → process env, with audit.
    for key, val in ((KEY_ACCOUNT, account), (KEY_PWD_MD5, md5)):
        secrets_admin.set_secret(key, val, actor="opend_credentials")
        print(f"  {key:32s} stored")
    return _status()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="store_true", help="write credentials to Bitwarden")
    ap.add_argument("--status", action="store_true", help="show presence (never values)")
    ap.add_argument("--account", help="moomoo user id or email")
    ap.add_argument("--stdin", action="store_true", help="read password from stdin")
    a = ap.parse_args()
    if a.set:
        return _set(a.account, a.stdin)
    return _status()


if __name__ == "__main__":
    raise SystemExit(main())
