from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "scripts/run_watch_quality_rollout_gates_3_to_6_from_ref.sh").read_text()


def test_rollout_requires_explicit_ack_and_exact_source():
    for marker in (
        'EXECUTE_WATCH_QUALITY_GATES_3_TO_6',
        'WATCH_QUALITY_SOURCE_REF',
        'exact 40-character commit SHA',
        'cat-file -e "$SOURCE_REF^{commit}"',
        'rev-parse "$SOURCE_REF^{commit}"',
    ):
        assert marker in SOURCE


def test_rollout_runs_source_gate_then_gates_3_4_5_6_in_order():
    validation = SOURCE.index('=== SOURCE VALIDATION ===')
    gate3 = SOURCE.index('=== GATE 3 — BOUNDED LOCAL REBUILD ===')
    gate4 = SOURCE.index('=== GATE 4 — READ-ONLY VERIFICATION ===')
    gate5 = SOURCE.index('=== GATE 5 — STATIC WATCH UI ===')
    gate6 = SOURCE.index('=== GATE 6 — LOCAL-ONLY SCHEDULER ===')
    assert validation < gate3 < gate4 < gate5 < gate6
    assert 'final_status|PASS_WATCH_QUALITY_GATES_3_TO_6' in SOURCE


def test_rollout_keeps_model_lanes_withheld():
    for marker in (
        'model_lanes|WITHHELD',
        'oauth_lanes|WITHHELD',
        'paid_lane|WITHHELD',
        'WATCH_QUALITY_LOCAL_LIMIT',
    ):
        assert marker in SOURCE
    lowered = SOURCE.lower()
    for forbidden in ('llm_lane', 'premium_review', 'place_order', 'broker_submit', 'approve_order', '2fa_unlock'):
        assert forbidden not in lowered
