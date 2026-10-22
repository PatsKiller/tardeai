"""Release train arming finding 8 (ANCHOR RELEASE_TRAIN_FORCED_CANARY_20261021): operator-forced off-window CANARY
runs.

``release_window.py train-run --live --force-window 1800 --operator-forced --operator-ref <ref> --forced-n <n>``:
host CLI only (never n8n, never the CC), a TTY plus a typed phrase for a live run; allowed only while the delegation
carries ``"phase": "canary"`` AND the controller policy's canary flag allows the slot (shipped FALSE). It overrides
ONLY the window timing: latch, armed control, ACTIVE delegation, slot enabled in scope, epoch, capabilities, the four
checks, self-modification blocking and quarantine all still apply. Each run is recorded with ``forced_by=operator``,
``operator_ref`` and ``window_gate_overridden=true`` (TrainEvent, trains/<id>/forced.json, outcome notes, the CC
train history) under the key ``rtw:<slot>:<date>:live:forced:<n>``, idempotent per n.

Hermetic: the controller test world under tmp_path (tmp git repo, fake GitHub, fake deploy host). No network, DB,
systemd or broker. psycopg2 is stubbed by the imported controller test module.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tests.test_release_train_controller_20261021 import World, delegation_body, runs_for  # noqa: E402
from scripts.lib import release_delegation as RD  # noqa: E402
from scripts.lib import release_train_controller as T  # noqa: E402
from scripts.lib import release_train_queue as Q  # noqa: E402
from scripts.lib import release_train_window_view as WV  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
OFF = datetime(2026, 10, 21, 14, 0, tzinfo=ET)            # well outside the 18:00 window (and its 90 min lead)
ALLOW = {"operator_forced_off_window": True, "slots": ["1800"]}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _world(tmp_path, *, phase="canary", enabled=True, arm=True, policy=ALLOW, monkeypatch=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    w = World(tmp_path, now=OFF, arm=False)
    d = delegation_body("1800" if enabled else "none")
    if phase is not None:
        d["phase"] = phase
    w.deleg.write_text(json.dumps(d))
    assert RD.validate(d) == []
    if arm:
        w.ctl.arm(T.RC.Actor("host_cli", "uid:test"),
                  T.RC.HostCliProof("/dev/pts/9", __import__("os").getuid(), w.ctl.expected_phrase("arm")),
                  policy_digest=RD.load(w.deleg).digest, reason="arm for test")
    if monkeypatch is not None:
        # the controller's view and the capability authority's independent read both see this test policy
        pol = json.loads((ROOT / "config/release_train_policy.json").read_text(encoding="utf-8"))
        pol["canary"] = {**pol["canary"], **policy}
        pp = tmp_path / "policy.json"
        pp.write_text(json.dumps(pol))
        monkeypatch.setattr(T.WV, "POLICY_PATH", pp)
        monkeypatch.setattr(T.CAP, "POLICY_PATH", pp)
    return w


def _forced(w, n=1, *, confirmed=True, live=True, ref="canary-proof-1", **kw):
    c = w.controller(live=live, force_window="1800", forced_n=n, operator_ref=ref, forced_confirmed=confirmed, **kw)
    return c.run(OFF)


def test_committed_policy_ships_the_flag_off_and_the_schema_knows_phase():
    pol = T.forced_canary_policy()
    assert pol == {"operator_forced_off_window": False, "slots": ["1800"]}
    schema = json.loads((ROOT / "config/schemas/release_delegation_v1.schema.json").read_text())
    assert schema["properties"]["phase"]["enum"] == ["shadow", "canary", "expand"]
    assert RD.validate({**delegation_body(), "phase": "nope"}) and RD.PHASES == {"shadow", "canary", "expand"}


def test_a_forced_canary_run_releases_and_records_the_override(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch=monkeypatch)
    code, rec = _forced(w)
    assert rec["outcome"] == "RELEASED_VERIFIED", (rec["outcome"], rec.get("reason"), rec.get("detail"))
    f = rec["forced"]
    assert f["forced_by"] == "operator" and f["operator_ref"] == "canary-proof-1" and f["window_gate_overridden"] is True
    assert f["forced_key"] == "rtw:1800:20261021:live:forced:1" and T.FORCED_KEY_RE.match(f["forced_key"])
    claimed = [e for e in w.events() if e["event_type"] == "selected" and e["subject_kind"] == "train"]
    assert claimed and claimed[0]["payload"]["forced"]["window_gate_overridden"] is True
    assert claimed[0]["idempotency_key"] == "rtw:1800:20261021:live:forced:1:claimed"
    tid = rec["train_id"]
    receipt = json.loads((w.state_dir / "trains" / tid / "forced.json").read_text())
    assert receipt["schema"] == "TrainForcedRun@v1" and receipt["forced_by"] == "operator"
    outcome = json.loads((w.state_dir / "trains" / tid / "outcome.json").read_text())
    assert outcome["notes"].startswith("[OPERATOR-FORCED rtw:1800:20261021:live:forced:1 ref canary-proof-1")
    # the CC train history (folded from the events) shows the forced flag
    evs = [e for e in w.events() if e.get("train_id") == tid]
    detail = Q.train_detail(tid, evs)
    assert detail["forced"]["window_gate_overridden"] is True and Q._train_row(detail)["forced"] is True
    assert Q._train_row(detail)["forced_ref"] == "canary-proof-1"


def test_forced_runs_are_idempotent_per_n_and_repeatable_with_a_new_n(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch=monkeypatch)
    assert _forced(w, 1)[1]["outcome"] == "RELEASED_VERIFIED"
    again = _forced(w, 1)[1]
    assert again["reason"] == "REFUSED_WINDOW_ALREADY_CLAIMED"
    w.gh.heads = dict(w.repo.heads)                       # a fresh evening proof
    second = _forced(w, 2)[1]
    assert second["reason"] != "REFUSED_WINDOW_ALREADY_CLAIMED" and second["forced"]["forced_n"] == 2


@pytest.mark.parametrize("phase", [None, "shadow", "expand"])
def test_refused_outside_canary(tmp_path, monkeypatch, phase):
    w = _world(tmp_path, phase=phase, monkeypatch=monkeypatch)
    code, rec = _forced(w)
    assert rec["reason"] == "REFUSED_FORCE_NOT_CANARY" and code == T.EXIT_REFUSED
    assert w.writer.calls == [] and w.host.calls == [] and not (w.state_dir / "claims").exists()


def test_refused_while_the_policy_flag_is_off(tmp_path, monkeypatch):
    w = _world(tmp_path, policy={"operator_forced_off_window": False, "slots": ["1800"]}, monkeypatch=monkeypatch)
    assert _forced(w)[1]["reason"] == "REFUSED_FORCE_NOT_ALLOWED"
    w2 = _world(tmp_path / "b", policy={"operator_forced_off_window": True, "slots": ["0000"]}, monkeypatch=monkeypatch)
    assert _forced(w2)[1]["reason"] == "REFUSED_FORCE_NOT_ALLOWED"


def test_refused_live_without_the_tty_proof(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch=monkeypatch)
    code, rec = _forced(w, confirmed=False)
    assert rec["reason"] == "REFUSED_FORCE_UNCONFIRMED" and w.writer.calls == []


def test_refused_when_stop_is_set(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch=monkeypatch)
    w.state.write(w.state.latch, {"latched_at": "x"})
    code, rec = _forced(w)
    assert rec["reason"] == "REFUSED_STOP_LATCHED" and w.writer.calls == [] and w.host.calls == []


def test_every_other_gate_still_applies(tmp_path, monkeypatch):
    # slot not enabled in the delegation scope
    w = _world(tmp_path / "a", enabled=False, monkeypatch=monkeypatch)
    assert _forced(w)[1]["reason"] == "REFUSED_WINDOW_DISABLED"
    # control not armed
    w = _world(tmp_path / "b", arm=False, monkeypatch=monkeypatch)
    assert _forced(w)[1]["reason"] == "REFUSED_CONTROL_UNARMED"
    # quarantined lineage
    w = _world(tmp_path / "c", monkeypatch=monkeypatch)
    (w.state_dir / "quarantine.jsonl").write_text(json.dumps({"kind": "quarantine", "sha": w.gh.main}) + "\n")
    assert _forced(w)[1]["reason"] == "REFUSED_QUARANTINED_LINEAGE"
    # a red batch check: never merged
    w = _world(tmp_path / "d", monkeypatch=monkeypatch)
    w.gh.default_runs = False
    w.gh.check_runs = lambda sha: runs_for(sha, conclusion="failure")
    code, rec = _forced(w)
    assert rec["outcome"] == "FAILED_PRE_MERGE" and not any(c[0] == "merge" for c in w.writer.calls)
    # self-modification is still blocked
    w = _world(tmp_path / "e", monkeypatch=monkeypatch)
    w.repo.pr(13, {"scripts/release_window.py": "x\n"})
    from tests.test_release_train_controller_20261021 import StaticQueue
    code, rec = _forced(w, queue=StaticQueue(w.entries([13])))
    assert rec["outcome"] == "NO_OP" and "BLOCKED_SELF_MODIFICATION" in json.dumps(rec.get("selection"))


def test_forced_key_is_host_only_never_an_n8n_run_key():
    k = T.forced_key("1800", datetime(2026, 10, 21).date(), 3)
    assert k == "rtw:1800:20261021:live:forced:3" and T.FORCED_KEY_RE.match(k)
    assert not WV.RUN_KEY_RE.match(k)                      # the gateway's request-lane key refuses it
    assert not T.FORCED_KEY_RE.match("rtw:1800:20261021:live") and not T.FORCED_KEY_RE.match(k + "x")


class _TTY:
    def __init__(self, typed, tty=True):
        self.typed, self.tty = typed, tty

    def isatty(self):
        return self.tty

    def readline(self):
        return self.typed + "\n"


def _args(**kw):
    base = dict(cmd="train-run", live=True, inject=None, integrate=False, local_test=False, simulate_classifier=None,
                now=None, json=True, force_window="1800", operator_forced=True, operator_ref="canary-proof-1",
                forced_n=1)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def cli_world(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(T, "TRAIN_CONTROLLER_STATUS", "ACTIVE")
    monkeypatch.setattr(T.RW, "State", lambda *a, **k: w.state)
    seen = {}

    def build(*, live, config=None, **_):
        seen["config"] = config
        return w.controller(live=live, force_window=config.force_window, forced_n=config.forced_n,
                            operator_ref=config.operator_ref, forced_confirmed=config.forced_confirmed)

    monkeypatch.setattr(T, "build_controller", build)
    w.clock.t = OFF.timestamp()
    return w, seen


def test_cli_refuses_a_live_forced_run_without_a_tty(cli_world, capsys):
    w, seen = cli_world
    assert T.cli(_args(), stdin=_TTY("x", tty=False)) == T.EXIT_REFUSED
    assert "REFUSED_FORCE_NO_TTY" in capsys.readouterr().out and "config" not in seen


def test_cli_refuses_a_wrong_phrase(cli_world, capsys):
    w, seen = cli_world
    assert T.cli(_args(), stdin=_TTY("FORCE WINDOW 1800 RUN 2 EPOCH 1")) == T.EXIT_REFUSED
    assert "REFUSED_FORCE_PHRASE" in capsys.readouterr().out and "config" not in seen


def test_cli_refuses_without_the_operator_flags(cli_world, capsys):
    w, seen = cli_world
    for kw in ({"operator_forced": False}, {"operator_ref": None}, {"forced_n": None}):
        assert T.cli(_args(**kw), stdin=_TTY("x")) == T.EXIT_REFUSED
    assert "config" not in seen


def test_cli_with_the_typed_phrase_confirms_the_run(cli_world, capsys):
    w, seen = cli_world
    epoch = T.RC.ReleaseControl(w.state_dir).view().epoch
    phrase = T.forced_phrase("1800", 1, epoch)
    assert phrase == f"FORCE WINDOW 1800 RUN 1 EPOCH {epoch}"
    code = T.cli(_args(), stdin=_TTY(phrase))
    assert seen["config"].forced_confirmed is True and seen["config"].force_window == "1800"
    out = json.loads(capsys.readouterr().out)
    assert out["forced"]["forced_by"] == "operator" and out["outcome"] == "RELEASED_VERIFIED", out.get("reason")


def test_still_refused_while_the_controller_is_build_only(cli_world, monkeypatch, capsys):
    monkeypatch.setattr(T, "TRAIN_CONTROLLER_STATUS", "BUILD_ONLY")
    assert T.cli(_args(), stdin=_TTY("x")) == T.EXIT_REFUSED
    assert "REFUSED_BUILD_ONLY" in capsys.readouterr().out


def test_never_reachable_from_n8n_or_the_cc():
    allow = (ROOT / "config/n8n_run_allowlist.json").read_text(encoding="utf-8")
    assert "--force-window" not in allow and "--operator-forced" not in allow
    for p in ("scripts/api_v2.py", "scripts/n8n_coordination_gateway.py", "scripts/n8n_run_relay.py"):
        f = ROOT / p
        if f.exists():
            assert "force-window" not in f.read_text(encoding="utf-8") and "force_window" not in f.read_text(
                encoding="utf-8")
    wf = (ROOT / "docs/implementation/n8n-maturity/workflows/fabric/tradeai-fabric-release-train.json").read_text()
    assert "force" not in wf.lower() or "--force-window" not in wf


def test_parser_has_the_flags():
    from scripts import release_window as RWm

    src = Path(RWm.__file__).read_text(encoding="utf-8")
    for flag in ("--force-window", "--operator-forced", "--operator-ref", "--forced-n"):
        assert flag in src


def test_packet_phase_i_uses_it_and_finding_8_is_recorded():
    text = (ROOT / "docs/ops/packets/release-train-arming-20261021/README.md").read_text(encoding="utf-8")
    i = text[text.index("## I. Phase 6"):text.index("## J. Phase 7")]
    assert "--force-window 1800 --operator-forced" in i and "one evening" in i
    f8 = text[text.index("8. **\"No minimum number of days\" versus one train per window.**"):]
    assert "**Status: ADDRESSED" in f8[:2500]


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_train_forced_canary_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_TRAIN_FORCED_CANARY_20261021"
    assert "tests/test_release_train_forced_canary_20261021.py" in doc["files"]
