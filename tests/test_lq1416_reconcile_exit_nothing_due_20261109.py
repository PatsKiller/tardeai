"""ANCHOR: lq1416_reconcile_exit_nothing_due — LQ-20261107-1416.

When Gain Guardian is published and nothing is due to reconcile, the lane must
exit 0 with empty_reason=nothing_due — not exit 1 / dependency_unavailable.

Latest live receipt before this tip (n8n_runs d:…:live:20261108T0900) was exit 1
under published=false; CURRENT now has published=true, so the published quiet
path must not terminalize.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scripts" / "reconcile_exit_advisory_outcomes.py"
    spec = importlib.util.spec_from_file_location("lq1416_exit", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


LANE = _load()


def test_nothing_due_is_a_clean_empty_reason():
    assert "nothing_due" in LANE.CLEAN_EMPTY_REASONS
    assert "up_to_date" in LANE.CLEAN_EMPTY_REASONS


def test_published_zero_rows_is_nothing_due_not_dependency():
    """published=True + ever=0 → nothing_due (LQ-1416); was dependency_unavailable exit 1."""
    state = {"ever": 0, "due": 0, "pending": 0, "newest_age_days": None}
    reason, why = LANE.empty_input_reason(state, True)
    assert reason == "nothing_due"
    assert "published" in why.lower()
    assert reason in LANE.CLEAN_EMPTY_REASONS


def test_unpublished_zero_rows_stays_dependency_unavailable():
    state = {"ever": 0, "due": 0, "pending": 0, "newest_age_days": None}
    reason, why = LANE.empty_input_reason(state, False)
    assert reason == "dependency_unavailable"
    assert "published=false" in why
    assert reason not in LANE.CLEAN_EMPTY_REASONS


def test_pending_zero_still_up_to_date():
    reason, _ = LANE.empty_input_reason(
        {"ever": 10, "due": 10, "pending": 0, "newest_age_days": 1}, True
    )
    assert reason == "up_to_date"


def test_reconcile_published_empty_exits_0(monkeypatch, tmp_path, capsys):
    """End-to-end: empty selector + published → exit 0, receipt nothing_due."""
    receipts: list[dict] = []

    def _fake_receipt(**kw):
        receipts.append(kw)

    class _Ex:
        def __call__(self, *a, **k):
            fetch = k.get("fetch")
            if fetch == "none":
                return None
            if fetch == "all":
                return []
            if fetch == "one":
                # producer_state counts
                sql = a[0] if a else ""
                if "count(*)" in str(sql).lower() or "AS ever" in str(sql):
                    return {"ever": 0, "due": 0, "pending": 0, "newest": None}
                return None
            return None

    monkeypatch.setattr(LANE, "_receipt", _fake_receipt)
    monkeypatch.setattr(LANE, "gain_guardian_published", lambda: True)

    import sys
    from types import ModuleType

    fake_db = ModuleType("db_adapter")
    fake_db.USE_DB = True
    fake_db._execute = _Ex()
    monkeypatch.setitem(sys.modules, "db_adapter", fake_db)

    rc = LANE.reconcile()
    err = capsys.readouterr().err
    assert rc == 0, err
    assert receipts and receipts[-1].get("empty_reason") == "nothing_due"
    assert receipts[-1].get("ok") is True
    assert receipts[-1].get("produced") == 0
