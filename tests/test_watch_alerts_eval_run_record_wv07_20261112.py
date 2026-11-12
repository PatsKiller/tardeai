"""WV-07 (LQ-20261107-2622): watch-alerts-eval writes a run record. Synthetic; the pass itself is stubbed."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import watch_alerts_eval as w  # noqa: E402


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))


def _rec(tmp_path):
    return json.loads(next(tmp_path.rglob("watch-alerts-eval_last.json")).read_text())


def test_ok_pass_writes_receipt_with_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_run_pass", lambda s: s.update(armed=5, fired=1, composites=0) or 0)
    assert w.main() == 0
    r = _rec(tmp_path)
    assert r["status"] == "ok" and r["ok_at"] and r["produced_count"] == 1 and r["attempted_count"] == 5


def test_no_db_is_a_failed_record_not_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_run_pass", lambda s: s.update(error="USE_DB off") or 2)
    assert w.main() == 2
    r = _rec(tmp_path)
    assert r["status"] == "failed" and r["ok_at"] is None and "USE_DB" in r["error"]


def test_exception_is_recorded_then_raised(tmp_path, monkeypatch):
    def boom(s):
        raise RuntimeError("db gone")
    monkeypatch.setattr(w, "_run_pass", boom)
    with pytest.raises(RuntimeError):
        w.main()
    assert _rec(tmp_path)["status"] == "failed"


def test_quiet_pass_names_its_empty_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_run_pass", lambda s: s.update(armed=3, fired=0, composites=0) or 0)
    w.main()
    assert _rec(tmp_path)["empty_reason"] == "no_alert_fired"
