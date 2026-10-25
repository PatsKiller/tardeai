"""Pinned merge regressions: source-proof readiness and observational premarket defaults.

No provider, live state, DB or transport. Future live paths use injected synthetic fixtures only.
"""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from lib import momentum_setup_evidence as mse
from lib import scalp_focus as sf
from lib import unified_momentum_alert as um
from active_trader import premarket_watch as pw
from tests.test_premarket_1min_threaded_20261023 import DAY, FakeData, FakeRecorder, base_bars, play, ts

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    for key, suffix in (("ACTIVE_TRADER_ALERTS_DIR", "at"), ("SCALP_FOCUS_DIR", "focus")):
        monkeypatch.setenv(key, str(tmp_path / suffix))
        (tmp_path / suffix).mkdir()
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_LEDGER", str(tmp_path / "unified.jsonl"))


def evidence(*, verified=False):
    row = {"symbol": "AAA", "price": 2.5, "float_m": 5, "rvol": 12, "gap_pct": 20,
           "catalyst": "Synthetic publication", "catalyst_source": "fixture",
           "catalyst_verified": verified, "run_date": DAY, "observed_at": NOW.isoformat()}
    if verified:
        row.update(catalyst_url="https://example.invalid/primary", catalyst_published_at=NOW.isoformat(),
                   catalyst_verification_method="PRIMARY_PUBLICATION")
    return mse.build_setup_evidence(row, now=NOW, observed_at=NOW.isoformat(), source_name="FIXTURE")


def event(ev=None, **kwargs):
    return um.UnifiedAlertEvent(symbol="AAA", state="WATCH", ts_epoch=NOW.timestamp(), origin="fixture",
                                evidence=ev, **kwargs)


def live_block(ev=None):
    return mse.evidence_block(ev, extra_facts=[{"id": "book", "label": "Book", "status": "PASSED",
                                              "detail": "fixture 2.5x", "driver": True}])


def test_merged_block_cannot_promote_an_unverified_catalyst():
    ev = evidence()
    text = um.render(event(ev, evidence_block=live_block(ev), catalyst_title="Synthetic publication"))
    assert "UNVERIFIED headline" in text
    assert "Ready: NO" in text and "needs 5/5, has 4/5" in text
    assert "Live facts:" in text and "Book fixture 2.5x" in text
    assert "Missing:" in text and "verified catalyst" in text.lower()
    assert "Ready: YES" not in text


def test_merged_block_keeps_main_veto_authoritative():
    ev = evidence(verified=True)
    text = um.render(event(ev, veto_reasons=["L2_ASK_HEAVY"], evidence_block=live_block(ev)))
    assert "Ready: NO" in text and "Active Trader veto: l2 ask heavy" in text
    assert "Ready: YES" not in text


def test_primary_readiness_only_render_is_preserved():
    ev = evidence(verified=True)
    text = um.render(event(ev))
    assert all(line in text for line in mse.format_readiness(mse.setup_readiness(ev)))
    assert "Live facts:" not in text and "Ready: YES" in text


def test_incoming_block_only_keeps_three_lines_without_an_unknown_second_verdict():
    block = live_block()
    text = um.render(event(evidence_block=block))
    assert mse.format_evidence_block(block) in text
    assert text.count("Ready:") == 1 and "Ready: UNKNOWN" not in text
    assert text.endswith(um.ADVISORY_LINE)


def test_block_only_headline_is_not_primary_source_verification():
    text = um.render(event(evidence_block=live_block(), catalyst_title="Synthetic publication"))
    assert "Catalyst: UNVERIFIED headline" in text


def test_enrichment_keeps_one_lookup_and_both_evidence_contracts():
    ev = evidence()
    e = event(ev, evidence_block=live_block(ev))
    lookups = []

    def lookup(symbol, day):
        lookups.append((symbol, day))
        return {"status": "FOUND", "summary": "Research inference", "catalyst_type": "fixture"}

    um.enrich_catalyst(e, lookup)
    assert lookups == [("AAA", DAY)]
    assert e.readiness["status"] == "NOT_READY" and e.readiness["catalyst"]["status"] == "UNVERIFIED_HEADLINE"
    stored = um._event_json(e)
    assert "evidence" not in stored and stored["readiness"] == e.readiness
    assert stored["evidence_block"] == e.evidence_block


@pytest.mark.parametrize("status", ["ok", "stale", "missing"])
def test_shadow_focus_never_changes_research_candidates(status):
    candidates = ["AAA", "BBB", {"symbol": "CCC"}]
    kept, report = sf.restrict_to_focus(candidates, cfg=sf.FocusConfig(mode="shadow"),
                                        focus={"status": status, "symbols": ["AAA", "CCC"]})
    assert kept == candidates and report["applied"] is False
    if status == "ok":
        assert report["would_drop"] == ["BBB"] and report["would_keep"] == 2
        assert report["dropped"] == []


def test_explicit_live_focus_fixture_still_filters():
    kept, report = sf.restrict_to_focus(["AAA", "BBB"], cfg=sf.FocusConfig(mode="live"),
                                        focus={"status": "ok", "symbols": ["AAA"]})
    assert kept == ["AAA"] and report["applied"] is True and report["dropped"] == ["BBB"]


def test_real_hermes_execution_observes_fresh_shadow_focus_without_filtering(tmp_path, monkeypatch, capsys):
    import hermes_momentum_catalyst_researcher as h
    from lib import hermes_catalyst_store as store

    researched = []
    monkeypatch.setattr(sf, "load_config", lambda: sf.FocusConfig(mode="shadow"))
    monkeypatch.setattr(sf, "read_focus", lambda **_: {"status": "ok", "symbols": ["AAA"]})
    monkeypatch.setattr(h, "_hot_research_on", lambda: False)
    monkeypatch.setattr(h, "get_scalp_candidates", lambda **_: ["AAA", "BBB"])
    monkeypatch.setattr(h, "active_trader_hot_symbols", lambda **_: [])
    monkeypatch.setattr(h, "run", lambda candidates, **_: researched.extend(candidates) or [])
    monkeypatch.setattr(store, "day_file", lambda _: tmp_path / "cat.jsonl")
    monkeypatch.setattr(store, "legacy_day_file", lambda *_: tmp_path / "legacy.jsonl")
    result = h._execute(SimpleNamespace(source="scalp", max_tickers=5, apply=False, on_list_advance=False))
    assert researched == ["AAA", "BBB"]
    assert result["focus_gate_mode"] == "shadow" and result["focus_gate_applied"] is False
    assert result["focus_gate_skipped"] == 0 and result["focus_gate_would_skip"] == 1
    assert "[focus SHADOW] candidates unchanged" in capsys.readouterr().out


@pytest.mark.parametrize("mapping", [{}, {"mode": "unknown"}, {"mode": None}])
def test_absent_or_unknown_focus_mode_never_promotes(mapping):
    assert sf.FocusConfig.from_mapping(mapping).mode == "shadow"


def test_candidate_flags_are_shadow_and_rth_sender_is_preserved():
    doc = yaml.safe_load((ROOT / "config/scalp_signal_engine.yaml").read_text())
    assert doc["active_trader_premarket"]["mode"] == "shadow"
    assert doc["active_trader_premarket"]["cadence_mode"] == "shadow"
    assert doc["scalp_focus"]["mode"] == "shadow"
    assert doc["unified_momentum_alert"]["mode"] == "shadow"
    assert doc["active_trader_alerts"]["mode"] == "send"


def test_shadow_cadence_with_injected_legacy_send_and_unified_live_sends_no_new_alert(tmp_path):
    ledger = um.Ledger(tmp_path / "ledger.jsonl")

    def forbidden_send(*args, **kwargs):
        pytest.fail("SHADOW must never call a new or fallback transport")

    results, _ = play(tmp_path, cfg=pw.PremarketConfig(mode="send", cadence_mode="shadow"), ledger=ledger,
                      unified_mode="live", send=forbidden_send, fallback=forbidden_send, upto=4)
    assert {r["mode"] for r in ledger.rows(DAY)} == {"shadow"}
    assert len(ledger.rows(DAY)) == 4
    assert all(r["action"] == "SHADOW_LOGGED" for r in ledger.rows(DAY))
    assert all(r["plan"]["emit_mode"] == "shadow" for r in results)
    assert all(r["focus"]["mode"] == "shadow" for r in results)


def test_focus_observation_round_trip_retains_shadow_mode(tmp_path):
    state, events = sf.update(None, [], now=ts("08:00"), cfg=sf.FocusConfig(mode="shadow"))
    path = tmp_path / "focus.json"
    sf.save(state, events, day=DAY, path=path)
    observed = sf.read_focus(path=path, now=ts("08:00", 6))
    assert observed["status"] == "ok" and observed["mode"] == "shadow"


def test_one_minute_dry_run_has_no_file_or_transport_effects(tmp_path):
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    ledger = um.MemoryLedger()

    def forbidden_send(*args, **kwargs):
        pytest.fail("Dry run must never reach a transport")

    result = pw.evaluate_1m(
        [{"symbol": "AAA", "float_mm": 5, "rvol": 12}], data=FakeData({"AAA": base_bars()}),
        cfg=pw.PremarketConfig(mode="send", cadence_mode="shadow"), fcfg=sf.FocusConfig(mode="shadow"),
        boundary=ts("08:00"), now=ts("08:00", 6), day=DAY, persist=False, recorder=FakeRecorder(),
        evidence_loader=lambda: None, unified_mode="live", ledger=ledger, send=forbidden_send,
        fallback_send=forbidden_send, catalyst_lookup=lambda *_: {}, lifecycle_path=tmp_path / "life.json",
        focus_path=tmp_path / "focus.json", focus_events_path=tmp_path / "events.jsonl",
        journal_path=tmp_path / "journal.jsonl")
    assert result["plan"]["emit_mode"] == "shadow"
    assert len(ledger.rows(DAY)) == 1 and ledger.rows(DAY)[0]["action"] == "SHADOW_LOGGED"
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == before
