"""n8n failure diagnosis runs at failure time, not off-peak (2026-10-15).

Cause: process ``n8n_lane_failure_diagnosis`` carried ``offpeak_tier: standard``, so with LLM_DEFER_OFFPEAK=1 (armed for
every cron line) every failure outside the scheduled window escalated as ``deferred_offpeak; conf=None; cause=`` — the
operator got escalations with no cause (2026-10-12..15 in the live store: 8,662 deferred records vs 25 diagnoses). The
process routes grok OAuth -> chatgpt OAuth (free) -> deepseek FAST under a $0.05/call and $0.10/day cap; off-peak
deferral exists to save paid peak spend, not to delay a time-sensitive advisory.

Pins:
1. the registry seed tier is ``critical``; the other N8nCoordination processes (paid deepseek_only drafts) stay
   ``standard``;
2. the real ``llm_deferral.evaluate`` with deferral ARMED, outside the window, does not defer this process (no DB: the
   operator-tier read is faked empty) — and an operator DB row still wins over the seed;
3. end to end through ``n8n_failure_diagnosis.main --apply`` with the real evaluate, armed, at an out-of-window
   instant: the fake bridge is called and a verdict is recorded;
4. an escalation without a verdict says why and whether it is retried — never ``conf=None; cause=``;
5. a deferred incident is retried next cycle, and a later successful catalogue action clears its stale escalation.

Hermetic: fake DB rows, fake bridge, fake run store, temp state root. Never the live token store, DB or bridge.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import n8n_failure_diagnosis as cli
from scripts.lib import llm_deferral as LD
from scripts.lib import n8n_failure_diagnosis as D
from scripts.lib.deepseek_offpeak import is_scheduled_deepseek_window

from tests.test_n8n_llm_remediation_20261010 import (  # noqa: F401 — the shared hermetic doubles + env fixture
    FakeDB,
    FakeStore,
    GovernedCall,
    _answer,
    _receipt,
    _run,
    _siem_row,
    env,
)

ROOT = Path(__file__).resolve().parents[1]
#: Thursday 2026-10-15 07:30 ET (11:30Z): weekday, before the 09:00 ET scheduled window opens.
OUT_OF_WINDOW = datetime(2026, 10, 15, 11, 30, tzinfo=timezone.utc)


def _registry() -> dict:
    return json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))


@pytest.fixture()
def armed(monkeypatch):
    """Deferral armed as on the cron path; the operator tier table read is faked (empty) — no DB."""
    monkeypatch.setenv(LD.ENABLE_ENV, "1")
    monkeypatch.setattr(LD, "_db_tiers", lambda: {})


def test_fixture_instant_is_outside_the_scheduled_window():
    assert not is_scheduled_deepseek_window(OUT_OF_WINDOW)


def test_registry_seed_pins_the_diagnosis_tier_critical():
    procs = {p["id"]: p for p in _registry()["processes"]}
    row = procs[D.PROCESS_ID]
    assert row["offpeak_tier"] == "critical"
    # what makes critical acceptable: OAuth first and hard-capped
    assert row["allowed_lanes"][:2] == ["grok", "chatgpt"]
    assert row["daily_cost_cap_usd"] <= 0.10 and D.PER_CALL_CAP_USD <= 0.05 and D.DAILY_CAP_USD <= 0.10
    # the drafts in the same category are not time-sensitive and keep the default tier. Since the operator's
    # OAuth-first decision (2026-10-15) they route grok -> chatgpt -> deepseek too (lane_policy either), no longer
    # deepseek_only (tests/test_n8n_oauth_first_routing_20261015.py).
    others = [p for p in procs.values() if p.get("category") == "N8nCoordination" and p["id"] != D.PROCESS_ID]
    assert others, "expected the other N8nCoordination processes"
    for p in others:
        assert p.get("lane_policy") == "either" and p["allowed_lanes"][:2] == ["grok", "chatgpt"]
        assert LD._registry_tiers().get(p["id"], LD.DEFAULT_TIER) == LD.TIER_STANDARD


def test_real_evaluate_does_not_defer_the_diagnosis_out_of_window(armed):
    dec = LD.evaluate(D.PROCESS_ID, now=OUT_OF_WINDOW.astimezone(LD.ET))
    assert dec.defer is False and dec.reason == "CRITICAL_CALLER" and dec.tier == LD.TIER_CRITICAL
    # control: a standard caller at the same instant IS deferred, so the window really is closed
    assert LD.evaluate("n8n_ops_summary_draft", now=OUT_OF_WINDOW.astimezone(LD.ET)).defer is True


def test_an_operator_db_row_still_overrides_the_seed(monkeypatch):
    monkeypatch.setenv(LD.ENABLE_ENV, "1")
    monkeypatch.setattr(LD, "_db_tiers", lambda: {D.PROCESS_ID: LD.TIER_STANDARD})
    assert LD.resolve_tier(D.PROCESS_ID) == LD.TIER_STANDARD


def test_apply_out_of_window_with_deferral_armed_calls_the_model(env, armed):
    call = GovernedCall(_answer(action="suggest_only", conf=0.9))
    real = lambda pid: LD.evaluate(pid, now=OUT_OF_WINDOW.astimezone(LD.ET))  # noqa: E731
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=call, store=FakeStore(), deferral=real,
                now=OUT_OF_WINDOW) == 0
    rec = _receipt(env)
    assert len(call.seen) == 1, "the diagnosis must run when the failure happens"
    res = rec["results"][0]
    assert res["deferral"]["defer"] is False and res["deferral"]["tier"] == "critical"
    assert res["outcome"] == "diagnosed" and res["verdict"]["cause"]
    assert rec["counts"]["deferred"] == 0 and rec["counts"]["model_called"] == 1
    assert "conf=0.9" in rec["escalations"][0]["detail"]


def test_escalation_without_a_verdict_says_why_not_conf_none(env):
    dec = lambda pid: type("Dec", (), {"defer": True, "reason": "OUTSIDE_OFFPEAK_WINDOW", "tier": "standard",  # noqa: E731
                                       "run_after": OUT_OF_WINDOW})()
    call = GovernedCall(_answer(), raise_on_call=True)
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=call, store=FakeStore(), deferral=dec) == 0
    rec = _receipt(env)
    detail = rec["escalations"][0]["detail"]
    assert "conf=None" not in detail and "cause=" not in detail
    assert "no diagnosis yet" in detail and "off-peak deferral" in detail and "retried next cycle" in detail
    assert rec["results"][0]["deferral"]["run_after"] == OUT_OF_WINDOW.isoformat()


def test_final_no_diagnosis_says_not_retried():
    detail = cli._escalation({"siem_id": 9, "incident_key": "k"}, "P1", "egress_refused", OUT_OF_WINDOW)["detail"]
    assert "not retried" in detail and "conf=None" not in detail
    ev = {"incident_key": "k", "run_id": "rem-k-dry_run", "run_state": "RUN_FAILED", "siem_id": 9}
    detail = cli._escalation(ev, "P1", "remediation_failed:RUN_FAILED", OUT_OF_WINDOW)["detail"]
    assert "run=rem-k-dry_run" in detail and "conf=None" not in detail


def test_deferred_incident_is_rediagnosed_and_its_stale_escalation_cleared(env):
    deferred = lambda pid: type("Dec", (), {"defer": True, "reason": "OUTSIDE_OFFPEAK_WINDOW"})()  # noqa: E731
    db = FakeDB([_siem_row()])
    assert _run(env, ["--apply"], db=db, call=GovernedCall(_answer(), raise_on_call=True), store=FakeStore(),
                deferral=deferred) == 0
    state = json.loads((env["state"] / cli.STATE_REL).read_text())
    assert len(state["escalations"]) == 1 and not state["diagnosed"]
    # next cycle (deferral lifted): the same open incident is diagnosed and its catalogue action runs
    call, store = GovernedCall(_answer(action="rerun_dry_run", conf=0.9)), FakeStore()
    assert _run(env, ["--apply"], db=db, call=call, store=store) == 0
    assert len(call.seen) == 1 and len(store.requests) == 1
    state = json.loads((env["state"] / cli.STATE_REL).read_text())
    assert state["escalations"] == {}, "the deferred escalation must stop paging once the incident is handled"
    assert _receipt(env)["escalations"] == []
