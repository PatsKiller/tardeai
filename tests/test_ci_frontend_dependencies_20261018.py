"""Execute the actual CI dependency selector against the real registered shard plan."""

from pathlib import Path

import pytest
import yaml

from scripts import run_cio_hardening_ci as runner

ROOT = Path(__file__).resolve().parents[1]
ACTION_PATH = ROOT / ".github/actions/setup-cio-frontend-tests/action.yml"
ACTION = yaml.safe_load(ACTION_PATH.read_text())
USES = "./.github/actions/setup-cio-frontend-tests"
READERS = {"tests/test_cc_reader_first_20261018.py", "tests/test_comms_delivery_health_truth_20261020.py"}


def actual_selector(tmp_path, monkeypatch, selector):
    output = tmp_path / "github-output"
    monkeypatch.setenv("CIO_TEST_SHARD", selector)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    script = ACTION["runs"]["steps"][0]["run"]
    python = script.split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    exec(compile(python, str(ACTION_PATH), "exec"), {})
    return output.read_text()


def test_complete_registered_suite_requires_real_frontend_dependencies(tmp_path, monkeypatch):
    assert actual_selector(tmp_path, monkeypatch, "") == "required=true\n"


@pytest.mark.parametrize("shard", ["0", "1", "2", "3", "4", "5", "6", "7", "serial", "pg"])
def test_only_actual_owning_shard_installs_frontend_dependencies(tmp_path, monkeypatch, shard):
    files = runner.shard_plan(8)["shards"][shard]
    expected = "required=true\n" if READERS & set(files) else "required=false\n"
    assert actual_selector(tmp_path, monkeypatch, shard + "/8") == expected
    for reader in READERS:
        owners = [sid for sid, paths in runner.shard_plan(8)["shards"].items() if reader in paths]
        assert len(owners) == 1, "dependency setup cannot drop or duplicate a real reader test"


@pytest.mark.parametrize("selector", ["unknown/8", "8/8", "0/0"])
def test_invalid_shard_cannot_silently_skip_dependencies(tmp_path, monkeypatch, selector):
    with pytest.raises(ValueError):
        actual_selector(tmp_path, monkeypatch, selector)
    assert not (tmp_path / "github-output").exists()


def test_all_actual_test_jobs_install_before_executing_the_existing_runner():
    hardening = yaml.safe_load((ROOT / ".github/workflows/cio-production-hardening-ci.yml").read_text())
    shards = yaml.safe_load((ROOT / ".github/workflows/cio-full-suite-sharded.yml").read_text())
    for workflow, job, selector in [
        (hardening, "cio-hardening", None),
        (hardening, "cio-hardening-full", None),
        # 2026-10-22: the push-to-main FAST profile runs as parallel shards (aggregate: cio-hardening)
        (hardening, "fast-shard", "${{ matrix.shard }}/${{ env.CIO_SHARDS }}"),
        (hardening, "fast-serial", "serial/${{ env.CIO_SHARDS }}"),
        (hardening, "fast-pg", "pg/${{ env.CIO_SHARDS }}"),
        (shards, "shard", "${{ matrix.shard }}/${{ env.CIO_SHARDS }}"),
        (shards, "serial", "serial/${{ env.CIO_SHARDS }}"),
        (shards, "pg", "pg/${{ env.CIO_SHARDS }}"),
    ]:
        steps = workflow["jobs"][job]["steps"]
        dependencies = [i for i, step in enumerate(steps) if step.get("uses") == USES]
        assert len(dependencies) == 1
        index = dependencies[0]
        assert steps[index].get("with", {}).get("shard") == selector
        test_index = next(i for i, step in enumerate(steps) if "scripts/run_cio_hardening_ci.py" in step.get("run", ""))
        assert index < test_index
    assert ACTION["runs"]["steps"][1]["with"]["node-version"] == "22"
    install = ACTION["runs"]["steps"][2]
    assert install["run"] == "npm ci --silent"
    assert install["working-directory"] == "apps/command-center-v3"
    assert install["if"] == "steps.frontend.outputs.required == 'true'"
