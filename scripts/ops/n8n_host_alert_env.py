#!/usr/bin/env python3
"""Provision the dead-man's least-privilege alert env file (n8n program package 0.4f, 2026-11-06).

ANCHOR: N8N_HOST_ALERT_ENV_20261106

The host dead-man (``scripts/n8n_host_deadman.py``, FW-P6) and the drift watch read their Telegram transport from
``~/.config/tradeai/n8n/host-alert.env`` (the proposed units' ``EnvironmentFile=-``). The packet requires that file to
hold ONLY ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID``, mode 0600, in a 0700 directory. Nothing ever created it, so
an installed dead-man would build its P1 page and then report ``not_configured``: a watcher that pages nobody.

  (default)  dry run, read-only: says which of the two keys the source holds and what is wrong with the target.
  --write    writes the target with exactly the two keys (O_EXCL, 0600; directory 0700). Idempotent when the target
             already holds the same two values; refuses to touch a target that differs.

The source defaults to the runtime env the other host units read (``/run/user/<uid>/tradeai/env``). Values are never
printed. No broker, no order path, no database: MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Sequence

KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
DEFAULT_SOURCE = Path(f"/run/user/{os.getuid()}/tradeai/env")
DEFAULT_TARGET = Path.home() / ".config" / "tradeai" / "n8n" / "host-alert.env"


def _env_keys(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def target_problems(path: Path) -> list[str]:
    """Why ``path`` is not a usable alert env file (key names only, never values). Empty when it is."""
    if not path.is_file():
        return [f"alert env file missing: {path}"]
    probs = []
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        probs.append(f"alert env file mode {oct(mode)} is readable by others; need 0600")
    dmode = stat.S_IMODE(path.parent.stat().st_mode)
    if dmode & 0o077:
        probs.append(f"alert env directory mode {oct(dmode)} is open to others; need 0700")
    keys = _env_keys(path)
    probs += [f"alert env file lacks {k}" for k in KEYS if not keys.get(k)]
    extra = sorted(set(keys) - set(KEYS))
    if extra:
        probs.append(f"alert env file carries keys the dead-man does not need: {', '.join(extra)}")
    return probs


def check(source: Path, target: Path) -> dict:
    """The read-only dry run."""
    res: dict = {"step": "dry-run", "source": str(source), "target": str(target)}
    if source.is_file():
        src = _env_keys(source)
        res["source_has"] = {k: bool(src.get(k)) for k in KEYS}
    else:
        res["source_has"] = None
        res["source_error"] = "source env file missing"
    res["target_problems"] = target_problems(target)
    res["ok"] = res["target_problems"] == []
    res["would_write"] = (not target.exists()) and bool(res["source_has"]) and all(res["source_has"].values())
    return res


def write(source: Path, target: Path) -> dict:
    """Write exactly the two keys to ``target`` (0600, parent 0700). Never prints a value."""
    if not source.is_file():
        return {"step": "write", "ok": False, "error": f"source env file missing: {source}"}
    src = _env_keys(source)
    missing = [k for k in KEYS if not src.get(k)]
    if missing:
        return {"step": "write", "ok": False, "error": f"source lacks {', '.join(missing)}"}
    want = {k: src[k] for k in KEYS}
    if target.exists():
        same = target.is_file() and _env_keys(target) == want
        probs = target_problems(target) if same else []
        return {"step": "write", "ok": same and not probs, "target": str(target), "written": False,
                **({} if same else {"error": "target exists with different content; left untouched"}),
                **({"target_problems": probs} if probs else {})}
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("".join(f"{k}={v}\n" for k, v in want.items()))
    return {"step": "write", "ok": target_problems(target) == [], "target": str(target), "written": True,
            "keys": list(KEYS)}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    out = write(a.source, a.target) if a.write else check(a.source, a.target)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
