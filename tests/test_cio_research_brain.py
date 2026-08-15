"""Phases 11–16 — research-brain foundation (dry, no network)."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_market_calendar import (  # noqa: E402
    calendar_backend,
    is_options_expiration,
    is_options_expiration_week,
    third_friday,
)
from scripts.lib.cio_research_grader import EVIDENCE_GRADES, grade_evidence  # noqa: E402
from scripts.lib.cio_research_library import FAMILY_IDS, family_catalog, library_facts  # noqa: E402
from scripts.lib.cio_research_registry import GRADE_CODES, ResearchSourceRegistry  # noqa: E402
from scripts.lib.cio_research_retriever import (  # noqa: E402
    retrieve_for_decision,
    retrieve_research_context,
)
from scripts.lib.cio_seasonality_analytics import (  # noqa: E402
    august_general,
    august_midterm,
    reproduced_weak_months,
    september_general,
    september_midterm,
)
from scripts.lib.cio_seasonality_engine import (  # noqa: E402
    month_context,
    presidential_cycle_year,
)
from scripts.lib.cio_strategy_knowledge import compose_strategy_context  # noqa: E402


def test_grades_exist():
    assert GRADE_CODES == frozenset({"A", "B", "C", "D", "X"})
    assert set(EVIDENCE_GRADES) == {"A", "B", "C", "D", "X"}
    assert EVIDENCE_GRADES["A"]["label"] == "robust"
    assert EVIDENCE_GRADES["B"]["label"] == "useful"
    assert EVIDENCE_GRADES["C"]["label"] == "exploratory"
    assert EVIDENCE_GRADES["D"]["label"] == "source_claim"
    assert EVIDENCE_GRADES["X"]["label"] == "invalidated"


def test_2026_is_midterm():
    rec = presidential_cycle_year(2026)
    assert rec["cycle_label"] == "midterm_year"
    assert rec["partisan_conclusion"] is None


def test_august_general_reproduction_from_fixture():
    rec = august_general()
    assert rec["n"] >= 20
    assert rec["mean"] is not None
    assert rec["win_rate"] is not None
    assert rec["evidence_grade"] in GRADE_CODES
    assert rec["source_claim"]["title"]
    assert rec["source_claim"]["url"].startswith("https://www.stocktradersalmanac.com/")
    assert rec["source_claim"]["date"]
    assert rec["source_claim"]["fulltext"] is False
    assert "n=" in rec["trade_ai_reproduction"]
    assert rec["current_applicability"]
    assert rec["oos_note"]


def test_september_general_reproduction_from_fixture():
    rec = september_general()
    assert rec["n"] >= 20
    assert rec["mean"] is not None
    assert rec["win_rate"] is not None
    assert rec["evidence_grade"] in GRADE_CODES
    assert rec["source_claim"]["url"].startswith("https://www.stocktradersalmanac.com/")
    assert rec["source_claim"]["fulltext"] is False


def test_midterm_slices_have_stats():
    for rec in (august_midterm(), september_midterm()):
        assert rec["n"] >= 10
        assert rec["cycle_label"] == "midterm_year"
        assert rec["mean"] is not None
        assert rec["evidence_grade"] in GRADE_CODES


def test_sta_source_claims_remain_layered():
    for rec in (
        august_general(),
        august_midterm(),
        september_general(),
        september_midterm(),
    ):
        layers = rec["layers"]
        assert layers["source_claim"] != layers["trade_ai_reproduction"]
        assert layers["trade_ai_reproduction"] != layers["current_application"]
        assert layers["source_claim"] != layers["current_application"]
        assert rec["source_claim"] != rec["trade_ai_reproduction"]
        assert rec["trade_ai_reproduction"] != rec["current_applicability"]
        assert rec["standalone_sell"] is False
        assert rec["creates_trim"] is False


def test_retrieve_research_context_attaches_governed_audit():
    ctx = retrieve_research_context(
        datetime(2026, 8, 14, tzinfo=timezone.utc),
        decision_id="dec_cio_wire_dry",
    )
    audit = ctx.get("governed_audit") or {}
    assert audit.get("status") == "OK", audit
    assert audit.get("signature_ok") is True
    assert audit.get("decision_id") == "dec_cio_wire_dry"
    assert float(audit.get("influence_cap_pct") or 99) <= 10.0
    assert audit.get("creates_trim") is False
    assert audit.get("standalone_sell") is False
    assert audit.get("partisan_conclusion") is None
    assert "standalone_sell" in (audit.get("forbidden_actions") or [])
    almanac = ctx.get("governed_almanac") or {}
    slices = almanac.get("slices") or {}
    assert "september_general" in slices
    layers = (slices["september_general"].get("layers") or {})
    assert set(layers) == {"source_claim", "trade_ai_reproduction", "current_application"}
    assert layers["source_claim"].get("citation_only") is True
    assert layers["source_claim"].get("fulltext") is False


def test_governed_audit_fail_soft_when_bundle_raises(monkeypatch):
    import scripts.lib.research_governance.almanac as almanac

    def _boom(*_a, **_k):
        raise RuntimeError("fixture missing")

    monkeypatch.setattr(almanac, "bundle", _boom)
    ctx = retrieve_research_context(datetime(2026, 8, 14, tzinfo=timezone.utc))
    assert ctx["authority"] == "READ_ONLY_ADVISORY"
    assert ctx["influence"]["creates_trim"] is False
    assert ctx["governed_audit"]["status"] == "UNAVAILABLE"
    assert "fixture missing" in str(ctx["governed_audit"].get("reason") or "")


def test_retrieve_does_not_emit_autonomous_execution():
    ctx = retrieve_for_decision(now=datetime(2026, 8, 14, tzinfo=timezone.utc))
    compact = retrieve_research_context(datetime(2026, 8, 14, tzinfo=timezone.utc))
    for payload in (ctx, compact):
        assert payload.get("authority") == "READ_ONLY_ADVISORY"
        assert payload.get("execution_engine") is False
        assert payload.get("role") == "risk_modifier_or_context"
        assert payload.get("autonomous_execution") is not True
        blob = json.dumps(payload)
        assert "autonomous_execution" not in blob
        assert payload["influence"]["standalone_sell"] is False
        assert payload["influence"]["creates_trim"] is False
        assert payload["influence"]["max_conviction_sizing_modifier_pct"] == 10.0


def test_august_is_not_a_standalone_sell_signal():
    rec = august_general()
    ctx = retrieve_research_context(datetime(2026, 8, 6, tzinfo=timezone.utc))
    composed = compose_strategy_context(now=datetime(2026, 8, 6, tzinfo=timezone.utc))
    assert rec["standalone_sell"] is False
    assert rec["creates_trim"] is False
    assert "never a standalone sell" in rec["current_applicability"].lower()
    assert ctx["influence"]["standalone_sell"] is False
    assert ctx["influence"]["creates_trim"] is False
    assert composed["standalone_sell"] is False
    assert composed["creates_trim"] is False
    blob = json.dumps(ctx).lower()
    assert "trim" not in blob or "do not create trim" in blob
    assert composed.get("role") == "risk_modifier_or_context"


def test_august_appears_in_weak_month_hypothesis_after_reproduction():
    weak = reproduced_weak_months()
    assert 8 in weak
    assert 9 in weak
    aug = month_context(8)
    assert "weaker" in aug["hypothesis_bucket"]
    assert 8 in aug["weak_months_reproduced"]


def test_options_expiration_is_not_day_15_21():
    # April 2026 starts Wednesday → 3rd Friday is 17 April, not the 15th.
    assert third_friday(2026, 4) == date(2026, 4, 17)
    assert is_options_expiration(date(2026, 4, 17))
    assert not is_options_expiration(date(2026, 4, 15))
    assert 15 <= 15 <= 21
    assert calendar_backend() in {
        "pandas_market_calendars",
        "exchange_calendars",
        "weekday_us_federal_holiday_table",
    }
    # A Wednesday the 15th is inside 15–21 but is not expiration week Friday.
    assert not is_options_expiration(datetime(2026, 4, 15, tzinfo=timezone.utc))
    assert is_options_expiration_week(date(2026, 4, 17))


def test_grader_d_without_reproduction():
    g = grade_evidence(reproduced=False)
    assert g["evidence_grade"] == "D"


def test_library_families_present():
    cats = {c["id"] for c in family_catalog()["families"]}
    assert cats == set(FAMILY_IDS)
    assert "seasonality" in cats
    assert "wealth_tax" in cats
    facts = library_facts()
    assert any(f["family"] == "seasonality" and f.get("n") for f in facts)


def test_capital_plan_retrieves_research_before_strategy_and_does_not_trim():
    from scripts.lib.cio_capital_plan import build_capital_plan_from_sources

    plan = build_capital_plan_from_sources(
        holdings_doc=None,
        now=datetime(2026, 8, 14, tzinfo=timezone.utc),
        attach_financial_truth_gate=False,
    )
    rc = plan.get("research_context") or {}
    sc = plan.get("strategy_context") or {}
    assert rc.get("authority") == "READ_ONLY_ADVISORY"
    assert rc.get("execution_engine") is False
    assert rc.get("influence", {}).get("creates_trim") is False
    assert rc.get("influence", {}).get("standalone_sell") is False
    assert sc.get("creates_trim") is False
    stances = {d.get("stance") or d.get("action_label") for d in (plan.get("position_decisions") or [])}
    assert "TRIM" not in stances


def test_registry_seeds_sta_citations():
    reg = ResearchSourceRegistry()
    seeded = reg.seed_public_sta_alerts()
    assert len(seeded) == 4
    for s in seeded:
        assert s["url"].startswith("https://www.stocktradersalmanac.com/")
        assert s["fulltext"] is False
        assert s["evidence_grade"] == "D"  # citation layer
