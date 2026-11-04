"""Nudger P2: the lane is registered, and it can only ever run dry while its stage is shadow (2026-11-03).

Board item 16 / P2 of docs/ops/NUDGER_N8N_MIGRATION_PROPOSAL_20261103.md.

The claim this file makes is narrow and mechanical: `agent_nudge` is in the executor's allowlist pointing at the
repo script, its registry row is a dispatcher row whose scheduler.stage is `shadow`, and the stage clamp — the code
that runs on every drain pass — turns a requested LIVE run into a dry run. A reviewer or the lead can therefore
dispatch a live fire at this lane and prove nothing is typed.

Hermetic: reads two committed config files and calls the pure clamp. No tmux, no network, no state write.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib.lane_stage_clamp import clamp_mode, load_stage_rows  # noqa: E402

LANE = "agent_nudge"
REGISTRY = ROOT / "config" / "lane_registry.json"
ALLOWLIST = ROOT / "config" / "n8n_run_allowlist.json"


def _row():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["lanes"]
    found = [r for r in rows if r.get("lane_id") == LANE]
    assert len(found) == 1, f"{LANE}: expected exactly one registry row, found {len(found)}"
    return found[0]


def _entry():
    lanes = json.loads(ALLOWLIST.read_text(encoding="utf-8"))["lanes"]
    found = [e for e in lanes if e.get("lane_id") == LANE]
    assert len(found) == 1, f"{LANE}: expected exactly one allowlist entry, found {len(found)}"
    return found[0]


# ── the registry row ────────────────────────────────────────────────────────────────────────────────


def test_the_row_is_a_dispatcher_row_in_shadow():
    sched = _row()["scheduler"]
    assert sched["kind"] == "n8n"
    assert sched["expression"] == "dispatcher"
    assert sched["stage"] == "shadow", "this lane must stay shadow until an operator-approved flip"


def test_the_row_is_dispatchable_and_carries_no_forbidden_token():
    row = _row()
    assert LD.dispatch_mode(row) == "dry_run"
    assert LD.dispatchable(row) is True
    assert LD.forbidden_hits(row) == [], "the row text must not name a forbidden class"


def test_the_row_keeps_the_live_cron_line_for_rollback():
    """P2 does not stop the host timer; the rollback record must say what the timer runs."""
    before = _row()["scheduler_before_cutover"]
    assert before["kind"] == "cron"
    assert "agent_nudger.py" in before["command_text"]
    assert "--apply" in before["command_text"], "the live line is the one that actually types"


# ── the allowlist entry ────────────────────────────────────────────────────────────────────────────


def test_the_entry_points_at_the_repo_script_with_a_real_dry_run_arg():
    e = _entry()
    assert e["command"][1] == "scripts/agent_nudger.py"
    assert e["dry_run_arg"] == ["--dry-run"], (
        "the dispatcher's shadow step requires a NON-EMPTY dry_run_arg (lane_dispatch.dispatch_eligible)")
    # While the row is shadow there is NO live argv at all, so no fire can type even if the stage clamp were
    # bypassed. The stage-flip PR sets ["--apply"] and brings its own test.
    assert e["live_arg"] is None
    assert e["lock"].startswith("/") and not e["lock"].endswith(".dryrun")
    assert e["timeout_s"] == 120
    assert e["market_gate"] is False
    assert e["output_signal"] == "data/coordination/agent_nudger/state.json"


def test_the_entry_declares_its_environment_instead_of_inheriting_it():
    e = _entry()
    assert isinstance(e.get("env_names"), list), "enforce mode refuses a lane with no declared names"
    assert e.get("env_allowlist_mode") == "enforce"


def test_the_executor_accepts_the_entry():
    sys.path.insert(0, str(ROOT / "scripts"))
    import n8n_run_executor as X  # noqa: E402

    e = _entry()
    assert X.env_policy_problem(e) is None
    assert X.validate_entry(e) is None


# ── the shadow guarantee, proved by the clamp the executor actually calls ──────────────────────────


def test_a_requested_live_run_is_clamped_to_dry_run():
    rows = load_stage_rows(REGISTRY)
    got = clamp_mode(LANE, "live", rows)
    assert got["requested_mode"] == "live"
    assert got["effective_mode"] == "dry_run"
    assert got["clamped"] is True and got["reason"] == "stage_shadow"


def test_the_clamp_assertion_is_not_vacuous():
    """With the stage flipped the SAME call lets live through — so the test above fails if the row is not shadow."""
    rows = load_stage_rows(REGISTRY)
    flipped = [dict(r, scheduler={**r["scheduler"], "stage": "canary"}) if r.get("lane_id") == LANE else r
               for r in rows]
    got = clamp_mode(LANE, "live", flipped)
    assert got["effective_mode"] == "live" and got["clamped"] is False


def test_the_script_still_defaults_to_dry_and_refuses_two_modes_at_once():
    import agent_nudger as N  # noqa: E402

    # --dry-run is accepted and means exactly what the bare command means.
    assert N.main(["--dry-run", "--state", "/dev/null"]) == 0
    # --apply and --dry-run together are an operator mistake, not a silent choice.
    try:
        N.main(["--apply", "--dry-run"])
    except SystemExit as exc:  # argparse exits 2 on a mutually-exclusive violation
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("--apply --dry-run must be refused")


# ── expected output: the contract's rule must be executable, not decorative (F2/P2) ─────────────────


def test_the_contract_declares_a_valid_executable_expected_output_rule():
    contracts = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))["contracts"]
    c = [x for x in contracts if x.get("id") == LANE][0]
    eo = c.get("expected_output")
    assert isinstance(eo, dict), "a shadow lane's contract must carry an expected_output rule"
    from scripts.lib.n8n_output_verdict import validate_expected_output  # noqa: PLC0415

    assert validate_expected_output(eo) == []
    assert eo["rule"] == "empty_allowed" and eo["produced_field"] == "produced_count"
    assert eo["empty_allowed_reasons"] == ["nothing_due"]
    assert eo["on_violation"]["run_state"] == "RUN_FAILED"


def test_the_lane_emits_the_count_the_contract_reads(monkeypatch, capsys, tmp_path):
    """The rule reads produced_count from LANE_OUTPUT on stderr; a rule no run can satisfy is not a rule."""
    import agent_nudger as N  # noqa: PLC0415

    monkeypatch.setattr(N, "list_sessions", lambda cfg: (["fixture-session-a", "fixture-session-b"], True))
    monkeypatch.setattr(N, "capture", lambda s: ("❯ \n  ? for shortcuts", True))
    rc = N.main(["--dry-run", "--state", str(tmp_path / "s.json"), "--ledger", str(tmp_path / "l.jsonl")])
    assert rc == 0
    captured = capsys.readouterr()
    lines = [ln for ln in captured.err.splitlines() if ln.startswith("LANE_OUTPUT ")]
    assert len(lines) == 1, captured.err
    block = json.loads(lines[0][len("LANE_OUTPUT "):])
    assert block["schema"] == "LaneOutput@v1" and block["lane_id"] == LANE
    # Dry run: produced == the "would:" lines it printed, and attempted == the sessions it inspected.
    assert block["produced_count"] == captured.out.count("would: ")
    assert block["attempted_count"] == 2
    assert block["unit"] == "agent nudges typed"
    assert block["produced_count"] or block["empty_reason"] == "nothing_due"


# ── A: the rule is CONNECTED to the executor, not merely declared (review 2026-11-04) ───────────────


def _shipped_entry():
    lanes = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))["lanes"]
    return [e for e in lanes if e.get("lane_id") == LANE][0]


def test_the_shipped_entry_asks_the_executor_to_enforce_the_rule():
    """Without output_receipt v2 the executor answers declared_not_enforced before it reads the rule at all."""
    assert _shipped_entry().get("output_receipt") == "v2"


def _live_attempt(tmp_path, monkeypatch, *, produced: int, empty_reason):
    """Write the attempt receipt the lane writes on a live run, then return the executor's own receipt for it."""
    from scripts.lib import lane_last_receipt as LR  # noqa: PLC0415

    run_id, sha = "run-fixture-1", "a" * 40
    monkeypatch.setenv(LR.RUN_ID_ENV, run_id)
    monkeypatch.setenv(LR.RUN_MODE_ENV, "live")
    monkeypatch.setenv(LR.CODE_SHA_ENV, sha)
    monkeypatch.setenv(LR.RUN_ATTEMPT_ENV, "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    # A future start would be "after" the receipt's own clock: the window must bracket the write, as a real run's does.
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415
    started = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    path = LR.receipt_path(LANE, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    LR.write_lane_receipt(LANE, ok=True, started_at=started, path=path, produced_count=produced,
                          attempted_count=2, skipped_reasons={}, empty_reason=empty_reason,
                          script="scripts/agent_nudger.py")
    # The verdict binds the receipt's own clock to the executor's attempt window, so build the window from the file
    # just written: a synthetic 2030 window makes a real receipt look "outside the attempt" (receipt_time_invalid).
    written = json.loads(path.read_text(encoding="utf-8"))
    receipt = {"state": "RUN_DONE", "run_id": run_id, "attempt": 1, "code_sha": sha,
               "started_at": started, "finished_at": written["finished_at"]}
    return receipt, started


def test_the_executor_evaluates_the_rule_and_allows_an_honest_empty(tmp_path, monkeypatch):
    import n8n_run_executor as X  # noqa: PLC0415

    receipt, _ = _live_attempt(tmp_path, monkeypatch, produced=0, empty_reason="nothing_due")
    # The PRODUCTION rule source, parsed by the executor's own parser — not a hand-built dict.
    outputs = X.expected_outputs_source(ROOT / "config" / "n8n_health_contracts.json")
    out = X.apply_output_verdict(dict(receipt), outputs, lane_id=LANE, mode="live",
                                 state_root=tmp_path, entry=_shipped_entry())
    assert out["output_verdict"]["verdict"] != "declared_not_enforced", out["output_verdict"]
    assert out["output_verdict"]["verdict"] == "empty_allowed", out["output_verdict"]
    assert out["state"] == "RUN_DONE"


def test_the_executor_REFUSES_a_live_run_that_typed_nothing_for_no_stated_reason(tmp_path, monkeypatch):
    """The control: exit 0 with nothing produced and no allowed reason is RUN_FAILED, not success."""
    import n8n_run_executor as X  # noqa: PLC0415

    receipt, _ = _live_attempt(tmp_path, monkeypatch, produced=0, empty_reason=None)
    # The PRODUCTION rule source, parsed by the executor's own parser — not a hand-built dict.
    outputs = X.expected_outputs_source(ROOT / "config" / "n8n_health_contracts.json")
    out = X.apply_output_verdict(dict(receipt), outputs, lane_id=LANE, mode="live",
                                 state_root=tmp_path, entry=_shipped_entry())
    assert out["output_verdict"]["verdict"] == "empty_violation", out["output_verdict"]
    assert out["state"] == "RUN_FAILED" and out["reason"] == "empty_output", out


# ── C: a refused keystroke is not a nudge ───────────────────────────────────────────────────────────


def test_a_failed_tmux_send_is_not_counted_as_a_nudge(monkeypatch, capsys, tmp_path):
    import agent_nudger as N  # noqa: PLC0415
    from types import SimpleNamespace  # noqa: PLC0415

    monkeypatch.setattr(N, "list_sessions", lambda cfg: (["fixture-session"], True))
    monkeypatch.setattr(N, "capture", lambda s: ("❯ \n  ? for shortcuts", True))
    # Every tmux call fails: the pane is gone. The run must record a skipped reason, not a nudge.
    monkeypatch.setattr(N.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    # An idle session is only nudged once it is known and quiet: seed state so decide() votes NUDGE.
    import hashlib  # noqa: PLC0415
    screen = "❯ \n  ? for shortcuts"
    state = {"fixture-session": {"hash": hashlib.sha256(N.tail_of(screen).encode()).hexdigest(),
                                 "changed_at": 0, "nudged_at": 0}}
    (tmp_path / "s.json").write_text(json.dumps(state), encoding="utf-8")
    rc = N.main(["--apply", "--state", str(tmp_path / "s.json"), "--ledger", str(tmp_path / "l.jsonl")])
    assert rc == 0
    err = capsys.readouterr().err
    block = json.loads([ln for ln in err.splitlines() if ln.startswith("LANE_OUTPUT ")][0][len("LANE_OUTPUT "):])
    assert block["produced_count"] == 0, block
    assert block["skipped_reasons"].get("send_failed") == 1, block
    assert not (tmp_path / "l.jsonl").exists() or (tmp_path / "l.jsonl").read_text() == ""


# ── F1 (cc3, 2026-11-04): a failure to OBSERVE is not a decision about the session ────────────────────


def _run_with(returncodes):
    """A fake tmux: `tmux ls` then one capture per session. Returns (fake, calls)."""
    from types import SimpleNamespace
    calls = []
    def run(argv, **kw):
        calls.append(argv)
        rc = returncodes.get(argv[1], 0)
        out = "cx-openai\n" if argv[1] == "ls" and rc == 0 else ""
        return SimpleNamespace(returncode=rc, stdout=out, stderr="")
    return run, calls


def test_a_failed_capture_is_reported_as_dependency_unavailable_not_as_idle(tmp_path, monkeypatch, capsys):
    """F1: at 392134248c29 a capture failure (rc=1, empty stdout) became `wait idle=0m`, produced 0 and
    empty_reason nothing_due — a blind run indistinguishable from a quiet one."""
    import json as _json

    import agent_nudger as N  # noqa: PLC0415
    run, calls = _run_with({"capture-pane": 1})
    real_ls, real_cap = N.list_sessions, N.capture
    monkeypatch.setattr(N, "list_sessions", lambda cfg: real_ls(cfg, run=run))
    monkeypatch.setattr(N, "capture", lambda sess: real_cap(sess, run=run))
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    assert N.main(["--dry-run", "--state", str(tmp_path / "s.json"),
                   "--ledger", str(tmp_path / "l.jsonl"), "--coord-dir", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    block = _json.loads([ln for ln in err.splitlines() if ln.startswith("LANE_OUTPUT ")][0].split(" ", 1)[1])
    assert "dependency_unavailable" in block["skipped_reasons"], block
    assert block["attempted_count"] == 0, "a session whose capture failed was counted as inspected"
    assert block["empty_reason"] == "dependency_unavailable", block


def test_a_failed_tmux_ls_is_not_the_same_run_as_no_sessions(tmp_path, monkeypatch, capsys):
    """F1: at 392134248c29 `tmux ls` rc=1 produced attempted 0 / nothing_due, the same evidence as a quiet machine."""
    import json as _json

    import agent_nudger as N  # noqa: PLC0415
    run, _ = _run_with({"ls": 1})
    real_ls, real_cap = N.list_sessions, N.capture
    monkeypatch.setattr(N, "list_sessions", lambda cfg: real_ls(cfg, run=run))
    monkeypatch.setattr(N, "capture", lambda sess: real_cap(sess, run=run))
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    assert N.main(["--dry-run", "--state", str(tmp_path / "s.json"),
                   "--ledger", str(tmp_path / "l.jsonl"), "--coord-dir", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    block = _json.loads([ln for ln in err.splitlines() if ln.startswith("LANE_OUTPUT ")][0].split(" ", 1)[1])
    assert "dependency_unavailable" in block["skipped_reasons"] and block["empty_reason"] == "dependency_unavailable", block


def test_a_blind_run_settles_as_degraded_not_as_a_successful_shadow_run(monkeypatch, capsys, tmp_path):
    """F2 (cc3 + cx-openai-2, 2026-11-04): main() returned 0 unconditionally, so a run whose producer said
    dependency_unavailable still settled RUN_DONE and no consumer saw a failure. Fails at 7df0f53ce."""
    import agent_nudger as N  # noqa: PLC0415
    monkeypatch.setattr(N, "list_sessions", lambda cfg: ([], True))
    assert N.main(["--dry-run", "--state", str(tmp_path / "s.json"),
                   "--ledger", str(tmp_path / "l.jsonl")]) == 0          # genuinely quiet stays 0
    monkeypatch.setattr(N, "list_sessions", lambda cfg: ([], False))   # tmux ls failed
    assert N.main(["--dry-run", "--state", str(tmp_path / "s2.json"),
                   "--ledger", str(tmp_path / "l2.jsonl")]) == 2         # blind is not a success


def test_the_registry_row_claims_no_signal_the_shadow_lane_cannot_produce(monkeypatch, tmp_path):
    """F1 (cc3, 2026-11-04): the row was ACTIVE with a file_mtime signal on a file only --apply writes, so the shadow
    lane could never advance it and every cycle reported a false SILENT. Fails at 7df0f53ce."""
    import json as _json  # noqa: PLC0415
    from pathlib import Path as _P  # noqa: PLC0415
    doc = _json.loads((_P(__file__).resolve().parents[1] / "config" / "lane_registry.json").read_text())
    row = [r for r in doc["lanes"] if r.get("lane_id") == "agent_nudge"][0]
    assert row["state"] != "ACTIVE", "an ACTIVE row must be able to produce its own health signal"
    sig = row.get("output_signal") or {}
    assert not (sig.get("kind") == "file_mtime" and "state.json" in str(sig.get("path"))), sig
