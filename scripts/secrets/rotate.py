#!/usr/bin/env python3
"""Assisted secret rotation: getpass → SM → render → optional restarts → probe.

  .venv/bin/python scripts/secrets/rotate.py TELEGRAM_BOT_TOKEN
  .venv/bin/python scripts/secrets/rotate.py DB_PASSWORD --generate
Never prints values.
"""
from __future__ import annotations

import argparse
import getpass
import os
import secrets
import string
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))


def _generate(n: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--generate", action="store_true", help="self_minted random value")
    ap.add_argument("--no-restart", action="store_true")
    args = ap.parse_args()
    name = args.name.strip()
    if name.upper().startswith("BWS_"):
        print("REFUSE: BWS_* not rotatable via this tool", file=sys.stderr)
        return 2
    if args.generate:
        value = _generate(40)
        print(f"generated new value for {name} (not shown)")
    else:
        if not sys.stdin.isatty():
            try:
                sys.stdin = open("/dev/tty", "r")
            except OSError:
                print("Need a TTY for getpass, or use --generate", file=sys.stderr)
                return 2
        value = getpass.getpass(f"Paste new value for {name}: ").strip()
    if len(value) < 4:
        print("value too short", file=sys.stderr)
        return 1
    from secrets_admin import set_secret
    res = set_secret(name, value, actor="operator:rotate.py")
    value = ""
    print({k: res.get(k) for k in ("ok", "key", "action", "backend", "rotated")})

    # probes (value-free)
    from rotation_probes import run_probe
    probe = run_probe(name)
    print("probe", probe)

    if not args.no_restart and probe.get("ok"):
        # staged restart only outside market hours is caller's responsibility
        print("restart: use scripts/secrets/staged_restart.sh when window allows")
    return 0 if res.get("ok") and probe.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
