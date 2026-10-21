"""n8nmat reliability: one slow read must not be able to wedge :7777.

Covers the three layers of the fix:

* lib.request_isolation — heavy truth contracts run in a child process with a
  hard deadline, a short cache and single-flight;
* control_plane_api._read_jsonl — streams, and never retains rows the list
  projection throws away (same output, bounded memory);
* the API wiring — the truth wrappers go through isolation, and the server leaves
  a flushed, timestamped trail that names a slow request before a watchdog kill.

All fixtures live under tmp_path. Nothing here reads a live store, a credential
or a broker.
"""

from __future__ import annotations

import ast
import json
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import control_plane_api as cpa  # noqa: E402
from lib import request_isolation as ri  # noqa: E402

# ── lib.request_isolation ─────────────────────────────────────────────────────


@pytest.fixture()
def probe_module(tmp_path, monkeypatch):
    """A throwaway module the child process can import via PYTHONPATH."""
    (tmp_path / "ri_probe_mod.py").write_text(
        textwrap.dedent(
            """
            import os, time

            def ok(n=1):
                return {"status": "OK", "n": n, "pid": os.getpid()}

            def slow(seconds=30):
                time.sleep(seconds)
                return {"status": "OK"}

            def boom():
                raise RuntimeError("contract exploded")

            def verdict():
                return {"status": "UNAVAILABLE", "reason": "no store"}
            """
        )
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    ri.clear_cache()
    yield "ri_probe_mod"
    ri.clear_cache()


def test_result_comes_from_a_child_process(probe_module):
    import os

    body = ri.run_isolated(probe_module, "ok", {"n": 3}, timeout=30, ttl=60)
    assert body["status"] == "OK" and body["n"] == 3
    assert body["isolation"] == "subprocess"
    assert body["pid"] != os.getpid()


def test_a_slow_contract_is_killed_at_the_deadline(probe_module):
    started = time.monotonic()
    body = ri.run_isolated(probe_module, "slow", {"seconds": 30}, timeout=1.0, ttl=60)
    elapsed = time.monotonic() - started
    assert body["status"] == "TIMEOUT"
    assert "killed" in body["reason"]
    assert elapsed < 10, "the caller must get an answer at the deadline, not when the work ends"


def test_a_timeout_is_not_cached(probe_module, monkeypatch):
    first = ri.run_isolated(probe_module, "slow", {"seconds": 30}, timeout=0.5, ttl=60)
    assert first["status"] == "TIMEOUT"
    calls = []
    real = ri._run_child
    monkeypatch.setattr(ri, "_run_child", lambda *a: calls.append(a) or real(*a))
    ri.run_isolated(probe_module, "slow", {"seconds": 30}, timeout=0.5, ttl=60)
    assert len(calls) == 1, "an isolation failure must be retried, never served from cache"


def test_a_crashing_contract_fails_closed_with_the_reason(probe_module):
    body = ri.run_isolated(probe_module, "boom", {}, timeout=30, ttl=60)
    assert body["status"] == "UNAVAILABLE"
    assert "contract exploded" in body["reason"]


def test_a_contract_verdict_is_a_result_and_is_cached(probe_module, monkeypatch):
    first = ri.run_isolated(probe_module, "verdict", {}, timeout=30, ttl=60)
    assert first["status"] == "UNAVAILABLE" and not first.get("isolation_failure")
    monkeypatch.setattr(ri, "_run_child", lambda *a: pytest.fail("verdict should be cached"))
    assert ri.run_isolated(probe_module, "verdict", {}, timeout=30, ttl=60) == first


def test_concurrent_callers_share_one_child(probe_module, monkeypatch):
    calls = []
    real = ri._run_child

    def counting(*a):
        calls.append(a)
        time.sleep(0.3)
        return real(*a)

    monkeypatch.setattr(ri, "_run_child", counting)
    out: list[dict] = []
    threads = [
        threading.Thread(target=lambda: out.append(ri.run_isolated(probe_module, "ok", {}, timeout=30, ttl=60)))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert len(out) == 4 and all(o["status"] == "OK" for o in out)


def test_operating_values_come_from_the_environment(monkeypatch):
    monkeypatch.setenv(ri.TIMEOUT_ENV, "7")
    monkeypatch.setenv(ri.TTL_ENV, "11")
    assert ri.timeout_sec() == 7.0 and ri.cache_ttl_sec() == 11.0
    monkeypatch.setenv(ri.TIMEOUT_ENV, "garbage")
    assert ri.timeout_sec() == ri.DEFAULT_TIMEOUT_SEC


# ── control_plane_api streaming reads ─────────────────────────────────────────


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def _lineage_rows(n: int) -> list[dict]:
    rows = []
    for i in range(n):
        wf = f"wf-{i % 37}"
        rows.append({"record_type": "envelope", "workflow_id": wf, "seq": i})
        rows.append({"record_type": "node", "workflow_id": wf, "node": i})
        rows.append({"record_type": "edge", "workflow_id": wf, "edge": i})
    return rows


@pytest.mark.parametrize("every", [3, 50, 5000])
def test_workflow_list_projection_is_unchanged_by_streaming(tmp_path, monkeypatch, every):
    monkeypatch.setattr(cpa, "_JSONL_COMPACT_EVERY", every)
    rows = _lineage_rows(400)
    path = _write_jsonl(tmp_path / "cio_workflow_lineage.jsonl", rows)
    expected = cpa._project_workflow_collection([dict(r) for r in rows])
    got, quality = cpa._select_rows((path,), domain="workflows")
    assert quality == "AVAILABLE"
    assert got == expected
    assert len(got) == 37


def test_untyped_workflow_rows_are_still_listed(tmp_path):
    rows = [{"workflow_id": f"w{i}", "x": i} for i in range(10)]
    path = _write_jsonl(tmp_path / "cio_workflow_lineage.jsonl", rows)
    got, _ = cpa._select_rows((path,), domain="workflows")
    assert got == rows


@pytest.mark.parametrize("every", [2, 7, 5000])
def test_agent_trace_projection_is_unchanged_by_compaction(tmp_path, monkeypatch, every):
    monkeypatch.setattr(cpa, "_JSONL_COMPACT_EVERY", every)
    rows = [
        {"agent": f"a{i % 5}", "role": "r", "started_at": f"2026-10-09T00:{i:02d}:00Z", "status": f"s{i}"}
        for i in range(60)
    ]
    path = _write_jsonl(tmp_path / "agent_run_traces.jsonl", rows)
    expected = cpa._agents_from_traces([dict(r) for r in rows])
    got, quality = cpa._select_rows((path,), domain="agents")
    assert quality == "AVAILABLE"
    assert got == expected


def test_one_corrupt_line_still_fails_the_file(tmp_path):
    path = tmp_path / "cio_workflow_lineage.jsonl"
    path.write_text('{"record_type": "node"}\n{not json\n')
    assert cpa._read_jsonl(path, keep=cpa._workflow_list_keep) == (None, "INVALID_SCHEMA")


def test_undecodable_bytes_are_invalid_not_a_crash(tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_bytes(b'{"a": 1}\n\xff\xfe\n')
    assert cpa._read_jsonl(path) == (None, "INVALID_SCHEMA")


def test_the_reader_never_slurps_the_file():
    fn = next(n for n in ast.parse((ROOT / "scripts" / "control_plane_api.py").read_text()).body
              if isinstance(n, ast.FunctionDef) and n.name == "_read_jsonl")
    called = {c.func.attr for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert not called & {"read_text", "read_bytes", "splitlines", "readlines", "read"}


# ── wiring in the API process ─────────────────────────────────────────────────


def _fn(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_bytes())
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


@pytest.mark.parametrize("wrapper", ["_whole_site_truth_block", "_effective_truth_block"])
def test_truth_wrappers_run_isolated(wrapper):
    src = ast.unparse(_fn(ROOT / "scripts" / "api_v2.py", wrapper))
    assert "_isolated_truth_block" in src
    assert "getattr(_wst" not in src and "getattr(_et" not in src


def test_server_names_slow_requests_and_flushes_its_access_log():
    server = ROOT / "scripts" / "portfolio_server.py"
    assert "_log_slow_request" in ast.unparse(_fn(server, "process_request_thread"))
    log_src = ast.unparse(_fn(server, "log_message"))
    assert "flush=True" in log_src
    slow_src = ast.unparse(_fn(server, "_log_slow_request"))
    assert "TRADEAI_API_SLOW_REQUEST_SEC" in slow_src and "flush=True" in slow_src


def test_watchdog_records_cgroup_memory_before_killing():
    text = (ROOT / "scripts" / "portfolio_server_watchdog.sh").read_text()
    assert "cgroup_evidence() {" in text
    kill_at = text.index('log "UNRESPONSIVE after ${FAILS} probes')
    assert text.rindex("cgroup_evidence\n", 0, kill_at) < kill_at
