"""A scheduler-launched --shadow run writes the lane's output signal (PR #2409, 2026-11-01).

ANCHOR: MARKET_RISK_SCHEDULED_SHADOW_RECEIPT_20261101

The market-risk-evaluate cron lines installed 2026-11-01 run ``--scheduled --shadow``. Before the fix, main()
returned from _shadow() before the ``if a.scheduled`` receipt write, so run_last.json (the lane's output signal and
what the stalled-escalation check reads) was never written and the lane read stale while it ran. The mutant test
re-introduces that early return and proves the regression test would catch it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

FIX_LINE = "scheduled_started=started if (a.scheduled and not a.as_of and not a.fixture) else None,"


def _setup(tmp_path, monkeypatch, ev):
    from scripts.lib.market_risk.fixture_reader import FixtureReader

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("MARKET_RISK_EPISODES_PATH", str(tmp_path / "e.json"))
    monkeypatch.setattr(ev, "production_reader", lambda: FixtureReader())
    d = tmp_path / "data/runtime/market_risk"
    return d / "run_last.json", d / "shadow_latest.json"


def _scheduled_shadow_writes_receipt(ev, tmp_path, monkeypatch) -> bool:
    run_last, shadow_latest = _setup(tmp_path, monkeypatch, ev)
    assert ev.main(["--scheduled", "--shadow", "--no-portfolio", "--json"]) == 0
    assert shadow_latest.exists()  # the snapshot Home/API read is written either way
    return run_last.exists()


def test_scheduled_shadow_writes_run_last_and_shadow_latest(tmp_path, monkeypatch, capsys):
    import market_risk_evaluate as ev

    run_last, shadow_latest = _setup(tmp_path, monkeypatch, ev)
    assert ev.main(["--scheduled", "--shadow", "--no-portfolio", "--json"]) == 0
    rec = json.loads(run_last.read_text())
    assert rec["schema"] == "MarketRiskRunReceipt@v1" and rec["lane_id"] == "market-risk-evaluate"
    assert rec["mode"] == "shadow" and rec["sends"] == 0
    snap = json.loads(shadow_latest.read_text())
    assert snap["mode"] == "shadow"
    assert not (tmp_path / "data/runtime/market_risk/latest.json").exists()  # never the live prior
    out = json.loads(capsys.readouterr().out)
    assert out["run_receipt"] == str(run_last)


def test_manual_and_replay_shadow_never_write_run_last(tmp_path, monkeypatch, capsys):
    import market_risk_evaluate as ev

    run_last, _ = _setup(tmp_path, monkeypatch, ev)
    assert ev.main(["--shadow", "--no-portfolio", "--json"]) == 0
    assert not run_last.exists()  # a hand-run cannot mask a dead schedule (review of #2411, M8)
    assert ev.main(["--scheduled", "--shadow", "--as-of", "2026-10-28T20:30:00+00:00", "--no-portfolio", "--json"]) == 0
    assert not run_last.exists()  # a replay never does either


def test_mutant_early_return_is_caught(tmp_path, monkeypatch, capsys):
    """Mutant: drop the scheduled flag on the shadow path (the pre-fix behaviour). The regression check must flip."""
    src = (ROOT / "scripts" / "market_risk_evaluate.py").read_text(encoding="utf-8")
    assert src.count(FIX_LINE) == 1
    mdir = tmp_path / "mutant"
    mdir.mkdir()
    mpath = mdir / "market_risk_evaluate_mutant.py"
    mpath.write_text(src.replace(FIX_LINE, "scheduled_started=None,"), encoding="utf-8")
    monkeypatch.setattr(sys, "path", list(sys.path))  # the module inserts its own (mutant) ROOT; undo after
    spec = importlib.util.spec_from_file_location("market_risk_evaluate_mutant", mpath)
    mutant = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutant)

    import market_risk_evaluate as ev

    assert _scheduled_shadow_writes_receipt(ev, tmp_path / "real", monkeypatch) is True
    assert _scheduled_shadow_writes_receipt(mutant, tmp_path / "mut", monkeypatch) is False
