"""Arming packet §K: the standing-release binding (release_grant_preflight accepts a train's prepare/promote on a
RESERVED host capability). Built PROPOSED and inert: ``CAPABILITY_BINDING_STATUS`` stays "PROPOSED" until a reviewed
PR flips it and the operator says so (protected surface; manual release path L.1).

Adversarial list from the packet: forged, expired, wrong-SHA, wrong-phase and replayed reservations; STOP or an
epoch change between reserve and preflight; a reservation for another train. Plus: flag off is inert and leaves the
preflight output unchanged, the environment cannot grant, the guard ledger is not consumed, a dead holder's
reservation is refused.

Hermetic: tmp state dir, temp HMAC key (the real host key is never read), temp delegation, fixed clock.
"""

from __future__ import annotations

import json
import os
import sys
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
    _pg.connect = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no DB in these tests"))
    sys.modules.setdefault("psycopg2", _pg)

from scripts import release_grant_preflight as PF  # noqa: E402
from scripts.lib import release_capability as CAP  # noqa: E402
from scripts.lib import release_control as RC  # noqa: E402
from scripts.lib import release_delegation as RD  # noqa: E402
from scripts.lib import release_grant_binding as B  # noqa: E402

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 21, 18, 10, tzinfo=ET).timestamp()
TRAIN = "rt-20261021-1800-ab12cd"
OTHER_TRAIN = "rt-20261021-1800-ef34ab"
BASE = "a" * 40
MERGED = "c" * 40
BATCH = "b" * 40
HEADS = [{"pr": 1901, "head_sha": "1" * 40}]
ARTIFACT = "sha256:" + "d" * 64
CHECKS = ("cio-hardening", "agent-governance", "release-readiness", "ci-gate")
HOST = RC.Actor("host_cli", "uid:test")
CC = RC.Actor("cc", "operator@tailnet")
CTRL = RC.Actor("controller", "tradeai-release-train.service")


class Clock:
    def __init__(self, t: float = NOW) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def evidence(sha, names=CHECKS):
    return {"sha": sha, "checks": [{"name": n, "head_sha": sha, "status": "completed", "conclusion": "success"}
                                   for n in names]}


def proof(ctl, command):
    return RC.HostCliProof(tty="/dev/pts/9", uid=os.getuid(), confirmation=ctl.expected_phrase(command))


def delegation_body():
    d = json.loads(RD.EXAMPLE_PATH.read_text(encoding="utf-8"))
    d["status"] = "ACTIVE"
    d["delegation_id"] = "rtd-test-0001"
    d["operator"]["approved_at"] = "2026-10-21T17:00:00-04:00"
    for s in d["windows"]["slots"]:
        s["enabled"] = s["window_id"] == "1800"
    return d


class World:
    def __init__(self, tmp: Path, train: str = TRAIN) -> None:
        self.state = tmp / "state"
        self.state.mkdir()
        host = tmp / "host"
        host.mkdir()
        self.key = host / "capability.key"
        self.key.write_bytes(os.urandom(48).hex().encode())
        os.chmod(self.key, 0o600)
        self.deleg = host / "delegation.json"
        self.deleg.write_text(json.dumps(delegation_body()), encoding="utf-8")
        self.clock = Clock()
        self.ctl = RC.ReleaseControl(self.state, clock=self.clock)
        self.ctl.arm(HOST, proof(self.ctl, "arm"), policy_digest=RD.load(self.deleg).digest, reason="arm for test")
        self.ctl.claim_train(CTRL, train)
        self.train = train
        self.auth = CAP.CapabilityAuthority(self.state, key_path=self.key, delegation_path=self.deleg,
                                            clock=self.clock, lock_timeout_s=0.0)

    def issue(self, action="promote_release", train=None):
        return self.auth.issue_promote(
            train or self.train, expected_base_sha=BASE, pr_heads=HEADS, candidate_sha=MERGED,
            artifact_digest=ARTIFACT, evidence=evidence(MERGED, CHECKS[:3]), batch_candidate_sha=BATCH,
            batch_evidence=evidence(BATCH), rollback_target={"kind": "release", "sha": BASE, "release": "/r/prev"},
            services=["portfolio-server.service"], actions=[action])

    def observed(self, **over):
        o = {"repository": "PatsKiller/tardeai", "environment": "production", "train_id": self.train,
             "main_sha": MERGED, "candidate_sha": MERGED, "artifact_digest": ARTIFACT}
        o.update(over)
        return o

    def reserve(self, action="promote_release", write_token=True):
        token = self.issue(action)
        res = self.auth.reserve(token, action, observed=self.observed())
        if write_token:
            B.write_reservation_token(self.state, self.train, action, token)
        return token, res

    def decide(self, action="promote", sha=MERGED, campaign=None, **kw):
        kw.setdefault("state_dir", self.state)
        kw.setdefault("key_path", self.key)
        kw.setdefault("delegation_path", self.deleg)
        kw.setdefault("now", self.clock())
        kw.setdefault("status", "ACTIVE")
        return B.decide_capability(action, sha, campaign or f"release-train-{self.train}", **kw)


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


# ── the flag ──────────────────────────────────────────────────────────────────────────────────────────

def test_flag_ships_proposed_and_is_a_code_constant():
    assert B.CAPABILITY_BINDING_STATUS == "PROPOSED"
    assert B.capability_binding_active() is False
    src = (ROOT / "scripts" / "lib" / "release_grant_binding.py").read_text(encoding="utf-8")
    assert 'CAPABILITY_BINDING_STATUS = "PROPOSED"' in src


def test_flag_off_refuses_even_a_perfect_reservation(w):
    _, res = w.reserve()
    v = w.decide(status=None)
    assert (v.allowed, v.code) == (False, "BINDING_NOT_ACTIVE")
    res.succeeded({"t": 1})


def test_env_cannot_turn_the_flag_on(monkeypatch):
    for name in ("TRADEAI_RELEASE_CAPABILITY_BINDING", "CAPABILITY_BINDING_STATUS", "TRADEAI_RELEASE_GRANT_BINDING"):
        monkeypatch.setenv(name, "ACTIVE")
    assert B.capability_binding_active() is False


def _run_main(monkeypatch, capsys, argv, env=None):
    monkeypatch.setattr(sys, "argv", ["release_grant_preflight.py", *argv])
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    rc = PF.main()
    out = capsys.readouterr().out.strip().splitlines()[-1]
    return rc, json.loads(out)


def test_preflight_flag_off_output_is_unchanged(monkeypatch, capsys, w):
    """Flag off: a train campaign with no grant is refused exactly as before; no capability key appears and the
    capability ledger is never consulted."""
    _, res = w.reserve()
    monkeypatch.setattr(PF, "decide_from_disk", lambda act: B.decide(act, grants=[]))
    monkeypatch.setattr(PF, "decide_capability", lambda *a, **k: pytest.fail("consulted while PROPOSED"))
    rc, body = _run_main(monkeypatch, capsys, ["--action", "prepare", "--sha", MERGED, "--no-consume"],
                         env={"TRADEAI_RELEASE_CAMPAIGN": f"release-train-{TRAIN}"})
    assert rc == 2 and body["allowed"] is False
    assert set(body) == {"schema", "allowed", "reason", "grant_id", "matched_by", "pending_request_ids",
                         "refused_grants", "mode", "action", "sha", "pr"}
    res.succeeded({"t": 1})


def _active_main(monkeypatch, w):
    monkeypatch.setattr(B, "CAPABILITY_BINDING_STATUS", "ACTIVE")
    monkeypatch.setattr(PF, "capability_binding_active", lambda: True)
    monkeypatch.setattr(PF, "decide_from_disk", lambda act: B.decide(act, grants=[]))
    monkeypatch.setattr(PF, "decide_capability", lambda a, s, c, **k: w.decide(a, s, c, **k))
    monkeypatch.setattr(PF, "consume_release_grant", lambda **k: pytest.fail("guard ledger consumed"))


def test_preflight_active_accepts_prepare_and_never_consumes_the_guard_ledger(monkeypatch, capsys, w):
    _, res = w.reserve("prepare_release")
    _active_main(monkeypatch, w)
    rc, body = _run_main(monkeypatch, capsys, ["--action", "prepare", "--sha", MERGED],
                         env={"TRADEAI_RELEASE_CAMPAIGN": f"release-train-{TRAIN}"})
    assert rc == 0 and body["allowed"] is True
    assert body["binding_source"] == "capability_ledger"
    assert body["consumed"] == {"skipped": "capability_binding"}
    assert body["capability_binding"]["code"] == "CAPABILITY_RESERVED"
    res.succeeded({"t": 1})


def test_preflight_active_promote_still_reads_exact_sha_ci(monkeypatch, capsys, w):
    _, res = w.reserve("promote_release")
    _active_main(monkeypatch, w)
    monkeypatch.setattr(PF, "promote_ci_gate", lambda sha, receipt: {"ok": False, "errors": ["missing"]})
    rc, body = _run_main(monkeypatch, capsys, ["--action", "promote", "--sha", MERGED],
                         env={"TRADEAI_RELEASE_CAMPAIGN": f"release-train-{TRAIN}"})
    assert rc == 3 and body["consumed"] == {"ok": False, "skipped": "ci_not_green"}
    res.succeeded({"t": 1})


def test_preflight_active_a_per_pr_grant_still_works_first(monkeypatch, capsys, w):
    _active_main(monkeypatch, w)
    grant = {"tier": "release-write", "grant_id": "g1", "expires": NOW + 3600, "uses": 3,
             "reason": f"PR #1950 sha {MERGED[:12]} prepare,promote"}
    monkeypatch.setattr(PF, "decide_from_disk", lambda act: B.decide(
        B.ReleaseAction(**{**act.__dict__, "now": NOW}), grants=[grant]))
    monkeypatch.setattr(PF, "decide_capability", lambda *a, **k: pytest.fail("grant path must win"))
    rc, body = _run_main(monkeypatch, capsys, ["--action", "prepare", "--sha", MERGED, "--pr", "1950",
                                               "--no-consume"])
    assert rc == 0 and body["grant_id"] == "g1" and "capability_binding" not in body


def test_preflight_active_rollback_is_never_capability_bound(monkeypatch, capsys, w):
    _active_main(monkeypatch, w)
    monkeypatch.setattr(PF, "decide_capability", lambda *a, **k: pytest.fail("rollback is grant-only"))
    rc, body = _run_main(monkeypatch, capsys, ["--action", "rollback", "--sha", MERGED, "--no-consume"],
                         env={"TRADEAI_RELEASE_CAMPAIGN": f"release-train-{TRAIN}"})
    assert rc == 2 and body["allowed"] is False


# ── the happy path ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("action,cap_action", [("prepare", "prepare_release"), ("promote", "promote_release")])
def test_reserved_capability_binds_this_release(w, action, cap_action):
    _, res = w.reserve(cap_action)
    v = w.decide(action)
    assert v.allowed, v.to_dict()
    assert v.code == "CAPABILITY_RESERVED" and v.train_id == TRAIN and v.intent_id == res.intent_id
    assert w.decide(action, artifact_digest=ARTIFACT).allowed
    res.succeeded({"t": 1})


def test_preflight_reads_and_writes_nothing(w):
    _, res = w.reserve()
    before = {p: p.read_bytes() for p in w.state.rglob("*") if p.is_file()}
    assert w.decide().allowed
    after = {p: p.read_bytes() for p in w.state.rglob("*") if p.is_file()}
    assert before == after
    res.succeeded({"t": 1})


# ── the adversarial list ──────────────────────────────────────────────────────────────────────────────

def test_forged_token_is_refused(w, tmp_path):
    token, res = w.reserve()
    prefix, body, _sig = token.split(".")
    other = os.urandom(48).hex().encode()
    forged = f"{prefix}.{body}.{CAP._sign(other, CAP._b64d(body))}"
    B.write_reservation_token(w.state, TRAIN, "promote_release", forged)
    assert w.decide().code == "SIGNATURE_INVALID"
    # an edited body under the original signature is refused the same way
    tampered = json.loads(CAP._b64d(body))
    tampered["candidate_sha"] = "e" * 40
    raw = RD.canonical(tampered)
    B.write_reservation_token(w.state, TRAIN, "promote_release", f"{prefix}.{CAP._b64e(raw)}.{_sig}")
    assert w.decide().code == "SIGNATURE_INVALID"
    res.succeeded({"t": 1})


def test_valid_signature_but_not_the_issued_record_is_refused(w):
    spare = w.issue()                             # issued before the reservation takes the global lock
    _, res = w.reserve()
    key = CAP.load_key(w.key)
    raw = RD.canonical({**CAP.decode(spare, key), "capability_id": "f" * 32})
    B.write_reservation_token(w.state, TRAIN, "promote_release",
                              f"{CAP.TOKEN_PREFIX}.{CAP._b64e(raw)}.{CAP._sign(key, raw)}")
    assert w.decide().code == "CAPABILITY_UNKNOWN"
    res.succeeded({"t": 1})


def test_expired_capability_is_refused(w):
    token, res = w.reserve()
    exp = CAP.decode(token, CAP.load_key(w.key))["expires_at"]
    assert w.decide(now=exp + 1).code == "CAPABILITY_EXPIRED"
    res.succeeded({"t": 1})


def test_wrong_sha_is_refused(w):
    _, res = w.reserve()
    assert w.decide(sha="e" * 40).code == "WRONG_SHA"
    assert w.decide(sha=MERGED[:12]).code == "SHA_INVALID"
    res.succeeded({"t": 1})


def test_wrong_artifact_is_refused(w):
    _, res = w.reserve()
    assert w.decide(artifact_digest="sha256:" + "0" * 64).code == "WRONG_ARTIFACT"
    res.succeeded({"t": 1})


def test_wrong_phase_is_refused(w):
    """A merge capability is valid and signed, but it is not a promote-phase capability."""
    merge = w.auth.issue_merge(TRAIN, expected_base_sha=BASE, pr_heads=HEADS, candidate_sha=MERGED,
                               artifact_digest=ARTIFACT, evidence=evidence(MERGED),
                               rollback_target={"kind": "main_ref", "sha": BASE}, actions=["merge_batch_pr"])
    B.write_reservation_token(w.state, TRAIN, "promote_release", merge)
    assert w.decide().code == "WRONG_PHASE"


def test_wrong_action_is_refused(w):
    """A promote_release capability does not authorize prepare (and the reverse)."""
    token, res = w.reserve("promote_release")
    B.write_reservation_token(w.state, TRAIN, "prepare_release", token)
    assert w.decide("prepare").code == "ACTION_NOT_PERMITTED"
    res.succeeded({"t": 1})


def test_rollback_and_verify_are_not_capability_bound(w):
    assert w.decide("rollback").code == "ACTION_NOT_BOUND"
    assert w.decide("verify").code == "ACTION_NOT_BOUND"


def test_replayed_reservation_is_refused(w):
    _, res = w.reserve()
    res.succeeded({"t": 1})                       # the effect happened: the token on disk is now a replay
    assert w.decide().code == "REPLAY"


def test_refunded_reservation_is_not_an_authority(w):
    _, res = w.reserve()
    res._end(CAP.ABORTED_NO_EFFECT, {"x": 1}, refund=True)
    assert w.decide().code == "RESERVATION_MISSING"


def test_issued_but_never_reserved_is_refused(w):
    B.write_reservation_token(w.state, TRAIN, "promote_release", w.issue())
    v = w.decide()
    assert v.code == "RESERVATION_MISSING"


def test_dead_holder_is_refused(w):
    """The global lock is free: the process that reserved is gone, so the effect is UNCERTAIN, not authorized."""
    _, res = w.reserve()
    res._lock.release()
    assert w.decide().code == "RESERVATION_HOLDER_GONE"


def test_uncertain_intent_anywhere_blocks(w):
    _, res = w.reserve()
    ledger = json.loads((w.state / CAP.LEDGER_NAME).read_text())
    ledger["intents"]["0" * 32] = {"intent_id": "0" * 32, "status": CAP.UNCERTAIN, "train_id": TRAIN}
    RC._atomic_write_json(w.state / CAP.LEDGER_NAME, ledger)
    assert w.decide().code == "RECONCILIATION_REQUIRED"
    res._lock.release()


def test_stop_between_reserve_and_preflight_is_refused(w):
    _, res = w.reserve()
    w.ctl.request_stop(CC, "operator STOP between reserve and preflight")
    assert w.decide().code == "STOP_LATCHED"
    res._lock.release()


def test_unreadable_latch_is_refused(w):
    _, res = w.reserve()
    (w.state / RC.LATCH_NAME).write_text("{corrupt", encoding="utf-8")
    assert w.decide().code == "STOP_LATCH_UNREADABLE"
    res._lock.release()


def test_epoch_change_between_reserve_and_preflight_is_refused(w):
    _, res = w.reserve()
    p = w.state / RC.CONTROL_NAME
    body = json.loads(p.read_text())
    body["epoch"] += 1
    body["version"] += 1
    RC._atomic_write_json(p, body)
    assert w.ctl.view().latch_state == RC.LATCH_ABSENT
    assert w.decide().code == "EPOCH_STALE"
    res._lock.release()


def test_pause_and_revoke_are_refused(w):
    _, res = w.reserve()
    p = w.state / RC.CONTROL_NAME
    body = json.loads(p.read_text())
    RC._atomic_write_json(p, {**body, "mode": RC.PAUSED})
    assert w.decide().code == "PAUSED"
    RC._atomic_write_json(p, {**body, "mode": RC.REVOKED})
    assert w.decide().code == "REVOKED"
    res._lock.release()


def test_delegation_edit_after_reserve_is_refused(w):
    _, res = w.reserve()
    d = json.loads(w.deleg.read_text())
    d["limits"]["max_prs_per_train"] = int(d["limits"]["max_prs_per_train"]) + 1
    w.deleg.write_text(json.dumps(d), encoding="utf-8")
    assert w.decide().code == "POLICY_DIGEST_CHANGED"
    res._lock.release()


def test_reservation_for_another_train_is_refused(w):
    """Train A's reserved token copied under train B's campaign path."""
    token, res = w.reserve()
    B.write_reservation_token(w.state, OTHER_TRAIN, "promote_release", token)
    assert w.decide(campaign=f"release-train-{OTHER_TRAIN}").code == "WRONG_TRAIN"
    res.succeeded({"t": 1})


def test_reservation_while_another_train_is_current_is_refused(tmp_path):
    w = World(tmp_path)
    _, res = w.reserve()
    p = w.state / RC.CONTROL_NAME
    RC._atomic_write_json(p, {**json.loads(p.read_text()), "current_train_id": OTHER_TRAIN})
    assert w.decide().code == "TRAIN_NOT_CLAIMED"
    res._lock.release()


@pytest.mark.parametrize("campaign", ["release-window-20261021-1800", "release-train-", "release-train-x",
                                      "trade-ai-maturity-overnight-20260912"])
def test_campaign_that_is_not_a_train_is_refused(w, campaign):
    assert w.decide(campaign=campaign).code == "CAMPAIGN_NOT_TRAIN"


def test_campaign_alone_never_grants(w, monkeypatch):
    """The campaign env identifies; with no reserved capability nothing is authorized."""
    monkeypatch.setenv("TRADEAI_RELEASE_CAMPAIGN", f"release-train-{TRAIN}")
    monkeypatch.setenv("TRADEAI_RELEASE_TRAIN_SHA", MERGED)
    assert w.decide().code == "TOKEN_MISSING"


def test_env_state_dir_override_cannot_plant_a_ledger(w, tmp_path):
    v = B.decide_capability("promote", MERGED, f"release-train-{TRAIN}", key_path=w.key,
                            delegation_path=w.deleg, now=NOW, status="ACTIVE",
                            env={"TRADEAI_RELEASE_WINDOW_STATE_DIR": str(w.state)})
    assert v.code == "STATE_DIR_OVERRIDDEN"


def test_token_file_must_be_private(w):
    _, res = w.reserve()
    p = B.reservation_token_path(w.state, TRAIN, "promote_release")
    os.chmod(p, 0o644)
    assert w.decide().code == "TOKEN_UNSAFE"
    res.succeeded({"t": 1})


def test_missing_or_unreadable_key_is_refused(w, tmp_path):
    _, res = w.reserve()
    assert w.decide(key_path=tmp_path / "nope.key").code == "KEY_MISSING"
    res.succeeded({"t": 1})


def test_written_token_is_mode_600(w):
    p = B.write_reservation_token(w.state, TRAIN, "promote_release", "rcap1.x.y")
    assert (p.stat().st_mode & 0o777) == 0o600
