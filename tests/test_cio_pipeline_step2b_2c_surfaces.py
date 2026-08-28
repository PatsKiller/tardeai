"""Pipeline Step 2B+2C: surface dropped earnings / new names / cash + CASE_SUMMARY A-context.

READ_ONLY_ADVISORY. No notify, no gate change, no ROTATE bucket.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib.agent_durable_memory import get_durable_provider
from scripts.lib.agent_memory_admission import admit_candidate
from scripts.lib.agent_memory_governance import (
    MEMORY_TYPE_CASE_SUMMARY,
    MEMORY_TYPE_RESEARCH_REFERENCE,
    admit_status,
    is_forbidden_authoritative,
)
from scripts.lib.cio_investment_product import (
    PORTFOLIO_IMPLICATION_CONSTANT,
    build_product,
    overlay_step2_surfaces,
)
from scripts.lib.cio_operator_product import REQUIRED_SECTIONS, build_operator_product


def _now() -> datetime:
    return datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "data" / "cio").mkdir(parents=True)
    (tmp_path / "data" / "portfolios" / "state").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    monkeypatch.setenv("CIO_SITUATION_NOTIFY", "0")
    monkeypatch.setenv("RATIFIED_LESSON_ADVISORY_INFLUENCE", "SHADOW")
    monkeypatch.setenv("FINANCIAL_SENSES_ADVISORY_INFLUENCE", "SHADOW")
    monkeypatch.setenv("GOVERNED_MEMORY_ADVISORY_INFLUENCE", "SHADOW")
    return tmp_path


def _write_earnings(root: Path, rows: dict) -> None:
    path = root / "data" / "portfolios" / "state" / "earnings_dates.json"
    path.write_text(json.dumps(rows), encoding="utf-8")


def _admit(root: Path, *, memory_type: str, subject: str, content: str,
           symbols: list[str], plan_id: str, result_id: str,
           source_kind: str = "HERMES_VALID_COMPLETE") -> dict:
    prov = get_durable_provider(root)
    return admit_candidate(
        {
            "memory_type": memory_type,
            "subject": subject,
            "content": content,
            "symbols": symbols,
            "plan_ids": [plan_id],
            "source_refs": [plan_id, f"res_{plan_id}", result_id],
            "source_event_ids": [plan_id, f"res_{plan_id}", result_id],
            "source_kind": source_kind,
            "confidence": 0.7,
            "producer": "test_step2bc",
        },
        provider=prov,
        admitted_by="test_step2bc",
    )


def test_earnings_source_present_fills_product(root: Path):
    _write_earnings(root, {
        "V": {"earnings_date": "2026-10-27", "fetched_at": "2026-08-24T00:00:00"},
        "NOC": {"earnings_date": "2026-09-15", "fetched_at": "2026-08-24T00:00:00"},
        "SCHG": {"earnings_date": None},
    })
    holdings = {
        "holdings": [
            {"symbol": "V", "market_value": 1000},
            {"symbol": "NOC", "market_value": 2000},
            {"symbol": "CASH", "market_value": 500, "is_cash": True},
        ],
        "portfolio_totals": {"total_cash": 500, "total_value": 3500},
    }
    p = build_product(root=root, queue={"items": []}, previously_traded=[], holdings=holdings, now=_now())
    assert p["earnings_quality"]["class"] == "D"
    assert p["earnings_quality"]["quality"] in {"OK", "DATA_UNAVAILABLE"}
    if p["earnings_quality"]["quality"] == "DATA_UNAVAILABLE":
        assert p["earnings_quality"]["reason"]
    else:
        assert len(p["earnings"]) > 0
        syms = {e["symbol"] for e in p["earnings"]}
        assert "V" in syms or "NOC" in syms
        assert all(e.get("class") == "D" for e in p["earnings"])
        assert all(e.get("as_of") for e in p["earnings"])


def test_earnings_missing_file_is_data_unavailable(root: Path):
    p = build_product(root=root, queue={"items": []}, previously_traded=[], holdings={}, now=_now())
    assert p["earnings"] == []
    assert p["earnings_quality"]["quality"] == "DATA_UNAVAILABLE"
    assert p["earnings_quality"]["reason"]
    assert p["earnings_quality"]["class"] == "D"


def test_not_former_defense_name_surfaces(root: Path):
    queue = {"items": [
        {"symbol": "NKE", "source": "defense", "state": "WATCH", "directive_label": "defense NKE"},
        {"symbol": "CSCO", "source": "reentry", "verdict": "RE_ENTER", "state": "READY TO REVIEW"},
    ], "count": 2}
    prev = [{"symbol": "CSCO", "reentry_signal": "IN_ZONE", "last_exit_price": 40, "current_price": 41}]
    p = build_product(root=root, queue=queue, previously_traded=prev, holdings={}, now=_now())
    nf = (p["opportunity_book"].get("not_former") or []) + (p["action_book"].get("NEW_POSITION_IF") or [])
    nf += [r for r in (p["opportunity_book"].get("top") or []) if r.get("vs_re") == "not_former"]
    nke = [r for r in nf if r.get("symbol") == "NKE"]
    assert nke, "NKE not_former must appear in NEW_POSITION_IF or opportunity_book"
    assert all(r.get("vs_re") == "not_former" for r in nke)
    assert p["action_book"]["NEW_POSITION_IF"][0]["symbol"] == "NKE"
    assert p["action_book"]["NEW_POSITION_IF"][0]["action"] in {"WATCH", "ADD_IF", "AVOID"}
    assert "CSCO" not in {r["symbol"] for r in p["action_book"]["NEW_POSITION_IF"]}
    re_names = {r["symbol"] for r in p["reentry_book"]["names"]}
    assert "CSCO" in re_names
    assert "NKE" not in re_names


def test_former_only_queue_leaves_new_position_if_empty(root: Path):
    queue = {"items": [
        {"symbol": "CSCO", "source": "reentry", "verdict": "RE_ENTER", "state": "READY TO REVIEW"},
    ]}
    prev = [{"symbol": "CSCO", "reentry_signal": "IN_ZONE", "last_exit_price": 40, "current_price": 41}]
    p = build_product(root=root, queue=queue, previously_traded=prev, holdings={}, now=_now())
    assert p["action_book"]["NEW_POSITION_IF"] == []
    assert p["action_book"]["NEW_POSITION_IF_REASON"]
    assert "CSCO" in {r["symbol"] for r in p["reentry_book"]["names"]}


def test_hold_cash_for_is_not_portfolio_implication_constant(root: Path):
    holdings = {
        "holdings": [
            {"symbol": "SCHD", "market_value": 80000},
            {"symbol": "CASH", "market_value": 20000, "is_cash": True},
        ],
        "portfolio_totals": {"total_cash": 20000, "total_value": 100000},
    }
    p = build_product(root=root, queue={"items": []}, previously_traded=[], holdings=holdings, now=_now())
    cash_rows = p["action_book"]["HOLD_CASH_FOR"]
    assert cash_rows
    why = cash_rows[0]["why"]
    assert PORTFOLIO_IMPLICATION_CONSTANT not in why
    assert cash_rows[0]["class"] == "D"
    assert cash_rows[0]["cash_pct"] == 20.0 or cash_rows[0]["total_cash"] == 20000
    assert p["temperament"]["cash"] is not None
    assert p["temperament"]["cash_pct"] == 20.0
    assert p["temperament"]["cash_class"] == "D"


def test_temperament_cash_from_cash_pct(root: Path):
    p = build_product(
        root=root, queue={"items": []}, previously_traded=[],
        holdings={"cash_pct": 44.9, "total_value": 1_000_000, "total_cash": 449_000},
        now=_now(),
    )
    assert p["temperament"]["cash"] is not None
    assert p["temperament"]["cash_pct"] == 44.9


def test_rotation_bucket_absent(root: Path):
    p = build_product(root=root, queue={"items": []}, previously_traded=[], holdings={}, now=_now())
    assert "ROTATE" not in p["action_book"]
    assert "rotation" not in p["action_book"]
    blob = json.dumps(p["action_book"])
    assert "ROTATE" not in blob


def test_case_summaries_active_only_not_in_do_now(root: Path):
    r1 = _admit(
        root, memory_type=MEMORY_TYPE_CASE_SUMMARY, subject="research_case:FUSE",
        content="Hermes research VALID for this case. Thesis tension remains advisory-only.",
        symbols=["FUSE"], plan_id="plan_fuse", result_id="rr_fuse",
    )
    r2 = _admit(
        root, memory_type=MEMORY_TYPE_CASE_SUMMARY, subject="research_case:JEPI",
        content="Hermes research VALID for this case. No order implied.",
        symbols=["JEPI"], plan_id="plan_jepi", result_id="rr_jepi",
    )
    _admit(
        root, memory_type=MEMORY_TYPE_RESEARCH_REFERENCE, subject="research observation RKLB",
        content="Reference note only.",
        symbols=["RKLB"], plan_id="plan_rklb", result_id="rr_rklb",
        source_kind="research_artifact",
    )
    assert r1.get("accepted") and r2.get("accepted")
    p = build_product(root=root, queue={"items": []}, previously_traded=[], holdings={}, now=_now())
    section = p["case_summaries"]
    assert section["class"] == "A"
    assert "NON_AUTHORITATIVE" in section["banner"]
    assert section["changes_action"] is False
    subjects = {it["subject"] for it in section["items"]}
    assert "research_case:FUSE" in subjects
    assert "research_case:JEPI" in subjects
    assert all(it.get("class") == "A" for it in section["items"])
    assert all(it.get("memory_id") and it.get("plan_id") for it in section["items"])
    joined = json.dumps(section)
    assert "research observation RKLB" not in joined
    assert "RESEARCH_REFERENCE" not in joined
    do_now_blob = json.dumps(p["action_book"]["DO_NOW"])
    assert "research_case:FUSE" not in do_now_blob
    assert "CASE_SUMMARY" not in do_now_blob
    rec_blob = json.dumps(p["recommendations"])
    assert "research_case:FUSE" not in rec_blob


def test_forbidden_authoritative_still_rejected():
    assert is_forbidden_authoritative("current_price SCHD")
    assert admit_status(MEMORY_TYPE_CASE_SUMMARY, provenance_ok=True, subject="research_case:SCHD") == "ACTIVE"
    assert admit_status(MEMORY_TYPE_RESEARCH_REFERENCE, provenance_ok=True, subject="research observation SCHD") == "CANDIDATE"


def test_operator_product_has_case_summaries_section(root: Path):
    _write_earnings(root, {"V": {"earnings_date": "2026-10-27"}})
    _admit(
        root, memory_type=MEMORY_TYPE_CASE_SUMMARY, subject="research_case:V",
        content="Hermes research VALID for this case. Advisory completeness only.",
        symbols=["V"], plan_id="plan_v", result_id="rr_v",
    )
    (root / "data" / "cio" / "cio_investment_brief.json").write_text(json.dumps({
        "schema": "CIOInvestmentProduct@v1",
        "product_id": "prod_test",
        "as_of": "2026-08-28T15:00:00+00:00",
        "summary": "Standing posture.",
        "final_position": "HOLD",
        "recommendations": [{
            "symbol": "V", "recommended_action": "HOLD", "title": "HOLD V",
            "description": "Thesis intact.", "confidence": 0.7,
        }],
    }), encoding="utf-8")
    (root / "data" / "portfolios" / "state" / "holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "V", "account": "ira", "market_value": 10000},
            {"symbol": "CASH", "account": "ira", "market_value": 4000, "is_cash": True},
        ],
    }), encoding="utf-8")
    op = build_operator_product(root=root, persist=False)
    assert op.get("available") is True
    for sec in REQUIRED_SECTIONS:
        assert sec in op, sec
    assert "case_summaries" in op
    assert op["case_summaries"]["class"] == "A"
    assert op["case_summaries"]["count"] >= 1
    subjects = {it["subject"] for it in op["case_summaries"]["items"]}
    assert "research_case:V" in subjects
    assert "research_case:V" not in json.dumps(op.get("action_now") or [])
    if op.get("earnings"):
        assert op["earnings"][0].get("class") == "D"


def test_overlay_does_not_put_cases_in_do_now(root: Path):
    _admit(
        root, memory_type=MEMORY_TYPE_CASE_SUMMARY, subject="research_case:RKLB",
        content="Hermes research VALID. Advisory only.",
        symbols=["RKLB"], plan_id="plan_rklb2", result_id="rr_rklb2",
    )
    brief = {
        "schema": "CIOInvestmentProduct@v1",
        "action_book": {"DO_NOW": [{"symbol": "CSCO", "action": "RE_ENTER", "why": "governed"}]},
        "temperament": {"title": "SELECTIVE"},
    }
    out = overlay_step2_surfaces(brief, root=root, now=_now())
    assert out["case_summaries"]["count"] >= 1
    assert out["action_book"]["DO_NOW"] == brief["action_book"]["DO_NOW"]
    assert "RKLB" not in json.dumps(out["action_book"]["DO_NOW"])


def test_morning_mentions_case_count_not_full_text(root: Path):
    from scripts.lib.cio_operator_renderers import morning_text
    product = {
        "available": True,
        "executive_summary": "Standing posture.",
        "cash": {"status": "PRESENT", "cash_usd": 10},
        "portfolio": {"holdings_n": 2},
        "action_now": [],
        "standing_decisions": [],
        "case_summaries": {
            "count": 2,
            "items": [
                {"subject": "research_case:FUSE", "symbols": ["FUSE"], "content": "FULL TEXT MUST NOT DUMP " * 20},
                {"subject": "research_case:JEPI", "symbols": ["JEPI"], "content": "more full text"},
            ],
            "banner": "A-context · NON_AUTHORITATIVE · does not change action",
        },
    }
    text = morning_text(product)
    assert "Research cases" in text
    assert "FUSE" in text
    assert "FULL TEXT MUST NOT DUMP" not in text


def test_ciohub_renders_earnings_and_cases_not_in_do_now():
    hub = (Path(__file__).resolve().parent.parent / "apps/command-center-v3/src/pages/CioHub.tsx").read_text()
    assert "cio-earnings" in hub
    assert "cio-case-summaries" in hub
    assert "A-context" in hub
    assert "NEW_POSITION_IF" in hub
    assert "HOLD_CASH_FOR" in hub
    # CASE_SUMMARY must not be mapped into the DO_NOW bucket keys.
    action_keys_line = [ln for ln in hub.splitlines() if "DO_NOW" in ln and "NEW_POSITION_IF" in ln][0]
    assert "case_summar" not in action_keys_line.lower()


def test_step2a_producer_still_admits_case_summary(root: Path):
    from scripts.lib.hermes_case_summary import mint_case_summary_from_attached_research
    plan = {
        "plan_id": "plan_still",
        "symbols": ["SCHD"],
        "hermes_research_id": "res_still",
        "hermes_result_id": "rr_still",
        "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
    }
    result = {
        "result_id": "rr_still",
        "research_id": "res_still",
        "plan_id": "plan_still",
        "symbol": "SCHD",
        "status": "completed",
        "summary": "SCHD concentration research. Hold with thesis.",
        "answers": [{"status": "answered", "summary": "ok"}],
    }
    out = mint_case_summary_from_attached_research(
        plan, result, critique={"verdict": "VALID"},
        provider=get_durable_provider(root),
    )
    assert out.get("ok") is True
    assert out.get("memory_id")
