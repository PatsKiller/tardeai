"""Class SLAs, dual coverage/fresh_pct, age-gate short-circuit."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

THICK = (
    "Living thesis: why this name is in the book, what would invalidate it, "
    "and what evidence would change the stance."
)


class _Store:
    def __init__(self, recs=None):
        self._recs = recs or {}

    def get_current(self, tid):
        return self._recs.get(tid)


def _old_thesis(*, days: float, extra=None, stance="hold"):
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rec = {
        "status": "active",
        "published_ts": ts,
        "updated_ts": ts,
        "summary": THICK,
        "stance": stance,
        "thesis_version": "symbol_x@v1",
    }
    if extra:
        rec["extra"] = extra
        rec.update(extra)
    return rec


def test_stale_days_for_income_vs_bond_vs_core():
    from scripts.lib.symbol_thesis_coverage import CLASS_SLA_DAYS, stale_days_for, coverage_class_for

    held = {"memberships": ["HELD"], "held": True}
    assert stale_days_for("JEPI", held) == 14
    assert stale_days_for("SCHD", held) == 14
    assert stale_days_for("PFLT", held) == 14
    assert stale_days_for("CSWC", held) == 14
    assert stale_days_for("DIV", held) == 14
    assert stale_days_for("DIVI", held) == 14
    assert coverage_class_for("JEPI", held) == "held_income"
    assert stale_days_for("BND", held) == 90
    assert coverage_class_for("BND", held) == "held_index_bond"
    assert stale_days_for("SCHG", held) == 30
    assert coverage_class_for("SCHG", held) == "held_growth_core"
    assert CLASS_SLA_DAYS["held_income"] == 14
    assert CLASS_SLA_DAYS["held_index_bond"] == 90
    assert CLASS_SLA_DAYS["held_growth_core"] == 30


def test_stale_days_for_reentry_and_watchlist():
    from scripts.lib.symbol_thesis_coverage import stale_days_for, coverage_class_for

    ready = {
        "memberships": ["REENTRY", "FORMER_HOLDING"],
        "held": False,
        "reentry": {"intel_state": "READY TO REVIEW"},
    }
    near = {
        "memberships": ["REENTRY"],
        "held": False,
        "reentry": {"intel_state": "NEAR ENTRY"},
    }
    watch = {"memberships": ["WATCHLIST"], "held": False, "watchlist": {"symbol": "XYZ"}}
    assert stale_days_for("AVAV", ready) == 14
    assert coverage_class_for("AVAV", ready) == "reentry_actionable"
    assert stale_days_for("DHX", near) == 14
    assert stale_days_for("XYZ", watch) == 45
    assert coverage_class_for("XYZ", watch) == "watchlist_actionable"


def test_classify_uses_class_sla_not_global_30():
    from scripts.lib.symbol_thesis_coverage import classify_symbol, symbol_thesis_id

    held = {"memberships": ["HELD"], "held": True}
    # 20d is stale for income (14) but current for bond (90) and growth (30)
    jepi_store = _Store({symbol_thesis_id("JEPI"): _old_thesis(days=20), "desk": None})
    bnd_store = _Store({symbol_thesis_id("BND"): _old_thesis(days=20), "desk": None})
    schg_store = _Store({symbol_thesis_id("SCHG"): _old_thesis(days=20), "desk": None})

    jepi = classify_symbol("JEPI", universe_rec=held, store=jepi_store)
    bnd = classify_symbol("BND", universe_rec=held, store=bnd_store)
    schg = classify_symbol("SCHG", universe_rec=held, store=schg_store)
    assert jepi["coverage_state"] == "STALE"
    assert jepi["sla_days"] == 14
    assert jepi["fresh"] is False
    assert jepi["has_current_symbol_thesis"] is True
    assert bnd["coverage_state"] == "CURRENT"
    assert bnd["sla_days"] == 90
    assert bnd["fresh"] is True
    assert schg["coverage_state"] == "CURRENT"
    assert schg["sla_days"] == 30
    assert schg["fresh"] is True


def test_age_gate_short_circuit_not_stale_by_age():
    from scripts.lib.symbol_thesis_coverage import classify_symbol, symbol_thesis_id

    held = {"memberships": ["HELD"], "held": True, "catalyst": True}
    store = _Store({symbol_thesis_id("JEPI"): _old_thesis(days=40), "desk": None})
    row = classify_symbol("JEPI", universe_rec=held, store=store)
    assert row["coverage_state"] != "STALE"
    assert row["coverage_state"] == "CURRENT"
    assert row["coverage_reason"].startswith("age_gate_short_circuit_")
    assert row["age_gate_short_circuit"] == "catalyst"
    assert row["fresh"] is False  # age still outside SLA
    assert row["has_current_symbol_thesis"] is True

    need = {"memberships": ["HELD"], "held": True, "intent": "NEED_DATA"}
    row2 = classify_symbol("JEPI", universe_rec=need, store=store)
    assert row2["coverage_state"] == "CURRENT"
    assert row2["age_gate_short_circuit"] == "need_data"

    earn = classify_symbol(
        "JEPI",
        universe_rec={"memberships": ["HELD"], "held": True},
        store=store,
        extra={"earnings": True},
    )
    assert earn["coverage_state"] == "CURRENT"
    assert earn["age_gate_short_circuit"] == "earnings"

    div = classify_symbol(
        "JEPI",
        universe_rec={"memberships": ["HELD"], "held": True},
        store=store,
        extra={"dividend": {"ex_date": "2026-08-01"}},
    )
    assert div["coverage_state"] == "CURRENT"
    assert div["age_gate_short_circuit"] == "dividend"


def test_build_coverage_report_publishes_coverage_and_fresh(tmp_path, monkeypatch):
    import scripts.lib.symbol_universe as su
    monkeypatch.setattr(su, "_former_from_db", lambda root: {})
    monkeypatch.setattr(su, "_watchlist_from_db", lambda root: {})
    from scripts.lib.cio_theses import CIOThesisStore
    from scripts.lib.symbol_thesis_coverage import build_coverage_report
    from scripts.lib.symbol_thesis_publish import publish_symbol_thesis

    (tmp_path / "data/portfolios/state").mkdir(parents=True)
    (tmp_path / "data/runtime").mkdir(parents=True)
    (tmp_path / "data/cio").mkdir(parents=True)
    (tmp_path / "data/portfolios/state/holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "JEPI", "quantity": 10, "is_cash": False},
            {"symbol": "BND", "quantity": 10, "is_cash": False},
            {"symbol": "CASH", "quantity": 1, "is_cash": True, "asset_type": "cash"},
        ]
    }))
    (tmp_path / "data/runtime/reentry_decision_desk_latest.json").write_text(json.dumps({
        "rows": [
            {"symbol": "AVAV", "held": False, "intel": {"state": "READY TO REVIEW"}},
            {"symbol": "DHX", "held": False, "intel": {"state": "NEAR ENTRY"}},
        ]
    }))
    store = CIOThesisStore(
        event_path=tmp_path / "data/cio/cio_theses.jsonl",
        projection_path=tmp_path / "data/cio/cio_theses_projection.json",
    )
    publish_symbol_thesis(
        "JEPI", summary=THICK, stance="hold", portfolio_role="INCOME",
        universe_memberships=["HELD"], store=store, notify=False,
    )
    rep = build_coverage_report(root=tmp_path, store=store)
    assert "coverage_pct" in rep and "fresh_pct" in rep
    assert isinstance(rep["coverage_pct"], float)
    assert isinstance(rep["fresh_pct"], float)
    held_slice = rep["slices"]["held"]
    assert held_slice["n"] == 2
    assert "CASH" not in held_slice["symbols"]
    assert set(held_slice["symbols"]) == {"BND", "JEPI"}
    reentry_slice = rep["slices"]["reentry_actionable"]
    assert reentry_slice["n"] == 2
    assert set(reentry_slice["symbols"]) == {"AVAV", "DHX"}
    assert "AVAV" not in held_slice["symbols"]
    assert held_slice["sla_target_pct"] == 100.0
    assert reentry_slice["sla_target_pct"] == 100.0


def test_actionable_helper_excludes_held_and_cash(tmp_path):
    from scripts.lib.symbol_thesis_coverage import actionable_universe_slices

    (tmp_path / "data/portfolios/state").mkdir(parents=True)
    (tmp_path / "data/runtime").mkdir(parents=True)
    (tmp_path / "data/portfolios/state/holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "JEPI", "is_cash": False},
            {"symbol": "CASH", "is_cash": True, "asset_type": "cash"},
        ]
    }))
    (tmp_path / "data/runtime/reentry_decision_desk_latest.json").write_text(json.dumps({
        "rows": [
            {"symbol": "AVAV", "held": False, "intel": {"state": "READY TO REVIEW"}},
            {"symbol": "CASH", "held": False, "intel": {"state": "READY TO REVIEW"}},
            {"symbol": "JEPI", "held": True, "intel": {"state": "CURRENTLY HELD"}},
        ]
    }))
    slices = actionable_universe_slices(root=tmp_path, universe={"symbols": {}})
    assert slices["held"] == ["JEPI"]
    assert "CASH" not in slices["held"]
    assert slices["reentry_actionable"] == ["AVAV"]
    assert "JEPI" not in slices["reentry_actionable"]
    assert "CASH" not in slices["reentry_actionable"]
