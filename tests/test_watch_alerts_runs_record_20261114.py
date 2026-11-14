"""LQ-20261107-3011 (cc-deepseek-2): every evaluator pass appends exactly one line to the durable runs record the
Watch Alerts tab reads (``lib/watch_alerts_record.read_record``), an unreadable armed count stays None (never 0), and
a missing or failing writer never fails the alert lane.

These tests fake ``lib.watch_alerts_record`` for the fast path because it folds with the Watch v002 stack
(LQ-20261107-2993c-v2). ``test_real_writer_contract_when_present`` exercises the real writer->reader contract
against a scratch root whenever the module is in the tree (N2).

r2 (REVIEW-LQ-20261107-3011-runs-record-cc-deepseek-8): a lock-skipped pass is not a run (F1), a writer that fails
*at import* never stops the lane (F2), and a refused append is named in the lane log (N1).

Rebased onto the release-3 source ``d12fe7ec3`` on the lead's 2026-11-14T07:20:49Z ruling: only the runs-record change
is carried. ``d12fe7ec3``'s evaluator has no pass lock yet, so nothing sets ``lock_skipped`` there — F1's guard is
inert on this tree and pinned here against a stats dict, exactly as it would arrive from the 3011-v4 pass.
"""
from __future__ import annotations

import builtins
import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import watch_alerts_eval as w  # noqa: E402


def _fake_record(monkeypatch, *, raises=None):
    calls = []

    def append_run(**kw):
        if raises is not None:
            raise raises
        calls.append(kw)
        return True

    monkeypatch.setitem(sys.modules, "lib.watch_alerts_record", types.SimpleNamespace(append_run=append_run))
    return calls


@pytest.fixture
def state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    return tmp_path


def test_one_line_per_pass_keeps_unknown_armed(state_root, monkeypatch):
    calls = _fake_record(monkeypatch)
    w._write_run_record(
        datetime.now(timezone.utc), 3, {"armed": None, "fired": 0, "composites": 0, "error": "alerts load failed"}
    )
    assert len(calls) == 1
    assert calls[0]["rc"] == 3
    # A failed alerts read is UNKNOWN, never "armed 0" (the LQ-3011 false-success class).
    assert calls[0]["armed"] is None
    assert calls[0]["fired"] == 0
    assert calls[0]["composites"] == 0
    assert calls[0]["error"] == "alerts load failed"


def test_ok_pass_records_its_counts(state_root, monkeypatch):
    calls = _fake_record(monkeypatch)
    w._write_run_record(datetime.now(timezone.utc), 0, {"armed": 18, "fired": 2, "composites": 1})
    assert len(calls) == 1
    assert (calls[0]["armed"], calls[0]["fired"], calls[0]["composites"], calls[0]["rc"]) == (18, 2, 1, 0)
    assert calls[0]["error"] is None


def test_missing_writer_module_never_fails_the_lane(state_root, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "lib.watch_alerts_record", None)  # `from ... import` raises ImportError
    w._write_run_record(datetime.now(timezone.utc), 0, {"armed": 18, "fired": 0, "composites": 0})
    assert "runs record writer absent" in capsys.readouterr().out
    # The receipt is still written; the missing record module changes nothing about the pass outcome.
    assert (state_root / "data" / "runtime" / "watch-alerts-eval_last.json").exists()


def test_record_failure_never_stops_the_pass(state_root, monkeypatch, capsys):
    _fake_record(monkeypatch, raises=OSError("disk full"))
    w._write_run_record(datetime.now(timezone.utc), 0, {"armed": 18, "fired": 0, "composites": 0})
    assert "runs record not written" in capsys.readouterr().out


def test_receipt_failure_still_appends_the_record(state_root, monkeypatch, capsys):
    broken = types.SimpleNamespace(write_lane_receipt=lambda *a, **k: (_ for _ in ()).throw(OSError("receipt")))
    monkeypatch.setitem(sys.modules, "lib.lane_last_receipt", broken)
    calls = _fake_record(monkeypatch)
    w._write_run_record(datetime.now(timezone.utc), 0, {"armed": 18, "fired": 1, "composites": 0})
    assert "run record not written" in capsys.readouterr().out
    assert len(calls) == 1 and calls[0]["armed"] == 18


# ── r2: F1 / F2 / N1 / N2 (REVIEW-LQ-20261107-3011-runs-record-cc-deepseek-8) ────────────────────────────


def test_lock_skipped_pass_is_not_a_run(state_root, monkeypatch):
    """F1: a pass that never acquired the pass lock evaluated nothing. Its rc is 0, and the reader certifies from
    the newest rc == 0 line — so appending it would drop the certified armed count to UNKNOWN and advance
    ``last_ok_at`` to a pass that did nothing ("registration is not execution")."""
    calls = _fake_record(monkeypatch)
    w._write_run_record(datetime.now(timezone.utc), 0, {"lock_skipped": True, "steps": {"pass_lock": "skipped"}})
    assert calls == []
    # The receipt beside it still names the skip; the skip stays visible, it is just not a run.
    receipt = json.loads((state_root / "data" / "runtime" / "watch-alerts-eval_last.json").read_text())
    assert "lock_skipped" in json.dumps(receipt)


def test_writer_import_failure_never_fails_the_lane(state_root, monkeypatch, capsys):
    """F2: a writer module that EXISTS but raises at import must not take the alert lane down. The docstring
    promises a record failure never stops an alert pass; ``except ImportError`` alone does not keep that promise."""
    monkeypatch.delitem(sys.modules, "lib.watch_alerts_record", raising=False)
    real_import = builtins.__import__

    def broken(name, *args, **kwargs):
        if name == "lib.watch_alerts_record":
            raise RuntimeError("writer module is broken")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken)
    w._write_run_record(datetime.now(timezone.utc), 0, {"armed": 18, "fired": 0, "composites": 0})
    assert "runs record" in capsys.readouterr().out
    # The receipt is still written; the broken writer changes nothing about the pass outcome.
    assert (state_root / "data" / "runtime" / "watch-alerts-eval_last.json").exists()


def test_refused_append_is_reported(state_root, monkeypatch, capsys):
    """N1: ``append_run`` never raises — it returns False when the write is refused. A silent False leaves the
    reader UNKNOWN with nothing in the lane log, so the refusal must be named."""
    monkeypatch.setitem(sys.modules, "lib.watch_alerts_record", types.SimpleNamespace(append_run=lambda **kw: False))
    w._write_run_record(datetime.now(timezone.utc), 0, {"armed": 18, "fired": 0, "composites": 0})
    assert "runs record refused" in capsys.readouterr().out


@pytest.mark.skipif(
    importlib.util.find_spec("lib.watch_alerts_record") is None,
    reason="writer folds with the Watch v002 stack (LQ-20261107-2993c-v2); exercised once it is in the tree",
)
def test_real_writer_contract_when_present(state_root):
    """N2: the real writer + reader, against a scratch root — not a SimpleNamespace fake. Pins the signature and
    the derived fields the Alerts tab shows: an unreadable armed count stays null, and the certified count comes
    from the newest rc == 0 line."""
    from lib.watch_alerts_record import append_run, read_record

    assert append_run(armed=18, fired=2, composites=0, rc=0) is True
    assert append_run(armed=None, fired=0, composites=0, rc=3, error="alerts load failed") is True
    rec = read_record()
    assert rec["readable"] is True
    assert rec["last_rc"] == 3
    assert rec["last_ok_at"] is not None
    assert rec["certified"]["armed"] == 18
    assert rec["certified"]["ok_runs_24h"] == 1
    assert rec["skipped_lines"] == 0
