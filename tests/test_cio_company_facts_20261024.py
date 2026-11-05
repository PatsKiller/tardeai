"""C1 ONE BRAIN: batch source -> existing CIO record -> actual consumers, offline.

ANCHOR: CIO_COMPANY_FACTS_20261024. All stores/clocks/readers are fixtures. No
production state, provider, database connection, alert delivery or HTTP server.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib import cio_company_facts as cf, cio_instrument_record as ir  # noqa: E402
from scripts.lib.data_broker import cio_company_facts as broker  # noqa: E402

NOW = datetime(2026, 10, 24, 14, tzinfo=timezone.utc)
AT = "2026-10-23T13:00:00+00:00"
GUID = "5f0c6a3e-2222-5222-8222-000000000001"
OTHER = "5f0c6a3e-2222-5222-8222-000000000002"
IDENT = {"symbol": "ACME", "security_guid": GUID, "subject_guid": GUID,
         "issuer_guid": OTHER, "identity_status": "CONFIRMED"}


def inputs():
    return {"profiles": {"ACME": {"description": "Acme makes precision instruments for industrial customers.",
                                    "sector": "Industrials", "industry": "Scientific Instruments", "updated_at": AT}},
            "finviz": {"ACME": {"as_of": AT, "record": {"company": "Acme Instruments Inc.",
                                                         "sector": "Industrials"}}}}


def facts(**kwargs):
    return cf.assemble("ACME", IDENT, inputs(), now=NOW, **kwargs)


def seed(root, *, duplicate=False):
    store = ir.InstrumentRecordStore(root / ir.DEFAULT_PATH)
    rec = {"subject_key": "WATCH:ACME", "symbol": "ACME", "kind": "WATCH", **IDENT,
           "symbols": ["ACME"], "stance": "WATCH", "stage": "watching", "conviction": 61, "evidence_at": AT,
           "expires_at": (NOW + timedelta(days=1)).isoformat(), "thesis_ref": "thesis-original",
           "research": {"private_notes": "must remain private", "review_lifecycle": {
               "status": "ANSWERED", "request_id": "req-fixture", "answered_at": AT,
               "reason": "Evidence collected; CIO decision pending", "old_stance": "WATCH", "new_stance": None,
               "quantity": 987654}}, "cognition": {"prior": "unchanged"}}
    rec, _ = ir.apply_prospect(rec, prospect={"research": rec["research"]}, strict=False)
    store.upsert(rec)
    if duplicate:
        store.upsert({**rec, "subject_key": "HELD:ACME", "kind": "HELD"})
    return store


def tree(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


def test_stored_sources_are_read_once_in_bulk_and_original_clock_survives(tmp_path):
    path = tmp_path / "data/state/ticker_enrichment_cache.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ACME": {"company": "Acme Instruments Inc.", "cached_at": AT}}))
    calls = []

    def query(sql, params):
        calls.append((sql, params))
        return [{"symbol": "ACME", "sector": "Industrials", "description_1s": "Acme makes instruments.",
                 "updated_at": NOW - timedelta(days=1), "source": "fixture_profile"}]

    before = tree(tmp_path)
    batch = cf.collect_inputs(tmp_path, ["ACME", "NONE"], db_query=query, now=NOW)
    f = cf.assemble("ACME", IDENT, batch, now=NOW)
    assert len(calls) == 1 and calls[0][1] == (["ACME", "NONE"],)
    assert "updated_at, source" in calls[0][0]
    assert f["company"]["value"] == "Acme Instruments Inc."
    assert f["company"]["observed_at"] == AT
    assert f["description"]["observed_at"] == (NOW - timedelta(days=1)).isoformat()
    assert f["description"]["clock_kind"] == "row_updated_at"
    assert f["description"]["producer_source"] == "fixture_profile"
    assert tree(tmp_path) == before


def test_saved_identity_profile_is_read_raw_without_minting_source_clock(tmp_path):
    path = tmp_path / "data/cio/ticker_research_graph.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": "TickerKnowledgeProfile@v1", "symbol": "ACME", "company": "Acme",
                                "security_guid": GUID, "updated_at": AT}) + "\n")
    f = cf.assemble("ACME", IDENT, cf.collect_inputs(tmp_path, ["ACME"], now=NOW), now=NOW)
    assert f["company"]["source"] == "ticker_research_graph.profile"
    assert f["company"]["observed_at"] == AT
    assert f["company"]["clock_kind"] == "profile_updated_at"


@pytest.mark.parametrize("identity", [{**IDENT, "identity_status": "CANDIDATE"}, {**IDENT, "security_guid": "fake"}])
def test_unproven_identity_cannot_assemble_company_facts(identity):
    f = cf.assemble("ACME", identity, inputs(), now=NOW)
    assert f["status"] == "MISSING" and f["company"]["value"] is None
    assert f["missing_reason"] == "identity_not_confirmed"


def test_guid_mismatch_is_excluded_and_conflicts_are_visible():
    data = inputs()
    data["profiles"]["ACME"]["security_guid"] = OTHER
    data["finviz"]["ACME"]["record"]["security_guid"] = OTHER
    f = cf.assemble("ACME", IDENT, data, now=NOW,
                    catalyst={"facts": [{"headline": "Wrong company event", "subject_guid": OTHER,
                                          "published_at": AT, "source": "fixture"}]})
    assert f["description"]["value"] is None and f["company"]["value"] is None
    assert f["catalyst"]["headline"] is None
    assert any(c["field"] == "catalyst" and c["reason"] == "source_guid_mismatch" for c in f["conflicts"])


def test_retained_source_values_keep_original_clocks_and_disagreement_is_not_hidden():
    old = facts()
    data = inputs()
    data["profiles"]["ACME"].update(sector="Technology", updated_at=None)
    f = cf.assemble("ACME", IDENT, data, prior=old, now=NOW + timedelta(hours=1))
    assert f["sector"]["value"] == "Industrials" and f["sector"]["observed_at"] == AT
    assert any(c["field"] == "sector" and c["reason"] == "source_values_disagree" for c in f["conflicts"])
    data = {"profiles": {}, "finviz": {}}
    retained = cf.assemble("ACME", IDENT, data, prior=old, now=NOW + timedelta(days=2))
    assert retained["description"] == old["description"]


@pytest.mark.parametrize("at", [None, "bad", "2026-10-23T12:00:00", "2026-08-01T00:00:00+00:00",
                                "2026-10-25T00:00:00+00:00"])
def test_undated_stale_and_future_catalysts_never_become_current(at):
    f = facts(catalyst={"facts": [{"headline": "Acme event", "source": "fixture", "published_at": at}]})
    assert f["catalyst"]["headline"] is None
    assert f["catalyst"]["missing_reason"] == "no_dated_current_catalyst_on_file"


def test_current_catalyst_preserves_publication_and_verification_claim_not_probability():
    f = facts(catalyst={"facts": [{"headline": "Acme opens a factory", "source": "catalyst_events", "feed": "fixture",
                                  "catalyst_type": "product_launch",
                                  "published_at": AT, "url": "https://example.invalid/acme", "verified": True,
                                  "confidence": 1.1, "factual_verification_status": "UNKNOWN"}]})
    c = f["catalyst"]
    assert c["published_at"] == AT and c["url"] == "https://example.invalid/acme"
    assert c["source_verified_claim"] is True and c["independent_verification"] == "NOT_MEASURED"
    assert c["factual_verification_status"] == "UNKNOWN" and "confidence" not in c
    snap = {GUID: {"company_facts": f, "review_lifecycle": {"status": "MISSING"}}}
    stale = broker.for_security(snap, "ACME", GUID, now=NOW + timedelta(days=31))
    assert stale["company_facts"]["catalyst"]["status"] == "STALE"
    assert f["catalyst"]["status"] == "CURRENT", "request projection must not mutate the saved record"


def test_fact_only_writer_preserves_every_judgment_and_other_research_keys(tmp_path):
    store = seed(tmp_path)
    before = deepcopy(store.all()[0])
    proposed = {**before, "stance": "BUY", "conviction": 99,
                "research": {"company_facts": facts(), "review_lifecycle": {"status": "FALSIFIED"}}}
    before_tree = tree(tmp_path)
    dry = cf.persist_company_facts(tmp_path, [proposed])
    assert dry["would_write"] == 1 and dry["written"] == 0 and tree(tmp_path) == before_tree
    result = cf.persist_company_facts(tmp_path, [proposed], write=True)
    latest = ir.InstrumentRecordStore(tmp_path / ir.DEFAULT_PATH).all()[0]
    assert result["written"] == 1 and len(store.history("WATCH:ACME")) == 2
    assert latest["research"]["company_facts"] == proposed["research"]["company_facts"]
    assert {k: v for k, v in latest["research"].items() if k != "company_facts"} == before["research"]
    for k in before:
        if k not in ("updated_ts", "research", "prospect_revision"):
            assert latest[k] == before[k], k
    assert cf.persist_company_facts(tmp_path, [proposed], write=True)["written"] == 0


@pytest.mark.parametrize("duplicate,reason", [(False, "cio_record_missing"), (True, "multiple_cio_records_for_guid")])
def test_no_mint_or_arbitrary_head_selection(tmp_path, duplicate, reason):
    if duplicate:
        seed(tmp_path, duplicate=True)
    before = tree(tmp_path)
    result = cf.persist_company_facts(tmp_path, [{"symbol": "ACME", "security_guid": GUID,
                                                "research": {"company_facts": facts()}}], write=True)
    assert result["written"] == 0 and result["gaps"][0]["reason"] == reason
    assert tree(tmp_path) == before


def test_judged_prospect_plus_fact_only_sibling_is_one_canonical_record(tmp_path):
    """One judged prospect + one fact-only SECURITY record for the same GUID is one
    canonical record (no ``multiple_cio_records_for_guid``), and the fact-only sibling's
    company facts still render when the prospect lacks them (2026-10-24 design)."""
    store = ir.InstrumentRecordStore(tmp_path / ir.DEFAULT_PATH)
    # fact-only SECURITY record — the designed home of research.company_facts.
    fact_only = ir.new_record("SECURITY", "ACME", symbols=["ACME"], **IDENT)
    fact_only, _ = ir.apply_prospect(fact_only, prospect={"research": {"company_facts": facts()}}, fact_only=True)
    store.upsert(fact_only)
    # judged HELD prospect for the same GUID, with no company facts of its own.
    prospect = ir.new_record("HELD", "ACME", symbols=["ACME"], **IDENT)
    prospect, _ = ir.apply_prospect(prospect, prospect={
        "stage": "held", "stance": "HOLD", "conviction": 61,
        "evidence_at": AT, "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "research": {"review_lifecycle": {"status": "ANSWERED", "request_id": "prospect-req"}},
    })
    store.upsert(prospect)
    assert ir.is_prospect_record(prospect) and ir.is_fact_only_record(fact_only)
    snapshot = broker.load_snapshot(tmp_path)
    row = broker.for_security(snapshot, "ACME", GUID, now=NOW)
    # The judged prospect is canonical: lifecycle kept, no multiple_cio_records_for_guid.
    assert row["review_lifecycle"]["status"] == "ANSWERED"
    assert row["review_lifecycle"]["request_id"] == "prospect-req"
    assert row["company_facts"].get("missing_reason") != "multiple_cio_records_for_guid"
    # The fact-only sibling's company facts still render (never silently dropped).
    assert row["company_facts"]["company"]["value"] == "Acme Instruments Inc."
    assert row["company_facts"]["description"]["value"].startswith("Acme makes")


def test_more_than_one_judged_prospect_still_flags_multiple_records(tmp_path):
    store = ir.InstrumentRecordStore(tmp_path / ir.DEFAULT_PATH)
    for kind, stage, stance in (("HELD", "held", "HOLD"), ("WATCH", "watching", "WATCH")):
        rec = ir.new_record(kind, "ACME", symbols=["ACME"], **IDENT)
        rec, _ = ir.apply_prospect(rec, prospect={
            "stage": stage, "stance": stance, "conviction": 61,
            "evidence_at": AT, "expires_at": (NOW + timedelta(days=1)).isoformat(),
        })
        store.upsert(rec)
    snapshot = broker.load_snapshot(tmp_path)
    row = broker.for_security(snapshot, "ACME", GUID, now=NOW)
    assert row["company_facts"]["missing_reason"] == "multiple_cio_records_for_guid"
    assert row["review_lifecycle"]["missing_reason"] == "multiple_cio_records_for_guid"


def test_builder_merges_extension_and_review_without_writing(tmp_path):
    from scripts.lib import cio_prospect_builder as b
    seed(tmp_path)
    path = tmp_path / "data/state/ticker_enrichment_cache.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ACME": {"company": "Acme", "cached_at": AT}}))
    before = tree(tmp_path)
    doc = b.build(tmp_path, symbols=["ACME"], identity_resolver=lambda _: IDENT, now=NOW,
                  held_reader=lambda: {"symbols": set(), "source": "fixture", "as_of": AT})
    assert tree(tmp_path) == before and doc["counts"]["prospects"] == 1
    r = doc["prospects"][0]
    assert r["research"]["company_facts"]["company"]["value"] == "Acme"
    assert r["research"]["review_lifecycle"]["status"] == "ANSWERED"
    assert doc["sources"]["company_facts"] == {"status": "stored_batch", "count": 1, "as_of": None}


def test_batch_cli_default_is_inert_and_explicit_opt_in_is_fact_only(tmp_path, monkeypatch, capsys):
    from scripts import cio_prospect_shadow_build as cli
    from scripts.lib import cio_prospect_builder as b
    seed(tmp_path)
    doc = b.build(tmp_path, symbols=["ACME"], identity_resolver=lambda _: IDENT, now=NOW,
                  held_reader=lambda: {"symbols": set(), "source": "fixture", "as_of": AT})
    monkeypatch.setattr(cli.builder, "build", lambda *a, **k: doc)
    before = tree(tmp_path)
    assert cli.main(["--state-root", str(tmp_path)]) == 0
    assert tree(tmp_path) == before
    assert json.loads(capsys.readouterr().out)["company_facts"]["written"] == 0
    with pytest.raises(SystemExit):
        cli.main(["--dry-run", "--write-company-facts", "--state-root", str(tmp_path)])
    assert tree(tmp_path) == before
    assert cli.main(["--write-company-facts", "--state-root", str(tmp_path)]) == 1
    result = json.loads(capsys.readouterr().out)["company_facts"]
    assert result["written"] == 1 and result["consumer_sync"] == "INERT"
    assert not (tmp_path / cli.SHADOW_REL).exists()


def test_saved_record_not_a_provider_is_ask_cio_source(tmp_path):
    from scripts.lib import cio_ask_research as ask
    seed(tmp_path)
    cf.persist_company_facts(tmp_path, [{"symbol": "ACME", "security_guid": GUID,
                                        "research": {"company_facts": facts()}}], write=True)
    entity = ask.Entity("Acme", "listed", symbol="ACME", security_guid=GUID, identity_status="CONFIRMED")
    ctx = ask.ResearchContext("What does Acme do?", now=NOW, state_root=tmp_path)
    out = ask._src_cio_record_research(entity, ctx)
    assert any("precision instruments" in f.claim and cf.timestamp(f.as_of) == cf.timestamp(AT)
               and f.citation["clock_kind"] == "row_updated_at" for f in out)
    assert any("ANSWERED" in f.claim and "req-fixture" in f.claim and cf.timestamp(f.as_of) == cf.timestamp(AT) for f in out)
    assert all("987654" not in f.claim and "private_notes" not in f.claim for f in out)
    assert any(s.name == "internal.cio_record_research" for s in ask.default_sources())


def test_telegram_and_specialist_envelope_consume_same_saved_guid_record(tmp_path, monkeypatch):
    from scripts.lib import cio_persistent_cognition as pc
    from scripts.lib.agent_context_envelope import get_context_for_agent
    from scripts.lib.cio_telegram_converse import assemble_context
    seed(tmp_path)
    cf.persist_company_facts(tmp_path, [{"symbol": "ACME", "security_guid": GUID,
                                        "research": {"company_facts": facts()}}], write=True)
    p = tmp_path / "data/cio/ticker_research_state.jsonl"
    p.write_text(json.dumps({"symbol": "ACME", "security_guid": GUID, "issuer_guid": OTHER,
                             "updated_at": AT, "decision": "NO_NEW_INFO"}) + "\n")
    row = pc.cognition_for_symbol(tmp_path, "ACME")
    assert row["cio_record_research"]["company_facts"]["description"]["value"].startswith("Acme makes")
    assert pc.telegram_fields(row)["cio_record_research"]["review_lifecycle"]["status"] == "ANSWERED"
    env = get_context_for_agent(agent="specialist", symbols=["ACME"], cognition_root=str(tmp_path))
    pack = env["research_memory"]["persistent_ticker_cognition"]
    assert pack["items"][0]["cio_record_research"] == row["cio_record_research"]
    assert "Acme makes" in json.dumps(pack["cio_context_v2"]["sections"]["COMPANY_FACTS"])
    assert "ANSWERED" in json.dumps(pack["cio_context_v2"]["sections"]["REVIEW_LIFECYCLE"])
    monkeypatch.setenv("TRADEAI_CURRENT", str(tmp_path))
    ctx = assemble_context("What is the company ACME?")
    assert ctx["ticker_cognition"][0]["cio_record_research"] == row["cio_record_research"]
    assert "private_notes" not in json.dumps(pack) and "987654" not in json.dumps(pack)


def test_snapshot_refuses_wrong_guid_and_projects_only_public_research(tmp_path):
    seed(tmp_path)
    cf.persist_company_facts(tmp_path, [{"symbol": "ACME", "security_guid": GUID,
                                        "research": {"company_facts": facts()}}], write=True)
    snapshot = broker.load_snapshot(tmp_path)
    same = broker.for_security(snapshot, "RENAMED", GUID, now=NOW)
    wrong = broker.for_security(snapshot, "ACME", OTHER, now=NOW)
    assert same["company_facts"]["company"]["value"] == "Acme Instruments Inc."
    assert wrong["company_facts"]["company"]["value"] is None
    assert "private_notes" not in json.dumps(same) and "987654" not in json.dumps(same)

class FakePG:
    def __init__(self, fail=False):
        self.rows = {}
        self.fail = fail
        self.probes = 0
        self.events = []

    def table_present(self):
        self.probes += 1
        return True

    def write(self, row, event, lifecycle=()):
        if self.fail:
            raise RuntimeError("private connection detail must not escape")
        self.rows[row["security_guid"]] = deepcopy(row)
        self.events.append(deepcopy(event))
        return {"ok": True, "upserted": 1, "event_appended": 1}

    def query(self, sql, params=None):
        assert "SELECT" in sql and "cio_prospect" in sql
        return list(self.rows.values())


GRANTED = {"domains": [{"domain": "cio_prospect", "approval": {"approved_by": "offline-fixture-owner"}}]}
ENABLED = {ir.PROSPECT_DUAL_WRITE_ENV: "1"}


def test_gated_fake_pg_and_all_record_consumers_read_same_guid_facts(tmp_path, monkeypatch):
    from scripts.lib.data_broker import cio_prospect as cp
    from scripts.lib import cio_ask_research as ask, cio_persistent_cognition as pc
    seed(tmp_path)
    pg = FakePG()
    f = facts()
    result = cf.persist_company_facts(tmp_path, [{"symbol": "ACME", "security_guid": GUID,
                                                "research": {"company_facts": f}}], write=True,
                                      backend=pg, registry=GRANTED, env=ENABLED)
    assert result["ok"] and result["consumer_sync"] == "DUAL_WRITE_ACKNOWLEDGED"
    assert pg.probes == 1 and len(pg.events) == 1
    status = ir.prospect_store_status(registry=GRANTED, env=ENABLED, table_probe=pg.table_present)
    view = cp.get_prospect(GUID, db_query=pg.query, status=status, now=NOW)
    assert view["source"]["kind"] == "store"
    readback = view["prospect"]
    assert readback["research"]["company_facts"] == f
    assert broker.for_security(broker.load_snapshot(tmp_path), "ACME", GUID, now=NOW)["company_facts"] == f
    ent = ask.Entity("Acme", "listed", symbol="ACME", security_guid=GUID)
    assert any("precision instruments" in r.claim for r in ask._src_cio_record_research(
        ent, ask.ResearchContext("company facts?", state_root=tmp_path, now=NOW)))
    p = tmp_path / "data/cio/ticker_research_state.jsonl"
    p.write_text(json.dumps({"symbol": "ACME", "security_guid": GUID, "issuer_guid": OTHER,
                             "updated_at": AT, "decision": "NO_NEW_INFO"}) + "\n")
    assert pc.cognition_for_symbol(tmp_path, "ACME")["cio_record_research"]["company_facts"] == f

    # Same saved record facts on Prospects and My Watchlist. No profile/Finviz read
    # is permitted in this HTTP projection; the batch already did that work.
    from lib.data_broker import watch_prospects as wp, watch_curation as wc, watch_domains as wd, watch_position_facts as pf
    from lib.data_broker import cio_company_facts as web_cf
    monkeypatch.setattr(web_cf, "load_snapshot", lambda: broker.load_snapshot(tmp_path))
    monkeypatch.setattr(wp, "_cio_prospect_records", lambda: ([readback], "store"))
    monkeypatch.setattr(wp, "_operator_membership", lambda: {"names": {"ACME": {"starred": True, "reasons": []}}})
    monkeypatch.setattr(wp, "_curator_projection", lambda: {"items": {}})
    monkeypatch.setattr(wd, "held_positions", lambda **kw: {})
    monkeypatch.setattr(wd, "held_detail_public", lambda x: x)
    monkeypatch.setattr(pf, "load", lambda **kw: {"facts_for": lambda s: {"position_state": "never_held"}})
    monkeypatch.setattr(pf, "public", lambda x: {"status": "fixture"})
    monkeypatch.setattr(wc, "read_dismissed", lambda: ({}, "ok"))
    wp._CACHE.update(at=0, val=None)
    try:
        g = wp.gather({"fresh": "1"}, db_query=lambda *a: [], now=NOW)
        assert g["row_for"]("ACME")["company_facts"] == f
        mine = wc.build_curation(g, now=NOW)["my_watchlist"]["rows"]
        assert mine[0]["company_facts"] == f
        # C1 quality: the card shows the common display name; the registered name is secondary.
        assert mine[0]["company"] == f["company"]["display_name"] == "Acme Instruments"
        assert mine[0]["company_legal_name"] == f["company"]["value"]
    finally:
        wp._CACHE.update(at=0, val=None)


@pytest.mark.parametrize("enabled,fail,expected", [(False, False, "INERT"), (True, True, "FAILED")])
def test_inert_and_pg_failure_are_visible_not_false_full_consumer_acceptance(tmp_path, enabled, fail, expected):
    seed(tmp_path)
    pg = FakePG(fail=fail)
    result = cf.persist_company_facts(tmp_path, [{"symbol": "ACME", "security_guid": GUID,
                                                "research": {"company_facts": facts()}}], write=True,
                                      backend=pg, registry=GRANTED, env=ENABLED if enabled else {})
    assert result["written"] == 1 and result["consumer_sync"] == expected and not result["ok"]
    assert not pg.rows
    assert pg.probes == int(enabled), "flag-off must never touch even a table probe"
    assert "private connection detail" not in json.dumps(result)
    if fail:
        assert result["pg"][0]["error"] == "RuntimeError"
    else:
        assert "dual_write_flag_off" in result["pg"][0]["reasons"]


def test_legacy_record_is_not_silently_promoted_by_company_enrichment(tmp_path):
    store = seed(tmp_path)
    legacy = deepcopy(store.all()[0])
    legacy.pop("prospect_schema")
    store.upsert(legacy)
    before = tree(tmp_path)
    result = cf.persist_company_facts(tmp_path, [{"symbol": "ACME", "security_guid": GUID,
                                                "research": {"company_facts": facts()}}], write=True)
    assert result["gaps"][0]["reason"] == "legacy_record_needs_cio_promotion"
    assert result["written"] == 0 and tree(tmp_path) == before


def test_write_shadow_only_never_writes_the_cio_record(tmp_path, monkeypatch, capsys):
    from scripts import cio_prospect_shadow_build as cli
    from scripts.lib import cio_prospect_builder as b
    seed(tmp_path)
    doc = b.build(tmp_path, symbols=["ACME"], identity_resolver=lambda _: IDENT, now=NOW,
                  held_reader=lambda: {"symbols": set(), "source": "fixture", "as_of": AT})
    monkeypatch.setattr(cli.builder, "build", lambda *a, **k: doc)
    monkeypatch.setattr(cli.builder, "compare", lambda *a, **k: {"summary": {}})
    before = (tmp_path / ir.DEFAULT_PATH).read_bytes()
    assert cli.main(["--write-shadow", "--state-root", str(tmp_path)]) == 0
    assert (tmp_path / ir.DEFAULT_PATH).read_bytes() == before
    assert json.loads(capsys.readouterr().out)["company_facts"]["written"] == 0
    assert (tmp_path / cli.SHADOW_REL).is_file()


@pytest.mark.parametrize("headline,sources,name,accepted", [
    ("Archrock announces unrelated contract", [{"title": "Archrock announces contract", "url": "https://example.invalid/archrock-contract"}], "Acme Instruments Inc.", False),
    ("Acme Instruments launches precision analyzer", [{"title": "Acme Instruments launches precision analyzer", "url": "https://example.invalid/acme-analyzer"}], "Acme Instruments Inc.", True),
    ("ACME", [{"title": "ALL NEWS", "url": "https://example.invalid/news"}], "Acme Instruments Inc.", False),
    ("ACME announces new product", [], None, False),
])
def test_hermes_company_selection_reuses_identity_validator(headline, sources, name, accepted):
    data = inputs()
    data["finviz"]["ACME"]["record"]["company"] = name
    raw = {"catalyst_summary": headline, "sources": sources}
    result = cf.assemble("ACME", IDENT, data, now=NOW, catalyst={"facts": [{
        "headline": headline, "source": "hermes_momentum_catalysts", "observed_at": AT,
        "catalyst_type": "product_launch", "identity_record": raw}]})
    c = result["catalyst"]
    assert (c.get("status") == "CURRENT") is accepted
    if accepted:
        assert c["identity_verification"]["status"] == "VERIFIED"
        assert c["identity_record"] == raw and c["observed_at"] == AT
        assert c["independent_verification"] == "NOT_MEASURED"
    else:
        assert c["headline"] is None
        assert any(x["reason"] == "hermes_company_identity_unverified" for x in result["conflicts"])


def test_builder_carries_raw_hermes_identity_evidence_without_rewriting_history():
    from scripts.lib import cio_prospect_builder as b
    raw = {"catalyst_type": "product", "catalyst_summary": "An unrelated company announces a product", "research_timestamp": AT,
           "sources": [{"title": "ALL NEWS", "url": "https://example.invalid/news"}]}
    block, _, _ = b.catalyst_facts("ACME", {"hermes_catalysts": {"rows": {"ACME": raw}}}, IDENT, now=NOW)
    f = block["facts"][0]
    assert f["headline"] == raw["catalyst_summary"], "historical research remains intact"
    assert f["identity_record"]["sources"] == raw["sources"]
    selected = facts(catalyst=block)
    assert selected["catalyst"]["headline"] is None
