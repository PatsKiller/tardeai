#!/usr/bin/env python3
"""Hermes Discovery Inbox Stage 2 integration tests: promotion pathways,
api_v2 route handlers, scorecard metrics, do-no-harm governor.

TRADE_AI_CI-safe: DB-bound tests skip when TRADE_AI_CI is set or PostgreSQL is
unreachable; pure-function / source-grep tests always run. Broker/registry side
effects are monkeypatched — no watch_directives / watchpool rows are created.

    .venv/bin/python -m pytest tests/test_hermes_discovery_integration.py -q
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery import inbox, promotion  # noqa: E402


def _db_available() -> bool:
    if os.getenv("TRADE_AI_CI"):
        return False
    try:
        from db_adapter import USE_DB, _execute
        if not USE_DB:
            return False
        return bool(_execute("SELECT 1 AS ok", fetch="one"))
    except Exception:
        return False


DB_OK = _db_available()
needs_db = pytest.mark.skipif(not DB_OK, reason="DB unavailable or TRADE_AI_CI set")

TAG = f"hdi2test{uuid.uuid4().hex[:8]}"
_created_ids: list[int] = []


def _track(row: dict) -> dict:
    _created_ids.append(row["id"])
    return row


@pytest.fixture(scope="module", autouse=True)
def _cleanup_test_rows():
    yield
    if not DB_OK:
        return
    from db_adapter import _execute
    if _created_ids:
        ids = tuple(set(_created_ids))
        _execute("DELETE FROM hermes_discovery_feedback WHERE candidate_id IN %s", (ids,))
        _execute("DELETE FROM hermes_discovery_audit WHERE candidate_id IN %s", (ids,))
        _execute("DELETE FROM hermes_discovery_clusters WHERE cluster_key LIKE %s", (f"%{TAG}%",))
        _execute("DELETE FROM hermes_discovery_candidates WHERE id IN %s", (ids,))
    # registry rows created by promotion tests are TAG-scoped — exact cleanup
    _execute("DELETE FROM research_sources WHERE source_name LIKE %s", (f"%{TAG}%",))
    _execute("DELETE FROM topic_monitor WHERE display_name LIKE %s", (f"%{TAG}%",))


# ── forbidden-path guards (always run) ───────────────────────────────────────

def test_forbidden_imports_promotion_and_ingestors():
    files = [
        ROOT / "scripts" / "lib" / "hermes_discovery" / "promotion.py",
        ROOT / "scripts" / "hermes_discovery_ingestors.py",
    ]
    import_re = re.compile(
        r"^\s*(?:import|from)\s+(?:scripts\.)?(?:lib\.)?"
        r"(brokers\b|schwab\w*|alpaca\w*)", re.MULTILINE)
    write_sql_re = re.compile(
        r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:watchlist_"
        r"items|strategy_watchpool)\b", re.IGNORECASE)
    offenders = []
    for path in files:
        src = path.read_text(encoding="utf-8")
        for rx, kind in ((import_re, "broker import"), (write_sql_re, "watch-table write")):
            m = rx.search(src)
            if m:
                offenders.append(f"{path.name}: {kind}: {m.group(0).strip()}")
    assert not offenders, f"forbidden paths found: {offenders}"


def test_promotion_module_level_guard_ran():
    # the guard executes at import time; importing the module without an
    # AssertionError proves it passed against the current source
    assert callable(promotion._forbidden_path_guard)
    promotion._forbidden_path_guard()  # re-run explicitly


# ── do-no-harm governor (pure, always runs) ──────────────────────────────────

def _win(vol=5, dup=0.0, tick=0, false=0.0):
    return {"candidate_volume": vol, "duplicate_rate": dup,
            "ticker_volume": tick, "false_ticker_rate": false}


def test_do_no_harm_steady_when_healthy():
    from hermes_discovery_scorecard import compute_do_no_harm
    out = compute_do_no_harm(_win(vol=12, dup=0.05, tick=6, false=0.1),
                             _win(vol=10, dup=0.05, tick=5, false=0.1))
    assert out["recommendation"] == "steady"
    assert out["degraded"] == []


def test_do_no_harm_tighten_on_single_degradation():
    from hermes_discovery_scorecard import compute_do_no_harm
    out = compute_do_no_harm(_win(vol=20, dup=0.40, tick=2, false=0.0),
                             _win(vol=18, dup=0.10, tick=2, false=0.0))
    assert out["degraded"] == ["duplicate_rate"]
    assert out["recommendation"] == "tighten"


def test_do_no_harm_pause_on_multiple_degradations():
    from hermes_discovery_scorecard import compute_do_no_harm
    out = compute_do_no_harm(_win(vol=100, dup=0.5, tick=10, false=0.6),
                             _win(vol=10, dup=0.1, tick=8, false=0.1))
    assert set(out["degraded"]) == {"duplicate_rate", "false_ticker_rate",
                                    "candidate_volume"}
    assert out["recommendation"] == "pause"


def test_do_no_harm_small_samples_never_flap():
    from hermes_discovery_scorecard import compute_do_no_harm
    # below the volume floors, even terrible rates stay advisory-steady
    out = compute_do_no_harm(_win(vol=3, dup=1.0, tick=2, false=1.0),
                             _win(vol=0, dup=0.0, tick=0, false=0.0))
    assert out["recommendation"] == "steady"


# ── promotion status-gating + pathways (DB) ──────────────────────────────────

@needs_db
def test_promote_source_status_gated_then_succeeds():
    from db_adapter import _execute
    row = _track(inbox.upsert_candidate(
        "SOURCE_CANDIDATE", f"{TAG}-macro.example.com",
        source_domain=f"{TAG}-macro.example.com",
        meta={"credibility": 42, "specialty": ["web search"]}))
    assert row["status"] == "DISCOVERED"
    # gate: DISCOVERED cannot promote
    with pytest.raises(inbox.IllegalTransitionError):
        promotion.promote_source(row["id"], actor="pytest")
    assert inbox.get_candidate(row["id"])["status"] == "DISCOVERED"
    # no registry orphan was written by the refused promotion
    assert _execute("SELECT id FROM research_sources WHERE source_name = %s",
                    (f"{TAG}-macro.example.com",), fetch="one") is None

    inbox.transition_candidate(row["id"], "READY_FOR_REVIEW", actor="pytest")
    res = promotion.promote_source(row["id"], actor="pytest", notes="test approve")
    assert res["ok"] and res["advisory_only"]
    assert res["status"] == "APPROVED_SOURCE"
    assert res["promoted_ref_type"] == "research_source"

    src = _execute("SELECT * FROM research_sources WHERE id = %s::bigint",
                   (res["promoted_ref_id"],), fetch="one")
    assert src and src["active"] is False  # curation lifecycle owns activation
    assert "DISCOVERY_INBOX" in (src["notes"] or "")

    cand = inbox.get_candidate(row["id"])
    assert cand["meta_json"]["promoted_ref_type"] == "research_source"
    assert str(cand["meta_json"]["promoted_ref_id"]) == str(src["id"])
    audit = _execute("""SELECT action FROM hermes_discovery_audit
                        WHERE candidate_id = %s ORDER BY id""", (row["id"],), fetch="all")
    assert [a["action"] for a in audit][-1] == "PROMOTE"


@needs_db
def test_promote_research_topic_registers_topic_monitor():
    from db_adapter import _execute
    row = _track(inbox.upsert_candidate(
        "TOPIC_CANDIDATE", f"grid interconnection reform {TAG}",
        meta={"keywords": ["grid interconnection", "queue reform"]}))
    inbox.transition_candidate(row["id"], "READY_FOR_REVIEW", actor="pytest")
    res = promotion.promote_research_topic(row["id"], actor="pytest")
    assert res["status"] == "APPROVED_RESEARCH_ONLY"
    assert res["promoted_ref_type"] == "research_topic"
    topic = _execute("SELECT * FROM topic_monitor WHERE topic_id = %s",
                     (res["promoted_ref_id"],), fetch="one")
    assert topic and topic["owner"] == "shared" and topic["enabled"]
    # idempotent second call is illegal by state machine (already approved)
    with pytest.raises(inbox.IllegalTransitionError):
        promotion.promote_research_topic(row["id"], actor="pytest")


@needs_db
def test_promote_watch_directive_uses_app_path(monkeypatch):
    import api_v2
    calls = []

    def fake_create(body):
        calls.append(body)
        return 200, {"ok": True, "directive_id": 987654321, "kind": body["kind"],
                     "label": body["label"], "reused": False}

    monkeypatch.setattr(api_v2, "_watch_directive_create", fake_create)
    row = _track(inbox.upsert_candidate(
        "TREND_CANDIDATE", f"defense drone swarm buildout {TAG}",
        seed_symbols=["AVAV"], meta={"keywords": ["drone swarm", "defense"]}))
    inbox.transition_candidate(row["id"], "READY_FOR_REVIEW", actor="pytest")
    res = promotion.promote_watch_directive(row["id"], actor="pytest")
    assert calls and calls[0]["kind"] == "trend"
    assert calls[0]["created_by"] == "hermes_discovery"
    assert calls[0]["spec"]["keywords"] == ["drone swarm", "defense"]
    assert res["status"] == "APPROVED_WATCH_DIRECTIVE"
    assert res["promoted_ref_type"] == "watch_directive"
    assert res["promoted_ref_id"] == "987654321"
    cand = inbox.get_candidate(row["id"])
    assert cand["meta_json"]["promoted_ref_type"] == "watch_directive"


@needs_db
def test_promote_ticker_calls_directive_promotion(monkeypatch):
    import directive_promotion
    calls = []

    def fake_lead(symbol, directive_id, reason, source_system, conn=None, *,
                  auto=None, actor="system"):
        calls.append({"symbol": symbol, "directive_id": directive_id,
                      "source_system": source_system, "auto": auto, "actor": actor})
        return {"status": "STAGED_FOR_REVIEW", "tier": "candidate",
                "divergence": "unavailable", "registered": False, "evaluated": False}

    monkeypatch.setattr(directive_promotion, "promote_directive_lead", fake_lead)
    row = _track(inbox.upsert_candidate(
        "TICKER_CANDIDATE", "GOOGL", normalized_key=f"googl {TAG}"))
    assert row["status"] == "READY_FOR_REVIEW"  # validated against symbol_profiles
    inbox.decide_candidate(row["id"], "STAGED_TICKER_REVIEW", actor="pytest")
    res = promotion.promote_ticker(row["id"], directive_id=424242, actor="pytest")
    assert calls and calls[0]["symbol"] == "GOOGL"
    assert calls[0]["source_system"] == "hermes_discovery"
    assert calls[0]["directive_id"] == 424242
    assert calls[0]["auto"] is None  # governor NOT bypassed
    assert res["status"] == "PROMOTED_TO_WATCH_EVALUATION"
    assert res["evaluation"]["status"] == "STAGED_FOR_REVIEW"


@needs_db
def test_promote_ticker_fail_closed_on_unvalidated_symbol():
    row = _track(inbox.upsert_candidate(
        "TICKER_CANDIDATE", "CEO", normalized_key=f"ceo {TAG}"))
    assert row["status"] == "NEEDS_VALIDATION"
    with pytest.raises(inbox.DiscoveryInboxError):
        # illegal transition AND invalid ticker — must never reach the engine
        promotion.promote_ticker(row["id"], directive_id=1, actor="pytest")


# ── api_v2 POST/GET route handlers (DB) ──────────────────────────────────────

@needs_db
def test_routes_list_detail_and_decision_audit():
    import api_v2
    from db_adapter import _execute
    row = _track(inbox.upsert_candidate(
        "TOPIC_CANDIDATE", f"sodium ion battery supply chain {TAG}"))
    inbox.transition_candidate(row["id"], "READY_FOR_REVIEW", actor="pytest")

    st, body = api_v2.handle("/api/v2/hermes/discovery-inbox", method="GET",
                             query={"type": ["TOPIC_CANDIDATE"], "limit": ["500"]})
    assert st == 200 and body["ok"] is True
    data = body["data"]
    assert data["advisory_only"] is True
    assert any(c["id"] == row["id"] for c in data["candidates"])

    st, body = api_v2.handle(f"/api/v2/hermes/discovery-inbox/{row['id']}", method="GET")
    assert st == 200 and body["data"]["id"] == row["id"]
    assert body["data"]["advisory_only"] is True
    assert isinstance(body["data"]["audit"], list) and body["data"]["audit"]

    before_audit = _execute("SELECT count(*) AS n FROM hermes_discovery_audit "
                            "WHERE candidate_id = %s", (row["id"],), fetch="one")["n"]
    st, body = api_v2.handle(f"/api/v2/hermes/discovery-inbox/{row['id']}/reject",
                             method="POST", body={"actor": "pytest", "notes": "route test"})
    assert st == 200 and body["ok"] is True and body["advisory_only"] is True
    assert body["result"]["status"] == "REJECTED"
    after_audit = _execute("SELECT count(*) AS n FROM hermes_discovery_audit "
                           "WHERE candidate_id = %s", (row["id"],), fetch="one")["n"]
    assert after_audit == before_audit + 1  # decision appended an audit row


@needs_db
def test_routes_decision_variants_and_errors():
    import api_v2
    # needs-more-data
    a = _track(inbox.upsert_candidate("TREND_CANDIDATE", f"orbital compute race {TAG}"))
    inbox.transition_candidate(a["id"], "READY_FOR_REVIEW", actor="pytest")
    st, body = api_v2.handle(f"/api/v2/hermes/discovery-inbox/{a['id']}/needs-more-data",
                             method="POST", body={"actor": "pytest"})
    assert st == 200 and body["result"]["status"] == "NEEDS_MORE_DATA"
    # block
    st, body = api_v2.handle(f"/api/v2/hermes/discovery-inbox/{a['id']}/block",
                             method="POST", body={"actor": "pytest"})
    assert st == 200 and body["result"]["status"] == "BLOCKED"
    # merge with target note
    b = _track(inbox.upsert_candidate("TREND_CANDIDATE", f"lunar regolith mining {TAG}"))
    st, body = api_v2.handle(f"/api/v2/hermes/discovery-inbox/{b['id']}/merge",
                             method="POST", body={"actor": "pytest",
                                                  "merge_into_id": a["id"]})
    assert st == 200 and body["result"]["status"] == "MERGED_DUPLICATE"
    # stage-ticker on a validated ticker
    t = _track(inbox.upsert_candidate("TICKER_CANDIDATE", "MSFT",
                                      normalized_key=f"msft {TAG}"))
    st, body = api_v2.handle(f"/api/v2/hermes/discovery-inbox/{t['id']}/stage-ticker",
                             method="POST", body={"actor": "pytest"})
    assert st == 200 and body["result"]["status"] == "STAGED_TICKER_REVIEW"
    # illegal decision → 409, unknown action → 400, missing id → 404
    st, body = api_v2.handle(f"/api/v2/hermes/discovery-inbox/{b['id']}/reject",
                             method="POST", body={})
    assert st == 409 and body["ok"] is False
    st, body = api_v2.handle(f"/api/v2/hermes/discovery-inbox/{b['id']}/frobnicate",
                             method="POST", body={})
    assert st == 400
    st, body = api_v2.handle("/api/v2/hermes/discovery-inbox/999999999/reject",
                             method="POST", body={})
    assert st == 404


@needs_db
def test_route_approve_research_topic_promotes(monkeypatch):
    import api_v2
    row = _track(inbox.upsert_candidate(
        "TOPIC_CANDIDATE", f"smr permitting acceleration {TAG}",
        meta={"keywords": ["SMR permitting"]}))
    inbox.transition_candidate(row["id"], "READY_FOR_REVIEW", actor="pytest")
    st, body = api_v2.handle(f"/api/v2/hermes/discovery-inbox/{row['id']}/approve-research-topic",
                             method="POST", body={"actor": "pytest"})
    assert st == 200 and body["ok"] is True and body["advisory_only"] is True
    assert body["result"]["promoted_ref_type"] == "research_topic"
    assert body["result"]["status"] == "APPROVED_RESEARCH_ONLY"


# ── ingestors: forbidden imports + dry-run shape ─────────────────────────────

@needs_db
def test_ingestors_dry_run_no_writes():
    import hermes_discovery_ingestors as ing
    from db_adapter import _execute
    before = _execute("SELECT count(*) AS n FROM hermes_discovery_candidates",
                      fetch="one")["n"]
    for fn in (ing.ingest_sources, ing.ingest_trends, ing.ingest_tickers,
               ing.ingest_topics):
        res = fn(limit=5, dry_run=True)
        assert res["dry_run"] is True
        assert res["upserted"] == 0
        assert isinstance(res["candidates"], list)
    after = _execute("SELECT count(*) AS n FROM hermes_discovery_candidates",
                     fetch="one")["n"]
    assert after == before  # dry-run wrote nothing


# ── scorecard (DB) ───────────────────────────────────────────────────────────

@needs_db
def test_scorecard_emits_all_metric_keys(tmp_path):
    import hermes_discovery_scorecard as hds
    card = hds.build_scorecard()
    for key in ("version", "generated_at", "totals", "by_status", "by_type",
                "intake", "decisions", "dedupe", "ticker_validation", "feedback",
                "audit_rows", "promotions", "windows", "do_no_harm"):
        assert key in card, f"scorecard missing key: {key}"
    assert card["version"] == hds.SCORECARD_VERSION
    for w in ("last_7d", "prior_7d"):
        win = card["windows"][w]
        for k in ("candidate_volume", "duplicate_rate", "ticker_volume",
                  "false_ticker_rate"):
            assert k in win
    dnh = card["do_no_harm"]
    assert dnh["recommendation"] in ("steady", "tighten", "pause")
    assert "by_ref_type" in card["promotions"]
    assert "promotions_7d" in card["promotions"]
    # discovery_health summary + feed writer (isolated path)
    health = hds.build_discovery_health(card)
    for k in ("generated_at", "candidates_total", "duplicate_rate_7d",
              "false_ticker_rate_7d", "promotions_7d", "recommendation"):
        assert k in health
    monkey_feed = tmp_path / "feed.json"
    orig = hds.OUTCOME_FEED_PATH
    try:
        hds.OUTCOME_FEED_PATH = monkey_feed
        path = hds.write_outcome_feed(card)
        feed = json.loads(path.read_text())
        assert feed["section"] == "discovery_health"
        assert feed["latest"]["recommendation"] == dnh["recommendation"]
        assert "outcome_bus" in feed["note"]
    finally:
        hds.OUTCOME_FEED_PATH = orig


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
