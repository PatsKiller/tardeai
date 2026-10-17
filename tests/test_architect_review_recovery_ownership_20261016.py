"""Architect review of main 26fd0518 (2026-10-16): negative tests that reproduce each reviewer case first.

F1  one shared recovery validator (scripts/lib/recovery_validator.py): the EFFECTIVE mode from the receipt; a
    live-requested, dry-executed run never covers or recovers a live lane (reviewer's reproduction at
    n8n_self_heal.py ~L289-302); output recovery needs a live receipt whose output verdict met the contract — a
    fresh shared file mtime / JSON timestamp alone never counts.
F2  ownership fail-open when history is missing (effect_claim.py ~L797-835): ledger unreachable + manifest missing /
    not listing an ARMED process -> fail CLOSED (P1); never-armed keeps fail-open; a missing manifest is a P1; the
    handover lock covers admission (decision + claim + child start), set-owner and the controller's rollback paths.
F3  critical-incident enrollment (n8n_failure_diagnosis.py ~L1081-1118): a first CRITICAL incident that enters
    successful recovery-request handling has exactly one open P1 record, never repaged, closed on resolution.
F4  nightly rollback (nightly_cutover_controller.py ~L628-641): exit non-zero with a per-target report when any
    restoration fails; every target re-read and verified.

Hermetic: tmp ledgers, manifests, crontabs (fake `crontab` on CRONTAB_CMD), tmp registry roots; never the live host.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import n8n_failure_diagnosis as cli  # noqa: E402
from scripts import nightly_cutover_controller as CTL  # noqa: E402
from scripts.lib import effect_claim as E  # noqa: E402
from scripts.lib import n8n_self_heal as H  # noqa: E402
from scripts.lib import nightly_cutover as NC  # noqa: E402
from scripts.lib import recovery_validator as RV  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger  # noqa: E402
from tests import test_nightly_cutover_controller_20261016 as T  # noqa: E402
from tests.test_nightly_cutover_controller_20261016 import fake_crontab  # noqa: E402,F401 — fixture

SLOT = "20261016T1215"
SKIP = f"d:lane-x:live:{SLOT}"
COVER = f"e:lane-x:live:{SLOT}"


def _row(run_id, state="RUN_DONE", *, mode="live", receipt=None, fin="2026-10-16T12:16:00+00:00", lane="lane-x"):
    rec = {"mode": mode} if receipt is None else receipt
    return {"run_id": run_id, "lane_id": lane, "state": state, "mode": mode, "requested_at": "2026-10-16T12:15:00+00:00",
            "finished_at": fin, "exit_code": 0 if state == "RUN_DONE" else 1,
            "receipt_json": None if rec is False else json.dumps(rec)}


#: exactly what scripts/n8n_run_executor.py writes for a live request on a lane the stage clamp holds in shadow
CLAMPED = {"mode": "dry_run", "requested_mode": "live", "output_verdict": {"verdict": "produced"},
           "stage_clamp": {"requested_mode": "live", "effective_mode": "dry_run", "stage": "shadow", "clamped": True,
                           "reason": "stage_shadow"}}


# ══ F1 ═════════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_F1_reviewer_case_live_requested_dry_executed_run_never_covers_a_live_lock_skip():
    cover = _row(COVER, receipt=CLAMPED)
    skip = _row(SKIP, "RUN_SKIPPED_LOCK", receipt={"mode": "live", "reason": "flock_held", "lock_skipped": True})
    assert H.verified_done(cover, "live") is False
    assert RV.validate(cover, mode="live") == (False, "requested_live_executed_dry")
    got, why = H.lock_skip_cover(skip, {"run": SKIP, "error": "flock_held"}, "flock_held", [cover, skip])
    assert got is None and why.endswith("requested_live_executed_dry")
    assert H.deterministic_verdict({"event_type": "RUN_SKIPPED_LOCK"}, fields={"run": SKIP, "error": "flock_held"},
                                   runs=[cover, skip], now=0.0) is None
    # the same run with a receipt that really executed live does cover (the positive control)
    real = _row(COVER, receipt={"mode": "live", "output_verdict": {"verdict": "produced"}})
    assert H.lock_skip_cover(skip, {"run": SKIP}, "flock_held", [real, skip])[1] == "covered"


def test_F1_live_requested_dry_executed_run_never_recovers_a_live_failure_or_output_breach():
    later = _row("later", receipt=CLAMPED, fin="2026-10-16T13:00:00+00:00")
    failed = _row("bad", "RUN_FAILED", receipt={"mode": "live"})
    assert H.deterministic_verdict({"event_type": "RUN_FAILED"}, fields={"run": "bad", "error": "mode=live exit=1"},
                                   runs=[later, failed], now=0.0) is None
    no_out = {"event_type": "NO_OUTPUT", "created_at": "2026-10-16T12:00:00+00:00"}
    assert H.deterministic_verdict(no_out, fields={}, runs=[later], now=0.0) is None
    assert RV.output_recovered("lane-x", "2026-10-16T12:00:00+00:00", {"mode": "live"}, runs=[later]) is None


def test_F1_diagnoser_verify_recovery_uses_the_effective_mode_and_pages_a_clamped_live_attempt():
    p = {"failure_mode": "live", "event_type": "RUN_FAILED", "lane": "lane-x", "requested_ts": 0.0,
         "slot": ["lane-x", "live", SLOT]}
    run = _row(f"e:lane-x:live:{SLOT}:a2", receipt=CLAMPED)
    ev, why = cli.verify_recovery(p, run, output_state=None)
    assert ev is None and why == "requested_live_executed_dry_run"
    assert not why.startswith(("mode_mismatch", "failure_mode_unknown"))   # -> P1 in advance_pending, not digest


def test_F1_a_fresh_shared_file_or_advancing_mtime_is_never_output_recovery():
    fresh = {"verdict": "FRESH", "last_output_at": "2026-10-16T12:40:00+00:00", "basis": "cron x2"}
    no_out = {"event_type": "NO_OUTPUT", "created_at": "2026-10-16T12:00:00+00:00"}
    assert H.deterministic_verdict(no_out, fields={}, runs=[], now=0.0, output_state=fresh) is None
    mtime_only = _row("m", receipt={"mode": "live", "output_signal_mtime_before": 1.0,
                                    "output_signal_mtime_after": 2.0,
                                    "output_verdict": {"verdict": "declared_not_enforced"}})
    assert RV.validate(mtime_only, mode="live") == (False, "output_contract_unproven:declared_not_enforced")
    assert H.verified_done(mtime_only, "live") is False
    assert H.deterministic_verdict(no_out, fields={}, runs=[mtime_only], now=0.0, output_state=fresh) is None


@pytest.mark.parametrize("row_mode, receipt", [
    ("live", False),                                                                   # no receipt at all
    ("live", {"mode": "live", "stage_clamp": {"effective_mode": "dry_run"}}),          # the two fields disagree
    ("dry_run", {"mode": "live", "output_verdict": {"verdict": "produced"}}),          # a clamp never upgrades
])
def test_F1_unknown_or_inconsistent_effective_mode_is_never_evidence(row_mode, receipt):
    r = _row(COVER, mode=row_mode, receipt=receipt)
    assert RV.effective_mode(r) is None
    assert RV.validate(r, mode="live") == (False, "effective_mode_unknown")


def test_F1_output_recovery_needs_the_matching_semantic_slot_and_lane():
    good = {"mode": "live", "output_verdict": {"verdict": "produced"}}
    since = "2026-10-16T12:00:00+00:00"
    other_slot = _row("e:lane-x:live:20261016T1230", receipt=good)
    other_lane = _row(f"e:lane-y:live:{SLOT}", receipt=good, lane="lane-y")
    c = {"mode": "live", "slot": ["lane-x", "live", SLOT]}
    assert RV.output_recovered("lane-x", since, c, runs=[other_slot, other_lane]) is None
    ok = RV.output_recovered("lane-x", since, c, runs=[_row(COVER, receipt=good)])
    assert ok["evidence"] == [f"run:{COVER}"] and ok["effective_mode"] == "live" and ok["output_verdict"] == "produced"
    assert RV.output_recovered("lane-x", "2026-10-16T12:30:00+00:00", c, runs=[_row(COVER, receipt=good)]) is None


def test_F1_every_component_decides_through_the_one_validator(monkeypatch):
    calls = []
    real = RV.validate

    def spy(*a, **k):
        calls.append(k.get("mode"))
        return real(*a, **k)
    monkeypatch.setattr(RV, "validate", spy)
    good = _row(COVER, receipt={"mode": "live", "output_verdict": {"verdict": "produced"}})
    H.verified_done(good, "live")
    H.lock_skip_cover(_row(SKIP, "RUN_SKIPPED_LOCK"), {"run": SKIP}, "", [good])
    H.output_recovered("NO_OUTPUT", failure_mode_="live", since=0.0, runs=[good], lane="lane-x")
    H.output_recovered("RUN_FAILED", failure_mode_="live", since=0.0, runs=[good])
    cli.verify_recovery({"failure_mode": "live", "event_type": "RUN_FAILED", "lane": "lane-x"}, good,
                        output_state=None)
    assert len(calls) >= 5 and set(calls) == {"live"}


# ══ F2 ═════════════════════════════════════════════════════════════════════════════════════════════════════════════

def _cfg(tmp_path, **spec):
    p = tmp_path / f"keys_{len(list(tmp_path.glob('keys_*')))}.json"
    p.write_text(json.dumps({"schema": E.EFFECT_CONFIG_SCHEMA, "lanes": {
        "x-lane": {"process": "x-lane", "input_version": "v1", **spec}}}))
    return p


def _broken_ledger(tmp_path):
    d = tmp_path / "gov" / "ledger.sqlite"
    d.mkdir(parents=True)          # a directory where the sqlite file should be: unreachable
    return d


@pytest.mark.parametrize("manifest_doc", [None, {"x-other": "n8n"}])       # missing file / replaced, not listed
def test_F2_reviewer_case_unreachable_ledger_and_missing_or_unlisted_manifest_fail_closed_for_armed(tmp_path,
                                                                                                   manifest_doc):
    led = _broken_ledger(tmp_path)
    man = led.parent / E.HANDOVER_NAME
    if manifest_doc is not None:
        man.write_text(json.dumps({"schema": E.HANDOVER_SCHEMA, "processes": {
            k: {"owner": v, "epoch": 1, "switched_at": "x", "by": "t"} for k, v in manifest_doc.items()}}))
    for spec in ({"cron_claim": True}, {"cron_claim": False}, {"cron_claim": False, "n8n_claim": True}):
        d = E.ownership_decision("x-lane", ledger=str(led), manifest=man, config=_cfg(tmp_path, **spec))
        assert d["decision"] == E.DECIDE_SKIP_UNKNOWN and d["p1"] is True and d["armed"] is True, (spec, d)
        assert d["reason"].startswith("ledger_unreachable_armed_unlisted:manifest=")


def test_F2_never_armed_keeps_fail_open_and_a_missing_manifest_is_still_a_p1(tmp_path):
    led = _broken_ledger(tmp_path)
    man = led.parent / E.HANDOVER_NAME
    cfg = _cfg(tmp_path, cron_claim=False, n8n_claim=False)
    d = E.ownership_decision("x-lane", ledger=str(led), manifest=man, config=cfg)
    assert d["decision"] == E.DECIDE_RUN and d["p1"] is True and "handover_manifest_missing" in d["reason"]
    man.write_text(json.dumps({"schema": E.HANDOVER_SCHEMA, "processes": {}}))
    d = E.ownership_decision("x-lane", ledger=str(led), manifest=man, config=cfg)
    assert d["decision"] == E.DECIDE_RUN and d["p1"] is False


def test_F2_manifest_listing_cron_still_admits_with_the_ledger_down(tmp_path):
    led = _broken_ledger(tmp_path)
    man = led.parent / E.HANDOVER_NAME
    man.write_text(json.dumps({"schema": E.HANDOVER_SCHEMA, "processes": {
        "x-lane": {"owner": "cron", "epoch": 2, "switched_at": "x", "by": "t"}}}))
    d = E.ownership_decision("x-lane", ledger=str(led), manifest=man, config=_cfg(tmp_path, cron_claim=True))
    assert d["decision"] == E.DECIDE_RUN and d["p1"] is False


def test_F2_process_armed_reads_the_effect_key_config_fail_closed(tmp_path):
    assert E.process_armed("x-lane", _cfg(tmp_path)) is True                     # n8n_claim defaults to true
    assert E.process_armed("x-lane", _cfg(tmp_path, cron_claim=True, n8n_claim=False)) is True
    assert E.process_armed("x-lane", _cfg(tmp_path, cron_claim=False, n8n_claim=False)) is False
    assert E.process_armed("not-keyed", _cfg(tmp_path)) is False
    bad = tmp_path / "bad.json"
    bad.write_text("{torn")
    assert E.process_armed("x-lane", bad) is True                               # unreadable = armed
    # the committed config: the 36 handed-over processes are all armed
    assert E.process_armed("hermes-learning-outcome-grader") is True


def _lock_is_held(manifest: Path) -> bool:
    fd = os.open(str(manifest) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


class _Child:
    def __init__(self, rc=0):
        self.rc = rc

    def wait(self):
        return self.rc


@pytest.mark.parametrize("claim", [True, False])
def test_F2_admission_holds_the_handover_lock_across_decision_claim_and_child_start(tmp_path, claim):
    led = tmp_path / "gov" / "l.sqlite"
    led.parent.mkdir()
    man = led.parent / E.HANDOVER_NAME
    st = E.EffectClaimStore(CoordinationLedger(led))
    E.set_owner_with_manifest(st, man, "x-lane", "cron", expect_epoch=None, by="t", now=1.0)
    key = E.effect_key("x-lane", SLOT, "v1")
    seen = {}

    def spawn(cmd, env):
        seen["lock_held_at_start"] = _lock_is_held(man)
        seen["claim_at_start"] = (E.EffectClaimStore(CoordinationLedger(led)).get(key) or {}).get("state")
        with pytest.raises(E.HandoverLockTimeout):     # a set-owner cannot land while the child is being admitted
            with E.handover_lock(man, timeout=0.2):
                pass
        seen["fence"] = env.get(E.FENCE_ENV)
        return _Child(0)

    out = tmp_path / "d.json"
    rc = E.gated_run(process="x-lane", key=key, cmd=["true"], scheduler="cron", claim=claim, fenced=False,
                     ledger=str(led), manifest=man, decision_out=str(out), config=_cfg(tmp_path, cron_claim=claim),
                     spawn=spawn)
    assert rc == 0 and seen["lock_held_at_start"] is True
    assert seen["claim_at_start"] == ("CLAIMED" if claim else None)          # recorded BEFORE the child starts
    assert (seen["fence"] is not None) is claim
    assert not _lock_is_held(man)                                             # released after the start
    doc = json.loads(out.read_text())
    assert doc["schema"] == E.ADMIT_SCHEMA and doc["ownership"]["decision"] == "run" and doc["spawned"] is True
    if claim:
        assert E.EffectClaimStore(CoordinationLedger(led)).get(key)["state"] == "DONE"


def test_F2_admission_after_a_switch_to_n8n_runs_nothing(tmp_path):
    led = tmp_path / "gov" / "l.sqlite"
    led.parent.mkdir()
    man = led.parent / E.HANDOVER_NAME
    st = E.EffectClaimStore(CoordinationLedger(led))
    E.set_owner_with_manifest(st, man, "x-lane", "n8n", expect_epoch=None, by="t", now=1.0)
    spawned = []
    rc = E.gated_run(process="x-lane", key=E.effect_key("x-lane", SLOT, "v1"), cmd=["true"], scheduler="cron",
                     claim=True, fenced=False, ledger=str(led), manifest=man, decision_out=str(tmp_path / "d.json"),
                     config=_cfg(tmp_path, cron_claim=True), spawn=lambda *a, **k: spawned.append(1))
    assert rc == 0 and spawned == []
    assert json.loads((tmp_path / "d.json").read_text())["ownership"]["decision"] == E.DECIDE_SKIP_N8N


def test_F2_admission_waits_for_a_held_fence_then_refuses_without_running(tmp_path):
    led = tmp_path / "gov" / "l.sqlite"
    led.parent.mkdir()
    man = led.parent / E.HANDOVER_NAME
    spawned = []
    with E.handover_lock(man):                       # a set-owner / controller holds the fence
        rc = E.gated_run(process="x-lane", key=E.effect_key("x-lane", SLOT, "v1"), cmd=["true"], scheduler="cron",
                         claim=False, fenced=False, ledger=str(led), manifest=man,
                         decision_out=str(tmp_path / "d.json"), config=_cfg(tmp_path), lock_timeout=0.2,
                         spawn=lambda *a, **k: spawned.append(1))
    assert rc == 2 and spawned == [] and (tmp_path / "d.json").exists() is False


def test_F2_cli_gate_runs_the_command_once(tmp_path):
    led = tmp_path / "gov" / "l.sqlite"
    led.parent.mkdir()
    man = led.parent / E.HANDOVER_NAME
    E.set_owner_with_manifest(E.EffectClaimStore(CoordinationLedger(led)), man, "x-lane", "cron",
                              expect_epoch=None, by="t", now=1.0)
    marker = tmp_path / "ran"
    rc = E.main(["--ledger", str(led), "run", "--ownership-gate", "--manifest", str(man), "--effect-config",
                 str(_cfg(tmp_path, cron_claim=True)), "--process", "x-lane", "--slot", SLOT, "--input-version", "v1",
                 "--scheduler", "cron", "--decision-out", str(tmp_path / "d.json"), "--", "touch", str(marker)])
    assert rc == 0 and marker.exists()
    assert E.EffectClaimStore(CoordinationLedger(led)).get(E.effect_key("x-lane", SLOT, "v1"))["state"] == "DONE"


def test_F2_wrapper_uses_the_gated_admission():
    text = (ROOT / "scripts" / "effect_claim_cron.sh").read_text()
    assert "--ownership-gate" in text and "--with-n8n-claim" in text
    assert " ownership --process" not in text            # no separate, unfenced decision call any more


# ══ F3 ═════════════════════════════════════════════════════════════════════════════════════════════════════════════

NOW = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)


def _crit_res(**kw):
    res = {"lane": "lane-x", "signature": "sig-c", "episode": 1, "incident_key": "kc1", "siem_id": 41,
           "severity": "CRITICAL", "event_type": "RUN_FAILED", "outcome": "deterministic",
           "_action": {"handler": "ledger_request_run", "action_id": "rerun_dry"}, "_phases": ["dry_run"],
           "decision": {"kind": "execute", "priority": None, "reason": "deterministic", "action_id": "rerun_dry"}}
    res.update(kw)
    return res


def test_F3_reviewer_case_first_critical_incident_with_a_successful_recovery_request_has_one_p1(tmp_path,
                                                                                                monkeypatch):
    monkeypatch.setattr(cli, "execute_action", lambda *a, **k: {"ok": True, "outcome": "requested", "run_id": "r1"})
    state = cli.empty_state()
    cli.apply_results({"results": [_crit_res()]}, [], state, {}, now=NOW, store_factory=object, allowlist={},
                      root=tmp_path)
    assert "kc1" in state["pending"]                                  # the recovery request is in flight ...
    p1 = [e for e in state["escalations"].values() if e["priority"] == "P1"]
    assert len(p1) == 1 and p1[0]["key"] == "lane-x|sig-c"             # ... AND visible as exactly one P1 record
    assert p1[0]["route"] == "operator_once" and p1[0]["heal_state"] == H.RECOVERY_REQUESTED
    first_at = p1[0]["at"]
    # next cycle: the same incident is carried (diagnosed) -> still ONE record, not re-put (no repeat page)
    carried = _crit_res(outcome="carried", decision={"kind": "carry", "priority": None, "reason": "diagnosis_cached",
                                                     "action_id": None})
    cli.apply_results({"results": [carried]}, [], state, {}, now=NOW + timedelta(minutes=5), store_factory=object,
                      allowlist={}, root=tmp_path)
    p1 = [e for e in state["escalations"].values() if e["priority"] == "P1"]
    assert len(p1) == 1 and p1[0]["at"] == first_at
    # the recovery verifies -> the record closes
    ev = {"incident_key": "kc1", "lane": "lane-x", "signature": "sig-c", "episode": 1, "siem_id": 41,
          "outcome": "incident_resolved", "resolve": True, "heal_state": H.INCIDENT_RESOLVED}
    cli.apply_results({"results": []}, [ev], state, {}, now=NOW + timedelta(minutes=10), store_factory=object,
                      allowlist={}, root=tmp_path)
    assert state["escalations"] == {}


def test_F3_reaped_or_attached_critical_incident_is_also_enrolled(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "execute_action", lambda *a, **k: {"ok": True, "outcome": "reaped"})
    state = cli.empty_state()
    reap = _crit_res(_action={"handler": "ledger_reap_orphan", "action_id": "reap_orphan_run"})
    att = _crit_res(incident_key="kc2", siem_id=42, outcome="attached",
                    decision={"kind": "attach", "priority": None, "reason": "duplicate_signature", "action_id": None})
    cli.apply_results({"results": [reap, att]}, [], state, {}, now=NOW, store_factory=object, allowlist={},
                      root=tmp_path)
    esc = list(state["escalations"].values())
    assert len(esc) == 1 and esc[0]["priority"] == "P1" and set(esc[0]["siem_ids"]) == {41, 42}


def test_F3_a_warn_incident_with_a_recovery_request_is_not_paged(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "execute_action", lambda *a, **k: {"ok": True, "outcome": "requested", "run_id": "r1"})
    state = cli.empty_state()
    cli.apply_results({"results": [_crit_res(severity="WARN")]}, [], state, {}, now=NOW, store_factory=object,
                      allowlist={}, root=tmp_path)
    assert state["escalations"] == {} and "kc1" in state["pending"]


# ══ F4 ═════════════════════════════════════════════════════════════════════════════════════════════════════════════

def _applied(tmp_path, fake_crontab, monkeypatch):
    served, led, text = T._setup(tmp_path)
    fake_crontab.write_text(text)
    T._arm(tmp_path)
    monkeypatch.setattr(CTL.NC, "resolve_current", lambda p: (served, T.SHA))
    code, rc = CTL.run(T.args(tmp_path, served, led, apply=True), workflow_reader=T.reader, now=T.NOW,
                       notifier=lambda *a: True)
    assert code == 0 and rc["applied"], rc
    rb = sorted((tmp_path / "receipts/rollback").glob("alpha-lane-*.json"))[0]
    a = T.args(tmp_path, served, led, receipt=str(rb))
    a.cmd = "rollback"
    return a, text


def test_F4_reviewer_case_registry_restore_failure_exits_nonzero_with_a_per_target_report(tmp_path, fake_crontab,
                                                                                          monkeypatch):
    a, text = _applied(tmp_path, fake_crontab, monkeypatch)
    real = NC._write_atomic

    def fail_registry(p, data):
        if Path(p).name == "lane_registry.json":
            raise OSError("disk full")
        return real(p, data)
    monkeypatch.setattr(NC, "_write_atomic", fail_registry)
    code, out = CTL.run(a, workflow_reader=T.reader, now=T.NOW)
    assert code == 2 and out["cohort_stop"].startswith("rollback_incomplete:"), out
    t = out["rollback"]["targets"]
    assert t["registry"]["ok"] is False and t["registry"]["after"] == "applied" and "disk full" in t["registry"]["problem"]
    assert t["contracts"]["ok"] is True and t["contracts"]["after"] == "not_applied"
    # the registry still routes to n8n, so the cron line is NOT re-enabled (no double schedule)
    assert t["crontab"]["action"] == "skipped_prior_failure" and t["crontab"]["ok"] is False
    assert fake_crontab.read_text().split("\n")[2] != text.split("\n")[2]
    assert out["rollback"]["registry_problems"] and Path(out["receipt_path"]).exists()


def test_F4_conflicting_target_touches_nothing_and_exits_nonzero(tmp_path, fake_crontab, monkeypatch):
    a, text = _applied(tmp_path, fake_crontab, monkeypatch)
    reg_p = tmp_path / "regroot/config/lane_registry.json"
    reg = json.loads(reg_p.read_text())
    next(r for r in reg["lanes"] if r["lane_id"] == "alpha-lane")["note"] = "operator edit"
    reg_p.write_text(json.dumps(reg, indent=2) + "\n")
    before = (reg_p.read_bytes(), fake_crontab.read_text())
    code, out = CTL.run(a, workflow_reader=T.reader, now=T.NOW)
    assert code == 2 and out["cohort_stop"] == "rollback_conflict:registry"
    assert {k: v["action"] for k, v in out["rollback"]["targets"].items()} == {
        "crontab": "untouched", "registry": "untouched", "contracts": "untouched"}
    assert (reg_p.read_bytes(), fake_crontab.read_text()) == before


def test_F4_successful_rollback_verifies_every_target_and_is_idempotent(tmp_path, fake_crontab, monkeypatch):
    a, text = _applied(tmp_path, fake_crontab, monkeypatch)
    code, out = CTL.run(a, workflow_reader=T.reader, now=T.NOW)
    assert code == 0, out
    assert all(v["ok"] and v["after"] in ("not_applied", "n/a") for v in out["rollback"]["targets"].values())
    assert fake_crontab.read_text() == text
    code, out = CTL.run(a, workflow_reader=T.reader, now=T.NOW)                 # again: already restored
    assert code == 0 and {v["action"] for v in out["rollback"]["targets"].values()} <= {
        "already_restored", "not_applicable"}


def test_F4_crontab_edit_failure_is_reported_and_nonzero(tmp_path, fake_crontab, monkeypatch):
    a, text = _applied(tmp_path, fake_crontab, monkeypatch)
    code, out = CTL.run(a, workflow_reader=T.reader, now=T.NOW,
                        edit=lambda req, **k: (3, {"problems": ["sha mismatch"]}))
    assert code == 2 and out["rollback"]["targets"]["crontab"]["ok"] is False
    assert "sha mismatch" in out["rollback"]["targets"]["crontab"]["problem"]


def test_F4_rollback_holds_the_handover_fence(tmp_path, fake_crontab, monkeypatch):
    a, text = _applied(tmp_path, fake_crontab, monkeypatch)
    man = CTL.manifest_path(a)
    seen = []

    def edit(req, **k):
        seen.append(_lock_is_held(man))
        return CTL.call_edit(req, **k)
    code, out = CTL.run(a, workflow_reader=T.reader, now=T.NOW, edit=edit)
    assert code == 0 and seen == [True], out
