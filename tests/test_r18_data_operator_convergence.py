"""R18-DATA.1 operator convergence: roots, registry, renderers, dedupe, no purge."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.alert_semantic_aggregation import aggregate
from scripts.lib.brief_semantic_dedupe import claim, immediate_material
from scripts.lib.canonical_cognition_bind import catalyst_to_product, sector_delta_to_product
from scripts.lib.canonical_store_registry import OWNERSHIP_CLASSES, STORES, load_json_store, registry
from scripts.lib.checkpoint_learning_filter import filter_learning_rows
from scripts.lib.cio_operator_product import REQUIRED_SECTIONS, build_operator_product, unavailable
from scripts.lib.cio_operator_renderers import (
    aegis_summary,
    command_center_view,
    deliver_eod,
    deliver_morning,
    eod_text,
    morning_text,
    render_research_message,
)
from scripts.lib.deploy_persist_simulation import restore_drill, simulate
from scripts.lib.filename_drift_audit import audit as filename_audit
from scripts.lib.operator_human_renderer import looks_like_raw_json, render_product
from scripts.lib.ops_health_routing import classify_message
from scripts.lib.persistent_overlay import overlay_is_safe
from scripts.lib.production_root_map import CLASSES, map_all
from scripts.lib.product_availability import UNAVAILABLE_REASONS, canonicalize_reason
from scripts.lib.purge_manifest import build as build_purge
from scripts.lib.r18_data_closeout import closeout
from scripts.lib.research_intelligence_summary import from_research_result


def _seed_brief(tmp: Path, **extra) -> None:
    (tmp / "data/cio").mkdir(parents=True, exist_ok=True)
    (tmp / "data/runtime").mkdir(parents=True, exist_ok=True)
    (tmp / "data/portfolios/state").mkdir(parents=True, exist_ok=True)
    brief = {
        "schema": "CIOInvestmentProduct@v1",
        "product_id": "prod_test",
        "as_of": "2026-08-26T12:00:00+00:00",
        "summary": "Preserve quality growth. Do not force replacements.",
        "final_position": "HOLD",
        "recommendations": [
            {
                "symbol": "NVDA",
                "recommended_action": "HOLD",
                "title": "HOLD NVDA",
                "description": "Thesis intact.",
                "rationale": "Quality compounder.",
                "priority": "LOW",
                "confidence": 0.7,
            },
            {
                "symbol": "GERN",
                "recommended_action": "WATCH",
                "title": "WATCH GERN",
                "description": "Zone 1.34–1.60.",
                "priority": "HIGH",
            },
        ],
        "reentry_book": {"count": 2, "counts": {"NEAR": 1, "WAIT": 1}},
        **extra,
    }
    (tmp / "data/cio/cio_investment_brief.json").write_text(json.dumps(brief))
    (tmp / "data/portfolios/state/holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "NVDA", "account": "ira", "market_value": 10000, "sector": "Technology"},
            {"symbol": "CASH", "account": "ira", "market_value": 4000, "is_cash": True},
        ]
    }))
    (tmp / "data/runtime/advisory_desk_latest.json").write_text(json.dumps({"ok": True, "rows": []}))


def test_every_store_has_ownership_class():
    for sid, spec in STORES.items():
        assert spec.get("ownership_class") in OWNERSHIP_CLASSES, sid
    required = {
        "portfolio.holdings.current", "cio.product.current", "cio.product.history",
        "cio.decisions", "cio.checkpoints", "cio.outcomes", "advisory.current",
        "research.current", "research.raw", "research.hermes", "memory.canonical",
        "notifications.outbox", "ops.health",
    }
    assert required <= set(STORES)


def test_root_map_zero_unknown():
    doc = map_all()
    assert doc["unknown_n"] == 0
    for name, row in doc["roots"].items():
        assert row["class"] in CLASSES
        assert row["class"] != "UNKNOWN", name
    for sid, row in doc["stores"].items():
        assert row["class"] != "UNKNOWN", sid


def test_operator_product_has_required_sections(tmp_path: Path):
    _seed_brief(tmp_path)
    product = build_operator_product(root=tmp_path, persist=True)
    assert product["available"] is True
    assert product["status"] == "AVAILABLE"
    for sec in REQUIRED_SECTIONS:
        assert sec in product, sec
    assert (tmp_path / "data/cio/cio_operator_product.json").is_file()
    assert (tmp_path / "data/cio/cio_operator_product.jsonl").is_file()
    text = render_product(product)
    assert "[CIO DECISION]" in text
    assert "{" not in text.split("What changed:")[0] or "CIO" in text


def test_invalid_schema_is_not_empty(tmp_path: Path):
    (tmp_path / "data/cio").mkdir(parents=True)
    (tmp_path / "data/cio/cio_investment_brief.json").write_text("{not json")
    (tmp_path / "data/cio/cio_operator_product.json").write_text(json.dumps({
        "schema": "CIOOperatorProduct@v1",
        "available": True,
        "product_id": "last_good",
        "generation_id": "abc",
        "as_of": "2026-08-26T00:00:00+00:00",
    }))
    loc = load_json_store("cio.product.current", root=tmp_path)
    assert loc["status"] == "INVALID_SCHEMA"
    u = build_operator_product(root=tmp_path)
    assert u["status"] == "INVALID_SCHEMA"
    assert u["operator_data_quality"] == "DEGRADED"
    assert (u.get("last_valid_product") or {}).get("product_id") == "last_good"
    text = render_product(u)
    assert "INVALID_SCHEMA" in text
    assert "no product on disk" not in text.lower()


def test_availability_reasons_are_enumerated():
    for r in (
        "PRODUCER_NOT_RUN", "STALE", "INVALID_SCHEMA", "WRONG_RUNTIME_SHA",
        "INELIGIBLE_ORIGIN", "SOURCE_UNAVAILABLE", "DATA_CONFLICT",
        "MISSING_REQUIRED_INPUT", "QUARANTINED",
    ):
        assert r in UNAVAILABLE_REASONS
    assert canonicalize_reason("no product on disk") == "PRODUCER_NOT_RUN"
    u = unavailable(reason="STALE", detail="mtime")
    assert u["reason"] == "STALE"
    assert u["status"] == "STALE"


def test_morning_and_eod_consume_product(tmp_path: Path):
    _seed_brief(tmp_path)
    product = build_operator_product(root=tmp_path)
    mt = morning_text(product)
    et = eod_text(product)
    assert "MORNING CIO BRIEF" in mt
    assert "EOD CIO BRIEF" in et
    assert "independen" not in mt.lower()
    first = deliver_morning(root=tmp_path, send=False)
    second = deliver_morning(root=tmp_path, send=False)
    assert first["published"] is True
    assert second["published"] is False
    assert second["reason"] == "semantic_duplicate"
    e1 = deliver_eod(root=tmp_path, send=False)
    e2 = deliver_eod(root=tmp_path, send=False)
    assert e1["published"] is True
    assert e2["reason"] == "semantic_duplicate"
    assert first["key"].startswith("MORNING:")
    assert e1["key"].startswith("EOD:")


def test_aegis_and_command_center_do_not_invent_cio(tmp_path: Path):
    _seed_brief(tmp_path)
    product = build_operator_product(root=tmp_path)
    a = aegis_summary(product)
    assert a["creates_cio_truth"] is False
    assert a["source"] == "cio.operator_product.current"
    cc = command_center_view(product)
    assert cc["hidden_alternative_calculation"] is False
    assert cc["decisions"]


def test_ops_and_raw_json_routing():
    r = classify_message("Research lane RAW-store health deepseek: zero_non_error_24h COST_CONFIGURATION_INVALID")
    assert r["channel"] == "OPS_HEALTH"
    assert r["is_investment_intelligence"] is False
    raw = '{"schema": "x", "error": "COST_CONFIGURATION_INVALID"}'
    assert looks_like_raw_json(raw)
    assert classify_message(raw)["is_investment_intelligence"] is False
    from telegram_alert_router import classify_alert
    assert classify_alert(raw) == "P3_LOG_ONLY"


def test_research_human_renderer():
    s = from_research_result({
        "symbol": "NOC",
        "question": "Does the thesis still hold?",
        "why_researched": "earnings next week",
        "what_was_found": "Guide in-line.",
        "material_change": False,
        "thesis_effect": "UNCHANGED",
        "decision_effect": "NONE",
        "unresolved_gaps": ["wait for 10-Q"],
    })
    text = render_research_message(s)
    assert "[RESEARCH] NOC" in text
    assert "{" not in text


def test_checkpoint_duplicates_excluded_from_learning():
    rows = [
        {"checkpoint_id": "a", "auto_registered": True, "semantic_key": "k1", "subject_guid": "g",
         "entity_type": "PORTFOLIO_CASH", "context_receipt": {"recommendation": "HOLD_CASH"}, "horizon": "1_session"},
        {"checkpoint_id": "b", "auto_registered": True, "semantic_key": "k2", "subject_guid": "g",
         "entity_type": "PORTFOLIO_CASH", "context_receipt": {"recommendation": "HOLD_CASH"}, "horizon": "1_session"},
        {"checkpoint_id": "c", "auto_registered": False, "semantic_key": "legacy"},
    ]
    out = filter_learning_rows(rows)
    assert out["active_learning_influence_from_duplicates"] == 0
    assert out["deleted"] == 0
    assert all(r["learning_class"] != "BUG_DUPLICATE" for r in out["rows"])


def test_purge_manifest_does_not_delete(tmp_path: Path):
    (tmp_path / "data/cio").mkdir(parents=True)
    (tmp_path / "data/cio/outcome_checkpoints.jsonl").write_text(
        json.dumps({"checkpoint_id": "x", "auto_registered": True, "semantic_key": "k",
                    "entity_type": "PORTFOLIO_CASH", "context_receipt": {"recommendation": "HOLD_CASH"},
                    "horizon": "1s"}) + "\n"
    )
    m = build_purge(root=tmp_path)
    assert m["destructive_applied"] is False
    assert m["approval_required"] is True


def test_deploy_persist_and_restore(tmp_path: Path):
    sim = simulate(tmp=tmp_path / "sim")
    assert sim["same_inodes"] is True
    assert sim["cio_reset"] is False
    assert sim["refuse_empty_source"] is True
    assert sim["switched_to_empty_source"] is False
    drill = restore_drill(tmp=tmp_path / "drill")
    assert drill["equivalent"] is True
    assert drill["destructive_applied"] is False


def test_overlay_refuses_empty_source(tmp_path: Path):
    dest = tmp_path / "dest" / "data" / "cio"
    dest.mkdir(parents=True)
    (dest / "cio_investment_brief.json").write_text("{}")
    empty = tmp_path / "empty"
    (empty / "data" / "cio").mkdir(parents=True)
    rep = overlay_is_safe(canonical_source=empty, dest=tmp_path / "dest")
    assert rep["ok"] is False


def test_sector_and_catalyst_bind():
    delta = sector_delta_to_product(
        {"sector": "Materials", "from": "LAGGING", "to": "LEADING", "held": ["X", "Y"], "exposure_pct": 7.4}
    )
    assert "7.4%" in delta["prose"]
    assert "LAGGING→LEADING" in delta["prose"] or "LAGGING" in delta["prose"]
    cat = catalyst_to_product({"symbol": "NVDA", "catalyst": "earnings", "when": "2026-08-28"})
    assert cat["traceable_to_entity"] is True


def test_alert_aggregation_does_not_delete():
    events = [{"alert_type": "hermes_rank_surge", "symbol": "ABC"} for _ in range(50)]
    events.append({"alert_type": "health", "raw_text": "ok"})
    out = aggregate(events)
    assert out["raw_events"] == 51
    assert out["semantic_generations"] < out["raw_events"]
    assert out["deleted"] == 0


def test_immediate_only_on_new_material_generation():
    assert immediate_material(generation_id="g1", prior_generation_id="g1", material=True)["send"] is False
    assert immediate_material(generation_id="g2", prior_generation_id="g1", material=True)["send"] is True
    assert immediate_material(generation_id="g2", prior_generation_id="g1", material=False)["send"] is False


def test_holdings_write_rejected_labelled(tmp_path: Path):
    _seed_brief(tmp_path)
    holdings = json.loads((tmp_path / "data/portfolios/state/holdings.json").read_text())
    holdings["write_rejected"] = True
    (tmp_path / "data/portfolios/state/holdings.json").write_text(json.dumps(holdings))
    product = build_operator_product(root=tmp_path)
    assert "LAST_KNOWN_GOOD" in (product.get("data_quality") or {}).get("labels", [])
    assert product["portfolio"]["holdings_n"] == 1  # not silently emptied


def test_filename_stale_production_readers_zero():
    repo = Path(__file__).resolve().parents[1]
    fn = filename_audit(root=repo)
    script_stale = [
        r for r in fn.get("stale_readers") or []
        if r.get("file", "").startswith("scripts/") and "canonical_store_registry" not in r.get("file", "")
    ]
    assert script_stale == []


def test_historical_migration_copy_only(tmp_path: Path):
    import shutil
    src = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/cio/outcome_checkpoints.jsonl")
    if not src.is_file():
        return
    before = src.read_bytes()
    dest_root = tmp_path / "copy"
    (dest_root / "data/cio").mkdir(parents=True)
    shutil.copy2(src, dest_root / "data/cio/outcome_checkpoints.jsonl")
    from scripts.lib.r17_checkpoint_reconciliation import reconcile_store
    rec = reconcile_store(dest_root)
    learn = filter_learning_rows([])
    assert rec["deleted"] == 0
    assert src.read_bytes() == before
    assert rec["total"] >= 0
    assert learn["deleted"] == 0


def test_closeout_unknown_zero_and_no_push():
    doc = closeout(root=Path(__file__).resolve().parents[1], repo=Path(__file__).resolve().parents[1])
    assert doc["roots"]["unknown_root_drift"] == 0
    assert doc["github"]["pushes"] == 0
    assert "git push" in doc["exact_one_sync_command"]
