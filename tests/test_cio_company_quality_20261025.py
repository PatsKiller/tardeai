"""C1 catalyst quality + display names. ANCHOR: CIO_COMPANY_QUALITY_20261025.

Real live examples (release 8a28c5728, /api/v3/data-broker/watch-curation My Watchlist) are the fixtures:
SMCI's price-prediction SEO piece and ANET's CEO share sale were chosen as "catalysts", every catalyst date was
None, and company names were registry ALL-CAPS. Isolated stores, pinned clocks; no provider, DB or credentials.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / 'scripts'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from scripts.lib import cio_company_facts as F, cio_company_quality as Q, cio_company_population as P  # noqa: E402
from scripts.lib import cio_instrument_record as I  # noqa: E402
from scripts.lib.data_broker import cio_company_facts as broker  # noqa: E402

NOW = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)
G = '5f0c6a3e-3333-5333-8333-000000000001'
IDENT = {'symbol': 'SMCI', 'security_guid': G, 'subject_guid': G, 'identity_status': 'CONFIRMED'}

# Verbatim live rows (catalyst_events, 2026-10).
SMCI_PREDICTION = {'source': 'catalyst_events', 'feed': 'google_news:24/7 Wall St.', 'catalyst_type': 'news_momentum',
                   'headline': 'SMCI Stock Price Prediction 2026-2027 | Super Micro Computer Forecast - 24/7 Wall St.',
                   'published_at': '2026-10-23T21:12:42-04:00', 'observed_at': '2026-10-24T06:46:00-04:00'}
ANET_INSIDER = {'source': 'catalyst_events', 'feed': 'google_news:Investing.com', 'catalyst_type': 'insider_buy',
                'headline': 'Arista Networks CEO Ullal sells $21m in ANET shares - Investing.com',
                'published_at': '2026-10-11T12:23:09-04:00', 'observed_at': '2026-10-11T18:45:12-04:00'}
NUAI_8K = {'source': 'catalyst_events', 'feed': 'sec_edgar', 'catalyst_type': 'regulatory_disclosure', 'event_id': 7,
           'headline': 'NUAI 8-K: Other events (Item 8.01) filed 2026-10-08', 'published_at': '2026-10-08T00:00:00-04:00',
           'observed_at': '2026-10-08T21:30:22-04:00', 'url': 'https://www.sec.gov/fixture'}


@pytest.mark.parametrize('symbol,fact,reason', [
    ('SMCI', SMCI_PREDICTION, 'price_prediction'),
    ('ANET', ANET_INSIDER, 'insider_or_holding_trade'),
    ('BETA', {'catalyst_type': 'insider_buy', 'headline': 'Beta Technologies CEO Kyle Clark sells $559,205 in stock By Investing.com - Investing.com'}, 'insider_or_holding_trade'),
    ('TSM', {'catalyst_type': 'merger_acquisition', 'headline': 'Taiwan Semiconductor Manufacturing Company Ltd. $TSM Stock Acquired by Ninety One North America Inc.'}, 'insider_or_holding_trade'),
    ('MSGM', {'catalyst_type': 'analyst_upgrade', 'headline': 'New Strong Buy Stocks for September 30th'}, 'stock_to_buy'),
    ('AAPL', {'catalyst_type': 'news_momentum', 'headline': '3 Portfolio-Worthy Stocks Hitting 52-Week Highs: AAPL, LLY & KO'}, 'stock_to_buy'),
    ('KBR', {'catalyst_type': 'analyst_upgrade', 'headline': 'KBR vs. ALFVY: Which Stock Is the Better Value Option? - Yahoo Finance'}, 'listicle'),
    ('HPE', {'catalyst_type': 'contract_win', 'headline': 'Hewlett Packard Enterprise Climbs 4% While AI Server Peers Lag; Dell Rises 2%, Super Micro'}, 'price_move'),
    ('AXTI', {'catalyst_type': 'contract_win', 'headline': "Can Surging InP Demand Strengthen AXT's Long-Term Growth Potential?"}, 'seo_commentary'),
    ('NXT', {'catalyst_type': 'analyst_upgrade', 'headline': 'NEXT plc (LON:NXT) Stock Has Average Target Price of £153.55 - MarketBeat'}, 'foreign_listing'),
    ('SPCX', {'catalyst_type': 'earnings_miss', 'headline': '3 reasons SpaceX could fall short of $1 trillion revenue goal'}, 'listicle'),
    ('SCHD', {'catalyst_type': 'dividend_increase', 'headline': 'SCHD’s Price May Be Soaring, but Its Dividend Isn’t Keeping Up - Yahoo Finance'}, 'seo_commentary'),
    ('JEPI', {'catalyst_type': 'dividend_increase', 'headline': 'JEPI Built Your Income Strategy. JEPQ Pays You Better for It. - 24/7 Wall St.'}, 'seo_commentary'),
    ('SPCX', {'catalyst_type': 'earnings_beat', 'headline': 'S&P 500, Nasdaq Gain, Powered By Meta, Tesla Stock — SPCX, META, TSLA, SKYD, IBM In Focus'}, 'market_wrap'),
    ('MDLN', {'catalyst_type': 'news_momentum', 'feed': 'google_news:Stock Traders Daily', 'headline': 'Behavioral Patterns of MDLN and Institutional Flows - Stock Traders Daily'}, 'excluded_publisher'),
])
def test_real_non_catalysts_are_news_with_a_named_reason(symbol, fact, reason):
    v = Q.classify(fact, symbol=symbol, names=[])
    assert v['class'] == Q.NEWS and v['reason'] == reason


@pytest.mark.parametrize('symbol,fact,etype', [
    ('NUAI', NUAI_8K, 'sec_8k'),
    ('AUUD', {'catalyst_type': 'material_agreement', 'headline': 'AUUD 8-K: Entry into a material agreement (Item 1.01) filed 2026-10-22'}, 'sec_8k'),
    ('LMT', {'catalyst_type': 'merger_acquisition', 'headline': 'LMT Stock Snaps Three-Day Winning Streak: Lockheed Martin Acquires Ultra Maritime For $3.4 Billion'}, 'm_and_a'),
    ('GEV', {'catalyst_type': 'earnings_miss', 'headline': 'GEV Stock Drops On Q2 Earnings Miss – CEO Raises Guidance, Says Data Center Orders Have Al'}, 'results'),
])
def test_material_corporate_events_qualify_even_with_price_move_wording(symbol, fact, etype):
    v = Q.classify(fact, symbol=symbol, names=[])
    assert v == {'class': Q.MATERIAL, 'event_type': etype, 'reason': None}


def test_ticker_match_is_case_sensitive_and_other_company_stories_are_not_this_company():
    saudi = {'catalyst_type': 'merger_acquisition', 'headline': 'Saudi Stock Exchange Main Index agrees merger'}
    assert Q.classify(saudi, symbol='MAIN', names=['Main Street Capital'])['reason'] == 'headline_does_not_name_subject'
    ok = {'catalyst_type': 'merger_acquisition', 'headline': 'Main Street Capital to acquire lender for $200 million'}
    assert Q.classify(ok, symbol='MAIN', names=['Main Street Capital'])['class'] == Q.MATERIAL


def test_fund_news_is_commentary_and_reported_deals_are_not_events():
    schd = {'catalyst_type': 'dividend_increase', 'headline': 'SCHD puts dividend investors at critical crossroads - thestreet.com'}
    assert Q.classify(schd, symbol='SCHD', names=['Schwab US Dividend Equity ETF'])['reason'] == 'fund_commentary'
    spcx = {'catalyst_type': 'merger_acquisition', 'headline': 'TSLA, SPCX Slip Overnight: Musk Reportedly Pushes Merger Before Exit'}
    assert Q.classify(spcx, symbol='SPCX', names=['Space Exploration Technologies'])['reason'] == 'seo_commentary'


def test_rules_are_data_driven(tmp_path):
    cfg = json.loads((ROOT / Q.CONFIG_REL).read_text())
    cfg['catalyst']['excluded_headline_patterns']['test_only'] = ['\\bfixture-banned\\b']
    path = tmp_path / 'rules.json'
    path.write_text(json.dumps(cfg))
    fact = {'catalyst_type': 'regulatory_disclosure', 'headline': 'NUAI 8-K fixture-banned filing'}
    assert Q.classify(fact, symbol='NUAI', path=path)['reason'] == 'test_only'
    assert Q.classify(fact, symbol='NUAI')['class'] == Q.MATERIAL


@pytest.mark.parametrize('sym,legal,finviz,desc,want', [
    ('DXCM', 'DEXCOM INC', 'Dexcom Inc', 'DexCom, Inc., a medical device company, focuses on...', 'Dexcom'),
    ('ANET', 'ARISTA NETWORKS INC', 'Arista Networks Inc', None, 'Arista Networks'),
    ('SMCI', 'SUPER MICRO COMPUTER', None, 'Super Micro Computer, Inc., together with its subsidiaries, develops...', 'Super Micro Computer'),
    ('FATN', 'FATPIPE INC UT', 'Fatpipe Inc', 'FatPipe, Inc. develops application-aware...', 'FatPipe'),
    ('LDOS', 'LEIDOS HLDGS INC', 'Leidos Holdings Inc', None, 'Leidos'),
    ('ZZZZ', 'ACME WIDGETS HOLDINGS INC CL A', None, None, 'Acme Widgets'),
    ('KBR', 'KBR INC', None, None, 'KBR'),
    ('SCHD', 'Schwab US Dividend Equity ETF', 'Schwab US Dividend Equity ETF', None, 'Schwab US Dividend Equity ETF'),
])
def test_display_name_is_common_name_with_legal_name_kept(sym, legal, finviz, desc, want):
    d = Q.display_name(sym, legal, finviz_name=finviz, description=desc)
    assert d['display_name'] == want and d['legal_name'] == legal
    assert d['display_name'] != d['display_name'].upper() or len(d['display_name']) <= 4


def inputs(profile=None, errors=()):
    return {'errors': list(errors), 'finviz': {}, 'identity_profiles': {},
            'instrument_names': {'SMCI': {'company': 'SUPER MICRO COMPUTER', 'updated_at': '2026-10-20T12:00:00+00:00',
                                          'source': 'schwab_instrument_evidence.description'}},
            'profiles': {'SMCI': {'description': 'Super Micro Computer, Inc., together with its subsidiaries, develops servers.',
                                  'updated_at': (NOW - timedelta(days=2)).isoformat(), **(profile or {})}}}


def assemble(facts, **kw):
    return F.assemble('SMCI', IDENT, kw.pop('inputs', None) or inputs(), catalyst={'facts': facts}, now=NOW, **kw)


def test_smci_prediction_is_recent_news_never_the_catalyst_and_none_on_file_has_reason():
    f = assemble([deepcopy(SMCI_PREDICTION)])
    cat = f['catalyst']
    assert cat['status'] == 'NONE_ON_FILE' and cat['headline'] is None
    assert cat['missing_reason'] == 'no_qualifying_catalyst_only_news_on_file' and 'price prediction' in cat['reason']
    assert f['recent_news'][0]['headline'] == SMCI_PREDICTION['headline']
    assert f['recent_news'][0]['date'] == '2026-10-24' and f['recent_news'][0]['source_label'] == '24/7 Wall St.'
    assert f['company']['display_name'] == 'Super Micro Computer' and f['company']['value'] == 'SUPER MICRO COMPUTER'
    assert f['company']['legal_name'] == 'SUPER MICRO COMPUTER'


def test_upcoming_dated_event_ranks_before_newer_material_event_and_date_is_the_event_date():
    f = assemble([dict(NUAI_8K, headline='SMCI 8-K: Other events (Item 8.01) filed 2026-10-20',
                       published_at='2026-10-20T00:00:00+00:00')], inputs=inputs({'next_earnings_date': '2026-11-04'}))
    cat = f['catalyst']
    assert cat['status'] == 'CURRENT' and cat['catalyst_class'] == Q.UPCOMING and cat['event_type'] == 'earnings'
    assert cat['date'] == '2026-11-04' and cat['date_kind'] == 'event_date' and cat['source_label'] == 'Earnings calendar'
    snap = {G: {'company_facts': f, 'review_lifecycle': {'status': 'MISSING'}}}
    assert broker.for_security(snap, 'SMCI', G, now=NOW + timedelta(days=5))['company_facts']['catalyst']['status'] == 'CURRENT'
    assert broker.for_security(snap, 'SMCI', G, now=NOW + timedelta(days=12))['company_facts']['catalyst']['status'] == 'STALE'


def test_material_event_selected_with_publication_date_and_source_when_no_upcoming():
    f = assemble([deepcopy(SMCI_PREDICTION), dict(NUAI_8K, headline='SMCI 8-K: Results of operations (Item 2.02) filed 2026-10-20',
                                                  catalyst_type='earnings', published_at='2026-10-20T13:00:00+00:00')],
                 inputs=inputs({'next_earnings_date': '2026-09-01'}))  # past schedule is not upcoming
    cat = f['catalyst']
    assert cat['catalyst_class'] == Q.MATERIAL and cat['event_type'] == 'results'
    assert cat['date'] == '2026-10-20' and cat['date_kind'] == 'published' and cat['source_label'] == 'SEC EDGAR'
    assert cat['published_at'] == '2026-10-20T13:00:00+00:00', 'original source clock preserved'
    assert [n['not_catalyst_reason'] for n in f['recent_news']] == ['price_prediction']


def test_stale_profile_schedule_is_not_an_upcoming_event():
    old = inputs({'next_earnings_date': '2026-11-04', 'updated_at': (NOW - timedelta(days=120)).isoformat()})
    assert assemble([], inputs=old)['catalyst']['status'] == 'NONE_ON_FILE'


def test_unmeasured_source_stays_missing_not_none_on_file():
    cat = assemble([], inputs=inputs(errors=['catalyst_events:not_captured']))['catalyst']
    assert cat['status'] == 'MISSING' and cat['missing_reason'] == 'catalyst_source_not_measured'


def test_legacy_stored_junk_catalyst_is_projected_as_none_on_file_and_gets_display_name():
    legacy = F.missing('ANET', G, 'fixture')
    legacy.update(status='AVAILABLE', company={'value': 'ARISTA NETWORKS INC', 'source': 'schwab'},
                  description={'value': 'Arista Networks, Inc. engages in cloud networking.'},
                  catalyst={**ANET_INSIDER, 'status': 'CURRENT', 'missing_reason': None})
    snap = {G: {'company_facts': legacy, 'review_lifecycle': {'status': 'MISSING'}}}
    out = broker.for_security(snap, 'ANET', G, now=NOW)['company_facts']
    assert out['company']['display_name'] == 'Arista Networks' and out['company']['legal_name'] == 'ARISTA NETWORKS INC'
    assert out['catalyst']['status'] == 'NONE_ON_FILE' and out['catalyst']['headline'] is None
    assert out['recent_news'][0]['date'] == '2026-10-11' and out['recent_news'][0]['source_label'] == 'Investing.com'
    assert legacy['catalyst']['status'] == 'CURRENT', 'read projection never mutates the saved record'


def test_population_rewrites_retained_junk_catalyst_and_reports_dated_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(P, 'resolve_security_identity', lambda *a, **k: deepcopy(IDENT))
    monkeypatch.setattr(P, 'stored_catalysts', lambda *_: {})
    monkeypatch.setattr(P.facts, 'collect_inputs', lambda *a, **kw: {k: v for k, v in inputs().items() if k != 'profiles'})
    old = F.missing('SMCI', G, 'fixture')
    old.update(status='AVAILABLE', catalyst={**SMCI_PREDICTION, 'status': 'CURRENT'})
    rec = I.new_record('SECURITY', 'SMCI', symbols=['SMCI'], **IDENT)
    rec, _ = I.apply_prospect(rec, prospect={'research': {'company_facts': old}}, fact_only=True)
    I.InstrumentRecordStore(tmp_path / I.DEFAULT_PATH).upsert_prospect(rec, fact_only=True, env={})
    row = dict(NUAI_8K, id=9, symbol='SMCI', subject_guid=G, headline='SMCI 8-K: Entry into a material agreement (Item 1.01) filed 2026-10-21',
               catalyst_type='material_agreement', published_at='2026-10-21T00:00:00+00:00', at='2026-10-21T00:00:00+00:00')
    capture = {'my_watchlist': ['SMCI'], 'held': [], 'formerly_held': [], 'identities': {'SMCI': IDENT}, 'gaps': [],
               'profiles': {'SMCI': inputs()['profiles']['SMCI']},
               'catalyst_events': {'status': 'ok', 'rows': {'SMCI': [row]}}}
    r = P.populate(tmp_path, capture, now=NOW, env={})
    before, after = r['before']['my_watchlist']['catalysts'], r['after']['my_watchlist']['catalysts']
    # Stored legacy junk is CURRENT on the record, but the read projection already shows it as None on file.
    assert before['stored_current'] == 1 and before['current'] == 0 and before['none_on_file'] == 1
    assert after['current'] == after['stored_current'] == 1 and after['dated'] == 1 and after['by_class'] == {Q.MATERIAL: 1}
    P.populate(tmp_path, capture, apply=True, now=NOW, env={})
    f = I.InstrumentRecordStore(tmp_path / I.DEFAULT_PATH).all()[0]['research']['company_facts']
    assert f['catalyst']['headline'].startswith('SMCI 8-K') and f['catalyst']['date'] == '2026-10-21'
    assert f['recent_news'][0]['headline'] == SMCI_PREDICTION['headline']


def test_capture_reads_deeper_catalyst_window_in_one_query(tmp_path, monkeypatch):
    from scripts.lib.data_broker import watch_domains
    monkeypatch.setattr(watch_domains, 'membership_operator', lambda q: {'names': ['SMCI'], 'sources': {}})
    calls = []
    P.capture_readonly_inputs(tmp_path, lambda sql, params=None: calls.append((sql, params)) or [], now=NOW)
    cat = [p for sql, p in calls if 'FROM catalyst_events' in sql]
    assert len(cat) == 1 and cat[0][1] == P.CAPTURE_CATALYSTS_PER_SYMBOL * 3
