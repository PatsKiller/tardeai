"""Relay contract check: concurrent GET /due under the gateway unit's CPU quota (RC11 lesson, 2026-10-10).

W0 re-run 17:14 ET: n8n fires the dispatcher, event-router, incident-router and digest-scheduler on the same minute;
the gateway (CPUQuota=20%) answered 2-4 concurrent /due calls after the relay's 5 s urlopen timeout and every one came
back 502 relay_gateway_unreachable (fixed by #1667). scripts/check_n8n_relay_contract.py probed one call at a time and
passed. These tests pin the concurrency probe it now runs: the CPU quota is read from the unit file, the relay
timeout from the relay source, the workflows' own /due queries are fired together through a scratch relay wired to a
CPU-throttled scratch gateway, and a slow or refused call refuses the import.

Hermetic: every relay / gateway is a loopback child under tmp_path with scratch keys; no live relay, gateway, ledger
or n8n. The negative end-to-end case uses a stub gateway that burns CPU per call like the pre-#1667 matcher did.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_n8n_relay_contract as C  # noqa: E402

WORKFLOWS = ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows"
REGISTRY = ROOT / "config" / "lane_registry.json"
FOUR = ["tradeai-dispatcher", "tradeai-event-router", "tradeai-incident-router", "tradeai-digest-scheduler"]

pytestmark = pytest.mark.skipif(os.name != "posix", reason="SIGSTOP/SIGCONT duty cycle is POSIX only")


# ── inputs: quota, relay timeout, query shapes ──────────────────────────────────────────────────────

def test_cpu_quota_is_read_from_the_gateway_unit(tmp_path):
    assert C.unit_cpu_quota(ROOT / C.GATEWAY_UNIT_REL) == pytest.approx(0.20)
    unit = tmp_path / "u.service"
    unit.write_text("[Service]\nCPUQuota=50%\n# CPUQuota=1%\nCPUQuota=12.5%\n")
    assert C.unit_cpu_quota(unit) == pytest.approx(0.125)             # last assignment wins, comments ignored
    unit.write_text("[Service]\nMemoryMax=256M\n")
    assert C.unit_cpu_quota(unit) is None
    assert C.unit_cpu_quota(tmp_path / "missing.service") is None


def test_relay_timeout_is_read_from_the_relay_source(tmp_path):
    assert C.relay_timeout_s(ROOT / "scripts" / "n8n_run_relay.py") == pytest.approx(5.0)
    src = tmp_path / "r.py"
    src.write_text("urlopen(request, timeout=TIMEOUT)\n")
    assert C.relay_timeout_s(src) is None                                # not a literal: fail closed upstream


def test_due_shapes_are_the_workflows_own_queries():
    shapes = C.due_shapes(WORKFLOWS, FOUR, C.registry_lane_ids(REGISTRY))
    assert [s["workflow"] for s in shapes] == FOUR
    by = {s["workflow"]: s["query"] for s in shapes}
    assert by["tradeai-incident-router"] == "source=schedule&limit=40&lane=n8n-incident-fanin,incident-notifier"
    assert by["tradeai-event-router"] == "source=event&limit=40"
    # a /due whose lane= filter is not a registry row is left to the static check (lane_filter_unknown)
    assert C.due_shapes(WORKFLOWS, ["tradeai-approval-router"], C.registry_lane_ids(REGISTRY)) == []


# ── the throttle holds a process to its quota ──────────────────────────────────────────────────────

def test_cpu_throttle_holds_a_busy_process_near_its_quota(tmp_path):
    out = tmp_path / "cpu.txt"
    spin = textwrap.dedent(f"""
        import time
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.5:
            pass
        open({str(out)!r}, "w").write(str(time.process_time()))
    """)
    proc = subprocess.Popen([sys.executable, "-c", spin])
    try:
        with C.CpuThrottle(proc.pid, 0.2) as thr:
            proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    cpu = float(out.read_text())
    assert thr.cycles >= 5
    assert cpu < 0.75, cpu                       # ~0.3 s at 20% of 1.5 s; unthrottled it would be ~1.5 s


def test_cpu_throttle_refuses_a_nonsense_quota():
    with pytest.raises(ValueError):
        C.CpuThrottle(os.getpid(), 0)


# ── end to end: this tree passes, a CPU-heavy gateway is refused ───────────────────────────────────

def test_this_tree_passes_the_concurrent_due_probe(tmp_path, capsys):
    rc = C.main(["--relay-root", str(ROOT), "--ids", ",".join(FOUR), "--scratch", str(tmp_path),
                 "--require-concurrency"])
    out = capsys.readouterr().out
    assert rc == 0, out
    summary = json.loads(out.strip().splitlines()[-1])
    conc = summary["concurrency"]
    assert conc["verdict"] == "PASS" and conc["n"] == 4 and conc["cpu_quota"] == pytest.approx(0.2)
    assert conc["relay_timeout_s"] == pytest.approx(5.0) and conc["budget_s"] == pytest.approx(2.5)
    assert [r["round"] for r in conc["rounds"]] == ["cold", "warm1"]
    assert out.count("concurrency cold") == 4 and "BAD concurrency" not in out
    # evidence the calls really went through the scratch gateway: the second relay logged 4 x 2 ok due lines
    log = (tmp_path / "relay-concurrency" / "state" / "data" / "runtime" / "n8n_relay" / "relay_log.jsonl")
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert sum(1 for r in rows if r.get("op") == "due" and r.get("state") == "OK") == 8


STUB_GATEWAY = '''
import argparse, json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ap = argparse.ArgumentParser()
ap.add_argument("--host"); ap.add_argument("--port", type=int); ap.add_argument("--expected-sha")
ap.add_argument("--ledger"); ap.add_argument("--registry"); ap.add_argument("--run-allowlist")
ap.add_argument("--retry-policies")
a = ap.parse_args()
BURN = float(open(__file__ + ".burn").read())

class H(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        t0 = time.thread_time()
        while time.thread_time() - t0 < BURN:      # CPU, like the pre-#1667 matcher (~0.5 s per due call)
            pass
        data = json.dumps({"schema": "DueResponse@v1", "ok": True, "items": [], "source": "schedule"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:                    # the relay gave up first: the RC11 journal line
            pass

ThreadingHTTPServer((a.host, a.port), H).serve_forever()
'''


def _stub_root(tmp_path: Path, burn_s: float, quota: str = "20%") -> Path:
    """A relay root with this tree's relay and a stub gateway that burns ``burn_s`` CPU per call."""
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    (root / "config" / "systemd" / "user").mkdir(parents=True)
    (root / "scripts" / "lib").symlink_to(ROOT / "scripts" / "lib")
    (root / "scripts" / "n8n_run_relay.py").write_text((ROOT / "scripts" / "n8n_run_relay.py").read_text())
    stub = root / "scripts" / "n8n_coordination_gateway.py"
    stub.write_text(STUB_GATEWAY)
    Path(str(stub) + ".burn").write_text(str(burn_s))
    for name in ("lane_registry.json", "n8n_run_allowlist.json", "n8n_retry_policies.json"):
        (root / "config" / name).symlink_to(ROOT / "config" / name)
    (root / C.GATEWAY_UNIT_REL).write_text(f"[Service]\nCPUQuota={quota}\n")
    return root


def test_a_cpu_heavy_gateway_under_the_quota_is_refused(tmp_path, capsys):
    """4 calls x 0.6 s CPU at 20% = ~12 s of wall: past the relay's 5 s, so the relay answers 502
    relay_gateway_unreachable — exactly the W0 re-run. The single-call route probe still passes."""
    root = _stub_root(tmp_path, burn_s=0.6)
    rc = C.main(["--relay-root", str(root), "--ids", ",".join(FOUR), "--scratch", str(tmp_path / "s"),
                 "--registry", str(REGISTRY)])
    out = capsys.readouterr().out
    assert rc == 1, out
    summary = json.loads(out.strip().splitlines()[-1])
    codes = {f["code"] for f in summary["findings"]}
    assert codes <= {"due_concurrency_refused", "due_concurrency_slow"} and "due_concurrency_refused" in codes
    assert "502 relay_gateway_unreachable" in out
    assert summary["concurrency"]["verdict"] == "REFUSED"
    assert not any(f["code"] == "unsupported_route" for f in summary["findings"])   # route probe alone: PASS


def test_the_same_stub_without_cpu_cost_passes(tmp_path, capsys):
    root = _stub_root(tmp_path, burn_s=0.0)
    rc = C.main(["--relay-root", str(root), "--ids", ",".join(FOUR), "--scratch", str(tmp_path / "s"),
                 "--registry", str(REGISTRY)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert json.loads(out.strip().splitlines()[-1])["concurrency"]["verdict"] == "PASS"


# ── classification and fail-closed paths (no processes) ────────────────────────────────────────────

class _Ctx:
    def __init__(self, *a, **k):
        self.url, self.n8n_key, self.port, self.bearer = "http://127.0.0.1:1", "k", 1, "b"
        self.proc = type("P", (), {"pid": os.getpid()})()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


class _NoThrottle(_Ctx):
    cycles = 0


def _fake(monkeypatch, rows):
    monkeypatch.setattr(C, "ScratchGateway", _Ctx)
    monkeypatch.setattr(C, "ScratchRelay", _Ctx)
    monkeypatch.setattr(C, "CpuThrottle", _NoThrottle)
    monkeypatch.setattr(C, "concurrent_due", lambda port, bearer, queries, client_timeout: [dict(r) for r in rows])


def test_slow_but_ok_is_refused_and_fast_ok_passes(monkeypatch, tmp_path):
    shapes = [{"workflow": "a", "node": "n", "query": "source=schedule&limit=40"},
              {"workflow": "b", "node": "n", "query": "source=event&limit=40"}]
    base = {"status": 200, "reason": "", "ok": True}
    _fake(monkeypatch, [{**base, "query": "q", "wall_s": 3.1}, {**base, "query": "q", "wall_s": 0.2}])
    res = C.concurrency_check(shapes, n=2, relay_root=ROOT, registry=REGISTRY, scratch=tmp_path, ledger=tmp_path / "l",
                              python=sys.executable, quota=0.2, timeout_s=5.0, rounds=1)
    assert res["verdict"] == "REFUSED" and [f["code"] for f in res["findings"]] == ["due_concurrency_slow"]
    assert res["findings"][0]["workflow"] == "a"
    _fake(monkeypatch, [{**base, "query": "q", "wall_s": 0.3}, {**base, "query": "q", "wall_s": 0.2}])
    res = C.concurrency_check(shapes, n=2, relay_root=ROOT, registry=REGISTRY, scratch=tmp_path, ledger=tmp_path / "l",
                              python=sys.executable, quota=0.2, timeout_s=5.0, rounds=2)
    assert res["verdict"] == "PASS" and [r["round"] for r in res["rounds"]] == ["cold", "warm1"]


def test_unknown_quota_or_timeout_fails_closed(tmp_path):
    shapes = [{"workflow": "a", "node": "n", "query": "source=schedule"}]
    for quota, timeout in ((None, 5.0), (0.2, None)):
        res = C.concurrency_check(shapes, n=3, relay_root=ROOT, registry=REGISTRY, scratch=tmp_path,
                                  ledger=tmp_path / "l", python=sys.executable, quota=quota, timeout_s=timeout)
        assert res["verdict"] == "REFUSED" and res["findings"][0]["code"] == "due_concurrency_unknown"


def test_require_concurrency_refuses_when_skipped(capsys):
    rc = C.main(["--no-probe", "--ids", ",".join(FOUR), "--require-concurrency"])
    out = capsys.readouterr().out
    assert rc == 1
    summary = json.loads(out.strip().splitlines()[-1])
    assert [f["code"] for f in summary["findings"]] == ["due_concurrency_not_run"]
    assert summary["concurrency"]["verdict"] == "NOT_RUN"
    rc = C.main(["--no-probe", "--ids", ",".join(FOUR)])                  # without the flag: static PASS as before
    assert rc == 0


def test_default_n_is_the_workflow_count_with_a_floor_of_three(monkeypatch, tmp_path, capsys):
    seen = {}

    def fake_check(shapes, *, n, **kw):
        seen["n"] = n
        return {"n": n, "cpu_quota": 0.2, "relay_timeout_s": 5.0, "margin": 0.5, "budget_s": 2.5, "shapes": [],
                "rounds": [], "findings": [], "verdict": "PASS"}

    monkeypatch.setattr(C, "concurrency_check", fake_check)
    assert C.main(["--relay-root", str(ROOT), "--ids", "tradeai-dispatcher", "--scratch", str(tmp_path / "a")]) == 0
    assert seen["n"] == 3
    assert C.main(["--relay-root", str(ROOT), "--ids", ",".join(FOUR), "--scratch", str(tmp_path / "b")]) == 0
    assert seen["n"] == 4
    capsys.readouterr()
