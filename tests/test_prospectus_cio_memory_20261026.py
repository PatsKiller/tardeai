"""Ticker Prospectus → CIO memory (operator 2026-10-26: "I need to ensure that this is also in the CIO memory.
Very important.").

Every finished prospectus version lands in the CIO-owned SecurityResearchSpine through upsert_research_memory, is
idempotent by (symbol, version), supersedes older versions while keeping history, and is surfaced by Ask the CIO
(internal.prospectus facts), the CIO desk's subject dossier and the thesis overlay. Synthetic tickers only; the
identity registry is stubbed; every write goes to a temporary state root (no DB, no token store, no network).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import load_config, store  # noqa: E402
from scripts.lib.prospectus import cio_memory as cm  # noqa: E402
from scripts.lib.prospectus import pipeline as pl  # noqa: E402
from scripts.lib.cross_asset import security_research_spine as sp  # noqa: E402

GUID = "0b9f3c2e-1111-5222-8333-444455556666"
ISSUER = "0b9f3c2e-1111-5222-8333-444455550000"
OTHER = "0b9f3c2e-9999-5222-8333-444455556666"
BEHAVIOR = {"recommended_delta_usd", "size_usd", "shares", "qty", "order", "stop", "limit", "target_weight_pct",
            "trade", "execution", "quantity", "size", "position_size", "weight", "allocation", "stop_price",
            "stop_loss", "limit_price", "usd_at_risk"}


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    def _resolve(symbol, *, root=None):
        sym = str(symbol or "").upper()
        ok = sym == "ZZAA"
        return {"symbol": sym, "subject_guid": GUID if ok else None, "issuer_guid": ISSUER if ok else None,
                "security_guid": GUID if ok else None, "identity_status": "CONFIRMED" if ok else "UNRESOLVED",
                "identity_lookup": "RESOLVED" if ok else "UNRESOLVED"}
    monkeypatch.setattr("scripts.lib.identity_carriage.resolve_security_identity", _resolve)
    monkeypatch.setenv("CROSS_ASSET_SPINE", "1")
    monkeypatch.delenv("CROSS_ASSET_SHADOW", raising=False)
    monkeypatch.delenv("TRADEAI_WRITE_PATH_MODE", raising=False)
    monkeypatch.delenv("TRADEAI_CIO_DIR", raising=False)
    monkeypatch.delenv("TRADEAI_WRITE_PATH_RECEIPTS_PATH", raising=False)


def doc(version="20261026T170000Z", *, sym="ZZAA", model="claude-fable-5-1", status="ready", stance="ADD",
        conviction=61.4, stop_plan=True):
    sections = [
        {"id": "summary_verdict", "body_md": "The synthetic widget maker keeps compounding [F1]. Demand is firm [F2]."},
        {"id": "business_and_moat", "body_md": "Switching costs protect the widget franchise [F3]."},
        {"id": "risks", "body_md": "- Customer concentration in two buyers [F4]\n- Input cost inflation [F5]"},
        {"id": "thesis_breakers", "body_md": "- Gross margin below the 5-year low [F6]\n- Loss of the anchor customer\n"
                                             "- Guidance cut at the next report"},
        {"id": "analyst_view", "body_md": "Consensus is constructive [F7]."},
    ]
    blocks = {"scenarios": {"cases": [
        {"case": "bear", "price": 80.0, "probability_pct": 25, "narrative": "Margins compress [F6]."},
        {"case": "base", "price": 120.0, "probability_pct": 50, "narrative": "Steady growth."},
        {"case": "bull", "price": 160.0, "probability_pct": 25, "narrative": "New contracts land."}],
        "probability_basis": "the writer model's stated judgment"}}
    if stop_plan:
        blocks["stop_plan"] = {"recommended": {"level": 95.5, "method": "ATR", "distance_pct": -8.2, "usd_at_risk": 999.0,
                                               "policy": "fixture.policy", "as_of": "2026-10-26"},
                               "broker": {"level": 90.0, "state": "resting", "as_of": "2026-10-26", "source": "fixture"},
                               "comparison": "Broker stop 5.8% below the house level", "advisory": "advisory — no AI places, sizes or stops orders",
                               "gaps": []}
    return {"schema": "Prospectus@v1", "symbol": sym, "name": f"{sym} Widgets Inc", "scope": "holding",
            "version": version, "generated_at": f"{version[:4]}-{version[4:6]}-{version[6:8]}T17:00:00+00:00",
            "mode": "full", "status": status, "partial_gaps": ["fundamentals"] if status == "partial" else [],
            "model": model, "verdict_line": f"{stance} — durable franchise, watch margins [F1].",
            "sections": sections, "blocks": blocks,
            "facts": [{"id": "F9", "label": "CIO conviction", "value": conviction, "source": "CIO prospect (data_broker.cio_prospect)",
                       "as_of": "2026-10-26T16:00:00+00:00"}],
            "gaps": ["13F holder changes: not in the house"],
            "source_coverage": {"counts": {"used": 20, "stale": 1, "empty": 3, "failed": 0, "not_applicable": 30},
                                "key_gaps": [], "web_searches": [{"query": "q", "ok": True, "results": 3}]},
            "inputs_digest": {"cio_stance": stance}}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_memory_record_carries_every_required_field_and_no_behavior_key():
    rec = cm.memory_record(doc())
    assert rec["schema"] == "ProspectusMemory@v1" and rec["symbol"] == "ZZAA" and rec["version"] == "20261026T170000Z"
    assert rec["model_label"] == "Fable" and rec["verdict"] == "ADD" and rec["cio_conviction"] == 61.4
    assert rec["written_at"].startswith("2026-10-26") and rec["link"] == "/v3/prospectus/ZZAA"
    assert rec["summary"].startswith("The synthetic widget maker") and "[F1]" not in rec["summary"]
    assert [c["case"] for c in rec["scenarios"]] == ["bear", "base", "bull"] and rec["scenarios"][0]["price"] == 80.0
    assert rec["scenarios"][1]["probability_pct"] == 50
    assert rec["thesis_breakers"][0] == "Gross margin below the 5-year low" and len(rec["thesis_breakers"]) == 3
    assert rec["key_risks"] == ["Customer concentration in two buyers", "Input cost inflation"]
    assert "13F holder changes: not in the house" in rec["data_gaps"]
    assert rec["source_coverage"]["used"] == 20 and rec["source_coverage"]["web_results"] == 3
    assert rec["house_stop_plan"]["recommended_level"] == 95.5 and rec["house_stop_plan"]["broker_state"] == "resting"
    assert "business_and_moat" in rec["section_excerpts"]
    assert not (set(_keys(rec)) & BEHAVIOR), "no BEHAVIOR_FIELDS key and no dollars at risk in memory"
    assert cm.memory_record(doc(model="claude-opus-5-5"))["model_label"] == "Opus"


def test_record_version_writes_the_spine_once_and_newer_versions_supersede(tmp_path):
    first = cm.record_version(doc("20261020T170000Z", conviction=50.0), root=tmp_path)
    assert first["outcome"] == "written", first
    assert cm.record_version(doc("20261020T170000Z", conviction=50.0), root=tmp_path)["outcome"] == "exists"
    assert cm.record_version(doc("20261026T170000Z"), root=tmp_path)["outcome"] == "written"
    tip = sp.load_latest("ZZAA", root=tmp_path)
    assert tip["owner"] == "cio" and tip["subject_guid"] == GUID
    assert tip["latest_prospectus"]["version"] == "20261026T170000Z"
    assert tip["latest_prospectus"]["supersedes_version"] == "20261020T170000Z"
    assert [h["version"] for h in tip["prospectus_history"]] == ["20261026T170000Z", "20261020T170000Z"]
    assert tip["thesis"]["state"] == "INSUFFICIENT_DATA", "prospectus prose never replaces the house thesis tip"
    contrib = [c for c in tip["contributions"] if c["kind"] == "prospectus_version"]
    assert len(contrib) == 2 and contrib[-1]["artifact_id"] == "prospectus:ZZAA:20261026T170000Z"
    assert "Prospectus ZZAA (Fable, 2026-10-26" in contrib[-1]["summary"] and "/v3/prospectus/ZZAA" in contrib[-1]["summary"]
    assert "prospectus" in tip["tags"]
    # an older version arriving later (backfill order) keeps history but never replaces the newer tip
    assert cm.record_version(doc("20261001T170000Z"), root=tmp_path)["outcome"] == "written"
    tip = sp.load_latest("ZZAA", root=tmp_path)
    assert tip["latest_prospectus"]["version"] == "20261026T170000Z"
    assert len(tip["prospectus_history"]) == 3
    view = sp.view_for_silo("ZZAA", "watchlist", root=tmp_path)
    assert view["latest_prospectus"]["verdict"] == "ADD" and len(view["prospectus_history"]) == 3


def test_write_path_receipt_is_recorded_in_shadow_under_the_temp_root(tmp_path):
    out = cm.record_version(doc(), root=tmp_path)
    assert out["receipt"]["mode"] == "SHADOW" and out["receipt"]["accepted"] is False
    rows = [json.loads(x) for x in (tmp_path / "data/cio/research_write_path_receipts.jsonl").read_text().splitlines()]
    assert rows[-1]["lane_id"] == "prospectus-writer" and rows[-1]["outcome"] == "SHADOW_RECORDED"
    assert rows[-1]["research_id"] == "prospectus:ZZAA:20261026T170000Z" and rows[-1]["memory_behavior_influence"] == 0


def test_partial_is_written_unfinished_skipped_unresolved_refused_and_spine_off_skipped(tmp_path, monkeypatch):
    assert cm.record_version(doc(status="partial"), root=tmp_path)["outcome"] == "written"
    assert sp.load_latest("ZZAA", root=tmp_path)["latest_prospectus"]["status"] == "partial"
    assert cm.record_version(doc("20261027T170000Z", status="failed"), root=tmp_path)["outcome"] == "skipped"
    refused = cm.record_version(doc(sym="ZZBB"), root=tmp_path)
    assert refused["outcome"] == "refused" and "registry" in refused["reason"]
    monkeypatch.setenv("CROSS_ASSET_SPINE", "0")
    assert cm.record_version(doc("20261028T170000Z"), root=tmp_path)["outcome"] == "skipped"


def _store_versions(tmp_path):
    base = store.base_dir(tmp_path, load_config())
    for v in ("20261020T170000Z", "20261026T170000Z"):
        store.write_version(base, "ZZAA", v, doc(v), {"prospectus.html": b"<html></html>"})
    store.write_version(base, "ZZBB", "20261026T170000Z", doc(sym="ZZBB"), {})
    return base


def test_backfill_is_dry_run_by_default_then_idempotent(tmp_path):
    base = _store_versions(tmp_path)
    dry = cm.backfill(base, root=tmp_path)
    assert dry["mode"] == "dry_run" and dry["counts"] == {"would_write": 2, "refused": 1}
    assert not (tmp_path / "data/cio/security_research_spine.jsonl").exists(), "dry run writes nothing"
    applied = cm.backfill(base, root=tmp_path, apply=True)
    assert applied["counts"] == {"written": 2, "refused": 1} and applied["symbols"] == 2
    assert sp.load_latest("ZZAA", root=tmp_path)["latest_prospectus"]["version"] == "20261026T170000Z"
    again = cm.backfill(base, root=tmp_path, apply=True)
    assert again["counts"] == {"exists": 2, "refused": 1}
    latest = cm.backfill(base, root=tmp_path, latest_only=True, symbols=["ZZAA"])
    assert latest["versions"] == 1


def test_backfill_cli_dry_run_uses_project_root(tmp_path, monkeypatch, capsys):
    _store_versions(tmp_path)
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import scripts.prospectus_cio_memory as cli
    assert cli.main(["--symbols", "ZZAA"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["counts"] == {"would_write": 2} and out["state_root"] == str(tmp_path)
    assert not (tmp_path / "data/cio/security_research_spine.jsonl").exists()


def test_run_queue_hands_every_stored_version_to_cio_memory(tmp_path):
    from tests.test_prospectus_build_20261026 import NOW, FakeSources, stub_generate
    base = store.base_dir(tmp_path, load_config())
    assert pl.state_root_for(base, load_config()) == tmp_path
    src, cfg = FakeSources(), load_config()
    uni = pl.plan_universe(src, cfg)
    store.write_universe(base, uni)
    store.enqueue(base, pl.first_build_rows(uni), now=NOW)
    seen = []

    def memory_fn(d, *, root):
        seen.append((d["symbol"], d["version"], root))
        return {"symbol": d["symbol"], "version": d["version"], "outcome": "written"}

    out = pl.run_queue(base, src, cfg, limit=5, generate_fn=stub_generate(src), now_fn=lambda: NOW,
                       log=lambda _m: None, memory_fn=memory_fn)
    assert [s for s, _v, _r in seen] == out["done"] and all(r == tmp_path for *_x, r in seen)
    assert [m["outcome"] for m in out["cio_memory"]] == ["written"] * len(out["done"])
    assert all(store.read_prospectus(base, s, v) for s, v, _r in seen), "memory runs after the version is stored"


def test_run_queue_memory_failure_never_fails_the_prospectus(tmp_path):
    from tests.test_prospectus_build_20261026 import NOW, FakeSources, stub_generate
    base = store.base_dir(tmp_path, load_config())
    src, cfg = FakeSources(), load_config()
    uni = pl.plan_universe(src, cfg)
    store.write_universe(base, uni)
    store.enqueue(base, pl.first_build_rows(uni)[:1], now=NOW)

    def boom(_d, *, root):
        raise RuntimeError("spine unavailable")

    out = pl.run_queue(base, src, cfg, limit=1, generate_fn=stub_generate(src), now_fn=lambda: NOW,
                       log=lambda _m: None, memory_fn=boom)
    assert len(out["done"]) == 1 and out["cio_memory"][0]["outcome"] == "error"
    assert "spine unavailable" in out["cio_memory"][0]["reason"]


def test_ask_the_cio_gets_cited_prospectus_facts(tmp_path):
    from scripts.lib import cio_ask_research as ask
    assert any(s.name == "internal.prospectus" for s in ask.default_sources())
    cm.record_version(doc(), root=tmp_path)
    ent = ask.Entity(label="ZZAA", kind="listed", symbol="ZZAA", security_guid=GUID, identity_status="CONFIRMED")
    ctx = ask.ResearchContext(question="what does the prospectus say about margins?", state_root=tmp_path)
    facts = ask._src_prospectus(ent, ctx)
    claims = [f.claim for f in facts]
    assert claims[0].startswith("Latest prospectus (Fable, Oct 26): ADD — durable franchise")
    assert "CIO conviction 61/100 at writing" in claims[0] and "/v3/prospectus/ZZAA" in claims[0]
    assert all(f.citation["store"] == "security_research_spine" and f.citation["version"] == "20261026T170000Z"
               for f in facts)
    assert any(c.startswith("Prospectus thesis breaker: Gross margin") for c in claims)
    assert any("business and moat" in c for c in claims), "section excerpts answer 'what does it say about X'"
    assert {f.kind for f in facts if "thesis breaker" in f.claim} == {"risk"}
    bear = [f for f in facts if f.field == "scenario_bear_price"][0]
    assert bear.value == 80.0 and bear.unit == "usd"
    stop = [f for f in facts if "stop plan" in f.claim][0]
    assert stop.egress == "local_only" and "95.50" in stop.claim and "resting" in stop.claim
    # a different security under the same ticker is never recalled
    other = ask.Entity(label="ZZAA", kind="listed", symbol="ZZAA", security_guid=OTHER, identity_status="CONFIRMED")
    assert ask._src_prospectus(other, ctx) == []
    ans = ask.synthesize({"question": ctx.question}, [ent], facts, [], [], mbi_log=[])
    assert any("thesis breaker" in r["text"] for r in ans["prospectus"][0]["risks"])


def test_cio_desk_subject_dossier_shows_the_latest_prospectus(tmp_path):
    from scripts.lib import subject_dossier as sd
    cm.record_version(doc(), root=tmp_path)
    dossier = sd.gather(["ZZAA", "ZZCC"], db_query=lambda *a, **k: [], runtime_dir=tmp_path,
                        prospectus_fn=lambda s: cm.latest_for(s, root=tmp_path))
    text, missing = sd.format_symbol(dossier["ZZAA"])
    assert "Latest prospectus (Fable, Oct 26): ADD" in text and "thesis breakers: Gross margin" in text
    assert "/v3/prospectus/ZZAA" in text and "security_research_spine" in text and "bear $80" in text
    assert "prospectus" not in missing
    _t, missing_c = sd.format_symbol(dossier["ZZCC"])
    assert "prospectus" in missing_c
    desk = (ROOT / "scripts/lib/cio_operator_desk_loop.py").read_text()
    assert "prospectus_fn=_latest_prospectus" in desk


def test_thesis_overlay_carries_the_prospectus_reference(tmp_path):
    from scripts.lib.cross_asset.hooks import overlay_thesis_fields_from_spine
    cm.record_version(doc(), root=tmp_path)
    out = overlay_thesis_fields_from_spine({"symbol": "ZZAA"}, "ZZAA", root=tmp_path, silo="watchlist")
    lp = out["latest_prospectus"]
    assert lp["verdict"] == "ADD" and lp["model_label"] == "Fable" and lp["link"] == "/v3/prospectus/ZZAA"
    assert lp["thesis_breakers"][0].startswith("Gross margin") and "thesis_summary" not in out


def test_build_apply_reaches_cio_memory_through_run_queue_default():
    """prospectus_build --apply calls run_queue(base, ...) with base = <state root>/data/prospectus; the default
    memory root is derived from it, so the build lane writes the same spine as the backfill."""
    text = (ROOT / "scripts/prospectus_build.py").read_text()
    assert "run_queue(base, sources, cfg" in text and "store.base_dir(root, cfg)" in text
    src = (ROOT / "scripts/lib/prospectus/pipeline.py").read_text()
    assert "memory_root = state_root_for(base, cfg)" in src and "cio_memory.record_version" in src
