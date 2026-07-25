import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOUND = (ROOT / "scripts/watch_quality_gate6_bound_scheduler.py").read_text()
WRAPPER = (ROOT / "scripts/run_watch_quality_local_scheduler_from_ref.sh").read_text()


def _load_selection():
    spec = importlib.util.spec_from_file_location(
        "watch_quality_gate6_selection_test",
        ROOT / "scripts/watch_quality_gate6_selection.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELECTION = _load_selection()
SOURCE = "a" * 40


def _rows(generated_at="2026-07-25T00:00:00+00:00", price=10.0):
    return [{
        "symbol": "AAA",
        "tier": "P0",
        "projection": {
            "symbol": "AAA",
            "projection_generated_at": generated_at,
            "projected_quality": "ADMITTED",
            "facts_used": {"price": price, "atr_pct": 4.0},
        },
    }]


def test_gate6_bound_scheduler_uses_complete_active_watch_population():
    for marker in (
        "watch-quality-active-population-v1",
        "FROM watchlist_items",
        "coalesce(status, 'active') IN ('active', 'researched')",
        '"packet_absent": len(population) - len(packets)',
        "active_symbols != projection_symbols",
        "active Watch population differs from quality projection",
        "Gate 6 candidates lack projection evidence",
        '"missing_projection_symbols": []',
        "PROJECTION_LIMIT = 1000",
    ):
        assert marker in BOUND


def test_gate6_run_requires_reviewed_selection_and_atomic_write():
    for marker in (
        "SELECTION_CONTRACT = selection.CONTRACT",
        "WATCH_QUALITY_EXPECTED_SELECTION_HASH",
        "BLOCKED_GATE6_SELECTION_DRIFT",
        "expected_selection_hash",
        "atomic._DeferredCommitConnection",
        "atomic._build_all_packets",
        "atomic._verify_pending_batch",
        '"database_commit_count": 1',
        '"database_commit_count": 0',
        "conn.commit()",
        "conn.rollback()",
    ):
        assert marker in BOUND
    assert SELECTION.CONTRACT == "watch-quality-gate6-reviewed-selection-v1"
    assert BOUND.index('if plan["selection_hash"] != expected_hash:') < BOUND.index(
        "atomic._build_all_packets"
    )
    assert "except BaseException" not in BOUND


def test_gate6_wrapper_runs_bound_entrypoint_and_never_changes_cron():
    for marker in (
        "watch_quality_gate6_bound_scheduler.py",
        "RUN requires WATCH_QUALITY_EXPECTED_SELECTION_HASH",
        "population_contract|watch-quality-active-population-v1",
        "selection_contract|watch-quality-gate6-reviewed-selection-v1",
        "transaction_contract|watch-quality-local-atomic-batch-v1",
        "cron_change|NONE",
        "blind_model_system|DISABLED",
        "inline_ticket_critic|DISABLED",
        "oauth_lane|WITHHELD",
        "paid_lane|WITHHELD",
    ):
        assert marker in WRAPPER
    assert "crontab " not in WRAPPER
    assert "systemctl " not in WRAPPER


def test_selection_hash_ignores_generation_timestamp_only():
    first = SELECTION.selection_hash(SOURCE, 20, _rows("2026-07-25T00:00:00+00:00"))
    second = SELECTION.selection_hash(SOURCE, 20, _rows("2026-07-25T01:00:00+00:00"))
    assert first == second
    assert len(first) == 64


def test_selection_hash_changes_with_evidence_order_scope_or_source():
    baseline = SELECTION.selection_hash(SOURCE, 20, _rows())
    assert baseline != SELECTION.selection_hash(SOURCE, 20, _rows(price=10.01))
    assert baseline != SELECTION.selection_hash("b" * 40, 20, _rows())
    assert baseline != SELECTION.selection_hash(SOURCE, 19, _rows())
    two = _rows() + [{
        "symbol": "BBB",
        "tier": "P1",
        "projection": {"symbol": "BBB", "projected_quality": "QUARANTINED"},
    }]
    assert SELECTION.selection_hash(SOURCE, 20, two) != SELECTION.selection_hash(
        SOURCE, 20, list(reversed(two))
    )
