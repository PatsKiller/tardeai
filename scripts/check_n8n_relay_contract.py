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
Exit 0 = PASS, 1 = REFUSED, 2 = could not check (fail closed).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
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
                 ledger_source: Optional[Path] = None) -> None:
        self.relay_root = relay_root
        self.scratch = scratch
        self.python = python
        self.ledger_source = ledger_source
        self.bearer = secrets.token_urlsafe(36)
        self.port = 0
        self.proc: Optional[subprocess.Popen] = None

    def __enter__(self) -> "ScratchRelay":
        state = self.scratch / "state"
        ledger = state / "data" / "governance" / "n8n_coordination_ledger.sqlite"
        _copy_ledger(self.ledger_source, ledger)
        self.port = _free_port()
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.scratch),
            "TRADEAI_N8N_RELAY_BEARER": self.bearer,
            "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": secrets.token_urlsafe(36),
            "TRADEAI_STATE_ROOT": str(state),
            "TRADEAI_N8N_COORDINATION_LEDGER": str(ledger),
            "TRADEAI_N8N_GATEWAY_URL": f"http://127.0.0.1:{_closed_port()}",
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
    a = ap.parse_args(argv)
    ids = [x for x in re.split(r"[,\s]+", a.ids) if x]
    relay_root = a.relay_root.resolve()
    registry = a.registry or relay_root / "config" / "lane_registry.json"
    try:
        if a.no_probe:
            result = check(a.workflows, ids, registry=registry, relay_root=relay_root)
        else:
            scratch = a.scratch or Path(tempfile.mkdtemp(prefix="relay-contract-"))
            scratch.mkdir(parents=True, exist_ok=True)
            with ScratchRelay(relay_root, scratch, python=a.python, ledger_source=a.ledger_source) as relay:
                result = check(a.workflows, ids, registry=registry, relay_root=relay_root, probe=relay.probe)
            result["scratch"] = str(scratch)
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as exc:
        print(json.dumps({"schema": SCHEMA, "verdict": "UNCHECKED", "error": f"{type(exc).__name__}: {exc}"}))
        return 2
    for call in result["calls"]:
        mark = "ok " if call["supported"] else "BAD"
        print(f"{mark} {call['workflow']:26s} {call['method']:4s} {call['path']:62s} timeout={call['timeout_ms']} "
              f"-> {call['evidence']}")
    for f in result["findings"]:
        print(f"REFUSE {f['workflow']} [{f['node']}] {f['code']}: {f['detail']}")
    print(json.dumps({k: v for k, v in result.items() if k != "calls"}, separators=(",", ":")))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
