"""Qualification uses actual emitter/validator with fake command effects only.

All written attestations are hermetic test fixtures, never operational proof.
No core subprocess, socket probe, Git configuration change or runtime effect runs.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from scripts import emit_sop_runtime_attestation as emitter
from scripts.lib import sop_evidence_integrity as evidence
from scripts.lib import sop_toolchain as tools


@pytest.fixture
def environment(tmp_path, monkeypatch):
    ruff = tmp_path / "fixture-ruff"
    ruff.touch()
    versions = {
        "python": "3.14.4",
        "pinned_ruff": "0.16.2",
        "ruff": "0.16.2",
        "ruff_raw": "ruff 0.16.2",
        "shellcheck": "0.11.0",
        "shellcheck_raw": "version: 0.11.0",
    }
    monkeypatch.setattr(tools, "collect_tool_versions", lambda root=None: dict(versions))
    monkeypatch.setattr(tools, "resolve_ruff_bin", lambda root=None: ruff)
    monkeypatch.setattr(emitter, "collect_tool_versions", lambda root=None: dict(versions))
    monkeypatch.setattr(emitter, "_docs_index_fingerprint", lambda: "f" * 12)
    real_git = emitter._git
    monkeypatch.setattr(emitter, "_git", lambda args: "" if args == ["status", "--porcelain"] else real_git(args))
    calls = []

    def runner(command):
        calls.append(command)
        return 0

    monkeypatch.setattr(emitter, "_run", runner)
    return calls


def producer():
    return emitter.build_attestation(run_commands=True, base_sha=emitter._git(["rev-parse", "HEAD"]))


@pytest.mark.parametrize(
    "failed_command",
    [
        "tests/test_agent_file_lease_canonical.py",
        "tests/test_sop_evidence_integrity.py",
        "scripts/validate_sop_evidence_integrity.py",
        "scripts/report_docs_inventory.py",
        "shellcheck",
    ],
)
def test_actual_main_does_not_qualify_a_failed_mandatory_command(
    tmp_path, monkeypatch, capsys, environment, failed_command
):
    def runner(command):
        environment.append(command)
        return 1 if failed_command in command else 0

    monkeypatch.setattr(emitter, "_run", runner)
    out = tmp_path / "NOT_OPERATIONAL_PROOF"
    result = emitter.main(["--out-dir", str(out), "--base-sha", emitter._git(["rev-parse", "HEAD"])])
    record = json.loads((out / "runtime-attestation.json").read_text())
    assert len(environment) == 5
    assert [row["exit"] for row in record["commands"]].count(1) == 1
    printed = capsys.readouterr().out
    summary = json.loads(printed[printed.index("{") :])
    assert result != 0 and summary["ok"] is False, "failed mandatory command must fail actual CLI qualification"


def test_actual_main_schema_only_artifact_is_diagnostic_not_qualified(tmp_path, capsys, environment):
    out = tmp_path / "DIAGNOSTIC_NOT_OPERATIONAL_PROOF"
    result = emitter.main(["--out-dir", str(out), "--skip-commands", "--base-sha", emitter._git(["rev-parse", "HEAD"])])
    record = json.loads((out / "runtime-attestation.json").read_text())
    assert record["commands"] == [] and environment == []
    printed = capsys.readouterr().out
    summary = json.loads(printed[printed.index("{") :])
    assert result != 0 and summary["ok"] is False, "schema-only output is not proof of mandatory checks"


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "empty",
        "duplicate",
        "failed_then_duplicate_pass",
        "unknown_exit",
        "missing_exit",
        "string_exit",
        "bool_exit",
        "float_exit",
        "skipped",
        "unknown_skip",
        "expected_failure",
        "missing_expected",
        "bool_expected",
        "commands_object",
        "non_object_record",
    ],
)
def test_shared_validator_refuses_unproven_mandatory_command_results(environment, case):
    record = producer()
    core = record["commands"][0]
    assert core["name"] == "pytest_core" and core["exit"] == 0 and core["expected"] == 0
    if case == "missing":
        record["commands"].pop(0)
    elif case == "empty":
        record["commands"] = []
    elif case in {"duplicate", "failed_then_duplicate_pass"}:
        record["commands"].append(copy.deepcopy(core))
        if case == "failed_then_duplicate_pass":
            core["exit"] = 1
    elif case == "unknown_exit":
        core["exit"] = None
    elif case == "missing_exit":
        core.pop("exit")
    elif case == "string_exit":
        core["exit"] = "0"
    elif case == "bool_exit":
        core["exit"] = False
    elif case == "float_exit":
        core["exit"] = 0.0
    elif case == "skipped":
        core["skipped"] = True
    elif case == "unknown_skip":
        core["skipped"] = None
    elif case == "expected_failure":
        core.update(exit=1, expected=1)
    elif case == "missing_expected":
        core.pop("expected")
    elif case == "bool_expected":
        core["expected"] = False
    elif case == "commands_object":
        record["commands"] = {"pytest_core": core}
    elif case == "non_object_record":
        record["commands"].append("unknown command evidence")
    assert evidence.validate_runtime_attestation(record, root=emitter.ROOT), (
        "shared consumer must refuse missing, conflicting or unproven mandatory outcomes"
    )


def test_actual_complete_v1_producer_and_main_remain_qualified(tmp_path, capsys, environment):
    record = producer()
    assert record["schema"] == "SopRuntimeAttestation@v1"
    assert len(record["commands"]) == 5 and evidence.validate_runtime_attestation(record, root=emitter.ROOT) == []
    environment.clear()
    out = tmp_path / "VALID_HERMETIC_FIXTURE_NOT_OPERATIONAL_PROOF"
    assert emitter.main(["--out-dir", str(out), "--base-sha", emitter._git(["rev-parse", "HEAD"])]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed[printed.index("{") :])["ok"] is True


def old_module(tmp_path, relative):
    """Execute the actual pinned prior module, not a copied compatibility reader."""
    raw = subprocess.check_output(
        ["git", "show", "7af14c7782cf7ab0cba261cc25e6789fe810b092:" + relative], cwd=emitter.ROOT
    )
    path = tmp_path / Path(relative).name
    path.write_bytes(raw)
    spec = importlib.util.spec_from_file_location("actual_prior_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_old_complete_v1_producer_passes_new_qualifier(tmp_path, monkeypatch, environment):
    old = old_module(tmp_path, "scripts/emit_sop_runtime_attestation.py")
    monkeypatch.setattr(old, "ROOT", emitter.ROOT)
    monkeypatch.setattr(old, "_run", emitter._run)
    monkeypatch.setattr(old, "_git", emitter._git)
    monkeypatch.setattr(old, "_docs_index_fingerprint", emitter._docs_index_fingerprint)
    record = old.build_attestation(run_commands=True, base_sha=emitter._git(["rev-parse", "HEAD"]))
    assert record["schema"] == "SopRuntimeAttestation@v1"
    assert evidence.validate_runtime_attestation(record, root=emitter.ROOT) == []


def test_actual_new_complete_v1_producer_remains_readable_by_old_consumer(tmp_path, environment):
    old = old_module(tmp_path, "scripts/lib/sop_evidence_integrity.py")
    assert old.validate_runtime_attestation(producer(), root=emitter.ROOT) == []


def test_actual_legacy_schema_only_v1_record_remains_readable_but_unproven(tmp_path, monkeypatch, environment):
    old = old_module(tmp_path, "scripts/emit_sop_runtime_attestation.py")
    monkeypatch.setattr(old, "ROOT", emitter.ROOT)
    monkeypatch.setattr(old, "_git", emitter._git)
    record = old.build_attestation(run_commands=False, base_sha=emitter._git(["rev-parse", "HEAD"]))
    assert json.loads(json.dumps(record))["schema"] == "SopRuntimeAttestation@v1"
    errors = evidence.validate_runtime_attestation(record, root=emitter.ROOT)
    assert set(errors) == {"ATTESTATION_COMMAND_MISSING:" + name for name in evidence.REQUIRED_RUNTIME_COMMANDS}


def test_actual_producer_covers_the_shared_mandatory_command_catalogue(environment):
    assert tuple(row["name"] for row in producer()["commands"]) == evidence.REQUIRED_RUNTIME_COMMANDS
