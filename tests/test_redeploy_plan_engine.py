#!/usr/bin/env python3
"""Phase B — institutional plan engine acceptance (FCNTX fixture)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _fcntx_event():
    dt = _load("redeploy_data_truth", "scripts/lib/redeploy_data_truth.py")
    ev = {
        "event_key": "txn:test",
        "symbol": "FCNTX",
        "account": "schwab_rollover_ira",
        "proceeds_usd": 107023.01,
        "cash_visible_usd": 17540.67,
        "proxy_symbol": "SCHG",
        "instrument_type": "mutual_fund",
        "metadata": {},
    }
    return dt.enrich_event_phase_a(ev)


def test_seven_plans_generated():
    eng = _load("redeploy_plan_engine", "scripts/lib/redeploy_plan_engine.py")
    ev = _fcntx_event()
    bundle = eng.build_institutional_plans(
        ev,
        v1_targets=[{"symbol": "JEPQ", "score": 124.5, "rationale": "test", "evidence": {}}],
        sleeve_gaps=[{"theme": "Defense / Aerospace", "gap_pct": 2.39}],
        sale_ctx={"tier": "major"},
    )
    archetypes = {p["plan_archetype"] for p in bundle["plans"]}
    assert archetypes == set("ABCDEFG")


def test_plan_f_respects_deployable_cap():
    eng = _load("redeploy_plan_engine", "scripts/lib/redeploy_plan_engine.py")
    ev = _fcntx_event()
    bundle = eng.build_institutional_plans(ev, sale_ctx={"tier": "major"})
    plan_f = next(p for p in bundle["plans"] if p["plan_archetype"] == "F")
    actionable = sum(
        l["target_dollars"] for l in plan_f["legs"] if not l.get("is_reserve")
    )
    deployable = ev["metadata"]["phase_a"]["reconciliation"]["deployable_cash_usd"]
    assert actionable <= deployable + 1.0
    assert plan_f["total_deployable_usd"] <= deployable + 1.0


def test_plan_g_full_reserve():
    eng = _load("redeploy_plan_engine", "scripts/lib/redeploy_plan_engine.py")
    ev = _fcntx_event()
    bundle = eng.build_institutional_plans(ev, sale_ctx={"tier": "major"})
    plan_g = next(p for p in bundle["plans"] if p["plan_archetype"] == "G")
    assert plan_g["total_deployable_usd"] == 0.0
    assert plan_g["reserve_usd"] == 107023.01


def test_schg_not_in_equity_legs():
    eng = _load("redeploy_plan_engine", "scripts/lib/redeploy_plan_engine.py")
    ev = _fcntx_event()
    bundle = eng.build_institutional_plans(ev, sale_ctx={"tier": "major"})
    for plan in bundle["plans"]:
        for leg in plan["legs"]:
            if not leg.get("is_reserve"):
                assert leg["ticker"] != "SCHG"


def test_ita_tactical_not_strategic_primary():
    eng = _load("redeploy_plan_engine", "scripts/lib/redeploy_plan_engine.py")
    ev = _fcntx_event()
    bundle = eng.build_institutional_plans(
        ev,
        sleeve_gaps=[{"theme": "Defense / Aerospace", "gap_pct": 2.39}],
        sale_ctx={"tier": "major"},
    )
    plan_a_syms = {
        l["ticker"] for p in bundle["plans"] if p["plan_archetype"] == "A"
        for l in p["legs"] if not l.get("is_reserve")
    }
    assert "ITA" not in plan_a_syms
    plan_e = next(p for p in bundle["plans"] if p["plan_archetype"] == "E")
    e_syms = {l["ticker"] for l in plan_e["legs"] if not l.get("is_reserve")}
    assert "ITA" in e_syms or "XAR" in e_syms


def test_rejected_includes_proxy():
    eng = _load("redeploy_plan_engine", "scripts/lib/redeploy_plan_engine.py")
    ev = _fcntx_event()
    bundle = eng.build_institutional_plans(ev, sale_ctx={"tier": "major"})
    codes = {r["reason_code"] for r in bundle["rejected_alternatives"]}
    assert "RPL-001" in codes


def test_major_sale_stays_draft_pending_oversight():
    eng = _load("redeploy_plan_engine", "scripts/lib/redeploy_plan_engine.py")
    ev = _fcntx_event()
    bundle = eng.build_institutional_plans(ev, sale_ctx={"tier": "major"})
    for p in bundle["plans"]:
        assert p["operator_status"] == "draft"
        assert p["oversight_status"] == "pending"


if __name__ == "__main__":
    tests = [
        test_seven_plans_generated,
        test_plan_f_respects_deployable_cap,
        test_plan_g_full_reserve,
        test_schg_not_in_equity_legs,
        test_ita_tactical_not_strategic_primary,
        test_rejected_includes_proxy,
        test_major_sale_stays_draft_pending_oversight,
    ]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"ALL {len(tests)} PASSED")