#!/usr/bin/env python3
"""Universal Research Discovery Layer — scheduled-ingest tests (Stage 1).

Covers spec Parts C + L: schedule config schema, do-no-harm steady/tighten/
pause cap behavior, per-domain/per-day caps, operator bypass of pause and caps,
dry-run writing nothing, and the no-broker-imports guarantee.

All tests here are pure/monkeypatched — no DB required (DB-bound intake
behavior is covered by test_hermes_discovery_inbox.py).

    .venv/bin/python -m pytest tests/test_hermes_discovery_schedule.py -q
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_discovery_ingestors as ing  # noqa: E402
from lib.hermes_discovery import domains  # noqa: E402

CONFIG_PATH = ROOT / "config" / "hermes_discovery_schedule.json"

REQUIRED_CONFIG_KEYS = {
    "enabled", "cadence_minutes", "max_candidates_per_run",
    "source_enabled", "trend_enabled", "ticker_enabled", "topic_enabled",
    "entity_spike_enabled", "tag_lift_enabled", "llm_review_enabled",
    "do_no_harm_pause_respected", "paused", "pause_reason",
    "min_cross_source_confirmation", "min_recurrence_count",
    "max_candidates_per_domain_per_day", "max_ticker_candidates_per_day",
    "max_legal_tax_candidates_per_day", "llm_review_daily_cap",
    "cloud_lane_daily_cap", "entity_spike_min_sources", "tag_lift_min_outcomes",
}


def _cfg() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


# ── config schema ────────────────────────────────────────────────────────────

def test_schedule_config_schema():
    cfg = _cfg()
    missing = REQUIRED_CONFIG_KEYS - set(cfg)
    assert not missing, f"schedule config missing keys: {sorted(missing)}"
    assert cfg["enabled"] is True and cfg["paused"] is False
    assert cfg["cadence_minutes"] == 120
    # Lane toggles are OPERATOR-OWNED runtime state, not schema: these lanes
    # shipped disabled but the operator enabled entity_spike/tag_lift on
    # 2026-07-05, so the schema test pins the TYPE (bool), never the value.
    assert isinstance(cfg["entity_spike_enabled"], bool)
    assert isinstance(cfg["tag_lift_enabled"], bool)
    assert isinstance(cfg["llm_review_enabled"], bool)
    assert cfg["do_no_harm_pause_respected"] is True


def test_load_schedule_config_fails_closed_on_missing_file(tmp_path):
    with pytest.raises(Exception):
        ing.load_schedule_config(tmp_path / "nope.json")


# ── do-no-harm cap behavior (monkeypatched scorecard) ────────────────────────

def _scorecard(tmp_path, recommendation: str) -> Path:
    p = tmp_path / "scorecard.json"
    p.write_text(json.dumps({"do_no_harm": {"recommendation": recommendation}}))
    return p


def test_scorecard_recommendation_loading(tmp_path):
    assert ing.load_scorecard_do_no_harm(_scorecard(tmp_path, "tighten")) == "tighten"
    assert ing.load_scorecard_do_no_harm(_scorecard(tmp_path, "pause")) == "pause"
    assert ing.load_scorecard_do_no_harm(_scorecard(tmp_path, "bogus")) == "steady"
    # missing scorecard must not halt intake
    assert ing.load_scorecard_do_no_harm(tmp_path / "absent.json") == "steady"


def test_effective_caps_steady():
    caps = ing.effective_caps(_cfg(), "steady")
    assert caps["paused"] is False
    assert caps["max_candidates_per_run"] == 25
    assert caps["max_candidates_per_domain_per_day"] == 10
    assert caps["max_ticker_candidates_per_day"] == 10
    assert caps["max_legal_tax_candidates_per_day"] == 5
    assert caps["min_recurrence_count"] == 2


def test_effective_caps_tighten_halves_and_raises_recurrence():
    caps = ing.effective_caps(_cfg(), "tighten")
    assert caps["paused"] is False
    assert caps["max_candidates_per_run"] == 12
    assert caps["max_candidates_per_domain_per_day"] == 5
    assert caps["max_ticker_candidates_per_day"] == 5
    assert caps["max_legal_tax_candidates_per_day"] == 2
    assert caps["min_recurrence_count"] == 3  # raised by 1


def test_effective_caps_pause():
    caps = ing.effective_caps(_cfg(), "pause")
    assert caps["paused"] is True
    assert "do_no_harm" in (caps["pause_reason"] or "")


def test_effective_caps_pause_not_respected_when_config_says_so():
    cfg = dict(_cfg(), do_no_harm_pause_respected=False)
    caps = ing.effective_caps(cfg, "pause")
    assert caps["paused"] is False


def test_config_paused_or_disabled_forces_pause():
    assert ing.effective_caps(dict(_cfg(), paused=True), "steady")["paused"] is True
    assert ing.effective_caps(dict(_cfg(), enabled=False), "steady")["paused"] is True


# ── run_scheduled behavior ───────────────────────────────────────────────────

def test_run_scheduled_pause_skips_all_intake(tmp_path, monkeypatch, capsys):
    """pause → no ingestor runs, no upsert, no Telegram; logged once."""
    called = {"telegram": 0}
    monkeypatch.setattr(ing, "_critical_alert",
                        lambda msg, dry_run: called.__setitem__("telegram",
                                                                called["telegram"] + 1))
    for name in ing.INGESTORS:
        monkeypatch.setitem(ing.INGESTORS, name,
                            lambda **kw: pytest.fail("ingestor ran during pause"))
    report = ing.run_scheduled(dry_run=True,
                               scorecard_path=_scorecard(tmp_path, "pause"))
    assert report["mode"] == "scheduled"
    assert report["do_no_harm"] == "pause"
    assert report["caps_applied"]["paused"] is True
    assert report["skipped_reasons"] == {"paused": 1}
    assert report["by_type_counts"] == {}
    assert called["telegram"] == 0  # pause is quiet by design
    assert "paused" in capsys.readouterr().err


def test_run_scheduled_steady_runs_enabled_ingestors(tmp_path, monkeypatch):
    seen = {}

    def fake_ingestor(**kw):
        seen.setdefault("kwargs", kw)
        return {"scanned": 3, "upserted": 2, "skipped": 1, "dry_run": True,
                "candidates": [], "skipped_reasons": {}}

    monkeypatch.setattr(ing, "_domain_counts_today",
                        lambda: {"by_domain": {}, "ticker": 0, "legal_tax": 0})
    for name in ing.INGESTORS:
        monkeypatch.setitem(ing.INGESTORS, name, fake_ingestor)
    report = ing.run_scheduled(dry_run=True,
                               scorecard_path=_scorecard(tmp_path, "steady"))
    assert report["do_no_harm"] == "steady"
    assert set(report["by_type_counts"]) == {"source", "trend", "ticker", "topic"}
    for res in report["by_type_counts"].values():
        assert res == {"scanned": 3, "upserted": 2, "skipped": 1}
    assert callable(seen["kwargs"]["gate"])  # caps gate handed to every ingestor
    assert report["suggested_cron"].startswith("0 */2 * * *")
    assert "--scheduled" in report["suggested_cron"]
    assert "flock -n /tmp/hermes_discovery_ingest.lock" in report["suggested_cron"]


def test_run_scheduled_tighten_passes_raised_recurrence(tmp_path, monkeypatch):
    captured = {}

    def fake_ticker(**kw):
        captured.update(kw)
        return {"scanned": 0, "upserted": 0, "skipped": 0, "candidates": []}

    monkeypatch.setattr(ing, "_domain_counts_today",
                        lambda: {"by_domain": {}, "ticker": 0, "legal_tax": 0})
    for name in ing.INGESTORS:
        monkeypatch.setitem(ing.INGESTORS, name, fake_ticker)
    report = ing.run_scheduled(dry_run=True,
                               scorecard_path=_scorecard(tmp_path, "tighten"))
    assert report["caps_applied"]["min_recurrence_count"] == 3
    assert captured["min_mentions"] == 3  # ticker lane inherits raised floor
    assert captured["limit"] == 12


def test_run_scheduled_broken_config_fails_closed(tmp_path, monkeypatch):
    sent = {"n": 0}
    monkeypatch.setattr(ing, "_critical_alert",
                        lambda msg, dry_run: (sent.__setitem__("n", sent["n"] + 1), False)[1])
    report = ing.run_scheduled(dry_run=False, config_path=tmp_path / "missing.json")
    assert "error" in report
    assert report["by_type_counts"] == {}  # nothing ran
    assert sent["n"] == 1  # exactly one throttled critical alert attempt


# ── intake gate: caps + operator bypass ──────────────────────────────────────

def _steady_gate(skipped, counts=None, **cap_overrides):
    caps = ing.effective_caps(_cfg(), "steady")
    caps.update(cap_overrides)
    return ing.make_intake_gate(
        caps, counts or {"by_domain": {}, "ticker": 0, "legal_tax": 0}, skipped)


def _macro_payload(i=0):
    return {"candidate_type": "TOPIC_CANDIDATE",
            "label": f"fed interest rate path {i}", "meta": {}}


def test_per_domain_daily_cap_enforced():
    skipped: dict[str, int] = {}
    gate = _steady_gate(skipped, max_candidates_per_domain_per_day=2)
    assert gate(_macro_payload(1)) == (True, None)
    assert gate(_macro_payload(2)) == (True, None)
    allowed, reason = gate(_macro_payload(3))
    assert not allowed and reason == "domain_cap:macro"
    assert skipped == {"domain_cap:macro": 1}


def test_domain_cap_counts_todays_existing_rows():
    skipped: dict[str, int] = {}
    gate = _steady_gate(skipped,
                        counts={"by_domain": {"macro": 10}, "ticker": 0, "legal_tax": 0})
    allowed, reason = gate(_macro_payload())
    assert not allowed and reason == "domain_cap:macro"


def test_ticker_and_legal_tax_daily_caps():
    skipped: dict[str, int] = {}
    gate = _steady_gate(skipped,
                        counts={"by_domain": {}, "ticker": 10, "legal_tax": 5})
    allowed, reason = gate({"candidate_type": "TICKER_CANDIDATE", "label": "ZZZZ"})
    assert not allowed and reason == "ticker_cap"
    allowed, reason = gate({"candidate_type": "TOPIC_CANDIDATE",
                            "label": "wash sale tax rules"})
    assert not allowed and reason == "legal_tax_cap"


def test_run_cap_enforced():
    skipped: dict[str, int] = {}
    gate = _steady_gate(skipped, max_candidates_per_run=1)
    assert gate(_macro_payload(1))[0] is True
    allowed, reason = gate(_macro_payload(2))
    assert not allowed and reason == "run_cap"


def test_operator_candidates_bypass_pause_and_caps():
    skipped: dict[str, int] = {}
    caps = ing.effective_caps(dict(_cfg(), paused=True), "pause")
    gate = ing.make_intake_gate(
        caps, {"by_domain": {"macro": 999}, "ticker": 999, "legal_tax": 999}, skipped)
    op = dict(_macro_payload(), is_operator=True)
    assert gate(op) == (True, None)          # operator sails through pause + caps
    assert gate(_macro_payload())[0] is False  # machine intake stays blocked
    assert skipped == {"paused": 1}


# ── dry-run writes nothing ───────────────────────────────────────────────────

def test_dry_run_never_calls_upsert(monkeypatch):
    from lib.hermes_discovery import inbox as inbox_mod
    monkeypatch.setattr(inbox_mod, "upsert_candidate",
                        lambda *a, **k: pytest.fail("dry-run must not write the inbox"))
    monkeypatch.setattr(ing.inbox, "upsert_candidate",
                        lambda *a, **k: pytest.fail("dry-run must not write the inbox"))
    payloads = [dict(candidate_type="TOPIC_CANDIDATE", label="dry run only")]
    out = ing._upsert_all(payloads, actor="pytest", dry_run=True)
    assert out["upserted"] == 0 and out["scanned"] == 1
    assert out["candidates"][0]["label"] == "dry run only"


# ── advisory-only guarantee ──────────────────────────────────────────────────

def test_no_broker_imports_in_discovery_layer():
    forbidden = re.compile(
        r"^\s*(?:import|from)\s+(?:scripts\.)?(?:lib\.)?(brokers\b|schwab\w*|"
        r"alpaca\w*)", re.MULTILINE)
    targets = sorted((ROOT / "scripts" / "lib" / "hermes_discovery").glob("*.py"))
    targets.append(ROOT / "scripts" / "hermes_discovery_ingestors.py")
    offenders = []
    for path in targets:
        m = forbidden.search(path.read_text(encoding="utf-8"))
        if m:
            offenders.append(f"{path.name}: {m.group(0).strip()}")
    assert not offenders, f"broker imports found in advisory-only layer: {offenders}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
