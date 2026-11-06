"""ANCHOR: RELAY_LIVE_SOURCE_ONEWAY_20261031

The n8n relay's live-lane list followed the AGENTS.md header status. A PATCH that changed no rule text
(27.0.0 PROPOSED -> 27.0.1 ACTIVE) moved the live set by 10 lanes at a promote, trade-ai-scalp-live among them,
with no operator step and no message. Now: config/n8n_relay_live_source.json pins the registry render one-way,
prepare reports the effective live-set change and every exclusion, and promote holds until the operator acks it.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.lib import n8n_relay_live_lanes as RLL
from scripts.lib import relay_live_set_gate as G

REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / "scripts" / "cio_phase2_exact_main_deploy.sh"
STATUS_RE = re.compile(r"^Status:(\s+)\S+", re.M)


def _root(tmp: Path, name: str, *, status: str = "ACTIVE", pin: object = "file", build: str = "a" * 40,
          drop_live_arg: str | None = None, extra_rows: list | None = None) -> Path:
    root = tmp / name
    (root / "config").mkdir(parents=True)
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    (root / "AGENTS.md").write_text(STATUS_RE.sub(lambda m: f"Status:{m.group(1)}{status}", text, count=1), encoding="utf-8")
    for rel in (RLL.REGISTRY_REL, RLL.ALLOWLIST_REL, RLL.CUTOVER_POLICY_REL):
        shutil.copy(REPO / rel, root / rel)
    if pin == "file":
        shutil.copy(REPO / RLL.SOURCE_REL, root / RLL.SOURCE_REL)
    elif pin is not None:
        (root / RLL.SOURCE_REL).write_text(pin if isinstance(pin, str) else json.dumps(pin), encoding="utf-8")
    al = json.loads((root / RLL.ALLOWLIST_REL).read_text())
    reg = json.loads((root / RLL.REGISTRY_REL).read_text())
    if drop_live_arg:
        for e in al["lanes"]:
            if e.get("lane_id") == drop_live_arg:
                e["live_arg"] = None
    for row, entry in extra_rows or []:
        reg["lanes"].append(row)
        al["lanes"].append(entry)
    (root / RLL.ALLOWLIST_REL).write_text(json.dumps(al), encoding="utf-8")
    (root / RLL.REGISTRY_REL).write_text(json.dumps(reg), encoding="utf-8")
    (root / "BUILD_SHA").write_text(build + "\n", encoding="utf-8")
    assert RLL.render(root)["ok"] is True
    return root


@pytest.fixture()
def env(tmp_path: Path) -> dict:
    (tmp_path / "state").mkdir()
    return {"TRADEAI_STATE_ROOT": str(tmp_path / "state")}


def test_repo_pins_registry_render_one_way() -> None:
    doc = json.loads((REPO / RLL.SOURCE_REL).read_text(encoding="utf-8"))
    assert doc["schema"] == RLL.SOURCE_SCHEMA
    assert doc["source"] == "registry_render" and doc["one_way"] is True


def test_header_flip_does_not_move_the_live_set_when_pinned(tmp_path: Path, env: dict) -> None:
    active = RLL.resolve(env, _root(tmp_path, "a", status="ACTIVE"))
    proposed = RLL.resolve(env, _root(tmp_path, "p", status="PROPOSED"))
    assert active["source"] == proposed["source"] == "registry_render"
    assert active["lanes"] == proposed["lanes"] and len(active["lanes"]) > 0


def test_without_the_pin_the_header_still_decides(tmp_path: Path, env: dict) -> None:
    """Documents what the pin protects against: the pre-2026-10-31 behaviour is unchanged for unpinned roots."""
    res = RLL.resolve(env, _root(tmp_path, "p", status="PROPOSED", pin=None))
    assert res["source"] == "host_env_legacy"


@pytest.mark.parametrize("pin", ["{not json", {"schema": RLL.SOURCE_SCHEMA, "source": "host_env_legacy"}, {"x": 1}])
def test_a_present_but_other_or_broken_pin_never_falls_back(tmp_path: Path, env: dict, pin) -> None:
    res = RLL.resolve(env, _root(tmp_path, "p", status="PROPOSED", pin=pin))
    assert res["source"] == "registry_render"
    assert RLL.live_source(tmp_path / "p")["pinned"] is True


def test_header_flip_without_pin_is_caught_and_held(tmp_path: Path, env: dict) -> None:
    served = _root(tmp_path, "served", status="ACTIVE")
    new = _root(tmp_path, "new", status="PROPOSED", pin=None, build="b" * 40)
    env = {**env, RLL.LIVE_LANES_ENV: "host-only-lane"}  # a real host list: the flip is a known change
    rep = G.compute(new, served, env)
    assert rep["changed"] is True and rep["new"]["source"] == "host_env_legacy"
    assert rep["indeterminate"] is False
    assert G.gate(rep, rows={}) == (False, "unacknowledged")


def test_header_flip_onto_a_missing_host_list_is_indeterminate(tmp_path: Path, env: dict) -> None:
    # No host list at all: that side's live set is unknown, so it is refused as indeterminate, never "unchanged".
    served = _root(tmp_path, "served", status="ACTIVE")
    new = _root(tmp_path, "new", status="PROPOSED", pin=None, build="b" * 40)
    rep = G.compute(new, served, env)
    assert rep["indeterminate"] is True and "new" in rep["indeterminate_reasons"]
    assert G.gate(rep, rows={}) == (False, "indeterminate")


def test_unchanged_set_passes_the_gate(tmp_path: Path, env: dict) -> None:
    rep = G.compute(_root(tmp_path, "new", build="b" * 40), _root(tmp_path, "served"), env)
    assert rep["changed"] is False and rep["added"] == rep["removed"] == []
    assert G.gate(rep, rows={}) == (True, "unchanged")


GUARD_LEDGER = REPO / ".cursor" / "hooks" / "guard_ledger.py"


def _ledger(adir: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("_test_guard_ledger", GUARD_LEDGER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _grant(adir: Path, reason: str, *, tier: str = "release-write") -> str:
    mod = _ledger(adir)
    out = mod.ledger_create_grant_row(tier, expires=int(__import__("time").time()) + 3600, uses=1, reason=reason,
                                      adir=adir, replace=True)
    return out["grant_id"]


@pytest.fixture()
def guard(tmp_path: Path, monkeypatch) -> Path:
    adir = tmp_path / "approvals"
    adir.mkdir()
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(adir))
    return adir


def _two_deltas(tmp_path: Path, env: dict):
    """Two candidate releases of the SAME build that drop different lanes."""
    served = _root(tmp_path, "served")
    lanes = json.loads((served / RLL.RENDER_NAME).read_text())["lanes"]
    a = G.compute(_root(tmp_path, "new_a", build="b" * 40, drop_live_arg=lanes[0]), served, env)
    b = G.compute(_root(tmp_path, "new_b", build="b" * 40, drop_live_arg=lanes[1]), served, env)
    return served, lanes, a, b


def test_a_dropped_lane_holds_until_the_operator_grants_that_diff_id(tmp_path: Path, env: dict, guard: Path) -> None:
    served, lanes, rep, _ = _two_deltas(tmp_path, env)
    assert rep["removed"] == [lanes[0]] and rep["added"] == []
    assert rep["exclusions"][lanes[0]]["reason"] == "no_allowlist_live_arg"
    assert G.gate(rep) == (False, "unacknowledged")
    _grant(guard, "relay-live-set:" + rep["diff_id"], tier="state-write")  # wrong tier
    _grant(guard, "release window 1200 PR #2424")  # right tier, no diff_id
    assert G.gate(rep) == (False, "unacknowledged")
    gid = _grant(guard, f"operator ok relay-live-set:{rep['diff_id']} scalp lane reviewed")
    assert G.gate(rep) == (True, "acknowledged")
    assert G.acknowledgement(rep)["grant_id"] == gid


def test_same_build_different_delta_is_not_acknowledged(tmp_path: Path, env: dict, guard: Path) -> None:
    """The reviewer's surviving mutant: diff_id must bind the delta, not only the build."""
    _, _, a, b = _two_deltas(tmp_path, env)
    assert a["new_build"] == b["new_build"] and a["removed"] != b["removed"]
    assert a["diff_id"] != b["diff_id"]
    _grant(guard, "relay-live-set:" + a["diff_id"])
    assert G.gate(a) == (True, "acknowledged")
    assert G.gate(b) == (False, "unacknowledged")


def test_another_build_of_the_same_delta_is_not_acknowledged(tmp_path: Path, env: dict) -> None:
    _, lanes, rep, _ = _two_deltas(tmp_path, env)
    other = G.diff_id("c" * 40, rep["added"], rep["removed"])
    rows = {"release-write@g1": {"tier": "release-write", "status": "active", "reason": "relay-live-set:" + other}}
    assert G.gate(rep, rows=rows) == (False, "unacknowledged")


def test_a_revoked_grant_acknowledges_nothing(tmp_path: Path, env: dict) -> None:
    _, _, rep, _ = _two_deltas(tmp_path, env)
    row = {"tier": "release-write", "status": "revoked", "reason": "relay-live-set:" + rep["diff_id"]}
    assert G.gate(rep, rows={"release-write@g1": row}) == (False, "unacknowledged")
    assert G.gate(rep, rows={"release-write@g1": {**row, "status": "active"}}) == (True, "acknowledged")


def test_there_is_no_agent_runnable_ack() -> None:
    assert not hasattr(G, "record_ack")
    src = (REPO / "scripts" / "relay_live_set_gate.py").read_text(encoding="utf-8")
    assert '"ack"' not in src and "--by" not in src


def test_page_names_only_diff_id_build_and_counts_and_pages_once(tmp_path: Path, env: dict) -> None:
    served, lanes, rep, _ = _two_deltas(tmp_path, env)
    state = Path(env["TRADEAI_STATE_ROOT"])
    sent = []
    send = lambda msg, **kw: sent.append((msg, kw)) or True  # noqa: E731
    first = G.notify(rep, state, sender=send)
    assert first["accepted"] is True
    msg, kw = sent[0]
    assert rep["diff_id"] in msg and ("b" * 12) in msg and "1 would stop" in msg
    assert "/" not in msg and str(tmp_path) not in msg, "a path in the page text defeats dedupe"
    assert "python" not in msg and "guard" not in msg and "ack " not in msg
    assert kw["producer"] == "relay_live_set_gate" and kw["priority"] == "P1"
    # a re-prepare (new release dir, same build and delta) never pages again
    again = G.compute(_root(tmp_path, "new_a2", build="b" * 40, drop_live_arg=lanes[0]), served, env)
    assert again["diff_id"] == rep["diff_id"]
    assert G.notify(again, state, sender=send)["skipped"] == "already_paged"
    assert len(sent) == 1
    assert (state / G.PAGED_REL / f"{rep['diff_id']}-promote.json").is_file()


def test_cli_gate_holds_without_printing_a_command_and_passes_on_the_grant(tmp_path: Path, env: dict,
                                                                           guard: Path) -> None:
    served = _root(tmp_path, "served")
    lane = json.loads((served / RLL.RENDER_NAME).read_text())["lanes"][0]
    new = _root(tmp_path, "new", build="b" * 40, drop_live_arg=lane)
    cli = [sys.executable, str(REPO / "scripts" / "relay_live_set_gate.py")]
    common = ["--release", str(new), "--served", str(served), "--host-file", str(tmp_path / "absent.env")]
    run_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TRADE_AI_CI": "1", "GUARD_APPROVALS_DIR": str(guard),
               **env}
    diff = subprocess.run(cli + ["diff", *common, "--write", "--notify"], capture_output=True, text=True, env=run_env,
                          timeout=60)
    assert diff.returncode == 0 and "WARN relay live set would change" in diff.stderr
    report = json.loads((new / G.DIFF_NAME).read_text())
    assert report["removed"] == [lane]
    held = subprocess.run(cli + ["gate", *common], capture_output=True, text=True, env=run_env, timeout=60)
    assert held.returncode == 3 and f"{G.HELD_MARKER} diff_id={report['diff_id']}" in held.stderr
    for runnable in ("python", "relay_live_set_gate.py", "bin/guard", "guard grant", "--by", "ack --"):
        assert runnable not in held.stderr, runnable
    gid = _grant(guard, "relay-live-set:" + report["diff_id"])
    ok = subprocess.run(cli + ["gate", *common], capture_output=True, text=True, env=run_env, timeout=60)
    assert ok.returncode == 0 and json.loads(ok.stdout)["reason"] == "acknowledged"
    st = subprocess.run(cli + ["status", *common], capture_output=True, text=True, env=run_env, timeout=60)
    assert json.loads(st.stdout)["acknowledged_by_grant"] == gid
    bad = subprocess.run(cli + ["ack", *common], capture_output=True, text=True, env=run_env, timeout=60)
    assert bad.returncode == 2  # argparse: no such command


# ── host-state pin: rollback cannot unpin (round-2 review) ─────────────────────────────────────────────────────


def test_host_pin_pins_a_release_without_the_config_file(tmp_path: Path, env: dict) -> None:
    state = Path(env["TRADEAI_STATE_ROOT"])
    unpinned = _root(tmp_path, "old", status="PROPOSED", pin=None)
    assert RLL.resolve(env, unpinned)["source"] == "host_env_legacy"
    first = RLL.latch_host_pin(state, build="b" * 40)
    assert first["latched"] is True
    body = (state / RLL.HOST_PIN_REL).read_bytes()
    assert RLL.resolve(env, unpinned)["source"] == "registry_render"
    assert RLL.live_source(unpinned, state)["detail"] == "host_pin"
    assert RLL.latch_host_pin(state, build="c" * 40)["latched"] is False  # never overwritten
    assert (state / RLL.HOST_PIN_REL).read_bytes() == body
    (state / RLL.HOST_PIN_REL).write_text("{garbage", encoding="utf-8")  # an edited pin still pins (one-way)
    assert RLL.resolve(env, unpinned)["source"] == "registry_render"


def test_cli_latch_pin_only_from_a_release_that_carries_the_pin(tmp_path: Path, env: dict) -> None:
    cli = [sys.executable, str(REPO / "scripts" / "relay_live_set_gate.py"), "latch-pin"]
    run_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TRADE_AI_CI": "1", **env}
    old = _root(tmp_path, "old", pin=None)
    out = subprocess.run(cli + ["--release", str(old)], capture_output=True, text=True, env=run_env, timeout=60)
    assert json.loads(out.stdout)["latched"] is False
    new = _root(tmp_path, "new")
    out = subprocess.run(cli + ["--release", str(new)], capture_output=True, text=True, env=run_env, timeout=60)
    assert json.loads(out.stdout)["latched"] is True
    assert (Path(env["TRADEAI_STATE_ROOT"]) / RLL.HOST_PIN_REL).is_file()


OLD_RESOLVER = """
def resolve(environ, root):
    lanes = environ.get("TRADEAI_N8N_RELAY_LIVE_LANES")
    return {"source": "host_env_legacy", "lanes": None if lanes is None else frozenset(lanes.split()),
            "detail": "old release: header decides", "paused": []}
"""


def _old_release(tmp_path: Path, name: str = "old") -> Path:
    """A rollback target older than the pin: its own resolver follows the host list (27.0.0 PROPOSED)."""
    root = _root(tmp_path, name, status="PROPOSED", pin=None, build="9" * 40)
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / "scripts" / "lib" / "n8n_relay_live_lanes.py").write_text(OLD_RESOLVER, encoding="utf-8")
    return root


def test_rollback_diff_uses_the_target_s_own_resolver_even_with_the_host_pin(tmp_path: Path, env: dict) -> None:
    state = Path(env["TRADEAI_STATE_ROOT"])
    RLL.latch_host_pin(state)
    served = _root(tmp_path, "served")
    served_lanes = json.loads((served / RLL.RENDER_NAME).read_text())["lanes"]
    host = {**env, RLL.LIVE_LANES_ENV: "only-on-host " + " ".join(served_lanes[1:])}
    rep = G.compute(_old_release(tmp_path), served, host)
    assert rep["new"]["source"] == "host_env_legacy"  # what the old relay code will really do
    assert rep["changed"] is True and rep["added"] == ["only-on-host"] and rep["removed"] == [served_lanes[0]]
    sent = []
    page = G.notify(rep, state, event="rollback", sender=lambda m, **k: sent.append(m) or True)
    assert page["accepted"] is True and "(rollback)" in sent[0] and "not held" in sent[0]
    assert G.notify(rep, state, event="rollback", sender=lambda m, **k: sent.append(m) or True)["skipped"]


def test_cli_rollback_diff_warns_and_never_blocks(tmp_path: Path, env: dict) -> None:
    served = _root(tmp_path, "served")
    cli = [sys.executable, str(REPO / "scripts" / "relay_live_set_gate.py"), "rollback-diff",
           "--release", str(_old_release(tmp_path)), "--served", str(served), "--host-file", str(tmp_path / "h.env")]
    (tmp_path / "h.env").write_text("TRADEAI_N8N_RELAY_LIVE_LANES=x y\n", encoding="utf-8")
    run_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TRADE_AI_CI": "1", **env}
    out = subprocess.run(cli + ["--notify"], capture_output=True, text=True, env=run_env, timeout=60)
    assert out.returncode == 0 and "WARN relay live set would change at rollback" in out.stderr
    assert sorted(json.loads(out.stdout)["added"]) == ["x", "y"]


def test_every_exclusion_is_recorded_with_a_reason(tmp_path: Path, env: dict) -> None:
    row = {"lane_id": "zz-native-no-stage", "state": "ACTIVE", "scheduler": {"kind": "n8n"}}
    entry = {"lane_id": "zz-native-no-stage", "live_arg": "--apply"}
    root = _root(tmp_path, "new", extra_rows=[(row, entry)])
    ex = G.exclusions(root, G.effective(root, env))
    assert ex["zz-native-no-stage"] == {"reason": "native_n8n_no_stage", "registry_state": "ACTIVE"}
    assert all(v["reason"] for v in ex.values())


def test_paused_lane_is_an_exclusion_not_a_silent_drop(tmp_path: Path, env: dict) -> None:
    root = _root(tmp_path, "new")
    lane = json.loads((root / RLL.RENDER_NAME).read_text())["lanes"][0]
    ex = G.exclusions(root, G.effective(root, {**env, RLL.PAUSED_ENV: lane}))
    assert ex[lane]["reason"] == "paused_by_override"


def test_host_file_reads_only_the_two_lane_keys(tmp_path: Path) -> None:
    f = tmp_path / "lanes.env"
    f.write_text("SOME_TOKEN=do-not-read\nTRADEAI_N8N_RELAY_LIVE_LANES=a b\nTRADEAI_N8N_RELAY_LIVE_LANES_PAUSED='c'\n")
    assert G.host_env(f) == {"TRADEAI_N8N_RELAY_LIVE_LANES": "a b", "TRADEAI_N8N_RELAY_LIVE_LANES_PAUSED": "c"}


def test_deploy_wires_diff_at_prepare_gate_and_latch_before_activation_and_diff_at_rollback() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    render_fn = text[text.index("render_relay_live_lanes() {"):text.index("relay_live_set_gate_step() {")]
    assert '"$gate" diff --release "$dir"' in render_fn and "--write --notify" in render_fn
    promote = text[text.index("cmd_promote() {"):]
    promote = promote[:promote.index("\n}\n")]
    g, c, a = (promote.index('relay_live_set_gate_step "$dir"'), promote.index('conformance_gate "$sha"'),
               promote.index('activate_release "$dir"'))
    assert c < g < a
    step = text[text.index("relay_live_set_gate_step() {"):]
    step = step[:step.index("\n}\n")]
    assert '"$gate" gate --release' in step and "die " in step and "relay_live_set_unacknowledged" in step
    assert step.index('"$gate" gate --release') < step.index('"$gate" latch-pin --release')
    die_line = next(ln for ln in step.splitlines() if "die " in ln)
    for runnable in ("ack --", "--by", "python", "relay_live_set_gate.py", "guard grant"):
        assert runnable not in die_line, runnable
    rollback = text[text.index("cmd_rollback() {"):]
    rollback = rollback[:rollback.index("\n}\n")]
    assert rollback.index('relay_live_set_rollback_diff "$target" "$rolled_from"') < rollback.index(
        'activate_release "$target"')
    fn = text[text.index("relay_live_set_rollback_diff() {"):]
    fn = fn[:fn.index("\n}\n")]
    assert "rollback-diff --release" in fn and "--notify" in fn and "die " not in fn


# ── deploy poller: a held promote is latched, not re-prepared every tick (round-2 review) ─────────────────────


def _poller(monkeypatch, tmp_path: Path, *, log: str, rc: int = 1, ack=None):
    from scripts.lib import deploy_on_main as DM
    from scripts.lib import deploy_delegation_binding as DDB

    calls, receipts = [], []
    monkeypatch.setattr(DM, "main_checks_status", lambda repo, sha: ("green", []))
    monkeypatch.setattr(DM, "checkout_hygiene", lambda repo, sha: (True, {}))
    monkeypatch.setattr(DDB, "issue_ticket", lambda sd, sha: (tmp_path / "ticket", "n"))
    monkeypatch.setattr(DDB, "revoke_ticket", lambda t: None)
    monkeypatch.setattr(DM, "current_pin_sha", lambda *a, **k: "cur000000")
    monkeypatch.setattr(DM, "write_receipt", lambda **kw: receipts.append(kw))
    monkeypatch.setattr(DM, "track_outcome", lambda *a, **k: None)
    monkeypatch.setattr(DM, "run_post_release_tester", lambda repo, dry_run=False: (0, "ok"))
    monkeypatch.setattr(DM, "hold_acknowledged", lambda did, since=None: ack)

    def deploy(repo, sha, dry_run=False, extra_env=None):
        calls.append(sha)
        return rc, log
    monkeypatch.setattr(DM, "run_deploy_script", deploy)
    return DM, calls, receipts


def _tick(DM, sd: Path, sha: str) -> dict:
    dec = DM.PollDecision("promote", "main_ahead_of_current", main_sha=sha, current_sha="cur000000")
    return DM._deploy_under_lock(Path("."), dec, {}, sd, dry_run=False)


HELD_LOG = "prepare:rc=0\npromote:rc=1\nRELAY_LIVE_SET_HELD diff_id=0123456789abcdef: ...\nERROR: promote held"


def test_poller_latches_a_held_promote_and_does_not_prepare_again(monkeypatch, tmp_path: Path) -> None:
    sd = tmp_path / "rw"
    DM, calls, receipts = _poller(monkeypatch, tmp_path, log=HELD_LOG)
    first = _tick(DM, sd, "a" * 40)
    assert first["outcome"] == "held_relay_live_set" and first["diff_id"] == "0123456789abcdef"
    assert calls == ["a" * 40] and receipts[-1]["outcome"] == "held_relay_live_set"
    assert DM.load_hold(sd)["status"] == "held"
    for _ in range(3):  # later 2-minute ticks: no prepare, no new release dir, no deploy_failed alert streak
        again = _tick(DM, sd, "a" * 40)
        assert again["outcome"] == "held_relay_live_set"
    assert calls == ["a" * 40]
    assert receipts[-1]["detail"]["prepare_skipped"] is True


def test_poller_records_the_held_release_for_recompute(monkeypatch, tmp_path: Path) -> None:
    sd = tmp_path / "rw"
    log = HELD_LOG + (" (relay live set would change and the operator has not acknowledged this diff_id — promote held "
                      f"({tmp_path}/rel-a/N8N_RELAY_LIVE_SET_DIFF.json))")
    DM, calls, _ = _poller(monkeypatch, tmp_path, log=log)
    _tick(DM, sd, "a" * 40)
    assert DM.load_hold(sd)["release"] == f"{tmp_path}/rel-a"


def test_poller_resumes_when_the_operator_acknowledges(monkeypatch, tmp_path: Path) -> None:
    sd = tmp_path / "rw"
    DM, calls, _ = _poller(monkeypatch, tmp_path, log=HELD_LOG)
    _tick(DM, sd, "a" * 40)
    DM, calls2, _ = _poller(monkeypatch, tmp_path, log="ok", rc=0, ack={"grant_id": "g-op"})
    assert _tick(DM, sd, "a" * 40)["outcome"] == "verified"
    assert calls2 == ["a" * 40]
    hold = DM.load_hold(sd)
    assert hold["status"] == "acknowledged" and hold["grant_id"] == "g-op"


def test_poller_resumes_when_main_moves(monkeypatch, tmp_path: Path) -> None:
    sd = tmp_path / "rw"
    DM, calls, _ = _poller(monkeypatch, tmp_path, log=HELD_LOG)
    _tick(DM, sd, "a" * 40)
    _tick(DM, sd, "b" * 40)
    assert calls == ["a" * 40, "b" * 40]


def test_poller_real_failure_is_still_a_failure(monkeypatch, tmp_path: Path) -> None:
    sd = tmp_path / "rw"
    DM, calls, receipts = _poller(monkeypatch, tmp_path, log="ERROR: conformance gate failed")
    assert _tick(DM, sd, "a" * 40)["outcome"] == "deploy_failed"
    assert DM.load_hold(sd) == {}


# ── release window: a hold is not a rollback (round-2 review) ─────────────────────────────────────────────────


def test_release_window_records_a_hold_as_held_not_rolled_back(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO / "tests"))
    import test_release_window_20261016 as T

    class HeldHost(T.FakeHost):
        def run_deploy(self, args, env):
            if args[0] == "promote":
                self.calls.append(("deploy", tuple(args), None, None, None))
                return 1, "RELAY_LIVE_SET_HELD diff_id=0123456789abcdef: not acknowledged\nERROR: promote held"
            return super().run_deploy(args, env)

    host = HeldHost(tmp_path)
    r = T.runner(tmp_path, host)
    code, rec = r.run("1200")
    assert rec["outcome"] == "STOP_RELAY_LIVE_SET_HELD" and code == T.RW.EXIT_STOPPED
    assert rec["promote"]["relay_live_set_diff_id"] == "0123456789abcdef"
    assert "rollback" not in rec and [c[1][0] for c in T.deploys(host)] == ["prepare", "promote"]
    assert r.state.read(r.state.latch) in (None, {})  # a hold does not latch release windows shut
