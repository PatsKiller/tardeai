"""Shadow wave 4 (SW4, 2026-10-11): 15 R1 lanes (10 ingest, 5 learn) on the dispatcher in SHADOW.

COVERS = ["config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json"]

AGENTS 4.4.0 cron-row shadow shape (scheduler.kind cron + stage shadow, dispatch.mode dry_run, allowlist live_arg null),
§23.18 R1 gate, §23.19 onboarding (REVIEWED contract). The dispatcher fires only each lane's write-free dry run on the
natural schedule; the cron line keeps doing the real work.

Pinned so a later PR cannot slip them in unreviewed (one reason each):
* premarket C1 stage steps (retired into premarket-data-pipeline by the open C1 PR): fred-data-ingest,
  sync-dividend-data, build-lesson-candidates, candidate-discovery-orchestrator, research-watchlist-discovery,
  market-regime-collector;
* agent-recommendation-normalizer: P0 duplicate rows (random recommendation_id per run);
* rag-indexer, journal-review-builder: llm class with an in-process model call (not the governed bridge);
* build-symbol-profiles-at-0-19: its receipt is build_symbol_profiles_last.json, shared with refresh_symbol_cards;
* social-ingest-stocktwits: consolidation merges it into the social owner (CONSOLIDATION_PLAN §B.2), and its match
  also hits L639;
* cio-stance-classification-drain, siem-to-hermes-backlog, desk-suggestions-digest, build-hermes-canonical-status,
  hermes-discovery-scorecard, drain-discovery-backlog: class is not ingest/llm/learn.
Hermetic: repo config read only.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
CONTRACTS = {c["id"]: c for c in json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())["contracts"]}
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")

#: lane -> (class, live cron schedule, dispatcher argv after $PY, receipt stem, cron flock lock or None)
SW4 = {
    "record-decision-outcome": ("learn", "50 7 * * 1-5", ["scripts/record_decision_outcome.py"], "record-decision-outcome", None),
    "update-lockup-earnings-dates": ("ingest", "18 8 * * *", ["scripts/update_lockup_earnings_dates.py"],
                                     "update_lockup_earnings_dates", "/tmp/lockup_earnings.lock"),
    "etf-analyst-enrich": ("ingest", "0 7 * * 6", ["scripts/etf_analyst_enrich.py"], "etf-analyst-enrich", "/tmp/etf_analyst.lock"),
    "hermes-tag-lift-discovery": ("learn", "50 3 * * *", ["scripts/hermes_tag_lift_discovery.py", "--run", "--json"],
                                  "hermes-tag-lift-discovery", "/tmp/hermes_tag_lift.lock"),
    "agent-outcome-scorer": ("learn", "0 11 * * 0", ["scripts/agent_outcome_scorer.py"], "agent-outcome-scorer", None),
    "validate-expense-ratios": ("ingest", "40 7 1 * *", ["scripts/validate_expense_ratios.py"], "validate-expense-ratios",
                                "/tmp/expense_ratio_validate.lock"),
    "identity-sweep-stage0": ("ingest", "*/30 * * * *", ["scripts/backfill_subject_identity.py", "--all"],
                              "identity-sweep-stage0", "/tmp/identity_sweep.lock"),
    "feedback-loop-processor": ("learn", "30 20 * * 1-5", ["scripts/feedback_loop_processor.py"], "feedback-loop-processor",
                                "/tmp/feedback_loop.lock"),
    "aegis-social-sentiment": ("ingest", "0 11,15 * * 1-5", ["scripts/aegis_social_sentiment.py"], "aegis-social-sentiment", None),
    "aegis-transcript-discovery": ("ingest", "0 9 * * 1-5", ["scripts/aegis_transcript_discovery.py"],
                                   "aegis-transcript-discovery", None),
    "aegis-nightly-ingestion": ("ingest", "0 19 * * *", ["scripts/aegis_nightly_ingestion.py"], "aegis-nightly-ingestion", None),
    "hermes-social-sentiment": ("ingest", "15 11,15 * * 1-5", ["scripts/hermes_social_sentiment.py"], "hermes-social-sentiment", None),
    "sync-social-to-intelligence": ("ingest", "30 11,15 * * 1-5", ["scripts/sync_social_to_intelligence.py"],
                                    "sync-social-to-intelligence", None),
    "trade-backtest-engine": ("learn", "30 18 * * 1-5", ["scripts/trade_backtest_engine.py"], "trade_backtest_engine",
                              "/tmp/trade_backtest_engine.lock"),
    "etf-performance-enrich": ("ingest", "15 7 * * 6", ["scripts/etf_performance_enrich.py"], "etf-performance-enrich",
                               "/tmp/etf_perf.lock"),
}

EXCLUDED = (
    "fred-data-ingest", "sync-dividend-data", "build-lesson-candidates", "candidate-discovery-orchestrator",
    "research-watchlist-discovery", "market-regime-collector", "agent-recommendation-normalizer", "rag-indexer",
    "journal-review-builder", "build-symbol-profiles-at-0-19", "social-ingest-stocktwits",
    "cio-stance-classification-drain", "siem-to-hermes-backlog", "desk-suggestions-digest",
    "build-hermes-canonical-status", "hermes-discovery-scorecard", "drain-discovery-backlog",
)


def test_counts():
    assert len(SW4) == 15
    assert sum(1 for v in SW4.values() if v[0] == "ingest") == 10
    assert sum(1 for v in SW4.values() if v[0] == "learn") == 5


@pytest.mark.parametrize("lane", sorted(SW4))
def test_row_is_a_w4_shadow_cron_row_admitted_by_the_r1_gate(lane):
    klass, cron, _argv, receipt, _lock = SW4[lane]
    row = ROWS[lane]
    s = row["scheduler"]
    assert s["kind"] == "cron" and s["stage"] == "shadow" and s["wave"] == "W4" and s["expression"] == cron
    assert row["state"] == "ACTIVE" and "generated_by" not in row
    assert row["dispatch"] == {"mode": "dry_run", "cron": [cron], "tz": "America/New_York", "wave": "W4",
                               "class": klass, "priority": 5, "retry_policy": "none"}
    assert row["output_signal"] == {"kind": "json_key", "path": f"data/runtime/{receipt}_last.json", "key": "ok_at"}
    assert LD.validate_dispatch_block(row) == []
    assert LD.dispatch_eligible(row) == (True, "eligible")
    assert LD.r1_class_admission(row) == (True, f"r1_admitted:{klass}")
    ok, why = LD.r1_class_admission(row, ALLOW[lane], shadow_shape_status="PROPOSED")
    assert not ok and why.startswith("shadow_on_cron_not_ratified"), why


@pytest.mark.parametrize("lane", sorted(SW4))
def test_allowlist_entry_is_shadow_only_and_carries_no_broker_credential(lane):
    _klass, _cron, argv, receipt, cron_lock = SW4[lane]
    e = ALLOW[lane]
    assert e["command"] == ["$PY", *argv]
    assert e["live_arg"] is None and e["dry_run_arg"][0] == "--dry-run"
    assert not any(t.startswith("--apply") for t in e["command"] + e["dry_run_arg"])
    assert e["output_signal"] == ROWS[lane]["output_signal"]["path"] == f"data/runtime/{receipt}_last.json"
    assert LD.receipt_signal_path(ROWS[lane]) == e["output_signal"]
    assert e["env_allowlist_mode"] == "report" and e["env_report_reason"]
    for name in e["env_names"]:
        assert not any(f in name.upper() for f in LD.BROKER_CREDENTIAL_ENV_FRAGMENTS), (lane, name)
    assert LD.forbidden_text_hits(" ".join(e["command"] + e["dry_run_arg"])) == []
    assert e["market_gate"] is False and 0 < e["timeout_s"] <= 1200
    text = ROWS[lane]["scheduler"]["command_text"]
    if cron_lock:
        assert e["lock"] == cron_lock and cron_lock in text
    else:
        assert "PROPOSED" in e["source"] and e["lock"] in e["source"] and e["lock"] not in text


def test_flock_lanes_are_canary_lock_equivalent_and_the_rest_stay_blocked():
    for lane, (_k, _c, _a, _r, cron_lock) in SW4.items():
        e = ALLOW[lane]
        canary = json.loads(json.dumps(ROWS[lane]))
        canary["scheduler"]["stage"] = "canary"
        canary["dispatch"]["mode"] = "live"
        ok, why = LD.r1_canary_lock_matches(canary, dict(e, live_arg=[]))
        if cron_lock and e["lock_kind"] == "flock":
            assert ok, (lane, why)
        else:
            assert not ok, (lane, why)


def test_the_script_writes_the_receipt_the_row_names():
    for lane, (_k, _c, argv, receipt, _l) in SW4.items():
        src = (ROOT / argv[0]).read_text(encoding="utf-8")
        assert re.search(r"""['"]%s['"]""" % re.escape(receipt), src), (lane, receipt)
        assert "write_lane_receipt" in src or "write_receipt" in src, lane
        assert re.search(r"""['"]--dry-run['"]""", src), lane


@pytest.mark.parametrize("lane", sorted(SW4))
def test_health_contract_is_reviewed_and_complete(lane):
    c = CONTRACTS[lane]
    assert c["status"] == "REVIEWED" and c["stage"] == "shadow" and c["kind"] == "lane"
    assert H.validate_contract(c) == []
    assert H.unknown_fields(c) == []
    assert not [x for x in c["connects_to"] if x["kind"] == "inventory_text"]
    assert {x["direction"] for x in c["connects_to"]} >= {"read", "write", "calls"}
    assert c["evidence"]["receipt"] == ALLOW[lane]["output_signal"]
    assert c["baseline"]["class"] == SW4[lane][0] and c["baseline"]["timeout_s"] == ALLOW[lane]["timeout_s"]
    assert c["baseline"]["freshness_degraded_after_h"] < c["baseline"]["freshness_failed_after_h"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", c["review_by"])
    assert c["owner"] == ROWS[lane]["owner"]


def test_contract_gate_is_clean_and_sw4_is_not_grandfathered():
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())
    idx = json.loads((ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows" / "INDEX.json").read_text())
    assert H.check(doc, REGISTRY, idx)["errors"] == []
    assert not set(SW4) & set(doc["grandfathered_draft"])


def test_excluded_lanes_stay_off_the_dispatcher():
    for lane in EXCLUDED:
        row = ROWS[lane]
        assert "dispatch" not in row and "r1_pending" not in row, lane
        assert (row.get("scheduler") or {}).get("stage") is None, lane
        # desk-suggestions-digest has a pre-SW4 allowlist entry (non-R1 report wave); no dispatcher row uses it.
        assert lane not in ALLOW or lane == "desk-suggestions-digest", lane


START = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)  # Monday 00:00 America/New_York


def _sweep(rows, start, days, step_min):
    slots: dict[str, set] = {}
    errors = set()
    t = start
    while t < start + timedelta(days=days):
        resp = D.compute_due(rows, ALLOW, POLICIES, None, t)
        for it in resp["items"]:
            assert it["mode"] == "dry_run", it
            slots.setdefault(it["lane_id"], set()).add(it["slot_local"])
        errors |= {(e["lane_id"], e["code"]) for e in resp["errors"]}
        t += timedelta(minutes=step_min)
    return slots, errors


def test_compute_due_week_sweep_emits_dry_run_on_the_natural_slots_only():
    slots, errors = _sweep([ROWS[x] for x in SW4 if x != "identity-sweep-stage0"], START, 7, 5)
    assert errors == set(), sorted(errors)
    want = {"record-decision-outcome": 5, "update-lockup-earnings-dates": 7, "etf-analyst-enrich": 1,
            "hermes-tag-lift-discovery": 7, "agent-outcome-scorer": 1, "feedback-loop-processor": 5,
            "aegis-social-sentiment": 10, "aegis-transcript-discovery": 5, "aegis-nightly-ingestion": 7,
            "hermes-social-sentiment": 10, "sync-social-to-intelligence": 10, "trade-backtest-engine": 5,
            "etf-performance-enrich": 1}
    assert {k: len(v) for k, v in slots.items()} == want
    assert {s[-4:] for s in slots["aegis-social-sentiment"]} == {"1100", "1500"}
    assert {s[:8] for s in slots["agent-outcome-scorer"]} == {"20261018"}  # Sunday


def test_identity_sweep_fires_every_half_hour_dry_run_only():
    slots, errors = _sweep([ROWS["identity-sweep-stage0"]], START, 1, 30)
    assert errors == set() and len(slots["identity-sweep-stage0"]) == 48


def test_monthly_lane_fires_on_the_first_only():
    slots, errors = _sweep([ROWS["validate-expense-ratios"]], datetime(2026, 10, 31, 4, 0, tzinfo=timezone.utc), 2, 10)
    assert errors == set() and slots == {"validate-expense-ratios": {"20261101T0740"}}
