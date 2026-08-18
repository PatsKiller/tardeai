"""Research completion → CIO investment-product reassessment (R6.8 missing link)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.cio_investment_product import build_product, persist_product
from scripts.lib.cio_product_reassessment import (
    already_completed,
    diff_products,
    reassess_on_research_completed,
    recover_parent,
    research_impact,
    retry_pending_reassessments,
)
from scripts.lib.hermes_research_loop import on_hermes_completed


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "data" / "cio").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    monkeypatch.setenv("RATIFIED_LESSON_ADVISORY_INFLUENCE", "SHADOW")
    monkeypatch.setenv("FINANCIAL_SENSES_ADVISORY_INFLUENCE", "SHADOW")
    monkeypatch.setenv("GOVERNED_MEMORY_ADVISORY_INFLUENCE", "SHADOW")
    return tmp_path


def _anet_prev():
    return [{"symbol": "ANET", "reentry_signal": "WATCH", "last_exit_price": 80, "current_price": 90}]


def _anet_ready():
    return [{"symbol": "ANET", "reentry_signal": "IN_ZONE", "last_exit_price": 80,
             "current_price": 81, "reentry_zone_low": 70, "reentry_zone_high": 85, "pct_above_exit": 1}]


def test_parent_recovered_from_plan_id():
    p = recover_parent({"plan_id": "plan_abc123def456"}, {"result_id": "rr_1", "symbol": "ANET"})
    assert p["status"] == "RECOVERED"
    assert p["plan_id"] == "plan_abc123def456"
    assert p["parent_key"] == "plan_abc123def456"


def test_orphan_legacy_not_symbol_attached():
    p = recover_parent({}, {"result_id": "rr_orphan", "symbol": "ANET"})
    assert p["status"] == "ORPHANED_LEGACY"
    assert p["parent_run_id"] is None
    assert p["parent_key"] == "global_product"


def test_simple_research_change_reassesses(root: Path):
    persist_product(build_product(root=root, queue={"items": []}, previously_traded=_anet_prev(), holdings={}), root=root)
    out = reassess_on_research_completed(
        {"plan_id": "plan_aaaaaaaa", "symbol": "ANET"},
        {"result_id": "rr_anet_1", "research_id": "res_anet_1", "symbol": "ANET",
         "summary": "VALID zone confirmation", "status": "completed"},
        critique={"verdict": "VALID", "confidence": 0.7},
        root=root,
        previously_traded=_anet_ready(),
        queue={"items": [{"symbol": "ANET", "source": "reentry", "directive_label": "Re-entry NEAR ENTRY — ANET"}]},
        holdings={},
    )
    assert out["ok"] is True
    assert out["duplicate"] is False
    assert out["parent"]["status"] == "RECOVERED"
    prod = out["product"]
    assert prod["previous_product_id"]
    assert prod["product_id"] != prod["previous_product_id"]
    assert "what_changed" in prod
    assert (root / "data/cio/cio_investment_brief.json").is_file()
    brief = build_product(root=root, previously_traded=_anet_ready(),
                          queue={"items": [{"symbol": "ANET", "source": "reentry",
                                            "directive_label": "Re-entry NEAR ENTRY — ANET"}]}, holdings={})
    names = {r["symbol"]: r for r in brief["reentry_book"]["names"]}
    assert names["ANET"]["governed_verdict"] is None  # research is not RE_ENTER
    assert out["notification"]["notification_class"]
    assert "place_order" not in str(out).lower()


def test_no_material_change(root: Path):
    prev = _anet_prev()
    persist_product(build_product(root=root, queue={"items": []}, previously_traded=prev, holdings={}), root=root)
    out = reassess_on_research_completed(
        {"plan_id": "plan_bbbbbbbb", "symbol": "ANET"},
        {"result_id": "rr_anet_same", "symbol": "ANET", "summary": "confirms wait", "status": "completed"},
        critique={"verdict": "VALID"},
        root=root,
        previously_traded=prev,
        queue={"items": []},
        holdings={},
    )
    assert out["ok"]
    assert out["impact"]["impact"] == "NO_MATERIAL_CHANGE"
    wc = out["product"]["what_changed"]
    assert wc["material"] is False
    assert out["notification"]["notification_class"] in {
        "COMMAND_CENTER_ONLY", "DIGEST", "SUPPRESSED",
    }


def test_negative_research_downgrade(root: Path):
    persist_product(build_product(
        root=root, previously_traded=_anet_ready(),
        queue={"items": [{"symbol": "ANET", "source": "reentry", "verdict": "RE_ENTER"}]},
        holdings={},
    ), root=root)
    out = reassess_on_research_completed(
        {"plan_id": "plan_cccccccc", "symbol": "ANET"},
        {"result_id": "rr_anet_broke", "symbol": "ANET", "summary": "thesis broken", "status": "completed"},
        critique={"verdict": "VALID"},
        root=root,
        previously_traded=[{"symbol": "ANET", "reentry_signal": "ABOVE_ZONE", "pct_above_exit": 40}],
        queue={"items": []},
        holdings={},
    )
    assert out["ok"]
    assert out["impact"]["impact"] in {"WEAKENED", "BROKEN"}
    assert out["impact"]["new_state"] == "AVOID"


def test_duplicate_completion_no_second_product(root: Path):
    args = dict(
        request={"plan_id": "plan_dddddddd", "symbol": "ANET"},
        result={"result_id": "rr_dup", "symbol": "ANET", "summary": "once", "status": "completed"},
        critique={"verdict": "VALID"},
        root=root,
        previously_traded=_anet_prev(),
        queue={"items": []},
        holdings={},
    )
    persist_product(build_product(root=root, previously_traded=_anet_prev(), queue={"items": []}, holdings={}), root=root)
    a = reassess_on_research_completed(**args)
    first_id = a["product"]["product_id"]
    b = reassess_on_research_completed(**args)
    assert b["duplicate"] is True
    assert b["product_id"] == first_id
    assert b["notification"]["notification_class"] == "SUPPRESSED"
    idx = already_completed(a["reassessment_id"], root=root)
    assert idx["product_id"] == first_id


def test_restart_retries_pending_without_rerunning_research(root: Path, monkeypatch: pytest.MonkeyPatch):
    persist_product(build_product(root=root, previously_traded=_anet_prev(), queue={"items": []}, holdings={}), root=root)
    calls = {"n": 0}
    real_build = build_product

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic persist fail")
        return real_build(*a, **k)

    monkeypatch.setattr("scripts.lib.cio_investment_product.build_product", boom)
    first = reassess_on_research_completed(
        {"plan_id": "plan_eeeeeeee"},
        {"result_id": "rr_retry", "symbol": "ANET", "summary": "ok", "status": "completed"},
        critique={"verdict": "VALID"},
        root=root,
        previously_traded=_anet_prev(),
        queue={"items": []},
        holdings={},
    )
    assert first["status"] == "REASSESSMENT_PENDING"
    monkeypatch.setattr("scripts.lib.cio_investment_product.build_product", real_build)
    # retry uses the module-level import inside the function
    retry = retry_pending_reassessments(root=root, limit=5)
    assert retry["paid_research_repeated"] is False
    assert retry["retried_ok"] >= 1


def test_orphan_legacy_classified(root: Path):
    persist_product(build_product(root=root, previously_traded=[], queue={"items": []}, holdings={}), root=root)
    out = reassess_on_research_completed(
        {},
        {"result_id": "rr_orphan2", "symbol": "ZZZZ", "summary": "no parent", "status": "completed"},
        critique={"verdict": "VALID"},
        root=root,
        previously_traded=[],
        queue={"items": []},
        holdings={},
    )
    assert out["parent"]["status"] == "ORPHANED_LEGACY"
    assert out["parent"]["parent_run_id"] is None
    assert out["ok"]


def test_what_changed_ignores_timestamp_only():
    prior = {
        "as_of": "2026-08-18T20:00:00+00:00",
        "temperament": {"title": "RISK OFF — SELECTIVE RISK"},
        "reentry_book": {"names": [{"symbol": "ANET", "status": "WAIT"}]},
        "opportunity_book": {"top": [{"symbol": "CSCO", "rank": 2}]},
        "action_book": {"WATCH_CLOSELY": [{"symbol": "ANET"}]},
    }
    new = {
        "as_of": "2026-08-18T22:00:00+00:00",
        "temperament": {"title": "RISK OFF — SELECTIVE RISK"},
        "reentry_book": {"names": [{"symbol": "ANET", "status": "WAIT"}]},
        "opportunity_book": {"top": [{"symbol": "CSCO", "rank": 2}]},
        "action_book": {"WATCH_CLOSELY": [{"symbol": "ANET"}]},
    }
    wc = diff_products(prior, new)
    assert wc["material"] is False
    assert wc["item_count"] == 0


def test_what_changed_reentry_upgrade_and_opp_downgrade():
    prior = {
        "temperament": {"title": "A"},
        "reentry_book": {"names": [{"symbol": "ANET", "status": "WAIT"}]},
        "opportunity_book": {"top": [{"symbol": "CSCO", "rank": 1}]},
        "action_book": {},
    }
    new = {
        "temperament": {"title": "B"},
        "reentry_book": {"names": [{"symbol": "ANET", "status": "NEAR"}]},
        "opportunity_book": {"top": [{"symbol": "CSCO", "rank": 8}]},
        "action_book": {},
    }
    wc = diff_products(prior, new)
    kinds = {i["kind"] for i in wc["items"]}
    assert "reentry_upgrade" in kinds
    assert "opportunity_rank_change" in kinds
    assert "temperament_changed" in kinds
    assert wc["material"] is True


def test_hook_calls_reassessment(root: Path):
    persist_product(build_product(root=root, previously_traded=_anet_prev(), queue={"items": []}, holdings={}), root=root)
    out = on_hermes_completed(
        {"plan_id": "", "symbol": "ANET"},
        {"result_id": "rr_hook", "symbol": "ANET", "summary": "x", "status": "completed"},
        resynth=False,
        notify=False,
    )
    assert out.get("reassessment") or out.get("reassessment_error")
    if out.get("reassessment"):
        assert out["reassessment"].get("reassessment_id")


def test_cc_shows_what_changed():
    hub = (Path(__file__).resolve().parent.parent / "apps/command-center-v3/src/pages/CioHub.tsx").read_text()
    assert "cio-what-changed" in hub
    assert "what_changed" in hub
    loop = (Path(__file__).resolve().parent.parent / "apps/command-center-v3/src/pages/ClosedLoopPanel.tsx").read_text()
    assert "cio-reassessment-chain" in loop


def test_no_broker_in_reassessment_module():
    text = (Path(__file__).resolve().parent.parent / "scripts/lib/cio_product_reassessment.py").read_text()
    for needle in ("place_order", "cancel_order", "broker.submit", "send_telegram("):
        assert needle not in text


def test_research_impact_insufficient():
    imp = research_impact(
        symbol="ANET", result_id="rr_x", research_id="res_x",
        prior={"reentry_book": {"names": [{"symbol": "ANET", "status": "NEAR"}]}},
        new={"reentry_book": {"names": [{"symbol": "ANET", "status": "NEAR"}]}},
        critique={"verdict": "INSUFFICIENT"},
    )
    assert imp["impact"] == "INSUFFICIENT"
    assert imp["schema"] == "ResearchImpact@v1"
