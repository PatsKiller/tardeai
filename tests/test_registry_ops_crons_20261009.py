"""registry-ops-crons (2026-10-09): three host-cron lanes declared before their crontab lines exist.

incident-notifier (*/5, #1603), n8n-activation-grants (P16, */30) and n8n-workflow-drift-check (P18, :07)
are rows with kind cron, scheduler.expression = the 5 cron fields and scheduler.install_line = the exact line
Agent A installs under a `cron` grant (packet ops-crons-install.md). Until the install they are PAUSED ("approved, pending install"): the one
state that is green before AND after the line appears, and that arms neither the lane monitor, the
supervisor breaches nor the fan-in's governance liveness. After the install the row flips to ACTIVE.
Hermetic: repo files only, no crontab, no systemctl, tmp roots.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import reconcile_lane_registry as R  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402
from scripts.lib import lane_state_drift as SD  # noqa: E402
from scripts.lib.lane_dispatch import dispatch_eligible  # noqa: E402

REG = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REG["lanes"]}
ALLOW = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
LANES = {
    # lane_id: (schedule, script + mode, lock, log, cadence hours)
    "incident-notifier": ("*/5 * * * *", "scripts/incident_notifier.py --live", "/tmp/tradeai_incident_notifier.lock",
                          "logs/incident_notifier.log", 0.1),
    "n8n-activation-grants": ("*/30 * * * *", "scripts/check_n8n_activation_grants.py --write",
                              "/tmp/tradeai_n8n_activation_attribution.lock", "logs/n8n_activation_grants.log", 0.5),
    "n8n-workflow-drift-check": ("7 * * * *", "scripts/check_n8n_workflow_drift.py --write",
                                 "/tmp/tradeai_n8n_workflow_drift.lock", "logs/n8n_workflow_drift.log", 1.0),
}
LINES = [ROWS[lid]["scheduler"]["install_line"] for lid in LANES]


@pytest.mark.parametrize("lane_id", sorted(LANES))
def test_row_is_paused_pending_install_with_the_exact_line(lane_id):
    sched, match, lock, log, cadence = LANES[lane_id]
    row = ROWS[lane_id]
    assert LR.validate_row(row) == []
    assert row["state"] == "PAUSED" and row["review_by"] and row["state_since"] == "2026-10-09"
    assert "PENDING INSTALL" in row["state_reason"] and "ops-crons-install.md" in row["state_reason"]
    s = row["scheduler"]
    assert s["kind"] == "cron" and s["match"] == match and s["expression"] == sched
    line = s["install_line"]
    assert match in line
    assert line.startswith(sched + " cd $PROJ && ")
    assert f"bash $PROJ/scripts/safe_flock.sh {lock} timeout " in line
    assert "TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state " in line
    assert f" >> {log} 2>&1  # TRADEAI_LANE {lane_id}" in line and line.endswith(f"# TRADEAI_LANE {lane_id}")
    assert "/home/" not in line and "%" not in line          # no host path; no cron-escaped char
    assert row["expected_cadence_hours"] == cadence
    assert R.cron_cadence_hours(sched) <= cadence
    assert row["output_signal"]["kind"] == "file_mtime" and row["output_signal"]["path"].startswith("data/runtime/")


def test_p16_p18_lines_match_the_governance_packet_and_the_notifier_line_is_a_system_sender():
    assert ROWS["n8n-activation-grants"]["scheduler"]["install_line"] == (
        "*/30 * * * * cd $PROJ && TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state bash "
        "$PROJ/scripts/safe_flock.sh /tmp/tradeai_n8n_activation_attribution.lock timeout 300 $PY "
        "scripts/check_n8n_activation_grants.py --write >> logs/n8n_activation_grants.log 2>&1  "
        "# TRADEAI_LANE n8n-activation-grants")
    assert ROWS["n8n-workflow-drift-check"]["scheduler"]["install_line"] == (
        "7 * * * * cd $PROJ && TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state bash "
        "$PROJ/scripts/safe_flock.sh /tmp/tradeai_n8n_workflow_drift.lock timeout 300 $PY "
        "scripts/check_n8n_workflow_drift.py --write >> logs/n8n_workflow_drift.log 2>&1  "
        "# TRADEAI_LANE n8n-workflow-drift-check")
    line = ROWS["incident-notifier"]["scheduler"]["install_line"]
    assert "set -a && . ./.env && set +a && " in line            # ops bot env, same as the other cron senders
    assert "SYSTEM_TELEGRAM_ENABLED=1 CIO_TELEGRAM_INTERDICT=1 " in line   # as tradeai-autonomy-watchdog.service
    assert "--dry-run" not in line and "timeout 120 $PY scripts/incident_notifier.py --live" in line


def test_none_of_the_three_can_be_dispatched_or_allowlisted():
    allow_ids = {e["lane_id"] for e in ALLOW["lanes"]}
    assert "incident-notifier" not in allow_ids and "n8n-activation-grants" not in allow_ids
    assert "grant" in ALLOW["blocked_reasons"]["n8n-activation-grants"]
    for lid in LANES:
        row = ROWS[lid]
        assert row["recommendation"] == "KEEP_ON_CRON" and not row.get("dispatch")
        assert dispatch_eligible(row) == (False, "keep_on_cron")


def test_each_installed_line_maps_to_exactly_one_row_and_nothing_is_undeclared():
    found = {"cron": LR.discover_cron("\n".join(LINES) + "\n")}
    assert len(found["cron"]) == 3
    assert LR.find_undeclared(REG, found, n8n_known_ids=[]) == []
    mapping = R.line_mapping(REG, [c["expression"] for c in found["cron"]])
    assert sorted(ids[0] for ids in mapping.values() if len(ids) == 1) == sorted(LANES)
    assert all(len(ids) == 1 for ids in mapping.values()), mapping


def _drift(rows, lines):
    return {r["lane_id"]: r for r in SD.classify_lanes(rows, cron_rows=[{"expression": x} for x in lines])}


def test_state_drift_is_green_before_install_after_install_and_after_the_flip():
    rows = [ROWS[lid] for lid in LANES]
    before = _drift(rows, [])
    after = _drift(rows, LINES)
    assert {r["code"] for r in before.values()} == {"ALIGNED"}
    assert SD.conflicts(list(before.values())) == [] and SD.conflicts(list(after.values())) == []
    flipped = [dict(r, state="ACTIVE") for r in rows]
    assert {r["code"] for r in _drift(flipped, LINES).values()} == {"ALIGNED"}
    # The old declaration would have been a conflict once the line is installed: why the rows had to change.
    old = [dict(r, state="NEVER_SCHEDULED") for r in rows]
    assert {r["code"] for r in _drift(old, LINES).values()} == {"CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED"}


def test_reconcile_leaves_the_rows_untouched_before_and_after_install():
    """`reconcile_lane_registry --write` stays a fixed point: annotate_existing only rewrites a hand row
    whose live line joins a rationalization item or a stay-on-cron token, and these join neither."""
    f_rows = R.load_rationalization()
    tokens = R._forbidden_tokens()
    for lines in ([], LINES):
        reg = {"lanes": [json.loads(json.dumps(ROWS[lid])) for lid in LANES]}
        R.annotate_existing(reg, list(lines), list(lines), {"timers": [], "services": []}, f_rows, tokens=tokens)
        assert reg["lanes"] == [ROWS[lid] for lid in LANES]


def test_paused_rows_are_expected_silent_for_the_lane_monitor(tmp_path):
    now = datetime(2026, 10, 9, 23, 0, tzinfo=timezone.utc)
    for lid in LANES:
        v = LR.evaluate_lane(ROWS[lid], now=now, found={"cron": [], "systemd": []}, root=tmp_path)
        assert v["verdict"] == LR.EXPECTED_SILENT, (lid, v)


def test_fanin_governance_liveness_stays_quiet_until_the_flip(tmp_path, monkeypatch):
    from scripts import n8n_incident_fanin as fanin
    monkeypatch.delenv("TRADEAI_FANIN_GOVERNANCE", raising=False)
    now = datetime(2026, 10, 9, 23, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(fanin, "_governance_lane", lambda lane_id: ROWS.get(lane_id))
    assert fanin._governance_findings(tmp_path, now, prev={}) == []          # PAUSED: no receipt is not a finding
    active = {lid: dict(ROWS[lid], state="ACTIVE") for lid in ("n8n-activation-grants", "n8n-workflow-drift-check")}
    monkeypatch.setattr(fanin, "_governance_lane", lambda lane_id: active.get(lane_id))
    items = sorted(f["item"] for f in fanin._governance_findings(tmp_path, now, prev={}))
    assert items == ["receipt:missing", "receipt:missing"]                  # after the flip the check is armed


# ============================================================================ breach triage (same PR)
SNAPSHOT = json.loads((R.DATA_DIR / "scheduler_snapshot_20261009.json").read_text(encoding="utf-8"))
SNAP_LINES = [x["line"] for x in SNAPSHOT["cron_lines"]]


def _parts(expr):
    return [p.strip() for p in expr.split(" + ")]


def test_no_active_cron_row_carries_command_text_in_its_expression():
    """cron_schedule / cron_last_fire parse 5 fields only; command text sent the detector to the 3x-cadence rule."""
    for r in REG["lanes"]:
        s = r["scheduler"]
        if s.get("kind") != "cron" or r["state"] not in ("ACTIVE", "PAUSED"):
            continue
        for part in _parts(s["expression"]):
            assert part.startswith("@") or len(part.split()) == 5, (r["lane_id"], s["expression"])
        if " + " in s["expression"]:
            assert s.get("schedules") == _parts(s["expression"]), r["lane_id"]
        assert s.get("match"), r["lane_id"]          # identity lives in match once the expression is bare
        if r.get("scheduler_note"):
            assert s.get("command_text"), r["lane_id"]   # still scanned by the dispatch forbidden-token rule


def test_stripped_hand_rows_keep_their_live_schedules():
    """Every hand row's (bare) schedules are exactly the schedules of the snapshot lines its match selects."""
    for r in REG["lanes"]:
        s = r["scheduler"]
        if s.get("kind") != "cron" or r["state"] != "ACTIVE" or r.get("generated_by") or not r.get("scheduler_note"):
            continue
        live = {R.split_schedule(ln)[0] for ln in SNAP_LINES if s["match"] in ln}
        assert set(_parts(s["expression"])) == live, (r["lane_id"], s["expression"], live)


def test_snapshot_carries_the_post_install_crontab():
    assert SNAP_LINES[-3:] == LINES
    joined = "\n".join(SNAP_LINES)
    assert "flock -n -E 99 /tmp/shadow_batch_cron.lock timeout 60m $PY scripts/shadow_batch_generator.py" in joined
    assert "flock -n -E 99 /tmp/shadow_batch.lock " not in joined
    assert any(ln.startswith("20 18 * * 1,4 ") and "hermes_cross_source_synthesizer.py" in ln for ln in SNAP_LINES)
    for script in ("hermes_discovery_yield_builder.py", "hermes_discovery_scorecard.py"):
        (ln,) = [x for x in SNAP_LINES if script in x]
        assert "run_with_deepseek_offpeak.sh" not in ln, script
    assert ROWS["hermes-cross-source-synthesizer"]["scheduler"]["expression"] == "20 18 * * 1,4"


SIGNALS = {
    "finviz-momentum-scalp-early-lane": {"kind": "file_mtime", "path": "logs/finviz_momentum_scalp_scan.log"},
    "resolve-due-checkpoints": {"kind": "file_mtime", "path": "logs/resolve_due_checkpoints.log"},
    "commitment-outcome-sweep": {"kind": "file_mtime", "path": "logs/sweep_commitment_outcomes.log"},
}


def test_signal_wrong_lanes_point_at_an_artifact_written_every_run():
    for lid, sig in SIGNALS.items():
        assert ROWS[lid]["output_signal"] == sig, lid
    sd = ROWS["schwab-stream-daemon"]["output_signal"]
    assert (sd["kind"], sd["table"], sd["column"]) == ("db_max", "schwab_stream_quotes", "captured_at")
    for lid, log in (("run-protection-pipeline-at-x-30-9-16", "protection_pipeline.log"),
                     ("run-protection-pipeline-at-30-20", "protection_pipeline.log"),
                     ("run-governed-symbol-thesis-acquisition", "symbol_thesis_acquisition.log")):
        sig = ROWS[lid]["output_signal"]
        assert sig["path"] == f"~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/logs/{log}" and sig["evidence"] == "SCRIPT_RECEIPT"
    for lid in ("prewarm-finviz-strip-map", "prewarm-trade-ai"):
        r = ROWS[lid]
        assert r["output_signal"]["kind"] == "none" and r["output_signal"]["reason"] == "NO_DURABLE_OUTPUT"
        assert r["flags"] == ["NO_DURABLE_OUTPUT"]


def test_declared_no_output_needs_written_evidence_and_wins_over_the_log_redirect():
    assert R.declared_no_output(None) is None
    assert R.declared_no_output({"declared_no_output": {"reason": "NO_DURABLE_OUTPUT"}}) is None   # no evidence
    sig, flags = R.declared_no_output({"declared_no_output": {"evidence": "curl -o /dev/null /home/someone/x"}})
    assert sig["kind"] == "none" and sig["reason"] == "NO_DURABLE_OUTPUT" and flags == ["NO_DURABLE_OUTPUT"]
    assert "/home/someone" not in sig["detail"]
    line = '*/9 * * * * curl -s -o /dev/null "http://127.0.0.1:7777/x" >> logs/x_prewarm.log 2>&1'
    ev = {"prewarm-x": {"declared_no_output": {"evidence": "curl writes nothing"}}}
    rows, problems = R.build_cron_rows([line], [line], [line], [], ev, set(), tokens=((), frozenset(), frozenset()))
    assert not problems and [r["lane_id"] for r in rows] == ["prewarm-x"]
    assert rows[0]["output_signal"]["kind"] == "none" and rows[0]["flags"] == ["NO_DURABLE_OUTPUT"]
    rows2, _ = R.build_cron_rows([line], [line], [line], [], {}, set(), tokens=((), frozenset(), frozenset()))
    assert rows2[0]["output_signal"]["path"] == "logs/x_prewarm.log"


def _sbd():
    from scripts import supervisor_breach_detector as SBD
    return SBD


def test_premarket_due_window_is_a_subset_of_the_live_line():
    s = ROWS["active-trader-premarket-watch"]["scheduler"]
    assert s["expression"] == "*/5 6-9 * * 1-5"
    assert s["due_schedules"] == ["*/5 6-8 * * 1-5", "0-25/5 9 * * 1-5"]
    SBD = _sbd()
    now = datetime(2026, 10, 9, 13, 50, tzinfo=timezone.utc)            # 09:50 EDT, Friday
    lane = {"scheduler": {"kind": "cron", "expression": s["expression"]}, "expected_cadence_hours": 0.084}
    assert SBD._expected_since(lane, now, 240)[0] == datetime(2026, 10, 9, 13, 45, tzinfo=timezone.utc)
    lane["scheduler"]["due_schedules"] = s["due_schedules"]
    assert SBD._expected_since(lane, now, 240)[0] == datetime(2026, 10, 9, 13, 25, tzinfo=timezone.utc)  # 09:25
    assert SBD._expected_since(lane, datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc), 240)[0] == datetime(
        2026, 10, 9, 10, 55, tzinfo=timezone.utc)                          # 06:55 EDT, inside the window


def test_sla_max_silence_follows_the_real_cadence():
    from scripts import seed_supervisor_sla as SEED
    assert SEED.max_silence_s(0.05) == 900
    assert SEED.max_silence_s(1.0) == 3 * 3600
    assert SEED.max_silence_s(16.0) == 48 * 3600
    assert SEED.max_silence_s(24.0) == 48 * 3600                 # daily unchanged
    assert SEED.max_silence_s(72.0) == 108 * 3600
    assert SEED.max_silence_s(168.0) == 252 * 3600               # weekly maturity-remeasure: no SILENT on day 3
    row = SEED.sla_row(ROWS["maturity-remeasure"])
    assert row["max_silence_s"] > 7 * 24 * 3600


def test_timers_are_not_judged_before_their_first_fire():
    SBD = _sbd()
    for lid, first in (("platform-maintenance-weekly", "2026-10-11T04:00:00-04:00"),
                       ("platform-maintenance-monthly", "2026-11-01T07:00:00-05:00")):
        lane = ROWS[lid]
        assert lane["first_due"] == first
        never = lambda sig: {"last_output_at": None, "readable": True}          # noqa: E731
        sla = {lid: {"max_run_s": 900}}
        before = SBD.detect(lanes=[lane], sla_by_lane=sla, heartbeats={}, observe=never,
                            now=datetime.fromisoformat(first) - timedelta(minutes=1))
        after = SBD.detect(lanes=[lane], sla_by_lane=sla, heartbeats={}, observe=never,
                           now=datetime.fromisoformat(first) + timedelta(minutes=1))
        assert before == [] and [r["kind"] for r in after] == ["NO_OUTPUT"]


def test_stripping_the_expressions_changed_no_dispatch_eligibility():
    """The forbidden-token scan reads every scheduler string; --send etc. moved to scheduler.command_text."""
    for lid in ("screener-go-alerts", "llm-spend-report-daily", "llm-spend-report-weekly", "llm-spend-report-monthly"):
        ok, why = dispatch_eligible(ROWS[lid])
        assert ok is False and why == "forbidden_token:send@scheduler.command_text", (lid, why)
