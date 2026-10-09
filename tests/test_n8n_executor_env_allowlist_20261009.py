"""P7: executor env selection and names-only reporting, with scratch state and fake lanes."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import n8n_run_executor as X

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text(encoding="utf-8"))
LANES = {entry["lane_id"]: entry for entry in DOC["lanes"]}
SIGNERS = {"n8n-pilot-dispatch", "n8n-incident-fanin", "n8n-research-intake-consumer"}
SECRET_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|BEARER", re.I)
SECRET_NAMES = {
    "UNLISTED_API_KEY", "UNLISTED_TOKEN", "UNLISTED_SECRET", "UNLISTED_PASSWORD", "UNLISTED_BEARER",
    "DB_PASSWORD", "TRADEAI_N8N_GATEWAY_HMAC_KEY", "TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS",
    "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N", "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N_PREVIOUS",
    "TRADEAI_N8N_RELAY_BEARER", "TRADEAI_N8N_RELAY_BEARER_PREVIOUS", "N8N_ENCRYPTION_KEY_ESCROW",
}


def environment(mode="enforce"):
    env = {name: "fixture-value-for-" + name for name in SECRET_NAMES | X.CHILD_ENV_BASE_NAMES}
    env.update({"TRADEAI_EXECUTOR_ENV_ALLOWLIST": mode, "UNLISTED_NON_SECRET": "unused",
                "TRADEAI_N8N_GATEWAY_URL": "http://127.0.0.1:18091", "TRADEAI_SERVED_SHA": "fixture"})
    return env


@pytest.mark.parametrize("lane_id", sorted(LANES))
def test_enforce_only_passes_base_and_explicit_lane_names(lane_id):
    # Even the incomplete lanes' candidate lists must obey least privilege when selected for enforcement.
    entry = {**LANES[lane_id], "env_allowlist_mode": "enforce"}
    env = environment()
    before = dict(env)
    seen = X.child_env(env, lane_id, entry)
    assert set(seen) <= X.CHILD_ENV_BASE_NAMES | set(entry["env_names"])
    assert {name for name in seen if SECRET_RE.search(name)} <= set(entry["env_names"])
    assert "UNLISTED_NON_SECRET" not in seen
    assert "TRADEAI_EXECUTOR_ENV_ALLOWLIST" not in seen
    assert env == before
    assert set(seen) & X.CHILD_ENV_BASE_NAMES == X.CHILD_ENV_BASE_NAMES


def test_base_names_are_the_requested_non_secret_set():
    assert X.CHILD_ENV_BASE_NAMES == {
        "PATH", "HOME", "LANG", "TZ", "PROJ", "PY", "TRADEAI_ENV", "TRADEAI_STATE_ROOT",
        "LLM_DEFER_OFFPEAK", "BLIND_REVIEW_LANES", "PYTHONPATH",
    }
    assert not any(SECRET_RE.search(name) for name in X.CHILD_ENV_BASE_NAMES)


def test_dispatch_key_is_declared_only_for_the_three_signers():
    assert {lane for lane, entry in LANES.items() if X.GATEWAY_DISPATCH_KEY_ENV in entry["env_names"]} == SIGNERS
    for lane, entry in LANES.items():
        for mode in ("off", "report", "enforce"):
            child = X.child_env(environment(mode), lane, {**entry, "env_allowlist_mode": "enforce"})
            assert (X.GATEWAY_DISPATCH_KEY_ENV in child) == (lane in SIGNERS)
            assert not (set(child) & {name for name in SECRET_NAMES if name.startswith(("TRADEAI_N8N_", "N8N_"))
                                     and name != X.GATEWAY_DISPATCH_KEY_ENV})


def test_signer_must_explicitly_list_the_key_in_enforce():
    assert X.GATEWAY_DISPATCH_KEY_ENV not in X.child_env(
        environment(), "n8n-pilot-dispatch", {"env_names": [], "env_allowlist_mode": "enforce"})


@pytest.mark.parametrize("lane_id", sorted(LANES))
def test_each_lane_has_valid_names_and_a_source_derivation(lane_id):
    entry = LANES[lane_id]
    assert X.validate_entry(entry) is None
    assert isinstance(entry["env_names"], list)
    assert entry["env_names"] == sorted(set(entry["env_names"]))
    assert entry["env_allowlist_mode"] in {"report", "enforce"}
    assert entry["env_evidence"]
    if entry["env_allowlist_mode"] == "report":
        assert entry["env_report_reason"]


def imported_env_reads(path, visited=None):
    """Static drift guard for the bounded lanes; includes lazy local imports and constant env-name aliases."""
    visited = set() if visited is None else visited
    if path in visited:
        return set()
    visited.add(path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = {target.id: node.value.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                 and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                 for target in node.targets if isinstance(target, ast.Name)}
    reads = set()
    for node in ast.walk(tree):
        key = None
        if isinstance(node, ast.Call) and ast.unparse(node.func) in {
            "os.getenv", "os.environ.get", "os.environ.setdefault", "env.get", "env.setdefault",
        }:
            assert node.args, (path, node.lineno)
            key = node.args[0]
        elif isinstance(node, ast.Subscript) and ast.unparse(node.value) in {"os.environ", "env"}:
            key = node.slice
        if key is not None:
            name = key.value if isinstance(key, ast.Constant) else constants.get(key.id) if isinstance(key, ast.Name) else None
            assert isinstance(name, str), f"unresolved env read in {path.relative_to(ROOT)}:{node.lineno}; keep lane report-only"
            reads.add(name)
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").replace(".", "/")
            if node.level:
                parent = path.parent
                for _ in range(node.level - 1):
                    parent = parent.parent
                module = str((parent / module).relative_to(ROOT))
            modules = [module, *(module + "/" + alias.name for alias in node.names)]
        for module in modules:
            module = module.replace(".", "/")
            for base in (ROOT, ROOT / "scripts", ROOT / "scripts/lib"):
                candidate = base / (module + ".py")
                if candidate.is_file():
                    reads |= imported_env_reads(candidate, visited)
                    break
    return reads


@pytest.mark.parametrize("lane_id", [lane for lane, entry in LANES.items() if entry["env_allowlist_mode"] == "enforce"])
def test_enforcement_ready_inventories_cover_script_and_recursive_import_reads(lane_id):
    entry = LANES[lane_id]
    scripts = [ROOT / token for token in entry["command"] if token.endswith(".py")]
    reads = set().union(*(imported_env_reads(path) for path in scripts))
    if entry.get("lock_kind", "safe_flock") == "safe_flock":
        reads |= {"PROJECT_ROOT", "SAFE_FLOCK_LOG_DIR"}
    assert reads <= X.CHILD_ENV_BASE_NAMES | set(entry["env_names"])


def run_fixture(tmp_path, env, entry_fields=None, runner=None):
    entry = {"lane_id": "fixture-lane", "command": ["true"], "lock": str(tmp_path / "lane.lock"),
             "timeout_s": 5, "dry_run_arg": [], "live_arg": [], "env_names": ["DB_PASSWORD"],
             "env_allowlist_mode": "enforce", **(entry_fields or {})}
    captured = []

    def fake_runner(argv, **kwargs):
        captured.append(kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, "", "")

    row = {"run_id": "run-env-fixture-00000001", "lane_id": entry["lane_id"], "mode": "dry_run"}
    receipt = X.execute(row, entry, env=env, state_root=tmp_path, code_root=tmp_path, runner=runner or fake_runner)
    return receipt, captured


@pytest.mark.parametrize("mode", [None, "report"])
def test_default_report_preserves_legacy_env_and_appends_only_names(tmp_path, mode):
    env = environment("report")
    if mode is None:
        env.pop("TRADEAI_EXECUTOR_ENV_ALLOWLIST")
    receipt, captured = run_fixture(tmp_path, env)
    assert receipt["state"] == "RUN_DONE"
    assert captured == [X.legacy_child_env(env, "fixture-lane")]
    path = tmp_path / X.ENV_ALLOWLIST_REPORT_REL
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["schema"] == X.ENV_ALLOWLIST_REPORT_SCHEMA
    assert report["requested_mode"] == report["effective_mode"] == "report"
    assert report["lane_id"] == "fixture-lane"
    assert report["run_id"] == "run-env-fixture-00000001"
    assert report["dropped_names"] == sorted(set(captured[0]) - X.CHILD_ENV_BASE_NAMES - {"DB_PASSWORD"})
    assert "DB_PASSWORD" not in report["dropped_names"]
    assert "UNLISTED_TOKEN" in report["dropped_names"]
    assert not any(value in path.read_text() for value in env.values() if value.startswith("fixture-value"))
    # One row per run, including runs that would drop no additional names.
    run_fixture(tmp_path, {"PATH": "fixture-path"})
    assert len(path.read_text().splitlines()) == 2
    assert json.loads(path.read_text().splitlines()[1])["dropped_names"] == []


@pytest.mark.parametrize("mode", ["off", "enforce"])
def test_off_and_enforce_do_not_emit_reports(tmp_path, mode):
    env = environment(mode)
    receipt, captured = run_fixture(tmp_path, env)
    assert receipt["state"] == "RUN_DONE"
    assert not (tmp_path / X.ENV_ALLOWLIST_REPORT_REL).exists()
    assert ("UNLISTED_TOKEN" in captured[0]) == (mode == "off")
    assert "DB_PASSWORD" in captured[0]


@pytest.mark.parametrize("fields,reason", [
    ({"env_names": None}, "env_names_missing"),
    ({"env_allowlist_mode": "report", "env_report_reason": "unresolved_dynamic_names"}, "lane_report_only"),
])
def test_unknown_requirements_stay_report_under_global_enforce(tmp_path, fields, reason):
    receipt, captured = run_fixture(tmp_path, environment(), fields)
    assert receipt["state"] == "RUN_DONE"
    assert "UNLISTED_TOKEN" in captured[0]
    report = json.loads((tmp_path / X.ENV_ALLOWLIST_REPORT_REL).read_text())
    assert report["requested_mode"] == "enforce"
    assert report["effective_mode"] == "report"
    assert report["reason"] == reason


def test_enforce_refuses_invalid_global_mode_without_spawning(tmp_path):
    receipt, captured = run_fixture(tmp_path, environment("typo-secret-value"))
    assert receipt["state"] == "RUN_REFUSED"
    assert receipt["reason"] == "bad_env_allowlist_mode"
    assert captured == []
    assert "typo-secret-value" not in json.dumps(receipt)


def test_report_write_failure_refuses_without_spawning_or_leaking(tmp_path):
    path = tmp_path / X.ENV_ALLOWLIST_REPORT_REL
    path.parent.mkdir(parents=True)
    path.mkdir()
    receipt, captured = run_fixture(tmp_path, environment("report"))
    assert receipt["state"] == "RUN_REFUSED"
    assert receipt["reason"] == "env_allowlist_report:IsADirectoryError"
    assert captured == []
    assert "fixture-value" not in json.dumps(receipt)


@pytest.mark.parametrize("fields,reason", [
    ({"env_names": "DB_PASSWORD"}, "bad_env_names"),
    ({"env_names": ["DB_PASSWORD", "DB_PASSWORD"]}, "bad_env_names"),
    ({"env_names": ["BAD-NAME"]}, "bad_env_names"),
    ({"env_names": [1]}, "bad_env_names"),
    ({"env_allowlist_mode": "off"}, "bad_lane_env_allowlist_mode"),
    ({"env_names": ["TRADEAI_N8N_RELAY_BEARER"]}, "forbidden_env_name"),
    ({"env_names": [X.GATEWAY_DISPATCH_KEY_ENV]}, "forbidden_env_name"),
])
def test_malformed_env_policy_is_refused(tmp_path, fields, reason):
    entry = {"lane_id": "fixture-lane", "command": ["true"], "lock": str(tmp_path / "lock"),
             "timeout_s": 5, "dry_run_arg": [], **fields}
    assert X.validate_entry(entry) == reason
    receipt, captured = run_fixture(tmp_path, environment(), fields)
    assert receipt["state"] == "RUN_REFUSED"
    assert receipt["reason"] == reason
    assert captured == []


def test_real_child_process_gets_no_unlisted_secrets(tmp_path):
    script = tmp_path / "dump_env.py"
    output = tmp_path / "child.json"
    script.write_text("import os,json,sys\nopen(sys.argv[1], 'w').write(json.dumps(dict(os.environ)))\n")
    env = environment()
    env["PATH"] = "/usr/bin:/bin"
    receipt, _ = run_fixture(tmp_path, env, {
        "command": [sys.executable, str(script), str(output)], "lock_kind": "flock",
        "env_names": ["DB_PASSWORD"],
    }, runner=X._subprocess_runner)
    assert receipt["state"] == "RUN_DONE"
    seen = json.loads(output.read_text())
    assert {name for name in seen if SECRET_RE.search(name)} == {"DB_PASSWORD"}
    assert not (set(seen) & {"UNLISTED_NON_SECRET", "TRADEAI_EXECUTOR_ENV_ALLOWLIST"})


def test_report_schema_is_classified_and_gate_registered():
    classification = json.loads((ROOT / "config/cio_surface_classification.json").read_text())
    row = next(row for row in classification["entries"] if row["name"] == "schema:" + X.ENV_ALLOWLIST_REPORT_SCHEMA)
    assert row["classification"] == "NOT_OPERATOR_RELEVANT"
    assert row["owner_hint"] == "scripts/n8n_run_executor.py"
    assert row["producer_path"] == "scripts/n8n_run_executor.py"
    source = (ROOT / "scripts/run_cio_hardening_ci.py").read_text()
    assert "# ANCHOR: N8N_AGENT_GATE_EXECUTOR_ENV" in source
    assert "tests/test_n8n_executor_env_allowlist_20261009.py" in source


def test_external_classification_requires_a_real_schema_definition(tmp_path):
    from scripts.cio_completeness_measurement import schema_definitions

    (tmp_path / "config").mkdir()
    (tmp_path / "scripts").mkdir()
    producer = tmp_path / "scripts/executor.py"
    producer.write_text('REPORT_SCHEMA = "FixtureEnvReport@v1"\nOTHER_SCHEMA = "UnclassifiedOther@v1"\n')
    classification = {"entries": [{"name": "schema:FixtureEnvReport@v1", "kind": "schema",
                                   "producer_path": "scripts/executor.py"}]}
    (tmp_path / "config/cio_surface_classification.json").write_text(json.dumps(classification))
    defined, _ = schema_definitions(tmp_path)
    assert defined == {"FixtureEnvReport@v1": ["scripts/executor.py"]}
    producer.write_text('REPORT_SCHEMA = "RenamedReport@v1"\n')
    assert schema_definitions(tmp_path)[0] == {}
    producer.write_text('_CATALOG = [{"schema": "FixtureEnvReport@v1"}]\n')
    assert schema_definitions(tmp_path) == ({}, {"FixtureEnvReport@v1": ["scripts/executor.py"]})


@pytest.mark.parametrize("source", ["../outside.py", "/tmp/outside.py", "missing.py", "scripts/missing.py"])
def test_external_classification_does_not_expand_to_unsafe_or_missing_sources(tmp_path, source):
    from scripts.cio_completeness_measurement import schema_definitions

    (tmp_path / "config").mkdir()
    (tmp_path / "config/cio_surface_classification.json").write_text(json.dumps({"entries": [
        {"name": "schema:FixtureEnvReport@v1", "kind": "schema", "producer_path": source},
    ]}))
    assert schema_definitions(tmp_path)[0] == {}
