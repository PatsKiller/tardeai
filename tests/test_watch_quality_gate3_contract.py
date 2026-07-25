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


# ---------------------------------------------------------------------------
# Behavioral coverage for the v2 JSONB numeric-equivalence logic.
#
# The tests above are static-text guards; they never execute the comparison
# helpers, so a regression such as ``_numbers_equal`` always returning True (an
# unsafe pass) would slip through. These tests import the *real* shipped module
# and exercise its own code, staying hermetic: the verifier's only non-stdlib
# import is ``watch_quality_gate3_sample_rebuild`` (which pulls in the DB driver
# absent from the pytest-only CI image), so we stub that single name before
# import. The equivalence helpers touch none of it.
# ---------------------------------------------------------------------------
def _load_roundtrip_verifier():
    import importlib.util
    import sys
    import types

    saved = sys.modules.get("watch_quality_gate3_sample_rebuild")
    sys.modules["watch_quality_gate3_sample_rebuild"] = types.ModuleType(
        "watch_quality_gate3_sample_rebuild")
    try:
        spec = importlib.util.spec_from_file_location(
            "watch_quality_gate3_sample_rebuild_v2_behavioral",
            ROOT / "scripts/watch_quality_gate3_sample_rebuild_v2.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if saved is None:
            sys.modules.pop("watch_quality_gate3_sample_rebuild", None)
        else:
            sys.modules["watch_quality_gate3_sample_rebuild"] = saved


V2 = _load_roundtrip_verifier()


def _equivalent(a, b):
    """True iff the verifier treats a and b as the same persisted JSON value."""
    return (
        V2._semantic_hash(a) == V2._semantic_hash(b)
        and V2._semantic_differences(a, b) == []
    )


def test_v2_numeric_equivalence_tolerates_representation_only():
    # Equal-valued JSON numbers differing only in spelling/type must round-trip
    # clean — this is the PostgreSQL JSONB normalization the verifier exists to
    # allow (e.g. 1 -> 1.0, -0.0 -> 0.0, 1.10 -> 1.1).
    for a, b in (
        (1, 1.0),
        (-0.0, 0.0),
        (100, 100.0),
        (1.10, 1.1),
        ({"q": 1}, {"q": 1.0}),
        ([1, 2.0], [1.0, 2]),
        ({"a": [1, 2.0], "b": True, "c": None}, {"a": [1.0, 2], "b": True, "c": None}),
    ):
        assert _equivalent(a, b), (a, b)
    assert V2._semantic_hash({"q": 1}) == V2._semantic_hash({"q": 1.0})


def test_v2_numeric_normalization_cannot_conceal_a_value_change():
    # Every genuine value change must be caught by BOTH the structural diff and
    # the semantic hash — neither may be fooled by numeric normalization.
    for a, b in (
        (1.5, 1.6),
        (1, 2),
        (0.0, 0.01),
        (2.0, 2.0001),
        (0.1 + 0.2, 0.3),
        ({"x": [{"y": 1.0}]}, {"x": [{"y": 1.001}]}),
    ):
        assert V2._semantic_differences(a, b), (a, b)
        assert V2._semantic_hash(a) != V2._semantic_hash(b), (a, b)
        assert not _equivalent(a, b), (a, b)


def test_v2_never_normalizes_across_json_types():
    # bool is not a number; a number is not a string; null is not zero.
    for a, b in ((True, 1), (False, 0), (1, "1"), (0, "0"), (None, 0), (1.0, "1.0")):
        assert V2._semantic_differences(a, b), (a, b)
        assert not _equivalent(a, b), (a, b)
    assert V2._numbers_equal(True, 1) is False
    assert V2._numbers_equal(1, True) is False
    assert V2._numbers_equal(1, 1.0) is True


def test_v2_structural_comparison_stays_strict():
    assert V2._semantic_differences([1], [1, 1])            # list length
    assert V2._semantic_differences([1, 2], [2, 1])         # list order
    assert V2._semantic_differences({"a": 1}, {})           # missing key
    assert V2._semantic_differences({}, {"a": 1})           # unexpected key
    assert V2._semantic_differences("1", "2")               # strings compared exactly
    assert V2._semantic_differences(True, False)            # booleans compared exactly
    assert V2._semantic_differences(None, False)            # null vs bool
    # identical structure with only numeric-representation drift is clean
    assert V2._semantic_differences(
        {"a": [1, 2.0], "b": "x"}, {"a": [1.0, 2], "b": "x"}) == []


def test_v2_number_token_is_canonical_and_rejects_non_numbers():
    import math

    import pytest

    tok = V2._number_token
    assert tok(1) == tok(1.0) == "1"
    assert tok(-0.0) == tok(0.0) == "0"
    assert tok(1.10) == tok(1.1)
    assert tok(100) == "100"                 # canonical decimal, never 1E+2
    assert tok(2.0) != tok(2.0001)           # real change is not collapsed
    with pytest.raises(TypeError):
        tok(True)                            # bool is not a JSON number
    for bad in (math.inf, -math.inf, math.nan):
        with pytest.raises(ValueError):
            tok(bad)                         # non-finite cannot persist to JSONB
