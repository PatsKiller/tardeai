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
    rep = G.compute(new, served, env)
    assert rep["changed"] is True and rep["new"]["source"] == "host_env_legacy"
    ok, why = G.gate(rep, Path(env["TRADEAI_STATE_ROOT"]))
    assert (ok, why) == (False, "unacknowledged")


def test_unchanged_set_passes_the_gate(tmp_path: Path, env: dict) -> None:
    rep = G.compute(_root(tmp_path, "new", build="b" * 40), _root(tmp_path, "served"), env)
    assert rep["changed"] is False and rep["added"] == rep["removed"] == []
    assert G.gate(rep, Path(env["TRADEAI_STATE_ROOT"])) == (True, "unchanged")


def test_a_dropped_lane_holds_until_that_exact_change_is_acked(tmp_path: Path, env: dict) -> None:
    served = _root(tmp_path, "served")
    lane = json.loads((served / RLL.RENDER_NAME).read_text())["lanes"][0]
    new = _root(tmp_path, "new", build="b" * 40, drop_live_arg=lane)
    state = Path(env["TRADEAI_STATE_ROOT"])
    rep = G.compute(new, served, env)
    assert rep["removed"] == [lane] and rep["added"] == []
    assert rep["exclusions"][lane]["reason"] == "no_allowlist_live_arg"
    assert G.gate(rep, state) == (False, "unacknowledged")
    # an ack for another build of the same delta does not count
    G.record_ack(state, {**rep, "new_build": "c" * 40, "diff_id": G.diff_id("c" * 40, [], [lane])}, "operator")
    assert G.gate(rep, state)[0] is False
    G.record_ack(state, rep, "operator")
    assert G.gate(rep, state) == (True, "acknowledged")


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


def test_page_names_the_delta_and_the_ack(tmp_path: Path, env: dict) -> None:
    served = _root(tmp_path, "served")
    lane = json.loads((served / RLL.RENDER_NAME).read_text())["lanes"][0]
    rep = G.compute(_root(tmp_path, "new", build="b" * 40, drop_live_arg=lane), served, env)
    sent = []
    out = G.notify(rep, "ACK-CMD", sender=lambda msg, **kw: sent.append((msg, kw)) or True)
    assert out == {"accepted": True}
    msg, kw = sent[0]
    assert lane in msg and "ACK-CMD" in msg and "-1 lanes" in msg
    assert kw["producer"] == "relay_live_set_gate" and kw["priority"] == "P1"


def test_cli_gate_exit_codes_and_ack(tmp_path: Path, env: dict) -> None:
    served = _root(tmp_path, "served")
    lane = json.loads((served / RLL.RENDER_NAME).read_text())["lanes"][0]
    new = _root(tmp_path, "new", build="b" * 40, drop_live_arg=lane)
    cli = [sys.executable, str(REPO / "scripts" / "relay_live_set_gate.py")]
    common = ["--release", str(new), "--served", str(served), "--host-file", str(tmp_path / "absent.env")]
    run_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TRADE_AI_CI": "1", **env}
    diff = subprocess.run(cli + ["diff", *common, "--write", "--notify"], capture_output=True, text=True, env=run_env, timeout=60)
    assert diff.returncode == 0 and "WARN relay live set would change" in diff.stderr
    assert json.loads((new / G.DIFF_NAME).read_text())["removed"] == [lane]
    held = subprocess.run(cli + ["gate", *common], capture_output=True, text=True, env=run_env, timeout=60)
    assert held.returncode == 3 and "REFUSED" in held.stderr
    ack = subprocess.run(cli + ["ack", *common, "--by", "operator"], capture_output=True, text=True, env=run_env, timeout=60)
    assert ack.returncode == 0 and json.loads(ack.stdout)["acked"] is True
    assert subprocess.run(cli + ["gate", *common], capture_output=True, text=True, env=run_env, timeout=60).returncode == 0


def test_host_file_reads_only_the_two_lane_keys(tmp_path: Path) -> None:
    f = tmp_path / "lanes.env"
    f.write_text("SOME_TOKEN=do-not-read\nTRADEAI_N8N_RELAY_LIVE_LANES=a b\nTRADEAI_N8N_RELAY_LIVE_LANES_PAUSED='c'\n")
    assert G.host_env(f) == {"TRADEAI_N8N_RELAY_LIVE_LANES": "a b", "TRADEAI_N8N_RELAY_LIVE_LANES_PAUSED": "c"}


def test_deploy_wires_diff_at_prepare_and_gate_before_activation() -> None:
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
