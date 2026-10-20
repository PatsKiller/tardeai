"""Transitive capabilities of n8n-allowlisted lanes (third-party audit finding B / DD01, 2026-10-15).

scripts/audit_lane_transitive_capabilities.py walks each lane's repo-local import closure (AST, lazy imports
included; stops at the approved delivery chokepoints) and flags direct_sender / broker_module / order_placement
(FORBIDDEN) plus db_write / subprocess / network_http / chokepoint_send (review only).

This test fails when:
  * an allowlisted lane (new or existing) reaches a FORBIDDEN capability that config/n8n_lane_capability_baseline.json
    does not list with a non-empty reason;
  * a baseline entry is no longer reached (shrink the baseline: it only ever shrinks);
  * the baseline holds a (lane, capability) pair outside FROZEN_20261015 below. Adding a pair therefore needs an edit
    to THIS test, which a reviewer sees, not only a config edit.
Plus unit proofs of the detector on synthetic modules (tmp_path; nothing in the repo is executed).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_lane_transitive_capabilities as cap  # noqa: E402

#: OPERATOR RULING 2026-10-15 (verbatim: "n8n ignor broker code it can't trade live ccontinue"; DD01 operator-reviewed
#: baseline entry, agreed with the Chief Architect): TRANSITIVE lazy reach to broker_module / order_placement (the
#: chain db_adapter -> holdings_guard -> schwab_position_sync -> schwab_transport) is ACCEPTED for these
#: n8n-allowlisted lanes, because the trading lock (scripts/lib/trading_lock.py assert_trading_unlocked, the first
#: statement of schwab_transport.place_order; LOCKED by default, operator unlock file) refuses every order placement
#: whatever the caller. It admits broker_module/order_placement ONLY: direct_sender stays forbidden with no exception.
#: Train 2026-10-15 d had deferred the first four; #1761 (shadow wave LD-W1) adds the last two.
OPERATOR_RULING_DD01_20261015 = frozenset(
    {
        "build-symbol-profiles-at-0-19",
        "indicator-engine",
        "watchlist-entry-planner-limit",
        "watchlist-entry-planner-scope",
        "hermes-discovery-scorecard",
        "wire-advisory-lessons",
    }
)
OPERATOR_RULING_DD01_REASON = (
    'operator ruling 2026-10-15 (verbatim: "n8n ignor broker code it can\'t trade live ccontinue"): transitive lazy '
    "broker reach accepted; trading lock refuses every order; direct_sender remains forbidden"
)

#: 2026-10-18 data-integrity fix PR (operator-approved; the two data monitors "within n8n with proper contracts"): the
#: n8n entries of scripts/data_plausibility_monitor.py and scripts/check_gap_resolution.py reach broker_module /
#: order_placement only through the same LAZY shared chains as heartbeat-watch (host_comms_intents ->
#: n8n_coordination_gateway -> ... -> schwab_instrument_evidence; gap_resolver -> cio_operator_desk_loop -> ...).
#: Read-only monitors; no direct_sender (the n8n entry scripts never reference the chokepoint; the dispatcher sender
#: gate tests/test_agents_policy_7_0_0_advisory_market_data.py stays green). Reviewed addition, not a ruling widening.
DATA_INTEGRITY_MONITORS_20261018 = frozenset({"n8n-data-plausibility-audit", "n8n-gap-resolution-audit"})

FROZEN_20261015 = {
    "broker_module": frozenset(
        {
            "advisory-desk-run-now",
            "aegis-brief-regenerate",
            "aegis-evening-packet",
            "aegis-nightly-ingestion",
            "aegis-social-sentiment",
            "aegis-transcript-discovery",
            "analyst-prospectus-generate",
            "audit-enrichment-coverage",
            "catalyst-graph",
            "catalyst-momentum-engine-overnight",
            "catalyst-symbol-impact",
            "classify-instruments",
            "data-gap-resolver-at-0-10-16",
            "data-gap-resolver-pre",
            "data-gap-resolver-weekly",
            "desk-suggestions-digest",
            "document-mentions-backfill",
            "enterprise-backtester",
            "etf-analyst-enrich",
            "etf-performance-enrich",
            "fee-efficiency-analyzer",
            "feedback-loop-processor",
            "finviz-enrichment",
            "finviz-enrichment-scalp-hot",
            "finviz-market-movers",
            "finviz-proactive-research",
            "finviz-screener-runner",
            "finviz-sector-research",
            "finviz-view-contracts",
            "generate-analyst-daily-digest",
            "heartbeat-watch",
            "hermes-analyst-signal-discovery",
            "hermes-entity-spike-discovery",
            "hermes-governance-api",
            "hermes-learning-autonomous-self-tune",
            "hermes-learning-config-governor",
            "hermes-learning-outcome-feedback-agent",
            "hermes-learning-outcome-grader",
            "hermes-learning-outcome-learning",
            "hermes-learning-tag-engine",
            "hermes-momentum-catalyst-scalp",
            "hermes-pipeline-health",
            "hermes-research-worker-pool",
            "hermes-scope-governor",
            "hermes-score-event-feeder",
            "hermes-social-sentiment",
            "instrument-belief-writer",
            "investment-costs",
            "job-coverage-monitor",
            "journal-tilt-morning-hook",
            "lane-governance-packet-weekly",
            "material-change-detector-stage1",
            "momentum-cache-reconcile",
            "momentum-lifecycle-monitor",
            "n8n-incident-fanin",
            "n8n-research-intake-consumer",
            "news-to-catalyst",
            "scalp-hot-list",
            "sector-rs-daily",
            "signal-fusion-active",
            "signal-fusion-full",
            "social-ingest-all",
            "sync-social-to-intelligence",
            "trade-ai-scalp-live",
            "update-agent-performance",
            "validate-expense-ratios",
            "watch-goods-consistency",
            "watchlist-enrichment-sweep",
        }
    )
    | OPERATOR_RULING_DD01_20261015
    | DATA_INTEGRITY_MONITORS_20261018,
    # 2026-10-15: trade-ai-scalp-live removed (DD01 fix, delivery only through send_telegram). Empty: no lane may
    # reach a direct sender.
    "direct_sender": frozenset(),
    "order_placement": frozenset(
        {
            "advisory-desk-run-now",
            "aegis-brief-regenerate",
            "aegis-evening-packet",
            "aegis-nightly-ingestion",
            "aegis-social-sentiment",
            "aegis-transcript-discovery",
            "analyst-prospectus-generate",
            "audit-enrichment-coverage",
            "catalyst-graph",
            "catalyst-momentum-engine-overnight",
            "catalyst-symbol-impact",
            "classify-instruments",
            "data-gap-resolver-at-0-10-16",
            "data-gap-resolver-pre",
            "data-gap-resolver-weekly",
            "desk-suggestions-digest",
            "enterprise-backtester",
            "etf-analyst-enrich",
            "etf-performance-enrich",
            "fee-efficiency-analyzer",
            "feedback-loop-processor",
            "finviz-enrichment",
            "finviz-enrichment-scalp-hot",
            "finviz-market-movers",
            "finviz-proactive-research",
            "finviz-screener-runner",
            "finviz-sector-research",
            "finviz-view-contracts",
            "generate-analyst-daily-digest",
            "heartbeat-watch",
            "hermes-analyst-signal-discovery",
            "hermes-entity-spike-discovery",
            "hermes-governance-api",
            "hermes-learning-autonomous-self-tune",
            "hermes-learning-config-governor",
            "hermes-learning-outcome-feedback-agent",
            "hermes-learning-outcome-grader",
            "hermes-learning-outcome-learning",
            "hermes-learning-tag-engine",
            "hermes-momentum-catalyst-scalp",
            "hermes-pipeline-health",
            "hermes-research-worker-pool",
            "hermes-scope-governor",
            "hermes-score-event-feeder",
            "hermes-social-sentiment",
            "instrument-belief-writer",
            "investment-costs",
            "job-coverage-monitor",
            "journal-tilt-morning-hook",
            "lane-governance-packet-weekly",
            "material-change-detector-stage1",
            "momentum-cache-reconcile",
            "momentum-lifecycle-monitor",
            "n8n-incident-fanin",
            "n8n-research-intake-consumer",
            "news-to-catalyst",
            "scalp-hot-list",
            "sector-rs-daily",
            "signal-fusion-active",
            "signal-fusion-full",
            "social-ingest-all",
            "sync-social-to-intelligence",
            "trade-ai-scalp-live",
            "update-agent-performance",
            "validate-expense-ratios",
            "watch-goods-consistency",
            "watchlist-enrichment-sweep",
        }
    )
    | OPERATOR_RULING_DD01_20261015
    | DATA_INTEGRITY_MONITORS_20261018,
}


@pytest.fixture(scope="module")
def result():
    return cap.audit()


def test_every_allowlisted_lane_is_audited(result):
    lanes = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))["lanes"]
    assert set(result) == {str(r["lane_id"]) for r in lanes}
    assert not [lid for lid, row in result.items() if row.get("error")], "entry script not found"


def test_no_unbaselined_forbidden_capability_and_no_stale_entry(result):
    v = cap.violations(result, cap.load_baseline())
    assert v["new"] == [], (
        "NEW forbidden capability (route via the chokepoint / drop the import, or justify in the "
        "baseline AND the frozen set here): " + json.dumps(v["new"])[:2000]
    )
    assert v["stale"] == [], "baseline entry no longer reached; delete it (shrink-only): " + json.dumps(v["stale"])


def test_baseline_only_shrinks_and_every_entry_has_a_reason():
    base = cap.load_baseline()
    for lid, caps in base.items():
        for c, reason in caps.items():
            assert c in cap.FORBIDDEN, (lid, c)
            assert lid in FROZEN_20261015.get(c, frozenset()), f"baseline grew: {lid} {c} is not in FROZEN_20261015"
            assert len(reason.strip()) >= 40, (lid, c)


def test_operator_ruling_dd01_entries_are_exactly_the_ruled_pairs(result):
    """The 2026-10-15 operator ruling admits transitive, lazy broker_module/order_placement reach only: each ruled
    lane's baseline entry is exactly those two capabilities with the ruling's reason, the reach is not at import, and
    no ruled lane reaches (or may baseline) a direct sender."""
    base = cap.load_baseline()
    for lid in sorted(OPERATOR_RULING_DD01_20261015):
        assert set(base.get(lid, {})) == {"broker_module", "order_placement"}, lid
        assert all(r == OPERATOR_RULING_DD01_REASON for r in base[lid].values()), lid
        caps = result[lid]["capabilities"]
        assert "direct_sender" not in caps, lid
        for c in ("broker_module", "order_placement"):
            assert c in caps and caps[c]["at_import"] is False, (lid, c)
    assert FROZEN_20261015["direct_sender"] == frozenset()


def test_no_forbidden_capability_is_loaded_at_import_time(result):
    eager = sorted(
        (lid, c)
        for lid, row in result.items()
        for c in cap.FORBIDDEN
        if (row["capabilities"].get(c) or {}).get("at_import")
    )
    assert eager == [], eager


def test_no_lane_reaches_a_direct_sender(result):
    """DD01 closed 2026-10-15: the scalp lane's continuous_runner -> alerting path is gone; no lane reaches one."""
    assert [lid for lid, row in result.items() if "direct_sender" in row["capabilities"]] == []
    assert "chokepoint_send" in result["trade-ai-scalp-live"]["capabilities"]


# ── detector unit proofs on synthetic trees ───────────────────────────────────────────────────────────────────────


def _tree(tmp_path: Path, files: dict[str, str], lanes: list[dict]) -> tuple[Path, cap.Resolver]:
    for rel, src in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"lanes": lanes}), encoding="utf-8")
    return allow, cap.Resolver(tmp_path)


def _rel_patch(monkeypatch, tmp_path):
    monkeypatch.setattr(cap, "ROOT", tmp_path)


def test_detector_flags_lazy_sender_and_order_with_chain(tmp_path, monkeypatch):
    _rel_patch(monkeypatch, tmp_path)
    allow, res = _tree(
        tmp_path,
        {
            "scripts/lane.py": "import helper\n",
            "scripts/helper.py": "def go():\n    from notify import ping\n    ping()\n",
            "scripts/notify.py": "import requests\nURL = 'https://hooks.slack.com/services/x'\n",
            "scripts/lib/schwab_thing.py": "def place_order(x):\n    return x\n",
            "scripts/other.py": "from lib import schwab_thing\n",
        },
        [
            {"lane_id": "a", "command": ["$PY", "scripts/lane.py"]},
            {"lane_id": "b", "command": ["$PY", "scripts/other.py"]},
            {"lane_id": "c", "command": ["bash", "-c", "true"]},
        ],
    )
    r = cap.audit(allow, res)
    a = r["a"]["capabilities"]["direct_sender"]
    assert a["chain"] == ["scripts/lane.py", "scripts/helper.py", "scripts/notify.py"] and a["at_import"] is False
    assert set(r["b"]["capabilities"]) >= {"broker_module", "order_placement"}
    assert r["b"]["capabilities"]["order_placement"]["at_import"] is True
    assert list(r["c"]["capabilities"]) == ["subprocess"]
    v = cap.violations(r, {"a": {"direct_sender": "x" * 50}, "z": {"broker_module": "gone"}})
    assert {(x[0], x[1]) for x in v["new"]} == {("b", "broker_module"), ("b", "order_placement")}
    assert v["stale"] == [["z", "broker_module"]]


def test_detector_stops_at_chokepoint_and_ignores_docstrings_and_tooling(tmp_path, monkeypatch):
    _rel_patch(monkeypatch, tmp_path)
    allow, res = _tree(
        tmp_path,
        {
            "scripts/lane.py": '"""mentions https://api.telegram.org/bot<token>/sendMessage in prose"""\n'
            "import telegram_alert\nimport secret_validators\n"
            "from telegram_transport import escape_markdown\n",
            "scripts/telegram_alert.py": "import smtplib\nimport telegram_transport\n",
            "scripts/telegram_transport.py": "API = 'https://api.telegram.org/bot{t}/sendMessage'\n",
            "scripts/secret_validators.py": "import requests\nX = 'https://api.telegram.org/bot{k}/getMe'\n",
        },
        [{"lane_id": "a", "command": ["$PY", "scripts/lane.py"]}],
    )
    r = cap.audit(allow, res)["a"]["capabilities"]
    assert "direct_sender" not in r and "chokepoint_send" in r


def test_transport_send_import_is_a_bypass(tmp_path, monkeypatch):
    _rel_patch(monkeypatch, tmp_path)
    allow, res = _tree(
        tmp_path,
        {
            "scripts/lane.py": "def f():\n    from telegram_transport import send_message\n",
            "scripts/telegram_transport.py": "pass\n",
        },
        [{"lane_id": "a", "command": ["$PY", "scripts/lane.py"]}],
    )
    r = cap.audit(allow, res)["a"]["capabilities"]
    assert "direct_sender" in r and "telegram_transport" in r["direct_sender"]["evidence"]
