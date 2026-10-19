"""Real host fencing primitives with temporary ledgers and fake child effects; no scheduler/live service changes."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from scripts import n8n_run_executor as X
from scripts.lib import effect_claim as E
from scripts.lib.n8n_coordination_ledger import CoordinationLedger
from tests import test_effect_claim_20261014 as T


def test_owner_change_cannot_land_between_executor_effect_claim_and_spawn(tmp_path):
    ledger = CoordinationLedger(tmp_path/'ledger.sqlite')
    store = E.EffectClaimStore(ledger)
    manifest = E.handover_manifest_path(ledger.path)
    E.set_owner_with_manifest(store, manifest, T.PROCESS, 'n8n', expect_epoch=None, by='fixture', now=T.T0)
    gate = X.EffectGate(store, {T.LANE: {'process': T.PROCESS, 'input_version': 'v1'}},
                        clock=lambda: T.T0+60, ledger_path=ledger.path)
    real_begin = gate.begin
    attempted, changed = threading.Event(), threading.Event()
    errors, observed = [], []

    def change_owner():
        attempted.set()
        try:
            E.set_owner_with_manifest(store, manifest, T.PROCESS, 'cron', expect_epoch=1,
                                      by='fixture', now=T.T0+61)
        except Exception as exc:
            errors.append(exc)
        finally:
            changed.set()

    worker = threading.Thread(target=change_owner)
    def claim_then_race(*args):
        result = real_begin(*args)
        worker.start()
        assert attempted.wait(timeout=3)
        changed.wait(timeout=0.5)
        return result
    gate.begin = claim_then_race
    def spawn(*args, **kwargs):
        owner = store.owner(T.PROCESS)
        observed.append((owner['owner'], owner['epoch']))
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    try:
        X.execute({'run_id': T.RUN_ID, 'lane_id': T.LANE, 'mode': 'live',
                   'requested_at': T.T0+30, 'attempt': 1}, T._entry(tmp_path), env={}, state_root=tmp_path/'state',
                  code_root=tmp_path, runner=spawn, effects=gate)
        worker.join(timeout=3)
        assert not worker.is_alive() and errors == []
        assert observed == [('n8n', 1)], 'a shared owner switch must wait until the old admitted child has started'
    finally:
        worker.join(timeout=3)
        ledger.close()


@pytest.mark.parametrize('runner_kind', ['v1', 'heartbeat'])
def test_fence_releases_after_actual_popen_and_late_effect_stays_unknown(tmp_path, monkeypatch, runner_kind):
    ledger = CoordinationLedger(tmp_path/'ledger.sqlite')
    store = E.EffectClaimStore(ledger)
    manifest = E.handover_manifest_path(ledger.path)
    E.set_owner_with_manifest(store, manifest, T.PROCESS, 'n8n', expect_epoch=None, by='fixture', now=T.T0)
    gate = X.EffectGate(store, {T.LANE: {'process': T.PROCESS, 'input_version': 'v1'}},
                        clock=lambda: T.T0+60, ledger_path=ledger.path)
    spawned, child_callbacks = [], []

    class FakeChild:
        pid, returncode = 12345, 0
        def __init__(self, argv, **kwargs):
            owner = store.owner(T.PROCESS)
            spawned.append((owner['owner'], owner['epoch']))
            self.token = kwargs['env'][E.FENCE_ENV]
        def communicate(self, **kwargs):
            # This is AFTER Popen returned. Holding the global lock until child completion would time out here.
            E.set_owner_with_manifest(store, manifest, T.PROCESS, 'cron', expect_epoch=1,
                                      by='fixture', now=T.T0+61)
            with pytest.raises(E.EffectFenceError, match='fence_epoch_moved'):
                store.assert_fence(self.token, now=T.T0+61)
            return '', ''

    monkeypatch.setattr(X.subprocess, 'Popen', FakeChild)
    monkeypatch.setattr(X, '_code_sha', lambda root: None)
    runner = X._subprocess_runner if runner_kind == 'v1' else X.heartbeat_runner(
        lambda pid: child_callbacks.append(pid), lambda pid: pytest.fail('fake child never waits'))
    try:
        receipt = X.execute({'run_id': T.RUN_ID, 'lane_id': T.LANE, 'mode': 'live',
                             'requested_at': T.T0+30, 'attempt': 1}, T._entry(tmp_path), env={}, state_root=tmp_path/'state',
                            code_root=tmp_path, runner=runner, effects=gate)
        assert spawned == [('n8n', 1)] and store.owner(T.PROCESS)['epoch'] == 2
        assert receipt['effect']['final_state'] == E.STATE_UNKNOWN and receipt['effect']['held_for_reconciliation']
        assert child_callbacks == ([] if runner_kind == 'v1' else [12345])
    finally:
        ledger.close()


def test_unavailable_handover_fence_refuses_before_claim_or_child(tmp_path, monkeypatch):
    ledger = CoordinationLedger(tmp_path/'ledger.sqlite')
    store = E.EffectClaimStore(ledger)
    E.set_owner_with_manifest(store, E.handover_manifest_path(ledger.path), T.PROCESS, 'n8n',
                              expect_epoch=None, by='fixture', now=T.T0)
    blocked_parent = tmp_path/'not-a-directory'
    blocked_parent.write_text('fixture')
    monkeypatch.setattr(X, 'handover_manifest_path', lambda path: blocked_parent/'manifest.json')
    gate = X.EffectGate(store, {T.LANE: {'process': T.PROCESS, 'input_version': 'v1'}},
                        clock=lambda: T.T0+60, ledger_path=ledger.path)
    try:
        receipt = X.execute({'run_id': T.RUN_ID, 'lane_id': T.LANE, 'mode': 'live',
                             'requested_at': T.T0+30}, T._entry(tmp_path), env={}, state_root=tmp_path/'state',
                            code_root=tmp_path, runner=lambda *a, **kw: pytest.fail('unfenced child invoked'), effects=gate)
        assert receipt['state'] == 'RUN_REFUSED' and receipt['reason'] == 'effect:handover_lock_unavailable'
        assert store.get(T.KEY) is None
    finally:
        ledger.close()
