"""The lane registry: make "off" a reported state.

A production lane was disabled 2026-06-01 and nothing reported its absence for
three months. The liveness monitor ran every 15 minutes throughout. It learns
its lanes from hardcoded tuples, so it could see lanes producing poorly and
could not see a lane producing nothing because nobody told it the lane existed.

These tests are the five acceptance criteria, asserted rather than described.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib.lane_registry import (
    EXPECTED_SILENT,
    LIVE,
    ORPHANED,
    SILENT,
    SLOW,
    changed_findings,
    collect_lane_registry_report,
    discover_commented_cron,
    discover_cron,
    evaluate_lane,
    find_undeclared,
    load_registry,
    observe_signal,
    validate_registry,
    validate_row,
)

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "check_lane_registry.py"
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)   # a Sunday


def _row(**kw):
    base = {
        "lane_id": "demo", "owner": "platform", "state": "ACTIVE",
        "expected_cadence_hours": 24.0,
        "scheduler": {"kind": "systemd", "expression": "demo.timer"},
        "output_signal": {"kind": "file_mtime", "path": "demo.json"},
    }
    base.update(kw)
    return base


def _found(units=("demo.timer",)):
    return {"cron": [], "systemd": [{"expression": u} for u in units]}


def _sig(tmp_path, age_hours):
    p = tmp_path / "demo.json"
    p.write_text("{}", encoding="utf-8")
    import os
    t = (NOW - timedelta(hours=age_hours)).timestamp()
    os.utime(p, (t, t))
    return {"kind": "file_mtime", "path": str(p)}


# ── acceptance 1 — a disabled ACTIVE lane produces exactly one finding ─────

def test_an_active_lane_whose_scheduler_vanished_is_orphaned(tmp_path):
    """ORPHANED is the verdict that would have caught the June retirement
    within one cadence period."""
    row = _row(output_signal=_sig(tmp_path, 1))
    v = evaluate_lane(row, now=NOW, found=_found(units=()))   # timer gone
    assert v["verdict"] == ORPHANED
    assert v["ok"] is False
    assert v["firing"] == [ORPHANED]


def test_an_active_lane_past_cadence_is_silent(tmp_path):
    row = _row(expected_cadence_hours=1.0, output_signal=_sig(tmp_path, 50))
    v = evaluate_lane(row, now=NOW, found=_found())
    assert v["verdict"] == SILENT
    assert v["ok"] is False


def test_one_to_two_cadences_is_slow_not_silent(tmp_path):
    row = _row(expected_cadence_hours=10.0, output_signal=_sig(tmp_path, 15))
    v = evaluate_lane(row, now=NOW, found=_found())
    assert v["verdict"] == SLOW
    assert v["ok"] is True, "SLOW is information, not a page"


def test_within_cadence_is_live(tmp_path):
    row = _row(expected_cadence_hours=10.0, output_signal=_sig(tmp_path, 2))
    assert evaluate_lane(row, now=NOW, found=_found())["verdict"] == LIVE


# ── acceptance 2 — a declared RETIRED lane is expected, not a finding ──────

def test_a_declared_retired_lane_is_expected_silent_and_never_alerts():
    """The entire point: 'off' must be distinguishable from 'gone'."""
    for state in ("RETIRED", "PAUSED", "NEVER_SCHEDULED"):
        row = _row(state=state, state_reason="declared", state_since="2026-06-01",
                   review_by="2026-09-15",
                   output_signal={"kind": "file_mtime", "path": "/nonexistent"})
        v = evaluate_lane(row, now=NOW, found=_found(units=()))
        assert v["verdict"] == EXPECTED_SILENT, state
        assert v["ok"] is True, state
        assert v["firing"] == [], state


def test_a_retired_lane_keeps_its_row_and_its_reason():
    reg = load_registry()
    retired = [r for r in reg["lanes"] if r["state"] == "RETIRED"]
    assert retired, "the seeded registry must declare the retired lanes"
    for r in retired:
        assert r.get("state_reason") and r.get("state_since")


# ── acceptance 3 — CI gate: undeclared job fails, declaring it passes ──────

def _gate(registry=None, extra=(), discovery=None):
    cmd = [sys.executable, str(GATE), "--fail-on-new", *extra]
    if registry:
        cmd += ["--registry", str(registry)]
    if discovery:
        cmd += ["--discovery-json", str(discovery)]
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                          text=True, timeout=300).returncode


def test_the_gate_is_green_on_this_tree(tmp_path):
    """Green on the committed registry with empty injected discovery.

    Must not inspect the runner's live crontab/systemd (CI hosts differ).
    Undeclared-job fail-closed is covered by the mutation test below.
    """
    disco = tmp_path / "discovery.json"
    disco.write_text(
        json.dumps({"cron": [], "cron_commented": [], "systemd": []}),
        encoding="utf-8",
    )
    assert _gate(discovery=disco) == 0


def test_a_scheduled_job_with_no_row_fails_the_build(tmp_path):
    """Mutation test. A gate that can only pass is not a gate.

    Discovery is injected rather than read from the host. The first version of
    this test read the live crontab and systemd, so it passed on a developer box
    and failed in CI — where there is no crontab and no systemd, live discovery
    returns empty, and nothing can ever be undeclared. A mutation test that
    depends on host state is not testing the gate.
    """
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    declared = {r["scheduler"].get("expression") for r in reg["lanes"]}
    victims = [b for b in reg["undeclared_baseline"]
               if b.endswith(".timer") and b not in declared]
    assert victims, "need a baselined timer to remove"

    disco = tmp_path / "discovery.json"
    disco.write_text(json.dumps({
        "cron": [], "cron_commented": [],
        "systemd": [{"expression": victims[0], "enabled_state": "enabled"}],
    }), encoding="utf-8")

    p = tmp_path / "mutated.json"
    reg["undeclared_baseline"] = [b for b in reg["undeclared_baseline"]
                                  if b != victims[0]]
    p.write_text(json.dumps(reg), encoding="utf-8")
    assert _gate(p, discovery=disco) == 1, "removing a declaration must go red"

    # ...and restoring it goes green again.
    reg["undeclared_baseline"].append(victims[0])
    p.write_text(json.dumps(reg), encoding="utf-8")
    assert _gate(p, discovery=disco) == 0


def test_unreadable_discovery_is_cannot_run_not_a_pass(tmp_path):
    reg = tmp_path / "r.json"
    reg.write_text((ROOT / "config" / "lane_registry.json").read_text(), encoding="utf-8")
    assert _gate(reg, discovery=tmp_path / "absent.json") == 2


def test_a_row_without_an_output_signal_fails(tmp_path):
    """A lane is verified by a durable artifact, never an exit code."""
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    del reg["lanes"][0]["output_signal"]
    p = tmp_path / "m.json"
    p.write_text(json.dumps(reg), encoding="utf-8")
    assert _gate(p) == 1


def test_a_non_active_row_without_reason_or_since_fails(tmp_path):
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    for r in reg["lanes"]:
        if r["state"] == "RETIRED":
            del r["state_reason"]
            break
    p = tmp_path / "m.json"
    p.write_text(json.dumps(reg), encoding="utf-8")
    assert _gate(p) == 1


def test_cannot_run_is_exit_2_and_never_reads_as_a_pass(tmp_path):
    """Exit 2 for a missing file reads identically to a pass unless the caller
    checks for the specific value. That has happened in this repository."""
    rc = _gate(tmp_path / "absent.json")
    assert rc == 2
    assert rc != 0


def test_a_paused_row_must_carry_a_review_date():
    errs = validate_row(_row(state="PAUSED", state_reason="x", state_since="2026-08-30"))
    assert any("review_by" in e for e in errs)


def test_the_seeded_registry_is_structurally_valid():
    assert validate_registry(load_registry()) == []


# ── acceptance 4 — a quiet weekend reports QUIET, not a page ───────────────

def test_a_weekday_only_lane_does_not_alarm_on_sunday(tmp_path):
    """Weekend cadences are declared, not inferred."""
    assert NOW.weekday() == 6, "fixture must be a Sunday"
    row = _row(expected_cadence_hours=1.0, active_days=[0, 1, 2, 3, 4],
               output_signal=_sig(tmp_path, 50))
    v = evaluate_lane(row, now=NOW, found=_found())
    assert v["verdict"] == EXPECTED_SILENT
    assert v["ok"] is True
    # The same lane on a Monday is a finding.
    monday = NOW + timedelta(days=1)
    assert evaluate_lane(row, now=monday, found=_found())["verdict"] == SILENT


def test_a_clean_report_says_quiet():
    rep = collect_lane_registry_report(cron_text="", include_systemd=False,
                                       registry_path=ROOT / "config" / "lane_registry.json")
    # With no schedulers discovered, ACTIVE lanes orphan — so assert the wording
    # rule directly on a registry with nothing to say.
    empty = collect_lane_registry_report(
        now=NOW, cron_text="", include_systemd=False,
        registry_path=Path("/nonexistent/registry.json"))
    assert empty["summary"] == "QUIET"
    assert empty["ok"] is True
    assert isinstance(rep["verdict_counts"], dict)


# ── suppression — escalate on change, not on continuation ─────────────────

def test_a_lane_silent_for_many_cycles_alerts_once():
    cur = {"lanes": [{"lane_id": "a", "verdict": SILENT}]}
    first = changed_findings(cur, None)
    assert [r["lane_id"] for r in first] == ["a"], "first transition alerts"
    again = changed_findings(cur, cur)
    assert again == [], "continued state must not re-alert every cycle"
    recovered = changed_findings({"lanes": [{"lane_id": "a", "verdict": LIVE}]}, cur)
    assert recovered == []
    relapse = changed_findings(cur, {"lanes": [{"lane_id": "a", "verdict": LIVE}]})
    assert [r["lane_id"] for r in relapse] == ["a"], "a new transition alerts"


# ── acceptance 5 — the census names the disabled and unscheduled lanes ─────

def test_the_registry_names_every_currently_disabled_lane():
    reg = load_registry()
    ids = {r["lane_id"] for r in reg["lanes"]}
    # Timers that previously ran and then stopped, cause not established.
    for unit in ("tradeai-continuous", "hermes-autonomous-loop",
                 "tradeai-flash-llm-intelligence", "tradeai-flash-watchlist-daily",
                 "tradeai-hermes-research-remediation",
                 "tradeai-intelligence-remediation",
                 "tradeai-main-desk-free-llm-weekly"):
        assert unit in ids, f"{unit} stopped and is undeclared"
    # The lane that prompted all of this.
    assert "deep-overnight-llm" in ids
    # A lane that produces output with no scheduler at all.
    assert "cio-residual-web" in ids


# The registry was seeded with 26 lanes whose cause was not established. Working
# through the git history, the crontab comments, the journal and the systemd
# enablement state brought that to 6. This is a RATCHET, not a snapshot: the
# first version of this test asserted `>= 20` and failed the moment the work was
# done, which is a test encoding a measurement instead of a rule.
MAX_UNKNOWN_LANES = 3


def test_the_unexplained_count_can_only_shrink():
    reg = load_registry()
    unknown = [r["lane_id"] for r in reg["lanes"]
               if r.get("state") != "ACTIVE"
               and str(r.get("reason_confidence") or "UNKNOWN") == "UNKNOWN"]
    assert len(unknown) <= MAX_UNKNOWN_LANES, (
        f"{len(unknown)} lanes have no established reason, was {MAX_UNKNOWN_LANES}. "
        "Either establish the cause or lower the ratchet deliberately.")


def test_unknown_reasons_are_recorded_as_unknown_not_invented():
    """An honest UNKNOWN is the correct entry and is itself a finding."""
    reg = load_registry()
    unknown = [r for r in reg["lanes"]
               if str(r.get("reason_confidence") or "") == "UNKNOWN"]
    assert unknown, "if nothing is unknown, check that the field is being read"
    for r in unknown:
        assert r.get("state_since"), r["lane_id"]
        # An UNKNOWN must still say what WAS looked at, so the next reader does
        # not repeat the dig.
        assert len(str(r.get("reason_evidence") or r.get("state_reason") or "")) > 60, (
            f"{r['lane_id']}: UNKNOWN with no record of what was searched")


def test_recoverable_reasons_are_recorded_rather_than_marked_unknown():
    reg = load_registry()
    by_id = {r["lane_id"]: r for r in reg["lanes"]}
    # This one's reason IS in the cron comment, so it must not say UNKNOWN.
    assert "UNKNOWN" not in by_id["portfolio-backup-cron"]["state_reason"]
    assert "tradeai-portfolio-backup-cadence" in by_id["portfolio-backup-cron"]["state_reason"]


# ── discovery ─────────────────────────────────────────────────────────────

def test_a_commented_cron_line_is_not_a_running_job():
    text = "# 0 3 * * * /bin/true\n0 4 * * * /bin/false\n"
    assert len(discover_cron(text)) == 1
    assert "/bin/false" in discover_cron(text)[0]["expression"]


def test_commented_entries_keep_whatever_reason_text_they_carry():
    text = "# PHASE102-RETIRED 0 23 * * * /bin/true\n"
    got = discover_commented_cron(text)
    assert got and "PHASE102-RETIRED" in got[0]["tags"]


def test_an_unreadable_signal_is_not_reported_as_silence(tmp_path):
    """A signal that cannot be read is a different thing from a lane that is
    silent, and conflating them is how a monitor starts lying."""
    out = observe_signal({"kind": "db_max", "table": "x; DROP TABLE y", "column": "c"})
    assert out["last_output_at"] is None
    assert "unsafe" in out["detail"]


def test_find_undeclared_respects_the_inherited_debt_baseline():
    reg = {"lanes": [], "undeclared_baseline": ["a.timer"]}
    found = {"cron": [], "systemd": [{"expression": "a.timer"},
                                     {"expression": "b.timer"}]}
    got = find_undeclared(reg, found)
    assert [g["expression"] for g in got] == ["b.timer"]


# ── reason quality: 26 UNKNOWN lanes → 6 (#722) → 3 (Wave 2b A4) ───────────

def test_every_non_active_lane_declares_how_well_its_reason_is_established():
    """"Superseded" has been asserted falsely in this repo twice. A reason now
    has to say whether it was proven or merely correlated."""
    from scripts.lib.lane_registry import REASON_CONFIDENCE
    for r in load_registry()["lanes"]:
        if r.get("state") != "ACTIVE":
            assert r.get("reason_confidence") in REASON_CONFIDENCE, r["lane_id"]


def test_an_established_reason_carries_the_evidence_that_established_it():
    for r in load_registry()["lanes"]:
        if r.get("reason_confidence") == "ESTABLISHED":
            ev = str(r.get("reason_evidence") or "")
            assert len(ev) > 60, f"{r['lane_id']}: ESTABLISHED with no evidence"


def test_correlated_reasons_refuse_to_claim_coverage():
    """The whole point of the CORRELATED tier: a running successor is not proof
    that this lane's output is produced."""
    rows = [r for r in load_registry()["lanes"]
            if r.get("reason_confidence") == "CORRELATED"]
    assert rows, "the tier must actually be used, or it is decoration"
    for r in rows:
        blob = (str(r.get("state_reason")) + str(r.get("reason_evidence"))).lower()
        assert any(k in blob for k in
                   ("not established", "not proven", "not verify", "not verified",
                    "inferred", "do not treat as covered")), r["lane_id"]


def test_the_unknown_count_is_read_from_the_field_not_the_prose():
    """The gate grepped state_reason for the word UNKNOWN and reported 2 the
    moment the reasons were rewritten, while 8 lanes were still UNKNOWN."""
    import subprocess, sys as _s
    out = subprocess.run([_s.executable, str(GATE), "--json"], cwd=str(ROOT),
                         capture_output=True, text=True, timeout=300).stdout
    got = json.loads(out)
    expected = [r["lane_id"] for r in load_registry()["lanes"]
                if r.get("state") != "ACTIVE"
                and str(r.get("reason_confidence") or "UNKNOWN") == "UNKNOWN"]
    assert got["unknown_reason_lanes"] == expected


def test_a_superseded_lane_names_the_unit_that_replaced_it():
    for r in load_registry()["lanes"]:
        if "supersed" in str(r.get("state_reason") or "").lower():
            assert r.get("superseded_by"), (
                f"{r['lane_id']} claims supersession without naming the successor")


def test_the_reboot_finding_is_recorded_on_both_lanes_it_explains():
    by = {r["lane_id"]: r for r in load_registry()["lanes"]}
    for lid in ("tradeai-continuous", "tradeai-main-desk-free-llm-weekly"):
        assert "reboot" in str(by[lid]["state_reason"]).lower()
        assert by[lid]["reason_confidence"] == "ESTABLISHED"


def test_the_lane_that_crashed_is_not_described_as_turned_off():
    by = {r["lane_id"]: r for r in load_registry()["lanes"]}
    h = by["hermes-autonomous-loop"]
    assert "failed" in str(h["state_reason"]).lower()
    assert "503" in str(h["reason_evidence"])


# ── Output signals resolve where the WRITER writes ──────────────────────────
# Measured 2026-09-05: run from a worktree, the registry reported 28 of 65 lanes
# SILENT — including `research-lane-health`, the lane producing the report, and
# `warm-caches`, whose cron had fired minutes earlier. Both artifacts existed,
# dated that day, under the canonical state root. Resolving relative output
# paths against the CODE tree asks "did this job write into the checkout I am
# running from", which is a different question. After the fix: LIVE 1 -> 15,
# SILENT 28 -> 8.

def test_output_signals_resolve_against_the_state_root():
    """The property, not the environment.

    The first version of this also asserted `str(lr.ROOT) not in detail`. That
    passed here and failed in CI, correctly: on a runner
    production_state_root() can itself resolve inside the checkout, so "the
    state root differs from the code tree" is a fact about the machine, not
    about the code. I made this exact mistake earlier the same day on the Brave
    ledger test and repeated it here.

    What holds everywhere is that the path is CONSTRUCTED from state_root().
    """
    from scripts.lib import lane_registry as lr

    sig = {"kind": "file_mtime", "path": "data/runtime/example.json"}
    detail = str(lr.observe_signal(sig, db_query=None)["detail"])
    assert detail.startswith(str(lr.state_root())), detail


def test_observe_signal_does_not_resolve_output_against_the_code_tree():
    """The source-level half, which the resolution test cannot see when the two
    roots coincide — exactly the CI case."""
    import ast
    import inspect
    import textwrap

    from scripts.lib import lane_registry as lr

    fn = ast.parse(textwrap.dedent(inspect.getsource(lr.observe_signal))).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    code = ast.unparse(ast.Module(body=fn.body, type_ignores=[]))
    assert "state_root()" in code
    assert "else ROOT" not in code, (
        "output signal falls back to the code tree — a job writing to the state "
        "root reads as SILENT from any worktree")


def test_an_explicit_root_still_wins_so_tests_stay_hermetic(tmp_path):
    from scripts.lib import lane_registry as lr

    sig = {"kind": "file_mtime", "path": "data/runtime/example.json"}
    obs = lr.observe_signal(sig, root=tmp_path, db_query=None)
    assert str(tmp_path) in str(obs["detail"])


def test_the_registry_file_itself_is_still_code_relative():
    """The registry is CONFIG and ships with the code. Only durable OUTPUT
    moves to the state root; moving the declaration too would mean a checkout
    could not read its own lane list."""
    from scripts.lib import lane_registry as lr

    assert str(lr.ROOT) in str(lr.REGISTRY_PATH)
    assert lr.REGISTRY_PATH.name == "lane_registry.json"


def test_absent_is_still_reported_as_silence_not_unverifiable(tmp_path):
    """The distinction the module is careful about must survive the fix: having
    looked and found nothing is silence; being unable to look is not."""
    from scripts.lib import lane_registry as lr

    obs = lr.observe_signal({"kind": "file_mtime", "path": "nope.json"},
                            root=tmp_path, db_query=None)
    assert obs["readable"] is True
    assert obs["last_output_at"] is None
    assert "(absent)" in str(obs["detail"])
