"""scripts/lib/n8n_broker_read_carveout.py — AGENTS.md 19.0.0 §27.1 (PROPOSED): n8n may schedule the audited
read-only broker lanes, and nothing else.

Operator 2026-10-22 (verbatim): "N8N can read the broker because right now we're only doing reading of the broker.
We're not doing any trading. So I want to amendment."

Pins:
  * while CARVEOUT_STATUS is not ACTIVE every command is refused with exactly `carveout_not_active`, no audit runs,
    and pipeline_manifest.forbidden_command_tokens behaves exactly as the plain substring test;
  * when ACTIVE (passed explicitly here; only the ratifying edit sets the module constant) a read lane is admitted only
    as its exact command, only on a clean audit, and only while every trading lock is LOCKED and the operator's Schwab
    switch resolves read_only;
  * order, stop-write, cancel, replace, preflight, 2FA, place_order, live/paper, sender, wrapper and extra-argument
    commands are refused whatever the status;
  * the market-data reads pass the real §24.11 audit.

Hermetic: no broker, no network, no lock or switch file is read (locks and mode are injected). TRADE_AI_CI=1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import broker_read_sync_policy as P  # noqa: E402
from lib import n8n_broker_read_carveout as C  # noqa: E402
from scripts.pipelines import pipeline_manifest as PM  # noqa: E402

LOCKED = {b: {"locked": True, "reason": "no operator unlock file (default: locked)"} for b in P.LOCK_BROKERS}
READ_ONLY = {"mode": "read_only", "source": "config/schwab_access_mode.yaml"}


def ok_audit(step):
    return {"ok": True, "findings": []}


def no_audit(step):  # proves the audit is never reached
    raise AssertionError(f"audit ran for {step.id}")


def lane_commands():
    """Every (step, mode, command) the carve-out covers, in the three accepted spellings."""
    out = []
    for step in C.READ_LANES:
        for mode in ("dry_run", "apply"):
            argv = step.argv(mode)
            if argv is None:
                continue
            out.append((step, mode, " ".join([step.script, *argv])))
            out.append((step, mode, " ".join(["$PY", step.script, *argv])))
            out.append((step, mode, ["/home/x/.venv/bin/python3", step.script, *argv]))
    return out


LANES = lane_commands()
IDS = [f"{s.id}:{m}:{i % 3}" for i, (s, m, _c) in enumerate(LANES)]

ORDER_AND_STOP = (
    "scripts/alpaca_stop_manager.py",
    "scripts/alpaca_stop_manager.py --apply",
    "scripts/broker_stop_reconcile.py --apply",
    "scripts/fidelity_stop_sync.py",
    "scripts/schwab_transport.py place_order",
    "scripts/brokers/options_order_pilot.py --live",
    "scripts/proposal_live_submit.py --apply",
    "scripts/brokers/approval_service.py --request-2fa",
    "scripts/defense_execution.py --apply",
    "scripts/options_lifecycle_alerts.py",
    "scripts/active_trader/runner.py",
    "scripts/schwab_token_manager.py reauth-url",
    "scripts/alpaca_paper_adapter.py --submit",
    "scripts/send_telegram.py --text hi",
    "scripts/positions_sync.py --apply --live",
    "scripts/positions_sync.py --apply; scripts/schwab_transport.py place_order",
    "scripts/positions_sync.py --apply && echo done",
    "scripts/positions_sync.py --apply | tee /tmp/x",
    "bash scripts/market_day_gate.sh scripts/positions_sync.py --apply",
    "flock -n /tmp/x.lock scripts/positions_sync.py --apply",
    "scripts/schwab_position_sync.py --apply --account all",
    "scripts/snaptrade_sync.py --apply --trade",
    "scripts/stop_health_check.py --quiet --write-stops",
    "scripts/options_chain_snapshot.py --place-order",
    "$PY",
    "",
)


# ------------------------------------------------------------------------------------------- the set

def test_status_is_proposed_until_the_ratifying_edit():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    ratified = "| 19.0.0 | 2026-10-22 | ACTIVE |" in agents
    assert C.CARVEOUT_STATUS == ("ACTIVE" if ratified else "PROPOSED")


def test_read_lanes_are_the_section_24_11_steps_plus_the_market_data_reads():
    assert C.READ_LANES[: len(P.STEPS)] == P.STEPS, "the §24.11 steps, byte for byte and in order"
    assert C.READ_LANES[len(P.STEPS):] == C.MARKET_DATA_READS
    assert [s.script for s in C.MARKET_DATA_READS] == ["scripts/options_chain_snapshot.py",
                                                        "scripts/sweep_schwab_instruments.py"]
    for step in C.READ_LANES:
        assert P.excluded_family(step.script) is None and P.runtime_denied(step.script) is None, step.script
        assert (ROOT / step.script).is_file(), step.script


def test_no_read_lane_command_carries_a_never_token():
    for step, mode, cmd in LANES:
        assert C.never_hits(cmd) == [], (step.id, mode, cmd)


# ------------------------------------------------------------------------------------------- PROPOSED

@pytest.mark.parametrize("cmd", [c for _s, _m, c in LANES] + list(ORDER_AND_STOP))
def test_not_active_refuses_everything_without_running_the_audit(cmd):
    for status in (None, "PROPOSED", "", "active", "Active", "ACTIVE "):
        if status is None and C.CARVEOUT_STATUS == "ACTIVE":
            continue
        assert C.static_refusals(cmd, status=status, audit_fn=no_audit) == ["carveout_not_active"]
        verdict = C.admit(cmd, status=status, audit_fn=no_audit, lock_fn=lambda: LOCKED, mode_fn=lambda: READ_ONLY)
        assert verdict["admitted"] is False and verdict["refusals"] == ["carveout_not_active"]
        assert C.runtime_refusals(status=status, lock_fn=lambda: LOCKED,
                                  mode_fn=lambda: READ_ONLY) == ["carveout_not_active"]


@pytest.mark.parametrize("cmd", [c for _s, _m, c in LANES if isinstance(c, str)])
def test_forbidden_command_tokens_is_the_plain_test_while_not_active(cmd, monkeypatch):
    monkeypatch.setattr(C, "CARVEOUT_STATUS", "PROPOSED")
    plain = [t for t in PM.FORBIDDEN_COMMAND_TOKENS if t in cmd]
    assert PM.forbidden_command_tokens(cmd) == plain
    assert PM.forbidden_command_tokens(cmd, n8n_broker_read=True) == plain


def test_pipeline_validate_still_refuses_a_broker_read_step(monkeypatch):
    monkeypatch.setattr(C, "CARVEOUT_STATUS", "ACTIVE")  # even ACTIVE: a pipeline step is not an n8n lane
    manifest = {"schema": PM.MANIFEST_SCHEMA, "pipeline": "p", "stages": {"s": {"steps": [
        {"id": "a", "cron_line": 1, "command": "scripts/positions_sync.py --apply", "timeout": "60"}]}}}
    errs = PM.validate(manifest)
    assert any("excluded token positions_sync.py" in e for e in errs), errs


# ------------------------------------------------------------------------------------------- ACTIVE

@pytest.mark.parametrize("step,mode,cmd", LANES, ids=IDS)
def test_active_admits_each_exact_read_lane(step, mode, cmd):
    assert C.static_refusals(cmd, status="ACTIVE", audit_fn=ok_audit) == []
    matched, matched_mode = C.match_lane(cmd)
    # stop_health runs the same argv in both modes; the first matching mode is reported
    assert matched == step and matched.argv(matched_mode) == step.argv(mode)
    verdict = C.admit(cmd, status="ACTIVE", audit_fn=ok_audit, lock_fn=lambda: LOCKED, mode_fn=lambda: READ_ONLY)
    assert verdict["admitted"] is True and verdict["lane"] == step.id and verdict["mode"] == matched_mode
    assert verdict["schema"] == "N8nBrokerReadAdmission@v1"


@pytest.mark.parametrize("cmd", ORDER_AND_STOP)
def test_order_and_stop_lanes_are_always_refused(cmd):
    for status in ("PROPOSED", "ACTIVE"):
        refusals = C.static_refusals(cmd, status=status, audit_fn=ok_audit)
        assert refusals, (status, cmd)
        verdict = C.admit(cmd, status=status, audit_fn=ok_audit, lock_fn=lambda: LOCKED, mode_fn=lambda: READ_ONLY)
        assert verdict["admitted"] is False
        hits = [t for t in PM.FORBIDDEN_COMMAND_TOKENS if t in cmd]
        assert C.exempt_command_tokens(cmd, forbidden=hits, status=status, audit_fn=ok_audit) == frozenset()


def test_a_dirty_audit_refuses_the_lane():
    def dirty(step):
        return {"ok": False, "findings": ["order_capability_unstubbed:scripts/x.py"]}

    cmd = "scripts/options_chain_snapshot.py --dry-run"
    refusals = C.static_refusals(cmd, status="ACTIVE", audit_fn=dirty)
    assert refusals == ["capability_found:order_capability_unstubbed:scripts/x.py"]
    assert C.exempt_command_tokens(cmd, forbidden=("options_chain_snapshot.py",), status="ACTIVE",
                                   audit_fn=dirty) == frozenset()


def test_an_excluded_family_is_refused_even_if_listed(monkeypatch):
    bad = P.Step("stop", "stop manager", "scripts/alpaca_stop_manager.py", (), ("--apply",), "alpaca")
    monkeypatch.setattr(C, "READ_LANES", C.READ_LANES + (bad,))
    refusals = C.static_refusals("scripts/alpaca_stop_manager.py --apply", status="ACTIVE", audit_fn=ok_audit)
    assert "excluded_family:stop_manager" in refusals


def test_active_exempts_only_the_tokens_naming_the_lanes_own_script(monkeypatch):
    monkeypatch.setattr(C, "CARVEOUT_STATUS", "ACTIVE")
    monkeypatch.setattr(C, "default_audit", ok_audit)
    assert PM.forbidden_command_tokens("$PY scripts/positions_sync.py --apply", n8n_broker_read=True) == []
    assert PM.forbidden_command_tokens("$PY scripts/positions_sync.py --apply") == ["positions_sync.py"]
    assert PM.forbidden_command_tokens("scripts/moomoo_live_read_sync.py --dry-run", n8n_broker_read=True) == []
    assert PM.forbidden_command_tokens("scripts/options_chain_snapshot.py --dry-run", n8n_broker_read=True) == []
    # never exempt: an order token, a wrapper, an extra argument, a non-lane
    assert PM.forbidden_command_tokens("scripts/schwab_transport.py place_order", n8n_broker_read=True) == [
        "place_order"]
    gated = "bash scripts/market_day_gate.sh scripts/positions_sync.py --apply"
    assert set(PM.forbidden_command_tokens(gated, n8n_broker_read=True)) == {"market_day_gate.sh",
                                                                             "positions_sync.py"}
    assert PM.forbidden_command_tokens("scripts/positions_sync.py --apply --x", n8n_broker_read=True) == [
        "positions_sync.py"]
    assert PM.forbidden_command_tokens("scripts/broker_stop_reconcile.py --apply", n8n_broker_read=True) == [
        "broker_stop_reconcile.py"]
    assert "place_order" not in C.exempt_command_tokens("$PY scripts/positions_sync.py --apply",
                                                        forbidden=("place_order", "positions_sync.py"))


def test_forbidden_command_tokens_fails_closed_when_the_carveout_raises(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("x")

    monkeypatch.setattr(C, "exempt_command_tokens", boom)
    assert PM.forbidden_command_tokens("scripts/positions_sync.py --apply", n8n_broker_read=True) == [
        "positions_sync.py"]


# ------------------------------------------------------------------------------------------- preconditions

def test_preconditions_pass_only_when_every_lock_is_locked_and_the_switch_is_read_only():
    assert C.runtime_refusals(status="ACTIVE", lock_fn=lambda: LOCKED, mode_fn=lambda: READ_ONLY) == []


@pytest.mark.parametrize("broker", P.LOCK_BROKERS)
def test_an_unlocked_or_missing_broker_lock_refuses(broker):
    unlocked = {**LOCKED, broker: {"locked": False, "reason": "operator unlock until 15:00"}}
    assert C.runtime_refusals(status="ACTIVE", lock_fn=lambda: unlocked, mode_fn=lambda: READ_ONLY) == [
        f"trading_lock_not_locked:{broker}"]
    missing = {b: v for b, v in LOCKED.items() if b != broker}
    assert C.runtime_refusals(status="ACTIVE", lock_fn=lambda: missing, mode_fn=lambda: READ_ONLY) == [
        f"trading_lock_not_locked:{broker}"]
    truthy = {**LOCKED, broker: {"locked": "yes"}}
    assert f"trading_lock_not_locked:{broker}" in C.runtime_refusals(status="ACTIVE", lock_fn=lambda: truthy,
                                                                     mode_fn=lambda: READ_ONLY)


@pytest.mark.parametrize("mode", ["normal", "forbidden", None, "READ_ONLY", "read-only"])
def test_a_switch_not_read_only_refuses(mode):
    assert C.runtime_refusals(status="ACTIVE", lock_fn=lambda: LOCKED, mode_fn=lambda: {"mode": mode}) == [
        "schwab_access_mode_not_read_only"]


def test_unreadable_lock_or_switch_state_refuses():
    def boom():
        raise OSError("unreadable")

    r = C.runtime_refusals(status="ACTIVE", lock_fn=boom, mode_fn=boom)
    assert "trading_lock_unreadable:OSError" in r and "schwab_access_mode_unreadable:OSError" in r
    assert all(f"trading_lock_not_locked:{b}" in r for b in P.LOCK_BROKERS)
    assert "schwab_access_mode_not_read_only" in r


def test_admit_combines_static_and_runtime_refusals():
    cmd = "$PY scripts/schwab_position_sync.py --apply"
    unlocked = {**LOCKED, "schwab": {"locked": False}}
    v = C.admit(cmd, status="ACTIVE", audit_fn=ok_audit, lock_fn=lambda: unlocked, mode_fn=lambda: {"mode": "normal"})
    assert v["admitted"] is False
    assert v["refusals"] == ["trading_lock_not_locked:schwab", "schwab_access_mode_not_read_only"]


def test_the_operator_switch_is_read_without_the_per_process_force(monkeypatch):
    seen = {}

    class FakeBRS:
        @staticmethod
        def resolved_child_mode(env):
            seen.update(env)
            return {"mode": "normal"}

    monkeypatch.setattr(C, "_broker_read_sync", lambda: FakeBRS)
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "read_only")
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE_PATH", "/tmp/fake.yaml")
    assert C.operator_access_mode() == {"mode": "normal"}
    assert "TRADEAI_SCHWAB_ACCESS_MODE" not in seen and "TRADEAI_SCHWAB_ACCESS_MODE_PATH" not in seen
    assert C.runtime_refusals(status="ACTIVE", lock_fn=lambda: LOCKED) == ["schwab_access_mode_not_read_only"]


def test_lock_states_and_mode_reuse_broker_read_sync():
    src = (ROOT / "scripts" / "lib" / "n8n_broker_read_carveout.py").read_text(encoding="utf-8")
    assert ".lock_states()" in src and ".resolved_child_mode(" in src and "policy.audit(" in src
    assert "excluded_family" in src and "runtime_denied" in src
    for forbidden in ("open(\".env", "dotenv", "schwab_transport", "place_order(", "requests.", "urllib"):
        assert forbidden not in src.replace("``place_order``", "").replace("\"place_order\"", ""), forbidden


# ------------------------------------------------------------------------------------------- the real audit

def test_market_data_reads_pass_the_real_section_24_11_audit():
    result = P.audit(ROOT, C.MARKET_DATA_READS)
    assert result["ok"], result["findings"][:5]
