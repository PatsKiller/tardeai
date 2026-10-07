"""Pilot observations from the real producers' shapes (plan tranche B, 2026-10-07).

Fixtures are copies of the served stores' row shapes (LlmSpendReportRun@v1, ResearchCallAccountingEvent@v1,
morning_brief_semantic_state.json, ApprovalReminderReceipt@v1), so the contracts are proven against
the vocabulary the producers actually write, not invented schema names."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts.lib import n8n_pilot_observations as O  # noqa: E402
from scripts.lib.n8n_pilot_contracts import evaluate_pilot  # noqa: E402

KEY = b"k" * 32
SHA = "d" * 40
NOW = dt.datetime(2026, 10, 7, 4, 10, tzinfo=dt.timezone.utc)


def _root(tmp_path: Path) -> Path:
    for d in ("data/cio", "data/runtime"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _eval(lane: str, obs: dict, idem: str) -> dict:
    idem = "idem-" + idem            # the gateway requires idempotency keys of 8+ characters
    now = time.time()
    claim = {"v": 1, "caller_id": "n8n-lab", "project": "trade-ai", "iat": now, "exp": now + 60, "nonce": "nonce-" + idem, "scope": "coordination_read"}
    req = {"claim": claim, "signature": hmac.new(KEY, G.canonical(claim), hashlib.sha256).hexdigest(),
           "route": "coordination/event", "operation": "accept_event",
           "event": O.event_reference(lane, idempotency_key=idem, subject_key="BOOK", artifact_ref=obs.get("source", "x"), now=NOW, origin_sha=SHA)}
    return evaluate_pilot(lane, request=req, observation=obs, key=KEY, now=dt.datetime.fromtimestamp(now, dt.timezone.utc),
                          nonce_store={}, idempotency_store={}, expected_origin_sha=SHA)


def test_llm_spend_maps_cadence_and_usd_and_is_artifact_written(tmp_path):
    root = _root(tmp_path)
    (root / "data/runtime/llm_spend_report_last_daily.json").write_text(json.dumps(
        {"schema": "LlmSpendReportRun@v1", "ran_at": "2026-10-06T11:05:05+00:00", "cadence": "daily", "key": "daily:2026-10-05", "sent": True, "usd": 1.014086}))
    obs = O.llm_spend_daily(root)
    assert obs["period"] == "daily" and obs["amount_usd"] == 1.014086 and obs["adapter_sent"] is True
    r = _eval("llm-spend-report-daily", obs, "spend-1")
    assert r["state"] == "ARTIFACT_WRITTEN" and r["reason"] == "no_consumer_receipt"   # sent != consumed
    assert _eval("llm-spend-report-daily", O.llm_spend_daily(_root(tmp_path / "empty")), "spend-2")["reason"] == "not_daily_digest"


def test_holdings_uses_the_schedulers_own_run_id_or_a_typed_refusal(tmp_path):
    root = _root(tmp_path)
    rows = [
        {"schema": "ResearchCallAccountingEvent@v1", "producer": "research_scheduler", "event": "SCHEDULED", "run_id": "rs:20261007T030501Z:1",
         "call_id": "rc_1", "trigger": "watchlist", "metadata": {"mode": "watchlist"}, "timestamp": "2026-10-07T03:05:01+00:00"},
        {"schema": "ResearchCallAccountingEvent@v1", "producer": "hermes_top20_external_intel", "event": "SKIP_GATED", "run_id": "x",
         "trigger": "top20_external_intel", "metadata": {}, "timestamp": "2026-10-07T03:06:01+00:00"},
    ]
    p = root / "data/cio/research_call_accounting.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    obs = O.holdings_research(root, now=NOW)
    assert obs["mode"] is None and obs["typed_refusal"]["code"] == "no_holdings_run_in_window" and obs["modes_seen"] == ["watchlist"]
    r = _eval("research-scheduler-holdings", obs, "hold-1")
    assert r["state"] == "REFUSED" and r["reason"] == "shared_ledger_not_mode_proof"
    rows.append({"schema": "ResearchCallAccountingEvent@v1", "producer": "research_scheduler", "event": "SCHEDULED", "run_id": "rs:20261007T040501Z:2",
                 "call_id": "rc_2", "trigger": "holdings", "metadata": {"mode": "holdings"}, "timestamp": "2026-10-07T04:05:01+00:00"})
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    obs = O.holdings_research(root, now=NOW)
    assert obs["mode"] == "holdings" and obs["hermes_run_id"] == "rs:20261007T040501Z:2"
    assert _eval("research-scheduler-holdings", obs, "hold-2")["state"] == "ARTIFACT_WRITTEN"
    rows[-1] = {**rows[-1], "event": "SKIP_GATED", "reason": "BUDGET_GUARD_DEFER", "timestamp": "2026-10-07T04:06:01+00:00"}
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    r = _eval("research-scheduler-holdings", O.holdings_research(root, now=NOW), "hold-3")
    assert r["reason"] == "typed_refusal:skip_gated"


def test_morning_brief_claim_is_an_artifact_not_a_receipt(tmp_path):
    root = _root(tmp_path)
    (root / "data/cio/morning_brief_semantic_state.json").write_text(json.dumps({"published": {
        "MORNING:2026-10-07:abc": {"key": "MORNING:2026-10-07:abc", "session_date": "2026-10-07", "material_generation": "abc", "claimed_at": "2026-10-07T11:33:10+00:00"}}}))
    obs = O.morning_brief(root, session_date="2026-10-07")
    assert obs["publish_claims"] == 1 and obs["artifact_status"] == "OBSERVED"
    r = _eval("morning-brief-0730", obs, "mb-1")
    assert r["state"] == "ARTIFACT_WRITTEN" and r["reason"] == "command_line_is_not_a_receipt"


def test_material_digest_from_a_detector_row_is_refused_until_a_muted_path_exists():
    row = {"change_guid": "d13460e0-f3fc-574c-8d69-a88d81e6c9b5", "symbol": "AMC", "kind": "price", "notify_outcome": "WOULD_SUPPRESS", "notified_at": None}
    obs = O.material_digest(lambda sql, args: [row])
    assert obs["detector_event_id"] == row["change_guid"] and obs["suppression"] == "WOULD_SUPPRESS" and obs["muted"] is False
    assert _eval("material-change-digest", obs, "md-1")["reason"] == "live_notifier_stays_in_code"
    assert O.material_digest(None)["detector_status"].startswith("NOT_MEASURED")


def test_approval_reminder_receipt_and_reconcile_become_the_consumer_receipt(tmp_path):
    root = _root(tmp_path)
    rp = root / "data/runtime/approval_package_reminder_last.json"
    assert _eval("approval-package-reminder", O.approval_reminder(root), "ap-0")["reason"] == "missing_run_receipt"
    rp.write_text(json.dumps({"schema": "ApprovalReminderReceipt@v1", "run_id": "r1", "served_sha": SHA, "planner_status": "ACTIONS_PLANNED",
                              "outcome": "PACKAGE_WRITTEN", "action_count": 1, "delivery_status": "DELIVERY_UNMEASURED", "delivery_receipt_count": 0,
                              "started_at": "2026-10-07T04:05:01+00:00", "ended_at": "2026-10-07T04:05:02+00:00"}))
    r = _eval("approval-package-reminder", O.approval_reminder(root), "ap-1")
    assert r["state"] == "ARTIFACT_WRITTEN" and r["reason"] == "no_consumer_receipt"
    rp.write_text(json.dumps({**json.loads(rp.read_text()), "delivery_status": "DELIVERY_OBSERVED", "delivery_receipt_count": 1}))
    (root / "data/runtime/approval_reminder_reconcile_last.json").write_text(json.dumps(
        {"schema": "ApprovalReminderReconcileRun@v1", "run_id": "r1", "status": "RECONCILED", "delivery_status": "DELIVERY_OBSERVED"}))
    r = _eval("approval-package-reminder", O.approval_reminder(root), "ap-2")
    assert r["state"] == "CONSUMED" and r["consumed"] is True


def test_every_builder_refuses_send_and_charge_by_construction(tmp_path):
    root = _root(tmp_path)
    for lane, fn in O.BUILDERS.items():
        obs = fn(None) if lane == "material-change-digest" else fn(root)
        assert obs["send"] is False and obs["provider_charge_requested"] is False and obs["lane_id"] == lane
