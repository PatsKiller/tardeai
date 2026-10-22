"""Actual canonical shell functions with temporary artifacts, fake control effects and real receipt writer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest

ROOT = Path(os.environ.get("RELEASE_RECEIPT_SOURCE_ROOT") or Path(__file__).resolve().parents[1])
SOURCE = ROOT / "scripts/cio_phase2_exact_main_deploy.sh"
OLD = "a" * 40
NEW = "b" * 40


def artifact(root: Path, name: str, sha: str):
    path = root / name
    (path / ".venv/bin").mkdir(parents=True)
    for pin in ["BUILD_SHA", "GIT_SHA", "SOURCE_COMMIT"]:
        (path / pin).write_text(sha + "\n")
    lock = b"fixture requirements, no installation\n"
    (path / "requirements.lock.txt").write_bytes(lock)
    digest = hashlib.sha256(lock).hexdigest()
    vid = "py3.14.4-" + digest[:12]
    (path / ".venv/.complete").write_text(f"venv_id={vid}\nlock_sha256={digest}\npython_version=3.14.4\n")
    (path / ".venv/bin/python").write_text("# fixture, never executed\n")
    return path


def run_shell(tmp_path, action, *, current=True, bad_pins=False, health_fail=False, activation_misses=False):
    releases = tmp_path / "releases"
    releases.mkdir()
    old = artifact(releases, "old", OLD)
    new = artifact(releases, "new", NEW)
    if current:
        (releases / "CURRENT").symlink_to(new if action == "rollback" else old, target_is_directory=True)
    state = tmp_path / "state"
    state.mkdir()
    # Intent state deliberately remains the most recently prepared release, as in the real faulty receipt.
    (state / "state.env").write_text(
        "\n".join(
            f"{k}={shlex.quote(str(v))}"
            for k, v in {
                "NEW_RELEASE": new,
                "PREV_RELEASE": old,
                "CONTENT_SHA": NEW,
                "RELEASE_VENV_ID": "stale-prepared-venv",
                "RELEASE_VENV_LOCK_SHA256": "c" * 64,
                "RELEASE_VENV_PY_VERSION": "0.0.0",
                "RELEASE_VENV_PYTHON": new / ".venv/bin/python",
                "RELEASE_VENV_ACTION": "reuse",
            }.items()
        )
        + "\n"
    )
    if bad_pins:
        (old / "GIT_SHA").write_text("d" * 40 + "\n")
    prefix = SOURCE.read_text().rsplit('case "$MODE" in', 1)[0]
    lib = 'source "${ROOT}/scripts/lib/release_venv.sh"'
    assert prefix.count(lib) == 1
    prefix = prefix.replace(lib, "source " + shlex.quote(str(ROOT / "scripts/lib/release_venv.sh")))
    fake = tmp_path / "fake-python"
    fake.write_text(
        '#!/bin/sh\ncase "$1" in */release_grant_preflight.py) exit 0;; *) exec /usr/bin/python3 "$@";; esac\n'
    )
    fake.chmod(0o700)
    setup = {
        "ROOT": ROOT,
        "RELEASES_BASE": releases,
        "STATE_DIR": state,
        "STATE_FILE": state / "state.env",
        "RECEIPT_FILE": state / "deploy_receipt.json",
        "CI_RECEIPT_FILE": state / "post_merge_ci.json",
        "VENV_PYTHON": fake,
    }
    extra = "\n".join(f"{k}={shlex.quote(str(v))}" for k, v in setup.items()) + "\n"
    extra += """
release_grant_preflight() { :; }
require_canonical_source_at() { :; }
conformance_gate() { :; }
release_pin_step() { :; }
restart_root_frozen_units() { :; }
write_expected_release_pin() { :; }
worker_pin_check() { :; }
ff_dev_tree_after_promote() { :; }
"""
    extra += (
        "activate_release() { :; }\n"
        if activation_misses
        else 'activate_release() { ln -sfn "$1" "$RELEASES_BASE/CURRENT"; }\n'
    )
    extra += (
        "health_check() { return 1; }\n"
        if health_fail
        else "health_check() { [[ \"$1\" != 'promote' || \"$TEST_PROMOTE_FAIL\" != '1' ]]; }\n"
    )
    extra += "TEST_PROMOTE_FAIL=" + ("1" if action == "auto_rollback" else "0") + "\n"
    if action == "rollback":
        extra += "cmd_rollback " + shlex.quote(str(old)) + "\n"
    elif action == "auto_rollback":
        extra += "cmd_promote " + shlex.quote(str(new)) + "\n"
    elif action == "prepare":
        extra += "load_state\nwrite_deploy_receipt true prepare skipped false prepare_ok\n"
    elif action == "promote":
        extra += "cmd_promote " + shlex.quote(str(new)) + "\n"
    else:
        raise AssertionError(action)
    script = tmp_path / "harness.sh"
    script.write_text(prefix + "\n" + extra)
    process = subprocess.run(
        ["bash", str(script)], env={**os.environ, "CIO_SOURCE_PR": "1854"}, capture_output=True, text=True, timeout=15
    )
    output = state / "deploy_receipt.json"
    return process, json.loads(output.read_text()) if output.exists() else None, old, new, state


@pytest.mark.parametrize("field", ["deployed_sha", "content_sha", "release_dir", "rolled_back", "release_venv"])
def test_actual_manual_rollback_receipt_uses_observed_current_not_prepared_state(tmp_path, field):
    process, receipt, old, new, state = run_shell(tmp_path, "rollback")
    assert process.returncode == 0, process.stdout + process.stderr
    expected = {"deployed_sha": OLD, "content_sha": OLD, "release_dir": str(old), "rolled_back": True}
    if field == "release_venv":
        assert receipt[field]["venv_python"] == str(old / ".venv/bin/python"), (
            "rollback venv metadata must describe the observed artifact"
        )
    else:
        assert receipt[field] == expected[field], f"rollback {field} must describe actual restored CURRENT"


def test_actual_failed_promote_auto_rollback_retains_attempt_and_observed_result(tmp_path):
    process, receipt, old, new, state = run_shell(tmp_path, "auto_rollback")
    assert process.returncode != 0 and receipt["ok"] is False
    assert receipt["deployed_sha"] == OLD and receipt["release_dir"] == str(old)
    assert receipt["rolled_back"] is True
    assert receipt.get("attempted_target", {}).get("sha") == NEW
    assert receipt["attempted_target"]["release_dir"] == str(new)


def test_prepare_without_existing_current_does_not_label_prepared_artifact_deployed(tmp_path):
    process, receipt, old, new, state = run_shell(tmp_path, "prepare", current=False)
    assert process.returncode == 0, process.stdout + process.stderr
    assert receipt["ok"] is True and receipt["deployed_sha"] is None
    assert receipt["release_dir"] is None and receipt["deployed_availability"] == "UNAVAILABLE"
    assert receipt["attempted_target"]["sha"] == NEW


def test_mismatched_current_pins_refuse_successful_rollback_receipt(tmp_path):
    process, receipt, old, new, state = run_shell(tmp_path, "rollback", bad_pins=True)
    assert process.returncode != 0 and receipt and receipt["ok"] is False, (
        "unknown artifact readback cannot produce rollback_ok"
    )
    assert receipt["deployed_sha"] is None and receipt["deployed_availability"] == "UNAVAILABLE"


def test_rollback_activation_that_does_not_move_current_is_not_accepted(tmp_path):
    process, receipt, old, new, state = run_shell(tmp_path, "rollback", activation_misses=True)
    assert process.returncode != 0 and receipt and receipt["ok"] is False
    assert receipt["rolled_back"] is False and receipt["deployed_sha"] == NEW


def test_actual_promote_control_keeps_success_when_target_is_observed(tmp_path):
    process, receipt, old, new, state = run_shell(tmp_path, "promote")
    assert process.returncode == 0, process.stdout + process.stderr
    assert receipt["ok"] is True and receipt["deployed_sha"] == NEW
    assert receipt["release_dir"] == str(new) and receipt["rolled_back"] is False


def governance_reader():
    spec = importlib.util.spec_from_file_location(
        "receipt_governance_reader", ROOT / "scripts/report_lane_governance_packet.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("candidate", [None, NEW, "not-a-full-sha"])
def test_actual_governance_reader_does_not_attribute_unbound_ci_to_observed_release(tmp_path, candidate):
    (tmp_path / "deploy_receipt.json").write_text(json.dumps({"deployed_sha": OLD, "ok": True}))
    ci = {"ok": True, "candidate_sha": candidate}
    (tmp_path / "post_merge_ci.json").write_text(json.dumps(ci))
    result = governance_reader().releases_section(tmp_path, tmp_path)
    assert result["post_merge_ci_ok"] is None, (
        "CI for a different or unknown candidate cannot prove observed release CI"
    )
    assert result.get("post_merge_ci_status") == "UNAVAILABLE"
    assert json.loads((tmp_path / "post_merge_ci.json").read_text()) == ci


def test_actual_governance_reader_preserves_exact_ci_binding_control(tmp_path):
    (tmp_path / "deploy_receipt.json").write_text(json.dumps({"deployed_sha": OLD, "ok": True}))
    (tmp_path / "post_merge_ci.json").write_text(json.dumps({"ok": True, "candidate_sha": OLD}))
    assert governance_reader().releases_section(tmp_path, tmp_path)["post_merge_ci_ok"] is True


def receipt_helper():
    spec = importlib.util.spec_from_file_location("exact_receipt_helper", ROOT / "scripts/lib/exact_release_receipt.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_failed_rollback_health_keeps_failure_separate_from_restored_artifact(tmp_path):
    process, receipt, old, new, state = run_shell(tmp_path, "rollback", health_fail=True)
    assert process.returncode != 0 and receipt["ok"] is False
    assert receipt["health"] == "fail" and receipt["deployed_sha"] == OLD
    assert receipt["rolled_back"] is True


def test_missing_observed_venv_is_unavailable_without_reusing_prepare_env(tmp_path):
    helper = receipt_helper()
    base = tmp_path / "releases"
    old = artifact(base, "old", OLD)
    new = artifact(base, "new", NEW)
    (base / "CURRENT").symlink_to(old)
    (old / ".venv/.complete").unlink()
    receipt, valid = helper.build_receipt(
        releases_base=base,
        mode="rollback",
        ok=True,
        health="ok",
        rolled_back=True,
        attempted_dir=str(old),
        attempted_sha=OLD,
        rollback_target=str(old),
        rollback_sha=OLD,
    )
    assert valid and receipt["ok"] is True and receipt["deployed_sha"] == OLD
    assert receipt["release_venv"] is None and receipt["venv_availability"] == "UNAVAILABLE"


@pytest.mark.parametrize("field,value", [("source_pr", None), ("source_pr", "99")])
def test_observed_pr_only_comes_from_exact_artifact_stamp(tmp_path, field, value):
    helper = receipt_helper()
    base = tmp_path / "releases"
    old = artifact(base, "old", OLD)
    (base / "CURRENT").symlink_to(old)
    if value is not None:
        (old / "BUILD_STAMP.json").write_text(json.dumps({"build_sha": OLD, "source_pr": value}))
    receipt, valid = helper.build_receipt(
        releases_base=base,
        mode="promote",
        ok=True,
        health="ok",
        rolled_back=False,
        attempted_dir=str(old),
        attempted_sha=OLD,
        source_pr="1854",
    )
    assert valid and receipt["source_pr"] == value
    assert receipt["attempted_target"]["source_pr"] == "1854"


def test_current_change_during_artifact_readback_is_unknown(tmp_path, monkeypatch):
    helper = receipt_helper()
    base = tmp_path / "releases"
    old = artifact(base, "old", OLD)
    new = artifact(base, "new", NEW)
    current = base / "CURRENT"
    current.symlink_to(old)
    real_read = helper.artifact_identity

    def changing_read(directory, releases_base):
        result = real_read(directory, releases_base)
        if directory == current:
            current.unlink()
            current.symlink_to(new)
        return result

    monkeypatch.setattr(helper, "artifact_identity", changing_read)
    receipt, valid = helper.build_receipt(
        releases_base=base,
        mode="promote",
        ok=True,
        health="ok",
        rolled_back=False,
        attempted_dir=str(new),
        attempted_sha=NEW,
    )
    assert valid is False and receipt["ok"] is False
    assert receipt["deployed_sha"] is None and receipt["deployed_availability"] == "UNAVAILABLE"


def test_atomic_writer_preserves_previous_receipt_if_replace_fails(tmp_path, monkeypatch):
    helper = receipt_helper()
    target = tmp_path / "deploy_receipt.json"
    target.write_bytes(b'{"prior":true}\n')

    def refuse_replace(*args):
        raise OSError("fixture replace refusal")

    monkeypatch.setattr(helper.os, "replace", refuse_replace)
    with pytest.raises(OSError, match="fixture replace refusal"):
        helper.atomic_write(target, {"ok": False})
    assert target.read_bytes() == b'{"prior":true}\n'
    assert sorted(p.name for p in tmp_path.iterdir()) == ["deploy_receipt.json"]


def test_atomic_writer_readers_only_see_complete_old_or_new_json(tmp_path):
    helper = receipt_helper()
    target = tmp_path / "deploy_receipt.json"
    old = {"schema": "old", "payload": "a" * 50000}
    new = {"schema": helper.SCHEMA, "payload": "b" * 50000}
    target.write_text(json.dumps(old))
    with target.open() as already_open:
        helper.atomic_write(target, new)
        assert json.load(already_open) == old
    assert json.loads(target.read_text()) == new
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("schema", [None, "CioExactMainDeployReceipt@v1", "CioExactMainDeployReceipt@v2"])
def test_actual_new_governance_reader_accepts_supported_old_and_new_receipts(tmp_path, schema):
    dep = {"deployed_sha": OLD, "source_pr": None, "release_dir": "observed", "ok": True, "rolled_back": True}
    if schema:
        dep["schema"] = schema
    if schema == "CioExactMainDeployReceipt@v2":
        process, dep, *_ = run_shell(tmp_path, "rollback")
        assert process.returncode == 0
    (tmp_path / "deploy_receipt.json").write_text(json.dumps(dep))
    (tmp_path / "post_merge_ci.json").write_text(json.dumps({"candidate_sha": OLD, "ok": False}))
    result = governance_reader().releases_section(tmp_path, tmp_path)
    assert result["deployed_sha"] == OLD and result["rolled_back"] is True
    assert result["receipt_supported"] is True and result["post_merge_ci_ok"] is False


def complete_v2_receipt(tmp_path):
    helper = receipt_helper()
    base = tmp_path / "releases"
    old = artifact(base, "old", OLD)
    (base / "CURRENT").symlink_to(old)
    dep, valid = helper.build_receipt(
        releases_base=base,
        mode="promote",
        ok=True,
        health="ok",
        rolled_back=False,
        attempted_dir=str(old),
        attempted_sha=OLD,
    )
    assert valid and dep["ok"]
    return dep


@pytest.mark.parametrize(
    "field,value",
    [
        ("deployed_availability", "UNAVAILABLE"),
        ("deployed_availability", None),
        ("content_sha", NEW),
        ("content_sha", None),
        ("content_sha", "__missing__"),
        ("release_dir", "relative/artifact"),
        ("release_dir", None),
        ("release_dir", "__missing__"),
        ("release_dir", "/fixture/../artifact"),
        ("deployed_unavailable_reason", "current_changed"),
        ("deployed_unavailable_reason", "__missing__"),
        ("readback_errors", "__missing__"),
        ("unexpected_future_field", "no_additive_authority_or_meaning"),
    ],
)
def test_actual_complete_v2_malformed_identity_cannot_claim_deployed_ci(tmp_path, field, value):
    dep = complete_v2_receipt(tmp_path)
    if value == "__missing__":
        dep.pop(field)
    else:
        dep[field] = value
    (tmp_path / "deploy_receipt.json").write_text(json.dumps(dep))
    (tmp_path / "post_merge_ci.json").write_text(json.dumps({"candidate_sha": OLD, "ok": True}))
    result = governance_reader().releases_section(tmp_path, tmp_path)
    assert result["post_merge_ci_ok"] is None, "inconsistent or incomplete v2 readback cannot claim deployed CI"
    assert result["post_merge_ci_status"] == "UNAVAILABLE"


def test_actual_new_governance_reader_does_not_accept_unknown_major_ci(tmp_path):
    (tmp_path / "deploy_receipt.json").write_text(
        json.dumps({"schema": "CioExactMainDeployReceipt@v99", "deployed_sha": OLD})
    )
    (tmp_path / "post_merge_ci.json").write_text(json.dumps({"candidate_sha": OLD, "ok": True}))
    result = governance_reader().releases_section(tmp_path, tmp_path)
    assert result["receipt_supported"] is False
    assert result["post_merge_ci_ok"] is None and result["post_merge_ci_status"] == "UNAVAILABLE"


@pytest.mark.parametrize("malformed", [[], "unreadable"])
def test_actual_governance_reader_missing_or_non_object_ci_is_unavailable(tmp_path, malformed):
    (tmp_path / "deploy_receipt.json").write_text(json.dumps({"deployed_sha": OLD}))
    (tmp_path / "post_merge_ci.json").write_text(json.dumps(malformed))
    result = governance_reader().releases_section(tmp_path, tmp_path)
    assert result["post_merge_ci_ok"] is None and result["post_merge_ci_status"] == "UNAVAILABLE"


def test_actual_old_governance_reader_reads_new_receipt_nulls_without_fabricating_deployment(tmp_path):
    # Execute the actual pinned old releases_section function, not a reimplementation.
    import ast

    source = subprocess.check_output(
        ["git", "show", "7af14c7782cf7ab0cba261cc25e6789fe810b092:scripts/report_lane_governance_packet.py"],
        cwd=ROOT,
        text=True,
    )
    tree = ast.parse(source)
    section = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "releases_section")
    old = governance_reader()
    exec(compile(ast.Module(body=[section], type_ignores=[]), "actual_old_reader.py", "exec"), old.__dict__)
    process, receipt, old_release, new, state = run_shell(tmp_path, "prepare", current=False)
    assert process.returncode == 0 and receipt["schema"] == "CioExactMainDeployReceipt@v2"
    result = old.releases_section(state, tmp_path)
    assert result["deployed_sha"] is None and result["release_dir"] is None and result["source_pr"] is None
    # Old reader can render the nullable deployed fields but cannot enforce new CI
    # binding; the consumer update must accompany the writer in production.
