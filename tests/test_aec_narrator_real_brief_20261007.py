"""AEC Executive Brief — real content, Command Center only (operator 2026-10-07).

The hourly brief went to Telegram 400 times in 17 days printing memory-row labels ("cio_cycle_status" x5, "cycle
touch" x5, "commitment_outcome" x3); its fingerprint included the timestamp so nothing was ever a repeat.
Fakes only: no network, no database, no Telegram.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import aec_narrator as narr  # noqa: E402
from scripts.lib import aec_memory_spines as mem  # noqa: E402

NOW = datetime(2026, 10, 7, 21, 0, tzinfo=timezone.utc)
SNAP = {"computed_at": "2026-10-07T20:45:00+00:00",
        "totals": {"total_value": 1265855.31, "day_change": -4622.09, "day_change_pct": -0.364},
        "account_states": {"accounts": {"alpaca_taxable_live": {"state": "LIVE"},
                                        "moomoo_taxable_live": {"state": "STALE"},
                                        "fidelity_rollover_ira": {"state": "NO_API_MANUAL"}}}}
HEALTH = {"overall_score": 86, "status": "healthy", "captured_at": "2026-10-07T20:58:00+00:00",
          "findings": [{"severity": "warning", "type": "x"}, {"severity": "critical", "type": "portfolio_stale_marks"}]}
PROOF = [{"date": "2026-10-07", "pass": True, "checks": {"runs": {"ok": True}}}]
SYNC = {"last_complete": "2026-10-07T20:54:00+00:00", "age_s": 360.0, "limit_s": 1800.0, "stale": False}
SOURCES = {"portfolio": lambda: SNAP, "health": lambda: HEALTH, "proof": lambda: PROOF, "sync": lambda: SYNC}
LABELS = ("cio_cycle_status", "cycle touch", "commitment_outcome", "thesis_touch")


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_AEC_BUS", str(tmp_path / "bus.jsonl"))
    monkeypatch.setenv("TRADEAI_AEC_MEMORY", str(tmp_path / "mem.json"))
    for i in range(5):
        mem.append_fact("operational", {"kind": "cio_cycle_status"}, path=tmp_path / "mem.json")
        mem.append_fact("strategic", {"kind": "thesis_touch", "note": "cycle touch"}, path=tmp_path / "mem.json")
    for o in ("INSUFFICIENT_EVIDENCE", "EXPIRED", "INSUFFICIENT_EVIDENCE"):
        mem.append_fact("learning", {"kind": "commitment_outcome", "outcome": o,
                                     "recorded_at": "2026-10-07T20:00:00Z"}, path=tmp_path / "mem.json")
    return tmp_path


def test_brief_states_facts_not_labels(stores):
    b = narr.render_executive_brief(sources=SOURCES, now=NOW)["body"]
    assert "Value $1,265,855 · today −$4,622 (-0.36%)" in b
    assert "moomoo_taxable_live STALE" in b and "fidelity_rollover_ira" not in b
    assert "1 critical" in b and "portfolio_stale_marks" in b
    assert "Proof 2026-10-07: PASS · day 1 of 10" in b
    assert "3 settled in 24 h · 0 with evidence" in b
    for label in LABELS:
        assert label not in b
    content = [l for l in b.splitlines() if l.startswith("- ")]
    assert len(content) == len(set(content))                   # no duplicate lines
    assert "Relationships" not in b and "Why:" not in b


def test_fingerprint_ignores_the_render_time(stores):
    a = narr.render_executive_brief(sources=SOURCES, now=NOW)
    b = narr.render_executive_brief(sources=SOURCES, now=NOW + timedelta(minutes=37))
    assert a["claim_fp"] == b["claim_fp"] and a["as_of"] != b["as_of"]


def test_a_missing_source_says_unavailable(stores):
    b = narr.render_executive_brief(sources={k: (lambda: None) for k in SOURCES}, now=NOW)["body"]
    assert "unavailable (data_broker/portfolio_snapshot.json)" in b
    assert "unavailable (data/portfolios/state/health_agent_status.json)" in b


def test_a_failing_source_is_unavailable_not_a_crash(stores):
    def boom():
        raise RuntimeError("db down")
    b = narr.render_executive_brief(sources=dict(SOURCES, sync=boom), now=NOW)["body"]
    assert "Sync freshness unavailable" in b


def test_telegram_is_off_by_config():
    assert narr.load_config()["telegram"] is False


def test_cycle_never_sends_with_config_off(stores, monkeypatch, alarm_capture):
    monkeypatch.setenv("AEC_NARRATOR_NOTIFY", "1")                 # the env var alone used to send hourly
    import importlib.util
    spec = importlib.util.spec_from_file_location("aec_cycle_cfg_off", ROOT / "scripts" / "aec_command_center_cycle.py")
    cycle = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = cycle
    spec.loader.exec_module(cycle)
    monkeypatch.setattr(narr, "SOURCES", {k: (lambda: None) for k in SOURCES})
    out = cycle.run_cycle(subject_key=None, apply=False)          # never apply in a test: no durable writes
    assert out["narrator_notify"]["telegram"] == "disabled_by_config"
    assert not alarm_capture.fired
    ev = next(e for e in out["events"] if e.get("topic") == "cycle.narrator.brief")
    assert ev["payload"]["body"].startswith("Trade AI — Executive Brief") and ev["payload"]["reason"] == "command_center_only"
    src = (ROOT / "scripts" / "aec_command_center_cycle.py").read_text()
    assert "_narr_notify = _narr_env and _narr_cfg_on" in src      # env alone can never send again


def test_command_payload_reads_the_latest_brief_from_the_bus_tail(tmp_path, monkeypatch):
    bus = tmp_path / "bus.jsonl"
    as_of = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [{"topic": "cycle.cio", "payload": {}},
            {"topic": "cycle.narrator.brief", "as_of": as_of, "payload": {"body": "old", "as_of": "2026-10-01T00:00:00Z"}},
            {"topic": "cycle.narrator.brief", "as_of": as_of, "payload": {"body": "Trade AI — Executive Brief\nnew", "as_of": as_of}}]
    bus.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setenv("TRADEAI_AEC_BUS", str(bus))
    import api_v2
    eb = api_v2._latest_executive_brief()
    assert eb["body"].endswith("new") and eb["stale"] is False and 200 < eb["age_s"] < 400
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    assert '"executive_brief": _latest_executive_brief(),' in src
