"""Real rotation producer/consumer boundaries; every external effect is a fake."""
import ast
import copy
import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def document():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "as_of": now,
        "holdings": [
            {"symbol": "SCHG", "account": "fixture_taxable", "shares": 0.25,
             "market_value": 10, "price": 40, "broker_position_as_of_at": now},
            {"symbol": "SCHG", "account": "fixture_rollover_ira", "shares": 200,
             "market_value": 8000, "price": 40, "broker_position_as_of_at": now},
        ],
        "account_summaries": {
            a: {"state": "LIVE", "account_state": {
                "contract_version": "AccountState@v1", "state": "LIVE",
                "state_as_of": now, "last_sync_at": now, "classified_at": now,
                "sync_window_hours": 24,
            }} for a in ["fixture_taxable", "fixture_rollover_ira"]
        },
    }


@pytest.fixture
def producer(tmp_path, monkeypatch):
    source = ast.parse((ROOT / "scripts/api_v2.py").read_text())
    fn = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "_rotation_summary")
    env = {"PROJECT_ROOT": tmp_path, "_ROTATION_SUMMARY_CACHE": {"data": None, "ts": 0},
           "_db_query": lambda *a, **kw: []}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "api_v2.py", "exec"), env)
    ctx = {"status": "warning", "holdings": document(), "target_conflict": False, "engine_runs": 0}
    for name in ["data/runtime", "data/portfolios/state", "config"]:
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/runtime/symbol_cards_latest.json").write_text('{}')
    (tmp_path / "data/portfolios/state/lookthrough_themes.json").write_text('{}')
    (tmp_path / "config/rotation_sector_targets.json").write_text('{}')
    (tmp_path / "config/etf_fund_universe.json").write_text('{"instruments":[]}')

    class Cursor:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchall(self):
            sql = self.sql
            if "SELECT symbol, thesis_status, escalation_reason" in sql:
                return [("SCHG", ctx["status"], "fixture finding", None, None, True)]
            if "SELECT symbol, thesis_status FROM" in sql:
                return [("SCHG", ctx["status"])]
            if "fs.recommendation IN" in sql:
                # Multiple discovery sources for DNP. Do not reach the third target to fill a dedup gap.
                return [("DNP", 5, "Income", None, "ADD_ON_PULLBACK"),
                        ("DNP", 5, "Income", None, "BUY" if ctx["target_conflict"] else "ADD_ON_PULLBACK"),
                        ("EXTRA", 6, "Income", 4, "BUY")]
            if "FROM watchlist_items w" in sql:
                return [("DNP", 5, 60, "Income", "stock", "ADD_ON_PULLBACK", None)]
            return []

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: types.SimpleNamespace(cursor=Cursor)))
    monkeypatch.setitem(sys.modules, "fee_efficiency_analyzer", types.SimpleNamespace(analyze=lambda: {}))
    monkeypatch.setitem(sys.modules, "lib.data_broker.rotation_ladders", types.SimpleNamespace(get_rotation_ladders=lambda **kw: {}))

    def fake_engine(*args, **kwargs):
        ctx["engine_runs"] += 1
        if ctx.get("change_inputs"):
            changed = copy.deepcopy(ctx["holdings"])
            changed["holdings"][1]["shares"] += 1
            (tmp_path / "data/portfolios/state/holdings.json").write_text(json.dumps(changed))
        candidates = [{"symbol": "SCHG", "account_key": "fixture_rollover_ira", "account_type": "rollover_ira",
                       "current_value": 8000, "sector": "Tech", "trim_score": 40, "evidence": {}}]
        return types.SimpleNamespace(stdout=json.dumps({"ok": True, "top_candidates": candidates,
                                                        "generated_at": datetime.now(timezone.utc).isoformat()}))

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_engine)

    def run(*, cached=None):
        env["_ROTATION_SUMMARY_CACHE"] = {"data": None, "ts": 0}
        (tmp_path / "data/portfolios/state/holdings.json").write_text(json.dumps(ctx["holdings"]))
        if cached is not None:
            (tmp_path / "data/runtime/rotation_summary_cache.json").write_text(json.dumps(cached))
        return env["_rotation_summary"](force=cached is None)
    return run, ctx


def test_selected_target_duplicates_do_not_duplicate_or_expand_proposals(producer):
    run, _ = producer
    result = run()
    assert [(x["from_symbol"], x["to_symbol"]) for x in result["research_rotation_ideas"]] == [("SCHG", "DNP")]


def test_api_preserves_exact_source_account_identity(producer):
    run, _ = producer
    ideas = run()["research_rotation_ideas"]
    assert ideas[0].get("from_account_key") == "fixture_rollover_ira"


def test_shares_are_bound_to_source_account_not_first_symbol_row(producer):
    run, _ = producer
    assert run()["research_rotation_ideas"][0]["from_shares_held"] == 200


def test_llm_severity_cannot_publish_a_stop_hit_reduction_range(producer):
    run, ctx = producer
    ctx["status"] = "broken"
    result = run()
    assert result["research_rotation_ideas"] == [], "LLM broken must not publish deterministic stop-hit ranges"
    assert result["publication"]["status"] == "UNAVAILABLE"
    assert "unsupported_stop_claim" in result["publication"]["reasons"]


def test_fresh_cache_does_not_override_explicit_source_stale(producer):
    run, ctx = producer
    ctx["holdings"]["account_summaries"]["fixture_rollover_ira"]["state"] = "STALE"
    result = run()
    assert result.get("publication", {}).get("status") == "STALE"
    assert result["research_rotation_ideas"] == []


def digest(monkeypatch, summary):
    spec = importlib.util.spec_from_file_location("rotation_digest_test", ROOT / "scripts/rotation_rebalance_digest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sent, posts = [], []
    monkeypatch.setattr(mod, "_get", lambda p: {"ok": True, "data": summary})
    monkeypatch.setattr(mod, "_post", lambda p: posts.append(p) or {"created": []})
    monkeypatch.setitem(sys.modules, "telegram_alert", types.SimpleNamespace(send_telegram=lambda m, **kw: sent.append(m)))
    mod.main()
    return sent[0], posts


def test_digest_shows_source_account(monkeypatch, producer):
    run, _ = producer
    text, _ = digest(monkeypatch, run())
    assert "fixture_rollover_ira" in text


def test_digest_unavailable_never_seeds_research_or_publishes_ranges(monkeypatch):
    summary = {"publication": {"schema": "RotationPublication@v1", "status": "UNAVAILABLE", "reasons": ["missing_input"]},
               "research_rotation_ideas": [{"from_symbol": "SCHG", "to_symbol": "DNP", "review_amount_range": {"low": 100, "high": 200}}]}
    text, posts = digest(monkeypatch, summary)
    assert not posts, "An unavailable source must not seed research"
    assert "UNAVAILABLE" in text and "SCHG → DNP" not in text


def test_conflicting_duplicate_source_identity_is_unavailable(producer):
    run, ctx = producer
    ctx["holdings"]["holdings"].append({**ctx["holdings"]["holdings"][1], "shares": 999})
    result = run()
    assert result.get("publication", {}).get("status") == "UNAVAILABLE"
    assert result["research_rotation_ideas"] == []


def test_conflicting_selected_target_identity_is_unavailable(producer):
    run, ctx = producer
    ctx["target_conflict"] = True
    result = run()
    assert result["publication"]["status"] == "UNAVAILABLE"
    assert "conflicting_identity" in result["publication"]["reasons"]
    assert result["research_rotation_ideas"] == []


def test_ready_cache_roundtrip_and_changed_source_hold(producer):
    run, ctx = producer
    fresh = run()
    assert fresh["publication"]["status"] == "READY"
    assert run(cached=fresh)["publication"]["status"] == "READY"
    ctx["holdings"]["holdings"][1]["shares"] = 201
    changed = run(cached=fresh)
    assert changed["publication"]["status"] == "UNAVAILABLE"
    assert "unbound_cache_inputs" in changed["publication"]["reasons"]
    assert not changed["research_rotation_ideas"]


def test_old_cache_remains_readable_but_cannot_publish_current_advice(producer):
    run, _ = producer
    old = run()
    old.pop("publication")
    for row in old["research_rotation_ideas"]:
        row.pop("from_account_key")
    result = run(cached=old)
    assert result["publication"]["status"] == "UNAVAILABLE"
    assert result["ok"] is False and result["research_rotation_ideas"] == []


def test_old_digest_reader_gets_no_advisory_ranges_when_publication_held(producer):
    run, ctx = producer
    ctx["status"] = "broken"
    result = run()
    # The legacy reader sees the same existing keys, with no unsafe ranges.
    assert result["ok"] is False
    assert all(result[k] == [] for k in ["research_rotation_ideas", "top_rotation_ideas", "degraded_holdings"])


@pytest.mark.parametrize("schema", [None, "RotationPublication@v0", "RotationPublication@v2"])
def test_digest_unsupported_producer_version_is_unavailable(monkeypatch, schema):
    text, posts = digest(monkeypatch, {"ok": True, "publication": {"schema": schema, "status": "READY"},
                                      "research_rotation_ideas": [{"from_symbol": "X", "to_symbol": "Y"}]})
    assert "UNAVAILABLE" in text and not posts


def test_conditional_endorsement_and_thin_coverage_are_visible_without_reselection(monkeypatch, producer):
    run, _ = producer
    result = run()
    text, _ = digest(monkeypatch, result)
    assert "CIO ADD_ON_PULLBACK" in text and "thin analyst coverage" in text
    assert "EXTRA" not in text


@pytest.mark.parametrize("clock", [float("nan"), float("inf"), True, None])
def test_cache_invalid_or_missing_clock_cannot_publish(producer, clock):
    run, _ = producer
    cached = run()
    cached["_cached_ts"] = clock
    result = run(cached=cached)
    assert result["publication"]["status"] == "UNAVAILABLE"


def test_cache_age_does_not_silently_return_to_healthy(producer):
    run, _ = producer
    cached = run()
    cached["_cached_ts"] -= 901
    held = run(cached=cached)
    assert held["publication"]["status"] == "STALE"
    assert held["research_rotation_ideas"] == []
    assert run(cached=held)["publication"]["status"] == "STALE"


def test_friday_postclose_live_evidence_uses_existing_market_calendar():
    from lib.rotation_publication import project_summary
    now = datetime(2026, 10, 18, 22, tzinfo=timezone.utc)  # Sunday
    h = document()
    for state in h["account_summaries"].values():
        state["account_state"]["last_sync_at"] = "2026-10-16T22:00:00+00:00"
    s = {"ok": True, "research_rotation_ideas": []}
    assert project_summary(s, h, now=now)["publication"]["status"] == "READY"
    h["account_summaries"]["fixture_taxable"]["state"] = "STALE"
    assert project_summary(s, h, now=now)["publication"]["status"] == "STALE"


def test_missed_friday_session_is_stale_even_on_weekend():
    from lib.rotation_publication import project_summary
    now = datetime(2026, 10, 18, 22, tzinfo=timezone.utc)
    h = document()
    for state in h["account_summaries"].values():
        state["account_state"]["last_sync_at"] = "2026-10-15T22:00:00+00:00"
    result = project_summary({"ok": True}, h, now=now)
    assert result["publication"]["status"] == "STALE"


def test_conflicting_duplicate_proposals_are_unavailable(producer):
    from lib.rotation_publication import project_summary
    run, ctx = producer
    result = run()
    result["research_rotation_ideas"].append(copy.deepcopy(result["research_rotation_ideas"][0]))
    result["research_rotation_ideas"][-1]["review_amount_range"]["low"] += 1
    result = project_summary(result, ctx["holdings"])
    assert result["publication"]["status"] == "UNAVAILABLE"
    assert result["research_rotation_ideas"] == []


def test_missing_or_expired_publication_evidence_cannot_seed(monkeypatch, producer):
    run, _ = producer
    s = run()
    s["publication"]["checked_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    text, posts = digest(monkeypatch, s)
    assert "UNAVAILABLE" in text and not posts


def test_missing_cache_get_never_bootstraps_producer(producer):
    run, ctx = producer
    result = run(cached={})
    assert result["publication"]["status"] == "UNAVAILABLE"
    assert ctx["engine_runs"] == 0


def test_midproduction_holdings_change_cannot_be_attached_to_old_output(producer):
    run, ctx = producer
    ctx["change_inputs"] = True
    result = run()
    assert result["publication"]["status"] == "UNAVAILABLE"
    assert "input_changed_during_production" in result["publication"]["reasons"]


@pytest.mark.parametrize("data", [[], {"publication": ["invalid"]}, {"publication": "invalid"}])
def test_malformed_publication_is_visible_unavailable(monkeypatch, data):
    text, posts = digest(monkeypatch, data)
    assert "UNAVAILABLE" in text and not posts
