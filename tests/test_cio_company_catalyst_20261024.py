"""C1 stored catalyst population / registered names. ANCHOR: CIO_COMPANY_CATALYST_20261024.
All source files/canonical records are isolated; no provider, DB connection or live writer.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from scripts.lib import cio_company_facts as F, cio_company_population as P, cio_instrument_record as I
from scripts.lib.data_broker.catalyst_record_readonly import get_catalyst_records_bulk
from scripts.lib.cio_prospect_builder import catalyst_facts

NOW = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)
G = '5f0c6a3e-1111-5111-8111-000000000001'
OTHER = '5f0c6a3e-1111-5111-8111-000000000002'
IDENT = {'symbol': 'SMCI', 'security_guid': G, 'subject_guid': G, 'identity_status': 'CONFIRMED'}


def write(root, rel, value):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value))


def event(**kw):
    r = {'id': 42, 'symbol': 'SMCI', 'subject_guid': G, 'headline': 'SMCI announces new server product',
         'catalyst_type': 'product', 'source': 'stored_fixture', 'source_url': 'https://example.invalid/smci/product',
         'published_at': '2026-10-23T14:00:00+00:00', 'created_at': '2026-10-24T06:10:00+00:00', 'confidence': 1.1}
    r.update(kw); r['at'] = r['published_at'] or r['created_at']
    return r


def captured(rows):
    queries = []
    result = get_catalyst_records_bulk(lambda sql, params: queries.append((sql, params)) or rows)
    assert len(queries) == 1 and 'published_at, created_at' in queries[0][0]
    return {'status': 'ok', 'rows': result, 'path': 'projection:catalyst_record'}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(P, 'resolve_security_identity', lambda *a, **k: deepcopy(IDENT))
    write(tmp_path, 'data/runtime/schwab_instrument_evidence.json', {
        'schema': 'SchwabInstrumentEvidence@v1', 'updated_at': NOW.isoformat(), 'instruments': {
            'SMCI': {'description': 'SUPER MICRO COMPUTER INC', 'observed_at': '2026-10-20T12:00:00+00:00'}}})
    write(tmp_path, 'data/cio/ticker_research_graph.jsonl', {
        'schema': 'TickerKnowledgeProfile@v1', 'symbol': 'SMCI', 'updated_at': NOW.isoformat(),
        'company': 'Super Micro Computer, Inc., together with its subsidiaries, develops and manufactures computer servers.'})
    c = {'my_watchlist': ['SMCI'], 'held': [], 'formerly_held': [], 'identities': {'SMCI': IDENT},
         'profiles': {'SMCI': {'description': 'Designs computer servers.', 'sector': 'Technology',
                               'industry': 'Computer Hardware', 'updated_at': NOW.isoformat()}},
         'catalyst_events': captured([event()]), 'gaps': []}
    return tmp_path, c


def tip(root):
    return I.InstrumentRecordStore(root / I.DEFAULT_PATH).all()[0]


def test_population_uses_real_captured_projection_and_preserves_all_original_clocks(world):
    root, c = world
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    preview = P.populate(root, c, now=NOW, env={})
    assert preview['writes'] == 0 and preview['after']['my_watchlist']['catalysts']['current'] == 1
    assert {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
    result = P.populate(root, c, apply=True, now=NOW, env={})
    f = tip(root)['research']['company_facts']; cat = f['catalyst']
    assert f['company']['value'] == 'SUPER MICRO COMPUTER INC'
    assert f['company']['observed_at'] == '2026-10-20T12:00:00+00:00'
    assert cat['published_at'] == event()['published_at'] and cat['created_at'] == event()['created_at']
    assert cat['observed_at'] == event()['created_at'] and cat['source_ref'] == 'catalyst_events#42'
    assert cat['event_id'] == 42 and cat['url'] == event()['source_url']
    assert cat['independent_verification'] == 'NOT_MEASURED' and cat['factual_verification_status'] == 'UNKNOWN'
    assert cat['source_verified_claim'] is False, 'legacy confidence threshold is not a source verification flag'
    assert result['judgment_writes'] == result['prospect_promotions'] == 0
    assert not any(k in tip(root) for k in ('stance', 'stage', 'conviction'))
    raw = (root / I.DEFAULT_PATH).read_bytes()
    again = P.populate(root, c, apply=True, now=NOW, env={})
    assert again['unchanged'] == 1 and again['writes'] == 0 and (root / I.DEFAULT_PATH).read_bytes() == raw


def test_created_only_event_is_observation_never_fabricated_publication(world):
    root, c = world; c['catalyst_events'] = captured([event(published_at=None)])
    P.populate(root, c, apply=True, now=NOW, env={})
    cat = tip(root)['research']['company_facts']['catalyst']
    assert cat['published_at'] is None and cat['observed_at'] == event()['created_at']
    assert cat['clock_kind'] == 'row_created' and cat['status'] == 'CURRENT'


@pytest.mark.parametrize('patch', [
    {'subject_guid': OTHER}, {'published_at': '2026-08-01T00:00:00+00:00'},
    {'published_at': '2026-11-01T00:00:00+00:00'}, {'published_at': None, 'created_at': None}])
def test_wrong_identity_stale_future_or_undated_events_do_not_invent_current_catalyst(world, patch):
    root, c = world; c['catalyst_events'] = captured([event(**patch)])
    P.populate(root, c, apply=True, now=NOW, env={})
    cat = tip(root)['research']['company_facts']['catalyst']
    assert cat['headline'] is None and cat['status'] == 'MISSING'


def test_proven_empty_and_uncaptured_sources_are_distinct(world):
    root, c = world; c['catalyst_events'] = captured([])
    empty = P.populate(root, c, now=NOW, env={})
    assert empty['ok'] and empty['after']['my_watchlist']['catalysts']['missing'] == 1
    c.pop('catalyst_events')
    missing = P.populate(root, c, now=NOW, env={})
    assert not missing['ok'] and any(g['scope'] == 'catalyst_events' for g in missing['source_gaps'])
    assert missing['after']['my_watchlist']['catalysts']['gaps'][0]['reason'] == 'catalyst_source_not_measured'


@pytest.mark.parametrize('name', ['Super Micro Computer, Inc.', 'T. Rowe Price Group, Inc.', 'A. O. Smith Corporation', 'AT&T Inc.'])
def test_valid_registered_names_and_legal_abbreviations_are_not_sentences(name):
    assert F.company_name_issue(name) is None


@pytest.mark.parametrize('name', ['x' * 181, 'Acme Inc., together with its subsidiaries, develops equipment.',
                                'Acme Corporation. It manufactures equipment.', 'Acme Inc. It builds servers.', 'Acme\nBusiness paragraph'])
def test_descriptions_and_multisentence_labels_are_rejected(name):
    assert F.company_name_issue(name)


def test_invalid_retained_paragraph_cannot_outvote_valid_older_registered_name(world):
    root, c = world
    old = F.missing('SMCI', G, 'fixture')
    old['company'] = {'value': 'Super Micro Computer, Inc., together with its subsidiaries, develops servers.',
                      'source': 'old_profile', 'observed_at': NOW.isoformat()}
    rec = I.new_record('SECURITY', 'SMCI', symbols=['SMCI'], **IDENT)
    rec, _ = I.apply_prospect(rec, prospect={'research': {'company_facts': old}}, fact_only=True)
    I.InstrumentRecordStore(root / I.DEFAULT_PATH).upsert_prospect(rec, fact_only=True, env={})
    P.populate(root, c, apply=True, now=NOW, env={})
    f = tip(root)['research']['company_facts']
    assert f['company']['value'] == 'SUPER MICRO COMPUTER INC'
    assert any(r.get('retained_value_rejected') for r in f['rejected_company_names'])
    raw = (root / I.DEFAULT_PATH).read_bytes()
    assert P.populate(root, c, apply=True, now=NOW, env={})['writes'] == 0
    assert (root / I.DEFAULT_PATH).read_bytes() == raw


def test_missing_name_file_mints_no_observation_clock(tmp_path):
    batch = F.collect_inputs(tmp_path, ['SMCI'], now=NOW)
    f = F.assemble('SMCI', IDENT, batch, now=NOW)
    assert batch['instrument_names'] == {} and f['company']['observed_at'] is None
    assert f['company']['value'] is None


def test_existing_lane_capture_includes_registered_catalysts_once(world, monkeypatch):
    from scripts.lib.data_broker import watch_domains
    root, c = world
    monkeypatch.setattr(watch_domains, 'membership_operator', lambda q: {'names': ['SMCI'], 'sources': {}})
    calls = []
    def q(sql, params=None):
        calls.append(sql)
        return [event()] if 'FROM catalyst_events' in sql else []
    capture = P.capture_readonly_inputs(root, q, now=NOW)
    assert capture['catalyst_events']['status'] == 'ok' and capture['catalyst_events']['rows']['SMCI']
    assert len([sql for sql in calls if 'FROM catalyst_events' in sql]) == 1
    assert all(sql.lstrip().startswith('SELECT') for sql in calls)
