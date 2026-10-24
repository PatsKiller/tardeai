"""Canonical Ask->MyWatchlist writer/consumer proof. ANCHOR: CIO_ASK_TRACKING_CANONICAL_20261024.
No DB, provider, broker, credential or live HTTP. Actual command + reader, injected fake SQL state.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from scripts.lib.cio_ask_contract import EntityRef
from scripts.lib import cio_ask_tracking as T
from scripts import api_v3_watch_commands as commands
from scripts.lib.data_broker.watch_domains import membership_operator
from scripts.lib.data_broker.watch_curation import my_rows

GUID = '5f0c6a3e-1111-5111-8111-000000000001'
OTHER = '5f0c6a3e-1111-5111-8111-000000000002'
AT = '2026-10-24T22:00:00+00:00'
ENTITY = EntityRef(name='Tesla', symbol='TSLA', security_guid=GUID)


class DB:
    def __init__(self):
        self.stars = {}; self.events = []; self.writes = []; self.reads = 0
        self.fail_after_write = False; self.hide_after_write = False; self.fail_initial = False

    def query(self, sql, params=None, fetch='all'):
        assert sql.lstrip().startswith('SELECT'), 'new writer outside canonical command'
        self.reads += 1
        if self.fail_initial or (self.fail_after_write and self.writes):
            raise RuntimeError('DO_NOT_RENDER_QUERY_CONTEXT')
        if 'FROM operator_starred_symbols' in sql:
            if self.hide_after_write and self.writes: return []
            return [{'s': s, 'at': at, 'ref': None, 'label': None} for s, at in self.stars.items()]
        if 'FROM watchlist_items' in sql or 'FROM watch_directives' in sql: return []
        if 'FROM watchlist_events' in sql:
            latest = {}
            for e in self.events: latest[e['s']] = e
            return list(latest.values())
        pytest.fail('unexpected source query')

    def execute(self, sql, params=None):
        self.writes.append((sql, params))
        if sql.startswith('INSERT INTO operator_starred_symbols'):
            self.stars[params[0]] = AT
        elif sql.startswith('INSERT INTO watchlist_events'):
            self.events.append({'s': params[1], 'event_type': params[0], 'created_at': AT})
            assert json.loads(params[3])['surface'] == 'ask_the_cio'
        else: pytest.fail('unexpected mutation; no removal/update by tracking adapter')


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, '_principal', lambda: 'operator-fixture')
    db = DB()
    backend = T.MyWatchlistBackend(db_execute=db.execute, db_query=db.query,
        identity_lookup=lambda s: {'symbol': s, 'security_guid': GUID, 'identity_status': 'CONFIRMED'}, root=tmp_path, now=lambda: AT)
    return tmp_path, db, backend


def add(backend, entity=ENTITY, thread='thread-fixture'):
    return backend.add_entity(entity, thesis='What is the current thesis?', thread_id=thread)


def test_default_tracker_is_canonical_and_constructor_has_no_io(tmp_path,monkeypatch):
    monkeypatch.setenv('TRADEAI_ROOT', str(tmp_path))
    assert isinstance(T.Tracker().watchlist, T.MyWatchlistBackend)
    assert not list(tmp_path.rglob('*'))


def test_actual_canonical_command_to_actual_membership_reader_and_curation(world):
    root, db, backend = world
    tracker = T.Tracker(watchlist=backend, enabled_steps={'cio_record': False, 'directive': False})
    r = tracker.track(ENTITY, question='Hedge context?', ask_id='ask-fixture', thread_id='thread-fixture', channel='cc')['watchlist']
    assert r['action'] == 'added' and r['membership_verified'] is True
    assert r['security_guid'] == GUID and len(db.writes) == 2
    assert r['membership_verified_at'] == AT and r['membership_reasons'] == ['starred']
    assert all('watchlist.json' not in sql for sql, _ in db.writes)
    assert not (root / 'data/portfolios/state/watchlist.json').exists()
    observed = membership_operator(db.query)
    assert set(observed['names']) == {'TSLA'}
    rows = my_rows(observed['names'], lambda s: {'symbol': s, 'starred': True, 'lane': 'forming', 'conviction': None}, {})
    assert [r['symbol'] for r in rows] == ['TSLA']
    event_write = db.writes[1]
    assert 'Ask thread thread-fixture' in event_write[1][2]


def test_second_question_or_replay_preserves_existing_operator_entry_without_event_spam(world):
    root, db, backend = world
    first = add(backend); count = len(db.writes)
    assert first['membership_verified']
    second = add(backend, thread='another-thread')
    assert second['action'] == 'already_present' and second['created_by_ask'] is False
    assert second['membership_verified'] and len(db.writes) == count


def test_preexisting_operator_member_is_not_rewritten(world):
    root, db, backend = world; db.stars['TSLA'] = '2026-09-01T00:00:00+00:00'
    r = add(backend)
    assert r['action'] == 'already_present' and r['membership_verified'] and not db.writes
    assert db.stars['TSLA'] == '2026-09-01T00:00:00+00:00'


def test_actual_add_event_reverses_prior_explicit_removal_through_canonical_writer(world):
    root, db, backend = world
    db.events.append({'s': 'TSLA', 'event_type': 'watch_mine_removed', 'created_at': AT})
    assert 'TSLA' not in membership_operator(db.query)['names']
    r = add(backend)
    assert r['membership_verified'] and membership_operator(db.query)['names']['TSLA']['starred']
    assert db.events[-1]['event_type'] == 'watch_mine_added'


@pytest.mark.parametrize('entity', [EntityRef(name='Tesla',symbol='TSLA'),
    EntityRef(name='Tesla',symbol='TSLA',security_guid=GUID,resolution='AMBIGUOUS'),
    EntityRef(name='Private company',kind='private_entity',entity_guid='private-fixture')])
def test_unconfirmed_or_unlisted_entities_do_not_write_canonical_membership(world,entity):
    root,db,backend=world
    r=add(backend,entity)
    assert not r['membership_verified'] and not db.writes


def test_wrong_guid_is_rejected_before_read_or_write(world):
    root,db,backend=world
    r=add(backend,EntityRef(name='Tesla',symbol='TSLA',security_guid=OTHER))
    assert r['reason']=='resolved_security_guid_mismatch' and db.reads==0 and not db.writes


def test_command_acceptance_without_consumer_visibility_never_verifies(world):
    root,db,backend=world;db.hide_after_write=True
    r=add(backend)
    assert r['command_accepted'] is True and r['membership_verified'] is False
    assert r['reason']=='canonical_membership_readback_unproven' and len(db.writes)==2


def test_failed_initial_read_refuses_write_and_sanitizes_context(world):
    root,db,backend=world;db.fail_initial=True
    r=add(backend)
    assert r['action']=='failed' and not r['membership_verified'] and not db.writes
    assert 'DO_NOT_RENDER_QUERY_CONTEXT' not in json.dumps(r)


def test_failed_postwrite_read_is_partial_not_green_or_automatically_repaired(world):
    root,db,backend=world;db.fail_after_write=True
    r=add(backend)
    assert not r['membership_verified'] and r['reason']=='canonical_membership_readback_unproven'
    assert len(db.writes)==2


def test_failed_or_partial_canonical_command_is_not_a_verified_tracking_claim(world):
    root,db,backend=world
    backend.command=lambda *a,**k:{'ok':False,'detail':'DO_NOT_RENDER_QUERY_CONTEXT'}
    r=add(backend)
    assert not r['membership_verified'] and r['reason']=='canonical_watch_command_failed_or_partial'
    assert 'DO_NOT_RENDER_QUERY_CONTEXT' not in json.dumps(r)


def test_untrack_never_removes_shared_operator_or_other_thread_membership(world):
    root,db,backend=world;add(backend);count=len(db.writes)
    r=backend.release('TSLA',thread_id='thread-fixture')
    assert r['action']=='kept' and r['membership_verified']
    assert r['reason']=='question_untracked_operator_membership_requires_explicit_remove'
    assert len(db.writes)==count and 'TSLA' in membership_operator(db.query)['names']


def test_explicit_legacy_adapter_cannot_verify_canonical_membership(tmp_path):
    adapter=T.WatchlistFile(tmp_path/'legacy-fixture.json')
    r=adapter.add('TSLA',thesis='legacy fixture',thread_id='fixture')
    assert r['action']=='added' and r['membership_verified'] is False
    assert r['membership_source']=='legacy_watchlist_file'


def test_identity_change_during_write_cannot_verify_another_security(world):
    root, db, backend = world
    identities = iter([GUID, OTHER])
    backend.identity_lookup = lambda s: {'symbol': s, 'security_guid': next(identities), 'identity_status': 'CONFIRMED'}
    r = add(backend)
    assert r['command_accepted'] and not r['membership_verified']
    assert r['reason'] == 'security_identity_changed_before_readback' and len(db.writes) == 2


def test_identity_refusal_cannot_be_bypassed_by_cio_or_operator_directive(world):
    root, db, backend = world
    class NoWrite:
        def note_question(self, *a, **kw): pytest.fail('CIO write bypassed identity refusal')
        def create(self, *a, **kw): pytest.fail('directive write bypassed identity refusal')
    tracker = T.Tracker(watchlist=backend, record=NoWrite(), directives=NoWrite())
    r = tracker.track(EntityRef(name='Wrong identity', symbol='TSLA', security_guid=OTHER),
        question='fixture', ask_id='fixture', thread_id='fixture', channel='cc')
    assert not r['watchlist']['membership_verified'] and not db.writes
    assert r['cio_record']['action'] == r['directive']['action'] == 'skipped'


def test_registry_failure_is_unmeasured_and_cannot_cause_later_tracking_writes(world):
    root, db, backend = world
    backend.identity_lookup = lambda s: (_ for _ in ()).throw(RuntimeError('DO_NOT_RENDER_QUERY_CONTEXT'))
    class NoWrite:
        def note_question(self, *a, **kw): pytest.fail('CIO write bypassed registry failure')
        def create(self, *a, **kw): pytest.fail('directive write bypassed registry failure')
    tracker = T.Tracker(watchlist=backend, record=NoWrite(), directives=NoWrite())
    r = tracker.track(ENTITY, question='fixture', ask_id='fixture', thread_id='fixture', channel='cc')
    assert r['watchlist']['reason'] == 'security_identity_unavailable' and not db.writes
    assert r['cio_record']['action'] == r['directive']['action'] == 'skipped'
    assert 'DO_NOT_RENDER_QUERY_CONTEXT' not in json.dumps(r)
