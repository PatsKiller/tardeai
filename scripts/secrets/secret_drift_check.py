#!/usr/bin/env python3
"""Secret drift check: does the disk .env disagree with the Bitwarden render? (2026-10-05)

resolve_secret reads the Bitwarden tmpfs render FIRST, so a value edited only in .env is silently
ignored (2026-10-05: a fresh FINVIZ_COOKIE in .env was shadowed by the stale Bitwarden copy). This
compares the two copies key by key and names every key whose values differ. It prints key names,
lengths and 8-char sha256 prefixes only — never a value.

  python3 scripts/secrets/secret_drift_check.py          # exit 1 when any key drifts
  python3 scripts/secrets/secret_drift_check.py --json

Fix a drifted key through the store of record: scripts/secrets/rotate.py <KEY>, the Command Center
Secrets Manager, or (Finviz) scripts/secrets/finviz_cookie.py sync-from-env --apply.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))

from resolve_secret import parse_env_file, render_env_path  # noqa: E402

try:
    from empty_sentinel import EMPTY_SENTINEL  # noqa: E402
except Exception:  # noqa: BLE001
    EMPTY_SENTINEL = "__TRADEAI_EMPTY__"


def _sha8(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()[:8]


def drift(render: dict, disk: dict) -> list[dict]:
    out = []
    for key in sorted(set(render) & set(disk)):
        if key.startswith("BWS_"):
            continue
        r = (render.get(key) or "").strip().strip("'\"")
        d = (disk.get(key) or "").strip().strip("'\"")
        if r == EMPTY_SENTINEL:
            r = ""
        if not r and not d:
            continue
        if r != d:
            out.append({"key": key, "render": {"len": len(r), "sha8": _sha8(r) if r else None},
                        "disk_env": {"len": len(d), "sha8": _sha8(d) if d else None},
                        "in_use": "render" if r else "disk_env"})
    return out


def check(*, render_path: Path | None = None, disk_path: Path | None = None) -> dict:
    rp = render_path or render_env_path()
    dp = disk_path or (ROOT / ".env")
    if not rp.is_file():
        return {"ok": True, "status": "NO_RENDER", "drift": [], "note": "no Bitwarden render; .env is the only copy"}
    if not dp.is_file():
        return {"ok": True, "status": "NO_DISK_ENV", "drift": []}
    d = drift(parse_env_file(rp), parse_env_file(dp))
    return {"ok": not d, "status": "DRIFT" if d else "MATCH", "drift": d,
            "fix": "rotate.py <KEY> / Secrets Manager / finviz_cookie.py sync-from-env --apply" if d else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = check()
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"secret drift: {res['status']} ({len(res['drift'])} key(s))")
        for x in res["drift"]:
            print(f"  {x['key']}: render {x['render']['sha8']} (len {x['render']['len']}) vs .env "
                  f"{x['disk_env']['sha8']} (len {x['disk_env']['len']}) — {x['in_use']} is used")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
