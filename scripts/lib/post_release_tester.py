"""Post-release tester — every release is verified, not assumed (AGENTS.md §29, PROPOSED).

One tick (``scripts/post_release_tester.py``, every 10 minutes on the host):

  1. The release: the newest successful promote/rollback row of the deploy receipt history
     (``~/.local/state/cio-phase2-exact-main/deploy_receipt_history.jsonl`` — the train and the manual path both
     release through ``cio_phase2_exact_main_deploy.sh``), else ``CURRENT/BUILD_SHA``.
  2. API checks, once per released SHA, as soon as the release is seen: the post-promote checks of the deploy script
     (``/api/v2/health`` ok, ``/v3/cio`` 200), ``/v3/`` 200, ``CURRENT/BUILD_SHA`` == the released SHA, and the
     release wrapper preflight when the release has admitted it. GET only, one request at a time, after the memory
     gate (portfolio-server ``MemoryCurrent`` <= ``memory_abort_bytes``).
  3. Light browser sweep, once per released SHA: ``scripts/site_sweep.sh`` (PR #2101) on the top routes at the 412 and
     390 viewports, judged only by the "broken" detectors (console errors, uncaught exceptions, HTTP 4xx/5xx except the
     sweeper's expected refusals, route crash) plus page load > ``slow_load_ms``. Never 04:00-16:15 ET on a weekday
     (§28.8): a noon release gets its API checks at noon and its sweep at the first tick after 16:15.
  4. Nightly full sweep at ``nightly.at_et`` (21:30 ET) once a day, when memory allows, until ``until_et``.

Receipts: ``<state root>/data/runtime/post_release_tester/last_{api,light,nightly}.json`` (PostReleaseTest@v1) and
``runs/<run_id>.json``; ``state.json`` remembers what was tested. ``status`` is PASSED, FAILED, DEFERRED (memory gate
or market window) or UNAVAILABLE (sweeper not installed). scripts/delivery_failure_alerts.py pages on FAILED.

Dry run prints the plan and runs nothing. MBI_BEHAVIOR = 0. Authority: READ_ONLY_ADVISORY (no restart, no rollback).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "post_release_tester.json"
SCHEMA = "PostReleaseTest@v1"
TESTER_DIR_REL = "data/runtime/post_release_tester"
ET = ZoneInfo("America/New_York")
PASSED, FAILED, DEFERRED, UNAVAILABLE = "PASSED", "FAILED", "DEFERRED", "UNAVAILABLE"
SWEEP_REFUSED_WINDOW, SWEEP_ABORTED, SWEEP_NO_DISK, SWEEP_NO_DEPS = 3, 2, 4, 5

HttpGet = Callable[[str, float], tuple[int, bytes]]
SweepRunner = Callable[[Mapping[str, str], float], tuple[int, str]]


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    doc = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    if doc.get("schema") != "PostReleaseTesterConfig@v1":
        raise ValueError("post_release_tester config: wrong schema")
    return doc


def _read_json(p: Path) -> Optional[dict]:
    try:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _hm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def browser_blocked(now: datetime, config: Mapping[str, Any]) -> bool:
    """True inside the §28.8 window (weekday 04:00-16:15 ET by default)."""
    b = config.get("browser_blackout_et") or {}
    local = now.astimezone(ET)
    if local.weekday() not in set(b.get("weekdays", [0, 1, 2, 3, 4])):
        return False
    mins = local.hour * 60 + local.minute
    return _hm(b.get("start", "04:00")) <= mins < _hm(b.get("end", "16:15"))


def _default_http_get(url: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "tradeai-post-release-tester"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — loopback, GET only
            return resp.status, resp.read(512_000)
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def _default_memory(unit: str) -> Optional[int]:
    try:
        p = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "MemoryCurrent", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        v = p.stdout.strip()
        return int(v) if v.isdigit() else None
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass
class Env:
    state_root: Path
    deploy_state_dir: Path
    releases_base: Path
    project_root: Path
    now: datetime
    config: dict[str, Any]
    http_get: HttpGet = _default_http_get
    memory: Callable[[], Optional[int]] = field(default=lambda: None)
    sweep_runner: Optional[SweepRunner] = None
    wrapper_runner: Optional[Callable[[Path, Path], tuple[int, str]]] = None
    sleep: Callable[[float], None] = time.sleep

    @property
    def dir(self) -> Path:
        return self.state_root / TESTER_DIR_REL


# ── what was released ──────────────────────────────────────────────────────────────────────────────


def current_release(env: Env) -> dict[str, Any]:
    """{sha, at, source} of the live release (newest ok promote/rollback row, else CURRENT/BUILD_SHA)."""
    try:
        lines = (
            (env.deploy_state_dir / "deploy_receipt_history.jsonl")
            .read_text(encoding="utf-8", errors="replace")
            .splitlines()[-200:]
        )
    except OSError:
        lines = []
    for raw in reversed(lines):
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("ok") is True and row.get("mode") in ("promote", "rollback"):
            sha = str(row.get("deployed_sha") or row.get("sha") or "")
            if sha:
                return {"sha": sha, "at": row.get("at"), "source": "deploy_receipt_history", "mode": row.get("mode")}
    try:
        sha = (env.releases_base / "CURRENT" / "BUILD_SHA").read_text().strip()
        return {"sha": sha, "at": None, "source": "CURRENT/BUILD_SHA", "mode": None}
    except OSError:
        return {"sha": "", "at": None, "source": "none", "mode": None}


def load_state(env: Env) -> dict[str, Any]:
    return _read_json(env.dir / "state.json") or {"schema": "PostReleaseTesterState@v1"}


# ── checks ─────────────────────────────────────────────────────────────────────────────────────────


def memory_ok(env: Env) -> tuple[bool, Optional[int]]:
    m = env.memory()
    limit = int(env.config.get("memory_abort_bytes", 1_300_000_000))
    return (m is None or m <= limit), m


def api_checks(env: Env, release_sha: str) -> list[dict[str, Any]]:
    cfg = env.config
    base = str(cfg.get("base_url") or "http://127.0.0.1:7777").rstrip("/")
    out: list[dict[str, Any]] = []
    for i, c in enumerate(cfg.get("api_checks") or []):
        if i:
            env.sleep(float(cfg.get("request_spacing_s", 1.0)))
        t0 = time.monotonic()
        try:
            status, body = env.http_get(base + c["path"], float(cfg.get("request_timeout_s", 15)))
        except Exception as exc:  # noqa: BLE001 — the failure is the finding
            out.append({"name": c["name"], "ok": False, "detail": f"{type(exc).__name__}: {str(exc)[:120]}"})
            continue
        ok = status == int(c.get("expect_status", 200))
        detail = f"HTTP {status}"
        if ok and c.get("expect_json_ok"):
            try:
                ok = bool(json.loads(body.decode("utf-8", "replace")).get("ok"))
                detail += " ok=" + str(ok).lower()
            except ValueError:
                ok, detail = False, detail + " body not JSON"
        out.append({"name": c["name"], "ok": ok, "detail": detail, "ms": int((time.monotonic() - t0) * 1000)})
    try:
        served = (env.releases_base / "CURRENT" / "BUILD_SHA").read_text().strip()
    except OSError:
        served = ""
    out.append(
        {
            "name": "served_sha",
            "ok": bool(release_sha) and served == release_sha,
            "detail": f"CURRENT/BUILD_SHA {served[:9] or 'missing'} vs released {release_sha[:9] or 'unknown'}",
        }
    )
    out.append(wrapper_check(env))
    return out


def wrapper_check(env: Env) -> dict[str, Any]:
    """The deploy script's post-promote wrapper preflight, read-only, when the live release admitted it."""
    current = env.releases_base / "CURRENT"
    cfg = _read_json(current / "config" / "release_wrapper_preflight.json")
    if not cfg or cfg.get("enabled") is not True:
        return {"name": "wrapper_preflight", "ok": None, "detail": "not admitted on this release (skipped)"}
    runner = env.wrapper_runner
    if runner is None:

        def runner(cur: Path, out: Path) -> tuple[int, str]:  # noqa: E306
            p = subprocess.run(
                [
                    "python3",
                    str(cur / "scripts" / "release_wrapper_preflight.py"),
                    "--current",
                    str(cur),
                    "--config",
                    str(cur / "config" / "release_wrapper_preflight.json"),
                    "--enforce",
                    "--output",
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            return p.returncode, (p.stderr or p.stdout)[-300:]

    rc, tail = runner(current, env.dir / "wrapper_preflight.json")
    return {"name": "wrapper_preflight", "ok": rc == 0, "detail": f"exit {rc} {tail.strip()[:160]}"}


def _default_sweep_runner(project_root: Path) -> SweepRunner:
    def run(extra: Mapping[str, str], timeout: float) -> tuple[int, str]:
        script = project_root / "scripts" / "site_sweep.sh"
        envv = {**os.environ, **extra}
        try:
            p = subprocess.run(
                ["bash", str(script)], env=envv, capture_output=True, text=True, timeout=timeout, check=False
            )
            return p.returncode, (p.stderr or p.stdout)[-400:]
        except subprocess.TimeoutExpired:
            return 124, "timeout"

    return run


def broken_findings(findings_doc: Mapping[str, Any], kinds: list[str], slow_ms: int) -> list[dict[str, Any]]:
    """The sweeper's 'broken' findings this tester judges by, plus loads slower than ``slow_ms``. Pure."""
    want = set(kinds)
    out = [
        {
            "route": f.get("route"),
            "viewport": f.get("viewport"),
            "kind": f.get("kind"),
            "detail": f.get("detail"),
            "sample": (f.get("samples") or [None])[0],
        }
        for f in findings_doc.get("findings") or []
        if f.get("severity") == "broken" and f.get("kind") in want and not f.get("in_flight")
    ]
    for c in findings_doc.get("coverage") or []:
        if int(c.get("load_ms") or 0) > slow_ms:
            out.append(
                {
                    "route": c.get("route"),
                    "viewport": c.get("viewport"),
                    "kind": "slow_load",
                    "detail": f"loaded in {int(c['load_ms']) / 1000:.1f}s (> {slow_ms / 1000:.0f}s)",
                    "sample": None,
                }
            )
    return out


def browser_sweep(env: Env, mode: str, run_id: str) -> dict[str, Any]:
    cfg = env.config.get(mode) or {}
    script = env.project_root / "scripts" / "site_sweep.sh"
    if env.sweep_runner is None and not script.exists():
        return {"status": UNAVAILABLE, "reason": "scripts/site_sweep.sh not on this release (PR #2101)"}
    out_root = env.state_root / "data" / "site_sweep" / f"{mode}-{run_id}"
    extra = {
        "SWEEP_OUT_ROOT": str(out_root),
        "SWEEP_NO_ROUTER_ONLY": "1",
        "SWEEP_BASE_URL": str(env.config.get("base_url") or "http://127.0.0.1:7777"),
    }
    if cfg.get("routes"):
        extra["SWEEP_ROUTES"] = ",".join(cfg["routes"])
    if cfg.get("viewports"):
        extra["SWEEP_VIEWPORTS"] = ",".join(cfg["viewports"])
    runner = env.sweep_runner or _default_sweep_runner(env.project_root)
    rc, tail = runner(extra, float(cfg.get("timeout_s", 1500)))
    try:
        runs = sorted(p for p in out_root.iterdir() if (p / "findings.json").exists())
    except OSError:
        runs = []
    doc = _read_json(runs[-1] / "findings.json") if runs else None
    if rc == SWEEP_REFUSED_WINDOW:
        return {"status": DEFERRED, "reason": "sweeper refused: market-hours window (§28.8)", "exit": rc}
    if rc in (SWEEP_NO_DISK, SWEEP_NO_DEPS):
        return {"status": UNAVAILABLE, "reason": f"sweeper exit {rc}: {tail.strip()[-160:]}", "exit": rc}
    if doc is None:
        return {
            "status": FAILED if rc not in (0, SWEEP_ABORTED) else DEFERRED,
            "reason": f"sweeper exit {rc} wrote no findings.json: {tail.strip()[-160:]}",
            "exit": rc,
        }
    broken = broken_findings(doc, list(cfg.get("broken_kinds") or []), int(cfg.get("slow_load_ms", 15000)))
    summary = str(runs[-1] / "summary.md")
    if broken:
        return {
            "status": FAILED,
            "reason": f"{len(broken)} broken finding(s)",
            "broken": broken[:50],
            "summary_path": summary,
            "exit": rc,
            "aborted": doc.get("aborted"),
        }
    if rc == SWEEP_ABORTED or doc.get("aborted"):
        return {
            "status": DEFERRED,
            "reason": f"sweep aborted: {doc.get('aborted')}",
            "summary_path": summary,
            "exit": rc,
        }
    return {"status": PASSED, "reason": f"{doc.get('routes')} routes, 0 broken", "summary_path": summary, "exit": rc}


# ── one tick ───────────────────────────────────────────────────────────────────────────────────────


def _receipt(
    env: Env, mode: str, run_id: str, release: Mapping[str, Any], status: str, reason: str, **extra: Any
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "mode": mode,
        "run_id": run_id,
        "status": status,
        "reason": reason,
        "release_sha": release.get("sha"),
        "release_source": release.get("source"),
        "released_at": release.get("at"),
        "finished_at": env.now.isoformat(),
        "summary_path": extra.pop("summary_path", None) or str(env.dir / "runs" / f"{run_id}.json"),
        **extra,
    }


def plan(env: Env, state: Mapping[str, Any], release: Mapping[str, Any]) -> list[str]:
    """Which phases this tick would run: subset of api, light, nightly. Pure."""
    sha = release.get("sha") or ""
    todo = []
    if sha and state.get("api_sha") != sha:
        todo.append("api")
    if sha and state.get("light_sha") != sha:
        todo.append("light")
    n = env.config.get("nightly") or {}
    local = env.now.astimezone(ET)
    mins = local.hour * 60 + local.minute
    if _hm(n.get("at_et", "21:30")) <= mins <= _hm(n.get("until_et", "23:45")) and state.get(
        "nightly_date"
    ) != local.strftime("%Y-%m-%d"):
        todo.append("nightly")
    return todo


def tick(env: Env, *, live: bool, force: Optional[list[str]] = None) -> dict[str, Any]:
    from scripts.lib.atomic_json_store import atomic_write_json

    state = load_state(env)
    release = current_release(env)
    phases = list(force) if force else plan(env, state, release)
    report: dict[str, Any] = {
        "schema": "PostReleaseTesterTick@v1",
        "as_of": env.now.isoformat(),
        "mode": "live" if live else "dry_run",
        "release": release,
        "planned": phases,
        "browser_blocked": browser_blocked(env.now, env.config),
        "results": {},
    }
    if not live:
        mem_ok, mem = memory_ok(env)
        report["memory"] = {"ok": mem_ok, "bytes": mem}
        return report
    for phase in phases:
        run_id = f"{phase}-{env.now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        mem_ok, mem = memory_ok(env)
        if not mem_ok:
            rec = _receipt(
                env,
                phase,
                run_id,
                release,
                DEFERRED,
                f"memory gate: portfolio-server {mem / 1e9:.2f} GB > "
                f"{int(env.config.get('memory_abort_bytes', 1.3e9)) / 1e9:.2f} GB",
            )
        elif phase == "api":
            checks = api_checks(env, str(release.get("sha") or ""))
            failed = [c for c in checks if c.get("ok") is False]
            rec = _receipt(
                env,
                phase,
                run_id,
                release,
                FAILED if failed else PASSED,
                f"{len(failed)} of {len(checks)} checks failed" if failed else "all checks passed",
                checks=checks,
            )
        elif browser_blocked(env.now, env.config):
            rec = _receipt(
                env, phase, run_id, release, DEFERRED, "browser sweep deferred: 04:00-16:15 ET weekday window (§28.8)"
            )
        else:
            res = browser_sweep(env, phase, run_id)
            rec = _receipt(env, phase, run_id, release, res.pop("status"), res.pop("reason"), **res)
        atomic_write_json(env.dir / "runs" / f"{run_id}.json", rec)
        if rec["status"] not in (DEFERRED, UNAVAILABLE):
            atomic_write_json(env.dir / f"last_{phase}.json", rec)
            if phase == "api":
                state["api_sha"] = release.get("sha")
            elif phase == "light":
                state["light_sha"] = release.get("sha")
            else:
                state["nightly_date"] = env.now.astimezone(ET).strftime("%Y-%m-%d")
        else:
            atomic_write_json(env.dir / f"deferred_{phase}.json", rec)
        report["results"][phase] = {"status": rec["status"], "reason": rec["reason"], "run_id": run_id}
    state["last_tick_at"] = env.now.isoformat()
    atomic_write_json(env.dir / "state.json", state)
    atomic_write_json(env.dir / "last_tick.json", report)
    return report
