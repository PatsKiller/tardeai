from pathlib import Path


SCRIPT = Path("scripts/agent_runtime/lab_evolve_from_ref.sh").read_text()


def test_wrapper_requires_exact_reviewed_commit():
    assert "AGENTIC_SOURCE_REF" in SCRIPT
    assert "40-character commit SHA" in SCRIPT
    assert "cat-file -e \"$SOURCE_REF^{commit}\"" in SCRIPT
    assert "rev-parse \"$SOURCE_REF^{commit}\"" in SCRIPT


def test_wrapper_stages_all_authoritative_inputs_from_one_commit():
    for path in (
        "migrations/agentic_runtime/0001_mvl.up.sql",
        "migrations/agentic_runtime/0001_mvl.down.sql",
        "scripts/agent_runtime/lab_evolve_1_to_8.sh",
        "config/agent_runtime_mvl.json",
    ):
        assert path in SCRIPT
    assert 'archive "$RESOLVED_COMMIT"' in SCRIPT
    assert 'REPO="$STAGE_ROOT" "$BASH" "$INNER"' in SCRIPT


def test_wrapper_never_changes_or_trusts_checked_out_source():
    forbidden = (
        "git checkout",
        "git switch",
        "git reset",
        "git clean",
        "git pull",
        "git merge",
        "git rebase",
        "worktree add",
    )
    lowered = SCRIPT.lower()
    for token in forbidden:
        assert token not in lowered
    assert "PINNED_GIT_OBJECT_ARCHIVE" in SCRIPT
    assert "host_worktree_checkout|UNCHANGED" in SCRIPT


def test_wrapper_preserves_safety_boundary():
    assert "DISPOSABLE_LAB_NO_PRODUCTION_DATA" in SCRIPT
    assert "BLOCKED_LAB_PROVISIONING" in SCRIPT
    for token in (
        "systemctl ",
        "service ",
        "apt install",
        "apt-get install",
        "pip install",
        "docker run",
        "podman run",
        "PGPASSWORD=",
    ):
        assert token not in SCRIPT
