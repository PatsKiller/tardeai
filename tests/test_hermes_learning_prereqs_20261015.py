"""Hermes learning on the n8n fabric: the four cutover prerequisites (2026-10-15; AGENTS.md §23.23, §23.4, §23.18,
§24.1, §12). Everything stays INERT at merge: spec mode dry_run, live_arg null, registry stage shadow.

  G3  p: process-step run keys are validated SERVER-SIDE (scripts/lib/n8n_process_keys.py, called by the gateway's
      coordination/run): the key must name a runnable step of a registered process, in a mode the spec allows, for a
      current slot; a forged, blocked, expired, future, over-budget or manual-live key is refused typed. The gateway
      stores the base key as the row's slot_key and the executor's effect gate claims fx:<lane>:<slot>:<ver> for a
      LIVE p: row only when that marker is present (otherwise effect:effect_process_key_unvalidated).
  G4  the cron steps' run_with_deepseek_offpeak.sh PEAK_SKIP is reproduced by the executor for a LIVE run (allowlist
      offpeak_gate, the same scripts/lib/deepseek_offpeak.py window); dry runs record the verdict only; a lane whose
      cron step has no wrapper declares offpeak_exempt (parity, not an invented exemption).
  G5a hermes_tag_engine's classifier goes through the governed bridge ONLY when the executor binds the llm_route
      (advisory_desk / hermes_tag_engine; registry cap $0.05/day, tools_allowed false); a refusal is "no tags", never
      an in-process provider call. The cron path is unchanged.
  G5b outcome_feedback_agent --notify queue QUEUES each alert as a host comms intent (config/host_comms_intent_routes
      .json, producer-bound) that the host comms-intent consumer turns into a P2 incident; no sender is called, n8n's
      intent route cannot post it, and the fabric policy hash does not move.

Hermetic: tmp_path ledgers, stub chokepoint and stub bridge transport, no DB, no network, no live token store.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hermes_tag_engine as TE  # noqa: E402
from lib.hermes_outcome_bus import alert_notifications as AN  # noqa: E402
from scripts import n8n_run_executor as X  # noqa: E402
from scripts import n8n_workflow_templates as T  # noqa: E402
from scripts.lib import effect_claim as E  # noqa: E402
from scripts.lib import governed_process_routes as R  # noqa: E402
from scripts.lib import host_comms_intents as HI  # noqa: E402
from scripts.lib import n8n_comms_intent_consumption as CI  # noqa: E402
from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts.lib import n8n_fabric_store as F  # noqa: E402
from scripts.lib import n8n_process_keys as PK  # noqa: E402
from scripts.lib.n8n_coordination_ledger import (  # noqa: E402
    CoordinationLedger,
    LedgerNonceStore,
    LedgerReceiptStore,
    LedgerRunStore,
)
from scripts.pipelines import pipeline_manifest as PM  # noqa: E402

ET = ZoneInfo("America/New_York")
PROCESS = "hermes-learning"
SOURCES = PK.load_sources()
SPEC = SOURCES["processes"][PROCESS]
MANIFEST = SOURCES["manifests"][PROCESS]
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
REGISTRY = {p["id"]: p for p in json.loads((ROOT / "config" / "llm_process_registry.json").read_text())["processes"]}
RUNNABLE = {sid: s for sid, s in SPEC["steps"].items() if not s["blocked"]}
GRADER = "hermes-learning-outcome-grader"
TUNE = "hermes-learning-autonomous-self-tune"
RETENTION = "hermes-learning-score-history-retention"
#: 2026-10-15 is a Thursday; the learn stage slot is 10:50 ET (14:50Z under EDT).
LEARN_NOW = datetime(2026, 10, 15, 10, 57, tzinfo=ET)
#: The fabric policy hash Build 1 shipped (tests/test_n8n_fabric_hermes_learning_20261015.py POLICY_PIN). A host intent
#: route must not move it.
POLICY_PIN = "c6750b96ada49f816798bf3714ad390616b1b32769fdcbcc54e0635e32caf31f"


def _live_sources(**proc_overrides) -> dict:
    src = copy.deepcopy(SOURCES)
    src["processes"][PROCESS].update({"mode": "live", **proc_overrides})
    return src


def _key(lane: str, mode: str, slot: str, attempt: int = 1) -> str:
    return f"p:{lane}:{mode}:{slot}" + (f":a{attempt}" if attempt > 1 else "")


# ── G3: pure key validation ───────────────────────────────────────────────────────────────────────────────────────


def test_scheduled_dry_run_key_is_accepted_with_its_base_slot_key():
    c = PK.check_process_key(
        _key(GRADER, "dry_run", "20261015T1050"), GRADER, "dry_run", sources=SOURCES, now=LEARN_NOW
    )
    assert c.ok and c.state == "OK" and c.slot_kind == "scheduled"
    assert c.slot_key == "p:hermes-learning-outcome-grader:dry_run:20261015T1050" and c.attempt == 1
    assert (c.process_id, c.step_id, c.stage) == (PROCESS, "outcome_grader", "learn")
    # the slot is the cron runner's effect-key slot string
    assert c.slot == PM.effect_slot(MANIFEST, "learn", "20261015")


def test_manual_dry_run_minute_is_accepted_and_the_tune_stage_slot_is_scheduled():
    m = PK.check_process_key(
        _key(GRADER, "dry_run", "20261015T1056"), GRADER, "dry_run", sources=SOURCES, now=LEARN_NOW
    )
    assert m.ok and m.slot_kind == "manual"
    t = PK.check_process_key(
        _key(TUNE, "dry_run", "20261015T1700"),
        TUNE,
        "dry_run",
        sources=SOURCES,
        now=datetime(2026, 10, 15, 17, 3, tzinfo=ET),
    )
    assert t.ok and t.slot_kind == "scheduled" and t.stage == "tune"


def test_live_key_is_refused_while_the_spec_is_dry_run():
    dry = copy.deepcopy(SOURCES)
    dry["processes"][PROCESS].update({"mode": "dry_run", "live_manual_slots": False})
    c = PK.check_process_key(_key(GRADER, "live", "20261015T1050"), GRADER, "live", sources=dry, now=LEARN_NOW)
    assert not c.ok and c.state == "MODE_NOT_LIVE"
    # hermes-learning cutover PR-2 (2026-10-15): the committed spec is live (learn stage at canary)
    assert SPEC["mode"] == "live"


def test_live_spec_accepts_the_scheduled_slot_and_refuses_a_manual_minute_unless_flagged():
    live = _live_sources()
    ok = PK.check_process_key(_key(GRADER, "live", "20261015T1050"), GRADER, "live", sources=live, now=LEARN_NOW)
    assert ok.ok and ok.slot_kind == "scheduled"
    manual = PK.check_process_key(_key(GRADER, "live", "20261015T1056"), GRADER, "live", sources=live, now=LEARN_NOW)
    assert not manual.ok and manual.state == "MANUAL_LIVE_REFUSED"
    flagged = _live_sources(live_manual_slots=True)
    assert PK.check_process_key(
        _key(GRADER, "live", "20261015T1056"), GRADER, "live", sources=flagged, now=LEARN_NOW
    ).ok


@pytest.mark.parametrize(
    "key,lane,mode,now,state",
    [
        (
            "p:hermes-learning-outcome-grader:dry_run:20261015T1050:a2",
            GRADER,
            "dry_run",
            LEARN_NOW,
            "ATTEMPT_OVER_BUDGET",
        ),
        ("p:hermes-learning-outcome-grader:dry_run:20261015T1150", GRADER, "dry_run", LEARN_NOW, "SLOT_IN_FUTURE"),
        ("p:hermes-learning-outcome-grader:dry_run:20261014T1050", GRADER, "dry_run", LEARN_NOW, "SLOT_EXPIRED"),
        ("p:hermes-learning-outcome-grader:dry_run:20261015T1050", GRADER, "live", LEARN_NOW, "KEY_MISMATCH"),
        ("p:hermes-learning-outcome-grader:dry_run:20261015T1050", TUNE, "dry_run", LEARN_NOW, "KEY_MISMATCH"),
        ("P:hermes-learning-outcome-grader:dry_run:20261015T1050", GRADER, "dry_run", LEARN_NOW, "MALFORMED_KEY"),
        ("p:hermes-learning-outcome-grader:dry_run:20261015T2561", GRADER, "dry_run", LEARN_NOW, "MALFORMED_KEY"),
        ("p:n8n-lab-watchdog:dry_run:20261015T1050", "n8n-lab-watchdog", "dry_run", LEARN_NOW, "NOT_A_PROCESS_STEP"),
        (f"p:{RETENTION}:dry_run:20261015T1050", RETENTION, "dry_run", LEARN_NOW, "STEP_BLOCKED"),
    ],
)
def test_forged_or_stale_keys_are_refused_typed(key, lane, mode, now, state):
    c = PK.check_process_key(key, lane, mode, sources=SOURCES, now=now)
    assert not c.ok and c.state == state, c


def test_unreadable_spec_fails_closed(tmp_path):
    with pytest.raises(PK.ProcessKeyError):
        PK.load_sources(tmp_path)
    c = PK.check_process_key(_key(GRADER, "dry_run", "20261015T1050"), GRADER, "dry_run", sources=None, now=LEARN_NOW)
    assert not c.ok and c.state == "PROCESS_SPEC_UNREADABLE"
    assert PK.is_process_key("P:x") and not PK.is_process_key("d:x")


# ── G3: the gateway route ─────────────────────────────────────────────────────────────────────────────────────────

GW_KEY = b"dispatch-key-not-a-live-secret-0123456"
N8N_KEY = b"relay-key-not-a-live-secret-9876543210"


@pytest.fixture
def gw(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield SimpleNamespace(
        ledger=ledger,
        nonces=LedgerNonceStore(ledger),
        receipts=LedgerReceiptStore(ledger),
        runs=LedgerRunStore(ledger),
        n=[0],
    )
    ledger.close()


def _gw_run(gw, key: str, *, lane=GRADER, mode="dry_run", now=LEARN_NOW, sources=SOURCES) -> dict:
    gw.n[0] += 1
    claim = {
        "v": 1,
        "caller_id": "n8n-relay",
        "project": "trade-ai",
        "iat": now.timestamp(),
        "exp": now.timestamp() + 120,
        "nonce": f"nonce-p-{gw.n[0]:04d}",
        "scope": G.SCOPE_RUN,
    }
    req = {
        "claim": claim,
        "signature": hmac.new(N8N_KEY, G.canonical(claim), hashlib.sha256).hexdigest(),
        "route": "coordination/run",
        "operation": "run",
        "lane_id": lane,
        "mode": mode,
        "idempotency_key": key,
        "requested_by": "n8n:tradeai-fabric-hermes-learning",
    }
    return G.handle_request(
        req,
        key=GW_KEY,
        now=now,
        nonce_store=gw.nonces,
        idempotency_store=gw.receipts,
        expected_origin_sha="a" * 40,
        caller_keys=G.build_caller_keys(GW_KEY, n8n_key=N8N_KEY),
        run_store=gw.runs,
        run_allowlist=frozenset(ALLOW),
        process_sources=sources,
    )


def test_gateway_accepts_a_valid_p_key_and_stores_the_validated_marker(gw):
    key = _key(GRADER, "dry_run", "20261015T1050")
    out = _gw_run(gw, key)
    assert out["schema"] == "RunRequested@v1" and out["state"] == "REQUESTED" and out["duplicate"] is False
    assert out["process_key"] == {
        "process_id": PROCESS,
        "step_id": "outcome_grader",
        "stage": "learn",
        "slot": "20261015T1050",
        "slot_kind": "scheduled",
    }
    row = gw.runs.get(key)
    assert row["slot_key"] == key and row["attempt"] == 1
    again = _gw_run(gw, key, now=LEARN_NOW + timedelta(hours=3))  # replay after the window: the existing row
    assert again["duplicate"] is True and again["run_id"] == key


@pytest.mark.parametrize(
    "key,mode,state",
    [
        ("p:hermes-learning-outcome-grader:live:20261015T1055", "live", "MANUAL_LIVE_REFUSED"),
        ("p:hermes-learning-outcome-grader:dry_run:20261014T1050", "dry_run", "SLOT_EXPIRED"),
        ("p:hermes-learning-tag-engine:dry_run:20261015T1050", "dry_run", "KEY_MISMATCH"),
        ("P:hermes-learning-outcome-grader:dry_run:20261015T1050", "dry_run", "MALFORMED_KEY"),
    ],
)
def test_gateway_refuses_forged_p_keys_typed_and_writes_no_row(gw, key, mode, state):
    out = _gw_run(gw, key, mode=mode)
    assert out["state"] == "REFUSED" and out["reason"] == "run_process_key_invalid" and out["key_state"] == state
    assert gw.ledger._conn.execute("SELECT count(*) AS n FROM runs").fetchone()["n"] == 0


def test_gateway_fails_closed_when_the_spec_is_unreadable(gw):
    def broken():
        raise PK.ProcessKeyError("process_spec_unreadable")

    out = _gw_run(gw, _key(GRADER, "dry_run", "20261015T1050"), sources=broken)
    assert out["reason"] == "run_process_key_invalid" and out["key_state"] == "PROCESS_SPEC_UNREADABLE"


def test_free_form_keys_and_host_callers_are_unchanged(gw):
    out = _gw_run(gw, "run-20261015-grader-manual-0001")  # a non-p caller key: accepted as before, no marker
    assert out["state"] == "REQUESTED" and gw.runs.get("run-20261015-grader-manual-0001")["slot_key"] is None
    host = G.host_run_request(
        lane_id=GRADER,
        mode="dry_run",
        run_id=_key(GRADER, "dry_run", "20261015T1050"),
        requested_by="diag",
        caller_id="tradeai-diagnoser",
        run_store=gw.runs,
        run_allowlist=frozenset(ALLOW),
        now=LEARN_NOW.timestamp(),
    )
    assert host["reason"] == "run_process_key_invalid" and host["key_state"] == "HOST_CALLER_REFUSED"
    assert "run_process_key_invalid" in G.REFUSAL_REASONS


# ── G3: the executor's effect gate, end to end ────────────────────────────────────────────────────────────────────


class Runner:
    def __init__(self, code: int = 0) -> None:
        self.calls: list = []
        self.code = code

    def __call__(self, argv, *, timeout, env, cwd):
        self.calls.append({"argv": argv, "env": env})
        return SimpleNamespace(returncode=self.code, stdout="ok", stderr="")


def _live_entry(tmp_path: Path, lane: str = GRADER, **extra) -> dict:
    e = copy.deepcopy(ALLOW[lane])
    e.update({"lock": str(tmp_path / "step.lock"), "live_arg": ["--apply"], "env_allowlist_mode": "report", **extra})
    return e


def _owner(gw, lane: str, at: datetime) -> E.EffectClaimStore:
    fx = E.EffectClaimStore(gw.ledger)
    fx.set_owner(lane, "n8n", expect_epoch=None, by="test", now=at.timestamp(), note="test")
    return fx


@pytest.fixture
def in_window(monkeypatch):
    monkeypatch.setattr(X, "_offpeak_now", lambda: LEARN_NOW.astimezone(timezone.utc))


def test_live_p_run_validated_by_the_gateway_claims_the_cron_runners_effect_key(gw, tmp_path, in_window):
    fx = _owner(gw, GRADER, LEARN_NOW - timedelta(minutes=30))
    key = _key(GRADER, "live", "20261015T1050")
    assert _gw_run(gw, key, mode="live", sources=_live_sources())["state"] == "REQUESTED"
    row = gw.runs.claim_next(now=LEARN_NOW.timestamp() + 1)
    gate = X.EffectGate(
        fx, {GRADER: {"process": GRADER, "input_version": "v1"}}, clock=lambda: LEARN_NOW.timestamp() + 2
    )
    runner = Runner()
    receipt = X.execute(
        row, _live_entry(tmp_path), env={}, state_root=tmp_path, code_root=tmp_path, runner=runner, effects=gate
    )
    assert receipt["state"] == "RUN_DONE" and len(runner.calls) == 1
    assert receipt["effect"]["claimed"] is True
    assert receipt["effect"]["key"] == E.effect_key(GRADER, PM.effect_slot(MANIFEST, "learn", "20261015"), "v1")
    assert receipt["effect"]["final_state"] == E.STATE_DONE


def test_live_p_row_without_the_gateway_marker_is_refused_and_runs_nothing(gw, tmp_path, in_window):
    fx = _owner(gw, GRADER, LEARN_NOW - timedelta(minutes=30))
    key = _key(GRADER, "live", "20261015T1050")
    # written straight into the ledger (no gateway validation): no slot_key
    gw.runs.request(
        run_id=key, lane_id=GRADER, mode="live", requested_by="forged", caller_id="n8n-relay", now=LEARN_NOW.timestamp()
    )
    row = gw.runs.claim_next(now=LEARN_NOW.timestamp() + 1)
    gate = X.EffectGate(
        fx, {GRADER: {"process": GRADER, "input_version": "v1"}}, clock=lambda: LEARN_NOW.timestamp() + 2
    )
    runner = Runner()
    receipt = X.execute(
        row, _live_entry(tmp_path), env={}, state_root=tmp_path, code_root=tmp_path, runner=runner, effects=gate
    )
    # 2026-10-15 (audit DD03): refused before the effect gate, for keyed and unkeyed lanes alike
    assert receipt["state"] == "RUN_REFUSED" and receipt["reason"] == "process_key_unvalidated"
    assert runner.calls == []


# ── G4: the off-peak gate ─────────────────────────────────────────────────────────────────────────────────────────

OUT_OF_WINDOW = datetime(2026, 10, 15, 8, 0, tzinfo=ET)  # before 10:00 ET (and inside the 06-10 UTC peak? 12:00Z: no)
UTC_PEAK_NIGHT = datetime(2026, 10, 15, 2, 30, tzinfo=timezone.utc)  # Thursday 02:30Z: official DeepSeek peak


@pytest.mark.parametrize(
    "gate,when,in_window",
    [
        ("bulk", LEARN_NOW, True),
        ("bulk", OUT_OF_WINDOW, False),
        ("official", OUT_OF_WINDOW, True),
        ("official", UTC_PEAK_NIGHT, False),
        ("scheduled", datetime(2026, 10, 15, 9, 30, tzinfo=ET), True),
        ("scheduled", datetime(2026, 10, 15, 22, 0, tzinfo=ET), False),
    ],
)
def test_offpeak_verdict_uses_the_wrapper_window(gate, when, in_window):
    v = X.offpeak_verdict({"offpeak_gate": gate}, "live", env={}, now=when)
    assert v["in_window"] is in_window and v["skipped"] is (not in_window)
    assert v["wrapper_flag"] == X.OFFPEAK_GATES[gate][0]
    assert X.offpeak_verdict({}, "live", env={}, now=when) is None


def test_live_run_outside_the_window_is_peak_skipped_before_any_claim(gw, tmp_path, monkeypatch):
    monkeypatch.setattr(X, "_offpeak_now", lambda: OUT_OF_WINDOW.astimezone(timezone.utc))
    fx = _owner(gw, GRADER, LEARN_NOW - timedelta(days=1))
    gate = X.EffectGate(fx, {GRADER: {"process": GRADER, "input_version": "v1"}})
    row = {"run_id": "run-offpeak-live-0001", "lane_id": GRADER, "mode": "live", "requested_at": None}
    runner = Runner()
    receipt = X.execute(
        row, _live_entry(tmp_path), env={}, state_root=tmp_path, code_root=tmp_path, runner=runner, effects=gate
    )
    assert receipt["state"] == "RUN_DONE" and receipt["reason"] == "offpeak_skip" and runner.calls == []
    assert receipt["offpeak"]["skipped"] is True and "PEAK_SKIP gate=--gate" in receipt["stdout_tail"]
    assert "effect" not in receipt  # no key claimed for a run that did nothing


def test_dry_run_and_the_override_are_never_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(X, "_offpeak_now", lambda: OUT_OF_WINDOW.astimezone(timezone.utc))
    entry = _live_entry(tmp_path)
    dry = X.execute(
        {"run_id": "run-offpeak-dry-0001", "lane_id": GRADER, "mode": "dry_run"},
        entry,
        env={},
        state_root=tmp_path,
        code_root=tmp_path,
        runner=Runner(),
    )
    assert dry["state"] == "RUN_DONE" and dry["offpeak"]["applies"] is False and dry["offpeak"]["in_window"] is False
    runner = Runner()
    over = X.execute(
        {"run_id": "run-offpeak-over-0001", "lane_id": GRADER, "mode": "live"},
        entry,
        env={"HERMES_ALLOW_DEEPSEEK_PEAK": "1"},
        state_root=tmp_path,
        code_root=tmp_path,
        runner=runner,
    )
    assert over["state"] == "RUN_DONE" and over["offpeak"]["override"] is True and len(runner.calls) == 1


def test_bad_offpeak_gate_is_a_malformed_entry(tmp_path):
    assert X.validate_entry(_live_entry(tmp_path, offpeak_gate="always")) == "bad_offpeak_gate"
    assert X.validate_entry(_live_entry(tmp_path)) is None


def _wrapper_gate(command: str) -> str | None:
    if "run_with_deepseek_offpeak.sh" not in command:
        return None
    rest = command.split("run_with_deepseek_offpeak.sh", 1)[1].lstrip("\"'").split()
    return {"--official": "official", "--scheduled": "scheduled"}.get(rest[0] if rest else "", "bulk")


@pytest.mark.parametrize("sid", sorted(RUNNABLE))
def test_every_runnable_step_reproduces_its_cron_wrapper(sid):
    step = next(st for s in MANIFEST["stages"].values() for st in s["steps"] if st["id"] == sid)
    entry = ALLOW[RUNNABLE[sid]["lane_id"]]
    want = _wrapper_gate(step["command"])
    assert entry.get("offpeak_gate") == want, (sid, entry.get("offpeak_gate"), want)
    if want is None:
        assert (
            isinstance(entry.get("offpeak_exempt"), str)
            and "no run_with_deepseek_offpeak.sh" in entry["offpeak_exempt"]
        )
    else:
        assert "offpeak_exempt" not in entry
    # cutover PR-2 (2026-10-15): learn lanes carry the spec's cutover_live_arg; the tune lane stays inert (shadow)
    want_live = None if sid == "autonomous_self_tune" else RUNNABLE[sid]["cutover_live_arg"]
    assert X.validate_entry(entry) is None and entry["live_arg"] == want_live


# ── G5a: tag engine through the governed bridge ───────────────────────────────────────────────────────────────────


def test_route_is_registered_on_both_sides_and_bounded():
    from scripts.lib import cio_governed_model_bridge as B

    assert R.route_for_process("hermes_tag_engine") == ("advisory_desk", "hermes_tag_engine")
    assert B.resolve_caller("advisory_desk", "hermes_tag_engine") == "hermes_tag_engine"
    row = REGISTRY["hermes_tag_engine"]
    assert row["daily_cost_cap_usd"] == 0.05 and row["tools_allowed"] is False and row["advisory_only"] is True


def test_allowlist_llm_route_binds_the_bridge_env_for_the_tag_engine_lane():
    entry = ALLOW["hermes-learning-tag-engine"]
    assert entry["llm_route"] == {"via": "cio-governed-bridge", "process_id": "hermes_tag_engine"}
    assert X.validate_entry(entry) is None and entry["live_arg"] == ["--apply"]  # cutover PR-2
    env, block = X.build_child_env({"PATH": "/usr/bin"}, entry["lane_id"], entry)
    assert env[X.LLM_BRIDGE_ENV] == "1" and env[X.LLM_PROCESS_ENV] == "hermes_tag_engine"


@pytest.fixture
def bridge(monkeypatch):
    calls: list = []
    mod = types.ModuleType("lib.llm_bridge_route")

    def text_via_bridge(process_id, prompt, *, timeout_s=60.0):
        calls.append({"process_id": process_id, "timeout_s": timeout_s, "prompt": prompt})
        return mod.reply

    mod.text_via_bridge = text_via_bridge
    mod.reply = '{"tags": ["breakout", "not_a_slug", "momentum", "x"]}'
    monkeypatch.setitem(sys.modules, "lib.llm_bridge_route", mod)
    gcg = types.ModuleType("lib.governed_cloud_generation")
    gcg.calls = []
    gcg.generate_cloud = lambda *a, **k: gcg.calls.append(k) or ('{"tags": ["momentum"]}', "grok")
    monkeypatch.setitem(sys.modules, "lib.governed_cloud_generation", gcg)
    return SimpleNamespace(mod=mod, calls=calls, gcg=gcg)


def test_bridge_flag_routes_only_through_the_governed_bridge(bridge, monkeypatch):
    monkeypatch.setenv("TRADEAI_LLM_VIA_BRIDGE", "1")
    tags = TE._llm_tags("text", ["breakout", "momentum"], 7, 2)
    assert tags == ["breakout", "momentum"]
    assert bridge.calls[0]["process_id"] == "hermes_tag_engine" and bridge.calls[0]["timeout_s"] == 7.0
    assert bridge.gcg.calls == []  # never the in-process provider path


def test_bridge_refusal_is_no_tags_never_a_fallthrough(bridge, monkeypatch):
    monkeypatch.setenv("TRADEAI_LLM_VIA_BRIDGE", "1")
    bridge.mod.reply = None
    assert TE._llm_tags("text", ["breakout"], 7, 2) == []
    bridge.mod.reply = "not json"
    assert TE._llm_tags("text", ["breakout"], 7, 2) == []
    assert bridge.gcg.calls == []


def test_without_the_flag_the_cron_path_is_unchanged(bridge, monkeypatch):
    monkeypatch.delenv("TRADEAI_LLM_VIA_BRIDGE", raising=False)
    assert TE._llm_tags("text", ["breakout", "momentum"], 7, 2) == ["momentum"]
    assert bridge.calls == [] and bridge.gcg.calls[0]["process_id"] == "hermes_tag_engine"


# ── G5b: outcome_feedback_agent intents reach the operator through the host consumer ──────────────────────────────


@pytest.fixture
def ledger_file(tmp_path):
    path = tmp_path / "ledger.sqlite"
    CoordinationLedger(path).close()
    return path


NOW_TS = LEARN_NOW.timestamp()


def _queue(ledger_file, **over):
    kw = {
        "producer": "hermes_outcome_feedback_agent",
        "domain": "research",
        "kind": "hermes_closed_loop_alert",
        "subject": "Hermes closed loop CRITICAL: Hit rate",
        "summary": "down\nfor 3 days",
        "execution_id": "ofb_abc",
        "node": "hit_rate_declining",
        "ledger_path": ledger_file,
        "now": NOW_TS,
    }
    kw.update(over)
    return HI.queue_intent(**kw)


def test_host_intent_is_queued_deduped_and_producer_bound(ledger_file):
    r = _queue(ledger_file)
    assert r["state"] == "ACCEPTED" and r["tier"] == "DIGEST" and r["duplicate"] is False
    again = _queue(ledger_file, now=NOW_TS + 60)
    assert again["duplicate"] is True and again["intent_id"] == r["intent_id"]
    for over, reason in (
        ({"producer": "someone_else"}, "producer_refused"),
        ({"producer": "Bad-Name"}, "producer_refused"),
        ({"kind": "other_kind"}, "intent_unrouted"),
        ({"ledger_path": ledger_file.parent / "absent.sqlite"}, "ledger_absent"),
    ):
        with pytest.raises(HI.HostIntentError) as exc:
            _queue(ledger_file, **over)
        assert exc.value.reason == reason


def test_n8n_cannot_post_a_host_route_and_the_policy_hash_does_not_move(ledger_file):
    ledger = CoordinationLedger(ledger_file)
    try:
        store = F.CommsIntentStore(ledger)  # the gateway's store: n8n route table only
        with pytest.raises(F.FabricStoreError) as exc:
            store.accept(
                {
                    "domain": "research",
                    "kind": "hermes_closed_loop_alert",
                    "subject": "x",
                    "summary": "y",
                    "workflow_id": "tradeai-fabric-hermes-learning",
                    "execution_id": "1",
                    "node": "n",
                },
                caller_id="n8n-relay",
                now=NOW_TS,
            )
        assert exc.value.reason == "intent_unrouted"
    finally:
        ledger.close()
    assert T.policy_hash() == POLICY_PIN


def test_the_consumer_turns_the_host_intent_into_a_p2_incident(ledger_file):
    r = _queue(ledger_file)
    routes = CI.load_routes()
    assert routes["host_routes"] == "ok" and ("research", "hermes_closed_loop_alert") in routes["routes"]
    conn = CI.connect_rw(ledger_file)
    try:
        res = CI.apply(conn, routes, LEARN_NOW.astimezone(timezone.utc), 10, "tok-1")
    finally:
        conn.close()
    assert [x.get("intent_id") for x in res["results"]] == [r["intent_id"]]
    findings, note = CI.open_incident_findings(ledger_file, LEARN_NOW.astimezone(timezone.utc))
    assert note == "ok:open=1" and findings[0]["severity"] == "P2"
    assert findings[0]["workflow_id"] == "host.hermes_outcome_feedback_agent"


def test_unreadable_host_routes_leave_the_n8n_table_and_refuse_host_intents(tmp_path):
    routes = CI.load_routes(host_path=tmp_path / "missing.json")
    assert routes["host_routes"] == "unreadable" and ("research", "hermes_closed_loop_alert") not in routes["routes"]
    assert (
        CI.map_intent({"domain": "research", "kind": "hermes_closed_loop_alert", "workflow_id": "w"}, routes)["action"]
        == "refuse"
    )


@pytest.fixture
def no_sender(monkeypatch, tmp_path):
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda *a, **k: pytest.fail("a sender was called")
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    monkeypatch.setattr(AN, "STATE_PATH", tmp_path / "notify_state.json")
    monkeypatch.setattr(AN, "AUDIT_PATH", tmp_path / "notify_audit.jsonl")
    monkeypatch.setattr(AN, "_panel_url", lambda cfg: "/v3/hermes")


NOTIFY_CFG = {
    "enabled": True,
    "min_severity": "warning",
    "cooldown_hours": 8,
    "alert_types": {},
    "channels": {"telegram": {"enabled": True}},
}
ALERTS = {
    "active_count": 2,
    "active": [
        {"id": "hit_rate_declining", "severity": "critical", "label": "Hit rate", "detail": "down"},
        {"id": "efficiency_declining", "severity": "warning", "label": "Efficiency", "detail": "low"},
    ],
}


def test_queue_mode_queues_each_alert_calls_no_sender_and_honours_the_cooldown(no_sender, ledger_file, monkeypatch):
    monkeypatch.setattr(
        AN, "_queue_host_intent", lambda **kw: HI.queue_intent(ledger_path=ledger_file, now=NOW_TS, **kw)
    )
    r = AN.dispatch_alert_notifications(
        copy.deepcopy(ALERTS), cfg=copy.deepcopy(NOTIFY_CFG), notify="queue", run_id="ofb_0123456789"
    )
    assert r["sent"] == 0 and r["queued"] == 2 and {x["status"] for x in r["results"]} == {"queued"}
    assert set(json.loads(AN.STATE_PATH.read_text())["last_sent"]) == {"hit_rate_declining", "efficiency_declining"}
    again = AN.dispatch_alert_notifications(copy.deepcopy(ALERTS), cfg=copy.deepcopy(NOTIFY_CFG), notify="queue")
    assert again["queued"] == 0 and again["suppressed"] == 2


def test_a_refused_queue_is_failed_and_leaves_the_cooldown(no_sender, monkeypatch):
    def refuse(**kw):
        raise HI.HostIntentError("ledger_absent")

    monkeypatch.setattr(AN, "_queue_host_intent", refuse)
    r = AN.dispatch_alert_notifications(copy.deepcopy(ALERTS), cfg=copy.deepcopy(NOTIFY_CFG), notify="queue")
    assert [x["reason"] for x in r["results"]] == ["queue:ledger_absent"] * 2 and not AN.STATE_PATH.exists()


def test_cutover_live_args_are_declared_and_applied():
    want = {sid: ["--apply"] for sid in RUNNABLE}
    want["outcome_feedback_agent"] = ["--apply", "--notify", "queue"]
    assert {sid: s["cutover_live_arg"] for sid, s in RUNNABLE.items()} == want
    for sid, s in RUNNABLE.items():  # cutover PR-2 (2026-10-15): the learn lanes carry the cutover argv; tune inert
        assert ALLOW[s["lane_id"]]["live_arg"] == (None if sid == "autonomous_self_tune" else want[sid])


def test_registered_in_the_cio_hardening_gates():
    text = (ROOT / "scripts" / "run_cio_hardening_ci.py").read_text(encoding="utf-8")
    assert "tests/test_hermes_learning_prereqs_20261015.py" in text
