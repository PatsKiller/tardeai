import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCHEDULER = (ROOT / "scripts/watch_quality_local_scheduler.py").read_text()
RUNNER = (ROOT / "scripts/run_watch_quality_local_scheduler_from_ref.sh").read_text()
INSTALLER = (ROOT / "scripts/install_watch_quality_local_scheduler_from_ref.sh").read_text()


def test_gate6_scheduler_withholds_all_model_lanes():
    for marker in (
        'watch-quality-local-scheduler-v1',
        'analysis_tier": "LOCAL_QUANT"',
        '"model_provider_call": False',
        '"oauth_lane_call": False',
        '"paid_lane_call": False',
        'selected_model_lane_calls": 0',
        'oauth_withheld',
        'watch-quality-projection-v2',
        'watch-quality-governed-builder-v1',
        'governed_builder.build_packet(',
        'decision_service.persist(',
        'PASS_LOCAL_SCHEDULER_COMPLETED',
    ):
        assert marker in SCHEDULER
    lowered = SCHEDULER.lower()
    for forbidden in (
        'analysis_tier="standard_blind"',
        'analysis_tier="premium_review"',
        'llm_lane.generate',
        'enqueue_run(',
        'spawn_workers=true',
        'place_order',
        'broker_submit',
        'approve_order',
        '2fa_unlock',
    ):
        assert forbidden not in lowered


def test_gate6_dry_run_precedes_activation_and_is_bounded():
    for marker in (
        'DEFAULT_LIMIT = 20',
        'MAX_LIMIT = 40',
        'PROJECTION_LIMIT = 200',
        '--dry-run',
        '--run',
        'WATCH_QUALITY_LOCAL_SCHEDULER_ACK',
        'ACTIVATE_BOUNDED_LOCAL_QUANT',
        'WATCH_SCHEDULER_PAUSED',
        'WATCH_QUALITY_SOURCE_COMMIT',
    ):
        assert marker in SCHEDULER


def test_gate6_batch_is_atomic_prebuilt_and_precommit_verified():
    for marker in (
        'watch-quality-local-atomic-batch-v1',
        'class _DeferredCommitConnection',
        'prepared = _build_all_packets(',
        'conn=deferred',
        'verification_errors = _verify_pending_batch(',
        'exact packet readback IDs',
        'live packet IDs {live_ids} != [{packet_id}]',
        'deferred.deferred_commit_calls != len(prepared)',
        'conn.commit()',
        'conn.rollback()',
        'BLOCKED_LOCAL_SCHEDULER_ATOMIC_ROLLBACK',
        '"database_commit_count": 0',
        '"database_commit_count": 1',
        '_close_quietly(conn)',
    ):
        assert marker in SCHEDULER
    assert SCHEDULER.index('prepared = _build_all_packets(') < SCHEDULER.index('decision_service.persist(')
    assert SCHEDULER.index('verification_errors = _verify_pending_batch(') < SCHEDULER.index('conn.commit()')
    assert 'except BaseException as exc:' not in SCHEDULER
    assert 'except Exception as exc:' in SCHEDULER


def test_gate6_exact_ref_runner_requires_gate4_live_gate5_and_zero_models():
    for marker in (
        'WATCH_QUALITY_SOURCE_REF',
        'PASS_GATE4_READONLY_VERIFICATION',
        'build-meta.json',
        'live UI source commit differs from scheduler source',
        'watch-quality-governance-v1',
        'WATCH_QUALITY_SCHEDULER_MODE',
        'WATCH_QUALITY_SOURCE_COMMIT="$RESOLVED_COMMIT"',
        'governed_builder|watch-quality-governed-builder-v1',
        'SHADOW_DISABLE_MODELS=1',
        'SHADOW_DISABLE_TICKET_CRITIC=1',
        'blind_model_system|DISABLED',
        'inline_ticket_critic|DISABLED',
        'oauth_lane|WITHHELD',
        'paid_lane|WITHHELD',
    ):
        assert marker in RUNNER


def test_gate6_installer_backs_up_crontab_and_refuses_conflicts():
    for marker in (
        'INSTALL_AND_RUN_BOUNDED_LOCAL_QUANT',
        '.crontab_backup_watch_quality_',
        'flock -n',
        '17 7 * * *',
        'BLOCKED_GATE6_CONFLICTING_WATCH_SCHEDULE',
        'watch_decision_scheduler|watch_decision_refresh|watch-quality-local-|watch_quality_local_scheduler',
        'PASS_GATE6_LOCAL_SCHEDULER_ACTIVATION',
        'oauth_lane|WITHHELD',
        'paid_lane|WITHHELD',
    ):
        assert marker in INSTALLER
    assert INSTALLER.index('WATCH_QUALITY_SCHEDULER_MODE=DRY_RUN') < INSTALLER.index('crontab "$CURRENT"')


def _load_scheduler_module():
    names = (
        "shadow_decision_service",
        "watch_decision_refresh",
        "watch_decision_scheduler",
        "watch_quality_governed_builder",
        "watch_quality_projection",
        "watch_quality_projection_v2",
    )
    saved = {name: sys.modules.get(name) for name in names}
    stubs = {name: types.ModuleType(name) for name in names}
    stubs["watch_quality_projection"].CONTRACT = "watch-quality-projection-v1"
    stubs["watch_quality_projection"].assemble_projection_facts = object()
    stubs["watch_quality_projection_v2"].CONTRACT = "watch-quality-projection-v2"
    stubs["watch_quality_projection_v2"].assemble_projection_facts = object()
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location(
            "watch_quality_local_scheduler_atomic_behavior",
            ROOT / "scripts/watch_quality_local_scheduler.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, prior in saved.items():
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


ATOMIC = _load_scheduler_module()
SOURCE_SHA = "a" * 40


def _packet(symbol):
    return {
        "symbol": symbol,
        "source_commit_sha": SOURCE_SHA,
        "quality_admission": {"state": "ADMITTED"},
        "operator_presentation": {
            "contract": "watch-quality-governance-v1",
            "one_sovereign_decision": True,
        },
        "model_review": {"lanes_completed": []},
        "ticket_review": {"reviews": {}},
    }


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def execute(self, query, params=()):
        normalized = " ".join(str(query).split())
        if "WHERE packet_id IN" in normalized:
            ids = {int(value) for value in params}
            self.rows = [
                (packet_id, row["symbol"], row["packet"])
                for packet_id, row in sorted(self.conn.pending.items())
                if packet_id in ids
            ]
        elif "superseded_by IS NULL" in normalized:
            symbol = str(params[0]).upper()
            self.rows = [
                (packet_id,)
                for packet_id, row in sorted(self.conn.pending.items())
                if row["symbol"] == symbol and row.get("live", True)
            ]
        else:
            raise AssertionError(normalized)

    def fetchall(self):
        return list(self.rows)


class _FakeConnection:
    def __init__(self):
        self.pending = {}
        self.committed = {}
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    def cursor(self, *args, **kwargs):
        return _FakeCursor(self)

    def commit(self):
        self.commit_calls += 1
        self.committed.update(self.pending)

    def rollback(self):
        self.rollback_calls += 1
        self.pending.clear()

    def close(self):
        self.closed = True


def _install_runtime(monkeypatch, conn, *, fail_on_symbol=None, interrupt=False):
    plan = {
        "contract": ATOMIC.CONTRACT,
        "transaction_contract": ATOMIC.TRANSACTION_CONTRACT,
        "source_commit": SOURCE_SHA,
        "local": [
            {"symbol": "AAA", "projection": {"symbol": "AAA"}},
            {"symbol": "BBB", "projection": {"symbol": "BBB"}},
        ],
    }
    monkeypatch.setattr(ATOMIC, "build_local_plan", lambda limit: plan)
    monkeypatch.setattr(ATOMIC.refresh, "_conn", lambda: conn)
    monkeypatch.setattr(
        ATOMIC.governed_builder,
        "build_packet",
        lambda symbol, *args, **kwargs: _packet(symbol),
    )
    next_id = iter((2001, 2002))

    def persist(packet, conn, **kwargs):
        conn.commit()
        if interrupt:
            raise KeyboardInterrupt()
        if fail_on_symbol == packet["symbol"]:
            raise RuntimeError("synthetic persist failure")
        packet_id = next(next_id)
        conn._conn.pending[packet_id] = {
            "symbol": packet["symbol"],
            "packet": packet,
            "live": True,
        }
        return packet_id

    monkeypatch.setattr(ATOMIC.decision_service, "persist", persist)
    monkeypatch.setenv("WATCH_QUALITY_LOCAL_SCHEDULER_ACK", ATOMIC.ACK_REQUIRED)
    monkeypatch.setattr(ATOMIC, "PROJECT_ROOT", ROOT)


def test_gate6_behavior_commits_one_verified_batch(monkeypatch):
    conn = _FakeConnection()
    _install_runtime(monkeypatch, conn)

    report = ATOMIC.run_local(2)

    assert report["status"] == "PASS_LOCAL_SCHEDULER_COMPLETED"
    assert report["database_commit_count"] == 1
    assert report["deferred_inner_commit_calls"] == 2
    assert conn.commit_calls == 1
    assert conn.rollback_calls == 0
    assert conn.closed is True
    assert sorted(conn.committed) == [2001, 2002]
    assert all(item["live_packet_ids"] == [item["packet_id"]] for item in report["persisted"])


def test_gate6_behavior_rolls_back_entire_batch_on_later_failure(monkeypatch):
    conn = _FakeConnection()
    _install_runtime(monkeypatch, conn, fail_on_symbol="BBB")

    report = ATOMIC.run_local(2)

    assert report["status"] == "BLOCKED_LOCAL_SCHEDULER_ATOMIC_ROLLBACK"
    assert report["persisted"] == []
    assert report["database_commit_count"] == 0
    assert report["atomic_rollback"] is True
    assert report["attempted_packet_ids"] == [2001]
    assert conn.commit_calls == 0
    assert conn.rollback_calls == 1
    assert conn.pending == {}
    assert conn.committed == {}
    assert conn.closed is True


def test_gate6_behavior_does_not_swallow_interrupts(monkeypatch):
    conn = _FakeConnection()
    _install_runtime(monkeypatch, conn, interrupt=True)

    with pytest.raises(KeyboardInterrupt):
        ATOMIC.run_local(2)

    assert conn.commit_calls == 0
    assert conn.closed is True
