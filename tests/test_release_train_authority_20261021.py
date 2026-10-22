"""Release Train v2, Phase 2: standing delegation, capability issuer, STOP/pause/resume/revoke (libraries only).

scripts/lib/release_delegation.py, scripts/lib/release_capability.py, scripts/lib/release_control.py and the host
CLI scripts/release_control_cli.py. Operator decisions 2026-10-21: D1 standing revocable authorization; D3 resume
and scope changes only via the host CLI or a Telegram confirmation (the hook is a stub that refuses).

Adversarial cases from the enhanced design §10: replay, forged token, wrong SHA, wrong environment, revoked epoch
(STOP, resume, delegation epoch, delegation edit, revoke), exhausted budget, phase confusion, concurrent
reservation, a crash between reserve and effect, and corrupt lock / ledger / control / latch / key (fail closed).

Hermetic: tmp_path state dir, temp HMAC key, temp delegation, fixed clock. No git, gh, network, DB or systemd.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import threading
import time
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: these tests never touch a database")

    _pg.connect = _no_connect
    sys.modules.setdefault("psycopg2", _pg)

from scripts import release_control_cli as CLI  # noqa: E402
from scripts.lib import release_capability as CAP  # noqa: E402
from scripts.lib import release_control as RC  # noqa: E402
from scripts.lib import release_delegation as RD  # noqa: E402

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 21, 18, 10, tzinfo=ET).timestamp()
TRAIN = "train-20261021-1800"
BASE = "a" * 40
CAND = "c" * 40
HEADS = [{"pr": 1901, "head_sha": "1" * 40}, {"pr": 1902, "head_sha": "2" * 40}]
ARTIFACT = "sha256:" + "d" * 64
ROLLBACK_MAIN = {"kind": "main_ref", "sha": BASE}
ROLLBACK_REL = {"kind": "release", "sha": BASE, "release": "/releases/aaaaaaaaa-prev"}
CHECKS = ("cio-hardening", "agent-governance", "release-readiness", "ci-gate")


class Clock:
    def __init__(self, t: float = NOW) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def evidence(sha=CAND, conclusion="success", names=CHECKS, extra=()):
    checks = [{"name": n, "head_sha": sha, "status": "completed", "conclusion": conclusion} for n in names]
    return {"sha": sha, "checks": checks + list(extra)}


def delegation_body(**over):
    d = json.loads(RD.EXAMPLE_PATH.read_text(encoding="utf-8"))
    d["status"] = "ACTIVE"
    d["delegation_id"] = "rtd-test-0001"
    d["operator"]["approved_at"] = "2026-10-21T17:00:00-04:00"
    for s in d["windows"]["slots"]:
        s["enabled"] = s["window_id"] == "1800"
    d["limits"]["max_attempts_per_capability"] = 2
    d.update(over)
    return d


def write_json(path: Path, body) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def proof(ctl: RC.ReleaseControl, command: str) -> RC.HostCliProof:
    return RC.HostCliProof(tty="/dev/pts/9", uid=os.getuid(), confirmation=ctl.expected_phrase(command))


HOST = RC.Actor("host_cli", "uid:test")
CC = RC.Actor("cc", "operator@tailnet")
CTRL = RC.Actor("controller", "tradeai-release-train.service")


class World:
    def __init__(self, tmp: Path, *, attempts_limit: int = 2) -> None:
        self.tmp = tmp
        self.state = tmp / "state"
        self.state.mkdir()
        self.key = tmp / "host" / "capability.key"
        self.key.parent.mkdir()
        self.key.write_bytes(os.urandom(48).hex().encode())
        os.chmod(self.key, 0o600)
        self.deleg = tmp / "host" / "delegation.json"
        body = delegation_body()
        body["limits"]["max_attempts_per_capability"] = attempts_limit
        write_json(self.deleg, body)
        self.clock = Clock()
        self.ctl = RC.ReleaseControl(self.state, clock=self.clock)
        self.ctl.arm(HOST, proof(self.ctl, "arm"), policy_digest=RD.load(self.deleg).digest, reason="arm for test")
        self.ctl.claim_train(CTRL, TRAIN)
        self.auth = self.authority()

    def authority(self, **kw) -> CAP.CapabilityAuthority:
        kw.setdefault("lock_timeout_s", 0.0)
        return CAP.CapabilityAuthority(self.state, key_path=self.key, delegation_path=self.deleg, clock=self.clock,
                                       **kw)

    def build(self, actions=("integrate", "push_train_ref"), **kw) -> str:
        return self.auth.issue_build(TRAIN, base_sha=BASE, pr_heads=HEADS, actions=list(actions), **kw)

    def merge(self, actions=("merge_batch_pr",), ev=None, **kw) -> str:
        return self.auth.issue_merge(TRAIN, expected_base_sha=BASE, pr_heads=HEADS, candidate_sha=CAND,
                                     artifact_digest=ARTIFACT, evidence=ev or evidence(),
                                     rollback_target=ROLLBACK_MAIN, actions=list(actions), **kw)

    def promote(self, actions=("promote_release", "restart_service"), services=("portfolio-server.service",), **kw):
        return self.auth.issue_promote(TRAIN, expected_base_sha=BASE, pr_heads=HEADS, candidate_sha=CAND,
                                       artifact_digest=ARTIFACT, evidence=evidence(), rollback_target=ROLLBACK_REL,
                                       services=list(services), actions=list(actions), **kw)

    def ledger(self) -> dict:
        return json.loads((self.state / CAP.LEDGER_NAME).read_text(encoding="utf-8"))

    def used(self) -> list[int]:
        return [c["attempts_used"] for c in self.ledger()["caps"].values()]


def obs_build(**over):
    o = {"repository": "PatsKiller/tardeai", "environment": "production", "train_id": TRAIN, "main_sha": BASE}
    o.update(over)
    return o


def obs_merge(**over):
    o = {"repository": "PatsKiller/tardeai", "environment": "production", "train_id": TRAIN, "main_sha": BASE,
         "candidate_sha": CAND, "artifact_digest": ARTIFACT, "pr_heads": HEADS}
    o.update(over)
    return o


def obs_promote(**over):
    return obs_merge(main_sha=CAND, **over)


@pytest.fixture
def w(tmp_path) -> World:
    return World(tmp_path)


def refused(code: str):
    return pytest.raises(RC.ControlRefused, match=rf"^{re.escape(code)}\b")


# ═════════════════════════════════════════════════════════════════════════════ delegation (fail closed)


def test_example_is_valid_but_not_armed():
    v = RD.load(RD.EXAMPLE_PATH, allow_repo_path=True)
    assert v.code == "PAUSED" and not v.authorized and v.errors == []
    d = json.loads(RD.EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert all(s["enabled"] is False for s in d["windows"]["slots"]), "nothing gets armed"
    assert sorted(s["window_id"] for s in d["windows"]["slots"]) == ["0000", "0600", "0800", "1800"]
    assert d["schema"] == RD.SCHEMA == "ReleaseDelegation@v1"


def test_schema_file_matches_the_loader():
    schema = json.loads(RD.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["title"] == RD.SCHEMA
    assert schema["additionalProperties"] is False
    required = set(schema["required"])
    assert required == {"schema", "delegation_id", "status", "repository", "environment", "revocation_epoch",
                        "operator", "permitted_classes", "windows", "merge_freeze", "limits", "verification_policy"}
    assert set(schema["properties"]["status"]["enum"]) == RD.STATUSES
    example = json.loads(RD.EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert required <= set(example) and set(example) <= set(schema["properties"])
    for missing in sorted(required):
        body = delegation_body()
        body.pop(missing)
        assert RD.validate(body), f"loader accepted a record without {missing}"


def test_real_record_is_never_inside_the_repo(tmp_path):
    assert not str(RD.DEFAULT_PATH).startswith(str(ROOT))
    inside = ROOT / "config" / "release_train_delegation.json"
    assert RD.load(inside).code == "IN_REPO"
    assert RD.load(RD.EXAMPLE_PATH).code == "IN_REPO"


@pytest.mark.parametrize("content,code", [
    (None, "MISSING"), ("{not json", "UNREADABLE"), ("[]", "INVALID"), ("null", "INVALID"),
])
def test_missing_or_corrupt_is_not_authorized(tmp_path, content, code):
    p = tmp_path / "d.json"
    if content is not None:
        p.write_text(content, encoding="utf-8")
    v = RD.load(p)
    assert v.code == code and v.authorized is False


@pytest.mark.parametrize("status,code", [("ACTIVE", "AUTHORIZED"), ("PAUSED", "PAUSED"), ("REVOKED", "REVOKED"),
                                         ("ARMED", "INVALID"), ("active", "INVALID"), ("", "INVALID")])
def test_status(tmp_path, status, code):
    p = tmp_path / "d.json"
    write_json(p, delegation_body(status=status))
    v = RD.load(p)
    assert v.code == code
    assert v.authorized is (code == "AUTHORIZED")


@pytest.mark.parametrize("mutate", [
    lambda d: d["permitted_classes"].append("broker_execution"),
    lambda d: d["permitted_classes"].append("active_trader"),
    lambda d: d["permitted_classes"].append("secrets"),
    lambda d: d.__setitem__("repository", "someone/else"),
    lambda d: d.__setitem__("environment", "staging"),
    lambda d: d.__setitem__("revocation_epoch", 0),
    lambda d: d.__setitem__("revocation_epoch", True),
    lambda d: d["verification_policy"]["required_checks"].remove("release-readiness"),
    lambda d: d["verification_policy"].__setitem__("conclusion_required", "neutral"),
    lambda d: d["verification_policy"].__setitem__("tree_equivalence_fallback", True),
    lambda d: d["windows"].__setitem__("catch_up", True),
    lambda d: d["windows"]["slots"][0].__setitem__("start_et", "18:30"),
    lambda d: d["windows"]["slots"][3].__setitem__("skip_on_macro_days", False),
    lambda d: d["limits"].__setitem__("capability_ttl_s", 7200),
    lambda d: d["limits"].__setitem__("max_trains_per_window", 2),
    lambda d: d.__setitem__("grant_everything", True),
    lambda d: d["operator"].__setitem__("approved_via", "cc"),
])
def test_invalid_records_fail_closed(tmp_path, mutate):
    d = delegation_body()
    mutate(d)
    p = tmp_path / "d.json"
    write_json(p, d)
    v = RD.load(p)
    assert v.code == "INVALID" and not v.authorized


def test_digest_changes_with_any_edit():
    a = delegation_body()
    b = delegation_body()
    b["limits"]["max_prs_per_train"] = 13
    assert RD.policy_digest(a) == RD.policy_digest(delegation_body()) != RD.policy_digest(b)


# ═════════════════════════════════════════════════════════════════════════════ control state machine


def test_unarmed_and_corrupt_control_fail_closed(tmp_path):
    ctl = RC.ReleaseControl(tmp_path)
    assert ctl.view().mode == RC.UNARMED and ctl.view().mutation_refusal("x") == "CONTROL_UNARMED"
    (tmp_path / RC.CONTROL_NAME).write_text("{oops", encoding="utf-8")
    assert ctl.view().mode == RC.CORRUPT and ctl.view().mutation_refusal("x") == "CONTROL_CORRUPT"
    write_json(tmp_path / RC.CONTROL_NAME, {"schema": RC.SCHEMA, "mode": "PARTY", "epoch": 1, "version": 1})
    assert ctl.view().mode == RC.CORRUPT
    write_json(tmp_path / RC.CONTROL_NAME, {"schema": RC.SCHEMA, "mode": "RUNNING", "epoch": "1", "version": 1,
                                            "accepted_policy_digest": "f" * 64})
    assert ctl.view().mode == RC.CORRUPT


@pytest.mark.parametrize("content", ["{corrupt", "[1,2]", "dir"])
def test_unreadable_latch_is_a_stop(w, content):
    latch = w.state / RC.LATCH_NAME
    if content == "dir":
        latch.mkdir()
    else:
        latch.write_text(content, encoding="utf-8")
    state, _ = RC.read_latch(latch)
    assert state == RC.LATCH_UNREADABLE
    assert w.ctl.view().mutation_refusal(TRAIN) == "STOP_LATCH_UNREADABLE"
    assert w.ctl.view().stop_phase == "stopped"


def test_dangling_symlink_latch_is_not_absent(tmp_path):
    (tmp_path / RC.LATCH_NAME).symlink_to(tmp_path / "nowhere")
    assert RC.read_latch(tmp_path / RC.LATCH_NAME)[0] == RC.LATCH_UNREADABLE


def test_release_window_latch_is_honoured(w):
    """A STOP latched by release_window.py itself (verify failed / rolled back) stops the train too."""
    write_json(w.state / RC.LATCH_NAME, {"latched_at": "2026-10-21T22:00:00Z", "window_id": "release-window-x",
                                         "outcome": "ROLLED_BACK"})
    assert w.ctl.view().mutation_refusal(TRAIN) == "STOP_LATCHED"


def test_cc_stop_latches_a_release_window_compatible_stop(w):
    from scripts import release_window as RW

    e0 = w.ctl.view().epoch
    out = w.ctl.request_stop(CC, "operator pressed STOP RELEASES")
    assert out["outcome"] == "STOP_REQUESTED" and out["epoch"] == e0 + 1
    body = RW.State(w.state).read(w.state / "STOP.json")
    assert isinstance(body, dict) and body["source"] == "release_control"   # release_window refuses: latched
    assert w.ctl.view().stop_phase == "requested"


def test_stop_lifecycle_requested_acknowledged_settling_stopped(w):
    w.ctl.request_stop(CC, "stop please")
    w.clock.t += 5
    a = w.ctl.acknowledge_stop(CTRL)
    assert a["outcome"] == RC.STOP_ACKNOWLEDGED and a["stop"]["acknowledged_at"]
    assert w.ctl.view().stop_phase == "acknowledged"
    w.clock.t += 5
    assert w.ctl.settle(CTRL, in_flight=True)["outcome"] == RC.SETTLING
    assert w.ctl.view().stop_phase == "settling"
    w.clock.t += 5
    s = w.ctl.settle(CTRL, in_flight=False)
    assert s["outcome"] == RC.STOPPED
    stop = w.ctl.view().stop
    assert stop["requested_at"] <= stop["acknowledged_at"] <= stop["settling_at"] <= stop["stopped_at"]


def test_cc_may_only_request_stop_or_pause(w):
    for fn, kw in ((w.ctl.resume, {"reason": "x" * 5, "readiness": {"checked_at": "now"}}),
                   (w.ctl.revoke, {"reason": "x" * 5}),
                   (w.ctl.arm, {"policy_digest": "f" * 64, "reason": "x" * 5}),
                   (w.ctl.change_scope, {"policy_digest": "f" * 64, "reason": "x" * 5})):
        with refused("ACTOR_NOT_PERMITTED"):
            fn(CC, proof(w.ctl, "resume"), **kw)
    with refused("ACTOR_NOT_PERMITTED"):
        w.ctl.acknowledge_stop(CC)
    assert w.ctl.request_pause(CC, "pause please")["outcome"] in (RC.PAUSE_REQUESTED, RC.PAUSED)


def test_operator_proofs(w):
    w.ctl.request_stop(CC, "stop")
    w.ctl.acknowledge_stop(CTRL)
    w.ctl.settle(CTRL, in_flight=False)
    ready = {"checked_at": "2026-10-21T22:20:00Z"}
    with refused("OPERATOR_PROOF_REFUSED"):     # wrong phrase
        w.ctl.resume(HOST, RC.HostCliProof("/dev/pts/9", os.getuid(), "RESUME"), reason="ok now", readiness=ready)
    with refused("OPERATOR_PROOF_REFUSED"):     # no tty
        w.ctl.resume(HOST, RC.HostCliProof("", os.getuid(), w.ctl.expected_phrase("resume")), reason="ok now",
                     readiness=ready)
    tg = RC.Actor("telegram", "operator-chat")
    conf = RC.TelegramConfirmation("req-1", "operator", "2026-10-21T22:20:00Z", w.ctl.expected_phrase("resume"))
    with refused("OPERATOR_PROOF_REFUSED"):     # D3 hook is a stub: Telegram stays closed
        w.ctl.resume(tg, conf, reason="ok now", readiness=ready)

    class Hook:
        def verify(self, confirmation, *, expected_phrase):
            return confirmation.confirmation == expected_phrase

    ok = RC.ReleaseControl(w.state, clock=w.clock, telegram_hook=Hook())
    out = ok.resume(tg, conf, reason="ok now", readiness=ready)
    assert out["outcome"] == "RESUMED"


def test_resume_needs_settled_stop_archives_latch_and_issues_new_epoch(w):
    w.ctl.request_stop(CC, "stop")
    e_stop = w.ctl.view().epoch
    ready = {"checked_at": "2026-10-21T22:20:00Z"}
    with refused("STOP_NOT_SETTLED"):
        w.ctl.resume(HOST, proof(w.ctl, "resume"), reason="too early", readiness=ready)
    w.ctl.acknowledge_stop(CTRL)
    w.ctl.settle(CTRL, in_flight=False)
    with refused("READINESS_MISSING"):
        w.ctl.resume(HOST, proof(w.ctl, "resume"), reason="no readiness", readiness={})
    out = w.ctl.resume(HOST, proof(w.ctl, "resume"), reason="incident reviewed", readiness=ready)
    assert out["epoch"] == e_stop + 1
    assert not os.path.lexists(w.state / RC.LATCH_NAME)
    assert Path(out["latch_archived"]).exists(), "archived by rename, never deleted"
    assert list((w.state / "windows").glob("STOP-cleared-*.json"))
    assert w.ctl.view().mode == RC.RUNNING


def test_resume_clears_an_unreadable_latch_by_archiving_it(w):
    (w.state / RC.LATCH_NAME).write_text("{broken", encoding="utf-8")
    out = w.ctl.resume(HOST, proof(w.ctl, "resume"), reason="inspected",
                       readiness={"checked_at": "2026-10-21T22:20:00Z"})
    assert Path(out["latch_archived"]).read_text(encoding="utf-8") == "{broken"


def test_pause_after_current_lets_only_the_current_train_finish(w):
    e = w.ctl.view().epoch
    assert w.ctl.request_pause(CC, "pause after this one")["outcome"] == RC.PAUSE_REQUESTED
    v = w.ctl.view()
    assert v.epoch == e, "pause does not revoke the current train"
    assert v.mutation_refusal(TRAIN) is None
    assert v.mutation_refusal("train-20261022-0000") == "PAUSED_AFTER_CURRENT"
    with refused("PAUSED_AFTER_CURRENT"):
        w.ctl.claim_train(CTRL, "train-20261022-0000")
    assert w.ctl.train_terminal(CTRL, TRAIN, "VERIFIED")["outcome"] == RC.PAUSED
    assert w.ctl.view().mutation_refusal(TRAIN) == "PAUSED"


def test_stop_overdue_escalation(w):
    w.ctl.request_stop(CC, "stop")
    assert not w.ctl.stop_overdue(60)
    w.clock.t += 61
    assert w.ctl.stop_overdue(60)
    w.ctl.acknowledge_stop(CTRL)
    assert not w.ctl.stop_overdue(60)


def test_idempotency_key_and_expected_version(w):
    v = w.ctl.view().version
    with refused("VERSION_CONFLICT"):
        w.ctl.request_stop(CC, "stop", expected_version=v - 1)
    a = w.ctl.request_stop(CC, "stop", idempotency_key="k-1", expected_version=v)
    b = w.ctl.request_stop(CC, "stop", idempotency_key="k-1")
    assert b.get("idempotent_replay") and b["epoch"] == a["epoch"] == w.ctl.view().epoch


def test_stop_works_when_control_state_is_corrupt(w):
    (w.state / RC.CONTROL_NAME).write_text("garbage", encoding="utf-8")
    out = w.ctl.request_stop(CC, "stop anyway")
    assert out["outcome"] == "STOP_LATCHED" and RC.read_latch(w.state / RC.LATCH_NAME)[0] == RC.LATCH_SET


def test_stop_does_not_wait_for_the_global_mutation_lock(w):
    with RC.GlobalReleaseLock(w.state):
        t0 = time.monotonic()
        w.ctl.request_stop(CC, "stop during a mutation")
        assert time.monotonic() - t0 < 2


def test_revoke_and_rearm_keep_the_epoch_monotonic(w):
    e = w.ctl.view().epoch
    assert w.ctl.revoke(HOST, proof(w.ctl, "revoke"), reason="revoke automation")["epoch"] == e + 1
    assert w.ctl.view().mutation_refusal(TRAIN) == "REVOKED"
    with refused("ACTOR_NOT_PERMITTED"):
        w.ctl.arm(CC, None, policy_digest=RD.load(w.deleg).digest, reason="cc re-arm")
    out = w.ctl.arm(HOST, proof(w.ctl, "arm"), policy_digest=RD.load(w.deleg).digest, reason="re-arm")
    assert out["epoch"] == e + 2


def test_journal_records_refusals(w):
    with pytest.raises(RC.ControlRefused):
        w.ctl.revoke(CC, None, reason="nope nope")
    rows = [json.loads(x) for x in (w.state / RC.JOURNAL_NAME).read_text(encoding="utf-8").splitlines()]
    assert any(r["command"] == "revoke" and r["result"]["code"] == "ACTOR_NOT_PERMITTED" for r in rows)


# ═════════════════════════════════════════════════════════════════════════════ capability issuer


def test_happy_path_build_reserve_succeed(w):
    tok = w.build()
    assert w.used() == [0]
    with w.auth.reserve(tok, "integrate", observed=obs_build()) as r:
        r.recheck(obs_build())
        intent = r.succeeded({"ref": f"refs/heads/train/{TRAIN}"})
    assert intent["status"] == CAP.SUCCEEDED and w.used() == [1]
    cap = CAP.decode(tok, CAP.load_key(w.key))
    for k in ("delegation_id", "policy_digest", "delegation_epoch", "control_epoch", "repository", "environment",
              "train_id", "base_sha", "pr_heads", "permitted_actions", "expires_at", "attempt_budget", "output_ref"):
        assert k in cap, k
    assert cap["output_ref"] == f"refs/heads/train/{TRAIN}"
    assert cap["expires_at"] - cap["issued_at"] <= 900


def test_merge_and_promote_bind_the_full_evidence(w):
    m = CAP.decode(w.merge(), CAP.load_key(w.key))
    p = CAP.decode(w.promote(), CAP.load_key(w.key))
    for cap in (m, p):
        for k in ("expected_base_sha", "candidate_sha", "artifact_digest", "evidence_digest", "rollback_target",
                  "pr_heads", "services", "policy_digest", "control_epoch", "delegation_epoch"):
            assert k in cap, k
    assert m["pr_heads"] == HEADS and m["services"] == [] and p["services"] == ["portfolio-server.service"]
    assert m["rollback_target"]["sha"] == BASE


def test_replay_and_budget(w):
    tok = w.build(attempts=2)
    with w.auth.reserve(tok, "integrate", observed=obs_build()) as r:
        r.succeeded({})
    with refused("REPLAY"):
        w.auth.reserve(tok, "integrate", observed=obs_build())
    with w.auth.reserve(tok, "push_train_ref", observed=obs_build()) as r:
        r.failed_no_effect({"why": "remote refused"})
    with refused("BUDGET_EXHAUSTED"):
        w.auth.reserve(tok, "push_train_ref", observed=obs_build())
    assert w.used() == [2]


def test_forged_and_foreign_tokens(w, tmp_path):
    tok = w.build()
    prefix, body, sig = tok.split(".")
    cap = json.loads(CAP._b64d(body))
    cap["attempt_budget"] = 99
    forged = f"{prefix}.{CAP._b64e(json.dumps(cap).encode())}.{sig}"
    with refused("SIGNATURE_INVALID"):
        w.auth.reserve(forged, "integrate", observed=obs_build())
    other = tmp_path / "other.key"
    other.write_bytes(b"z" * 64)
    os.chmod(other, 0o600)
    with refused("SIGNATURE_INVALID"):
        CAP.CapabilityAuthority(w.state, key_path=other, delegation_path=w.deleg, clock=w.clock).reserve(
            tok, "integrate", observed=obs_build())
    with refused("TOKEN_MALFORMED"):
        w.auth.reserve("not-a-token", "integrate", observed=obs_build())
    # a validly signed token the ledger never recorded (e.g. minted from a copied key on another box)
    raw = json.dumps({**cap, "attempt_budget": 1, "capability_id": "f" * 32}, sort_keys=True,
                     separators=(",", ":")).encode()
    unknown = f"rcap1.{CAP._b64e(raw)}.{CAP._sign(CAP.load_key(w.key), raw)}"
    with refused("CAPABILITY_UNKNOWN"):
        w.auth.reserve(unknown, "integrate", observed=obs_build())
    assert w.used() == [0]


def test_wrong_sha_env_repo_train_consume_nothing(w):
    tok = w.build()
    for obs, code in ((obs_build(main_sha="b" * 40), "WRONG_SHA"),
                      (obs_build(environment="staging"), "WRONG_ENVIRONMENT"),
                      (obs_build(repository="PatsKiller/other"), "WRONG_REPOSITORY"),
                      (obs_build(train_id="train-20261021-0000"), "WRONG_TRAIN"),
                      ("not a dict", "OBSERVED_MISSING")):
        with refused(code):
            w.auth.reserve(tok, "integrate", observed=obs)
    assert w.used() == [0], "a gate refusal consumes nothing"
    mtok = w.merge()
    for obs, code in ((obs_merge(candidate_sha="e" * 40), "WRONG_SHA"),
                      (obs_merge(main_sha=CAND), "WRONG_SHA"),
                      (obs_merge(artifact_digest="sha256:" + "0" * 64), "WRONG_ARTIFACT"),
                      (obs_merge(pr_heads=list(reversed(HEADS))), "PR_HEADS_CHANGED")):
        with refused(code):
            w.auth.reserve(mtok, "merge_batch_pr", observed=obs)
    assert w.used() == [0, 0]


def test_env_vars_never_grant_authority(w, monkeypatch):
    for mod in (CAP, RD, RC):
        assert "os.environ" not in Path(mod.__file__).read_text(encoding="utf-8"), mod.__name__
    tok = w.build()
    monkeypatch.setenv("TRADEAI_RELEASE_TRAIN_SHA", "b" * 40)
    with refused("WRONG_SHA"):
        w.auth.reserve(tok, "integrate", observed=obs_build(main_sha="b" * 40))


def test_stop_revokes_and_resume_never_revives(w):
    tok = w.build()
    w.ctl.request_stop(CC, "stop")
    with refused("STOP_LATCHED"):
        w.auth.reserve(tok, "integrate", observed=obs_build())
    w.ctl.acknowledge_stop(CTRL)
    w.ctl.settle(CTRL, in_flight=False)
    w.ctl.resume(HOST, proof(w.ctl, "resume"), reason="reviewed", readiness={"checked_at": "x"})
    w.ctl.claim_train(CTRL, TRAIN)
    with refused("EPOCH_STALE"):
        w.auth.reserve(tok, "integrate", observed=obs_build())
    fresh = w.build()
    with w.auth.reserve(fresh, "integrate", observed=obs_build()) as r:
        r.succeeded({})


def test_delegation_epoch_edit_and_status_revoke(w):
    tok = w.build()
    d = json.loads(w.deleg.read_text(encoding="utf-8"))
    d["revocation_epoch"] = 2
    write_json(w.deleg, d)
    with refused("DELEGATION_EPOCH_STALE"):
        w.auth.reserve(tok, "integrate", observed=obs_build())
    d["revocation_epoch"] = 1
    d["permitted_classes"].append("more_scope")
    write_json(w.deleg, d)
    with refused("POLICY_DIGEST_CHANGED"):
        w.auth.reserve(tok, "integrate", observed=obs_build())
    with refused("POLICY_NOT_ACCEPTED"):        # an edited file is not accepted until change_scope (host CLI)
        w.build()
    d["status"] = "REVOKED"
    write_json(w.deleg, d)
    with refused("DELEGATION_REVOKED"):
        w.auth.reserve(tok, "integrate", observed=obs_build())
    w.deleg.unlink()
    with refused("DELEGATION_MISSING"):
        w.build()
    assert w.used() == [0]


def test_scope_change_issues_new_epoch(w):
    tok = w.build()
    d = json.loads(w.deleg.read_text(encoding="utf-8"))
    d["permitted_classes"].append("more_scope")
    write_json(w.deleg, d)
    w.ctl.change_scope(HOST, proof(w.ctl, "change_scope"), policy_digest=RD.load(w.deleg).digest, reason="scope")
    with refused("EPOCH_STALE"):
        w.auth.reserve(tok, "integrate", observed=obs_build())
    with w.auth.reserve(w.build(), "integrate", observed=obs_build()) as r:
        r.succeeded({})


def test_control_revoke_blocks_issuance_and_use(w):
    tok = w.build()
    w.ctl.revoke(HOST, proof(w.ctl, "revoke"), reason="revoke automation")
    with refused("REVOKED"):
        w.auth.reserve(tok, "integrate", observed=obs_build())
    with refused("REVOKED"):
        w.build()


def test_phase_confusion(w):
    with refused("ACTIONS_OUTSIDE_PHASE"):
        w.build(actions=("integrate", "merge_batch_pr"))
    with refused("ACTIONS_OUTSIDE_PHASE"):
        w.merge(actions=("promote_release",))
    btok = w.build()
    for action in ("merge_batch_pr", "update_main_ref", "promote_release", "restart_service"):
        with refused("PHASE_CONFUSION"):
            w.auth.reserve(btok, action, observed=obs_build())
    mtok = w.merge()
    with refused("PHASE_CONFUSION"):
        w.auth.reserve(mtok, "promote_release", observed=obs_merge())
    with refused("ACTION_NOT_PERMITTED"):
        w.auth.reserve(btok, "build_artifact", observed=obs_build())
    assert w.used() == [0, 0]


@pytest.mark.parametrize("ev,code", [
    (evidence(conclusion="neutral"), "EVIDENCE_NOT_QUALIFYING"),
    (evidence(conclusion="skipped"), "EVIDENCE_NOT_QUALIFYING"),
    (evidence(names=CHECKS[:3]), "EVIDENCE_NOT_QUALIFYING"),               # ci-gate missing
    (evidence(sha=BASE), "EVIDENCE_NOT_QUALIFYING"),                       # stale: another SHA
    (evidence(extra=[{"name": "ci-gate", "head_sha": CAND, "status": "completed", "conclusion": "failure"}]),
     "EVIDENCE_NOT_QUALIFYING"),                                           # a red rerun on the same SHA
    (evidence(extra=[{"name": "cio-hardening", "head_sha": CAND, "status": "in_progress", "conclusion": None}]),
     "EVIDENCE_NOT_QUALIFYING"),
])
def test_merge_requires_exact_success_evidence(w, ev, code):
    with refused(code):
        w.merge(ev=ev)


def test_promote_services_and_rollback_target(w):
    with refused("SERVICE_NOT_NAMED"):
        w.promote(services=("evil.service",))
    with refused("SERVICES_REQUIRED"):
        w.promote(services=())
    with refused("ROLLBACK_TARGET_INVALID"):
        w.auth.issue_promote(TRAIN, expected_base_sha=BASE, pr_heads=HEADS, candidate_sha=CAND,
                             artifact_digest=ARTIFACT, evidence=evidence(), rollback_target={"kind": "release"},
                             services=["portfolio-server.service"], actions=["promote_release"])
    tok = w.promote(attempts=2)
    with refused("SERVICE_NOT_NAMED"):
        w.auth.reserve(tok, "restart_service", observed=obs_promote(service="tradeai-other.service"))
    with refused("WRONG_SHA"):        # promote is of exact main: main must already be the candidate
        w.auth.reserve(tok, "promote_release", observed=obs_merge())
    with w.auth.reserve(tok, "restart_service", observed=obs_promote(service="portfolio-server.service")) as r:
        r.succeeded({})


def test_issuance_limits_window_and_train_claim(w):
    with refused("TTL_OUT_OF_POLICY"):
        w.build(ttl_s=3600)
    with refused("ATTEMPTS_OUT_OF_POLICY"):
        w.build(attempts=3)
    with refused("TRAIN_ID_INVALID"):
        w.auth.issue_build("main", base_sha=BASE, pr_heads=HEADS, actions=["integrate"])
    with refused("SHA_INVALID"):
        w.auth.issue_build(TRAIN, base_sha="abc1234", pr_heads=HEADS, actions=["integrate"])
    with refused("PR_HEADS_INVALID"):
        w.auth.issue_build(TRAIN, base_sha=BASE, pr_heads=HEADS + HEADS[:1], actions=["integrate"])
    with refused("TRAIN_NOT_CLAIMED"):         # a competing train id
        w.auth.issue_build("train-20261021-1800-b", base_sha=BASE, pr_heads=HEADS, actions=["integrate"])
    with refused("TRAIN_ALREADY_CLAIMED"):
        w.ctl.claim_train(CTRL, "train-20261021-1800-b")
    w.clock.t = datetime(2026, 10, 21, 12, 0, tzinfo=ET).timestamp()
    with refused("OUTSIDE_WINDOW"):
        w.build()


def test_capability_expires(w):
    tok = w.build(ttl_s=60)
    w.clock.t += 61
    with refused("CAPABILITY_EXPIRED"):
        w.auth.reserve(tok, "integrate", observed=obs_build())


def test_windows_are_dst_aware():
    d = delegation_body()
    edt = datetime(2026, 10, 21, 18, 5, tzinfo=ET).timestamp()     # UTC-4
    est = datetime(2026, 11, 10, 18, 5, tzinfo=ET).timestamp()     # UTC-5
    assert CAP.open_window(d, edt)["window_id"] == "1800"
    assert CAP.open_window(d, est)["window_id"] == "1800"
    assert CAP.open_window(d, est - 3600) is None, "17:05 EST is not in the 18:00 window"
    for s in d["windows"]["slots"]:
        s["enabled"] = s["window_id"] == "0000"
    assert CAP.open_window(d, datetime(2026, 11, 1, 1, 30, tzinfo=ET).timestamp())["window_id"] == "0000"


def test_concurrent_reservations_take_one_attempt(w):
    tok = w.build(attempts=1)
    results: list[str] = []
    barrier = threading.Barrier(6)

    def go():
        auth = w.authority(lock_timeout_s=3.0)
        barrier.wait()
        try:
            r = auth.reserve(tok, "integrate", observed=obs_build())
            time.sleep(0.2)
            r.succeeded({})
            results.append("OK")
        except RC.ControlRefused as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=go) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert results.count("OK") == 1, results
    assert set(results) <= {"OK", "REPLAY", "BUDGET_EXHAUSTED"}, results
    assert w.used() == [1]


def test_lock_held_by_release_window_refuses_without_consuming(w):
    tok = w.build()
    fh = open(w.state / RC.GLOBAL_LOCK_NAME, "a+")  # noqa: SIM115 - what release_window.py Runner.run holds
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with refused("LOCK_BUSY"):
            w.auth.reserve(tok, "integrate", observed=obs_build())
    finally:
        fh.close()
    assert w.used() == [0]
    lock = RC.GlobalReleaseLock(w.state).acquire()       # a caller that already holds it may pass it in
    try:
        r = w.auth.reserve(tok, "integrate", observed=obs_build(), held_lock=lock)
        r.succeeded({})
        assert lock.held, "a passed-in lock stays with its owner"
    finally:
        lock.release()


CRASH = r"""
import os, sys
sys.path[:0] = [{root!r}, {root!r} + "/scripts"]
from scripts.lib import release_capability as CAP
auth = CAP.CapabilityAuthority({state!r}, key_path={key!r}, delegation_path={deleg!r}, clock=lambda: {now!r})
r = auth.reserve({tok!r}, "integrate", observed={obs!r})
print("RESERVED", r.intent_id, flush=True)
os._exit(9)          # crash between reserve and effect: no outcome recorded, flock released by the kernel
"""


def test_crash_between_reserve_and_effect_requires_reconciliation(w):
    tok = w.build(attempts=2)
    code = CRASH.format(root=str(ROOT), state=str(w.state), key=str(w.key), deleg=str(w.deleg), now=w.clock.t,
                        tok=tok, obs=obs_build())
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert proc.returncode == 9, proc.stderr
    intent_id = proc.stdout.split()[1]
    assert w.ledger()["intents"][intent_id]["status"] == CAP.RESERVED
    with refused("RECONCILIATION_REQUIRED"):
        w.auth.reserve(tok, "push_train_ref", observed=obs_build())
    assert w.ledger()["intents"][intent_id]["status"] == CAP.UNCERTAIN
    other = w.build()
    with refused("RECONCILIATION_REQUIRED"):     # global: no other mutation either
        w.auth.reserve(other, "integrate", observed=obs_build())
    with refused("RECONCILE_EVIDENCE_REQUIRED"):
        w.auth.reconcile(intent_id, disposition="EFFECT_ABSENT", observed_evidence={}, reconciled_by="ctl")
    out = w.auth.reconcile(intent_id, disposition="EFFECT_ABSENT",
                           observed_evidence={"train_ref": None, "main": BASE}, reconciled_by="controller")
    assert out["status"] == CAP.RECONCILED_ABSENT and out["refunded"]
    with w.auth.reserve(tok, "integrate", observed=obs_build()) as r:
        r.succeeded({})


def test_reconciled_applied_counts_as_done(w):
    tok = w.build(attempts=2)
    r = w.auth.reserve(tok, "integrate", observed=obs_build())
    r.uncertain({"why": "push timed out"})
    with refused("RECONCILIATION_REQUIRED"):
        w.auth.reserve(tok, "integrate", observed=obs_build())
    w.auth.reconcile(r.intent_id, disposition="EFFECT_APPLIED", observed_evidence={"train_ref": CAND},
                     reconciled_by="controller")
    with refused("REPLAY"):
        w.auth.reserve(tok, "integrate", observed=obs_build())


def test_exit_without_outcome_is_uncertain(w):
    tok = w.build()
    with pytest.raises(RuntimeError):
        with w.auth.reserve(tok, "integrate", observed=obs_build()):
            raise RuntimeError("effect crashed mid-way")
    assert [i["status"] for i in w.ledger()["intents"].values()] == [CAP.UNCERTAIN]


def test_recheck_sees_a_stop_that_arrived_after_reservation_and_refunds(w):
    tok = w.build()
    r = w.auth.reserve(tok, "integrate", observed=obs_build())
    w.ctl.request_stop(CC, "stop mid-flight")          # takes only control.lock, never waits on .lock
    with refused("STOP_LATCHED"):
        r.recheck(obs_build())
    assert w.used() == [0], "no effect happened: the attempt is refunded"
    assert [i["status"] for i in w.ledger()["intents"].values()] == [CAP.ABORTED_NO_EFFECT]
    assert RC.GlobalReleaseLock(w.state).acquire().held   # and the lock was released


@pytest.mark.parametrize("what", ["ledger", "ledger_shape", "control", "latch", "lock_dir"])
def test_corrupt_state_fails_closed(w, what):
    tok = w.build()
    if what == "ledger":
        (w.state / CAP.LEDGER_NAME).write_text("{trunc", encoding="utf-8")
        code = "STATE_CORRUPT"
    elif what == "ledger_shape":
        write_json(w.state / CAP.LEDGER_NAME, {"schema": CAP.LEDGER_SCHEMA, "caps": []})
        code = "STATE_CORRUPT"
    elif what == "control":
        (w.state / RC.CONTROL_NAME).write_text("{trunc", encoding="utf-8")
        code = "CONTROL_CORRUPT"
    elif what == "latch":
        (w.state / RC.LATCH_NAME).write_text("{trunc", encoding="utf-8")
        code = "STOP_LATCH_UNREADABLE"
    else:
        lock = w.state / RC.GLOBAL_LOCK_NAME
        if lock.exists():
            lock.rename(w.state / "old.lock")
        lock.mkdir()
        code = "LOCK_ERROR"
    with refused(code):
        w.auth.reserve(tok, "integrate", observed=obs_build())


def test_missing_ledger_means_nothing_was_issued(w):
    tok = w.build()
    (w.state / CAP.LEDGER_NAME).rename(w.state / "moved.json")
    with refused("CAPABILITY_UNKNOWN"):
        w.auth.reserve(tok, "integrate", observed=obs_build())


@pytest.mark.parametrize("what,code", [("missing", "KEY_MISSING"), ("mode", "KEY_MODE_TOO_OPEN"),
                                       ("short", "KEY_TOO_SHORT"), ("symlink", "KEY_NOT_REGULAR_FILE")])
def test_key_fails_closed(w, what, code):
    if what == "missing":
        w.key.rename(w.key.with_name("gone"))
    elif what == "mode":
        os.chmod(w.key, 0o644)
    elif what == "short":
        w.key.write_bytes(b"short")
    else:
        real = w.key.with_name("real.key")
        w.key.rename(real)
        w.key.symlink_to(real)
    with refused(code):
        w.build()


def test_libraries_are_wired_into_nothing():
    names = ("release_capability", "release_control", "release_delegation", "release_control_cli")
    # Phase 3 (feat/release-train-controller-20261021): the train controller is the one intended consumer; it is
    # BUILD_ONLY (TRAIN_CONTROLLER_STATUS), refuses --live, and no timer/unit/n8n lane invokes it.
    allowed = {"scripts/lib/release_capability.py", "scripts/lib/release_control.py",
               "scripts/lib/release_delegation.py", "scripts/release_control_cli.py",
               "tests/test_release_train_authority_20261021.py", "config/release_train_delegation.example.json",
               "scripts/lib/release_train_controller.py",
               # Phase 1 contracts name the schema file release_control.v1.schema.json (a filename, not an import)
               "scripts/lib/release_train_contracts.py",
               # Phase 4 (feat/release-train-n8n-20261021; release-2 integration): release_train_window.py calls only
               # release_delegation.load() (read-only validation of the standing delegation, fail closed when absent);
               # the other three name the libraries in docstrings or in the workflow's forbidden-text denylist.
               "scripts/lib/release_train_window.py", "scripts/lib/release_train_window_view.py",
               "scripts/release_train_window_request.py", "scripts/n8n_workflow_templates.py",
               # Arming packet (ops/release-train-arming-20261021): the OPERATOR's one-time setup script. It verifies
               # the key with release_capability.load_key, validates the delegation with release_delegation, and
               # reads release_control_cli.py status; it never arms (arm is a TTY act) and no timer, unit or lane
               # runs it.
               "scripts/ops/release_train_arm.sh"}
    hits = []
    for base in ("scripts", "config", "deploy", "systemd", "n8n", "src", "bin"):
        root = ROOT / base
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix not in {".py", ".sh", ".json", ".yaml", ".yml", ".service", ".timer",
                                                   ".ts", ".tsx", ""}:
                continue
            rel = p.relative_to(ROOT).as_posix()
            if rel in allowed or rel.startswith("config/schemas/release_delegation"):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(n in text for n in names):
                hits.append(rel)
    assert hits == [], f"Phase 2 is library-only; found references in {hits}"


# ═════════════════════════════════════════════════════════════════════════════ host CLI


class FakeStdin:
    def __init__(self, text: str, tty: bool) -> None:
        self.text, self.tty = text, tty

    def isatty(self) -> bool:
        return self.tty

    def readline(self) -> str:
        return self.text

    def fileno(self) -> int:
        return 0


def test_cli_status_dry_run_and_tty_rule(tmp_path, capsys):
    state = tmp_path / "state"
    assert CLI.main(["--state-dir", str(state), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == RC.UNARMED
    assert CLI.main(["--state-dir", str(state), "stop", "--reason", "dry", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["writes"] == "nothing"
    assert not (state / RC.LATCH_NAME).exists()
    rc = CLI.main(["--state-dir", str(state), "resume", "--reason", "piped resume"],
                  stdin=FakeStdin("RESUME EPOCH 1\n", tty=False))
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["code"] == "NOT_A_TTY"
    assert CLI.main(["--state-dir", str(state), "stop", "--reason", "host stop"]) == 0
    assert RC.read_latch(state / RC.LATCH_NAME)[0] == RC.LATCH_SET


def test_cli_arm_refuses_an_unauthorized_delegation(tmp_path, capsys):
    p = tmp_path / "d.json"
    write_json(p, delegation_body(status="PAUSED"))
    rc = CLI.main(["--state-dir", str(tmp_path / "s"), "arm", "--delegation", str(p), "--reason", "arm it"])
    assert rc == 2 and json.loads(capsys.readouterr().out)["code"] == "DELEGATION_PAUSED"
