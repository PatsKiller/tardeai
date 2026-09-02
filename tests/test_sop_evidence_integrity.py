"""Evidence-integrity validator + runtime attestation schema tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.sop_evidence_integrity import (
    EXPECTED_CORE_TESTS,
    RUNTIME_ATTESTATION_SCHEMA,
    control_surface_digest,
    load_manifest,
    validate_in_repo_evidence,
    validate_runtime_attestation,
    workflow_facts,
)
from scripts.lib.sop_toolchain import collect_tool_versions

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_sorted_unique():
    m = load_manifest(ROOT)
    assert m["paths"] == sorted(m["paths"])
    assert len(m["paths"]) == len(set(m["paths"]))


def test_control_surface_digest_deterministic():
    a = control_surface_digest(ROOT)
    b = control_surface_digest(ROOT)
    assert a["digest"] == b["digest"]
    assert len(a["digest"]) == 64
    assert a["path_count"] == len(load_manifest(ROOT)["paths"])


def test_digest_changes_when_surface_file_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Copy minimal surface into tmp is heavy; instead mutate via monkeypatch of file_sha256
    from scripts.lib import sop_evidence_integrity as sei

    base = sei.control_surface_digest(ROOT)
    real = sei.file_sha256

    def flipped(path: Path) -> str:
        d = real(path)
        # flip first nibble
        return ("0" if d[0] != "0" else "1") + d[1:]

    monkeypatch.setattr(sei, "file_sha256", flipped)
    altered = sei.control_surface_digest(ROOT)
    assert altered["digest"] != base["digest"]


def test_workflow_facts_no_path_filters_and_ruff_pin():
    wf = workflow_facts(ROOT)
    assert wf["has_path_filters"] is False
    assert wf["triggers"]["pull_request"]
    assert wf["triggers"]["push_main"]
    assert wf["triggers"]["workflow_dispatch"]
    assert wf["pinned_ruff_install"] is True
    assert wf["ruff_or_true"] is False
    assert wf["lines"] >= 40


def test_in_repo_evidence_validator_on_repo():
    # After evidence repair this must be empty; during mid-edit may fail — skip soft
    errors = validate_in_repo_evidence(ROOT)
    # Always structural: digest computable
    digest = control_surface_digest(ROOT)["digest"]
    assert digest
    # If CURRENT files already repaired, expect no errors
    # (CI and local freeze require this to be empty.)
    assert errors == [], errors


def test_validator_detects_placeholder_and_self_head(tmp_path: Path):
    from scripts.lib import sop_evidence_integrity as sei

    # Build a fake root with manifest pointing at one file
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    surface = root / "AGENTS.md"
    surface.write_text("Policy-Version: 1.2.0\nStatus: PROPOSED\n", encoding="utf-8")
    (root / ".github/workflows").mkdir(parents=True)
    wf = root / ".github/workflows/agent-governance.yml"
    wf.write_text(
        "name: agent-governance\non:\n  pull_request:\n  push:\n    branches: [main]\n  workflow_dispatch:\n"
        "jobs:\n  agent-governance:\n    runs-on: ubuntu-latest\n    steps:\n"
        '      - name: Install\n        run: pip install "ruff==0.16.2"\n',
        encoding="utf-8",
    )
    paths = [
        ".github/workflows/agent-governance.yml",
        "AGENTS.md",
        "config/sop_120_control_surface.manifest.json",
    ]
    # touch required surface files as empty stubs for digest — validator needs all paths
    # Use a tiny manifest for this unit test by writing only existing paths
    man = {
        "schema": "SopControlSurfaceManifest@v1",
        "sop": "1.2.0",
        "paths": sorted(paths),
    }
    (root / "config/sop_120_control_surface.manifest.json").write_text(json.dumps(man, indent=2) + "\n")
    ev = root / sei.EVIDENCE_DIR_REL
    ev.mkdir(parents=True)
    digest = sei.control_surface_digest(root)["digest"]
    # Create all CURRENT files minimally bound to digest
    for name in sei.CURRENT_EVIDENCE:
        if name == "FULL_TEST_MATRIX.txt":
            (ev / name).write_text(
                f"control_surface_digest={digest}\nexpected_pytest_core={sei.EXPECTED_CORE_TESTS}\n"
                "EXIT_lease_canonical=0\nEXIT_session=0\nEXIT_identity=0\nEXIT_quality_unit=0\n"
                "EXIT_clients=0\nEXIT_drive=0\nEXIT_policy=0\nEXIT_quality=0\n"
                "EXIT_ruff_check=0\nEXIT_ruff_format=0\nEXIT_shellcheck=0\nEXIT_diffcheck=0\n"
                "EXIT_secrets=0\nEXIT_missing_ruff=2\nEXIT_positive_control=1\n"
                "PYTEST_CORE=120\n",
                encoding="utf-8",
            )
        elif name == "RUFF_SHELLCHECK.txt":
            (ev / name).write_text(
                f"control_surface_digest={digest}\nruff pinned=0.16.2\n"
                "EXIT_ruff_check=0\nEXIT_ruff_format=0\nEXIT_shellcheck=0\n"
                "EXIT_missing_ruff_negative=2\n",
                encoding="utf-8",
            )
        elif name == "CONTROL7_WORKFLOW_PROOF.txt":
            wf_hash = sei.file_sha256(wf)
            (ev / name).write_text(
                f"control_surface_digest={digest}\nworkflow_blob_sha256={wf_hash}\n"
                f"workflow_lines={len(wf.read_text().splitlines())}\npath_filters=absent\n",
                encoding="utf-8",
            )
        elif name == "CONTROL7_LOCAL_EQUIVALENT.txt":
            (ev / name).write_text(
                f"control_surface_digest={digest}\nEXIT_clients=0\nEXIT_quality=0\n",
                encoding="utf-8",
            )
        elif name == "CONTROL6_INDEX_FINGERPRINT.txt":
            (ev / name).write_text(
                "verify_command=python3 scripts/report_docs_inventory.py --check-index\n"
                "do_not_embed_live_fingerprint=true\n",
                encoding="utf-8",
            )
        elif name == "MATURITY_SCORECARD.md":
            (ev / name).write_text(f"control_surface_digest={digest}\n| 7 | PASS |\n", encoding="utf-8")
        else:
            (ev / name).write_text(f"control_surface_digest={digest}\nok\n", encoding="utf-8")

    assert sei.validate_in_repo_evidence(root) == []

    # Placeholder
    bad = ev / "FULL_TEST_MATRIX.txt"
    bad.write_text(bad.read_text() + "EXIT_index=run_check_index_after_evidence_commit\n", encoding="utf-8")
    errs = sei.validate_in_repo_evidence(root)
    assert any(e.startswith("PLACEHOLDER:") for e in errs)
    # restore and test self-head
    bad.write_text(
        f"control_surface_digest={digest}\nexpected_pytest_core=120\nPYTEST_CORE=120\n"
        "EXIT_lease_canonical=0\nEXIT_session=0\nEXIT_identity=0\nEXIT_quality_unit=0\n"
        "EXIT_clients=0\nEXIT_drive=0\nEXIT_policy=0\nEXIT_quality=0\n"
        "EXIT_ruff_check=0\nEXIT_ruff_format=0\nEXIT_shellcheck=0\nEXIT_diffcheck=0\n"
        "EXIT_secrets=0\nEXIT_missing_ruff=2\nEXIT_positive_control=1\n"
        "source_head=e789fe263cdc6fafbd4366369e485c65be98219f\n",
        encoding="utf-8",
    )
    errs = sei.validate_in_repo_evidence(root)
    assert any(e.startswith("SELF_REF_HEAD_CLAIM:") for e in errs)


def test_runtime_attestation_schema_roundtrip():
    digest = control_surface_digest(ROOT)["digest"]
    wf = workflow_facts(ROOT)
    att = {
        "schema": RUNTIME_ATTESTATION_SCHEMA,
        "schema_version": "1.0.0",
        "head_sha": "a" * 40,
        "base_sha": "b" * 40,
        "control_surface_digest": digest,
        "policy_version": "1.2.0",
        "policy_status": "PROPOSED",
        "workflow_blob_sha256": wf["blob_sha256"],
        "commands": [],
        "test_counts": {"core": EXPECTED_CORE_TESTS},
        "docs_index_fingerprint": "deadbeef",
        "tool_versions": {
            "python": "3.14.4",
            "pinned_ruff": "0.16.2",
            "ruff": "0.16.2",
            "ruff_raw": "ruff 0.16.2",
            "shellcheck": collect_tool_versions(root=ROOT)["shellcheck"],
        },
        "clean_state": True,
        "authority_non_regression": "PASS",
    }
    assert validate_runtime_attestation(att, root=ROOT) == []
    att["control_surface_digest"] = "0" * 64
    assert "ATTESTATION_DIGEST_MISMATCH" in validate_runtime_attestation(att, root=ROOT)
