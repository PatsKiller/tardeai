#!/usr/bin/env python3
"""Pre-import contract check: every generic n8n workflow HTTP node against the relay it will call.

2026-10-10 (W0 relay fix). W0 imported and published the six generic workflows (design 02 §11) and rolled them
back five minutes later: the incident router's `POST /event` came back 404 `relay_bad_path` (the relay served no
such route) and three workflows' `GET /due?...&lane=` filters came back 403 `bad_lane_filter` (they named lane ids
with no registry row). Neither was visible to the import dry run, which checked JSON shape only. This check makes
both visible before anything is imported, and refuses:

  * unsupported_route        an HTTP node's method + path is not served by the relay (probe: 404 relay_bad_path,
                             405, or 400 relay_bad_query from a scratch relay started from --relay-root; or, with
                             --no-probe, absent from the relay's declared ROUTES table)
  * route_table_unknown      --no-probe and the relay declares no ROUTES table (fail closed)
  * lane_filter_unknown      a `lane=` value on /due is not a row of --registry (the gateway answers bad_lane_filter)
  * http_timeout_missing     an HTTP node without options.timeout > 0
  * http_timeout_exceeds_execution   options.timeout is longer than the workflow's executionTimeout
  * execution_timeout_missing        settings.executionTimeout absent or not a positive int
  * save_manual_executions_true      settings.saveManualExecutions is true (open item F4 / P19)

The probe never touches the live relay, the live gateway or the live ledger. It starts `<relay-root>/scripts/
n8n_run_relay.py` on 127.0.0.1:<free port> with a random scratch bearer and key, TRADEAI_STATE_ROOT in a scratch
directory (its relay_log.jsonl lands there), the coordination ledger pointed at a scratch copy (or an empty file),
and the gateway URL pointed at a closed loopback port, so a forwarded request can only come back
relay_gateway_unreachable. POST probes carry `{}`, which every relay version refuses before forwarding.

Concurrency probe (2026-10-10, RC11 lesson; on by default with the probe). The route probe sends one call at a time,
so it could not see the W0 re-run failure: n8n fires the dispatcher, event-router, incident-router and
digest-scheduler on the same minute, the gateway (CPUQuota=20%) answered 2-4 concurrent /due calls after the relay's
5 s urlopen timeout, and every one came back relay_gateway_unreachable (fixed by #1667). This step starts a SECOND
scratch relay wired to a scratch gateway (`<relay-root>/scripts/n8n_coordination_gateway.py`, scratch keys, the
scratch ledger copy, `--registry`, the relay root's run allowlist and retry policies), throttles the gateway process
to the CPUQuota of the gateway unit file (SIGSTOP/SIGCONT duty cycle over a 100 ms period, the CFS default period),
and fires N concurrent GET /due with the workflows' real query shapes (N = --concurrency, default the number of
workflows checked, at least 3), first against a cold gateway (the minute after a restart), then warm. Every call
must come back 200 DueResponse@v1 ok within the relay timeout x (1 - --concurrency-margin). Refusals:

  * due_concurrency_refused  a concurrent /due call did not come back 200 DueResponse@v1 ok (e.g. 502
                             relay_gateway_unreachable: the gateway answered after the relay gave up)
  * due_concurrency_slow     a call came back ok but slower than the budget (relay timeout minus the margin)
  * due_concurrency_unknown  the CPU quota (unit file) or the relay timeout could not be read (fail closed)
  * due_concurrency_not_run  --require-concurrency and the step did not run (--no-probe / --no-concurrency /
                             no /due call in the selected workflows)

Exit 0 = PASS, 1 = REFUSED, 2 = could not check (fail closed).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOWS = ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows"
RELAY_EXPR = "={{ $('Relay').first().json.TRADEAI_N8N_RUN_URL }}"
HTTP_TYPE = "n8n-nodes-base.httpRequest"
SCHEMA = "N8nRelayContractCheck@v1"
#: The relay refuses ports below 1024 and the gateway's BLOCKED_PORTS; a free ephemeral port is always above both.
_UNSUPPORTED_REASONS = frozenset({"relay_bad_path", "relay_bad_query"})
GATEWAY_UNIT_REL = Path("config") / "systemd" / "user" / "tradeai-n8n-coordination-gateway.service"
CONCURRENCY_MIN = 3
CONCURRENCY_MARGIN = 0.5          # every call must finish inside half the relay timeout
CONCURRENCY_ROUNDS = 2            # cold (first minute after a gateway restart), then warm
THROTTLE_PERIOD_S = 0.1           # CFS default cpu.cfs_period_us = 100 ms


def _finding(wid: str, node: str, code: str, detail: str) -> dict[str, str]:
    return {"workflow": wid, "node": node, "code": code, "detail": detail}


def http_calls(doc: dict) -> list[dict[str, Any]]:
    """(node, method, path, query, timeout_ms) for each HTTP Request node; path/query split from the relay URL."""
    out = []
    for node in doc.get("nodes") or []:
        if node.get("type") != HTTP_TYPE:
            continue
        params = node.get("parameters") or {}
        url = str(params.get("url") or "")
        rest = url[len(RELAY_EXPR):] if url.startswith(RELAY_EXPR) else url
        path, _, query = rest.partition("?")
        timeout = (params.get("options") or {}).get("timeout")
        out.append({"node": str(node.get("name")), "method": str(params.get("method") or "GET").upper(),
                    "path": path, "query": query, "timeout_ms": timeout, "via_relay": url.startswith(RELAY_EXPR)})
    return out


def registry_lane_ids(path: Path) -> set[str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("lanes") if isinstance(doc, dict) else doc
    return {str(r["lane_id"]) for r in rows or [] if isinstance(r, dict) and r.get("lane_id")}


def declared_routes(relay_source: Path) -> Optional[set[tuple[str, str]]]:
    """The relay's ROUTES literal, read with ast (nothing is imported or run); None when it declares none."""
    try:
        tree = ast.parse(relay_source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for stmt in tree.body:
        target = stmt.target if isinstance(stmt, ast.AnnAssign) else (
            stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None)
        if isinstance(target, ast.Name) and target.id == "ROUTES" and stmt.value is not None:
            try:
                return {(str(m), str(p)) for m, p in ast.literal_eval(stmt.value)}
            except (ValueError, TypeError):
                return None
    return None


def route_in_table(method: str, path: str, table: set[tuple[str, str]]) -> bool:
    if (method, path) in table:
        return True
    parts = path.split("/")
    return (method, "/runs/<lane_id>/last") in table and len(parts) == 4 and parts[1] == "runs" and \
        parts[3] == "last" and bool(re.fullmatch(r"[A-Za-z0-9._-]+", parts[2]))


def static_findings(wid: str, doc: dict, lanes: set[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    settings = doc.get("settings") or {}
    exec_timeout = settings.get("executionTimeout")
    if isinstance(exec_timeout, bool) or not isinstance(exec_timeout, int) or exec_timeout <= 0:
        out.append(_finding(wid, "-", "execution_timeout_missing", f"settings.executionTimeout={exec_timeout!r}"))
        exec_timeout = None
    if settings.get("saveManualExecutions") is not False:
        out.append(_finding(wid, "-", "save_manual_executions_true",
                            f"settings.saveManualExecutions={settings.get('saveManualExecutions')!r} (F4/P19)"))
    for call in http_calls(doc):
        t = call["timeout_ms"]
        if isinstance(t, bool) or not isinstance(t, int) or t <= 0:
            out.append(_finding(wid, call["node"], "http_timeout_missing", f"options.timeout={t!r}"))
        elif exec_timeout is not None and t > exec_timeout * 1000:
            out.append(_finding(wid, call["node"], "http_timeout_exceeds_execution",
                                f"options.timeout={t} ms > executionTimeout={exec_timeout} s"))
        if call["path"] == "/due" and call["query"]:
            params = parse_qs(call["query"], keep_blank_values=True)
            for value in params.get("lane", []):
                for lane in (x for x in value.split(",") if x):
                    if lane not in lanes:
                        out.append(_finding(wid, call["node"], "lane_filter_unknown",
                                            f"lane={lane} is not a registry row (gateway: bad_lane_filter)"))
    return out


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _closed_port() -> int:
    """A loopback port nothing listens on (bound then released), so a forwarded call is refused at once."""
    return _free_port()


def _copy_ledger(source: Optional[Path], dest: Path) -> None:
    """Scratch ledger: a read-only sqlite backup of ``source`` (never opened for write), else an empty file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source is None:
        sqlite3.connect(dest).close()
        return
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _request(port: int, method: str, path_query: str, bearer: str, timeout: float = 5.0) -> tuple[int, dict]:
    data = b"{}" if method == "POST" else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path_query}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    try:
        body = json.loads(raw.decode() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = {}
    return status, body if isinstance(body, dict) else {}


class ScratchRelay:
    """`<relay_root>/scripts/n8n_run_relay.py` on 127.0.0.1 with scratch secrets, state root and ledger."""

    def __init__(self, relay_root: Path, scratch: Path, *, python: str = sys.executable,
                 ledger_source: Optional[Path] = None, gateway_url: Optional[str] = None,
                 n8n_key: Optional[str] = None, copy_ledger: bool = True) -> None:
        self.relay_root = relay_root
        self.scratch = scratch
        self.python = python
        self.ledger_source = ledger_source
        self.gateway_url = gateway_url
        self.n8n_key = n8n_key or secrets.token_urlsafe(36)
        self.copy_ledger = copy_ledger
        self.bearer = secrets.token_urlsafe(36)
        self.port = 0
        self.proc: Optional[subprocess.Popen] = None

    @property
    def ledger(self) -> Path:
        return self.scratch / "state" / "data" / "governance" / "n8n_coordination_ledger.sqlite"

    def __enter__(self) -> "ScratchRelay":
        state = self.scratch / "state"
        ledger = self.ledger
        self.scratch.mkdir(parents=True, exist_ok=True)
        if self.copy_ledger:
            _copy_ledger(self.ledger_source, ledger)
        self.port = _free_port()
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.scratch),
            "TRADEAI_N8N_RELAY_BEARER": self.bearer,
            "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": self.n8n_key,
            "TRADEAI_STATE_ROOT": str(state),
            "TRADEAI_N8N_COORDINATION_LEDGER": str(ledger),
            "TRADEAI_N8N_GATEWAY_URL": self.gateway_url or f"http://127.0.0.1:{_closed_port()}",
            "TRADEAI_N8N_RELAY_LIVE_LANES": "",
            "TRADE_AI_CI": os.environ.get("TRADE_AI_CI", "1"),
        }
        if os.environ.get("PYTHONPATH"):
            env["PYTHONPATH"] = os.environ["PYTHONPATH"]
        log = (self.scratch / "relay.stdout").open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [self.python, str(self.relay_root / "scripts" / "n8n_run_relay.py"), "--host", "127.0.0.1",
             "--port", str(self.port)],
            cwd=str(self.scratch), env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"scratch relay exited {self.proc.returncode}: "
                                   f"{(self.scratch / 'relay.stdout').read_text()[:300]}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("scratch relay did not listen within 15 s")

    def __exit__(self, *_exc: Any) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)

    def probe(self, method: str, path: str, query: str) -> tuple[bool, str]:
        status, body = _request(self.port, method, path + (f"?{query}" if query else ""), self.bearer)
        reason = str(body.get("reason") or body.get("state") or "")
        supported = not (status in (404, 405) or reason in _UNSUPPORTED_REASONS)
        return supported, f"{status} {reason}".strip()


# ── concurrency probe (RC11) ─────────────────────────────────────────────────────────────────────────


def unit_cpu_quota(unit: Path) -> Optional[float]:
    """CPUQuota=NN% of a systemd unit file as a fraction (0.2 for 20%); None when absent or unreadable."""
    try:
        text = unit.read_text(encoding="utf-8")
    except OSError:
        return None
    found = None
    for line in text.splitlines():
        m = re.fullmatch(r"\s*CPUQuota\s*=\s*([0-9]+(?:\.[0-9]+)?)%\s*", line)
        if m:
            found = float(m.group(1)) / 100.0          # the last assignment wins, as in systemd
    return found if found and found > 0 else None


def relay_timeout_s(relay_source: Path) -> Optional[float]:
    """The relay's gateway urlopen timeout (Relay._transport), read from source; None when not a literal."""
    try:
        text = relay_source.read_text(encoding="utf-8")
    except OSError:
        return None
    hits = {float(x) for x in re.findall(r"urlopen\([^)]*?timeout\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*\)", text)}
    return min(hits) if hits else None


def due_shapes(workflows: Path, ids: Iterable[str], lanes: set[str]) -> list[dict[str, str]]:
    """Each selected workflow's GET /due query, as the workflow sends it. A shape whose lane= filter names a
    non-registry lane is left out (the static check already refuses it as lane_filter_unknown)."""
    index = json.loads((workflows / "INDEX.json").read_text(encoding="utf-8"))
    rows = {w["id"]: w for w in index.get("workflows") or []}
    out: list[dict[str, str]] = []
    for wid in ids:
        if wid not in rows:
            continue
        doc = json.loads((workflows / rows[wid]["file"]).read_text(encoding="utf-8"))
        for call in http_calls(doc):
            if call["method"] != "GET" or call["path"] != "/due" or not call["via_relay"]:
                continue
            named = [x for v in parse_qs(call["query"], keep_blank_values=True).get("lane", []) for x in v.split(",") if x]
            if any(x not in lanes for x in named):
                continue
            out.append({"workflow": wid, "node": call["node"], "query": call["query"]})
    return out


class CpuThrottle:
    """Hold a process to ``quota`` of one CPU: SIGCONT for quota x period, SIGSTOP for the rest, every period.

    A stand-in for the unit's CPUQuota (cgroup CFS bandwidth, 100 ms period) that needs no systemd or cgroup write.
    Python serialises the gateway's request threads on the GIL, so one CPU's worth of duty cycle is the quota."""

    def __init__(self, pid: int, quota: float, period_s: float = THROTTLE_PERIOD_S) -> None:
        if not 0 < quota <= 1:
            raise ValueError(f"quota {quota} outside (0, 1]")
        self.pid, self.quota, self.period_s = pid, quota, period_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.cycles = 0

    def _loop(self) -> None:
        on, off = self.quota * self.period_s, (1 - self.quota) * self.period_s
        try:
            while not self._stop.is_set():
                os.kill(self.pid, signal.SIGCONT)
                time.sleep(on)
                if off <= 0 or self._stop.is_set():
                    continue
                os.kill(self.pid, signal.SIGSTOP)
                time.sleep(off)
                self.cycles += 1
        except ProcessLookupError:
            return
        finally:
            try:
                os.kill(self.pid, signal.SIGCONT)
            except ProcessLookupError:
                pass

    def __enter__(self) -> "CpuThrottle":
        if self.quota < 1:
            self._thread = threading.Thread(target=self._loop, name="cpu-throttle", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        try:
            os.kill(self.pid, signal.SIGCONT)            # never leave the scratch gateway stopped
        except ProcessLookupError:
            pass


class ScratchGateway:
    """`<relay_root>/scripts/n8n_coordination_gateway.py` on 127.0.0.1 with scratch keys and the scratch ledger."""

    def __init__(self, relay_root: Path, scratch: Path, ledger: Path, registry: Path, *,
                 python: str = sys.executable) -> None:
        self.relay_root, self.scratch, self.ledger, self.registry, self.python = relay_root, scratch, ledger, registry, python
        self.key = secrets.token_urlsafe(36)
        self.n8n_key = secrets.token_urlsafe(36)
        self.port = 0
        self.proc: Optional[subprocess.Popen] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "ScratchGateway":
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.port = _free_port()
        cfg = self.relay_root / "config"
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.scratch),
            "TRADEAI_N8N_GATEWAY_HMAC_KEY": self.key,
            "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": self.n8n_key,
            "TRADEAI_STATE_ROOT": str(self.scratch / "state"),
            "TRADEAI_N8N_COORDINATION_LEDGER": str(self.ledger),
            "TRADE_AI_CI": os.environ.get("TRADE_AI_CI", "1"),
        }
        if os.environ.get("PYTHONPATH"):
            env["PYTHONPATH"] = os.environ["PYTHONPATH"]
        log = (self.scratch / "gateway.stdout").open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [self.python, str(self.relay_root / "scripts" / "n8n_coordination_gateway.py"), "--host", "127.0.0.1",
             "--port", str(self.port), "--expected-sha", "0" * 40, "--ledger", str(self.ledger),
             "--registry", str(self.registry), "--run-allowlist", str(cfg / "n8n_run_allowlist.json"),
             "--retry-policies", str(cfg / "n8n_retry_policies.json")],
            cwd=str(self.scratch), env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"scratch gateway exited {self.proc.returncode}: "
                                   f"{(self.scratch / 'gateway.stdout').read_text()[:300]}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("scratch gateway did not listen within 30 s")

    def __exit__(self, *_exc: Any) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.kill(self.proc.pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)


def concurrent_due(port: int, bearer: str, queries: list[str], *, client_timeout: float) -> list[dict[str, Any]]:
    """Fire every query at once through the relay; one row per call (status, reason, ok, wall seconds)."""
    barrier = threading.Barrier(len(queries))

    def call(q: str) -> dict[str, Any]:
        barrier.wait()
        t0 = time.perf_counter()
        try:
            status, body = _request(port, "GET", f"/due?{q}", bearer, timeout=client_timeout)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            status, body = 0, {"reason": f"client_{type(exc).__name__}"}
        wall = time.perf_counter() - t0
        ok = status == 200 and body.get("schema") == "DueResponse@v1" and body.get("ok") is True
        return {"query": q, "status": status, "reason": str(body.get("reason") or body.get("state") or ""),
                "ok": ok, "wall_s": round(wall, 3)}

    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        return list(pool.map(call, queries))


def concurrency_check(shapes: list[dict[str, str]], *, n: int, relay_root: Path, registry: Path, scratch: Path,
                      ledger: Path, python: str, quota: Optional[float], timeout_s: Optional[float],
                      margin: float = CONCURRENCY_MARGIN, rounds: int = CONCURRENCY_ROUNDS) -> dict[str, Any]:
    """{verdict, n, quota, relay_timeout_s, budget_s, rounds:[...], findings:[...]} for N concurrent /due calls
    through a scratch relay wired to a CPU-throttled scratch gateway. ``ledger`` is the scratch copy (never live)."""
    out: dict[str, Any] = {"n": n, "cpu_quota": quota, "relay_timeout_s": timeout_s, "margin": margin,
                           "shapes": [s["workflow"] for s in shapes], "rounds": [], "findings": []}
    if quota is None or timeout_s is None:
        out["findings"].append(_finding("-", "-", "due_concurrency_unknown",
                                        f"cpu_quota={quota} relay_timeout_s={timeout_s}: cannot set the budget"))
        out["verdict"] = "REFUSED"
        return out
    budget = round(timeout_s * (1 - margin), 3)
    out["budget_s"] = budget
    queries = [shapes[i % len(shapes)]["query"] for i in range(n)]
    owners = [shapes[i % len(shapes)]["workflow"] for i in range(n)]
    with ScratchGateway(relay_root, scratch / "gateway", ledger, registry, python=python) as gw, \
            ScratchRelay(relay_root, scratch / "relay-concurrency", python=python, gateway_url=gw.url,
                         n8n_key=gw.n8n_key, copy_ledger=False) as relay:
        assert gw.proc is not None
        for rnd in range(rounds):
            with CpuThrottle(gw.proc.pid, quota) as thr:
                rows = concurrent_due(relay.port, relay.bearer, queries, client_timeout=timeout_s + 10)
            for row, wid in zip(rows, owners):
                row["workflow"] = wid
            label = "cold" if rnd == 0 else f"warm{rnd}"
            out["rounds"].append({"round": label, "throttle_cycles": thr.cycles,
                                  "max_wall_s": max(r["wall_s"] for r in rows), "calls": rows})
            for r in rows:
                if not r["ok"]:
                    out["findings"].append(_finding(r["workflow"], "GET /due", "due_concurrency_refused",
                                                    f"{label} n={n} quota={quota:.0%}: {r['status']} {r['reason']} "
                                                    f"after {r['wall_s']} s ({r['query']})"))
                elif r["wall_s"] > budget:
                    out["findings"].append(_finding(r["workflow"], "GET /due", "due_concurrency_slow",
                                                    f"{label} n={n} quota={quota:.0%}: {r['wall_s']} s > budget "
                                                    f"{budget} s (relay timeout {timeout_s} s, margin {margin:.0%})"))
    out["verdict"] = "REFUSED" if out["findings"] else "PASS"
    return out


def check(workflows: Path, ids: Optional[Iterable[str]], *, registry: Path, relay_root: Path,
          probe: Optional[Callable[[str, str, str], tuple[bool, str]]] = None) -> dict[str, Any]:
    """Findings for every selected workflow. ``probe(method, path, query) -> (supported, evidence)``; None means
    the static ROUTES table of ``relay_root`` is the route source."""
    index = json.loads((workflows / "INDEX.json").read_text(encoding="utf-8"))
    rows = {w["id"]: w for w in index.get("workflows") or []}
    wanted = list(ids) if ids else sorted(rows)
    unknown_ids = [w for w in wanted if w not in rows]
    lanes = registry_lane_ids(registry)
    table = None if probe is not None else declared_routes(relay_root / "scripts" / "n8n_run_relay.py")
    findings: list[dict[str, str]] = [_finding(w, "-", "unknown_workflow_id", "not in INDEX.json") for w in unknown_ids]
    calls_out: list[dict[str, Any]] = []
    cache: dict[tuple[str, str, str], tuple[bool, str]] = {}
    for wid in (w for w in wanted if w in rows):
        doc = json.loads((workflows / rows[wid]["file"]).read_text(encoding="utf-8"))
        findings.extend(static_findings(wid, doc, lanes))
        for call in http_calls(doc):
            key = (call["method"], call["path"], call["query"])
            if not call["via_relay"]:
                result = (False, "url does not start with the Relay set-node expression")
            elif probe is not None:
                if key not in cache:
                    cache[key] = probe(*key)
                result = cache[key]
            elif table is None:
                result = (False, "relay declares no ROUTES table")
                findings.append(_finding(wid, call["node"], "route_table_unknown", "use the probe"))
            else:
                ok = route_in_table(call["method"], call["path"], table)
                result = (ok, "in ROUTES" if ok else "not in ROUTES")
            if not result[0] and not any(f["node"] == call["node"] and f["workflow"] == wid
                                         and f["code"] == "route_table_unknown" for f in findings):
                findings.append(_finding(wid, call["node"], "unsupported_route",
                                         f"{call['method']} {call['path']} -> {result[1]}"))
            calls_out.append({"workflow": wid, "node": call["node"], "method": call["method"],
                              "path": call["path"] + (f"?{call['query']}" if call["query"] else ""),
                              "timeout_ms": call["timeout_ms"], "supported": result[0], "evidence": result[1]})
    return {"schema": SCHEMA, "verdict": "REFUSED" if findings else "PASS", "workflows": wanted,
            "relay_root": str(relay_root), "registry": str(registry),
            "route_source": "probe" if probe is not None else "static_ROUTES", "calls": calls_out,
            "findings": findings}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workflows", type=Path, default=DEFAULT_WORKFLOWS, help="dir holding INDEX.json + the files")
    ap.add_argument("--ids", default="", help="comma/space list of workflow ids (default: every INDEX row)")
    ap.add_argument("--relay-root", type=Path, default=ROOT,
                    help="release or worktree root whose scripts/n8n_run_relay.py is checked (served: CURRENT)")
    ap.add_argument("--registry", type=Path, default=None,
                    help="lane registry the gateway reads (default: <relay-root>/config/lane_registry.json)")
    ap.add_argument("--no-probe", action="store_true", help="static ROUTES table only; no scratch relay")
    ap.add_argument("--ledger-source", type=Path, default=None,
                    help="sqlite ledger to COPY (read-only backup) into the scratch relay; default an empty one")
    ap.add_argument("--scratch", type=Path, default=None, help="scratch dir (default: a new temp dir, kept)")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--concurrency", type=int, default=0,
                    help=f"concurrent GET /due calls (default: number of workflows checked, at least {CONCURRENCY_MIN})")
    ap.add_argument("--concurrency-margin", type=float, default=CONCURRENCY_MARGIN,
                    help="fraction of the relay timeout every call must leave unused (default 0.5)")
    ap.add_argument("--gateway-unit", type=Path, default=None,
                    help="unit file whose CPUQuota is simulated (default: <relay-root>/" + str(GATEWAY_UNIT_REL)
                         + ", else this tree's)")
    ap.add_argument("--no-concurrency", action="store_true", help="skip the concurrent /due probe")
    ap.add_argument("--require-concurrency", action="store_true",
                    help="refuse (due_concurrency_not_run) unless the concurrent /due probe ran")
    a = ap.parse_args(argv)
    ids = [x for x in re.split(r"[,\s]+", a.ids) if x]
    relay_root = a.relay_root.resolve()
    registry = a.registry or relay_root / "config" / "lane_registry.json"
    conc: Optional[dict[str, Any]] = None
    try:
        if a.no_probe:
            result = check(a.workflows, ids, registry=registry, relay_root=relay_root)
        else:
            scratch = a.scratch or Path(tempfile.mkdtemp(prefix="relay-contract-"))
            scratch.mkdir(parents=True, exist_ok=True)
            with ScratchRelay(relay_root, scratch, python=a.python, ledger_source=a.ledger_source) as relay:
                result = check(a.workflows, ids, registry=registry, relay_root=relay_root, probe=relay.probe)
                scratch_ledger = relay.ledger
            result["scratch"] = str(scratch)
            shapes = [] if a.no_concurrency else due_shapes(a.workflows, result["workflows"], registry_lane_ids(registry))
            if shapes:
                unit = a.gateway_unit or next((p for p in (relay_root / GATEWAY_UNIT_REL, ROOT / GATEWAY_UNIT_REL)
                                               if p.is_file()), relay_root / GATEWAY_UNIT_REL)
                n = a.concurrency or max(CONCURRENCY_MIN, len(result["workflows"]))
                conc = concurrency_check(shapes, n=n, relay_root=relay_root, registry=registry, scratch=scratch,
                                         ledger=scratch_ledger, python=a.python, quota=unit_cpu_quota(unit),
                                         timeout_s=relay_timeout_s(relay_root / "scripts" / "n8n_run_relay.py"),
                                         margin=a.concurrency_margin)
                conc["gateway_unit"] = str(unit)
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as exc:
        print(json.dumps({"schema": SCHEMA, "verdict": "UNCHECKED", "error": f"{type(exc).__name__}: {exc}"}))
        return 2
    if conc is not None:
        result["findings"].extend(conc["findings"])
        result["concurrency"] = {k: v for k, v in conc.items() if k not in ("rounds", "findings")}
        result["concurrency"]["rounds"] = [{k: v for k, v in r.items() if k != "calls"} for r in conc["rounds"]]
        result["concurrency"]["verdict"] = conc["verdict"]
    else:
        result["concurrency"] = {"verdict": "NOT_RUN", "reason": "--no-probe" if a.no_probe else (
            "--no-concurrency" if a.no_concurrency else "no GET /due call in the selected workflows")}
        if a.require_concurrency:
            result["findings"].append(_finding("-", "-", "due_concurrency_not_run", result["concurrency"]["reason"]))
    result["verdict"] = "REFUSED" if result["findings"] else "PASS"
    for call in result["calls"]:
        mark = "ok " if call["supported"] else "BAD"
        print(f"{mark} {call['workflow']:26s} {call['method']:4s} {call['path']:62s} timeout={call['timeout_ms']} "
              f"-> {call['evidence']}")
    for rnd in (conc or {}).get("rounds") or []:
        for c in rnd["calls"]:
            mark = "ok " if c["ok"] and c["wall_s"] <= conc["budget_s"] else "BAD"
            print(f"{mark} concurrency {rnd['round']:5s} n={conc['n']} quota={conc['cpu_quota']:.0%} "
                  f"{c['workflow']:26s} GET /due?{c['query']:52s} -> {c['status']} {c['reason'] or 'ok'} "
                  f"{c['wall_s']} s (budget {conc['budget_s']} s)")
    for f in result["findings"]:
        print(f"REFUSE {f['workflow']} [{f['node']}] {f['code']}: {f['detail']}")
    print(json.dumps({k: v for k, v in result.items() if k != "calls"}, separators=(",", ":")))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
