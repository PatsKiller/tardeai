"""R18.2: persistent-root decoupling, product binding, standing cards, delivery audit."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.canonical_cognition_bind import bind_market_context
from scripts.lib.cio_delivery_audit import audit_delivery_flags, write_test_sink
from scripts.lib.cio_operator_product import build_operator_product
from scripts.lib.cio_operator_renderers import (
    command_center_view,
    deliver_eod,
    deliver_morning,
    eod_text,
    morning_text,
    telegram_text,
)
from scripts.lib.deploy_persist_simulation import simulate
from scripts.lib.operator_decision_contract import (
    COMPLETE,
    INVALID,
    NOT_PROVIDED,
    PARTIAL,
    completeness,
    normalize_decision,
)
from scripts.lib.operator_human_renderer import looks_like_raw_json, render_decision
from scripts.lib.persistent_overlay import overlay_data_source, overlay_is_safe
from scripts.lib.persistent_state_root import (
    copy_verified,
    decommission_plan,
    inventory,
    mark_legacy_read_only,
    migration_manifest,
)
from scripts.lib.r17_checkpoint_binding import bind_material_decision
from scripts.lib.research_intelligence_summary import from_research_result, render_human as render_research


def _seed(tmp: Path) -> None:
    (tmp / "data/cio").mkdir(parents=True)
    (tmp / "data/runtime").mkdir(parents=True)
    (tmp / "data/portfolios/state").mkdir(parents=True)
    brief = {
        "schema": "CIOInvestmentProduct@v1",
        "product_id": "prod_r18_2",
        "as_of": "2026-08-26T12:00:00+00:00",
        "summary": "Preserve quality growth. HOLD remains correct.",
        "final_position": "HOLD",
        "recommendations": [
            {
                "symbol": "SCHD",
                "recommended_action": "HOLD",
                "title": "HOLD SCHD",
                "description": "Thesis intact. Quality income compounder remains the core holding.",
                "rationale": "Thesis intact.",
                "priority": "LOW",
            },
            {
                "symbol": "V",
                "recommended_action": "WATCH",
                "title": "WATCH V",
                "description": "Credit services leading; watch concentration.",
                "priority": "HIGH",
            },
        ],
        "reentry_book": {"count": 1, "counts": {"NEAR": 1}},
    }
    (tmp / "data/cio/cio_investment_brief.json").write_text(json.dumps(brief))
    (tmp / "data/cio/outcome_checkpoints.jsonl").write_text("")
    (tmp / "data/cio/aif_memory.json").write_text(json.dumps({"n": 1}))
    (tmp / "data/portfolios/state/holdings.json").write_text(json.dumps({
        "holdings": [{"symbol": "SCHD", "account": "ira", "market_value": 40000},
                     {"symbol": "V", "account": "ira", "market_value": 77000, "is_cash": False}]
    }))
    (tmp / "data/runtime/advisory_desk_latest.json").write_text(json.dumps({"ok": True, "rows": []}))
    (tmp / "data/runtime/sector_momentum_latest.json").write_text(json.dumps({
        "generated_at": "2026-08-26T02:00:00+00:00",
        "transitions_today": [
            {"sector": "Materials", "from": "LAGGING", "to": "LEADING"},
        ],
        "rows": [
            {
                "sector": "Materials", "state": "LEADING", "book_pct": 7.4,
                "book_contributors": [{"fund": "XLB", "dollars": 27000}, {"fund": "SCHD", "dollars": 7000}],
            },
            {
                "sector": "Financials", "state": "LAGGING", "book_pct": 33.6,
                "book_contributors": [{"fund": "V", "dollars": 77000, "direct": True}],
            },
        ],
    }))
    (tmp / "data/runtime/industry_momentum_latest.json").write_text(json.dumps({
        "industries": [
            {"industry": "Credit Services", "sector": "Financials", "state": "LEADING",
             "held": ["V"], "watched": [], "rel1w": 4.45},
            {"industry": "Unrelated Widgets", "state": "LEADING", "held": [], "watched": [], "rel1w": 9.0},
        ]
    }))
    (tmp / "data/hermes/momentum_catalysts").mkdir(parents=True)
    (tmp / "data/hermes/momentum_catalysts/2026-08-26_catalysts.jsonl").write_text(
        json.dumps({"symbol": "V", "catalyst_type": "earnings", "headline": "V reports next week",
                    "date": "2026-08-28", "why_relevant": "Held credit-services name"}) + "\n"
    )


def test_inventory_classifies_source_tree(tmp_path: Path):
    _seed(tmp_path)
    inv = inventory(source=tmp_path)
    assert inv["n"] >= 10
    assert any(r["logical_store"] == "cio.checkpoints" for r in inv["rows"])


def test_copy_verified_hashes_and_no_delete(tmp_path: Path):
    src = tmp_path / "src"
    dst = tmp_path / "persistent"
    _seed(src)
    man = migration_manifest(source=src, dest=dst)
    assert man["destructive_changes"] is False
    out = copy_verified(source=src, dest=dst, manifest=man)
    assert out["ok"] is True
    assert out["destructive_applied"] is False
    assert (src / "data/cio/cio_investment_brief.json").is_file()
    assert (dst / "data/cio/cio_investment_brief.json").is_file()
    assert (dst / "PERSISTENT_STATE_ROOT.json").is_file()
    assert json.loads((src / "data/cio/cio_investment_brief.json").read_text()) == json.loads(
        (dst / "data/cio/cio_investment_brief.json").read_text()
    )
    mark = mark_legacy_read_only(src)
    assert mark["read_only"] is True
    assert mark["destructive_cleanup"] is False
    plan = decommission_plan(old=src, new=dst)
    assert plan["destructive_cleanup"] is False


def test_isolated_runtime_loads_copied_state(tmp_path: Path):
    src = tmp_path / "src"
    dst = tmp_path / "persistent"
    _seed(src)
    copy_verified(source=src, dest=dst)
    a = build_operator_product(root=src)
    b = build_operator_product(root=dst)
    assert a["generation_id"] == b["generation_id"]
    assert a["product_id"] == b["product_id"]
    assert len(a["decisions"]) == len(b["decisions"])


def test_deploy_survival_same_inodes(tmp_path: Path):
    sim = simulate(tmp=tmp_path / "sim")
    assert sim["same_inodes"] is True
    assert sim["switched_to_empty_source"] is False


def test_overlay_prefers_provisioned_persistent(tmp_path: Path, monkeypatch):
    root = tmp_path / "persistent-state"
    root.mkdir()
    (root / "PERSISTENT_STATE_ROOT.json").write_text(json.dumps({"schema": "PersistentStateRoot@v1"}))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(root))
    assert overlay_data_source(canonical_source=tmp_path / "source") == root


def test_rollback_is_config_revert(tmp_path: Path):
    src = tmp_path / "src"
    dst = tmp_path / "persistent"
    _seed(src)
    copy_verified(source=src, dest=dst)
    # Mismatch → keep using src
    (dst / "data/cio/cio_investment_brief.json").write_text("{broken")
    dest_safe = overlay_is_safe(canonical_source=src, dest=tmp_path / "empty_dest")
    assert dest_safe["ok"] is True  # dest empty, source has data
    # Integrity mismatch detected by re-hash
    man = migration_manifest(source=src, dest=dst)
    again = copy_verified(source=src, dest=dst, manifest=man)
    assert again["ok"] is True  # copy repairs dest from source


def test_sector_industry_catalyst_binding(tmp_path: Path):
    _seed(tmp_path)
    ctx = bind_market_context(root=tmp_path)
    assert ctx["sector"]
    assert any(s.get("sector") == "Materials" for s in ctx["sector"])
    assert any("7.4%" in (s.get("prose") or "") for s in ctx["sector"])
    assert ctx["industry"]
    assert any(i.get("industry") == "Credit Services" for i in ctx["industry"])
    assert not any(i.get("industry") == "Unrelated Widgets" for i in ctx["industry"])
    assert ctx["catalysts"]
    product = build_operator_product(root=tmp_path)
    assert product["sector"]
    assert product["industry"]
    assert product["catalysts"]
    assert product.get("sector_reason") is None
    mt = morning_text(product)
    assert "Materials" in mt
    assert "Credit Services" in mt or "Industry" in mt


def test_empty_events_have_reason_not_missing_binding(tmp_path: Path):
    (tmp_path / "data/cio").mkdir(parents=True)
    (tmp_path / "data/runtime").mkdir(parents=True)
    (tmp_path / "data/portfolios/state").mkdir(parents=True)
    (tmp_path / "data/cio/cio_investment_brief.json").write_text(json.dumps({
        "schema": "CIOInvestmentProduct@v1",
        "recommendations": [{"symbol": "NVDA", "recommended_action": "HOLD",
                             "title": "HOLD NVDA", "description": "Thesis intact."}],
    }))
    (tmp_path / "data/portfolios/state/holdings.json").write_text(json.dumps({"holdings": []}))
    product = build_operator_product(root=tmp_path)
    assert product["sector"] == []
    assert product["sector_reason"] == "NO_RELEVANT_CURRENT_EVENTS"
    assert product["industry_reason"] == "NO_RELEVANT_CURRENT_EVENTS"


def test_standing_hold_is_complete_contract():
    d = normalize_decision({
        "symbol": "SCHD",
        "recommended_action": "HOLD",
        "title": "HOLD SCHD",
        "description": "Thesis intact; quality compounder remains core.",
    }, generation_id="g1", as_of="2026-08-26T12:00:00+00:00")
    assert d["decision"] == "HOLD"
    assert d["decision_id"]
    assert d["entity"] == "SCHD"
    assert d["confidence"] is None
    assert d["confidence_status"] == NOT_PROVIDED
    assert "not fabricated" in d["confidence_text"]
    assert d["counter_evidence"]
    assert d["next_review_at"]
    assert "HOLD remains correct" in d["why_it_matters"] or "intact" in d["why_it_matters"].lower()
    text = render_decision(d)
    assert "Confidence:" in text
    assert "—" not in text.split("Confidence:")[1].splitlines()[0] or "not provided" in text
    assert looks_like_raw_json(text) is False


def test_hold_without_why_is_insufficient():
    d = normalize_decision({"symbol": "XYZ", "recommended_action": "HOLD"})
    assert d["decision"] == "INSUFFICIENT_DATA"
    assert d["confidence"] is None


def test_all_action_classes_have_required_fields():
    for action in ("HOLD", "WAIT", "WATCH", "REVIEW", "TRIM", "REENTER", "AVOID", "NO_ACTION"):
        d = normalize_decision({
            "symbol": "T",
            "recommended_action": action,
            "title": f"{action} T",
            "description": f"{action} remains the CIO view because evidence is unchanged.",
        })
        for f in ("decision_id", "entity", "decision", "urgency", "what_changed", "why_it_matters",
                  "operator_action", "counter_evidence", "data_quality", "created_at",
                  "last_confirmed_at", "next_review_at"):
            assert d.get(f) not in (None, ""), (action, f)
        assert "confidence" in d


def test_completeness_grades(tmp_path: Path):
    _seed(tmp_path)
    product = build_operator_product(root=tmp_path)
    c = completeness(product)
    assert c["grade"] in {COMPLETE, PARTIAL}
    assert not any(x.endswith("decision_id") for x in c.get("missing") or [])
    bad = completeness({"available": True, "decisions": [{"decision": "HOLD"}]})
    assert bad["grade"] == INVALID


def test_consumers_share_generation(tmp_path: Path):
    _seed(tmp_path)
    p = build_operator_product(root=tmp_path)
    cc = command_center_view(p)
    assert cc["generation_id"] == p["generation_id"]
    assert cc["decisions"][0]["decision_id"] == p["decisions"][0]["decision_id"]
    assert cc["hidden_alternative_calculation"] is False
    m1 = deliver_morning(root=tmp_path, send=False)
    m2 = deliver_morning(root=tmp_path, send=False)
    assert m1["published"] is True
    assert m2["reason"] == "semantic_duplicate"
    e1 = deliver_eod(root=tmp_path, send=False)
    e2 = deliver_eod(root=tmp_path, send=False)
    assert e2["reason"] == "semantic_duplicate"
    tg = telegram_text(p)
    assert "[CIO DECISION]" in tg
    assert looks_like_raw_json(tg) is False
    assert "Materials" in morning_text(p)


def test_delivery_audit_does_not_flip_canary(monkeypatch):
    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "0")
    monkeypatch.delenv("CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY", raising=False)
    a = audit_delivery_flags()
    assert a["AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY"] == "1"
    assert a["CIO_TELEGRAM_INTERDICT"] == "0"
    assert a["CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY"] in {"0", ""}
    assert a["LIVE_CIO_DELIVERY_AUTHORIZATION_REQUIRED"] is True
    assert a["canary_changed"] is False
    assert a["orders"] == 0


def test_sink_human_and_dedupe(tmp_path: Path):
    _seed(tmp_path)
    p = build_operator_product(root=tmp_path)
    sink = tmp_path / "sink.jsonl"
    seen = set()
    for d in p["decisions"]:
        rec = write_test_sink(d, path=sink, kind="IMMEDIATE")
        assert rec["raw_json"] is False
        assert rec["broker_call"] is False
        assert rec["order_execution"] is False
        key = d["decision_id"]
        assert key not in seen
        seen.add(key)
    # second send of same decision is a second sink row; semantic dedupe is the brief layer
    assert sink.is_file()


def test_research_normalization_regression():
    text = render_research(from_research_result({
        "symbol": "NOC", "question": "thesis", "why_researched": "earnings",
        "what_was_found": "in-line", "material_change": False,
        "thesis_effect": "UNCHANGED", "decision_effect": "NONE",
        "confidence": 0.6, "unresolved_gaps": ["10-Q"],
    }))
    assert "why" in text.lower() or "Question" in text
    assert looks_like_raw_json(text) is False


def test_cash_unchanged_binds_do_not_grow(tmp_path: Path):
    from tests.test_r17_cash_checkpoint import NOW, _cash
    (tmp_path / "data/cio").mkdir(parents=True)
    (tmp_path / "data/cio/outcome_checkpoints.jsonl").write_text("")
    first = bind_material_decision(tmp_path, _cash(decision_id="d0", digest="jitter-0"), source_sha="s", persist=True, now=NOW)
    assert first["wrote_n"] == 3
    wrote = 0
    for i in range(200):
        r = bind_material_decision(
            tmp_path, _cash(decision_id=f"d{i+1}", digest=f"jitter-{i+1}"),
            source_sha="s", persist=True, now=NOW,
        )
        wrote += r["wrote_n"]
        assert r["skipped_n"] == 3
    assert wrote == 0
    lines = (tmp_path / "data/cio/outcome_checkpoints.jsonl").read_text().strip().splitlines()
    assert len(lines) == 3
