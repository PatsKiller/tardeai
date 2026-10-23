"""/api/v2/health/remediation and finviz credential-health stay bounded. Hermetic: tmp files only.

2026-10-22: portfolio-server was SIGKILLed 69 times in one day by the cron watchdog after its
cgroup passed MemoryHigh 1.5G. /api/v2/health/remediation parsed two never-rotated JSONL logs whole
(119 MB + 55 MB, ~300k lines) on every 60 s poll, adding 300-770 MB RSS per call; the finviz
credential-health banner ran a live Finviz probe per poll. These tests pin the fix: a bounded tail
read that returns the same newest-50 rows and 24h stats as the old full parse, a single-flight
cache, a cached Finviz verdict, and no sys.path growth.
"""

from __future__ import annotations

import builtins
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402

NOW = datetime(2026, 10, 22, 23, 0, 0, tzinfo=timezone.utc)


# ── old implementation (pre-2026-10-22), kept as the reference oracle ───────────────────────────
def _old_full_parse(agent_path, inspector_paths, now):
    remediations = []

    def _read(path, build):
        p = Path(path)
        if not p.exists():
            return
        for line in p.read_text(errors="replace").strip().splitlines():
            if not line.strip():
                continue
            try:
                remediations.append(build(json.loads(line)))
            except Exception:
                pass

    _read(agent_path, api_v2._health_agent_remediation_row)
    for ip in inspector_paths:
        _read(ip, api_v2._health_inspector_remediation_row)
    remediations.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    recent = [
        r
        for r in remediations
        if r.get("timestamp")
        and now - datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) < timedelta(hours=24)
    ]
    by_agent, by_sev, ok = {}, {}, 0
    for r in recent:
        by_agent[r.get("agent", "unknown")] = by_agent.get(r.get("agent", "unknown"), 0) + 1
        by_sev[r.get("severity", "info")] = by_sev.get(r.get("severity", "info"), 0) + 1
        ok += 1 if r.get("verified") else 0
    return api_v2._json_clean(
        {
            "remediations": remediations[:50],
            "stats": {
                "total_fixes_24h": len(recent),
                "by_agent": by_agent,
                "by_severity": by_sev,
                "success_rate": f"{ok / max(len(recent), 1) * 100:.0f}%" if recent else "N/A",
            },
        }
    )


def _write_agent(path: Path, n: int, span_h: float, now=NOW):
    with open(path, "w") as fh:
        for i in range(n):
            ts = now - timedelta(hours=span_h) + timedelta(hours=span_h * i / n)
            fh.write(
                json.dumps(
                    {
                        "at": ts.isoformat(),
                        "type": f"t{i % 7}",
                        "cmd": "python scripts/x.py",
                        "ok": i % 3 == 0,
                        "exit_code": i % 2,
                        "trigger": "x" * 40,
                    }
                )
                + "\n"
            )
            if i % 997 == 0:
                fh.write("not json\n\n")


def _write_inspector(path: Path, n: int, span_h: float, now=NOW):
    with open(path, "w") as fh:
        for i in range(n):
            ts = now - timedelta(hours=span_h) + timedelta(hours=span_h * i / n) + timedelta(seconds=1)
            fh.write(
                json.dumps(
                    {
                        "timestamp": ts.isoformat(),
                        "agent": "tradeai-health-inspector",
                        "layer": 1,
                        "finding": f"f{i % 11}",
                        "severity": ["info", "warning", "critical"][i % 3],
                        "old_state": "would_run",
                        "new_state": "would_run",
                        "script": "cd /x && python scripts/y.py --run",
                        "exit_code": None,
                        "duration_ms": 0,
                        "verified": i % 5 == 0,
                        "mode": "dry_run",
                    }
                )
                + "\n"
            )


@pytest.fixture(autouse=True)
def _reset_caches():
    api_v2._HEALTH_REMEDIATION_CACHE.update(key=None, ts=0.0, result=None, paths=None, paths_ts=0.0)
    api_v2._FINVIZ_CRED_HEALTH_CACHE.update(ts=0.0, result=None)
    yield
    api_v2._HEALTH_REMEDIATION_CACHE.update(key=None, ts=0.0, result=None, paths=None, paths_ts=0.0)
    api_v2._FINVIZ_CRED_HEALTH_CACHE.update(ts=0.0, result=None)


@pytest.mark.parametrize("chunk", [None, 4096, 50_000])
def test_tail_read_matches_old_full_parse(tmp_path, monkeypatch, chunk):
    agent, insp = tmp_path / "agent.jsonl", tmp_path / "insp.jsonl"
    _write_agent(agent, 3000, span_h=72)
    _write_inspector(insp, 5000, span_h=96)
    if chunk:
        monkeypatch.setattr(api_v2, "_HEALTH_REMEDIATION_TAIL_BYTES", chunk)
    new = api_v2._health_remediation_compute(agent, [insp], now=NOW)
    old = _old_full_parse(agent, [insp], NOW)
    assert new == old
    assert len(new["remediations"]) == 50
    assert new["stats"]["total_fixes_24h"] > 1000
    assert "stats_truncated" not in new["stats"]


def test_small_and_missing_files_match_old(tmp_path):
    agent, insp = tmp_path / "agent.jsonl", tmp_path / "insp.jsonl"
    _write_agent(agent, 10, span_h=2)
    missing = tmp_path / "nope.jsonl"
    assert api_v2._health_remediation_compute(agent, [missing], now=NOW) == _old_full_parse(agent, [missing], NOW)
    insp.write_text("")
    assert api_v2._health_remediation_compute(missing, [insp], now=NOW) == _old_full_parse(missing, [insp], NOW)


def test_cap_marks_stats_truncated_instead_of_silent_undercount(tmp_path, monkeypatch):
    agent, insp = tmp_path / "agent.jsonl", tmp_path / "insp.jsonl"
    _write_agent(agent, 10, span_h=1)
    _write_inspector(insp, 20_000, span_h=12)  # every row is inside 24h
    monkeypatch.setattr(api_v2, "_HEALTH_REMEDIATION_TAIL_BYTES", 64 * 1024)
    monkeypatch.setattr(api_v2, "_HEALTH_REMEDIATION_MAX_BYTES", 256 * 1024)
    new = api_v2._health_remediation_compute(agent, [insp], now=NOW)
    old = _old_full_parse(agent, [insp], NOW)
    assert new["stats"]["stats_truncated"] is True
    assert new["stats"]["total_fixes_24h"] < old["stats"]["total_fixes_24h"]
    assert new["remediations"] == old["remediations"]  # newest 50 still exact


def test_large_file_reads_a_bounded_window(tmp_path, monkeypatch):
    agent, insp = tmp_path / "agent.jsonl", tmp_path / "insp.jsonl"
    _write_agent(agent, 20_000, span_h=24 * 60)
    _write_inspector(insp, 200_000, span_h=24 * 60)  # 200k lines, ~60 days, ~3.3k rows in 24h
    total = agent.stat().st_size + insp.stat().st_size
    window = 1024 * 1024
    monkeypatch.setattr(api_v2, "_HEALTH_REMEDIATION_TAIL_BYTES", window)

    read_bytes = {"n": 0}
    real_open = builtins.open

    class _Counting:
        def __init__(self, fh):
            self._fh = fh

        def read(self, *a):
            data = self._fh.read(*a)
            read_bytes["n"] += len(data)
            return data

        def __getattr__(self, name):
            return getattr(self._fh, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._fh.__exit__(*exc)

    monkeypatch.setattr(api_v2, "open", lambda *a, **k: _Counting(real_open(*a, **k)), raising=False)
    new = api_v2._health_remediation_compute(agent, [insp], now=NOW)
    monkeypatch.undo()
    assert total > 30 * 1024 * 1024
    assert 0 < read_bytes["n"] <= 4 * window, read_bytes
    assert read_bytes["n"] < total / 20
    old = _old_full_parse(agent, [insp], NOW)
    assert new == old


def test_single_flight_cache_shares_one_computation(tmp_path, monkeypatch):
    agent, insp = tmp_path / "agent.jsonl", tmp_path / "insp.jsonl"
    _write_agent(agent, 100, span_h=4)
    _write_inspector(insp, 100, span_h=4)
    monkeypatch.setattr(api_v2, "_health_remediation_paths", lambda: (agent, [insp]))
    calls = {"n": 0}
    real = api_v2._health_remediation_compute

    def slow(*a, **k):
        calls["n"] += 1
        time.sleep(0.2)
        return real(*a, **k)

    monkeypatch.setattr(api_v2, "_health_remediation_compute", slow)
    results = []
    threads = [threading.Thread(target=lambda: results.append(api_v2._health_remediation())) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls["n"] == 1
    assert len(results) == 8 and all(r == results[0] for r in results)
    results[0]["remediations"].clear()  # callers get copies, never the cached object
    assert api_v2._health_remediation()["remediations"]
    assert calls["n"] == 1

    with open(insp, "a") as fh:  # file changed -> key changed -> recompute
        fh.write("\n")
    api_v2._health_remediation()
    assert calls["n"] == 2

    monkeypatch.setattr(api_v2, "_HEALTH_REMEDIATION_CACHE_TTL_S", 0.0)  # TTL expiry -> recompute
    api_v2._health_remediation()
    assert calls["n"] == 3


def test_ops_autonomy_still_reads_remediation(tmp_path, monkeypatch):
    agent, insp = tmp_path / "agent.jsonl", tmp_path / "insp.jsonl"
    _write_agent(agent, 5, span_h=1, now=datetime.now(timezone.utc))
    monkeypatch.setattr(api_v2, "_health_remediation_paths", lambda: (agent, [insp]))
    out = api_v2._health_remediation()
    assert set(out) == {"remediations", "stats"}
    assert out["stats"]["total_fixes_24h"] == 5


# ── finviz credential-health ──────────────────────────────────────────────────────────────────
def _fake_finviz(monkeypatch):
    import secret_validators as sv

    probes = {"cookie": 0}

    def cookie_probe(k):
        probes["cookie"] += 1
        return True, "37 rows"

    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: {"last_error": None})
    monkeypatch.setattr(sv, "_key", lambda name: {"FINVIZ_COOKIE": "c", "FINVIZ_API_TOKEN": "t"}.get(name))
    monkeypatch.setattr(sv, "_finviz_cookie", cookie_probe)
    monkeypatch.setattr(sv, "_finviz_token", lambda k: (True, "ok"))
    return probes


def test_credential_health_cached_hit_never_probes(monkeypatch):
    probes = _fake_finviz(monkeypatch)
    first = api_v2._finviz_credential_health()
    assert probes["cookie"] == 1 and first["ok"] is True and first["status"] == "ok"
    for _ in range(20):
        assert api_v2._finviz_credential_health() == first
    assert probes["cookie"] == 1
    monkeypatch.setattr(api_v2, "_FINVIZ_CRED_HEALTH_TTL_S", 0.0)
    api_v2._finviz_credential_health()
    assert probes["cookie"] == 2


def test_credential_health_serves_stale_while_another_request_probes(monkeypatch):
    probes = _fake_finviz(monkeypatch)
    first = api_v2._finviz_credential_health()
    monkeypatch.setattr(api_v2, "_FINVIZ_CRED_HEALTH_TTL_S", 0.0)
    assert api_v2._FINVIZ_CRED_HEALTH_LOCK.acquire(blocking=False)
    try:
        assert api_v2._finviz_credential_health() == first  # no wait, no probe
    finally:
        api_v2._FINVIZ_CRED_HEALTH_LOCK.release()
    assert probes["cookie"] == 1


def test_credential_health_single_flight(monkeypatch):
    calls = {"n": 0}

    def live(query=None):
        calls["n"] += 1
        time.sleep(0.2)
        return {"ok": True, "status": "ok"}

    monkeypatch.setattr(api_v2, "_finviz_credential_health_live", live)
    out = []
    threads = [threading.Thread(target=lambda: out.append(api_v2._finviz_credential_health())) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls["n"] == 1 and len(out) == 6


def test_sys_path_does_not_grow(monkeypatch):
    _fake_finviz(monkeypatch)
    api_v2._finviz_credential_health_live()
    before = len(sys.path)
    for _ in range(25):
        api_v2._finviz_credential_health_live()
    assert len(sys.path) == before
