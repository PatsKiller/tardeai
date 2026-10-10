"""Refactor wave 1 (cron -> n8n), 2026-10-10: build_hermes_canonical_status.py + hermes_governance_api.py.

build_hermes_canonical_status: --dry-run fetches and prints, writes neither the snapshot nor the receipt;
a real run writes the snapshot as before and exits 1 when any endpoint failed (receipt ok_at only on a
clean run). hermes_governance_api: --dry-run never writes the cache; --warm exits non-zero when the cache
write fails; the request path still swallows it. Hermetic: endpoints, systemctl and the DB are faked.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "persistent"
    (root / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(root))
    return root


def _receipt(state, lane):
    p = state / "data" / "runtime" / f"{lane}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


# ── build_hermes_canonical_status ─────────────────────────────────────────


@pytest.fixture
def bh(tmp_path, monkeypatch):
    mod = importlib.import_module("build_hermes_canonical_status")
    out = tmp_path / "out" / "hermes_canonical_status_latest.json"
    monkeypatch.setattr(mod, "OUT", out)
    monkeypatch.setattr(mod, "sysd", lambda cmd: "active")
    calls = []

    def fake_api(ep):
        calls.append(ep)
        return {"_error": "connection refused"} if ep in mod._FAILING else {}

    mod._FAILING = set()
    monkeypatch.setattr(mod, "api", fake_api)
    mod._calls = calls
    return mod


def test_build_dry_run_writes_nothing(state, bh, capsys):
    assert bh.main(["--dry-run"]) == 0
    assert not bh.OUT.exists()
    assert _receipt(state, "build-hermes-canonical-status") is None
    out = capsys.readouterr().out
    assert f"would write {bh.OUT}" in out and "nothing written" in out
    assert sorted(bh._calls) == sorted(bh.ENDPOINTS)  # same reads as a real run


def test_build_dry_run_reports_failing_endpoint(state, bh, capsys):
    bh._FAILING.add("health")
    assert bh.main(["--dry-run"]) == 0
    assert "live exit would be 1" in capsys.readouterr().out
    assert not bh.OUT.exists()


def test_build_dry_run_source_order():
    src = (ROOT / "scripts" / "build_hermes_canonical_status.py").read_text()
    body = src[src.index("def main(") :]
    assert body.index("if args.dry_run:") < body.index("OUT.write_text")
    assert body.index("return 0") < body.index("OUT.write_text")


def test_build_live_clean_writes_snapshot_and_ok_receipt(state, bh):
    assert bh.main([]) == 0
    snap = json.loads(bh.OUT.read_text())
    assert snap["hermes_version"] == "v0.16.0" and snap["gateway_status"] == "active/active"
    rec = _receipt(state, "build-hermes-canonical-status")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"]["endpoint_errors"] == []


def test_build_live_endpoint_failure_exits_1_still_writes_snapshot(state, bh):
    assert bh.main([]) == 0
    ok_at = _receipt(state, "build-hermes-canonical-status")["ok_at"]
    bh._FAILING.update({"health", "workflow-matrix"})
    assert bh.main([]) == 1
    assert bh.OUT.exists()  # snapshot behaviour unchanged
    rec = _receipt(state, "build-hermes-canonical-status")
    assert rec["status"] == "failed" and rec["exit"] == 1 and rec["ok_at"] == ok_at
    assert rec["summary"]["endpoint_errors"] == ["health", "workflow-matrix"]


# ── hermes_governance_api ─────────────────────────────────────────────────


@pytest.fixture
def hg(tmp_path, monkeypatch):
    mod = importlib.import_module("hermes_governance_api")
    monkeypatch.setattr(mod, "_CACHE_PATH", str(tmp_path / "rt" / "hermes_governance_cache.json"))
    calls = []

    def compute():
        calls.append(1)
        return {"ok": True, "status": "WARN", "by_tier": {"T0": {"calls": 1, "symbols": 1}}, "budget_decisions": {}}

    monkeypatch.setattr(mod, "_governance_summary_compute", compute)
    mod._calls = calls
    return mod


def test_gov_dry_run_never_writes_cache(hg, capsys):
    assert hg.main(["--warm", "--dry-run"]) == 0
    assert not Path(hg._CACHE_PATH).exists()
    out = capsys.readouterr().out
    assert '"dry_run": true' in out and "cache not written" in out and hg._calls == [1]


def test_gov_dry_run_source_order():
    src = (ROOT / "scripts" / "hermes_governance_api.py").read_text()
    body = src[src.index("def main(") :]
    assert body.index("if a.dry_run:") < body.index("_write_cache(d)")


def test_gov_warm_writes_cache(hg):
    assert hg.main(["--warm"]) == 0
    doc = json.loads(Path(hg._CACHE_PATH).read_text())
    assert doc["status"] == "WARN" and doc["cached"] is False and doc["_cached_at"] > 0


def test_gov_warm_cache_write_failure_is_nonzero(hg, tmp_path, monkeypatch):
    blocker = tmp_path / "a_file"
    blocker.write_text("x")
    monkeypatch.setattr(hg, "_CACHE_PATH", str(blocker / "sub" / "cache.json"))
    with pytest.raises(OSError):
        hg.main(["--warm"])


def test_gov_request_path_still_swallows_cache_write_failure(hg, tmp_path, monkeypatch):
    blocker = tmp_path / "a_file"
    blocker.write_text("x")
    monkeypatch.setattr(hg, "_CACHE_PATH", str(blocker / "sub" / "cache.json"))
    assert hg.governance_summary(fresh=True)["status"] == "WARN"


def test_gov_module_still_has_no_write_sql():
    src = (ROOT / "scripts" / "hermes_governance_api.py").read_text()
    for bad in ("INSERT", "UPDATE ", "DELETE", "place_order"):
        assert bad not in src
