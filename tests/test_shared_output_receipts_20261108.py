"""LQ-20261107-1058 — G3 repair: one manifest row per systemd unit, and a receipt per mode for lanes that shared one log.

Defect (LQ-1054 diff): five systemd units had two ACTIVE registry rows each, and twelve groups of ACTIVE lanes
named one shared log as their output signal, so any mode writing that log turned every mode in the group green.

Synthetic fixtures only (public repo): made-up lane ids, no holdings, no keys, no host paths. The real-tree tests
read this tree's own config/ and the proposed overlay in docs/ops/packets/shared-output-repair-20261108/.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import lane_manifest as lm  # noqa: E402

OVERLAY = ROOT / "docs/ops/packets/shared-output-repair-20261108/registry_rows.PROPOSED.json"
TRAP = ROOT / "scripts/lib/lane_receipt_trap.sh"

#: units with two rows each: the five of LQ-1054 G3 plus one its output-grouped diff could not see (the duplicate
#: declared no output). The plain id survives; the tradeai-* id retires.
DUPLICATE_PAIRS = {
    "telegram-callback-poller": "tradeai-telegram-callback-poller",
    "health-tick": "tradeai-health-tick",
    "n8n-lab-watchdog": "tradeai-n8n-lab-watchdog",
    "platform-maintenance-monthly": "tradeai-platform-maintenance-monthly",
    "platform-maintenance-nightly": "tradeai-platform-maintenance-nightly",
    "platform-maintenance-weekly": "tradeai-platform-maintenance-weekly",
}

#: shared-log groups this task does NOT repair, and why (each is reported in the DONE note with its owner).
HELD_GROUPS = {
    frozenset({"active-trader-micro-recorder-premarket", "active-trader-micro-recorder"}),  # active-trader path
    frozenset({"watchlist-entry-planner-limit", "watchlist-entry-planner-scope"}),  # claimed grok-b-lq1006
    frozenset({"external-market-data-ingest-fundamentals", "external-market-data-ingest"}),  # claimed LQ-940
    frozenset({"holding-protection-advisor-at-5-17", "holding-protection-advisor-lane"}),  # claimed grok-b-lq1006
    frozenset({"schwab-transaction-ingest-classifier", "schwab-transaction-ingest-at-3-18-33-48-9-16"}),  # rule 2
    frozenset({"run-protection-pipeline-at-x-30-9-16", "run-protection-pipeline-at-30-20"}),  # same argv, no mode
}

#: lane -> the code that writes data/runtime/<lane>_last.json each real run.
RECEIPT_WRITERS = {
    "deploy-detect": "scripts/deploy_detect.py",
    "deploy-recompute": "scripts/deploy_recompute.py",
    "deploy-monitor": "scripts/deploy_monitor.py",
    "run-scheduled-quote-refresh-incubator": "scripts/run_scheduled_quote_refresh.sh",
    "run-scheduled-quote-refresh-pending": "scripts/run_scheduled_quote_refresh.sh",
    "run-scheduled-watchpool-alerts-diagnostic": "scripts/run_scheduled_watchpool_alerts.sh",
    "run-scheduled-watchpool-alerts-maturity": "scripts/run_scheduled_watchpool_alerts.sh",
    "run-scheduled-two-way-curation-options": "scripts/run_scheduled_two_way_curation.sh",
    "run-scheduled-two-way-curation-desk": "scripts/run_scheduled_two_way_curation.sh",
    "run-inference-cycle-preopen": "linux_launchers/run_inference_cycle.sh",
    "run-inference-cycle-midday": "linux_launchers/run_inference_cycle.sh",
    "run-inference-cycle-postclose": "linux_launchers/run_inference_cycle.sh",
    "generate-analyst-reports-autonomous-weekly": "scripts/generate_analyst_reports_autonomous.py",
    "generate-analyst-reports-autonomous-full": "scripts/generate_analyst_reports_autonomous.py",
}


def _codes(findings, code):
    return [f for f in findings if f["code"] == code]


def _row(lid, state="ACTIVE", **kw):
    row = {"lane_id": lid, "owner": "platform", "state": state, "expected_cadence_hours": 24}
    row.update(kw)
    return row


def _man(rows):
    reg = {"schema": "LaneRegistry@v1", "lanes": rows, "freshness_contracts": []}
    return lm.build_manifest(reg, {"lanes": []}, {"contracts": []}, generated_at="t", sources={})


def _f(rows):
    return lm.disagreements(_man(rows), allowlist={"lanes": []}, contracts={"contracts": []})


# ── (A) the manifest names a duplicate unit and a shared output ──────────────────────────────────────────────────


def test_two_active_rows_for_one_systemd_unit_are_one_error_naming_both():
    rows = [
        _row("tick", scheduler={"kind": "systemd", "expression": "demo-tick.timer (*:0/5)", "match": "demo-tick.timer"},
             output_signal={"kind": "file_mtime", "path": "data/runtime/tick_last.json"}),
        _row("demo-tick", scheduler={"kind": "systemd", "expression": "demo-tick.timer", "cadence": "*:0/5"},
             output_signal={"kind": "json_key", "path": "data/runtime/tick_last.json", "key": "as_of"}),
        _row("other", scheduler={"kind": "systemd", "expression": "other.service"},
             output_signal={"kind": "json_key", "path": "data/runtime/other.json", "key": "as_of"}),
    ]
    f = _f(rows)
    dup = _codes(f, "DUPLICATE_UNIT_ROW")
    assert len(dup) == 1 and dup[0]["severity"] == "error"
    assert dup[0]["evidence"]["unit"] == "demo-tick" and dup[0]["evidence"]["lanes"] == ["demo-tick", "tick"]
    # the group is one unit, so its shared receipt is not ALSO a shared-output finding
    assert not _codes(f, "SHARED_OUTPUT_SIGNAL")


def test_a_step_lane_and_a_lane_with_its_own_receipt_are_not_duplicates():
    rows = [
        _row("tick", scheduler={"kind": "systemd", "expression": "demo-tick.timer (*:0/5)"},
             output_signal={"kind": "json_key", "path": "data/runtime/tick_last.json", "key": "as_of"}),
        _row("tick-step", scheduler={"kind": "systemd", "expression": "demo-tick.timer step deadman (*/15)"},
             output_signal={"kind": "file_mtime", "path": "data/runtime/tick_last.json"}),
        _row("cycle", scheduler={"kind": "systemd", "expression": "demo-cycle.timer"},
             output_signal={"kind": "file_mtime", "path": "data/runtime/cycle_last.json"}),
        _row("cycle-effects", scheduler={"kind": "systemd", "expression": "demo-cycle.timer"},
             output_signal={"kind": "json_key", "path": "data/runtime/cycle-effects_last.json", "key": "ok_at"}),
        _row("daemon", scheduler={"kind": "systemd", "expression": "demo-d.service (Restart=always)"},
             output_signal={"kind": "file_mtime", "path": "logs/d.log"}),
        _row("demo-daemon", scheduler={"kind": "systemd", "expression": "demo-d.service"},
             output_signal={"kind": "none", "reason": "JOURNAL_ONLY"}),
    ]
    f = _f(rows)
    assert [x["evidence"]["lanes"] for x in _codes(f, "DUPLICATE_UNIT_ROW")] == [["daemon", "demo-daemon"]]
    # the step shares its parent's receipt path: not a duplicate unit, but still one output proving two lanes
    assert [x["evidence"]["lanes"] for x in _codes(f, "SHARED_OUTPUT_SIGNAL")] == [["tick", "tick-step"]]


def test_a_retired_duplicate_is_not_a_duplicate():
    rows = [
        _row("tick", scheduler={"kind": "systemd", "expression": "demo-tick.timer (*:0/5)"},
             output_signal={"kind": "json_key", "path": "data/runtime/tick_last.json", "key": "as_of"}),
        _row("demo-tick", state="RETIRED", scheduler={"kind": "systemd", "expression": "demo-tick.timer"},
             output_signal={"kind": "none"}),
    ]
    assert not _codes(_f(rows), "DUPLICATE_UNIT_ROW")


def test_lanes_sharing_one_log_are_one_warn_naming_every_lane():
    rows = [
        _row("job-a", scheduler={"kind": "cron", "expression": "0 8 * * *", "match": "scripts/job.sh a"},
             output_signal={"kind": "file_mtime", "path": "logs/job.log"}),
        _row("job-b", scheduler={"kind": "cron", "expression": "0 9 * * *", "match": "scripts/job.sh b"},
             output_signal={"kind": "file_mtime", "path": "$STATE_ROOT/logs/job.log"}),
        _row("job-c", state="RETIRED", scheduler={"kind": "cron", "expression": "0 9 * * *", "match": "x"},
             output_signal={"kind": "file_mtime", "path": "logs/job.log"}),
        _row("solo", scheduler={"kind": "cron", "expression": "0 9 * * *", "match": "scripts/solo.py"},
             output_signal={"kind": "json_key", "path": "data/runtime/solo_last.json", "key": "ok_at"}),
    ]
    shared = _codes(_f(rows), "SHARED_OUTPUT_SIGNAL")
    assert len(shared) == 1 and shared[0]["severity"] == "warn"
    assert shared[0]["evidence"] == {"path": "logs/job.log", "lanes": ["job-a", "job-b"]}


# ── (D) the overlay: one source per unit, a receipt per mode ─────────────────────────────────────────────────────


def _real():
    load = lambda rel: json.loads((ROOT / rel).read_text(encoding="utf-8"))  # noqa: E731
    return (load("config/lane_registry.json"), load("config/n8n_run_allowlist.json"),
            load("config/n8n_health_contracts.json"))


def _overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


def _shared_groups(findings):
    return {frozenset(f["evidence"]["lanes"]) for f in _codes(findings, "SHARED_OUTPUT_SIGNAL")}


def test_current_registry_duplicates_are_exactly_the_known_five():
    reg, allow, con = _real()
    f = lm.disagreements(lm.build_manifest(reg, allow, con, generated_at="t", sources={}), allowlist=allow,
                         contracts=con)
    found = {frozenset(x["evidence"]["lanes"]) for x in _codes(f, "DUPLICATE_UNIT_ROW")}
    assert found <= {frozenset(p) for p in DUPLICATE_PAIRS.items()}


def test_overlay_leaves_one_row_per_unit_and_only_the_held_shared_groups():
    reg, allow, con = _real()
    patched = lm.apply_registry_overlay(reg, _overlay())
    man = lm.build_manifest(patched, allow, con, generated_at="t", sources={})
    assert lm.validate(man) == []
    f = lm.disagreements(man, allowlist=allow, contracts=con)
    assert _codes(f, "DUPLICATE_UNIT_ROW") == []
    assert _shared_groups(f) <= HELD_GROUPS, _shared_groups(f) - HELD_GROUPS
    lanes = {l["id"]: l for l in man["lanes"]}
    for keep, retire in DUPLICATE_PAIRS.items():
        assert lm.dispatchable(lanes[keep]) and not lm.dispatchable(lanes[retire])
        assert lanes[retire]["legacy"]["superseded_by"] == keep
        if keep != "telegram-callback-poller":  # the better signal moved onto the survivor
            assert lanes[keep]["output"]["signal"]["kind"] == "json_key", keep
    for lid in RECEIPT_WRITERS:
        sig = lanes[lid]["output"]["signal"]
        assert sig == {**sig, "kind": "json_key", "path": f"data/runtime/{lid}_last.json", "key": "ok_at",
                       "evidence": "SCRIPT_RECEIPT"}, lid


def test_overlay_does_not_mutate_its_input_and_refuses_an_unknown_lane():
    reg, _, _ = _real()
    before = json.dumps(reg, sort_keys=True)
    lm.apply_registry_overlay(reg, _overlay())
    assert json.dumps(reg, sort_keys=True) == before
    bad = _overlay()
    bad["output_signal"]["no-such-lane"] = {"kind": "none"}
    with pytest.raises(ValueError, match="no-such-lane"):
        lm.apply_registry_overlay(reg, bad)


def test_every_receipt_lane_in_the_overlay_has_a_writer_in_code():
    ov = _overlay()
    receipt_lanes = {lid for lid, s in ov["output_signal"].items() if s.get("key") == "ok_at"}
    assert receipt_lanes == set(RECEIPT_WRITERS)
    for lid, rel in RECEIPT_WRITERS.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        stem = lid.rsplit("-", 1)[0]
        assert lid in text or stem in text, f"{rel} never names {lid}"


# ── (B) python entrypoints: a receipt per real run ───────────────────────────────────────────────────────────────


def _receipt(state, lane):
    p = Path(state) / "data" / "runtime" / f"{lane}_last.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    return tmp_path


def test_run_main_writes_a_receipt_only_for_a_real_run(state):
    from scripts.lib.lane_receipt_main import run_main

    assert run_main("demo-lane", lambda: 0, script="demo.py", argv=["--apply"]) == 0
    r = _receipt(state, "demo-lane")
    assert r["exit"] == 0 and r["ok_at"] and r["script"] == "demo.py"
    assert run_main("demo-preview", lambda: 0, script="demo.py", argv=[]) == 0
    assert _receipt(state, "demo-preview") is None


def test_run_main_records_a_failed_exit_and_an_exception(state):
    from scripts.lib.lane_receipt_main import run_main

    assert run_main("demo-rc", lambda: 1, script="demo.py", argv=["--apply"]) == 1
    r = _receipt(state, "demo-rc")
    assert r["exit"] == 1 and r.get("ok_at") is None

    def boom():
        raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        run_main("demo-exc", boom, script="demo.py", argv=["--apply"])
    r = _receipt(state, "demo-exc")
    assert r["exit"] == 1 and "RuntimeError" in (r.get("error") or "") and r.get("ok_at") is None

    def usage():
        raise SystemExit(2)

    with pytest.raises(SystemExit):
        run_main("demo-exit", usage, script="demo.py", argv=["--apply"])
    assert _receipt(state, "demo-exit")["exit"] == 2


@pytest.mark.parametrize("rel,lane", [("scripts/deploy_detect.py", "deploy-detect"),
                                      ("scripts/deploy_recompute.py", "deploy-recompute"),
                                      ("scripts/deploy_monitor.py", "deploy-monitor")])
def test_deploy_entrypoints_run_main_through_the_receipt(rel, lane):
    text = (ROOT / rel).read_text(encoding="utf-8")
    tail = text[text.rindex('if __name__ == "__main__":'):]
    assert re.search(rf'run_main\(\s*"{lane}"\s*,\s*main\b', tail), rel


# ── (C) shell wrappers: an EXIT trap writes one receipt per mode lane ────────────────────────────────────────────


def _fake_py(tmp_path, child_rc=0):
    """A $PY that runs the real interpreter for the receipt CLI and exits ``child_rc`` for any other script."""
    p = tmp_path / "fakepy"
    p.write_text("#!/usr/bin/env bash\n"
                 'case "$1" in *completion_compound_receipt.py) exec "' + sys.executable + '" "$@" ;; esac\n'
                 f"exit {child_rc}\n", encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def _run_snippet(tmp_path, body, env_extra=None):
    script = tmp_path / "s.sh"
    script.write_text("#!/usr/bin/env bash\nset -euo pipefail\n"
                      f'source "{TRAP}"\n' + body, encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "TRADEAI_STATE_ROOT": str(tmp_path), "HOME": str(tmp_path)}
    env.update(env_extra or {})
    return subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=60)


def test_trap_writes_a_receipt_per_lane_and_keeps_the_exit_code(tmp_path):
    py = _fake_py(tmp_path)
    r = _run_snippet(tmp_path, f'tradeai_lane_receipt_on_exit "{py}" lane-x lane-y\nfalse\n')
    assert r.returncode == 1
    for lane in ("lane-x", "lane-y"):
        rec = _receipt(tmp_path, lane)
        assert rec and rec["exit"] == 1 and rec.get("ok_at") is None and rec["started_at"]
    r = _run_snippet(tmp_path, f'tradeai_lane_receipt_on_exit "{py}" lane-ok\necho fine\n')
    assert r.returncode == 0 and _receipt(tmp_path, "lane-ok")["ok_at"]


def test_trap_honours_an_explicit_rc_and_a_lock_skip(tmp_path):
    py = _fake_py(tmp_path)
    r = _run_snippet(tmp_path, f'tradeai_lane_receipt_on_exit "{py}" lane-q\nTRADEAI_LANE_RC=4\nexit 0\n')
    assert r.returncode == 0  # the wrapper's own exit is unchanged; the receipt carries the child's code
    assert _receipt(tmp_path, "lane-q")["exit"] == 4
    _run_snippet(tmp_path, f'tradeai_lane_receipt_on_exit "{py}" lane-l\nexit 75\n')
    assert _receipt(tmp_path, "lane-l")["summary"]["status"] == "RUN_SKIPPED_LOCK"


@pytest.mark.parametrize("mode,lane,rc", [("desk-emit", "run-scheduled-two-way-curation-desk", 0),
                                          ("options-edge", "run-scheduled-two-way-curation-options", 3)])
def test_two_way_curation_writes_its_mode_receipt(tmp_path, mode, lane, rc):
    proj = tmp_path / "proj"
    (proj / "logs").mkdir(parents=True)
    py = _fake_py(tmp_path, child_rc=rc)
    env = {"PATH": os.environ["PATH"], "TRADEAI_STATE_ROOT": str(tmp_path), "HOME": str(tmp_path),
           "PROJ": str(proj), "PY": str(py), "TRADEAI_ENV": str(tmp_path / "no-env")}
    r = subprocess.run(["bash", str(ROOT / "scripts/run_scheduled_two_way_curation.sh"), mode], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == rc, r.stderr
    rec = _receipt(tmp_path, lane)
    assert rec and rec["exit"] == rc and bool(rec.get("ok_at")) == (rc == 0)
    other = ({"run-scheduled-two-way-curation-desk", "run-scheduled-two-way-curation-options"} - {lane}).pop()
    assert _receipt(tmp_path, other) is None


def test_two_way_curation_dry_run_writes_no_receipt(tmp_path):
    env = {"PATH": os.environ["PATH"], "TRADEAI_STATE_ROOT": str(tmp_path), "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(ROOT / "scripts/run_scheduled_two_way_curation.sh"), "desk-emit", "--dry-run"],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and not (tmp_path / "data").exists()


@pytest.mark.parametrize("rel,lane_expr", [
    ("scripts/run_scheduled_quote_refresh.sh", "run-scheduled-quote-refresh-"),
    ("scripts/run_scheduled_watchpool_alerts.sh", "run-scheduled-watchpool-alerts-"),
])
def test_env_sourcing_wrappers_arm_the_trap_before_their_first_exit(rel, lane_expr):
    # These two source the host .env at the top, so a test may not run them; prove the order statically.
    text = (ROOT / rel).read_text(encoding="utf-8")
    arm = text.index("tradeai_lane_receipt_on_exit")
    assert lane_expr in text[arm:text.index("\n", arm)]
    assert "lane_receipt_trap.sh" in text[:arm]
    loop_end = text.index("\ndone\n")
    assert loop_end < arm < text.index("{ log \"ABORT")  # the first guard exit


def test_quote_refresh_receipt_carries_the_child_exit_not_the_wrapper_exit():
    text = (ROOT / "scripts/run_scheduled_quote_refresh.sh").read_text(encoding="utf-8")
    assert re.search(r"_EXIT=\$\{PIPESTATUS\[0\]\}\s*\n(\s*#[^\n]*\n)*\s*TRADEAI_LANE_RC=\$_EXIT", text)
