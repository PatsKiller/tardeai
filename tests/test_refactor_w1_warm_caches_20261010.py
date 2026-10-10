"""Refactor wave 1 (cron -> n8n), 2026-10-10: warm_caches.py + the LaneRunReceipt@v1 helper.

warm_caches --dry-run must not import api_v2 or rotation_autopilot (the warm steps compute and write in
one call; the autopilot tick can propose and send). A real run exits 1 on ANY failed step and writes
<state>/data/runtime/warm-caches_last.json whose ok_at advances only on full success. Hermetic: the
persistent-state root is a tmp dir; api_v2 / rotation_autopilot are fake modules.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
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


# ── helper ────────────────────────────────────────────────────────────────


def test_receipt_ok_at_only_on_success_and_carried_on_failure(state):
    from lib import lane_last_receipt as r

    p = r.write_lane_receipt("demo-lane", ok=True, exit_code=0, summary={"n": 1})
    assert p == state / "data" / "runtime" / "demo-lane_last.json"
    first = json.loads(p.read_text())
    assert first["schema"] == "LaneRunReceipt@v1" and first["status"] == "ok"
    assert first["ok_at"] == first["finished_at"]
    r.write_lane_receipt("demo-lane", ok=False, exit_code=1)
    second = json.loads(p.read_text())
    assert second["status"] == "failed" and second["exit"] == 1
    assert second["ok_at"] == first["ok_at"]  # carried, not advanced


def test_receipt_first_failure_has_no_ok_at(state):
    from lib import lane_last_receipt as r

    p = r.write_lane_receipt("never-ok", ok=False, exit_code=2)
    assert json.loads(p.read_text())["ok_at"] is None


@pytest.mark.parametrize("bad", ["", "../x", ".hidden", "a/b"])
def test_receipt_rejects_path_like_lane_ids(state, bad):
    from lib import lane_last_receipt as r

    with pytest.raises(ValueError):
        r.receipt_path(bad)


# ── warm_caches ───────────────────────────────────────────────────────────


class _Forbidden(types.ModuleType):
    def __getattr__(self, name):  # any use of the module in a dry run is the bug
        raise AssertionError(f"dry run touched {self.__name__}.{name}")


@pytest.fixture
def wc(monkeypatch):
    sys.modules.pop("warm_caches", None)
    return importlib.import_module("warm_caches")


def test_warm_module_import_does_not_import_api_v2(monkeypatch):
    monkeypatch.setitem(sys.modules, "api_v2", _Forbidden("api_v2"))
    sys.modules.pop("warm_caches", None)
    importlib.import_module("warm_caches")  # would raise on a module-level api_v2 use


def test_warm_dry_run_reports_plan_and_touches_nothing(state, wc, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "api_v2", _Forbidden("api_v2"))
    monkeypatch.setitem(sys.modules, "rotation_autopilot", _Forbidden("rotation_autopilot"))
    cache = state / "data" / "runtime" / "trade_ai_cache.json"
    cache.write_text("{}")
    before = sorted(p.name for p in (state / "data" / "runtime").iterdir())
    assert wc.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    for step in ("rotation_summary", "trade_ai", "rotation_autopilot"):
        assert f"would run {step}" in out
    assert str(cache) in out and "current age None" in out  # absent caches say so
    assert sorted(p.name for p in (state / "data" / "runtime").iterdir()) == before
    assert _receipt(state, "warm-caches") is None


def test_warm_dry_run_source_order():
    src = (ROOT / "scripts" / "warm_caches.py").read_text()
    body = src[src.index("def main(") :]
    assert body.index("if args.dry_run:") < body.index("import api_v2")
    assert body.index("return 0") < body.index("import api_v2")


def _fakes(monkeypatch, *, rot=None, ta=None, auto=None):
    calls = []

    def mk(name, exc):
        def f(*a, **k):
            calls.append(name)
            if exc:
                raise exc
            return {} if name == "autopilot" else None

        return f

    api = types.ModuleType("api_v2")
    api._rotation_summary = mk("rotation_summary", rot)
    api.trade_ai = mk("trade_ai", ta)
    ra = types.ModuleType("rotation_autopilot")
    ra.run_autopilot_tick = mk("autopilot", auto)
    monkeypatch.setitem(sys.modules, "api_v2", api)
    monkeypatch.setitem(sys.modules, "rotation_autopilot", ra)
    return calls


def test_warm_success_writes_ok_receipt_with_rss(state, wc, monkeypatch):
    calls = _fakes(monkeypatch)
    assert wc.main([]) == 0
    assert calls == ["rotation_summary", "trade_ai", "autopilot"]
    rec = _receipt(state, "warm-caches")
    assert rec["status"] == "ok" and rec["ok_at"]
    assert set(rec["summary"]["steps_s"]) == {"rotation_summary", "trade_ai", "rotation_autopilot"}
    assert rec["summary"]["peak_rss"]["self_mb"] > 0


def test_warm_trade_ai_failure_is_exit_1_and_autopilot_still_runs(state, wc, monkeypatch):
    calls = _fakes(monkeypatch, ta=RuntimeError("db gone"))
    assert wc.main([]) == 1
    assert calls == ["rotation_summary", "trade_ai", "autopilot"]
    rec = _receipt(state, "warm-caches")
    assert rec["status"] == "failed" and rec["ok_at"] is None and rec["summary"]["failed"] == ["trade_ai"]


def test_warm_autopilot_failure_is_exit_1(state, wc, monkeypatch):
    _fakes(monkeypatch, auto=RuntimeError("x"))
    assert wc.main([]) == 1
    assert _receipt(state, "warm-caches")["summary"]["failed"] == ["rotation_autopilot"]


def test_warm_rotation_failure_stops_early_and_keeps_previous_ok_at(state, wc, monkeypatch):
    _fakes(monkeypatch)
    assert wc.main([]) == 0
    ok_at = _receipt(state, "warm-caches")["ok_at"]
    calls = _fakes(monkeypatch, rot=RuntimeError("engine"))
    assert wc.main([]) == 1
    assert calls == ["rotation_summary"]  # unchanged early return
    rec = _receipt(state, "warm-caches")
    assert rec["status"] == "failed" and rec["ok_at"] == ok_at
