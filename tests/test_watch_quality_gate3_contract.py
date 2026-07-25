from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_RUNNER = (ROOT / "scripts/watch_quality_gate3_sample_rebuild.py").read_text()
ROUNDTRIP_RUNNER = (ROOT / "scripts/watch_quality_gate3_sample_rebuild_v2.py").read_text()
RUNNER = LEGACY_RUNNER + ROUNDTRIP_RUNNER
BUILDER = (ROOT / "scripts/watch_quality_governed_builder.py").read_text()
WRAPPER = (ROOT / "scripts/run_watch_quality_gate3_from_ref.sh").read_text()
WORKFLOW = (ROOT / ".github/workflows/watch-quality-governance-ci.yml").read_text()


def test_gate3_is_exactly_five_role_local_quant_sample():
    for marker in (
        'ROLE_ORDER = ("admitted", "research_only", "quarantined", "management_only", "contradiction")',
        'PASS_GATE3_BOUNDED_LOCAL_REBUILD',
        'BLOCKED_GATE3_PREWRITE_MISMATCH',
        'BLOCKED_GATE3_PERSISTENCE_FAILURE',
        'BLOCKED_GATE3_POSTWRITE_VERIFICATION',
        'watch-quality-projection-v2',
        'watch-quality-governed-builder-v1',
        'watch-quality-gate3-jsonb-roundtrip-v1',
        'MAX_PROJECTION_AGE_HOURS = 6.0',
        'governed_builder.build_packet(',
    ):
        assert marker in RUNNER or marker in BUILDER


def test_gate3_prevalidates_every_candidate_before_persisting():
    evaluation = LEGACY_RUNNER.index('governed_builder.build_packet(')
    prewrite = LEGACY_RUNNER.index('if prewrite_errors:')
    persist = LEGACY_RUNNER.index('decision_service.persist(')
    assert evaluation < prewrite < persist
    assert 'projected quality {expected_quality} != rebuilt quality {observed_quality}' in RUNNER
    assert 'rebuilt_quality_facts_used' in RUNNER
    assert 'inline_ticket_reviews' in RUNNER


def test_gate3_freezes_candidates_at_persistence_boundary():
    snapshot = ROUNDTRIP_RUNNER.index('snapshots[str(packet.get("symbol") or "").upper()] = _json_snapshot(packet)')
    persist_patch = ROUNDTRIP_RUNNER.index('gate3.decision_service.persist = snapshot_persist')
    execute = ROUNDTRIP_RUNNER.index('report = gate3.execute(')
    restore = ROUNDTRIP_RUNNER.index('gate3.decision_service.persist = original_persist')
    assert snapshot < persist_patch < execute < restore
    assert 'candidate_semantic_hash' in ROUNDTRIP_RUNNER


def test_gate3_verifies_exact_packet_ids_and_all_roles():
    for marker in (
        'WHERE packet_id=%s',
        'for role in gate3.ROLE_ORDER:',
        'errors: list[str] = []',
        'representation_hash_mismatches',
        'after_semantic_differences',
        'JSONB semantic difference at',
        'gate field {field} changed after persistence',
    ):
        assert marker in ROUNDTRIP_RUNNER
    assert 'WHERE upper(symbol)=%s AND superseded_by IS NULL' not in ROUNDTRIP_RUNNER


def test_gate3_jsonb_equivalence_only_normalizes_numbers():
    for marker in (
        'only equal-valued JSON numbers may differ in type/spelling',
        'if payload is None or isinstance(payload, (bool, str)):',
        'if isinstance(payload, (int, float)):',
        'if type(left) is not type(right):',
        'add("missing_key"',
        'add("unexpected_key"',
        'add("list_length"',
    ):
        assert marker in ROUNDTRIP_RUNNER


def test_governed_builder_uses_projection_as_immutable_quality_input():
    for marker in (
        'quality_policy.evaluate_admission = projected_admission',
        'packet["quality_admission"] = root_admission',
        'packet["quality_projection_snapshot"]',
        'ticket_reconciler.reconcile(validation, {})',
        'SHADOW_DISABLE_MODELS',
        'SHADOW_DISABLE_TICKET_CRITIC',
        'run_models=False',
        'governed LOCAL_QUANT build recorded a model or critic result',
    ):
        assert marker in BUILDER


def test_gate3_has_no_model_scheduler_ui_or_execution_authority():
    lowered = (RUNNER + BUILDER).lower()
    for forbidden in (
        'analysis_tier="standard_blind"',
        'analysis_tier="premium_review"',
        'llm_lane.generate',
        'crontab ',
        'systemctl ',
        'place_order',
        'broker_submit',
        'approve_order',
        '2fa_unlock',
        'deploy_defense_sectors',
    ):
        assert forbidden not in lowered
    for evidence in (
        '"model_provider_call": False',
        '"oauth_lane_call": False',
        '"paid_lane_call": False',
        '"schedule_change": False',
        '"service_restart": False',
        '"ui_deployment": False',
        '"proposal_or_execution_action": False',
    ):
        assert evidence in RUNNER


def test_gate3_workflow_compiles_and_scans_roundtrip_verifier():
    assert "'scripts/watch_quality_gate3_sample_rebuild_v2.py'" in WORKFLOW
    assert WORKFLOW.count('scripts/watch_quality_gate3_sample_rebuild_v2.py') >= 3
    compile_step = WORKFLOW.index('python -m py_compile')
    verifier = WORKFLOW.index('scripts/watch_quality_gate3_sample_rebuild_v2.py', compile_step)
    authority = WORKFLOW.index('Confirm bounded authority')
    scanned = WORKFLOW.index('scripts/watch_quality_gate3_sample_rebuild_v2.py', authority)
    assert compile_step < verifier < authority < scanned


def test_gate3_wrapper_pins_source_and_disables_every_model_path():
    for marker in (
        'WATCH_GATE3_EXECUTION_ACK',
        'EXECUTE_WATCH_QUALITY_GATE3',
        'WATCH_QUALITY_SOURCE_REF',
        'git -C "$HOST_REPO" archive "$RESOLVED_COMMIT" scripts config',
        'host_worktree_checkout|UNCHANGED',
        'WATCH_GATE3_ACK=BOUNDED_LOCAL_QUANT_SAMPLE',
        'WATCH_QUALITY_SOURCE_COMMIT="$RESOLVED_COMMIT"',
        'watch_quality_governed_builder.py',
        'watch_quality_gate3_sample_rebuild_v2.py',
        'roundtrip_verifier|watch-quality-gate3-jsonb-roundtrip-v1',
        'governed_builder|watch-quality-governed-builder-v1',
        'SHADOW_DISABLE_MODELS=1',
        'SHADOW_DISABLE_TICKET_CRITIC=1',
        'blind_model_system|DISABLED',
        'inline_ticket_critic|DISABLED',
        'final_status|PASS_GATE3_OPERATOR_PACKET',
    ):
        assert marker in WRAPPER
    for forbidden in ('git checkout', 'git reset', 'git clean', 'npm ', 'systemctl ', 'crontab '):
        assert forbidden not in WRAPPER
