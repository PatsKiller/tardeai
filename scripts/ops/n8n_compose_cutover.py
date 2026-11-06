#!/usr/bin/env python3
"""Move the running n8n from the bake-off folder onto the repo compose (n8n program package 0.1a, 2026-11-06).

ANCHOR: N8N_COMPOSE_CUTOVER_20261106

The production n8n (project ``m8m-n8n``) was started from ``~/m8m-bakeoff-lab/docker-compose.n8n.yml``. The repo now
carries the same file at ``ops/n8n/docker-compose.n8n.yml``; its two secrets come from an env file outside the repo
(default ``~/.config/tradeai/n8n/n8n.env``, mode 0600) instead of the bake-off folder's ``.env``.

Three steps, each its own invocation:

  (default)        dry run, read-only. Proves the repo compose resolves to the SAME compose config hash as each running
                   container (so nothing about the services changes), and counts active workflows. Prints JSON.
  --prepare-env    copies only N8N_PG_PASSWORD and N8N_ENCRYPTION_KEY from the old .env into the new env file, plus
                   N8N_RELAY_GATEWAY read from the live lab network (mode 0600, directory 0700). Values are never
                   printed; the gateway address is kept out of git.
  --apply          only when the dry run passes: recreates the n8n container from the repo compose (same image,
                   volumes and network), waits for /healthz, and refuses success unless the active-workflow count is
                   unchanged. Writes a receipt. It is a restart: run it under the operator's go-ahead, outside market
                   hours.

The old folder is left in place; renaming it to ``…-archived`` is the operator's last step (README). Rollback: start
from the kept old compose (README). No broker, no order path, no production database: MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import stat
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[2]
REPO_COMPOSE = ROOT / "ops" / "n8n" / "docker-compose.n8n.yml"
PROJECT = "m8m-n8n"
SERVICES = {"n8n": "m8m-n8n", "n8n-db": "m8m-n8n-db"}
SECRET_KEYS = ("N8N_PG_PASSWORD", "N8N_ENCRYPTION_KEY")
GATEWAY_KEY = "N8N_RELAY_GATEWAY"
ENV_KEYS = (*SECRET_KEYS, GATEWAY_KEY)
LAB_NETWORK = f"{PROJECT}_lab"
DEFAULT_OLD_ENV = Path.home() / "m8m-bakeoff-lab" / ".env"
DEFAULT_NEW_ENV = Path.home() / ".config" / "tradeai" / "n8n" / "n8n.env"
HEALTH_URL = "http://127.0.0.1:5678/healthz"
ACTIVE_SQL = "select count(*) from workflow_entity where active"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=120, check=False)  # noqa: S603 -- fixed argv list, no shell


def _env_keys(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def env_file_problems(path: Path) -> list[str]:
    """Why ``path`` is not a usable secrets file (names only, never values). Empty when it is."""
    if not path.is_file():
        return [f"env file missing: {path}"]
    probs = []
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        probs.append(f"env file mode {oct(stat.S_IMODE(path.stat().st_mode))} is readable by others; need 0600")
    keys = _env_keys(path)
    probs += [f"env file lacks {k}" for k in ENV_KEYS if not keys.get(k)]
    extra = sorted(set(keys) - set(ENV_KEYS))
    if extra:
        probs.append(f"env file carries keys n8n does not need: {', '.join(extra)}")
    return probs


def lab_gateway(run: Runner) -> str | None:
    """The lab network's gateway address (where the run relay listens), read from docker, or None."""
    cp = run(["docker", "network", "inspect", LAB_NETWORK, "--format", "{{(index .IPAM.Config 0).Gateway}}"])
    val = cp.stdout.strip() if cp.returncode == 0 else ""
    try:
        return str(ipaddress.IPv4Address(val))
    except ValueError:
        return None


def prepare_env(old_env: Path, new_env: Path, run: Runner = _run) -> dict:
    """Write the two n8n secrets plus the lab gateway into ``new_env`` (0600, parent 0700). Never prints a value."""
    old = _env_keys(old_env)
    missing = [k for k in SECRET_KEYS if not old.get(k)]
    if missing:
        return {"ok": False, "error": f"old env lacks {', '.join(missing)}"}
    gw = lab_gateway(run)
    if gw is None:
        return {"ok": False, "error": f"could not read the gateway of docker network {LAB_NETWORK}"}
    want = {**{k: old[k] for k in SECRET_KEYS}, GATEWAY_KEY: gw}
    body = "".join(f"{k}={v}\n" for k, v in want.items())
    if new_env.exists():
        same = _env_keys(new_env) == want
        return {"ok": same, "path": str(new_env), "written": False,
                **({} if same else {"error": "env file exists with different content; left untouched"})}
    new_env.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(new_env.parent, 0o700)
    fd = os.open(new_env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    return {"ok": True, "path": str(new_env), "written": True, "keys": list(ENV_KEYS)}


def compose_argv(env_file: Path, *rest: str) -> list[str]:
    return ["docker", "compose", "-p", PROJECT, "-f", str(REPO_COMPOSE), "--env-file", str(env_file), *rest]


def repo_hashes(env_file: Path, run: Runner) -> dict[str, str]:
    cp = run(compose_argv(env_file, "config", "--hash", "*"))
    if cp.returncode != 0:
        raise RuntimeError(f"docker compose config failed: {(cp.stderr or '').strip()[:300]}")
    out = {}
    for line in cp.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


def live_hashes(run: Runner) -> dict[str, str]:
    out = {}
    for svc, container in SERVICES.items():
        cp = run(["docker", "inspect", container, "--format",
                  '{{index .Config.Labels "com.docker.compose.config-hash"}}'])
        out[svc] = cp.stdout.strip() if cp.returncode == 0 else ""
    return out


def active_workflows(run: Runner) -> int | None:
    cp = run(["docker", "exec", SERVICES["n8n-db"], "psql", "-U", "n8n", "-d", "n8n", "-Atc", ACTIVE_SQL])
    try:
        return int(cp.stdout.strip()) if cp.returncode == 0 else None
    except ValueError:
        return None


def plan(env_file: Path, run: Runner = _run) -> dict:
    """The read-only dry run. ``ok`` only when every check passes."""
    res: dict = {"step": "dry-run", "compose": str(REPO_COMPOSE.relative_to(ROOT)), "env_file": str(env_file),
                 "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    probs = env_file_problems(env_file)
    res["active_workflows"] = active_workflows(run)
    if res["active_workflows"] is None:
        probs.append("could not count active workflows (is m8m-n8n-db running?)")
    if not any(p.startswith("env file missing") or p.startswith("env file lacks") for p in probs):
        try:
            res["repo_hash"] = repo_hashes(env_file, run)
        except RuntimeError as exc:
            probs.append(str(exc))
            res["repo_hash"] = {}
        res["live_hash"] = live_hashes(run)
        for svc in SERVICES:
            if not res["live_hash"].get(svc):
                probs.append(f"{svc}: no running container hash")
            elif res["repo_hash"].get(svc) != res["live_hash"][svc]:
                probs.append(f"{svc}: repo compose hash differs from the running container (the service would change)")
    res["problems"] = probs
    res["ok"] = not probs
    return res


def _healthy(timeout_s: float, sleep: Callable[[float], None]) -> bool:
    """True once /healthz answers 200 inside ``timeout_s``; a refused or failed probe means "not yet", retried."""
    deadline = time.monotonic() + timeout_s
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=5) as r:  # noqa: S310 -- fixed localhost URL
                if r.status == 200:
                    return True
                last_error = f"status {r.status}"
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        sleep(3)
    print(f"n8n not healthy after {timeout_s:.0f}s: {last_error}", file=sys.stderr)
    return False


def apply(env_file: Path, receipt: Path, run: Runner = _run, healthy: Callable[[], bool] | None = None) -> dict:
    pre = plan(env_file, run)
    if not pre["ok"]:
        return {"step": "apply", "ok": False, "refused": "dry run did not pass", "dry_run": pre}
    cp = run(compose_argv(env_file, "up", "-d", "--no-deps", "--force-recreate", "n8n"))
    res = {"step": "apply", "dry_run": pre, "up_rc": cp.returncode, "up_stderr_tail": (cp.stderr or "")[-400:]}
    is_up = cp.returncode == 0 and (healthy or (lambda: _healthy(180, time.sleep)))()
    after = active_workflows(run) if is_up else None
    res.update({"healthy": bool(is_up), "active_before": pre["active_workflows"], "active_after": after,
                "live_hash_after": live_hashes(run),
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    res["ok"] = bool(is_up) and after == pre["active_workflows"]
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    res["receipt"] = str(receipt)
    return res


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env-file", type=Path, default=DEFAULT_NEW_ENV)
    ap.add_argument("--old-env", type=Path, default=DEFAULT_OLD_ENV)
    ap.add_argument("--receipt", type=Path, default=None)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--prepare-env", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if a.prepare_env:
        out = prepare_env(a.old_env, a.env_file)
    elif a.apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = apply(a.env_file, a.receipt or Path.home() / ".cache" / "tradeai" / f"n8n-cutover-{stamp}.json")
    else:
        out = plan(a.env_file)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
