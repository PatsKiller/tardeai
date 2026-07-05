#!/usr/bin/env python3
"""Health-agent coverage for the Strategy Weekly Review data problems (2026-07-05):
(a) NULL/empty strategy_id rows in strategy_registry → warning + safe audited auto-backfill
    (fix_strategy_registry_null_ids.py, strategy_id = strategy_type — backfill, never delete);
(b) weekly review real-trade join returning 0 while the schwab journal (trade_closed) has
    ≥1 closed trade → critical needs-operator alert, NO auto-remediation (joins are never
    auto-rewritten)."""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
if "dotenv" not in sys.modules:
    _d = types.ModuleType("dotenv")
    _d.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _d

import health_agent as ha  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _fake_db(null_rows=None, journal_n=0):
    def fake(sql, params=None, fetch="one"):
        if "strategy_registry" in sql:
            return null_rows or []
        if "trade_closed" in sql:
            return {"n": journal_n}
        return None
    return fake


def _run_collector(null_rows=None, journal_n=0, state=None, state_age_ok=True):
    """Run the collector with mocked _db and STATE_DIR pointed at a temp dir."""
    old_db, old_state_dir = ha._db, ha.STATE_DIR
    tmp = Path(tempfile.mkdtemp())
    try:
        ha._db = _fake_db(null_rows, journal_n)
        ha.STATE_DIR = tmp
        if state is not None:
            f = tmp / "strategy_weekly_review_latest.json"
            f.write_text(json.dumps(state))
            if not state_age_ok:  # backdate mtime beyond the 8-day judgement window
                old = 9 * 24 * 3600
                os.utime(f, (f.stat().st_atime - old, f.stat().st_mtime - old))
        return ha.collect_strategy_registry_integrity()
    finally:
        ha._db, ha.STATE_DIR = old_db, old_state_dir


def test_collector_registered():
    assert ha.collect_strategy_registry_integrity in ha.COLLECTORS


def test_clean_registry_no_findings():
    assert _run_collector(null_rows=[], journal_n=100, state=None) == []


def test_null_ids_detected():
    rows = [{"strategy_type": "meme_squeeze_momentum"}, {"strategy_type": "pullback_macd_reversal"}]
    findings = _run_collector(null_rows=rows)
    f = [x for x in findings if x["type"] == "strategy_registry_null_ids"]
    assert len(f) == 1
    assert f[0]["severity"] == "warning" and f[0]["category"] == "data_quality"
    assert f[0]["count"] == 2
    assert "meme_squeeze_momentum" in f[0]["strategy_types"]


def test_real_join_zero_alerts_critical():
    state = {"generated_at": "2026-07-05T10:30:00", "real_rows_attributed": 0,
             "real_rows_unattributed": 0}
    findings = _run_collector(journal_n=136, state=state)
    f = [x for x in findings if x["type"] == "weekly_review_real_join_zero"]
    assert len(f) == 1
    assert f[0]["severity"] == "critical"
    assert f[0]["journal_closed"] == 136


def test_real_join_healthy_silent():
    state = {"generated_at": "2026-07-05T10:30:00", "real_rows_attributed": 120,
             "real_rows_unattributed": 16}
    findings = _run_collector(journal_n=136, state=state)
    assert not [x for x in findings if x["type"] == "weekly_review_real_join_zero"]


def test_stale_review_snapshot_not_judged():
    state = {"generated_at": "2026-06-01T10:30:00", "real_rows_attributed": 0,
             "real_rows_unattributed": 0}
    findings = _run_collector(journal_n=136, state=state, state_age_ok=False)
    assert not [x for x in findings if x["type"] == "weekly_review_real_join_zero"]


def test_missing_snapshot_silent():
    assert not [x for x in _run_collector(journal_n=136, state=None)
                if x["type"] == "weekly_review_real_join_zero"]


def test_collector_never_raises_without_db():
    old = ha._db
    try:
        ha._db = lambda *a, **k: None
        out = ha.collect_strategy_registry_integrity()
        assert isinstance(out, list)
    finally:
        ha._db = old


def test_policy_wiring():
    pol = json.loads((ROOT / "config" / "health_agent_policy.json").read_text())
    # (a) auto-remediable via the safe backfill script
    assert "strategy_registry_null_ids" in pol["auto_remediate"]["finding_types"]
    cmd = pol["remediation_map"]["strategy_registry_null_ids"]
    assert "fix_strategy_registry_null_ids.py" in cmd
    assert all(x not in cmd for x in ("schwab", "place_order", "alpaca_submit"))
    # (b) join breakage is needs-operator: NEVER auto-remediated
    assert "weekly_review_real_join_zero" not in pol["remediation_map"]
    assert "weekly_review_real_join_zero" not in pol["auto_remediate"]["finding_types"]


def test_backfill_script_allowlisted_and_safe():
    src = (ROOT / "scripts" / "health_agent.py").read_text()
    assert '"fix_strategy_registry_null_ids.py" not in cmd' in src
    fix = (ROOT / "scripts" / "fix_strategy_registry_null_ids.py").read_text()
    assert "UPDATE strategy_registry" in fix and "RETURNING" in fix
    assert "DELETE" not in fix  # backfill, never delete
    for broker_marker in ("schwab", "alpaca", "place_order", "submit_order"):
        assert broker_marker not in fix.lower()  # no broker writes, ever


def main():
    fails = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {name}")
            except AssertionError as e:
                fails.append(name)
                print(f"  [FAIL] {name}: {e}")
    print(f"\n{len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
