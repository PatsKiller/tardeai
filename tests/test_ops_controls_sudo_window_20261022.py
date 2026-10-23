"""Ops -> Controls sudo window, release-train passkey proof, kill-switch read, audit reasons: ANCHOR OPS_CONTROLS_SUDO_WINDOW_20261022.

Operator decision 2026-10-22, verbatim: "approve sudo window"; its policy text ships in AGENTS.md 19.1.0, so the window
is built INERT (setting ``ops_controls.sudo_window_enabled`` default false AND 19.1.0 ACTIVE with its heading).
AGENTS.md 19.0.0 §25.4 (ACTIVE) names the passkey + typed phrase as the release-train resume / arm proof.

Hermetic, on the fixtures of tests/test_ops_controls_20261022.py (in-memory store, fake host runner, fake WebAuthn
verifier, tmp release-train state dir, tmp AGENTS.md). Nothing touches production state (§24.6).

Proves: the window is inert while the setting is false or 19.1.0 is not ACTIVE; one passkey assertion opens it; inside
it a risky act needs only the phrase; it ends on its time, on 15 idle minutes, on "End window now", on revoking its
passkey and when the gate closes; a token from another session or identity is refused; the always-fresh kinds are
refused inside a window at step-up, at approve and in the applier; every act in a window is audited with the opening
assertion id, credential and time; agents are refused on every new route. Release-train resume and arm run through the
applier with a passkey proof that a sudo-window step-up or a forged approval cannot satisfy. Every audit row and every
non-OK section carries a reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib import ops_controls_sudo as SW
from scripts.lib import release_control as RC
from tests.test_ops_controls_20261022 import (  # noqa: F401 — env is a fixture
    ACTIVE_AGENTS, CRON_A, KEY, OP, cred, enroll_passkey, env, get, idem, post, run_applier, sha, step_up,
)

API_PREFIX = "/requests"
AGENTS_19_1 = ACTIVE_AGENTS + ("\n## 27.6 Sudo window\n\n"
                               "| 19.1.0 | 2026-10-23 | ACTIVE | MINOR | sudo window | ratified |\n")


def enable(e, minutes=None, on=True, agents=AGENTS_19_1):
    e.agents.write_text(agents)
    e.store.settings[SW.SETTING_ENABLED] = {"key": SW.SETTING_ENABLED, "value": on, "active": True}
    if minutes is not None:
        e.store.settings[SW.SETTING_MINUTES] = {"key": SW.SETTING_MINUTES, "value": minutes, "active": True}


def create(e, kind, params):
    st, body = post(e, API_PREFIX, {"kind": kind, "params": params, "idempotency_key": idem()})
    assert st == 200, body
    return body["request"]["request_id"]


def open_window(e, kind="crontab.pause", params=None, cid="cred-0001"):
    """A passkey step-up that asks to open a window. Returns (request id, step-up body)."""
    rid = create(e, kind, params or {"line_sha256": sha(CRON_A), "lane_id": "alpha"})
    st, body = post(e, f"/requests/{rid}/step-up/options")
    assert st == 200, body
    req = e.store.get_request(rid)
    st, out = post(e, f"/requests/{rid}/step-up/verify",
                   {"credential": cred(cid, body["options"]["challenge"]), "phrase": req["phrase"],
                    "open_window": True})
    assert st == 200, out
    return rid, out


def window_step(e, rid, token, phrase=None):
    req = e.store.get_request(rid)
    return post(e, f"/requests/{rid}/step-up/window",
                {"sudo_token": token, "phrase": req["phrase"] if phrase is None else phrase})


def pause_beta_params():
    from tests.test_ops_controls_20261022 import CRON_B

    return {"line_sha256": sha(CRON_B), "lane_id": "beta"}


# ── inert gate ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_repository_agents_md_keeps_the_window_inert_until_19_1_0():
    root = Path(__file__).resolve().parents[1]
    g = SW.gate(type("S", (), {"setting_get": lambda self, k: {"value": True, "active": True}})(), root / "AGENTS.md")
    if "| 19.1.0 |" not in (root / "AGENTS.md").read_text():
        assert g["state"] == "INERT" and "19.1.0" in g["reason"]


@pytest.mark.parametrize("agents,on,why", [
    (AGENTS_19_1, False, "sudo_window_enabled is false"),
    (ACTIVE_AGENTS, True, "19.1.0 is not ACTIVE"),
    (AGENTS_19_1.replace("| 19.1.0 | 2026-10-23 | ACTIVE", "| 19.1.0 | 2026-10-23 | PROPOSED"), True, "19.1.0"),
    (AGENTS_19_1.replace("## 27.6 Sudo window", "## 27.6 Something else"), True, "heading absent"),
])
def test_window_is_inert_when_the_setting_is_false_or_policy_is_below_19_1(env, agents, on, why):
    enroll_passkey(env)
    enable(env, on=on, agents=agents)
    rid, out = open_window(env)
    assert out["sudo_window"]["opened"] is False and why in out["sudo_window"]["reason"]
    assert "sudo_token" not in out["sudo_window"]
    # the passkey step-up itself still worked: the request is stepped up the ordinary way
    assert env.store.get_request(rid)["stepup_factor"] == "passkey"
    rid2 = create(env, "crontab.pause", pause_beta_params())
    st, body = window_step(env, rid2, "anything")
    assert (st, body["error"]) == (403, "SUDO_WINDOW_INERT")
    st, state = get(env, "/state")
    assert state["sudo_window"]["state"] == "INERT" and state["sudo_window"]["window"] is None
    assert any(a["action"] == "refused.sudo_window_inert" for a in env.store.audit)


def test_default_setting_is_off_and_minutes_default_60_max_120(env):
    env.agents.write_text(AGENTS_19_1)
    g = SW.gate(env.store, env.agents)
    assert (g["state"], g["enabled"], g["minutes"], g["max_minutes"], g["idle_minutes"]) == ("INERT", False, 60,
                                                                                            120, 15)
    enable(env, minutes=500)
    assert SW.gate(env.store, env.agents)["minutes"] == 120
    from scripts.lib import ops_controls_core as C

    cat = {r["key"]: r for r in C.load_config()["settings_catalog"]}
    assert cat[SW.SETTING_ENABLED]["default"] is False and cat[SW.SETTING_MINUTES]["max"] == 120
    assert cat[SW.SETTING_MINUTES]["default"] == 60


# ── open, use, expire, idle, end ───────────────────────────────────────────────────────────────────────────────────


def test_one_assertion_opens_a_window_and_risky_acts_then_need_only_the_phrase(env):
    enroll_passkey(env)
    enable(env)
    rid, out = open_window(env)
    sw = out["sudo_window"]
    assert sw["opened"] is True and sw["window"]["minutes"] == 60 and sw["window"]["credential_id8"] == "cred-000"
    token = sw["sudo_token"]
    rid2 = create(env, "crontab.pause", pause_beta_params())
    st, body = window_step(env, rid2, token)
    assert st == 200, body
    st, body = post(env, f"/requests/{rid2}/approve", {"step_up_token": body["step_up_token"]})
    assert st == 200 and body["request"]["status"] == "APPROVED"
    r = env.store.get_request(rid2)
    assert r["stepup_factor"] == "sudo_window" and r["stepup_credential_id"] == "cred-0001"
    done = run_applier(env)
    assert {d["request_id"]: d["outcome"] for d in done}[rid2] == "APPLIED"
    assert env.store.get_request(rid2)["result"]["sudo_window"]["opening_request_id"] == rid


def test_wrong_phrase_inside_a_window_is_refused(env):
    enroll_passkey(env)
    enable(env)
    _, out = open_window(env)
    rid2 = create(env, "crontab.pause", pause_beta_params())
    st, body = window_step(env, rid2, out["sudo_window"]["sudo_token"], phrase="PAUSE CRON nope")
    assert (st, body["error"]) == (403, "PHRASE_MISMATCH")


def test_every_act_in_a_window_is_audited_with_the_opening_assertion(env):
    enroll_passkey(env)
    enable(env)
    rid, out = open_window(env)
    opened = [a for a in env.store.audit if a["action"] == "sudo.opened"]
    assert len(opened) == 1
    link = opened[0]["detail"]["sudo_window"]
    assert link["opening_assertion_id"].startswith("asrt_") and link["opening_credential_id8"] == "cred-000"
    assert link["opened_at"] and link["opening_request_id"] == rid
    rid2 = create(env, "crontab.pause", pause_beta_params())
    st, body = window_step(env, rid2, out["sudo_window"]["sudo_token"])
    post(env, f"/requests/{rid2}/approve", {"step_up_token": body["step_up_token"]})
    run_applier(env)
    rows = [a for a in env.store.audit if a["request_id"] == rid2 and a["action"] in
            ("step_up.verified", "request.approved", "request.applied")]
    assert [a["action"] for a in rows] == ["step_up.verified", "request.approved", "request.applied"]
    for a in rows:
        sw = a["detail"]["sudo_window"]
        assert (sw["opening_assertion_id"], sw["opening_credential_id8"], sw["opened_at"]) == (
            link["opening_assertion_id"], link["opening_credential_id8"], link["opened_at"])
    st, state = get(env, "/state")
    reasons = [r["reason"] for r in state["audit"]["rows"] if r["request_id"] == rid2]
    assert reasons and all(link["opening_assertion_id"] in x for x in reasons if "sudo window" in x)


def test_window_expires_after_its_minutes(env):
    enroll_passkey(env)
    enable(env, minutes=20)
    _, out = open_window(env)
    token = out["sudo_window"]["sudo_token"]
    for _ in range(3):  # keep it busy so idle never fires
        env.clock.advance(6 * 60)
        rid = create(env, "setting.set", {"key": "active_trader_alerts.min_buy_ratio", "value": 0.6})
        assert window_step(env, rid, token)[0] == 200
        post(env, f"/requests/{rid}/cancel")
    env.clock.advance(3 * 60)  # 21 minutes since opening
    rid = create(env, "crontab.pause", pause_beta_params())
    st, body = window_step(env, rid, token)
    assert (st, body["error"]) == (403, "SUDO_WINDOW_NOT_OPEN")
    ended = [a for a in env.store.audit if a["action"] == "sudo.ended"]
    assert ended and ended[-1]["detail"]["reason"] == "expired"


def test_window_ends_after_15_idle_minutes(env):
    enroll_passkey(env)
    enable(env)
    _, out = open_window(env)
    env.clock.advance(15 * 60)
    rid = create(env, "crontab.pause", pause_beta_params())
    st, body = window_step(env, rid, out["sudo_window"]["sudo_token"])
    assert (st, body["error"]) == (403, "SUDO_WINDOW_NOT_OPEN")
    assert [a for a in env.store.audit if a["action"] == "sudo.ended"][-1]["detail"]["reason"] == "idle 15 minutes"


def test_end_window_now(env):
    enroll_passkey(env)
    enable(env)
    _, out = open_window(env)
    st, state = get(env, "/state")
    win = state["sudo_window"]["window"]
    assert state["sudo_window"]["state"] == "ACTIVE" and win["remaining_s"] == 15 * 60  # the idle limit bites first
    assert win["expires_at"] == "2026-10-23T16:00:00Z" and win["idle_expires_at"] == "2026-10-23T15:15:00Z"
    st, body = post(env, "/sudo/end")
    assert st == 200 and body["ended"] == 1
    rid = create(env, "crontab.pause", pause_beta_params())
    assert window_step(env, rid, out["sudo_window"]["sudo_token"])[1]["error"] == "SUDO_WINDOW_NOT_OPEN"
    assert get(env, "/state")[1]["sudo_window"]["window"] is None
    assert [a for a in env.store.audit if a["action"] == "sudo.ended"][-1]["detail"]["reason"] == \
        "ended by the operator"


def test_window_ends_when_the_setting_is_turned_off_or_its_passkey_is_revoked(env):
    enroll_passkey(env)
    enable(env)
    _, out = open_window(env)
    env.store.settings[SW.SETTING_ENABLED]["value"] = False
    rid = create(env, "crontab.pause", pause_beta_params())
    assert window_step(env, rid, out["sudo_window"]["sudo_token"])[1]["error"] == "SUDO_WINDOW_INERT"
    enable(env)
    _, out = open_window(env, params=pause_beta_params())
    env.store.credentials["cred-0001"]["revoked_at"] = env.clock().isoformat()
    enroll_passkey(env, "cred-0002")
    rid = create(env, "setting.set", {"key": "active_trader_alerts.min_buy_ratio", "value": 0.6})
    assert window_step(env, rid, out["sudo_window"]["sudo_token"])[1]["error"] == "SUDO_WINDOW_NOT_OPEN"
    assert [a for a in env.store.audit if a["action"] == "sudo.ended"][-1]["detail"]["reason"] == \
        "opening passkey revoked"


def test_window_is_bound_to_its_browser_session_token_and_identity(env):
    enroll_passkey(env)
    enable(env)
    _, out = open_window(env)
    rid = create(env, "crontab.pause", pause_beta_params())
    assert window_step(env, rid, None)[1]["error"] == "SUDO_WINDOW_TOKEN_MISSING"
    assert window_step(env, rid, "forged-token")[1]["error"] == "SUDO_WINDOW_NOT_OPEN"
    # the server keeps only the token's hash
    w = env.ctx.windows.active_for(OP)
    assert w.token_hash == SW.token_hash(out["sudo_window"]["sudo_token"])
    assert out["sudo_window"]["sudo_token"] not in json.dumps(get(env, "/state")[1])
    # another operator identity cannot spend this window, even holding the token
    env.ctx.allowed_logins = frozenset({"john@jwwhiting.com", "other@example.com"})
    env.store.requests[rid]["actor"] = "tailnet:other@example.com"
    env.who["principal"] = "tailnet:other@example.com"
    st, body = window_step(env, rid, out["sudo_window"]["sudo_token"])
    assert (st, body["error"]) == (403, "SUDO_WINDOW_NOT_OPEN")


def test_a_new_window_replaces_the_old_one(env):
    enroll_passkey(env)
    enable(env)
    _, first = open_window(env)
    _, second = open_window(env, params=pause_beta_params())
    rid = create(env, "setting.set", {"key": "active_trader_alerts.min_buy_ratio", "value": 0.6})
    assert window_step(env, rid, first["sudo_window"]["sudo_token"])[1]["error"] == "SUDO_WINDOW_NOT_OPEN"
    assert window_step(env, rid, second["sudo_window"]["sudo_token"])[0] == 200


# ── always-fresh kinds ─────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind,params", [
    ("grant.issue", {"tier": "cron", "for": "30m", "uses": 2, "reason": "testing sudo window"}),
    ("passkey.revoke", {"credential_id": "cred-0001"}),
    ("passkey.register", {"name": "Laptop"}),
    ("setting.set", {"key": SW.SETTING_ENABLED, "value": False}),
    ("setting.set", {"key": SW.SETTING_MINUTES, "value": 30}),
])
def test_always_fresh_kinds_are_refused_inside_a_window(env, kind, params):
    enroll_passkey(env)
    enable(env)
    _, out = open_window(env)
    rid = create(env, kind, params)
    st, body = window_step(env, rid, out["sudo_window"]["sudo_token"])
    assert (st, body["error"]) == (403, "FRESH_PASSKEY_REQUIRED")
    assert env.store.get_request(rid)["status"] == "AWAITING_STEP_UP"
    assert env.store.audit[-1]["action"] == "refused.fresh_passkey_required"
    # ... and a fresh passkey assertion still works for it inside the window
    st, body = step_up(env, rid)
    assert st == 200 and env.store.get_request(rid)["stepup_factor"] == "passkey"


def test_kill_switch_clear_and_release_operator_kinds_are_always_fresh():
    for k in ("kill_switch.clear", "grant.issue", "passkey.register", "passkey.revoke", "release_train.resume",
              "release_train.arm"):
        assert SW.needs_fresh_passkey(k)
    assert SW.needs_fresh_passkey("setting.set", {"key": SW.SETTING_MINUTES})
    assert SW.needs_fresh_passkey("setting.unset", {"key": SW.SETTING_ENABLED})
    assert SW.needs_fresh_passkey("setting.set", {"key": "active_trader_alerts.min_buy_ratio"}) is None
    assert SW.needs_fresh_passkey("crontab.pause") is None


def test_approve_and_applier_refuse_an_always_fresh_kind_carrying_a_window_factor(env):
    """Defence in depth: even a row that somehow reached STEP_UP_VERIFIED / APPROVED with factor sudo_window."""
    enroll_passkey(env)
    enable(env)
    rid = create(env, "grant.issue", {"tier": "cron", "for": "30m", "uses": 2, "reason": "testing sudo window"})
    from scripts.lib import ops_controls_auth as A

    token = "tok-" + "x" * 30
    env.store.transition(rid, ("AWAITING_STEP_UP",), "STEP_UP_VERIFIED", stepup_token_hash=A.token_hash(token),
                         stepup_expires_at=env.clock() + __import__("datetime").timedelta(seconds=60),
                         stepup_factor="sudo_window", stepup_credential_id="cred-0001")
    st, body = post(env, f"/requests/{rid}/approve", {"step_up_token": token})
    assert (st, body["error"]) == (403, "FRESH_PASSKEY_REQUIRED")
    # forge an APPROVED, correctly signed row with the window factor: the applier still refuses it
    row = env.store.get_request(rid)
    row.update(status="APPROVED", approved_at=env.clock())
    row["approval_sig"] = A.sign_approval(KEY, row)
    env.store.requests[rid] = row
    out = run_applier(env)
    assert out == [{"request_id": rid, "outcome": "REFUSED", "code": "FRESH_PASSKEY_REQUIRED"}]
    assert env.host.grants == {}


def test_agents_are_refused_on_the_new_routes(env):
    enroll_passkey(env)
    enable(env)
    rid = create(env, "crontab.pause", pause_beta_params())
    env.who.update(principal="service-token", listener="service")
    for sub in ("/sudo/end", f"/requests/{rid}/step-up/window"):
        st, body = post(env, sub, {"sudo_token": "x", "phrase": "y"})
        assert (st, body["error"]) == (403, "AGENT_CALLER_REFUSED")


# ── release train: resume / arm with a passkey proof ───────────────────────────────────────────────────────────────


HOST = RC.Actor("host_cli", "uid:test")
CC = RC.Actor("cc", "operator@tailnet")
CTRL = RC.Actor("controller", "tradeai-release-train.service")


def _delegation(env):
    from scripts.lib import release_delegation as RD

    d = json.loads(RD.EXAMPLE_PATH.read_text(encoding="utf-8"))
    d.update(status="ACTIVE", delegation_id="rtd-test-0001")
    d["operator"]["approved_at"] = "2026-10-21T17:00:00-04:00"
    for s in d["windows"]["slots"]:
        s["enabled"] = s["window_id"] == "1800"
    p = env.tmp / "delegation" / "delegation.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))
    env.hosts.release_delegation_path = p
    assert RD.load(p).authorized
    return RD.load(p).digest


def _stopped_train(env):
    import os

    _delegation(env)
    ctl = RC.ReleaseControl(env.tmp / "release_window")
    ctl.root.mkdir(parents=True, exist_ok=True)
    ctl.arm(HOST, RC.HostCliProof("/dev/pts/9", os.getuid(), ctl.expected_phrase("arm")),
            policy_digest="a" * 64, reason="armed by test")
    ctl.request_stop(CC, "stop for test")
    ctl.acknowledge_stop(CTRL)
    ctl.settle(CTRL, in_flight=False)
    return ctl


def test_release_resume_via_passkey_through_the_applier(env):
    enroll_passkey(env)
    ctl = _stopped_train(env)
    assert ctl.view().mode == RC.STOPPED
    rid = create(env, "release_train.resume", {"reason": "operator resumes after review"})
    req = env.store.get_request(rid)
    assert req["phrase"] == f"RESUME EPOCH {ctl.view().epoch + 1}" and req["executor"] == "applier"
    st, body = step_up(env, rid)
    assert st == 200
    st, body = post(env, f"/requests/{rid}/approve", {"step_up_token": body["step_up_token"]})
    assert st == 200 and body["request"]["status"] == "APPROVED"
    out = run_applier(env)
    assert out == [{"request_id": rid, "outcome": "APPLIED", "code": None}], out
    v = ctl.view()
    assert v.mode == RC.RUNNING and v.latch_state == RC.LATCH_ABSENT
    assert v.raw["resumed"]["actor"] == {"kind": "passkey", "identity": OP}
    journal = [json.loads(x) for x in ctl.journal_path.read_text().splitlines()]
    assert journal[-1]["command"] == "resume" and journal[-1]["result"]["outcome"] == "RESUMED"


def test_release_arm_via_passkey_through_the_applier(env):
    enroll_passkey(env)
    digest = _delegation(env)
    rid = create(env, "release_train.arm", {"reason": "arm the train for tonight"})
    assert env.store.get_request(rid)["phrase"] == "ARM EPOCH 1"
    st, body = step_up(env, rid)
    post(env, f"/requests/{rid}/approve", {"step_up_token": body["step_up_token"]})
    out = run_applier(env)
    assert out[0]["outcome"] == "APPLIED", out
    v = RC.ReleaseControl(env.tmp / "release_window").view()
    assert v.mode == RC.RUNNING and v.epoch == 1 and v.accepted_policy_digest == digest


def test_release_resume_refused_when_the_epoch_moved_since_the_preview(env):
    enroll_passkey(env)
    ctl = _stopped_train(env)
    rid = create(env, "release_train.resume", {"reason": "operator resumes after review"})
    st, body = step_up(env, rid)
    post(env, f"/requests/{rid}/approve", {"step_up_token": body["step_up_token"]})
    import os

    ctl.resume(HOST, RC.HostCliProof("/dev/pts/9", os.getuid(), ctl.expected_phrase("resume")),
               reason="resumed at the host meanwhile", readiness={"checked_at": "now"})
    ctl.request_stop(CC, "a second stop")  # two new epochs: the approval names an old one
    ctl.acknowledge_stop(CTRL)
    ctl.settle(CTRL, in_flight=False)
    out = run_applier(env)
    assert out[0]["outcome"] == "REFUSED" and out[0]["code"] == "STATE_CHANGED"
    assert ctl.view().mode in (RC.STOP_REQUESTED, RC.STOPPED)


def test_release_passkey_hook_refuses_window_factor_unsigned_and_mismatched_approvals(env):
    from scripts.lib import ops_controls_auth as A
    from scripts.lib import ops_controls_core as C

    approval = {"request_id": "opsreq_" + "1" * 20, "kind": "release_train.resume", "direction": "risky",
                "executor": "applier", "params": {"reason": "x" * 5}, "expected_state_digest": "d",
                "actor": OP, "stepup_factor": "passkey", "stepup_credential_id": "cred-0001",
                "approved_at": env.clock(), "phrase": "RESUME EPOCH 3"}
    approval["approval_sig"] = A.sign_approval(KEY, approval)
    proof = RC.PasskeyProof(approval["request_id"], "cred-0001", "t", "RESUME EPOCH 3")
    ok = C.ApprovalPasskeyHook(approval, KEY, "release_train.resume")
    assert ok.verify(proof, command="resume", expected_phrase="RESUME EPOCH 3")
    assert not ok.verify(proof, command="resume", expected_phrase="RESUME EPOCH 4")       # stale epoch
    assert not ok.verify(proof, command="arm", expected_phrase="RESUME EPOCH 3")          # other command
    assert not C.ApprovalPasskeyHook(approval, b"z" * 40, "release_train.resume").verify(  # wrong key
        proof, command="resume", expected_phrase="RESUME EPOCH 3")
    windowed = dict(approval, stepup_factor="sudo_window")
    windowed["approval_sig"] = A.sign_approval(KEY, windowed)
    assert not C.ApprovalPasskeyHook(windowed, KEY, "release_train.resume").verify(
        proof, command="resume", expected_phrase="RESUME EPOCH 3")
    other = RC.PasskeyProof(approval["request_id"], "cred-9999", "t", "RESUME EPOCH 3")
    assert not ok.verify(other, command="resume", expected_phrase="RESUME EPOCH 3")


def test_release_control_refuses_a_passkey_actor_without_a_hook(tmp_path):
    import os

    ctl = RC.ReleaseControl(tmp_path)
    ctl.arm(HOST, RC.HostCliProof("/dev/pts/9", os.getuid(), ctl.expected_phrase("arm")), policy_digest="a" * 64,
            reason="armed by test")
    ctl.request_stop(CC, "stop")
    ctl.acknowledge_stop(CTRL)
    ctl.settle(CTRL, in_flight=False)
    pk = RC.Actor("passkey", OP)
    proof = RC.PasskeyProof("opsreq_x", "cred", "t", ctl.expected_phrase("resume"))
    with pytest.raises(RC.ControlRefused) as exc:
        ctl.resume(pk, proof, reason="try it", readiness={"checked_at": "now"})
    assert exc.value.code == "OPERATOR_PROOF_REFUSED"
    with pytest.raises(RC.ControlRefused):  # a passkey actor never requests STOP / pause
        ctl.request_pause(pk, "pause")


def test_release_kinds_cannot_be_stepped_up_inside_a_window(env):
    enroll_passkey(env)
    enable(env)
    _stopped_train(env)
    _, out = open_window(env)
    rid = create(env, "release_train.resume", {"reason": "operator resumes after review"})
    st, body = window_step(env, rid, out["sudo_window"]["sudo_token"])
    assert (st, body["error"]) == (403, "FRESH_PASSKEY_REQUIRED")


# ── kill-switch row, audit reasons, section reasons ────────────────────────────────────────────────────────────────


def test_page_reads_kill_switch_state_from_the_existing_read_route_only():
    root = Path(__file__).resolve().parents[1]
    page = (root / "apps/command-center-v3/src/pages/OpsControls.tsx").read_text()
    cell = (root / "apps/command-center-v3/src/components/OpsControlsSudo.tsx").read_text()
    assert "state not in this read model" not in page and "<KillSwitchCell />" in page
    assert "useApi<KillSwitchWire>('/api/v2/execution/kill-switches'" in cell
    src = page + cell
    for forbidden in ("brokers/kill_switches", "--disable", "kill_switches.py"):
        assert forbidden not in src
    assert "_kill_switches_status" in (root / "scripts/api_v2.py").read_text()


def test_audit_rows_and_not_ok_sections_never_have_an_empty_reason(env):
    enroll_passkey(env)
    create(env, "crontab.pause", pause_beta_params())
    rid = create(env, "crontab.pause", {"line_sha256": sha(CRON_A), "lane_id": "alpha"})
    post(env, f"/requests/{rid}/approve", {})                      # refused.step_up_required
    env.who.update(principal="service-token", listener="service")
    post(env, "/requests", {"kind": "release_train.stop", "params": {}, "idempotency_key": idem()})
    env.who.update(principal=OP, listener="serve_proxy")
    st, state = get(env, "/state")
    rows = state["audit"]["rows"]
    assert rows and all(isinstance(r["reason"], str) and r["reason"].strip() for r in rows)
    by = {r["action"]: r["reason"] for r in rows}
    assert "passkey assertion and the typed phrase" in by["refused.step_up_required"]
    assert "service token" in by["refused.caller"]
    env.store.migrated = False
    st, state = get(env, "/state")
    for name in ("audit", "settings"):
        assert state[name]["state"] == "NOT_MIGRATED" and state[name]["reason"], name
    assert "2026_10_22_ops_controls.sql" in state["audit"]["reason"]
    assert "missing" in state["store"]["reason"]
    assert state["sudo_window"]["state"] == "INERT" and state["sudo_window"]["reason"]


def test_kinds_carry_the_fresh_passkey_flag(env):
    st, state = get(env, "/state")
    k = {x["kind"]: x for x in state["kinds"]}
    assert k["grant.issue"]["fresh_passkey"] and not k["crontab.pause"]["fresh_passkey"]
    assert k["release_train.resume"]["supported"] and k["release_train.arm"]["supported"]
    assert not k["release_train.change_scope"]["supported"] and not k["kill_switch.clear"]["supported"]


def test_sudo_migration_only_widens_the_factor_check():
    root = Path(__file__).resolve().parents[1]
    up = (root / "migrations" / "2026_10_22_ops_controls_sudo_window.sql").read_text()
    code = "\n".join(line.split("--", 1)[0] for line in up.splitlines())
    assert "'passkey', 'totp', 'sudo_window'" in code
    for bad in ("DELETE", "TRUNCATE", "DROP TABLE", "DROP COLUMN", "UPDATE ops", "GRANT"):
        assert bad not in code.upper(), bad
    down = (root / "migrations" / "2026_10_22_ops_controls_sudo_window.down.sql").read_text()
    assert "NOT VALID" in down and "DELETE" not in down.upper()
