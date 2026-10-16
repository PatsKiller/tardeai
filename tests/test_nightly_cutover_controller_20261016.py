"""Nightly cutover controller (2026-10-16): the enforced state machine, its checks, the cohort stop, the narrow
crontab edit capability, arming, registry reconciliation, rollback and the P1 completed-session rule.

Hermetic: fixture crontabs (a fake `crontab` command on CRONTAB_CMD), tmp ledgers, tmp served roots and registry
roots, a stub notifier. Nothing here reads the live crontab, ledger, grants or n8n.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import nightly_cutover as NC  # noqa: E402
from scripts import nightly_cutover_controller as CTL  # noqa: E402
from scripts import nightly_cutover_cron_edit as EDIT  # noqa: E402
from scripts import n8n_cutover_wave as W  # noqa: E402

#: alarm_firing_coverage: the controller's one summary send is exercised through the real chokepoint below.
COVERS = ["scripts/nightly_cutover_controller.py"]
ET = ZoneInfo("America/New_York")
SHA = "a" * 40
NOW = datetime(2026, 10, 16, 23, 30, tzinfo=timezone.utc)      # Fri 19:30 ET
AL_V, C_V = "allowlistv000001", "contractsv00001"


# ── fixtures ───────────────────────────────────────────────────────────────────────────────────────────────────────

def reg_row(lane, script, *, expr="10 6 * * 1-5", klass="report", stage="canary", mode="live"):
    return {"lane_id": lane, "owner": "platform", "state": "ACTIVE",
            "scheduler": {"kind": "cron", "expression": expr, "match": script, "stage": stage, "wave": "LD-W1",
                          "command_text": f"cd $PROJ && flock -n /tmp/{lane}.lock $PY {script}"},
            "dispatch": {"mode": mode, "cron": [expr], "tz": "America/New_York", "class": klass, "priority": 5}}


def entry(lane, script):
    return {"lane_id": lane, "command": ["$PY", script], "lock": f"/tmp/{lane}.lock", "lock_kind": "flock",
            "timeout_s": 600, "dry_run_arg": ["--dry-run"], "live_arg": [], "output_signal": f"data/runtime/{lane}.json"}


def contract(lane, stage="canary"):
    return {"id": lane, "kind": "lane", "status": "REVIEWED", "stage": stage,
            "healthy": [{"check": "canary_live_done", "text": "... RUN_SKIPPED_LOCK while the cron twin holds ..."}]}


def cron_line(lane, script, *, expr="10 6 * * 1-5", wrap=False):
    w = f"env TRADEAI_EFFECT_CLAIM={lane} bash scripts/effect_claim_cron.sh {lane} " if wrap else ""
    return f"{expr} cd $PROJ && flock -n /tmp/{lane}.lock {w}$PY {script} >> logs/{lane}.log 2>&1"


def run(lane, *, rid=None, state="RUN_DONE", exit_code=0, verdict="produced", sha=SHA, al=AL_V, cv=C_V,
        wf="tradeai-dispatcher", finished=NOW - timedelta(hours=3), clamp="live", lock_skipped=False, mode="live"):
    rid = rid or f"d:{lane}:live:{finished.strftime('%Y%m%dT%H%M')}"
    return {"run_id": rid, "lane_id": lane, "mode": mode, "state": state, "exit_code": exit_code,
            "requested_by": f"n8n:workflow:{wf}" if wf else "host:x", "requested_at": finished.isoformat(),
            "finished_at": finished.isoformat(),
            "receipt": {"run_id": rid, "code_sha": sha, "lock_skipped": lock_skipped,
                        "stage_clamp": {"effective_mode": clamp, "stage": "canary"},
                        "output_verdict": {"verdict": verdict},
                        "policy": {"allowlist_version": al, "expected_outputs_version": cv}}}


LANES = {"alpha-lane": ("scripts/alpha.py", "F11"), "beta-lane": ("scripts/beta.py", "F11"),
         "gamma-lane": ("scripts/gamma.py", "F11")}


def mk_world(lanes=("alpha-lane",), **over):
    reg = {l: reg_row(l, LANES[l][0]) for l in lanes}
    crontab = "\n".join(["SHELL=/bin/bash", "# header"] + [cron_line(l, LANES[l][0]) for l in lanes]) + "\n"
    base = dict(now=NOW, config=json.loads(json.dumps(NC.DEFAULT_CONFIG)),
                policy={"families": {l: LANES[l][1] for l in lanes}, "holds": {}, "p1_last": frozenset(),
                        "cron_overlap_trading_days": 1},
                disposition={l: {"lane_id": l, "family_id": LANES[l][1], "source": "crontab",
                                 "disposition": "MIGRATE_N8N"} for l in lanes},
                current_sha=SHA, registry=reg, registry_root_rows=json.loads(json.dumps(reg)),
                allowlist={l: entry(l, LANES[l][0]) for l in lanes}, allowlist_version=AL_V,
                contracts={l: contract(l) for l in lanes}, contracts_version=C_V, effect_raw={}, effect_lanes={},
                relay_live=frozenset(lanes), crontab=crontab, runs={l: [run(l)] for l in lanes}, in_flight={},
                owners={}, ambiguous_claims={}, served_wrapper_ok=True, served_wrapper_why="ok",
                workflow_live={"tradeai-dispatcher": "h1"}, workflow_git={"tradeai-dispatcher": "h1"})
    base.update(over)
    return NC.World(**base)


def verdict(world, lane="alpha-lane"):
    return next(v for v in NC.evaluate(world)["lanes"] if v["lane_id"] == lane)


def held(world, lane="alpha-lane"):
    return verdict(world, lane).get("held") or ""


# ── the happy path and the state machine ───────────────────────────────────────────────────────────────────────────

def test_ready_lane_reaches_drained_with_exact_edits():
    v = verdict(mk_world())
    assert v["status"] == "ready" and v["state"] == "drained" and not v["held"]
    e = v["edits"][0]
    assert e["line"] == 3 and e["after"] == "# RETIRED 2026-10-16 n8n-cutover alpha-lane " + e["before"]
    assert v["proof_run"]["verdict"] == "produced"


def test_plan_records_the_crontab_hash_and_versions():
    w = mk_world()
    p = NC.evaluate(w)
    assert p["crontab_sha"] == NC.sha256_text(w.crontab) and p["current_sha"] == SHA and p["schema"] == NC.PLAN_SCHEMA


# ── 1. cohort ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mutate, expect", [
    (lambda w: w.policy["holds"].update({"alpha-lane": "operator_hold_20261016: x"}), "operator_hold:operator_hold_20261016"),
    (lambda w: w.policy["families"].pop("alpha-lane"), "unknown_family"),
    (lambda w: w.policy["families"].update({"alpha-lane": "F07"}), "excluded_F07"),
    (lambda w: w.disposition["alpha-lane"].update({"source": "registry_systemd"}), "excluded_registry_systemd"),
    (lambda w: w.disposition.pop("alpha-lane"), "not_in_disposition_scope"),
    (lambda w: w.disposition["alpha-lane"].update({"family_id": "F40"}), "family_disagrees"),
    (lambda w: w.registry["alpha-lane"].update({"state": "PAUSED"}), "registry_state_PAUSED"),
    (lambda w: w.registry["alpha-lane"]["dispatch"].update({"mode": "dry_run"}), "dispatch_mode_dry_run"),
])
def test_cohort_negatives(mutate, expect):
    w = mk_world()
    mutate(w)
    assert held(w).startswith(expect)


def test_shadow_and_systemd_rows_are_not_in_the_cohort():
    w = mk_world()
    w.registry["alpha-lane"]["scheduler"]["stage"] = "shadow"
    assert NC.evaluate(w)["lanes"] == []


def test_already_retired_line_is_named_not_reapplied():
    w = mk_world()
    w.crontab = w.crontab.replace("10 6 * * 1-5 cd", "# RETIRED 2026-10-15 n8n-cutover alpha-lane 10 6 * * 1-5 cd")
    assert held(w).startswith("already_retired_outside_controller")


def test_match_hitting_two_lines_is_held():
    w = mk_world()
    w.crontab += cron_line("alpha-lane", "scripts/alpha.py", expr="20 6 * * 1-5") + "\n"
    assert held(w).startswith("cron_line_match_hits_2_lines")


@pytest.mark.parametrize("mutate, expect", [
    (lambda w: w.allowlist["alpha-lane"].update({"live_arg": None}), "allowlist_no_live_arg"),
    (lambda w: w.registry_root_rows["alpha-lane"].update({"note": "drift"}), "registry_root_row_differs"),
    (lambda w: setattr(w, "relay_live", frozenset()), "not_relay_live"),
    (lambda w: w.contracts["alpha-lane"].update({"stage": "shadow"}), "contract_disagrees_with_registry"),
    (lambda w: w.contracts["alpha-lane"].update({"status": "DRAFT"}), "contract_disagrees_with_registry"),
])
def test_registry_allowlist_mode_contract_agreement(mutate, expect):
    w = mk_world()
    mutate(w)
    assert held(w).startswith(expect)


# ── 2 + 3. versions and the qualifying run ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kw, expect", [
    ({"sha": "b" * 40}, "proof_release_mismatch"),
    ({"al": "other"}, "allowlist_version_mismatch"),
    ({"cv": "other"}, "contract_version_mismatch"),
    ({"wf": "rogue-workflow"}, "workflow_not_in_cohort"),
    ({"verdict": "declared_not_enforced"}, "output_verdict_declared_not_enforced"),
    ({"verdict": "no_rule"}, "output_verdict_no_rule"),
    ({"verdict": "unverifiable"}, "output_verdict_unverifiable"),
    ({"verdict": "empty_violation"}, "output_verdict_empty_violation"),
    ({"exit_code": 1}, "not_live_done"),
    ({"state": "RUN_SKIPPED_LOCK", "exit_code": 75}, "not_live_done"),
    ({"clamp": "dry_run"}, "stage_clamped"),
    ({"lock_skipped": True}, "lock_skipped"),
    ({"finished": NOW - timedelta(hours=100)}, "proof_too_old"),
    ({"wf": None}, "not_an_n8n_run"),
])
def test_qualifying_run_negatives(kw, expect):
    w = mk_world(runs={"alpha-lane": [run("alpha-lane", **kw)]})
    h = held(w)
    assert h.startswith("no_qualifying_live_run") and expect in h, h


def test_empty_allowed_is_a_verified_empty_proof():
    assert verdict(mk_world(runs={"alpha-lane": [run("alpha-lane", verdict="empty_allowed")]}))["status"] == "ready"


def test_no_live_run_at_all():
    assert held(mk_world(runs={})).startswith("no_live_n8n_run")


def test_workflow_graph_drift_and_missing_git_copy():
    assert "workflow_graph_drift" in held(mk_world(workflow_live={"tradeai-dispatcher": "DRIFTED"}))
    assert "workflow_not_in_git" in held(mk_world(workflow_git={}))


def test_lane_own_workflow_is_in_cohort():
    w = mk_world(runs={"alpha-lane": [run("alpha-lane", wf="own123")]}, lane_workflows={"alpha-lane": "own123"},
                 workflow_live={"own123": "h"}, workflow_git={"own123": "h"})
    assert verdict(w)["status"] == "ready"


def test_newest_good_run_wins_over_older_bad_ones():
    runs = [run("alpha-lane", exit_code=1, finished=NOW - timedelta(hours=5)), run("alpha-lane")]
    assert verdict(mk_world(runs={"alpha-lane": runs}))["status"] == "ready"


def test_f09_requires_a_natural_slot_proof():
    w = mk_world(runs={"alpha-lane": [run("alpha-lane", rid="nc:alpha-lane:live:20261016T1900", wf=None)]})
    w.policy["families"]["alpha-lane"] = "F09"
    w.disposition["alpha-lane"]["family_id"] = "F09"
    h = held(w)
    assert "natural_slot_required_F09" in h
    w.runs["alpha-lane"] = [run("alpha-lane")]
    w.effect_lanes["alpha-lane"] = {"process": "alpha", "input_version": "v1", "n8n_claim": True, "cron_claim": False}
    w.owners["alpha"] = "n8n"
    w.manifest_status, w.manifest_owners = "ok", {"alpha": "n8n"}
    assert verdict(w)["status"] == "ready"


def test_sender_lane_needs_downstream_evidence():
    w = mk_world()
    w.policy["families"]["alpha-lane"] = "F10"
    w.disposition["alpha-lane"]["family_id"] = "F10"
    w.effect_lanes["alpha-lane"] = {"process": "alpha", "input_version": "v1", "n8n_claim": True, "cron_claim": False}
    w.owners["alpha"] = "n8n"
    w.manifest_status, w.manifest_owners = "ok", {"alpha": "n8n"}
    assert held(w).startswith("downstream_evidence_unconfigured")
    w.config["downstream_evidence"] = {"alpha-lane": {"kind": "receipt_field", "path": "delivery.delivered"}}
    assert held(w).startswith("downstream_missing:receipt.delivery.delivered")
    w.runs["alpha-lane"][0]["receipt"]["delivery"] = {"delivered": 1}
    assert verdict(w)["status"] == "ready"
    w.config["downstream_evidence"] = {"alpha-lane": {"kind": "file_mtime_after", "path": "data/x.json"}}
    assert held(w).startswith("downstream_missing:data/x.json")
    w.downstream_mtimes = {"data/x.json": NOW.timestamp()}
    assert verdict(w)["status"] == "ready"


# ── P1: one COMPLETED NYSE session after valid proof ───────────────────────────────────────────────────────────────

def et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def test_completed_sessions_midnight_crossing_is_not_a_session():
    proof = et(2026, 10, 15, 20)                                  # Thu 20:00 ET
    assert NC.completed_sessions_after(proof, et(2026, 10, 16, 0, 5)) == 0
    assert NC.completed_sessions_after(proof, et(2026, 10, 16, 9, 0)) == 0
    assert NC.completed_sessions_after(proof, et(2026, 10, 16, 15, 59)) == 0
    assert NC.completed_sessions_after(proof, et(2026, 10, 16, 16, 0)) == 1


def test_session_open_at_proof_time_does_not_count():
    assert NC.completed_sessions_after(et(2026, 10, 16, 10), et(2026, 10, 16, 23)) == 0
    assert NC.completed_sessions_after(et(2026, 10, 16, 10), et(2026, 10, 19, 16)) == 1     # Mon


def test_nyse_holidays_not_federal():
    # Columbus Day 2026-10-12 is an NYSE session; Good Friday 2026-04-03 is not; day after Thanksgiving closes 13:00.
    assert NC.completed_sessions_after(et(2026, 10, 9, 17), et(2026, 10, 12, 16, 30)) == 1
    assert NC.completed_sessions_after(et(2026, 4, 2, 17), et(2026, 4, 3, 23)) == 0
    assert NC.completed_sessions_after(et(2026, 11, 26, 17), et(2026, 11, 27, 13, 1)) == 1


def test_wave_tool_p1_counting_is_fixed():
    # The old trading_days_between counted the Friday DATE at 00:05 after a Thursday-evening proof.
    assert W.trading_days_between(et(2026, 10, 15, 20), datetime(2026, 10, 16).date()) == 1   # end of Fri
    assert NC.completed_sessions_after(et(2026, 10, 15, 20), et(2026, 10, 16, 0, 5)) == 0


def _ledger(tmp_path, rows):
    p = tmp_path / "ledger.sqlite"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_by TEXT, "
              "requested_at TEXT, started_at TEXT, finished_at TEXT, exit_code INTEGER, receipt_json TEXT)")
    for r in rows:
        c.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)", r)
    c.commit()
    c.close()
    return p


def test_wave_p1_overlap_uses_completed_sessions(tmp_path):
    pol = {"p1_last": frozenset({"incident-notifier"}), "cron_overlap_trading_days": 1}
    led = _ledger(tmp_path, [("r1", "incident-notifier", "live", "RUN_DONE", "x", "2026-10-16T00:00:00+00:00", None,
                              "2026-10-16T00:00:05+00:00", 0, "{}")])            # Thu 20:00 ET
    assert W.p1_overlap_problems(["incident-notifier"], pol, ledger=led, now=et(2026, 10, 16, 9))
    assert W.p1_overlap_problems(["incident-notifier"], pol, ledger=led, now=et(2026, 10, 16, 16, 1)) == []


def test_p1_lane_in_controller():
    proof_t = NOW - timedelta(hours=3)                            # Fri 16:30 ET: no session after it yet
    w = mk_world(runs={"alpha-lane": [run("alpha-lane", finished=proof_t)]})
    w.policy["p1_last"] = frozenset({"alpha-lane"})
    assert held(w).startswith("p1_session_pending: 0/1")
    w.runs["alpha-lane"] = [run("alpha-lane", finished=et(2026, 10, 15, 8)),                 # Thu 08:00 ET proof
                            run("alpha-lane", finished=proof_t)]
    assert verdict(w)["status"] == "ready" and verdict(w)["p1"]["completed_sessions"] >= 1
    w.runs["alpha-lane"].insert(1, run("alpha-lane", state="RUN_FAILED", exit_code=1,
                                       finished=et(2026, 10, 16, 12)))
    assert held(w).startswith("p1_session_pending")          # the failed run resets the chain to the last proof


def test_p1_lanes_sort_last():
    w = mk_world(lanes=("alpha-lane", "beta-lane"))
    w.policy["p1_last"] = frozenset({"alpha-lane"})
    assert [v["lane_id"] for v in NC.evaluate(w)["lanes"]] == ["beta-lane", "alpha-lane"]


# ── 4. remaining triggers protected ────────────────────────────────────────────────────────────────────────────────

def _effect(w, owner="n8n", n8n_claim=True):
    w.effect_lanes["alpha-lane"] = {"process": "alpha", "input_version": "v1", "n8n_claim": n8n_claim,
                                    "cron_claim": False}
    w.effect_raw["alpha-lane"] = {"process": "alpha", "input_version": "v1", "effects": ["append"]}
    w.owners["alpha"] = owner
    # the production owner switch (effect_claim.py set-owner) writes the handover manifest too
    w.manifest_status = "ok"
    w.manifest_owners = {**w.manifest_owners, "alpha": owner}


def test_append_lane_needs_armed_key_and_n8n_owner():
    w = mk_world()
    w.effect_raw["alpha-lane"] = {"process": "alpha", "input_version": "v1", "effects": ["append"]}
    assert held(w).startswith("effect_key_not_armed_for_n8n")
    _effect(w, n8n_claim=False)
    assert held(w).startswith("effect_key_not_armed_for_n8n")
    _effect(w, owner="cron")
    assert held(w).startswith("effect_owner_cron")
    _effect(w)
    assert verdict(w)["status"] == "ready"


def _narrow_match(w):
    for rows in (w.registry, w.registry_root_rows):
        rows["alpha-lane"]["scheduler"]["match"] = "logs/alpha-lane.log"


def test_remaining_trigger_must_be_switched_on_and_served_wrapper_current():
    w = mk_world()
    _narrow_match(w)
    _effect(w)
    extra = "30 12 * * 1-5 cd $PROJ && $PY scripts/alpha.py --catchup >> logs/a.log 2>&1"
    w.crontab += extra + "\n"
    h = held(w)
    assert h.startswith("remaining_trigger_unprotected: L4"), h
    w.crontab = w.crontab.replace(extra, extra.replace("$PY", "env TRADEAI_EFFECT_CLAIM=alpha-lane bash "
                                                               "scripts/effect_claim_cron.sh alpha-lane $PY"))
    assert verdict(w)["status"] == "ready" and verdict(w)["remaining_cron_triggers"] == [4]
    w.served_wrapper_ok, w.served_wrapper_why = False, "missing skipped_effect"
    assert held(w).startswith("served_wrapper_lacks_1016_semantics")


def test_switch_for_another_lane_or_crontab_wide_export_is_not_protection():
    assert not NC.line_switched_on("x TRADEAI_EFFECT_CLAIM=beta-lane bash scripts/effect_claim_cron.sh alpha-lane $PY",
                                   "alpha-lane")
    assert not NC.line_switched_on("x TRADEAI_EFFECT_CLAIM=1 bash scripts/effect_claim_cron.sh alpha-lane $PY",
                                   "alpha-lane")
    assert NC.line_switched_on("x env TRADEAI_EFFECT_CLAIM=alpha-lane bash scripts/effect_claim_cron.sh alpha-lane $PY",
                               "alpha-lane")


def test_read_only_lane_needs_no_effect_protection():
    w = mk_world()
    _narrow_match(w)
    w.crontab += "30 12 * * 1-5 cd $PROJ && $PY scripts/alpha.py --catchup\n"
    assert verdict(w)["status"] == "ready"


# ── 5. drained ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_in_flight_and_stale_runs_and_ambiguous_effects():
    young = {"run_id": "d:alpha-lane:live:x", "state": "RUNNING", "started_at": (NOW - timedelta(seconds=60)).isoformat()}
    old = dict(young, started_at=(NOW - timedelta(hours=2)).isoformat())
    assert held(mk_world(in_flight={"alpha-lane": [young]})).startswith("in_flight_run")
    assert held(mk_world(in_flight={"alpha-lane": [old]})).startswith("stale_in_flight_run")
    w = mk_world()
    _effect(w)
    w.ambiguous_claims = {"alpha": [("fx:alpha:x:v1", "UNKNOWN")]}
    assert held(w).startswith("ambiguous_effect:fx:alpha:x:v1 UNKNOWN (never auto-released")


# ── cap ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_nightly_cap():
    w = mk_world(lanes=("alpha-lane", "beta-lane", "gamma-lane"))
    w.config["max_lanes_per_night"] = 2
    st = {v["lane_id"]: v["status"] for v in NC.evaluate(w)["lanes"]}
    assert st["alpha-lane"] == st["beta-lane"] == "ready" and st["gamma-lane"].startswith("held:nightly_cap_reached")


# ── config ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_config_loads_and_bad_config_stops(tmp_path):
    cfg = NC.load_config(ROOT / "config/nightly_cutover_controller.json")
    assert cfg["grant_token"] == "nightly-cutover-controller" and cfg["grant_tier"] == "cron"
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"schema": NC.CONFIG_SCHEMA, "max_lanes_per_night": -1}))
    with pytest.raises(NC.CohortStop):
        NC.load_config(p)
    p.write_text("{")
    with pytest.raises(NC.CohortStop):
        NC.load_config(p)


# ── arming ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _grants(tmp_path, rows):
    p = tmp_path / "grants.json"
    p.write_text(json.dumps(rows))
    return p


def test_armed_needs_active_cron_grant_naming_the_controller(tmp_path):
    cfg = NC.load_config(ROOT / "config/nightly_cutover_controller.json")
    now = 1_000_000.0
    good = {"grant_id": "g1", "expires": str(now + 3600), "uses": "5",
            "reason": "nightly-cutover-controller: arm (PR #1 sha abcdef123)"}
    assert CTL.armed(cfg, grants_path=_grants(tmp_path, {"cron": good}), now=now)[0]
    assert not CTL.armed(cfg, grants_path=_grants(tmp_path, {"cron": dict(good, expires=str(now - 1))}), now=now)[0]
    assert not CTL.armed(cfg, grants_path=_grants(tmp_path, {"cron": dict(good, uses="0")}), now=now)[0]
    assert not CTL.armed(cfg, grants_path=_grants(tmp_path, {"cron": dict(good, reason="merge PR #1")}), now=now)[0]
    assert not CTL.armed(cfg, grants_path=_grants(tmp_path, {"config-write": good}), now=now)[0]
    assert not CTL.armed(cfg, grants_path=tmp_path / "missing.json", now=now)[0]


# ── the narrow crontab edit capability ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_crontab(tmp_path, monkeypatch):
    store = tmp_path / "crontab.store"
    script = tmp_path / "fakecrontab"
    script.write_text(f"""#!/usr/bin/env bash
set -e
if [ "$1" = "-l" ]; then cat {store}; exit 0; fi
if [ "$1" = "-" ]; then cat > {store}; exit 0; fi
exit 2
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CRONTAB_CMD", str(script))
    return store


def _req(text, lane="alpha-lane", idx=2, op="retire"):
    lines = text.split("\n")
    return {"op": op, "lane_id": lane, "date": "2026-10-16", "expect_sha": EDIT._sha(text),
            "edits": [{"index": idx, "before": lines[idx],
                       "after": EDIT.TAG.format(date="2026-10-16", lane=lane) + lines[idx]}]}


def test_edit_retire_touches_only_the_planned_line(fake_crontab, tmp_path):
    text = "A=1\n# keep\n" + cron_line("alpha-lane", "scripts/alpha.py") + "\nlast line\n"
    fake_crontab.write_text(text)
    rc, out = EDIT.run(_req(text), lock_path=str(tmp_path / "l"), backup_dir=tmp_path / "bk")
    assert rc == 0 and out["applied"] and out["read_back_ok"] and out["ownership_ok"]
    new = fake_crontab.read_text().split("\n")
    old = text.split("\n")
    assert [i for i in range(len(old)) if old[i] != new[i]] == [2]
    assert new[2] == "# RETIRED 2026-10-16 n8n-cutover alpha-lane " + old[2]
    bk = Path(out["backup"])
    assert bk.read_text() == text and (bk.stat().st_mode & 0o777) == 0o600


def test_edit_refuses_a_changed_crontab_and_writes_nothing(fake_crontab, tmp_path):
    text = "A=1\n# keep\n" + cron_line("alpha-lane", "scripts/alpha.py") + "\n"
    req = _req(text)
    fake_crontab.write_text(text + "# someone else edited\n")
    rc, out = EDIT.run(req, lock_path=str(tmp_path / "l"), backup_dir=tmp_path / "bk")
    assert rc == 3 and "crontab_hash_changed" in out["problems"][0] and out["backup"] is None
    assert fake_crontab.read_text() == text + "# someone else edited\n"


def test_edit_refuses_line_drift_commented_line_and_impure_after(fake_crontab, tmp_path):
    text = "A=1\n# keep\n" + cron_line("alpha-lane", "scripts/alpha.py") + "\n"
    fake_crontab.write_text(text)
    req = _req(text)
    req["edits"][0]["before"] = "something else"
    assert EDIT.run(req, lock_path=str(tmp_path / "l"), backup_dir=tmp_path / "bk")[0] == 3
    req = _req(text)
    req["edits"][0]["after"] = "rm -rf /"
    assert EDIT.run(req, lock_path=str(tmp_path / "l"), backup_dir=tmp_path / "bk")[0] == 3
    req = _req(text, idx=1)
    assert EDIT.run(req, lock_path=str(tmp_path / "l"), backup_dir=tmp_path / "bk")[0] == 3   # already a comment
    assert fake_crontab.read_text() == text


def test_edit_refuses_when_lock_is_held(fake_crontab, tmp_path):
    import fcntl
    text = "A=1\n# keep\n" + cron_line("alpha-lane", "scripts/alpha.py") + "\n"
    fake_crontab.write_text(text)
    lock = tmp_path / "l"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        rc, out = EDIT.run(_req(text), lock_path=str(lock), backup_dir=tmp_path / "bk")
    finally:
        os.close(fd)
    assert rc == 3 and out["problems"][0].startswith("lock_held")


def test_edit_read_back_mismatch_is_a_failure(tmp_path, monkeypatch):
    store = tmp_path / "s"
    script = tmp_path / "mangle"
    script.write_text(f"""#!/usr/bin/env bash
if [ "$1" = "-l" ]; then cat {store}; exit 0; fi
if [ "$1" = "-" ]; then cat > {store}; echo extra >> {store}; exit 0; fi
""")
    script.chmod(0o755)
    monkeypatch.setenv("CRONTAB_CMD", str(script))
    text = "A=1\n# keep\n" + cron_line("alpha-lane", "scripts/alpha.py") + "\n"
    store.write_text(text)
    rc, out = EDIT.run(_req(text), lock_path=str(tmp_path / "l"), backup_dir=tmp_path / "bk")
    assert rc == 4 and out["read_back_ok"] is False


def test_edit_rollback_restores_exact_line(fake_crontab, tmp_path):
    text = "A=1\n# keep\n" + cron_line("alpha-lane", "scripts/alpha.py") + "\n"
    fake_crontab.write_text(text)
    req = _req(text)
    assert EDIT.run(req, lock_path=str(tmp_path / "l"), backup_dir=tmp_path / "bk")[0] == 0
    retired = fake_crontab.read_text()
    rb = {"op": "rollback", "lane_id": "alpha-lane", "expect_sha": EDIT._sha(retired), "edits": req["edits"]}
    rc, out = EDIT.run(rb, lock_path=str(tmp_path / "l"), backup_dir=tmp_path / "bk")
    assert rc == 0 and fake_crontab.read_text() == text
    rb2 = dict(rb, lane_id="beta-lane", expect_sha=EDIT._sha(text))
    assert EDIT.run(rb2, lock_path=str(tmp_path / "l"), backup_dir=tmp_path / "bk")[0] == 3


# ── gather_world: shared control failures stop the cohort ──────────────────────────────────────────────────────────

def make_served(tmp_path, lanes=("alpha-lane",)):
    served = tmp_path / "served"
    (served / "config").mkdir(parents=True)
    (served / "scripts").mkdir()
    (served / "GIT_SHA").write_text(SHA + "\n")
    reg = {"schema": "x", "lanes": [reg_row(l, LANES[l][0]) for l in lanes]}
    for root in (served, tmp_path / "regroot"):
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "config/lane_registry.json").write_text(json.dumps(reg, indent=2) + "\n")
        (root / "config/n8n_health_contracts.json").write_text(
            json.dumps({"contracts": [contract(l) for l in lanes]}, indent=2) + "\n")
    (served / "config/n8n_run_allowlist.json").write_text(json.dumps({"lanes": [entry(l, LANES[l][0]) for l in lanes]}))
    (served / "config/n8n_effect_keys.json").write_text(json.dumps({"schema": "N8nEffectKeys@v1", "lanes": {}}))
    (served / "config/lane_cutover_policy.json").write_text(json.dumps(
        {"families": {l: LANES[l][1] for l in lanes}, "holds": {}, "p1_last": [], "cron_overlap_trading_days": 1}))
    d = served / W.DISPOSITION_CSV
    d.parent.mkdir(parents=True)
    with open(d, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["row_id", "source", "lane_id", "family_id", "disposition"])
        wr.writeheader()
        for i, l in enumerate(lanes):
            wr.writerow({"row_id": f"cron:L{i}", "source": "crontab", "lane_id": l, "family_id": LANES[l][1],
                         "disposition": "MIGRATE_N8N"})
    (served / NC.WRAPPER_REL).write_text("# " + " ".join(NC.WRAPPER_MARKERS) + "\n")
    gen = served / "docs/implementation/n8n-parallel/workflows/generated"
    gen.mkdir(parents=True)
    generic = served / "docs/implementation/n8n-maturity/workflows"
    generic.mkdir(parents=True)
    (generic / "tradeai-dispatcher.json").write_text(json.dumps(DISPATCHER_WF))
    return served


DISPATCHER_WF = {"id": "tradeai-dispatcher", "name": "d", "nodes": [{"name": "n", "type": "x", "parameters": {}}],
                 "connections": {}, "settings": {}}


def make_ledger(tmp_path, lanes=("alpha-lane",), served=None):
    al_v = NC.sha16((served / "config/n8n_run_allowlist.json").read_bytes())
    c_v = NC.sha16((served / "config/n8n_health_contracts.json").read_bytes())
    rows = []
    for l in lanes:
        r = run(l, al=al_v, cv=c_v)
        rows.append((r["run_id"], l, "live", "RUN_DONE", r["requested_by"], r["requested_at"], r["requested_at"],
                     r["finished_at"], 0, json.dumps(r["receipt"])))
    return _ledger(tmp_path, rows)


def args(tmp_path, served, ledger, crontab_file=None, **kw):
    ns = CTL.parser().parse_args(["run"])
    ns.current = str(served)
    ns.served_root = None
    ns.registry_root = str(tmp_path / "regroot")
    ns.crontab = str(crontab_file) if crontab_file else None
    ns.ledger = str(ledger)
    ns.relay_live = str(tmp_path / "relay.env")
    ns.state_root = str(tmp_path / "state")
    ns.receipt_dir = str(tmp_path / "receipts")
    ns.grants = str(tmp_path / "grants.json")
    ns.backup_dir = str(tmp_path / "bk")
    ns.config = str(ROOT / "config/nightly_cutover_controller.json")
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def _setup(tmp_path, lanes=("alpha-lane",)):
    served = make_served(tmp_path, lanes)
    led = make_ledger(tmp_path, lanes, served)
    (tmp_path / "relay.env").write_text("TRADEAI_N8N_RELAY_LIVE_LANES=" + " ".join(lanes) + "\n")
    text = "SHELL=/bin/bash\n# header\n" + "\n".join(cron_line(l, LANES[l][0]) for l in lanes) + "\n"
    return served, led, text


def reader():
    return [dict(DISPATCHER_WF, active=True)]


def test_gather_world_end_to_end_plan(tmp_path):
    served, led, text = _setup(tmp_path)
    ct = tmp_path / "ct.txt"
    ct.write_text(text)
    code, rc = CTL.run(args(tmp_path, served, led, ct, dry_run=True), workflow_reader=reader, now=NOW)
    assert code == 0 and rc["plan"]["counts"] == {"ready": 1}, rc
    assert Path(rc["receipt_path"]).exists() and (tmp_path / "receipts/nightly_cutover_last.json").exists()
    assert rc["armed"] is False


@pytest.mark.parametrize("breaker, expect", [
    ("ledger", "ledger_unreadable"),
    ("current", "current_unresolvable"),
    ("inventory", "n8n_workflow_inventory_unreadable"),
    ("registry", "registry_unreadable"),
    ("policy", "cutover_policy_unreadable"),
])
def test_shared_control_failures_stop_the_cohort(tmp_path, breaker, expect):
    served, led, text = _setup(tmp_path)
    ct = tmp_path / "ct.txt"
    ct.write_text(text)
    rd = reader
    a = args(tmp_path, served, led, ct, dry_run=True)
    if breaker == "ledger":
        a.ledger = str(tmp_path / "nope.sqlite")
    elif breaker == "current":
        (served / "GIT_SHA").write_text("garbage")
    elif breaker == "inventory":
        def rd():
            raise RuntimeError("docker down")
    elif breaker == "registry":
        (served / "config/lane_registry.json").write_text("{")
    elif breaker == "policy":
        (served / "config/lane_cutover_policy.json").unlink()
    code, rc = CTL.run(a, workflow_reader=rd, now=NOW)
    assert code == 2 and rc["cohort_stop"].startswith(expect), rc["cohort_stop"]
    assert rc["plan"] == {}


# ── apply: disarmed, armed, failures ───────────────────────────────────────────────────────────────────────────────

def _arm(tmp_path):
    import time as _t
    (tmp_path / "grants.json").write_text(json.dumps({"cron": {
        "grant_id": "g1", "expires": str(_t.time() + 3600), "uses": "5",
        "reason": "nightly-cutover-controller: operator arms (PR #1 sha abcdef123)"}}))


def test_apply_refused_when_disarmed_and_nothing_edited(tmp_path, fake_crontab):
    served, led, text = _setup(tmp_path)
    fake_crontab.write_text(text)
    calls = []
    code, rc = CTL.run(args(tmp_path, served, led, apply=True), workflow_reader=reader, now=NOW,
                       edit=lambda *x, **k: calls.append(x) or (0, {}), notifier=lambda *x: calls.append("n"))
    assert code == 1 and rc["refused"].startswith("DISARMED") and calls == []
    assert fake_crontab.read_text() == text


def test_armed_apply_retires_reconciles_and_writes_rollback(tmp_path, fake_crontab, monkeypatch):
    served, led, text = _setup(tmp_path, ("alpha-lane", "beta-lane"))
    fake_crontab.write_text(text)
    _arm(tmp_path)
    monkeypatch.setattr(CTL.NC, "resolve_current", lambda p: (served, SHA))
    sent = []
    code, rc = CTL.run(args(tmp_path, served, led, apply=True), workflow_reader=reader, now=NOW,
                       notifier=lambda line, cfg: sent.append(line) or True)
    assert code == 0 and rc["cohort_stop"] is None, rc
    assert [s["lane_id"] for s in rc["applied"]] == ["alpha-lane", "beta-lane"]
    live = fake_crontab.read_text().split("\n")
    assert live[2].startswith("# RETIRED 2026-10-16 n8n-cutover alpha-lane ")
    assert live[3].startswith("# RETIRED 2026-10-16 n8n-cutover beta-lane ")
    assert live[:2] == text.split("\n")[:2]
    reg = json.loads((tmp_path / "regroot/config/lane_registry.json").read_text())
    row = next(r for r in reg["lanes"] if r["lane_id"] == "alpha-lane")
    assert row["scheduler"]["kind"] == "n8n" and row["scheduler"]["stage"] == "cutover"
    assert row["scheduler_before_cutover"]["kind"] == "cron"
    con = json.loads((tmp_path / "regroot/config/n8n_health_contracts.json").read_text())
    c = next(x for x in con["contracts"] if x["id"] == "alpha-lane")
    assert c["stage"] == "cutover" and "cron twin holds" not in json.dumps(c["healthy"])
    rbs = sorted((tmp_path / "receipts/rollback").glob("alpha-lane-*.json"))
    assert rbs and json.loads(rbs[0].read_text())["schema"] == CTL.ROLLBACK_SCHEMA
    assert len(sent) == 1 and sent[0].startswith("nightly-cutover apply 2026-10-16: cut over 2 (alpha-lane, beta-lane)")
    # rollback (armed) restores the line and the rows
    a = args(tmp_path, served, led, receipt=str(rbs[0]))
    a.cmd = "rollback"
    code, out = CTL.run(a, workflow_reader=reader, now=NOW)
    assert code == 0 and not out["rollback"]["registry_problems"], out
    assert fake_crontab.read_text().split("\n")[2] == text.split("\n")[2]
    reg = json.loads((tmp_path / "regroot/config/lane_registry.json").read_text())
    assert next(r for r in reg["lanes"] if r["lane_id"] == "alpha-lane")["scheduler"]["kind"] == "cron"


def test_crontab_changed_between_evaluation_and_edit_stops_cohort(tmp_path, fake_crontab, monkeypatch):
    served, led, text = _setup(tmp_path, ("alpha-lane", "beta-lane"))
    fake_crontab.write_text(text)
    _arm(tmp_path)
    monkeypatch.setattr(CTL.NC, "resolve_current", lambda p: (served, SHA))
    real = CTL.call_edit

    def racing_edit(req, **kw):
        fake_crontab.write_text(fake_crontab.read_text() + "# operator edit\n")
        return real(req, **kw)
    code, rc = CTL.run(args(tmp_path, served, led, apply=True), workflow_reader=reader, now=NOW, edit=racing_edit,
                       notifier=lambda *x: True)
    assert code == 2 and rc["cohort_stop"].startswith("crontab_edit_failed:alpha-lane") and rc["applied"] == []
    assert fake_crontab.read_text() == text + "# operator edit\n"        # unrelated change preserved, nothing retired


def test_registry_write_failure_rolls_back_the_line_and_stops(tmp_path, fake_crontab, monkeypatch):
    served, led, text = _setup(tmp_path, ("alpha-lane", "beta-lane"))
    fake_crontab.write_text(text)
    _arm(tmp_path)
    monkeypatch.setattr(CTL.NC, "resolve_current", lambda p: (served, SHA))
    # a registry root whose serialisation would churn: the write must refuse
    p = tmp_path / "regroot/config/lane_registry.json"
    p.write_text(json.dumps(json.loads(p.read_text())))
    code, rc = CTL.run(args(tmp_path, served, led, apply=True), workflow_reader=reader, now=NOW,
                       notifier=lambda *x: True)
    assert code == 2 and rc["cohort_stop"].startswith("registry_write_failure"), rc["cohort_stop"]
    assert fake_crontab.read_text() == text            # alpha's line was rolled back; beta never attempted


def test_current_changed_mid_run_stops(tmp_path, fake_crontab, monkeypatch):
    served, led, text = _setup(tmp_path)
    fake_crontab.write_text(text)
    _arm(tmp_path)
    seq = iter([(served, SHA), (served, "c" * 40)])
    monkeypatch.setattr(CTL.NC, "resolve_current", lambda p: next(seq))
    code, rc = CTL.run(args(tmp_path, served, led, apply=True), workflow_reader=reader, now=NOW,
                       notifier=lambda *x: True)
    # the fresh per-lane re-check sees the release move before the edit: a shared change stops the cohort
    assert code == 2 and rc["cohort_stop"].startswith(("current_changed", "shared_state_changed_mid_run:current_sha"))
    assert fake_crontab.read_text() == text


def test_apply_refuses_projection_flags():
    assert CTL.main(["--apply", "--cutover-policy", "x.json"]) == 1
    assert CTL.main(["--apply", "--crontab", "x"]) == 1


def test_forced_canary_policy():
    w = mk_world(lanes=("alpha-lane", "beta-lane", "gamma-lane"), runs={})
    w.policy["families"]["beta-lane"] = "F09"
    w.effect_lanes["gamma-lane"] = {"process": "g", "input_version": "v1", "n8n_claim": True, "cron_claim": False}
    plan = NC.evaluate(w)
    reqs = []

    def req(lane, mode, rid):
        reqs.append((lane, mode, rid))
        return {"state": "REQUESTED"}
    out = CTL.forced_canaries(w, plan, NC.DEFAULT_CONFIG, request_run=req,
                              wait_run=lambda rid, b: {"state": "RUN_DONE", "exit_code": 0})
    assert [r["lane_id"] for r in out] == ["alpha-lane"]                 # F09 natural only; keyed lane needs a slot
    assert [(l, m) for l, m, _ in reqs] == [("alpha-lane", "dry_run"), ("alpha-lane", "live")]
    assert all(r.startswith("nc:alpha-lane:") for _, _, r in reqs)
    reqs.clear()
    out = CTL.forced_canaries(w, plan, NC.DEFAULT_CONFIG, request_run=req,
                              wait_run=lambda rid, b: {"state": "RUN_FAILED", "exit_code": 1})
    assert [(l, m) for l, m, _ in reqs] == [("alpha-lane", "dry_run")]  # a failed dry run never goes live


# ── registration ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_controller_lane_is_registered_disarmed():
    reg = json.loads((ROOT / "config/lane_registry.json").read_text())
    row = next(r for r in reg["lanes"] if r.get("lane_id") == NC.LANE_ID)
    assert row["state"] == "PAUSED" and (row.get("dispatch") or {}).get("mode", "off") == "off"
    assert "Agent A" in row["owner_note"]
    al = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())
    e = next(x for x in al["lanes"] if x.get("lane_id") == NC.LANE_ID)
    assert e["command"] == ["$PY", "scripts/nightly_cutover_controller.py"]
    assert e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] == ["--apply"]
    assert not any("cron_edit" in str(t) for t in e["command"] + e["live_arg"])   # n8n never calls the edit capability


# ── the one summary line reaches the transport (alarm firing coverage) ─────────────────────────────────────────────

def test_summary_line_fires_through_the_chokepoint(alarm_capture):
    rc = {"mode": "apply", "date": "2026-10-16", "applied": [{"lane_id": "alpha-lane"}],
          "plan": {"lanes": [{"lane_id": "beta-lane", "held": "no_live_n8n_run"}]}, "cohort_stop": None,
          "receipt_path": "/x/run-20261016T230000Z-apply.json"}
    line = CTL.summary_line(rc)
    assert line == ("nightly-cutover apply 2026-10-16: cut over 1 (alpha-lane); held 1; stop none; "
                    "receipt run-20261016T230000Z-apply.json")
    # Production config routes it P3 (digest, archived: never the transport). The priority is config, so the firing
    # test drives the same call site with a deliverable priority and proves the line reaches the transport.
    cfg = dict(NC.DEFAULT_CONFIG, summary={"priority": "P1", "producer": NC.LANE_ID})
    CTL.notify(line, cfg)
    alarm_capture.assert_fired(contains="nightly-cutover apply 2026-10-16: cut over 1")
