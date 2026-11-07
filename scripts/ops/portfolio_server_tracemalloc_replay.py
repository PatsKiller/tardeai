#!/usr/bin/env python3
"""Replay the Command Center page walk against a SECOND, sandboxed portfolio-server and diff tracemalloc snapshots.

WHY (LQ-20261107-229, 2026-11-07)
    The live portfolio-server grew 1.13 GB -> 1.59 GB RSS (peak 1.97 GB) during one 21-minute walk of the
    70 /v3 pages. RSS cannot say which Python lines hold the memory. This harness answers that, without
    touching the live :7777 process, its data or its sockets.

ISOLATION (each is a hard property of the sandbox, not a convention)
    * ``bwrap``: the whole filesystem is read-only; ``$HOME`` is a copy-on-write tmpfs overlay, so every
      write the second instance makes (stores under persistent-state, logs, boot stamp) lands in RAM and
      disappears with the sandbox. Only the report directory is bound writable.
    * ``--unshare-net``: the instance has its own loopback. It cannot reach :7777, Telegram, an LLM, n8n
      or a broker; the replay browser runs inside the same namespace.
    * ``XDG_RUNTIME_DIR`` and ``~/.config/tradeai`` are fresh tmpfs: the live serve-proxy socket is not
      visible (so it cannot be unlinked or re-bound), and no operator env file is visible.
    * Every ``.env`` / ``*credentials*`` symlink in the build is masked with ``/dev/null``: the instance
      never reads a credential. The DB is reached over the unix socket with peer auth and
      ``PGOPTIONS=-c default_transaction_read_only=on``.
    * PROJECT_ROOT is a copy of the build (symlinks kept, secret-shaped files left out) in the sandbox
      tmpfs, with its ``config/cc_auth.yaml``
      service port changed to ``--port``.
    * Broker-named pages are skipped unless ``--include-broker-pages`` (AGENTS.md rule 2).

USAGE
    portfolio_server_tracemalloc_replay.py --build <release dir> --routes routes.txt --out <dir> --dry-run
    portfolio_server_tracemalloc_replay.py --build <release dir> --routes routes.txt --out <dir> --passes 3
    portfolio_server_tracemalloc_replay.py --report <dir>          # re-rank existing snapshots

OUTPUT (in --out)
    snap-boot.tmsnap, snap-pass<N>.tmsnap   tracemalloc dumps (gc.collect() first), 25 frames
    rss.jsonl                               VmRSS / VmHWM of the second instance at each snapshot
    replay.jsonl                            one row per page: status, seconds, API calls, failures
    report.json, report.md                  top-N growing lines by size_diff for each pass pair, plus the
                                            lines that grew in EVERY pass (the leak candidates)

READ_ONLY_ADVISORY. No order, size, stop or weight path; no live process is signalled.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import tracemalloc
import urllib.request
from pathlib import Path

FRAMES = 25
DEFAULT_PORT = 7787
LIVE_PORT = 7777
TOP_N = 20
SNAP_SIGNAL = signal.SIGUSR1

#: Pages whose name is the broker execution subsystem. Skipped by default (AGENTS.md rule 2).
BROKER_PAGE_RE = re.compile(r"broker|schwab|alpaca|place[-_]?order", re.I)
#: Files that must never be visible to the second instance.
SECRET_NAME_RE = re.compile(r"(^|/)\.env($|\.)|credential|secret|_tokens?\.(json|env|ya?ml)$", re.I)
#: A key with one of these words is never forwarded to the second instance, whatever its source.
SECRET_KEY_RE = re.compile(r"(^|_)(API_)?KEY$|SECRET|(^|_)TOKEN$|PASSWORD|CREDENTIAL|CHAT_IDS$|CHATS$", re.I)

#: Non-secret feature flags the live unit sets (Environment= lines). Copied, not read from systemd, so the
#: harness never reads the operator's env. Outbound senders are forced off; the sandbox has no network anyway.
LIVE_FLAGS = {
    "AGENT_RUNTIME_TIMER_PROBE": "1",
    "TRADEAI_WATCH_DEFAULT_WORKSPACE": "intelligence",
    "AIF_FINANCIAL_SENSES_SHADOW": "1",
    "AGENT_RUN_TRACE": "1",
    "RATIFIED_LESSON_ADVISORY_INFLUENCE": "ACTIVE_ADVISORY",
    "FINANCIAL_SENSES_ADVISORY_INFLUENCE": "ACTIVE_ADVISORY",
    "MEMORY_PROVIDER": "durable",
    "MEMORY_SHADOW": "1",
    "GOVERNED_MEMORY_ADVISORY_INFLUENCE": "SHADOW",
    "AGENT_DECISION_PAYLOAD": "1",
    "MEMORY_ADVERSARIAL_SCAN": "1",
    "AGENT_CONTEXT_ENVELOPE": "1",
    "AGENT_CONTEXT_TOKEN_BUDGET": "4000",
    "AGENT_PROMPT_TOKEN_BUDGET": "8000",
    "AGENT_EMPTY_RAG_MODE": "record",
    "AGENT_NUMBER_GROUNDING_MODE": "enforce",
    "AGENT_NUMBER_GROUNDING_MIN_UNSUPPORTED": "2",
    "AGENT_NUMBER_GROUNDING_MAX_SHARE": "0.20",
    "ACTIVE_TRADER_MOTION_MAX_AGE_S": "60",
    "LLM_DEFER_OFFPEAK": "1",
    # allocator exactly as live (LQ-20261107-88)
    "MALLOC_ARENA_MAX": "2",
    "PYTHONMALLOC": "malloc",
}
#: Forced values: nothing leaves the sandbox, nothing writes as if it were live.
FORCED = {
    "MEMORY_BEHAVIOR_INFLUENCE": "0",
    "ENABLE_TELEGRAM": "0",
    "AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY": "0",
    "CIO_SITUATION_NOTIFY": "0",
    "CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY": "0",
    "PERSISTENT_WAKE_ENABLED": "0",
    "PERSISTENT_WAKE_SCHEDULE_ENABLED": "0",
    "COMMS_GATEWAY_MODE": "OFF",
    "LLM_GLOBAL_DAILY_USD_CAP": "0",
    "PORTFOLIO_SERVER_BIND": "127.0.0.1",
    "PGOPTIONS": "-c default_transaction_read_only=on",
}


# ── pure helpers (unit-tested) ────────────────────────────────────────────────
def load_routes(path: Path, *, include_broker: bool = False) -> tuple[list[str], list[str]]:
    """``(routes, skipped)``: one ``/v3/...`` path per line; blanks and ``#`` comments ignored."""
    routes: list[str] = []
    skipped: list[str] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("/"):
            raise ValueError(f"route must be a path starting with '/': {line!r}")
        if not include_broker and BROKER_PAGE_RE.search(line):
            skipped.append(line)
            continue
        routes.append(line)
    return routes, skipped


def server_env(*, scripts_dir: str, runtime_dir: str, boot_stamp: str, db_user: str, base: dict | None = None) -> dict:
    """The second instance's whole environment. Nothing is inherited except PATH/LANG/HOME/TZ."""
    base = os.environ if base is None else base
    env = {k: base[k] for k in ("PATH", "LANG", "HOME", "TZ") if k in base}
    env.update(LIVE_FLAGS)
    env.update(FORCED)
    env.update(
        {
            "PYTHONPATH": scripts_dir,
            "XDG_RUNTIME_DIR": runtime_dir,
            "PORTFOLIO_SERVER_BOOT_STAMP_PATH": boot_stamp,
            "DB_HOST": "/var/run/postgresql",
            "DB_PORT": "5432",
            "DB_NAME": "trade_ai",
            "DB_USER": db_user,
            "PYTHONUNBUFFERED": "1",
        }
    )
    leaked = sorted(k for k in env if SECRET_KEY_RE.search(k) and k not in FORCED)
    if leaked:
        raise RuntimeError(f"refusing to forward secret-shaped keys to the replay instance: {leaked}")
    return env


def secret_masks(build: Path) -> list[Path]:
    """Resolved targets of every secret-shaped file the build links to or ships (masked with /dev/null)."""
    out: list[Path] = []
    for p in [*build.glob(".env*"), *(build / "config").glob("*")]:
        if not SECRET_NAME_RE.search(p.name):
            continue
        target = p.resolve() if p.is_symlink() else p
        if target.is_file() and target not in out:
            out.append(target)
    return out


def bwrap_argv(*, build: Path, out_dir: Path, home: Path, uid: int, inner: list[str]) -> list[str]:
    """The sandbox. Order matters: later mounts sit on top of earlier ones."""
    argv = [
        "bwrap",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/dev/shm",
        "--tmpfs", "/tmp",
        "--overlay-src", str(home), "--tmp-overlay", str(home),
        "--tmpfs", f"/run/user/{uid}",
        "--tmpfs", str(home / ".config" / "tradeai"),
        "--bind", "/run/postgresql", "/run/postgresql",
        "--unshare-net",
        "--unshare-pid",
        "--die-with-parent",
        "--new-session",
    ]
    for target in secret_masks(build):
        argv += ["--ro-bind", "/dev/null", str(target)]
    argv += ["--bind", str(out_dir), str(out_dir)]
    return argv + ["--"] + inner


def set_service_port(cc_auth_yaml: Path, port: int) -> None:
    """Rewrite ``listeners.service.port`` in the COPY's cc_auth.yaml. Refuses the live port."""
    if port == LIVE_PORT:
        raise ValueError("the replay instance must not use the live port")
    text = cc_auth_yaml.read_text(encoding="utf-8")
    new, n = re.subn(r"(?m)^(\s+port:\s*)7777\b", rf"\g<1>{port}", text, count=1)
    if n != 1:
        raise RuntimeError(f"{cc_auth_yaml}: listeners.service.port 7777 not found")
    cc_auth_yaml.write_text(new, encoding="utf-8")


def _filtered(snap: tracemalloc.Snapshot) -> tracemalloc.Snapshot:
    return snap.filter_traces(
        (
            tracemalloc.Filter(False, tracemalloc.__file__),
            tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
            tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
            tracemalloc.Filter(False, "<unknown>"),
            tracemalloc.Filter(False, __file__),
        )
    )


def _site(frame) -> str:
    return f"{frame.filename}:{frame.lineno}"


def top_growers(prev: tracemalloc.Snapshot, cur: tracemalloc.Snapshot, n: int = TOP_N) -> list[dict]:
    """Top ``n`` lines by size_diff (bytes grown since ``prev``), largest first; shrinking lines excluded."""
    stats = _filtered(cur).compare_to(_filtered(prev), "lineno")
    rows = [
        {
            "site": _site(s.traceback[0]),
            "size_diff": s.size_diff,
            "size": s.size,
            "count_diff": s.count_diff,
            "count": s.count,
        }
        for s in stats
        if s.size_diff > 0
    ]
    rows.sort(key=lambda r: r["size_diff"], reverse=True)
    return rows[:n]


def callers(prev: tracemalloc.Snapshot, cur: tracemalloc.Snapshot, site: str, depth: int = 12) -> list[str]:
    """The biggest growing full traceback that ends at ``site`` (innermost frame last)."""
    best = None
    for s in _filtered(cur).compare_to(_filtered(prev), "traceback"):
        # Traceback frames run oldest -> most recent (3.7+): the allocating line is the LAST frame.
        if s.size_diff > 0 and _site(s.traceback[-1]) == site and (best is None or s.size_diff > best.size_diff):
            best = s
    if best is None:
        return []
    return [_site(f) for f in list(best.traceback)[-depth:]]


def persistent_growers(pairs: list[list[dict]]) -> list[dict]:
    """Lines that grew in EVERY pass-to-pass interval: the leak candidates, ranked by total growth."""
    if not pairs:
        return []
    common = set.intersection(*({r["site"] for r in rows} for rows in pairs))
    total: dict[str, dict] = {}
    for rows in pairs:
        for r in rows:
            if r["site"] in common:
                t = total.setdefault(r["site"], {"site": r["site"], "size_diff": 0, "count_diff": 0, "per_pass": []})
                t["size_diff"] += r["size_diff"]
                t["count_diff"] += r["count_diff"]
                t["per_pass"].append(r["size_diff"])
    return sorted(total.values(), key=lambda r: r["size_diff"], reverse=True)


def build_report(snaps: list[tuple[str, tracemalloc.Snapshot]], n: int = TOP_N, deep: int = 5) -> dict:
    """Consecutive pairs (boot->pass1, pass1->pass2, ...) plus persistent growers across the pass pairs."""
    pairs = []
    for (pa, sa), (pb, sb) in zip(snaps, snaps[1:]):
        rows = top_growers(sa, sb, n)
        for r in rows[:deep]:
            r["callers"] = callers(sa, sb, r["site"])
        pairs.append({"from": pa, "to": pb, "top": rows})
    # boot->pass1 includes first-touch caches; leaks are lines that keep growing AFTER pass 1
    steady = [p["top"] for p in pairs if p["from"] != "boot"]
    full = []
    if len(steady) >= 1:
        # rank against the full stats, not the top-n cut, so a line at #21 in one pass is not lost
        named = dict(snaps)
        steady_full = [top_growers(named[p["from"]], named[p["to"]], 10_000) for p in pairs if p["from"] != "boot"]
        full = persistent_growers(steady_full)[:n] if len(steady_full) > 1 else []
    return {"schema": "TracemallocReplayReport@v1", "frames": FRAMES, "pairs": pairs, "persistent": full}


def render_md(report: dict, rss: list[dict]) -> str:
    out = ["# portfolio-server tracemalloc replay", ""]
    if rss:
        out += ["| snapshot | VmRSS MB | VmHWM MB | traced MB |", "|---|---|---|---|"]
        for r in rss:
            out.append(
                f"| {r['label']} | {r['rss_kb'] / 1024:.0f} | {r['hwm_kb'] / 1024:.0f} | {r.get('traced', 0) / 1e6:.0f} |"
            )
        out.append("")
    for p in report["pairs"]:
        out += [f"## {p['from']} -> {p['to']}: top {len(p['top'])} by size_diff", "",
                "| # | line | +KB | KB now | +count |", "|---|---|---|---|---|"]
        for i, r in enumerate(p["top"], 1):
            out.append(f"| {i} | `{r['site']}` | {r['size_diff'] / 1024:.0f} | {r['size'] / 1024:.0f} | {r['count_diff']} |")
        for r in p["top"]:
            if r.get("callers"):
                out += ["", f"`{r['site']}` called from:", "", *[f"    {c}" for c in r["callers"]]]
        out.append("")
    if report["persistent"]:
        out += ["## Grew in every pass after the first (leak candidates)", "",
                "| line | total +KB | per pass KB |", "|---|---|---|"]
        for r in report["persistent"]:
            per = ", ".join(f"{x / 1024:.0f}" for x in r["per_pass"])
            out.append(f"| `{r['site']}` | {r['size_diff'] / 1024:.0f} | {per} |")
    return "\n".join(out) + "\n"


def report_dir(out: Path) -> dict:
    order = ["boot"] + sorted(
        (p.stem.removeprefix("snap-") for p in out.glob("snap-pass*.tmsnap")), key=lambda s: int(s[4:])
    )
    snaps = [(label, tracemalloc.Snapshot.load(str(out / f"snap-{label}.tmsnap"))) for label in order
             if (out / f"snap-{label}.tmsnap").exists()]
    if len(snaps) < 2:
        raise SystemExit(f"{out}: need at least two snapshots, found {[s[0] for s in snaps]}")
    report = build_report(snaps)
    rss = [json.loads(x) for x in (out / "rss.jsonl").read_text().splitlines()] if (out / "rss.jsonl").exists() else []
    report["rss"] = rss
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_md(report, rss), encoding="utf-8")
    return report


# ── inside the second instance (boot mode) ────────────────────────────────────
def _status_kb(field: str, pid: str = "self") -> int:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith(field + ":"):
            return int(line.split()[1])
    return 0


def boot(server: Path, out: Path) -> None:
    """Run portfolio_server.py as __main__ with tracemalloc on; SIGUSR1 + a label file dump a snapshot."""
    import runpy

    tracemalloc.start(FRAMES)

    def _snap(_signum, _frame):
        label = (out / "next-label").read_text().strip()
        gc.collect()
        snap = tracemalloc.take_snapshot()
        tmp = out / f"snap-{label}.tmsnap.tmp"
        snap.dump(str(tmp))
        os.replace(tmp, out / f"snap-{label}.tmsnap")
        row = {"label": label, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "rss_kb": _status_kb("VmRSS"),
               "hwm_kb": _status_kb("VmHWM"), "traced": tracemalloc.get_traced_memory()[0]}
        with open(out / "rss.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    signal.signal(SNAP_SIGNAL, _snap)
    sys.argv = [str(server)]
    sys.path.insert(0, str(server.parent))
    runpy.run_path(str(server), run_name="__main__")


# ── inside the sandbox (driver mode) ──────────────────────────────────────────
def _wait_health(port: int, proc: subprocess.Popen, timeout: float = 240.0) -> float:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError(f"replay instance exited during boot (rc={proc.returncode})")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as r:  # noqa: S310 -- loopback in a private netns
                if r.status < 500:
                    return time.monotonic() - t0
        except OSError:
            pass
        time.sleep(2)
    raise RuntimeError(f"replay instance not healthy after {timeout:.0f}s")


def _snapshot(proc: subprocess.Popen, out: Path, label: str, timeout: float = 600.0) -> None:
    (out / "next-label").write_text(label)
    target = out / f"snap-{label}.tmsnap"
    proc.send_signal(SNAP_SIGNAL)  # our own child, inside our own pid namespace
    t0 = time.monotonic()
    while not target.exists():
        if time.monotonic() - t0 > timeout:
            raise RuntimeError(f"snapshot {label} not written in {timeout:.0f}s")
        time.sleep(1)


def replay_pass(port: int, routes: list[str], out: Path, label: str, *, batch: int = 6, cap_s: float = 25.0) -> None:
    """Load every page in headless Chromium, ``batch`` at a time, like the page walk. Non-GET /api/ is aborted."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw, open(out / "replay.jsonl", "a", encoding="utf-8") as log:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 412, "height": 915})

        def _route(route):
            req = route.request
            if "/api/" in req.url and req.method != "GET":
                route.abort()
            else:
                route.continue_()

        ctx.route("**/*", _route)
        for i in range(0, len(routes), batch):
            pages = []
            for r in routes[i:i + batch]:
                page = ctx.new_page()
                api: list[dict] = []
                page.on("response", lambda resp, api=api: api.append({"url": resp.url, "status": resp.status})
                        if "/api/" in resp.url else None)
                t0 = time.monotonic()
                try:
                    resp = page.goto(f"http://127.0.0.1:{port}{r}", wait_until="commit", timeout=cap_s * 1000)
                    status = resp.status if resp else None
                except Exception as exc:  # noqa: BLE001 -- recorded per page; the pass continues
                    status = f"{type(exc).__name__}: {exc}"[:200]
                pages.append((r, page, api, t0, status))
            for r, page, api, t0, status in pages:
                try:
                    page.wait_for_load_state("networkidle", timeout=cap_s * 1000)
                    idle = True
                except Exception:  # noqa: BLE001 -- a page that never idles is capped, like the walk
                    idle = False
                row = {"pass": label, "route": r, "status": status, "idle": idle,
                       "seconds": round(time.monotonic() - t0, 1), "api_calls": len(api),
                       "api_failed": sorted({a["url"].split("?")[0] for a in api if a["status"] >= 400})[:20]}
                log.write(json.dumps(row) + "\n")
                page.close()
        ctx.close()
        browser.close()


def drive(args) -> int:
    out = Path(args.out)
    work = Path("/tmp/lq229")  # sandbox tmpfs
    root = work / "root"
    # Secret-shaped files are masked in the sandbox and left out of the copy altogether.
    shutil.copytree(args.build, root, symlinks=True,
                    ignore=lambda _d, names: [n for n in names if SECRET_NAME_RE.search(n)])
    set_service_port(root / "config" / "cc_auth.yaml", args.port)
    env = server_env(scripts_dir=str(root / "scripts"), runtime_dir=f"/run/user/{os.getuid()}",
                     boot_stamp=str(work / "boot.json"), db_user=os.environ.get("USER") or str(os.getuid()))
    py = str(root / ".venv" / "bin" / "python")
    routes, skipped = load_routes(Path(args.routes), include_broker=args.include_broker_pages)
    log = open(out / "server.log", "w", encoding="utf-8")  # noqa: SIM115 -- lives as long as the child
    proc = subprocess.Popen(  # noqa: S603 -- fixed argv, our own copy of the build
        [py, os.path.abspath(__file__), "--boot", str(root / "scripts" / "portfolio_server.py"), "--out", str(out)],
        cwd=str(root), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    meta = {"build": str(args.build), "port": args.port, "routes": len(routes), "skipped": skipped,
            "passes": args.passes, "pid_in_sandbox": proc.pid}
    try:
        meta["boot_s"] = round(_wait_health(args.port, proc), 1)
        time.sleep(args.settle)
        _snapshot(proc, out, "boot")
        for n in range(1, args.passes + 1):
            t0 = time.monotonic()
            replay_pass(args.port, routes, out, f"pass{n}", batch=args.batch)
            meta[f"pass{n}_s"] = round(time.monotonic() - t0, 1)
            time.sleep(args.settle)
            _snapshot(proc, out, f"pass{n}")
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    report_dir(out)
    return 0


# ── outside (launcher) ────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--build", type=Path, help="release directory to run (never the canonical checkout)")
    ap.add_argument("--routes", type=Path, help="file with one /v3/... page per line")
    ap.add_argument("--out", type=Path, help="report directory (the only writable path in the sandbox)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--batch", type=int, default=6)
    ap.add_argument("--settle", type=float, default=15.0, help="seconds idle before each snapshot")
    ap.add_argument("--include-broker-pages", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the sandbox and plan; start nothing")
    ap.add_argument("--report", type=Path, help="re-rank the snapshots already in this directory")
    ap.add_argument("--boot", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--inner", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.report:
        rep = report_dir(args.report)
        print((args.report / "report.md").read_text())
        return 0 if rep["pairs"] else 1
    if args.boot:
        boot(args.boot, args.out)
        return 0
    if args.inner:
        return drive(args)

    if not (args.build and args.routes and args.out):
        ap.error("--build, --routes and --out are required")
    build = args.build.resolve()
    if not (build / "scripts" / "portfolio_server.py").is_file():
        ap.error(f"{build} is not a portfolio-server build")
    if args.port == LIVE_PORT:
        ap.error("--port must not be the live port")
    routes, skipped = load_routes(args.routes, include_broker=args.include_broker_pages)
    out = args.out.resolve()
    inner = [str(build / ".venv" / "bin" / "python"), os.path.abspath(__file__), "--inner",
             "--build", str(build), "--routes", str(out / "routes.txt"), "--out", str(out),
             "--port", str(args.port), "--passes", str(args.passes), "--batch", str(args.batch),
             "--settle", str(args.settle)] + (["--include-broker-pages"] if args.include_broker_pages else [])
    argv_bw = bwrap_argv(build=build, out_dir=out, home=Path.home(), uid=os.getuid(), inner=inner)
    plan = {"build": str(build), "port": args.port, "passes": args.passes, "routes": len(routes),
            "skipped_broker_pages": skipped, "masked": [str(p) for p in secret_masks(build)],
            "env_keys": sorted(server_env(scripts_dir="<copy>/scripts", runtime_dir="<tmpfs>",
                                          boot_stamp="<tmpfs>", db_user="<peer>")),
            "bwrap": argv_bw}
    if args.dry_run:
        print(json.dumps({"dry_run": True, **plan}, indent=1))
        return 0
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.routes, out / "routes.txt")
    (out / "plan.json").write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    rc = subprocess.call(argv_bw)  # noqa: S603 -- fixed argv
    if (out / "report.md").exists():
        print((out / "report.md").read_text())
    return rc


if __name__ == "__main__":
    sys.exit(main())
