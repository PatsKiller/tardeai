from pathlib import Path


SCRIPT = Path("scripts/agent_runtime/lab_evolve_1_to_8.sh").read_text()


def test_lab_evolve_is_pinned_to_isolated_cluster():
    assert "readonly LAB_PORT=5433" in SCRIPT
    assert "readonly LAB_HOST=127.0.0.1" in SCRIPT
    assert "readonly EXPECTED_DATA_DIR=/home/johnclaw/tradeai-lab/pg17" in SCRIPT
    assert "readonly LAB_DATABASE=trade_ai_agentic_lab" in SCRIPT
    assert "trade_ai_test" in SCRIPT
    assert "existing_database_reuse|DENIED" in SCRIPT


def test_lab_evolve_requires_explicit_disposable_ack():
    assert "DISPOSABLE_LAB_NO_PRODUCTION_DATA" in SCRIPT
    assert "BLOCKED_LAB_PROVISIONING" in SCRIPT
    assert "REFUSED_NON_LAB_TARGET" in SCRIPT


def test_migration_executor_is_non_login_and_runtime_roles_are_separate():
    assert "CREATE ROLE $MIGRATOR_ROLE\n  NOLOGIN" in SCRIPT
    assert "CREATE ROLE $READER_ROLE\n  LOGIN" in SCRIPT
    assert "CREATE ROLE $WRITER_ROLE\n  LOGIN" in SCRIPT
    assert "runtime_excludes_migration_executor|PASS" in SCRIPT


def test_secrets_are_host_local_and_never_echoed():
    assert "SECRET_DIR=/home/johnclaw/tradeai-lab/secrets/agentic-runtime" in SCRIPT
    assert "chmod 600 \"$READER_PGPASS\" \"$WRITER_PGPASS\"" in SCRIPT
    assert "reader_password|" not in SCRIPT
    assert "writer_password|" not in SCRIPT
    assert "PGPASSWORD=" not in SCRIPT


def test_proof_covers_expected_eight_tables_and_replay():
    for table in (
        "agent_runs",
        "agent_artifacts",
        "agent_tool_calls",
        "agent_reviews",
        "agent_scores",
        "kb_lessons",
        "kb_cases",
        "kb_chunks",
    ):
        assert table in SCRIPT
    assert "migration_down_cleanup|PASS" in SCRIPT
    assert "migration_replay_hash_match|PASS" in SCRIPT
    assert "final_status|PASS_DB_PROOF" in SCRIPT


def test_denial_surface_is_synthetic_and_complete():
    assert "approved_canonical.v_agentic_market_snapshot" in SCRIPT
    for schema in ("trade", "broker", "account", "position", "approval", "configuration", "lab_protected"):
        assert schema in SCRIPT
    assert "producer_self_review" in SCRIPT
    assert "producer_self_score" in SCRIPT
    assert "append_only_update_" in SCRIPT
    assert "append_only_delete_" in SCRIPT


def test_script_does_not_manage_services_or_install_packages():
    forbidden = (
        "systemctl ",
        "service ",
        "apt install",
        "apt-get install",
        "pip install",
        "docker run",
        "podman run",
        "ssh ",
    )
    for token in forbidden:
        assert token not in SCRIPT
