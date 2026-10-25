"""ANCHOR: RELAY_LIVE_LANES_REGISTRY_20261025. Relay live lanes from the lane registry (AGENTS.md 20.4.0 hands-off delivery), 2026-10-25.

Hermetic: temp roots under tmp_path hold a fixture AGENTS.md and copies of the repo's registry + allowlist; the
environment is a plain dict (never os.environ, never a real ~/.config/tradeai file). Lane ids are the only values.
"""
from __future__ import annotations

import ast
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import hands_off_policy as HOP  # noqa: E402
from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_relay_live_lanes as R  # noqa: E402

KEY = R.LIVE_LANES_ENV
PAUSED = R.PAUSED_ENV


def _agents(active: bool) -> str:
    status = "ACTIVE" if active else "PROPOSED"
    return (
        "# AGENTS.md\n\n```\nPolicy-Version:      20.4.0\nStatus:              " + status + "\n"
        "Effective-Date:      " + ("2026-10-25" if active else "PENDING") + "\n```\n\n"
        "| 20.4.0 | 2026-10-25 | " + status + " | MINOR | hands-off | x |\n"
        "| 20.2.0 | 2026-10-24 | ACTIVE | MINOR | prior | x |\n"
    )


def _root(tmp_path: Path, *, active: bool, render: bool = True) -> Path:
    root = tmp_path / "release"
    (root / "config").mkdir(parents=True)
    for rel in (R.REGISTRY_REL, R.ALLOWLIST_REL, R.CUTOVER_POLICY_REL):
        shutil.copyfile(ROOT / rel, root / rel)
    (root / "AGENTS.md").write_text(_agents(active), encoding="utf-8")
    (root / "BUILD_SHA").write_text("f" * 40 + "\n", encoding="utf-8")
    if render:
        assert R.render(root)["ok"] is True
    return root


def _env(tmp_path: Path, **kw: str) -> dict[str, str]:
    env = {"TRADEAI_STATE_ROOT": str(tmp_path / "state")}
    env.update(kw)
    return env


@pytest.fixture(autouse=True)
def _clear_memo():
    R._MEMO.clear()
    yield
    R._MEMO.clear()


def _registry_lanes() -> list[str]:
    reg = json.loads((ROOT / R.REGISTRY_REL).read_text(encoding="utf-8"))
    al = json.loads((ROOT / R.ALLOWLIST_REL).read_text(encoding="utf-8"))
    return R.registry_live_lanes(reg, al)[0]


# ---------------------------------------------------------------- the rule


def test_registry_list_is_live_dispatch_or_native_canary_with_live_arg():
    reg = json.loads((ROOT / R.REGISTRY_REL).read_text(encoding="utf-8"))
    al = {e["lane_id"]: e for e in json.loads((ROOT / R.ALLOWLIST_REL).read_text(encoding="utf-8"))["lanes"]}
    rows = {r["lane_id"]: r for r in reg["lanes"]}
    lanes = _registry_lanes()
    assert lanes, "the current registry has live lanes"
    for lane in lanes:
        row = rows[lane]
        stage = (row.get("scheduler") or {}).get("stage")
        assert al[lane].get("live_arg") is not None
        assert stage in (None, "canary", "cutover")
        if row.get("dispatch") is not None:
            assert row["dispatch"]["mode"] == "live"
        else:
            assert row["scheduler"]["kind"] == "n8n" and stage in ("canary", "cutover")
    for lane, row in rows.items():
        mode = (row.get("dispatch") or {}).get("mode")
        stage = (row.get("scheduler") or {}).get("stage")
        if mode in ("dry_run", "off") or stage == "shadow":
            assert lane not in lanes, lane


def _live_rows():
    reg = json.loads((ROOT / R.REGISTRY_REL).read_text(encoding="utf-8"))
    al = json.loads((ROOT / R.ALLOWLIST_REL).read_text(encoding="utf-8"))
    lane = next(r["lane_id"] for r in reg["lanes"] if (r.get("dispatch") or {}).get("mode") == "live")
    return reg, al, lane


def test_shadow_stage_dry_run_and_off_are_never_live():
    reg, al, lane = _live_rows()
    row = next(r for r in reg["lanes"] if r["lane_id"] == lane)
    row["scheduler"]["stage"] = "shadow"
    lanes, excluded = R.registry_live_lanes(reg, al)
    assert lane not in lanes and excluded[lane] == "stage_shadow"
    row["scheduler"]["stage"] = "canary"
    row["dispatch"]["mode"] = "dry_run"
    assert lane not in R.registry_live_lanes(reg, al)[0]
    row["dispatch"]["mode"] = "off"
    assert lane not in R.registry_live_lanes(reg, al)[0]


def test_null_live_arg_excludes():
    reg, al, lane = _live_rows()
    for e in al["lanes"]:
        if e["lane_id"] == lane:
            e["live_arg"] = None
    lanes, excluded = R.registry_live_lanes(reg, al)
    assert lane not in lanes and excluded[lane] == "no_allowlist_live_arg"


def test_native_n8n_row_without_stage_is_not_live():
    reg, al, _ = _live_rows()
    native = [r for r in reg["lanes"] if r.get("dispatch") is None and (r.get("scheduler") or {}).get("kind") == "n8n"
              and not (r.get("scheduler") or {}).get("stage")]
    assert native
    lanes = R.registry_live_lanes(reg, al)[0]
    assert not {r["lane_id"] for r in native} & set(lanes)


def test_operator_hold_excludes():
    reg, al, lane = _live_rows()
    pol = {"families": {}, "holds": {lane: "operator hold for test"}, "p1_last": frozenset(),
           "cron_overlap_trading_days": 0}
    lanes, excluded = R.registry_live_lanes(reg, al, cutover_policy=pol)
    assert lane not in lanes and excluded[lane].startswith("not_dispatch_eligible:operator_hold")


# ---------------------------------------------------------------- gate


def test_policy_not_active_is_exactly_the_legacy_parse(tmp_path):
    root = _root(tmp_path, active=False)
    assert R.resolve(_env(tmp_path, **{KEY: "a b  c"}), root)["lanes"] == frozenset({"a", "b", "c"})
    assert R.resolve(_env(tmp_path, **{KEY: ""}), root)["lanes"] == frozenset()
    assert R.resolve(_env(tmp_path), root)["lanes"] is None
    # the pause key and ops overrides do nothing before ratification
    res = R.resolve(_env(tmp_path, **{KEY: "a", PAUSED: "a"}), root)
    assert res["lanes"] == frozenset({"a"}) and res["source"] == "host_env_legacy"


def test_policy_read_has_no_env_override(tmp_path):
    root = _root(tmp_path, active=False)
    env = _env(tmp_path, **{KEY: "x", "TRADEAI_HANDS_OFF_ACTIVE": "1", "AGENTS_POLICY_STATUS": "ACTIVE"})
    assert R.resolve(env, root)["source"] == "host_env_legacy"


def test_active_uses_registry_render(tmp_path):
    root = _root(tmp_path, active=True)
    res = R.resolve(_env(tmp_path, **{KEY: "something-else"}), root)
    assert res["source"] == "registry_render"
    assert res["lanes"] == frozenset(_registry_lanes())


def test_active_without_host_key_is_not_missing(tmp_path):
    root = _root(tmp_path, active=True)
    assert R.resolve(_env(tmp_path), root)["lanes"] == frozenset(_registry_lanes())


# ---------------------------------------------------------------- precedence: pause-only layers


def _write_ops(tmp_path: Path, doc) -> None:
    p = tmp_path / "state" / R.OVERRIDE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")


def test_host_pause_removes(tmp_path):
    root = _root(tmp_path, active=True)
    lane = _registry_lanes()[0]
    res = R.resolve(_env(tmp_path, **{PAUSED: lane}), root)
    assert lane not in res["lanes"] and res["paused"] == [lane]
    assert res["paused_by"]["host_env"] == [lane]


def test_ops_pause_removes_and_union_with_host(tmp_path):
    root = _root(tmp_path, active=True)
    a, b = _registry_lanes()[:2]
    _write_ops(tmp_path, {"schema": R.OVERRIDE_SCHEMA, "paused": {a: {"by": "operator", "reason": "t"}}})
    res = R.resolve(_env(tmp_path, **{PAUSED: b}), root)
    assert a not in res["lanes"] and b not in res["lanes"]
    assert res["paused_by"] == {"ops_controls": [a], "host_env": [b]}


def test_no_layer_can_add_a_lane(tmp_path):
    root = _root(tmp_path, active=True)
    _write_ops(tmp_path, {"schema": R.OVERRIDE_SCHEMA, "paused": {}, "added": {"not-a-registry-lane": {}}})
    res = R.resolve(_env(tmp_path, **{KEY: "not-a-registry-lane", "TRADEAI_N8N_RELAY_LIVE_LANES_ADD": "zz"}), root)
    assert "not-a-registry-lane" not in res["lanes"] and "zz" not in res["lanes"]
    assert res["lanes"] <= frozenset(_registry_lanes())


@pytest.mark.parametrize("doc", ["{not json", json.dumps({"schema": "Other@v1", "paused": {}}),
                                 json.dumps({"schema": R.OVERRIDE_SCHEMA, "paused": ["a"]})])
def test_corrupt_ops_override_fails_closed(tmp_path, doc):
    root = _root(tmp_path, active=True)
    _write_ops(tmp_path, doc)
    res = R.resolve(_env(tmp_path, **{KEY: "a"}), root)
    assert res["lanes"] == frozenset()
    assert "fail closed" in res["detail"]


# ---------------------------------------------------------------- fail-safe fallback


def test_missing_render_falls_back_to_host_list(tmp_path):
    root = _root(tmp_path, active=True, render=False)
    res = R.resolve(_env(tmp_path, **{KEY: "a b"}), root)
    assert res["source"] == "host_env_fallback" and res["lanes"] == frozenset({"a", "b"})
    assert R.resolve(_env(tmp_path), root)["lanes"] is None


def test_stale_render_falls_back(tmp_path):
    root = _root(tmp_path, active=True)
    reg = root / R.REGISTRY_REL
    reg.write_bytes(reg.read_bytes() + b"\n")
    res = R.resolve(_env(tmp_path, **{KEY: "a"}), root)
    assert res["source"] == "host_env_fallback" and res["detail"] == "render_stale"
    assert res["lanes"] == frozenset({"a"})


def test_corrupt_render_falls_back(tmp_path):
    root = _root(tmp_path, active=True)
    (root / R.RENDER_NAME).write_text("{", encoding="utf-8")
    res = R.resolve(_env(tmp_path, **{KEY: "a"}), root)
    assert res["source"] == "host_env_fallback" and res["detail"] == "render_unreadable"


def test_corrupt_registry_renders_nothing(tmp_path):
    root = _root(tmp_path, active=True, render=False)
    (root / R.REGISTRY_REL).write_text("{", encoding="utf-8")
    rep = R.render(root)
    assert rep["ok"] is False and not (root / R.RENDER_NAME).exists()


def test_fallback_still_honours_pause(tmp_path):
    root = _root(tmp_path, active=True, render=False)
    res = R.resolve(_env(tmp_path, **{KEY: "a b", PAUSED: "a"}), root)
    assert res["lanes"] == frozenset({"b"})


def test_render_is_stamped(tmp_path):
    root = _root(tmp_path, active=True)
    doc = json.loads((root / R.RENDER_NAME).read_text(encoding="utf-8"))
    assert doc["schema"] == R.RENDER_SCHEMA and doc["build_sha"] == "f" * 40
    assert len(doc["registry_sha256"]) == 64 and doc["lanes"] == _registry_lanes()


# ---------------------------------------------------------------- consumers


def test_n8n_due_parse_follows_resolve(monkeypatch, tmp_path):
    root = _root(tmp_path, active=True)
    monkeypatch.setattr(R, "ROOT", root)
    monkeypatch.setattr(R.resolve, "__defaults__", (root,))
    assert D.parse_relay_live_lanes(_env(tmp_path)) == frozenset(_registry_lanes())
    assert D.relay_live_lanes_present(_env(tmp_path)) is True


def test_n8n_due_legacy_unchanged_on_repo_root():
    # The repo's own AGENTS.md is below 20.4.0 / not ACTIVE today: the old semantics hold.
    if HOP.policy_state_from_path(ROOT / "AGENTS.md")["active"]:
        pytest.skip("20.4.0 already ACTIVE on this tree")
    assert D.parse_relay_live_lanes({KEY: "x y"}) == frozenset({"x", "y"})
    with pytest.raises(D.RelayLiveLanesMissing):
        D.parse_relay_live_lanes({})
    assert D.relay_live_lanes_present({}) is False


def test_render_cli_check_and_diff(tmp_path, capsys):
    import scripts.render_n8n_relay_live_lanes as CLI

    root = _root(tmp_path, active=True)
    host = tmp_path / "host.env"
    lane = _registry_lanes()[0]
    host.write_text(f"# c\nOTHER_KEY=ignored\n{KEY}={lane} host-only-lane\n", encoding="utf-8")
    assert CLI.main(["--root", str(root), "--diff-host-file", str(host)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["host_only"] == ["host-only-lane"] and lane not in out["registry_only"]
    assert "ignored" not in json.dumps(out)
    assert CLI.main(["--root", str(root), "--check"]) == 0


# ---------------------------------------------------------------- never a secret value


def test_module_reads_only_lane_id_keys():
    """Static: the only environment names this module and the render CLI read are the state root and the two
    lane-id keys; neither reads a file under ~/.config/tradeai (the units load it)."""
    names = set()
    for rel in ("scripts/lib/n8n_relay_live_lanes.py", "scripts/render_n8n_relay_live_lanes.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert ".config/tradeai" not in text.split('"""', 2)[-1], rel
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("environ.get") and node.args:
                a = node.args[0]
                names.add(a.value if isinstance(a, ast.Constant) else ast.unparse(a))
    assert names <= {"TRADEAI_STATE_ROOT", "LIVE_LANES_ENV", "PAUSED_ENV"}, names
    assert R.LIVE_LANES_ENV == D.LIVE_LANES_ENV


def test_hands_off_policy_copy_is_shared():
    # Identical bytes in every 20.4.0 PR (add/add merges cleanly only when identical).
    assert HOP.POLICY_VERSION_TEXT == "20.4.0"


def test_relay_unit_is_restarted_by_deploy_and_train():
    deploy = (ROOT / "scripts/cio_phase2_exact_main_deploy.sh").read_text(encoding="utf-8")
    assert "tradeai-n8n-run-relay.service" in deploy.split('local units="${TRADEAI_CURRENT_BOUND_UNITS:-', 1)[1].split("\n", 1)[0]
    assert 'render_relay_live_lanes "$NEW_RELEASE"' in deploy
    assert deploy.index('render_relay_live_lanes "$NEW_RELEASE"') < deploy.index('run_integrity_hook "$NEW_RELEASE"')
    deleg = json.loads((ROOT / "config/release_train_delegation.example.json").read_text(encoding="utf-8"))
    assert "tradeai-n8n-run-relay.service" in deleg["limits"]["named_services"]
