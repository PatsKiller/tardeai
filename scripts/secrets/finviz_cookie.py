#!/usr/bin/env python3
"""FINVIZ_COOKIE: one command to see, sync and set it everywhere (operator tool, 2026-10-05).

Why: the cookie lives in three places, read in this order by resolve_secret:
  1. Bitwarden SM render (tmpfs, /run/user/<uid>/tradeai/env, re-rendered every 4 h)
  2. process environment
  3. disk .env
On 2026-10-05 the operator pasted a new cookie into .env; the tmpfs render still held the old one
and won, so every cookie-based Finviz job kept failing. Bitwarden is the store of record; this tool
writes there through secrets_admin.set_secret (SM → render → .env), then proves all copies match
and the cookie works.

  python3 scripts/secrets/finviz_cookie.py status                # fingerprints + which copy is used
  python3 scripts/secrets/finviz_cookie.py status --probe        # + live Finviz check (read-only)
  python3 scripts/secrets/finviz_cookie.py sync-from-env         # dry run: plan only
  python3 scripts/secrets/finviz_cookie.py sync-from-env --apply # push the .env value to Bitwarden
  python3 scripts/secrets/finviz_cookie.py set --apply           # paste a new value (hidden prompt)

Never prints, logs or returns the cookie: only length and an 8-char sha256 prefix. Run it from the
dev tree (it needs the Bitwarden machine token that the repo environment provides).
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))

from resolve_secret import parse_env_file, render_env_path, validate_finviz_cookie_value  # noqa: E402

KEY = "FINVIZ_COOKIE"


def fingerprint(value: str | None) -> dict:
    v = (value or "").strip()
    if not v:
        return {"present": False, "len": 0, "sha8": None}
    return {"present": True, "len": len(v), "sha8": hashlib.sha256(v.encode()).hexdigest()[:8]}


def copies(*, root: Path | None = None, environ=None) -> dict:
    """Fingerprints of each copy plus which one resolve_secret would use."""
    import os
    root = root or ROOT
    env = os.environ if environ is None else environ
    tmpfs = render_env_path()
    disk = root / ".env"
    render_v = parse_env_file(tmpfs).get(KEY, "") if tmpfs.is_file() else ""
    env_v = env.get(KEY, "")
    disk_v = parse_env_file(disk).get(KEY, "") if disk.is_file() else ""
    out = {"render": {"path": str(tmpfs), **fingerprint(render_v)},
           "process_env": fingerprint(env_v),
           "disk_env": {"path": str(disk), **fingerprint(disk_v)}}
    used = "render" if render_v.strip() else ("process_env" if str(env_v).strip() else ("disk_env" if disk_v.strip() else None))
    present = [k for k in ("render", "process_env", "disk_env") if out[k]["present"]]
    shas = {out[k]["sha8"] for k in present}
    out["in_use"] = used
    out["all_match"] = len(shas) <= 1
    out["drift"] = None if out["all_match"] else (
        f"{used} is used, but differs from " + ", ".join(k for k in present if out[k]["sha8"] != out[used]["sha8"]))
    return out


def probe() -> dict:
    """Run the existing Finviz health check (read-only export probe) and keep only safe fields."""
    try:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "finviz_health_check.py"), "--json"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        t = r.stdout
        d = json.loads(t[t.index("{"):])
        return {k: d.get(k) for k in ("status", "row_count", "credential", "error")}
    except Exception as exc:  # noqa: BLE001
        return {"status": "probe_failed", "error": f"{type(exc).__name__}"}


def write(value: str, *, apply: bool, setter=None, actor: str = "operator:finviz_cookie.py") -> dict:
    """Validate, then (only with apply) write through secrets_admin.set_secret and verify."""
    validate_finviz_cookie_value(value)
    target = fingerprint(value)
    if not apply:
        return {"applied": False, "would_write": target, "next": "re-run with --apply"}
    if setter is None:
        from secrets_admin import set_secret as setter  # type: ignore
    res = setter(KEY, value, actor=actor)
    value = ""  # noqa: F841 - drop the reference
    after = copies()
    ok = bool(res.get("ok")) and after["render"]["sha8"] == target["sha8"] and after["all_match"]
    return {"applied": True, "ok": ok, "set_secret": {k: res.get(k) for k in ("ok", "action", "backend", "render")},
            "target": target, "after": after}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--probe", action="store_true")
    sy = sub.add_parser("sync-from-env", help="push the disk .env value to Bitwarden (store of record)")
    sy.add_argument("--apply", action="store_true")
    sy.add_argument("--probe", action="store_true", default=True)
    st = sub.add_parser("set", help="paste a new cookie at a hidden prompt")
    st.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "status":
        out = copies()
        if a.probe:
            out["probe"] = probe()
        print(json.dumps(out, indent=2))
        return 0 if out["all_match"] else 1

    if a.cmd == "sync-from-env":
        disk = ROOT / ".env"  # read at call time (ROOT may be overridden in tests)
        value = parse_env_file(disk).get(KEY, "") if disk.is_file() else ""
    else:
        value = getpass.getpass(f"Paste new {KEY} (hidden): ").strip()
    try:
        res = write(value, apply=a.apply)
    except ValueError as exc:
        print(json.dumps({"applied": False, "refused": str(exc)}))
        return 2
    finally:
        value = ""
    if res.get("applied"):
        res["probe"] = probe()
        res["ok"] = res["ok"] and res["probe"].get("credential") == "cookie" and not res["probe"].get("error")
    else:
        res["before"] = copies()
    print(json.dumps(res, indent=2))
    return 0 if (not res.get("applied") or res.get("ok")) else 1


if __name__ == "__main__":
    sys.exit(main())
