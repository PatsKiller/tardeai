"""CIO prospect — catalyst facts on the record (ANCHOR CIO_PROSPECT_CATALYST_FACTS_20261023).

Silo audit 2026-10-23 (docs/ops/CIO_MEMORY_SILO_AUDIT_2026-10-23.md, PR #1995, P1): operator, verbatim: "Anything that's such as
a security catalyst related to the security, anything for the security . The CIO agent needs to have it in memory. We
should have no silos." Measured: SAIQ — Trade AI cited an UNVERIFIED 2026-10-20 catalyst while catalyst_events' newest
typed row (2026-10-05, legacy confidence threshold => "verified") said otherwise, and the CIO record carried no
catalyst at all (catalyst_grade None, NOT_WIRED).

Pins (AGENTS.md §26): the catalyst facts from every producer the builder reads land on the ONE prospect record
(catalyst_grade), keyed by security_guid; two verdicts are a recorded conflict, never resolved (§26.5); a catalyst the
scanner cites that the store lacks is a named gap; no grade is invented (Gate 2 has no producer); the store is read
through its registered projection (§7A rule 3); MBI_BEHAVIOR = 0; the builder still writes nothing; a catalyst change
is an append-only, idempotent prospect event.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib import cio_instrument_record as ir  # noqa: E402
from scripts.lib import cio_prospect_builder as B  # noqa: E402
from scripts.lib.data_broker import catalyst_record as CR  # noqa: E402

NOW = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)   # 09:30 ET, market open
G_SAIQ, I_SAIQ = "5f0c6a3e-2222-5222-8222-000000000001", "5f0c6a3e-2222-5222-8222-0000000000a1"
G_ACME, I_ACME = "5f0c6a3e-2222-5222-8222-000000000002", "5f0c6a3e-2222-5222-8222-0000000000a2"
G_OTHER = "5f0c6a3e-2222-5222-8222-000000000099"
IDS = {"SAIQ": (G_SAIQ, I_SAIQ), "ACME": (G_ACME, I_ACME)}


def _identity(sym: str) -> dict:
    g, i = IDS[sym]
    return {"symbol": sym, "security_guid": g, "issuer_guid": i, "subject_guid": g, "identity_status": "CONFIRMED"}


def _state(tmp: Path) -> Path:
    (tmp / "data/cio").mkdir(parents=True)
    (tmp / "data/runtime").mkdir(parents=True)
    opp = {"symbol": "SAIQ", "as_of": "2026-10-23T13:00:00+00:00", "conviction": 75.9, "stance": "WATCH",
           "type": "new_position", "position_status": "not_owned", "coverage": 0.72, "rank": 163,
           "risk_reward": {"rr": 3.4}, "factors": {}, "factors_missing": ["fundamental", "analyst"]}
    (tmp / "data/cio/cio_opportunity_projection.json").write_text(json.dumps({
        "as_of": "2026-10-23T13:00:00+00:00",
        "items": {"SAIQ": opp, "ACME": {**opp, "symbol": "ACME", "rank": 9}}}))
    (tmp / "data/runtime/trade_ai_cache.json").write_text(json.dumps({
        "latest_run_timestamp": "2026-10-23T13:00:44+00:00",
        "source_observations": [{
            "symbol": "SAIQ", "observed_at": "2026-10-23T12:55:11+00:00", "decision": "MANUAL_REVIEW",
            "catalyst_verified": False, "catalyst_confidence": 0.0,
            "catalyst": "WISeSat.Space and SEALSQ Advance Satellite Cybersecurity Hardening as FOSSA Launches",
            "catalyst_source": "Yahoo Finance", "catalyst_url": "https://finance.example/wisesat",
            "catalyst_published_at": "2026-10-20T12:00:00+00:00"}]}))
    return tmp


CATALYST_ROWS = [
    # SAIQ: the store's newest typed row is 2026-10-05; confidence 0.56 => "verified" by the legacy threshold
    {"id": 198110, "symbol": "SAIQ", "subject_guid": G_SAIQ, "catalyst_type": "news_momentum",
     "headline": "Morning Market Movers: SAIQ, VEEA, PCVX, SDEV See Big Swings - RTTNews", "severity": "low",
     "impact_score": 3.7, "confidence": 0.56, "source": "google_news_rss", "source_url": "https://n.example/1",
     "at": datetime(2026, 10, 6, 2, 2, 57, tzinfo=timezone.utc)},
    # ACME: one row filed under another GUID
    {"id": 7, "symbol": "ACME", "subject_guid": G_OTHER, "catalyst_type": "earnings",
     "headline": "ACME beats", "severity": "medium", "impact_score": 6.0, "confidence": 0.9,
     "source": "sec_edgar_filing", "source_url": "https://n.example/2",
     "at": datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)},
]


def _db_query(sql, params=None):
    if "FROM catalyst_events" in sql:
        assert "row_number() OVER" in sql and "catalyst_type <> 'other'" in sql   # the projection's rules
        return [dict(r) for r in CATALYST_ROWS]
    return []


def _build(root: Path, db_query=_db_query):
    return B.build(root, db_query=db_query, held_reader=lambda: {"symbols": set(), "source": "t", "as_of": None},
                   identity_resolver=_identity, now=NOW)


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*") if p.is_file()}


def test_bulk_projection_normalizes_dedupes_and_carries_event_identity():
    rows = CATALYST_ROWS + [{**CATALYST_ROWS[0], "id": 198111}]          # same headline twice -> one
    by = CR.get_catalyst_records_bulk(lambda sql, params=None: [dict(r) for r in rows], days=30)
    assert set(by) == {"SAIQ", "ACME"} and len(by["SAIQ"]) == 1
    s = by["SAIQ"][0]
    assert s["id"] == 198110 and s["subject_guid"] == G_SAIQ and s["source"] == "google_news_rss"
    assert s["verified"] is True and s["verification_basis"] == "LEGACY_CONFIDENCE_THRESHOLD"
    assert s["at"].startswith("2026-10-06")
    json.dumps(by)                                                        # JSON-safe (no datetime/Decimal)


def test_saiq_two_catalyst_verdicts_are_one_recorded_conflict_and_a_named_gap(tmp_path):
    root = _state(tmp_path)
    before = _tree(root)
    doc = _build(root)
    assert _tree(root) == before                                          # still writes nothing
    assert doc["sources"]["catalyst_events"]["status"] == "ok"
    assert doc["sources"]["catalyst_events"]["path"] == "projection:catalyst_record"
    saiq = {r["symbol"]: r for r in doc["prospects"]}["SAIQ"]
    cg = saiq["catalyst_grade"]
    assert cg["grade"] is None and cg["grade_status"] == "not_produced"   # no grade invented
    assert cg["verdict"] == "DISAGREE"
    assert cg["sources"] == ["catalyst_events", "trade_ai_scans"]
    assert cg["freshest"]["source"] == "trade_ai_scans" and cg["freshest"]["published_at"].startswith("2026-10-20")
    c = [x for x in saiq["conflicts"] if x["field"] == "catalyst"]
    assert len(c) == 1 and c[0]["resolved"] is False
    assert {v["source"] for v in c[0]["values"]} == {"catalyst_events", "trade_ai_scans"}
    assert any(v["value"].startswith("unverified: WISeSat") for v in c[0]["values"])
    assert any("catalyst_events holds no row for the catalyst trade_ai_scans cites" in m for m in saiq["whats_missing"])
    assert saiq["next_action"]["who"] == "cio" and "catalyst" in saiq["next_action"]["fields"]
    blob = json.dumps(saiq)
    for k in ir.BEHAVIOR_FIELDS:
        assert f'"{k}":' not in blob, k                                   # MBI_BEHAVIOR = 0
    ir.prospect_row(saiq)                                                 # a valid table row


def test_catalyst_filed_under_another_guid_is_a_conflict_never_rekeyed(tmp_path):
    doc = _build(_state(tmp_path))
    acme = {r["symbol"]: r for r in doc["prospects"]}["ACME"]
    assert acme["catalyst_grade"]["verdict"] == "VERIFIED"
    ci = [x for x in acme["conflicts"] if x["field"] == "catalyst_identity"]
    assert len(ci) == 1 and {v["value"] for v in ci[0]["values"]} == {G_OTHER, G_ACME}


def test_without_a_db_the_store_is_reported_not_read_and_the_scanner_fact_still_lands(tmp_path):
    doc = _build(_state(tmp_path), db_query=None)
    assert doc["sources"]["catalyst_events"]["status"].startswith("not_read")
    saiq = {r["symbol"]: r for r in doc["prospects"]}["SAIQ"]
    assert saiq["catalyst_grade"]["verdict"] == "UNVERIFIED"
    assert not [x for x in saiq["conflicts"] if x["field"] == "catalyst"]
    assert not [m for m in saiq["whats_missing"] if "catalyst_events holds no row" in m]   # unknown, not a gap


def test_a_failing_store_read_is_reported_never_invented(tmp_path):
    def boom(sql, params=None):
        if "FROM catalyst_events" in sql:
            raise RuntimeError("down")
        return []
    doc = _build(_state(tmp_path), db_query=boom)
    assert doc["sources"]["catalyst_events"]["status"] == "error:RuntimeError"
    assert doc["counts"]["errors"] == 0


def test_hermes_none_found_is_a_fact_on_the_record_never_verified(tmp_path):
    root = _state(tmp_path)
    d = root / "data/hermes/momentum_catalysts"
    d.mkdir(parents=True)
    (d / "2026-10-22_catalysts.jsonl").write_text(json.dumps({"symbol": "ACME", "research_timestamp":
        "2026-10-22T11:00:00", "catalyst_type": "earnings", "catalyst_summary": "old", "confidence": 0.6}) + "\n")
    (d / "2026-10-23_catalysts.jsonl").write_text(json.dumps({"symbol": "ACME", "research_timestamp":
        "2026-10-23T11:25:27.5", "catalyst_type": "no_clear_catalyst", "catalyst_summary": "", "confidence": 0.2,
        "catalyst_strength": "low"}) + "\n")
    doc = _build(root)
    assert doc["sources"]["hermes_catalysts"]["status"] == "ok"
    acme = {r["symbol"]: r for r in doc["prospects"]}["ACME"]
    h = [f for f in acme["catalyst_grade"]["facts"] if f["source"] == "hermes_momentum_catalysts"]
    assert len(h) == 1 and h[0]["verified"] is False and h[0]["verification_basis"] == "HERMES_SEARCH_NONE_FOUND"
    assert h[0]["observed_at"] == "2026-10-23T11:25:27.5+00:00"
    assert acme["catalyst_grade"]["verdict"] == "DISAGREE"            # store "verified" vs Hermes none found
    c = [x for x in acme["conflicts"] if x["field"] == "catalyst"]
    assert {v["source"] for v in c[0]["values"]} == {"catalyst_events", "hermes_momentum_catalysts"}


def test_catalyst_change_is_an_idempotent_append_only_prospect_event(tmp_path):
    saiq = {r["symbol"]: r for r in _build(_state(tmp_path))["prospects"]}["SAIQ"]
    prior = {**saiq, "catalyst_grade": None, "revision": 1}
    row = {**saiq, "revision": 2}
    ev = ir.prospect_event(prior, row)
    assert "catalyst_grade" in ev["change"] and ev["event_key"] == "rev:2"
    assert ev["event_type"] in ir.PROSPECT_EVENT_TYPES
    assert ir.prospect_event(prior, row) == ev                            # same input, same key: idempotent


def test_starred_query_reads_the_real_column():
    sql = B.DB_QUERIES["starred"]
    assert "starred_at" in sql and "FROM operator_starred_symbols" in sql
    assert sql.split("FROM")[0].count("created_at") == 1 and "starred_at AS created_at" in sql


def test_gate_file_registers_this_test():
    gate = json.loads((ROOT / "config/ci_gates/cio_prospect_catalyst_facts_20261023.json").read_text())
    assert gate["name"] == "cio_prospect_catalyst_facts_20261023"
    assert "tests/test_cio_prospect_catalyst_facts_20261023.py" in gate["files"]
