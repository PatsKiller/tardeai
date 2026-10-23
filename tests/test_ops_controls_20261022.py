"""Ops -> Controls (AGENTS.md 19.0.0 §27.2-§27.3, PROPOSED): ANCHOR OPS_CONTROLS_20261022.

Hermetic. Every host effect goes to a tmp dir or a fake runner (crontab, systemctl, bin/guard, kill-switch CLI are
never executed); the store is the in-memory twin (the Postgres twin is exercised in
tests/test_ops_controls_pg_webauthn_20261022.py on a throwaway cluster). Nothing touches production state (§24.6).

Proves: every POST refuses before 19.0.0 is ACTIVE; agent callers (service token, wrong listener, unknown login) are
refused; CSRF refused; safe actions are one click; risky actions are refused without a passkey assertion AND the typed
phrase; replayed / expired / cross-request step-ups and replayed / expired challenges are refused; TOTP is recovery
only; the applier previews, refuses unsigned / stale / drifted approvals, backs up, applies, verifies and undoes;
the audit is append-only and hash-chained; unsupported kinds say why.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import ops_controls_api as API

C, S, A = API.C, API.S, API.A
ROOT = Path(__file__).resolve().parents[1]
OP = "tailnet:john@jwwhiting.com"
KEY = b"k" * 40

CRON_A = "7,22 9-16 * * 1-5 cd $PROJ && flock -n /tmp/x.lock $PY scripts/alpha_job.py >> logs/a.log 2>&1"
CRON_B = "30 8 * * * cd $PROJ && $PY scripts/beta_job.py --token-free"
PAUSED_C = "# PAUSED 2026-10-14 schwab-app-deactivated 0 6 * * * cd $PROJ && $PY scripts/gamma_job.py"


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


ACTIVE_AGENTS = (
    "# AGENTS\n\n## 27.3 Safe direction one click; risky direction a passkey and a typed phrase\n\n"
    "| Version | Date | Status | Change class | Summary | Approval |\n|---|---|---|---|---|---|\n"
    "| 19.0.0 | 2026-10-22 | ACTIVE | MAJOR | x | ratified |\n")
PROPOSED_AGENTS = ACTIVE_AGENTS.replace("| ACTIVE | MAJOR", "| PROPOSED | MAJOR")


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, s: int) -> None:
        self.t += timedelta(seconds=s)


class FakeHost:
    """Records every argv; serves crontab, systemctl, bin/guard and the kill-switch CLI from memory."""

    def __init__(self, guard_bin: Path) -> None:
        self.crontab = "\n".join(["SHELL=/bin/bash", CRON_A, CRON_B, PAUSED_C, ""])
        self.calls: list[list[str]] = []
        self.guard_bin = str(guard_bin)
        self.grants: dict[str, str] = {}
        self.kill_fail = False

    def __call__(self, argv, stdin=None):
        self.calls.append(list(argv))
        if argv[0] == "crontab":
            if argv[1] == "-l":
                return 0, self.crontab, ""
            self.crontab = stdin
            return 0, "", ""
        if argv[0] == "systemctl":
            return 0, ("active\n" if argv[2] == "is-active" else ""), ""
        if argv[0] == self.guard_bin:
            cmd = argv[1]
            if cmd == "id":
                g = self.grants.get(argv[2])
                return (0, g + "\n", "") if g else (1, "", "no active grant")
            if cmd == "grant":
                assert "--yes" in argv
                self.grants[argv[2]] = "g" * 8 + "1234567890abcdef"
                return 0, "granted", ""
            if cmd == "revoke":
                self.grants.pop(argv[2], None)
                return 0, "revoked", ""
            if cmd == "show":
                lines = ["\x1b[1mActive grants\x1b[0m"] + [
                    f"  \x1b[33m{t:<14}\x1b[0m   10 uses    100m left  id={g[:8]}  — test reason" for t, g in
                    self.grants.items()]
                return 0, "\n".join(lines) + "\n", ""
        if argv[1].endswith("kill_switches.py"):
            if argv[2:] == ["--status"]:
                return 0, '{"global": "engaged"}', ""
            return (1, "", "boom") if self.kill_fail else (0, "enabled", "")
        raise AssertionError(f"unexpected argv {argv}")


@pytest.fixture()
def env(tmp_path):
    clock = Clock()
    guard = tmp_path / "guard"
    guard.write_text('#!/bin/sh\nALL_TIERS="db-write cron config-write broker-read"\n')
    live = tmp_path / "n8n-live-lanes.env"
    live.write_text("# live lanes\nTRADEAI_N8N_RELAY_LIVE_LANES=lane-a lane-b\n")
    live.chmod(0o600)
    registry = {"lanes": [
        {"lane_id": "alpha", "state": "ACTIVE", "scheduler": {"kind": "cron", "match": "scripts/alpha_job.py"}},
        {"lane_id": "beta", "state": "ACTIVE", "scheduler": {"kind": "cron", "match": "scripts/beta_job.py"}},
        {"lane_id": "gamma", "state": "PAUSED", "scheduler": {"kind": "cron", "match": "scripts/gamma_job.py"}},
        {"lane_id": "lane-a", "state": "ACTIVE", "scheduler": {"kind": "cron", "stage": "canary"},
         "dispatch": {"mode": "live"}},
        {"lane_id": "lane-c", "state": "ACTIVE", "scheduler": {"kind": "cron", "stage": "shadow"},
         "dispatch": {"mode": "dry_run"}},
    ]}
    code_root = tmp_path / "code"
    (code_root / "config").mkdir(parents=True)
    (code_root / "config" / "lane_registry.json").write_text(json.dumps(registry))
    (code_root / "config" / "data_source_authority.json").write_text(json.dumps(
        {"proposed_domains": [{"domain": "operator_settings", "title": "t", "status": "proposed"}]}))
    cfg = C.load_config()
    cfg = json.loads(json.dumps(cfg))
    cfg["live_list"]["file"] = str(live)
    cfg["guard"]["bin"] = str(guard)
    cfg["applier"].update(backup_dir=str(tmp_path / "backups"), heartbeat_file=str(tmp_path / "hb.json"),
                          lock_file=str(tmp_path / "applier.lock"))
    cfg["release_train"]["state_dir"] = str(tmp_path / "release_window")
    agents = tmp_path / "AGENTS.md"
    agents.write_text(ACTIVE_AGENTS)
    host = FakeHost(guard)
    hosts = C.Hosts(cfg, code_root=code_root, runner=host, clock=clock,
                    release_state_dir=tmp_path / "release_window")
    store = S.MemoryStore(clock=clock)
    verifier = FakeVerifier()
    who = {"principal": OP, "listener": "serve_proxy", "csrf": (True, "")}
    notes: list = []
    ctx = API.Ctx(cfg=cfg, store=store, hosts=hosts, verifier=verifier, principal=lambda: who["principal"],
                  listener=lambda: who["listener"], csrf=lambda m, p: who["csrf"],
                  allowed_logins=frozenset({"john@jwwhiting.com"}), hmac_key=lambda: KEY,
                  totp_secret=lambda: None, agents_path=agents, clock=clock,
                  notify=lambda s, b, r: notes.append((s, r)) or {"queued": True})
    return type("Env", (), dict(ctx=ctx, store=store, host=host, hosts=hosts, clock=clock, who=who, cfg=cfg,
                                agents=agents, live=live, verifier=verifier, notes=notes, tmp=tmp_path))


class FakeVerifier:
    """Stands in for py_webauthn (the real library is exercised in the PG/WebAuthn test file). A 'good' signature
    passes; anything else raises ASSERTION_INVALID. It never decides challenge freshness: the store does."""

    def __init__(self) -> None:
        self.uv = True

    def authentication_options(self, *, challenge, allow_ids):
        return {"challenge": b64(challenge), "allowCredentials": [{"id": i, "type": "public-key"} for i in allow_ids],
                "userVerification": "required", "rpId": "ms01-openclaw.tail163d14.ts.net"}

    def verify_assertion(self, *, credential, challenge, public_key, sign_count):
        if credential["response"].get("signature") != "good":
            raise A.AuthError("ASSERTION_INVALID", "bad signature")
        return A.VerifiedAssertion(credential["rawId"], sign_count + 1, self.uv)

    def registration_options(self, *, challenge, user_handle, user_name, exclude_ids):
        return {"challenge": b64(challenge), "excludeCredentials": exclude_ids}

    def verify_registration(self, *, credential, challenge):
        return A.VerifiedRegistration(credential["rawId"], "pk-" + credential["rawId"], 0, None, ["internal"])


def cred(cid: str, challenge: str, sig: str = "good") -> dict:
    cdj = json.dumps({"type": "webauthn.get", "challenge": challenge, "origin": "https://ms01-openclaw.tail163d14.ts.net"})
    return {"id": cid, "rawId": cid, "type": "public-key",
            "response": {"clientDataJSON": b64(cdj.encode()), "authenticatorData": "x", "signature": sig}}


def post(e, sub, body=None):
    return API.handle(API.PREFIX + sub, "POST", body or {}, ctx=e.ctx)


def get(e, sub):
    return API.handle(API.PREFIX + sub, "GET", None, ctx=e.ctx)


_idem = iter(range(10**6))


def idem() -> str:
    return f"idem-{next(_idem):08d}"


def enroll_passkey(e, cid="cred-0001"):
    e.store.credential_add({"credential_id": cid, "name": "Pixel", "public_key": "pk", "user_handle": "u",
                            "created_by": OP, "created_request_id": "seed"})


def step_up(e, rid, cid="cred-0001", phrase=None, sig="good"):
    st, body = post(e, f"/requests/{rid}/step-up/options")
    assert st == 200, body
    req = e.store.get_request(rid)
    st, body = post(e, f"/requests/{rid}/step-up/verify",
                    {"credential": cred(cid, body["options"]["challenge"], sig),
                     "phrase": req["phrase"] if phrase is None else phrase})
    return st, body


def risky(e, kind, params):
    st, body = post(e, "/requests", {"kind": kind, "params": params, "idempotency_key": idem()})
    assert st == 200, body
    rid = body["request"]["request_id"]
    st, body = step_up(e, rid)
    assert st == 200, body
    st, body = post(e, f"/requests/{rid}/approve", {"step_up_token": body["step_up_token"]})
    assert st == 200 and body["request"]["status"] in ("APPROVED", "APPLIED"), body
    return rid


def run_applier(e):
    from scripts.ops import operator_controls_applier as AP

    return AP.process_once(cfg=e.cfg, store=e.store, hosts=e.hosts, hmac_key=KEY, agents_path=e.agents,
                           clock=e.clock, notify=e.ctx.notify)


def sha(s: str) -> str:
    return C.sha256_text(s)


# ── policy gate ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_policy_state_reads_the_19_row_and_fails_closed(tmp_path):
    p = tmp_path / "A.md"
    p.write_text(ACTIVE_AGENTS)
    assert C.policy_state(p)["state"] == "ACTIVE"
    p.write_text(PROPOSED_AGENTS)
    assert C.policy_state(p)["state"] == "NOT_ACTIVE"
    p.write_text(ACTIVE_AGENTS.replace("## 27.3", "## 99.9"))
    assert C.policy_state(p)["state"] == "NOT_ACTIVE"
    assert C.policy_state(tmp_path / "missing.md")["state"] == "UNREADABLE"


def test_repository_agents_md_is_19_active_so_the_surface_may_answer_after_setup():
    # Flipped 2026-10-22 when the operator ratified AGENTS.md 19.0.0 (PR #1962, token comment 6352416425).
    # Operator, verbatim, approving this flip: "Approved both". The policy gate now opens; the surface still
    # refuses every risky action until its own setup exists (deps, migration, applier HMAC key, an enrolled
    # passkey): see the PASSKEY_REQUIRED / step-up tests in this file, which stay unchanged.
    assert C.policy_state(ROOT / "AGENTS.md")["state"] == "ACTIVE"


POST_ROUTES = ["/requests", "/requests/opsreq_" + "0" * 20 + "/approve",
               "/requests/opsreq_" + "0" * 20 + "/step-up/options", "/requests/opsreq_" + "0" * 20 + "/step-up/verify",
               "/requests/opsreq_" + "0" * 20 + "/step-up/totp", "/requests/opsreq_" + "0" * 20 + "/cancel",
               "/requests/opsreq_" + "0" * 20 + "/undo", "/passkeys/register/options", "/passkeys/register/verify"]


@pytest.mark.parametrize("sub", POST_ROUTES)
@pytest.mark.parametrize("text", [PROPOSED_AGENTS, "# no row\n", None])
def test_every_post_refuses_policy_not_active(env, sub, text):
    if text is None:
        env.agents.unlink()
    else:
        env.agents.write_text(text)
    st, body = post(env, sub, {"kind": "release_train.stop", "params": {}, "idempotency_key": idem(),
                               "one_click": True})
    assert (st, body["error"]) == (409, "POLICY_NOT_ACTIVE")
    assert env.store.requests == {} and env.store.audit == []


def test_get_state_answers_while_inert_and_shows_why(env):
    env.agents.write_text(PROPOSED_AGENTS)
    st, body = get(env, "/state")
    assert st == 200 and body["policy"]["state"] == "NOT_ACTIVE"
    assert body["schema"] == "OpsControlsState@v1" and body["jobs"]["state"] == "OK"


# ── callers, CSRF, store ───────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("principal,listener", [
    ("service-token", "service"), ("service-token", "serve_proxy"), (OP, "service"), (OP, None),
    ("tailnet:intruder@example.com", "serve_proxy"), ("", "serve_proxy"), ("disabled", "serve_proxy"),
    ("exempt", "service")])
def test_agent_and_non_operator_callers_are_refused_on_get_and_post(env, principal, listener):
    env.who.update(principal=principal, listener=listener)
    assert get(env, "/state")[1]["error"] == "AGENT_CALLER_REFUSED"
    st, body = post(env, "/requests", {"kind": "release_train.stop", "params": {}, "idempotency_key": idem(),
                                       "one_click": True})
    assert (st, body["error"]) == (403, "AGENT_CALLER_REFUSED")
    assert env.store.requests == {}
    assert env.store.audit[-1]["action"] == "refused.caller"


def test_body_cannot_claim_the_operator_identity(env):
    env.who.update(principal="service-token", listener="service")
    st, body = post(env, "/requests", {"kind": "release_train.stop", "params": {}, "idempotency_key": idem(),
                                       "actor": OP, "operator": OP, "one_click": True})
    assert body["error"] == "AGENT_CALLER_REFUSED"


def test_csrf_refusal(env):
    env.who["csrf"] = (False, "csrf: Origin not on allowlist")
    st, body = post(env, "/requests", {"kind": "release_train.stop", "params": {}, "idempotency_key": idem()})
    assert (st, body["error"]) == (403, "CSRF_REFUSED") and env.store.requests == {}


def test_store_not_migrated_refuses(env):
    env.store.migrated = False
    st, body = post(env, "/requests", {"kind": "release_train.stop", "params": {}, "idempotency_key": idem()})
    assert (st, body["error"]) == (503, "STORE_NOT_MIGRATED")


def test_cc_auth_config_makes_ops_controls_a_hard_csrf_route():
    from scripts.lib import cc_auth

    cfg = cc_auth.load_config(ROOT / "config" / "cc_auth.yaml")
    assert cc_auth.csrf_class(cfg, "POST", "/api/v2/ops/controls/requests") == "hard"
    assert cc_auth.step_up_action(cfg, "POST", "/api/v2/ops/controls/requests") is None


def test_api_v2_dispatches_ops_controls():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    assert 'base_path.startswith("/api/v2/ops/controls/")' in src and "ops_controls_api as _oca" in src


# ── safe direction: one click ──────────────────────────────────────────────────────────────────────────────────────


def test_release_stop_is_one_click_and_writes_the_existing_latch(env):
    st, body = post(env, "/requests", {"kind": "release_train.stop", "params": {"reason": "test"},
                                       "idempotency_key": idem(), "one_click": True})
    assert st == 200 and body["request"]["status"] == "APPLIED", (body["request"]["result"] or {}).get("verify")
    assert (env.tmp / "release_window" / "STOP.json").is_file()
    assert body["request"]["undo"]["available"] is False
    actions = [a["action"] for a in env.store.audit]
    assert actions == ["request.created", "request.approved", "request.applied"]


def test_kill_switch_engage_is_one_click_then_applied_by_the_applier_via_the_existing_cli(env):
    st, body = post(env, "/requests", {"kind": "kill_switch.engage", "params": {"scope": "global"},
                                       "idempotency_key": idem(), "one_click": True})
    assert st == 200 and body["request"]["status"] == "APPROVED"
    assert not any("kill_switches.py" in " ".join(c) for c in env.host.calls)  # the CC process never runs it
    out = run_applier(env)
    assert out[0]["outcome"] == "APPLIED"
    enable = [c for c in env.host.calls if c[1].endswith("kill_switches.py") and "--enable" in c]
    assert enable and enable[0][2:4] == ["--enable", "global"]
    assert not any("--disable" in c for c in env.host.calls)


def test_one_click_is_ignored_for_a_risky_kind(env):
    st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A)},
                                       "idempotency_key": idem(), "one_click": True})
    assert body["request"]["status"] == "AWAITING_STEP_UP" and "one_click ignored" in body["note"]


@pytest.mark.parametrize("kind", ["kill_switch.clear", "release_train.resume", "release_train.arm",
                                  "release_train.change_scope", "release_train.revoke"])
def test_unsupported_kinds_say_why(env, kind):
    st, body = post(env, "/requests", {"kind": kind, "params": {}, "idempotency_key": idem()})
    assert (st, body["error"]) == (409, "KIND_NOT_SUPPORTED") and "grant" in body["detail"] or "D3" in body["detail"]


def test_kill_switch_clear_reason_names_the_execution_engineering_grant():
    assert "execution-engineering" in C.KINDS["kill_switch.clear"].reason


# ── risky direction: passkey + phrase ──────────────────────────────────────────────────────────────────────────────


def test_risky_refused_without_step_up(env):
    st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A),
                                                                           "lane_id": "alpha"},
                                       "idempotency_key": idem()})
    rid = body["request"]["request_id"]
    assert body["request"]["phrase"] == "PAUSE CRON alpha 2026-10-23"
    assert post(env, f"/requests/{rid}/approve", {})[1]["error"] == "STEP_UP_REQUIRED"
    assert post(env, f"/requests/{rid}/approve", {"step_up_token": "forged"})[1]["error"] == "STEP_UP_REQUIRED"
    assert env.store.get_request(rid)["status"] == "AWAITING_STEP_UP"
    assert run_applier(env) == []


def test_risky_needs_an_enrolled_passkey(env):
    st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A)},
                                       "idempotency_key": idem()})
    st, b = post(env, f"/requests/{body['request']['request_id']}/step-up/options")
    assert (st, b["error"]) == (409, "PASSKEY_REQUIRED")


def test_wrong_phrase_refused_and_the_challenge_is_spent(env):
    enroll_passkey(env)
    st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A),
                                                                           "lane_id": "alpha"},
                                       "idempotency_key": idem()})
    rid = body["request"]["request_id"]
    st, opts = post(env, f"/requests/{rid}/step-up/options")
    c = cred("cred-0001", opts["options"]["challenge"])
    st, b = post(env, f"/requests/{rid}/step-up/verify", {"credential": c, "phrase": "pause cron alpha"})
    assert (st, b["error"]) == (403, "PHRASE_MISMATCH")
    st, b = post(env, f"/requests/{rid}/step-up/verify", {"credential": c, "phrase": "PAUSE CRON alpha 2026-10-23"})
    assert (st, b["error"]) == (403, "CHALLENGE_REPLAYED")


def test_bad_assertion_unknown_and_revoked_passkeys_refused(env):
    enroll_passkey(env)
    st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A)},
                                       "idempotency_key": idem()})
    rid = body["request"]["request_id"]
    assert step_up(env, rid, sig="bad")[1]["error"] == "ASSERTION_INVALID"
    assert step_up(env, rid, cid="cred-unknown")[1]["error"] == "PASSKEY_UNKNOWN"
    env.store.credential_revoke("cred-0001", actor=OP, request_id="x")
    assert post(env, f"/requests/{rid}/step-up/options")[1]["error"] == "PASSKEY_REQUIRED"


def test_user_verification_is_required(env):
    enroll_passkey(env)
    env.verifier.uv = False
    st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A)},
                                       "idempotency_key": idem()})
    assert step_up(env, body["request"]["request_id"])[1]["error"] == "ASSERTION_INVALID"


def test_expired_challenge_refused(env):
    enroll_passkey(env)
    st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A)},
                                       "idempotency_key": idem()})
    rid = body["request"]["request_id"]
    st, opts = post(env, f"/requests/{rid}/step-up/options")
    env.clock.advance(121)
    st, b = post(env, f"/requests/{rid}/step-up/verify", {"credential": cred("cred-0001", opts["options"]["challenge"]),
                                                          "phrase": env.store.get_request(rid)["phrase"]})
    assert (st, b["error"]) == (403, "CHALLENGE_EXPIRED")


def test_challenge_is_bound_to_its_request(env):
    enroll_passkey(env)
    ids = []
    for line in (CRON_A, CRON_B):
        st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(line)},
                                           "idempotency_key": idem()})
        ids.append(body["request"]["request_id"])
    st, opts = post(env, f"/requests/{ids[0]}/step-up/options")
    st, b = post(env, f"/requests/{ids[1]}/step-up/verify", {"credential": cred("cred-0001", opts["options"]["challenge"]),
                                                             "phrase": env.store.get_request(ids[1])["phrase"]})
    assert b["error"] == "CHALLENGE_UNKNOWN"


def test_step_up_token_replayed_expired_and_cross_request_refused(env):
    enroll_passkey(env)
    reqs = []
    for line in (CRON_A, CRON_B):
        st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(line)},
                                           "idempotency_key": idem()})
        rid = body["request"]["request_id"]
        st, b = step_up(env, rid)
        reqs.append((rid, b["step_up_token"]))
    (r1, t1), (r2, t2) = reqs
    assert post(env, f"/requests/{r2}/approve", {"step_up_token": t1})[1]["error"] == "STEP_UP_INVALID"
    assert post(env, f"/requests/{r1}/approve", {"step_up_token": t1})[1]["request"]["status"] == "APPROVED"
    assert post(env, f"/requests/{r1}/approve", {"step_up_token": t1})[1]["error"] == "STEP_UP_REPLAYED"
    env.clock.advance(121)
    assert post(env, f"/requests/{r2}/approve", {"step_up_token": t2})[1]["error"] == "STEP_UP_EXPIRED"
    assert env.store.get_request(r2)["status"] == "EXPIRED"


def test_cannot_step_up_someone_elses_request(env):
    enroll_passkey(env)
    st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A)},
                                       "idempotency_key": idem()})
    rid = body["request"]["request_id"]
    env.store.requests[rid]["actor"] = "tailnet:other@example.com"
    assert post(env, f"/requests/{rid}/step-up/options")[1]["error"] == "ACTOR_MISMATCH"


def test_idempotency_replay_and_conflict(env):
    k = idem()
    b1 = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A)}, "idempotency_key": k})[1]
    b2 = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A)}, "idempotency_key": k})[1]
    assert b2["replayed"] and b1["request"]["request_id"] == b2["request"]["request_id"]
    b3 = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_B)}, "idempotency_key": k})
    assert b3[1]["error"] == "IDEMPOTENCY_CONFLICT"


# ── the applier: preview, backup, apply, verify, undo ──────────────────────────────────────────────────────────────


def test_crontab_pause_apply_and_undo_round_trip(env):
    enroll_passkey(env)
    original = env.host.crontab
    rid = risky(env, "crontab.pause", {"line_sha256": sha(CRON_A), "lane_id": "alpha"})
    pre = env.store.get_request(rid)["preview"]
    assert pre["diff"][0].startswith("- 7,22") and pre["diff"][1].startswith("+ # PAUSED 2026-10-23 ops-controls:")
    assert run_applier(env)[0]["outcome"] == "APPLIED"
    assert f"# PAUSED 2026-10-23 ops-controls:{rid} {CRON_A}" in env.host.crontab
    res = env.store.get_request(rid)["result"]
    assert Path(res["backup_ref"]).read_text() == original and res["verify"]["read_back_matches"]
    st, state = get(env, "/state")
    alpha = [r for r in state["jobs"]["rows"] if r["lane_id"] == "alpha"][0]
    assert alpha["cron_state"] == "PAUSED" and alpha["paused_note"] == f"ops-controls:{rid}"
    row = [a for a in state["audit"]["rows"] if a["request_id"] == rid and a["action"] == "request.applied"][0]
    assert row["undo_available"]
    # undo: the inverse request has its own (risky) factors
    st, body = post(env, f"/requests/{rid}/undo", {"idempotency_key": idem()})
    u = body["request"]
    assert u["kind"] == "crontab.resume" and u["status"] == "AWAITING_STEP_UP" and u["undo_of"] == rid
    st, b = step_up(env, u["request_id"])
    post(env, f"/requests/{u['request_id']}/approve", {"step_up_token": b["step_up_token"]})
    assert run_applier(env)[0]["outcome"] == "APPLIED"
    assert env.host.crontab == original
    assert env.store.get_request(rid)["undone_by"] == u["request_id"]
    assert post(env, f"/requests/{rid}/undo", {"idempotency_key": idem()})[1]["error"] == "UNDO_NOT_AVAILABLE"


def test_resume_of_a_hand_paused_broker_line_warns_and_restores_exact_text(env):
    enroll_passkey(env)
    st, body = post(env, "/requests", {"kind": "crontab.resume", "params": {"line_sha256": sha(PAUSED_C),
                                                                            "lane_id": "gamma"},
                                       "idempotency_key": idem()})
    assert body["request"]["phrase"] == "RESUME CRON gamma 2026-10-23"
    assert body["request"]["preview"]["after"] == "0 6 * * * cd $PROJ && $PY scripts/gamma_job.py"


def test_applier_refuses_when_the_target_moved_since_the_preview(env):
    enroll_passkey(env)
    rid = risky(env, "crontab.pause", {"line_sha256": sha(CRON_A)})
    env.host.crontab += "15 * * * * echo new\n"
    out = run_applier(env)
    assert out[0]["outcome"] == "REFUSED" and out[0]["code"] == "STATE_CHANGED"
    assert "# PAUSED" not in env.host.crontab.split(CRON_B)[0] or CRON_A in env.host.crontab
    assert env.store.get_request(rid)["status"] == "REFUSED"


def test_applier_refuses_unsigned_tampered_and_stale_approvals(env):
    enroll_passkey(env)
    r1 = risky(env, "crontab.pause", {"line_sha256": sha(CRON_A)})
    env.store.requests[r1]["params"] = {"line_sha256": sha(CRON_B)}  # an agent edits the row: the sig breaks
    r2 = risky(env, "crontab.pause", {"line_sha256": sha(CRON_B)})
    env.store.requests[r2]["approval_sig"] = None
    out = {o["request_id"]: o for o in run_applier(env)}
    assert out[r1]["code"] == "SIGNATURE_INVALID" and out[r2]["code"] == "SIGNATURE_INVALID"
    assert CRON_A in env.host.crontab.split("\n") and CRON_B in env.host.crontab.split("\n")
    r3 = risky(env, "n8n_live_list.add", {"lane_id": "lane-c"})
    env.clock.advance(121)
    assert run_applier(env)[0]["outcome"] == "EXPIRED"
    assert env.store.get_request(r3)["status"] == "EXPIRED"


def test_forged_approved_row_without_the_key_is_refused(env):
    """An agent with database access writes an APPROVED row directly: no HMAC key, no apply."""
    row = {"request_id": "opsreq_" + "f" * 20, "idempotency_key": "forged-0001", "kind": "n8n_live_list.add",
           "direction": "risky", "executor": "applier", "params": {"lane_id": "lane-c"}, "actor": OP,
           "status": "APPROVED", "approved_at": env.clock(), "approval_sig": "0" * 64}
    env.store.create_request(row)
    assert run_applier(env)[0]["code"] == "SIGNATURE_INVALID"
    assert "lane-c" not in env.live.read_text()


def test_applier_is_inert_before_19_active(env):
    enroll_passkey(env)
    rid = risky(env, "crontab.pause", {"line_sha256": sha(CRON_A)})
    env.agents.write_text(PROPOSED_AGENTS)
    assert run_applier(env) == []
    assert env.store.get_request(rid)["status"] == "APPROVED"
    assert json.loads((env.tmp / "hb.json").read_text())["policy"] == "NOT_ACTIVE"


def test_applier_single_writer_lock(env):
    from scripts.ops import operator_controls_applier as AP

    first = AP._lock(env.cfg)
    assert first is not None and AP._lock(env.cfg) is None
    first.close()


def test_live_list_add_backup_restart_and_undo(env):
    enroll_passkey(env)
    before = env.live.read_text()
    rid = risky(env, "n8n_live_list.add", {"lane_id": "lane-c"})
    assert env.store.get_request(rid)["phrase"] == "ADD LIVE lane-c 2026-10-23"
    assert run_applier(env)[0]["outcome"] == "APPLIED"
    assert "TRADEAI_N8N_RELAY_LIVE_LANES=lane-a lane-b lane-c" in env.live.read_text()
    assert oct(env.live.stat().st_mode & 0o777) == "0o600"
    bak = Path(env.store.get_request(rid)["result"]["backup_ref"])
    assert bak.read_text() == before and bak.name.startswith("n8n-live-lanes.env.bak-")
    assert ["systemctl", "--user", "restart", "tradeai-n8n-run-relay.service"] in env.host.calls
    st, body = post(env, f"/requests/{rid}/undo", {"idempotency_key": idem()})
    u = body["request"]["request_id"]
    st, b = step_up(env, u)
    post(env, f"/requests/{u}/approve", {"step_up_token": b["step_up_token"]})
    run_applier(env)
    assert env.live.read_text() == before


def test_live_list_refuses_unknown_lanes_and_no_change(env):
    st, b = post(env, "/requests", {"kind": "n8n_live_list.add", "params": {"lane_id": "nope"}, "idempotency_key": idem()})
    assert b["error"] == "LANE_UNKNOWN"
    st, b = post(env, "/requests", {"kind": "n8n_live_list.add", "params": {"lane_id": "lane-a"}, "idempotency_key": idem()})
    assert b["error"] == "NO_CHANGE"
    st, b = post(env, "/requests", {"kind": "n8n_live_list.add", "params": {"lane_id": "x; rm -rf"}, "idempotency_key": idem()})
    assert b["error"] == "PARAMS_INVALID"


def test_setting_set_history_and_undo(env):
    enroll_passkey(env)
    key = "active_trader_alerts.min_buy_ratio"
    st, b = post(env, "/requests", {"kind": "setting.set", "params": {"key": key, "value": 5}, "idempotency_key": idem()})
    assert b["error"] == "SETTING_VALUE_INVALID"
    st, b = post(env, "/requests", {"kind": "setting.set", "params": {"key": "nope.key", "value": 1},
                                    "idempotency_key": idem()})
    assert b["error"] == "SETTING_UNKNOWN"
    rid = risky(env, "setting.set", {"key": key, "value": 0.6})
    run_applier(env)
    assert env.store.setting_get(key)["value"] == 0.6
    rid2 = risky(env, "setting.set", {"key": key, "value": 0.62})
    run_applier(env)
    st, state = get(env, "/state")
    row = [r for r in state["settings"]["rows"] if r["key"] == key][0]
    assert row["current"] == 0.62 and row["overridden"] and row["wired"] is False
    assert [h["new_value"] for h in state["settings"]["history"]] == [0.62, 0.6]
    st, body = post(env, f"/requests/{rid2}/undo", {"idempotency_key": idem()})
    assert body["request"]["params"] == {"key": key, "value": 0.6}
    assert rid


def test_grant_issue_and_revoke_through_bin_guard(env):
    enroll_passkey(env)
    st, b = post(env, "/requests", {"kind": "grant.issue", "params": {"tier": "root", "for": "2h", "uses": 3,
                                                                      "reason": "a long enough reason"},
                                    "idempotency_key": idem()})
    assert b["error"] == "TIER_UNKNOWN"
    st, b = post(env, "/requests", {"kind": "grant.issue", "params": {"tier": "broker-read", "for": "2h", "uses": -1,
                                                                      "reason": "a long enough reason"},
                                    "idempotency_key": idem()})
    assert b["error"] == "PARAMS_INVALID"
    rid = risky(env, "grant.issue", {"tier": "broker-read", "for": "2h", "uses": 3, "reason": "operator read sync"})
    assert run_applier(env)[0]["outcome"] == "APPLIED"
    issued = env.store.get_request(rid)["result"]["grant_id"]
    argv = [c for c in env.host.calls if len(c) > 1 and c[1] == "grant"][0]
    assert argv[2:] == ["broker-read", "--for", "7200s", "--uses", "3", "--reason",
                        f"operator read sync (ops-controls {rid})", "--yes"]
    st, state = get(env, "/state")
    assert state["grants"]["active"][0]["grant_id"] == issued
    st, body = post(env, f"/requests/{rid}/undo", {"idempotency_key": idem()})
    assert body["request"]["kind"] == "grant.revoke" and body["request"]["params"]["grant_id"] == issued


# ── TOTP is recovery only ──────────────────────────────────────────────────────────────────────────────────────────


def test_totp_refused_for_anything_but_registering_the_first_passkey(env):
    st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A)},
                                       "idempotency_key": idem()})
    rid = body["request"]["request_id"]
    assert post(env, f"/requests/{rid}/step-up/totp", {"code": "123456", "phrase": "x"})[1]["error"] == \
        "TOTP_NOT_ALLOWED"
    enroll_passkey(env)
    st, body = post(env, "/requests", {"kind": "passkey.register", "params": {"name": "Laptop"},
                                       "idempotency_key": idem()})
    rid = body["request"]["request_id"]
    assert post(env, f"/requests/{rid}/step-up/totp", {"code": "123456", "phrase": "x"})[1]["error"] == \
        "TOTP_NOT_ALLOWED"


def test_totp_recovery_registers_the_first_passkey_once(env):
    pyotp = pytest.importorskip("pyotp")
    secret = pyotp.random_base32()
    env.ctx.totp_secret = lambda: secret
    env.store.totp_enroll(label="phone", fingerprint=A.totp_fingerprint(secret), actor="host")
    st, body = post(env, "/requests", {"kind": "passkey.register", "params": {"name": "Pixel 11"},
                                       "idempotency_key": idem()})
    req = body["request"]
    code = pyotp.TOTP(secret).at(env.clock().timestamp())
    st, b = post(env, f"/requests/{req['request_id']}/step-up/totp", {"code": code, "phrase": req["phrase"]})
    assert st == 200, b
    st, b = post(env, f"/requests/{req['request_id']}/approve", {"step_up_token": b["step_up_token"]})
    st, opts = post(env, "/passkeys/register/options", {"request_id": req["request_id"]})
    c = cred("new-cred-01", opts["options"]["challenge"])
    st, b = post(env, "/passkeys/register/verify", {"request_id": req["request_id"], "credential": c})
    assert st == 200 and b["request"]["status"] == "APPLIED" and env.store.credential_get("new-cred-01")
    # the same code again (replay) is refused even for a new request
    st, body = post(env, "/requests", {"kind": "passkey.register", "params": {"name": "Spare"}, "idempotency_key": idem()})
    assert post(env, f"/requests/{body['request']['request_id']}/step-up/totp",
                {"code": code, "phrase": body["request"]["phrase"]})[1]["error"] == "TOTP_NOT_ALLOWED"


def test_passkey_revoke_needs_a_passkey_and_phrase(env):
    enroll_passkey(env)
    enroll_passkey(env, "cred-0002")
    st, b = post(env, "/requests", {"kind": "passkey.revoke", "params": {"credential_id8": "cred-000"},
                                    "idempotency_key": idem()})
    assert b["error"] == "PARAMS_INVALID"  # an ambiguous prefix never picks one
    rid = risky(env, "passkey.revoke", {"credential_id": "cred-0002"})
    assert env.store.get_request(rid)["status"] == "APPLIED"  # executed by the CC process right after approval
    assert env.store.credential_get("cred-0002")["revoked_at"] and not env.store.credential_get("cred-0001")["revoked_at"]


# ── audit ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_audit_is_append_only_and_hash_chained(env):
    post(env, "/requests", {"kind": "release_train.stop", "params": {}, "idempotency_key": idem(), "one_click": True})
    assert len(env.store.audit) >= 3 and S.verify_audit_chain(env.store.audit)
    with pytest.raises(S.StoreError):
        env.store.audit_update(1, outcome="x")
    with pytest.raises(S.StoreError):
        env.store.audit_delete(1)
    env.store.audit[0]["outcome"] = "tampered"
    assert not S.verify_audit_chain(env.store.audit)


def test_every_refusal_is_audited(env):
    st, body = post(env, "/requests", {"kind": "crontab.pause", "params": {"line_sha256": sha(CRON_A)},
                                       "idempotency_key": idem()})
    post(env, f"/requests/{body['request']['request_id']}/approve", {})
    assert "refused.step_up_required" in [a["action"] for a in env.store.audit]


# ── read model ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_state_read_model_sections(env):
    st, s = get(env, "/state")
    assert st == 200
    rows = {r["lane_id"]: r for r in s["jobs"]["rows"]}
    assert rows["alpha"]["cron_state"] == "ACTIVE" and rows["alpha"]["line_sha256"] == sha(CRON_A)
    assert rows["gamma"]["cron_state"] == "PAUSED" and rows["gamma"]["paused_on"] == "2026-10-14"
    assert s["n8n"]["live_lanes"] == ["lane-a", "lane-b"]
    assert {r["lane_id"]: r["on_live_list"] for r in s["n8n"]["rows"]} == {"lane-a": True, "lane-c": False}
    assert s["data_approvals"]["rows"][0]["domain"] == "operator_settings"
    assert s["applier"]["state"] == "ABSENT" and s["factors"]["hmac_key"] == "present"
    kinds = {k["kind"]: k for k in s["kinds"]}
    assert kinds["release_train.stop"]["direction"] == "safe" and kinds["kill_switch.engage"]["direction"] == "safe"
    assert all(k["direction"] == "risky" for k in kinds.values() if k["kind"] not in
               ("release_train.stop", "release_train.pause", "kill_switch.engage"))


def test_unreadable_sections_are_unavailable_not_empty(env):
    env.live.unlink()
    env.host.crontab = None

    def broken(argv, stdin=None):
        return 1, "", "no crontab"
    env.hosts.runner = broken
    st, s = get(env, "/state")
    assert s["jobs"]["state"] == "UNAVAILABLE" and "CRONTAB_UNREADABLE" in s["jobs"]["reason"]
    assert s["n8n"]["state"] == "UNAVAILABLE"


def test_redaction_of_secretish_assignments():
    assert C.redact("0 * * * * API_TOKEN=abc123 run") == "0 * * * * API_TOKEN=*** run"


def test_phrase_match_is_exact_after_whitespace_collapse():
    assert C.phrase_matches("  ADD LIVE  x 2026-10-23 ", "ADD LIVE x 2026-10-23")
    assert not C.phrase_matches("add live x 2026-10-23", "ADD LIVE x 2026-10-23")
    assert not C.phrase_matches("", None)


def test_migration_is_additive_and_least_privilege():
    from scripts.ops import ops_controls_migration_plan as MP

    up = (ROOT / "migrations" / "2026_10_22_ops_controls.sql").read_text()
    p = MP.plan(up)
    assert p["additive"] and set(p["creates_tables"]) == set(S.TABLES)
    code = MP._code(up)
    assert not re.search(r"\bDELETE\b(?!\s+(ON|OR))", code.replace("BEFORE DELETE", "").replace("UPDATE OR DELETE", ""))
    down = MP._code((ROOT / "migrations" / "2026_10_22_ops_controls.down.sql").read_text())
    assert "DROP" not in down.upper() and down.count("RENAME TO") == 7


# ── 2026-10-22: multi-word pause notes (operator "approve all": fix the Resume parse) ──────────────────────────────

@pytest.mark.parametrize("line,note,cron", [
    ("# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 31 9 * * 1-5 cd $PROJ && run",
     "schwab-app-deactivated (incident SPCX)", "31 9 * * 1-5 cd $PROJ && run"),
    ("# PAUSED 2026-10-15 schwab-app-deactivated (incident SPCX, grant 0f9de907) 7,22,37,52 9-16 * * 1-5 run",
     "schwab-app-deactivated (incident SPCX, grant 0f9de907)", "7,22,37,52 9-16 * * 1-5 run"),
    ("# PAUSED 2026-10-14 WS7-02 coder-agent autolaunch (grant a67b8f21) 0 9-18/3 * * 1-5 run",
     "WS7-02 coder-agent autolaunch (grant a67b8f21)", "0 9-18/3 * * 1-5 run"),
    ("# PAUSED 2026-10-22 ops-controls:opsreq_abc */5 * * * * cmd  a", "ops-controls:opsreq_abc", "*/5 * * * * cmd  a"),
    ("# PAUSED 2026-10-14 note @reboot sleep 60", "note", "@reboot sleep 60"),
])
def test_paused_parse_keeps_multi_word_notes_out_of_the_cron_line(line, note, cron):
    m = C.PAUSED_RE.match(line)
    assert m is not None and m.group(1)[:4] == "2026" and m.group(2) == note and m.group(3) == cron
    assert C.CRON_LINE_RE.match(m.group(3))


def test_paused_parse_refuses_a_note_with_no_cron_line():
    assert C.PAUSED_RE.match("# PAUSED 2026-10-14 just a note") is None
    assert C.PAUSED_RE.match("# PAUSED 2026-10-14 31 9 * * 1-5 run") is None  # a note is required
