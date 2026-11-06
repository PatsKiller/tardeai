"""n8n program 0.1a (2026-11-06): the production n8n compose lives in the repo, and its cutover is guarded.

ANCHOR: N8N_COMPOSE_CUTOVER_20261106

Hermetic: docker is a fake runner; nothing is started, no network, no database.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ops"))

import n8n_compose_cutover as cut  # noqa: E402

COMPOSE = ROOT / "ops" / "n8n" / "docker-compose.n8n.yml"
H_N8N, H_DB = "a" * 64, "b" * 64
GW = ".".join(["198", "51", "100", "7"])  # synthetic (TEST-NET-2), assembled so no address sits in git
GOOD_ENV = f"N8N_PG_PASSWORD=a\nN8N_ENCRYPTION_KEY=b\nN8N_RELAY_GATEWAY={GW}\n"


def _doc() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


# ---- the compose file --------------------------------------------------------------------------------------------


def test_compose_keeps_the_project_name_volumes_and_network():
    d = _doc()
    assert d["name"] == "m8m-n8n"  # the name picks the existing volumes m8m-n8n_n8n-pg / m8m-n8n_n8n-data
    assert set(d["volumes"]) == {"n8n-pg", "n8n-data"}
    assert set(d["networks"]) == {"lab"}
    assert d["services"]["n8n"]["volumes"] == ["n8n-data:/home/node/.n8n"]
    assert d["services"]["n8n-db"]["volumes"] == ["n8n-pg:/var/lib/postgresql/data"]
    assert d["services"]["n8n"]["ports"] == ["127.0.0.1:5678:5678"]


def test_compose_pins_the_images():
    d = _doc()
    assert d["services"]["n8n"]["image"] == "n8nio/n8n:2.43.0"
    assert d["services"]["n8n-db"]["image"] == "postgres:16.15-alpine"


def test_compose_has_no_literal_secret():
    d = _doc()
    envs = {**d["services"]["n8n"]["environment"], **d["services"]["n8n-db"]["environment"]}
    for k, v in envs.items():
        if re.search(r"PASSWORD|SECRET|TOKEN|ENCRYPTION_KEY", k):
            assert re.fullmatch(r"\$\{[A-Z0-9_]+:\?[^}]*\}", str(v)), k
    refs = set(re.findall(r"\$\{([A-Z0-9_]+)", COMPOSE.read_text(encoding="utf-8")))
    assert refs == set(cut.ENV_KEYS)


def test_compose_holds_no_network_address():
    text = COMPOSE.read_text(encoding="utf-8")
    ips = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text))
    assert ips <= {"127.0.0.1", "0.0.0.0"}  # loopback and the in-container listen address only
    assert _doc()["services"]["n8n"]["extra_hosts"] == [
        "tradeai-relay:${N8N_RELAY_GATEWAY:?N8N_RELAY_GATEWAY is not set; see ops/n8n/README.md}"]


def test_nodes_exclude_is_a_json_array_without_the_types_active_workflows_use():
    raw = _doc()["services"]["n8n"]["environment"]["NODES_EXCLUDE"]
    types = json.loads(raw)
    assert isinstance(types, list) and len(types) > 100
    used = {"code", "httpRequest", "if", "scheduleTrigger", "set", "wait", "noOp", "errorTrigger", "executeWorkflow"}
    assert not {f"n8n-nodes-base.{t}" for t in used} & set(types)
    assert "n8n-nodes-base.executeCommand" in types


def test_env_example_names_only_the_three_keys():
    text = (ROOT / "ops" / "n8n" / "n8n.env.example").read_text(encoding="utf-8")
    pairs = [ln.split("=", 1) for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert pairs == [[k, "replace-me"] for k in cut.ENV_KEYS]


# ---- the env file ------------------------------------------------------------------------------------------------


def _write(p: Path, text: str, mode: int = 0o600) -> Path:
    p.write_text(text, encoding="utf-8")
    os.chmod(p, mode)
    return p


def _gw_run(value):
    def run(argv):
        assert argv[:3] == ["docker", "network", "inspect"] and argv[3] == "m8m-n8n_lab"
        return subprocess.CompletedProcess(argv, 0, value + "\n", "")
    return run


def test_prepare_env_copies_only_the_two_secrets_and_the_live_gateway_at_0600(tmp_path):
    old = _write(tmp_path / "old.env", "KESTRA_PASSWORD=k\nN8N_PG_PASSWORD=pgv\nN8N_ENCRYPTION_KEY=ekv\nLAB_GATEWAY_TOKEN=t\n")
    new = tmp_path / "cfg" / "n8n.env"
    out = cut.prepare_env(old, new, _gw_run(GW))
    assert out["ok"] and out["written"]
    assert new.read_text() == f"N8N_PG_PASSWORD=pgv\nN8N_ENCRYPTION_KEY=ekv\nN8N_RELAY_GATEWAY={GW}\n"
    assert stat.S_IMODE(new.stat().st_mode) == 0o600
    assert stat.S_IMODE(new.parent.stat().st_mode) == 0o700
    assert "pgv" not in json.dumps(out) and "ekv" not in json.dumps(out)
    assert cut.env_file_problems(new) == []
    again = cut.prepare_env(old, new, _gw_run(GW))  # idempotent, no rewrite
    assert again["ok"] and not again["written"]


def test_prepare_env_refuses_an_unreadable_gateway(tmp_path):
    old = _write(tmp_path / "old.env", "N8N_PG_PASSWORD=a\nN8N_ENCRYPTION_KEY=b\n")
    new = tmp_path / "n8n.env"
    out = cut.prepare_env(old, new, _gw_run("<no value>"))
    assert out["ok"] is False and not new.exists()


def test_prepare_env_never_overwrites_a_different_file(tmp_path):
    old = _write(tmp_path / "old.env", "N8N_PG_PASSWORD=a\nN8N_ENCRYPTION_KEY=b\n")
    new = _write(tmp_path / "n8n.env", "N8N_PG_PASSWORD=x\nN8N_ENCRYPTION_KEY=y\n")
    out = cut.prepare_env(old, new, _gw_run(GW))
    assert out["ok"] is False and new.read_text() == "N8N_PG_PASSWORD=x\nN8N_ENCRYPTION_KEY=y\n"


def test_env_file_problems(tmp_path):
    assert cut.env_file_problems(tmp_path / "nope.env")[0].startswith("env file missing")
    loose = _write(tmp_path / "loose.env", GOOD_ENV, 0o644)
    assert any("mode" in p for p in cut.env_file_problems(loose))
    extra = _write(tmp_path / "extra.env", GOOD_ENV + "KESTRA_PASSWORD=c\n")
    assert any("KESTRA_PASSWORD" in p for p in cut.env_file_problems(extra))
    short = _write(tmp_path / "short.env", "N8N_PG_PASSWORD=a\n")
    assert any("N8N_ENCRYPTION_KEY" in p for p in cut.env_file_problems(short))
    assert any("N8N_RELAY_GATEWAY" in p for p in cut.env_file_problems(short))
    assert cut.env_file_problems(_write(tmp_path / "good.env", GOOD_ENV)) == []


# ---- dry run and apply against a fake docker ----------------------------------------------------------------------


class FakeDocker:
    def __init__(self, repo=(H_N8N, H_DB), live=(H_N8N, H_DB), active=("17", "17"), up_rc=0):
        self.repo, self.live, self.active, self.up_rc = repo, live, list(active), up_rc
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if "shell" in argv:
            raise AssertionError("no shell")
        if argv[:2] == ["docker", "compose"] and "config" in argv:
            return subprocess.CompletedProcess(argv, 0, f"n8n {self.repo[0]}\nn8n-db {self.repo[1]}\n", "")
        if argv[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(argv, 0, (self.live[0] if argv[2] == "m8m-n8n" else self.live[1]) + "\n", "")
        if argv[:2] == ["docker", "exec"]:
            val = self.active.pop(0) if len(self.active) > 1 else self.active[0]
            return subprocess.CompletedProcess(argv, 0, f"{val}\n", "")
        if argv[:2] == ["docker", "compose"] and "up" in argv:
            return subprocess.CompletedProcess(argv, self.up_rc, "", "")
        raise AssertionError(f"unexpected call {argv}")

    def ups(self):
        return [c for c in self.calls if "up" in c]


@pytest.fixture
def env(tmp_path):
    return _write(tmp_path / "n8n.env", GOOD_ENV)


def test_dry_run_passes_when_the_hashes_match(env):
    fd = FakeDocker()
    out = cut.plan(env, fd)
    assert out["ok"] and out["problems"] == [] and out["active_workflows"] == 17
    assert fd.ups() == []
    cfg = next(c for c in fd.calls if "config" in c)
    assert cfg[cfg.index("-p") + 1] == "m8m-n8n" and str(cut.REPO_COMPOSE) in cfg


def test_dry_run_refuses_a_changed_service(env):
    out = cut.plan(env, FakeDocker(repo=("c" * 64, H_DB)))
    assert not out["ok"] and any(p.startswith("n8n:") for p in out["problems"])


def test_dry_run_refuses_a_missing_container(env):
    out = cut.plan(env, FakeDocker(live=("", H_DB)))
    assert not out["ok"] and any("no running container" in p for p in out["problems"])


def test_apply_refuses_without_a_passing_dry_run(env, tmp_path):
    fd = FakeDocker(repo=("c" * 64, H_DB))
    out = cut.apply(env, tmp_path / "r.json", fd, healthy=lambda: True)
    assert out["ok"] is False and out["refused"] and fd.ups() == []


def test_apply_recreates_only_n8n_and_checks_the_count(env, tmp_path):
    fd = FakeDocker()
    out = cut.apply(env, tmp_path / "r.json", fd, healthy=lambda: True)
    assert out["ok"] and out["active_before"] == out["active_after"] == 17
    (up,) = fd.ups()
    assert up[-4:] == ["-d", "--no-deps", "--force-recreate", "n8n"][-4:] and up[-1] == "n8n"
    assert json.loads((tmp_path / "r.json").read_text())["ok"] is True


def test_apply_fails_when_a_workflow_goes_inactive(env, tmp_path):
    out = cut.apply(env, tmp_path / "r.json", FakeDocker(active=("17", "16")), healthy=lambda: True)
    assert out["ok"] is False and out["active_after"] == 16


def test_apply_fails_when_n8n_is_not_healthy(env, tmp_path):
    out = cut.apply(env, tmp_path / "r.json", FakeDocker(), healthy=lambda: False)
    assert out["ok"] is False and out["healthy"] is False


def test_this_file_is_registered_in_a_ci_gate():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.lib import ci_gates  # noqa: PLC0415 -- needs ROOT on sys.path first

    assert "tests/test_n8n_compose_cutover_20261106.py" in ci_gates.registry_text(ROOT)
