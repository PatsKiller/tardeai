"""P1.7 — thesis_driven / rag_first research_scheduler commissioning."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_producer_map_flags_thesis_driven_rag_first():
    path = ROOT / "docs" / "audits" / "AGENT_JOB_PRODUCER_MAP.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    row = next(p for p in data["producers"] if p["script"] == "scripts/research_scheduler.py")
    assert row["thesis_driven"] is True
    assert row["rag_first"] is True
    assert "gap" in (row.get("pipeline_order") or [])


def test_scheduler_flags_default_on():
    import scripts.research_scheduler as rs

    assert rs.THESIS_DRIVEN is True
    assert rs.RAG_FIRST is True
    assert rs.thesis_driven_enabled() is True
    assert rs.rag_first_enabled() is True
    assert rs.R71_PIPELINE_ORDER[0] == "gap"
    assert rs.R71_PIPELINE_ORDER[-1] == "synthesize"


def test_build_thesis_gap_commission_carries_thesis_id(monkeypatch):
    import scripts.research_scheduler as rs

    gap_req = {
        "thesis_id": "symbol_schg",
        "thesis_version": 2,
        "request_id": "str_abc",
        "research_gap": "Create living symbol thesis",
        "specific_question": "Why is SCHG still held (role=GROWTH)?",
    }
    out = rs.build_thesis_gap_commission("SCHG", tier="T0-HOLD", gap_request=gap_req)
    assert out is not None
    assert out["thesis_id"] == "symbol_schg"
    assert out["research_gap_id"] == "str_abc"
    assert out["specific_question"].startswith("Why is SCHG")
    assert out["RAG_FIRST"] is True
    assert out["rag_first"] is True
    assert out["materiality"] == "T1"
    assert out["pipeline_order"] == list(rs.R71_PIPELINE_ORDER)
    assert out["request_type"] == "thesis_gap_research"


def test_build_thesis_gap_commission_none_without_gap(monkeypatch):
    import scripts.research_scheduler as rs

    monkeypatch.setattr(
        "scripts.lib.symbol_thesis_research.research_requests_for_symbol",
        lambda *a, **k: [],
    )
    assert rs.build_thesis_gap_commission("ZZZZ", tier="T0-HOLD", gap_request=None) is None
    assert rs.build_thesis_gap_commission(
        "SCHG", tier="T0-HOLD", gap_request={"thesis_id": "x"}  # missing question
    ) is None


def test_dispatch_dry_run_attaches_thesis_id_when_gap_exists():
    import scripts.research_scheduler as rs

    gap = rs.build_thesis_gap_commission(
        "CSCO",
        tier="T1-WATCH",
        gap_request={
            "thesis_id": "symbol_csco",
            "request_id": "gap_csco_1",
            "research_gap": "re-entry living thesis",
            "specific_question": "For former holding CSCO: why was it owned?",
        },
    )
    res = rs.dispatch("CSCO", "local-gemma", "T1-WATCH", apply=False, thesis_gap=gap)
    assert res["ok"] is True
    assert res["thesis_id"] == "symbol_csco"
    assert "thesis_gap" in res["tail"]
    assert res["payload"]["RAG_FIRST"] is True


def test_canary_dry_plan_safe_without_db(monkeypatch, tmp_path):
    """Canary dry-run assertions safe without live DB secrets."""
    from scripts.lib.symbol_thesis_canary import plan_canary_publish

    monkeypatch.setattr(
        "scripts.lib.symbol_thesis_canary.thesis_fields_for_symbol",
        lambda sym, **k: {
            "thesis_summary": "",
            "thesis_state": "RESEARCH_REQUIRED",
            "symbol_thesis_id": f"symbol_{sym.lower()}",
        },
    )
    out = plan_canary_publish(["SCHG", "CSCO", "ANET"], root=tmp_path, apply=False, env={})
    assert out["mode"] == "dry"
    assert out["apply_blocked"] is False
    assert [r["symbol"] for r in out["rows"]] == ["SCHG", "CSCO", "ANET"]
    assert all(r.get("skip_reason") == "no_existing_summary_will_not_invent" for r in out["rows"])
    assert all(r["applied"] is False for r in out["rows"])
