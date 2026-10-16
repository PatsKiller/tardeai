#!/usr/bin/env python3
"""Operator-only: enroll the Command Center TOTP step-up secret (2026-10-16).

    python3 scripts/cc_totp_enroll.py            # enroll (interactive terminal required)
    python3 scripts/cc_totp_enroll.py --status   # file checks only; never prints the secret

AGENTS: agents never run enrollment and never read the secret file (§0, §24.7). ``--status`` is the only
mode an agent may run; it stats files and prints no secret material.

Enrollment:
  1. Refuses unless stdin and stdout are an interactive terminal and the secret file does not exist.
  2. Generates a 160-bit secret into ``<secret_file>.pending`` (0600, 0700 parent, outside the repo).
  3. Prints the otpauth:// provisioning URI, and a terminal QR code when the ``qrencode`` binary or
     the ``qrcode`` Python package is present (the URI goes to qrencode on stdin, never argv).
  4. Asks for one 6-digit code from the authenticator. Only a correct code activates: the pending file
     is re-written as the activated secret file and the verified counter is recorded in the state file,
     so the enrollment code can never be replayed on the web.
  5. Prints the config change that turns step-up on (``cc_auth.step_up.totp.enabled: true``) — a
     separate, operator-approved config PR. Until then every step-up route refuses as before.
Path overrides: --secret-file / --state-file (default: config/cc_auth.yaml step_up.totp).
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "scripts"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import cc_auth, cc_totp  # noqa: E402


def _paths(args) -> tuple[cc_totp.TotpSettings, Path, Path]:
    cfg = cc_auth.load_config(args.config) if args.config else cc_auth.load_config()
    s = cfg.totp
    secret = Path(os.path.expanduser(args.secret_file)) if args.secret_file else s.secret_file
    state = Path(os.path.expanduser(args.state_file)) if args.state_file else s.state_file
    if secret is None or state is None:
        raise SystemExit("cc_auth.step_up.totp.secret_file / state_file not configured (and no override given)")
    if ROOT in secret.resolve().parents or ROOT in state.resolve().parents:
        raise SystemExit("refusing: secret/state file must live OUTSIDE the repository")
    return s, secret, state


def status(args) -> int:
    s, secret, state = _paths(args)
    pending = secret.with_name(secret.name + ".pending")
    print(f"config enabled : {s.enabled}")
    print(f"actions        : {', '.join(sorted(s.actions)) or '(none)'}")
    print(f"secret file    : {secret} — {cc_totp.check_private_file(secret) or 'present, 0600, owned by you'}")
    print(f"pending file   : {pending} — {'present (enrollment not verified)' if pending.exists() else 'absent'}")
    print(f"state file     : {state} — {cc_totp.check_private_file(state) or 'present, 0600'}")
    mgr = cc_totp.StepUpManager(dataclasses.replace(s, secret_file=secret, state_file=state))
    active, why = mgr.status(read_secret=False)  # stat only: never opens the secret
    print(f"step-up active : {active}{'' if active else ' (' + why + ')'}")
    return 0


def _show_qr(uri: str) -> None:
    exe = shutil.which("qrencode")
    if exe:
        subprocess.run([exe, "-t", "ANSIUTF8"], input=uri.encode(), check=False)
        return
    try:
        import qrcode  # type: ignore
        q = qrcode.QRCode(border=1)
        q.add_data(uri)
        q.print_ascii(invert=True)
    except ImportError:
        print("(no qrencode / qrcode available — type the secret into your authenticator manually,"
              " or install qrencode and re-run after removing the .pending file)")


def enroll(args, *, prompt=input, out=print, clock=time.time, is_tty=None) -> int:
    tty = is_tty if is_tty is not None else (sys.stdin.isatty() and sys.stdout.isatty())
    if not tty:
        out("refusing: enrollment is operator-only and needs an interactive terminal")
        return 2
    s, secret_path, state_path = _paths(args)
    pending = secret_path.with_name(secret_path.name + ".pending")
    if os.path.lexists(secret_path):
        out(f"refusing: {secret_path} already exists. To rotate, move it aside first "
            f"(mv {secret_path} {secret_path}.retired-$(date +%Y%m%d)) and re-run.")
        return 2
    if os.path.lexists(pending):
        out(f"refusing: {pending} exists from an unfinished enrollment. Remove it (shred -u) and re-run.")
        return 2
    account = args.account or (sorted(cc_auth.load_config().allowed_logins) or ["operator"])[0]
    secret_b32 = cc_totp.generate_secret()
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {"schema": cc_totp.SECRET_SCHEMA, "secret_b32": secret_b32, "account": account,
            "issuer": s.issuer, "digits": s.digits, "period": s.period, "algorithm": s.algorithm,
            "created_at": created, "activated_at": None}
    cc_totp.write_private_json(pending, meta, exclusive=True)
    uri = cc_totp.provisioning_uri(secret_b32, account=account, issuer=s.issuer, digits=s.digits,
                                   period=s.period, algorithm=s.algorithm)
    out("Scan this with your authenticator app (or enter the secret manually). Do not screenshot or paste it anywhere.")
    out(uri)
    if not args.no_qr:
        _show_qr(uri)
    key = cc_totp.decode_secret(secret_b32)
    for attempt in range(3):
        code = prompt(f"Enter the {s.digits}-digit code shown by the authenticator: ").strip()
        counter = cc_totp.match_counter(key, code, clock(), period=s.period, digits=s.digits,
                                        algorithm=s.algorithm, window=s.window)
        if counter is not None:
            break
        out(f"wrong code ({2 - attempt} tries left)")
    else:
        out(f"not activated. {pending} left in place; remove it (shred -u) before re-running.")
        return 1
    meta["activated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with cc_totp.state_lock(state_path):
        st, problem = cc_totp.read_state(state_path)
        if st is None:
            out(f"not activated: state file problem ({problem})")
            return 1
        st["last_counter"] = max(st["last_counter"], counter)  # the enrollment code can never be replayed
        st["failures"], st["locked_until"] = [], 0.0
        cc_totp.write_private_json(state_path, st)
        cc_totp.write_private_json(secret_path, meta, exclusive=True)
    os.unlink(pending)
    out(f"ACTIVATED: {secret_path} (0600). The secret is not stored anywhere else.")
    if not s.enabled:
        out("Step-up is still OFF: set cc_auth.step_up.totp.enabled: true in config/cc_auth.yaml "
            "(operator-approved config PR), promote, restart the Command Center.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="file checks only; prints no secret")
    ap.add_argument("--config", help="cc_auth.yaml path (default: repo config / TRADEAI_CC_AUTH_CONFIG)")
    ap.add_argument("--secret-file")
    ap.add_argument("--state-file")
    ap.add_argument("--account", help="label shown in the authenticator (default: first allowed login)")
    ap.add_argument("--no-qr", action="store_true")
    args = ap.parse_args(argv)
    return status(args) if args.status else enroll(args)


if __name__ == "__main__":
    raise SystemExit(main())
