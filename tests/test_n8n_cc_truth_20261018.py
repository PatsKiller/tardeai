"""Read-model truth: fake files/SQLite only, never host effects."""
import json,sqlite3
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pytest
from scripts.lib.data_broker import n8n_today as N
from scripts.lib import n8n_coordination_projection as P

NOW=datetime(2026,10,18,16,tzinfo=timezone.utc)

def test_missing_receipt_source_is_unknown_not_zero(tmp_path):
    out=N.build(tmp_path,NOW)
    assert out['runs']['totals']['live'] is None
    assert out['diagnoses']['total'] is None
    assert out['status']=='UNAVAILABLE'


def test_process_keys_are_in_explicit_today_namespace_coverage(tmp_path):
    directory=tmp_path/N.RUNS_REL;directory.mkdir(parents=True)
    rid='p:fixture-learning:live:20261018T1100'
    (directory/(rid+'.json')).write_text(json.dumps({'run_id':rid,'lane_id':'fixture-learning','state':'RUN_DONE','mode':'live','finished_at':'2026-10-18T15:00:00+00:00'}))
    out=N.build(tmp_path,NOW)
    assert out['runs']['totals']['live']==1
    assert 'p' in out.get('coverage',{}).get('run_namespaces',{}).get('included',[])


def test_missing_ledger_and_missing_table_are_unavailable(tmp_path):
    out=P.project(tmp_path/'missing.sqlite',now=NOW)
    assert out['count'] is None and out['status']=='UNAVAILABLE'
    path=tmp_path/'empty.sqlite';sqlite3.connect(path).close()
    out=P.project_runs(path,now=NOW)
    assert out['count'] is None and out['status']=='UNAVAILABLE'


def test_detail_limit_is_not_the_total_aggregation_window(tmp_path):
    path=tmp_path/'runs.sqlite'
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE runs(run_id TEXT,lane_id TEXT,mode TEXT,state TEXT,requested_at TEXT,started_at TEXT,finished_at TEXT,receipt_json TEXT)')
    db.executemany('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)',[(f'd:fixture:live:slot{i}','fixture','live','RUN_DONE','2026-10-17T01:00:00+00:00',None,'2026-10-17T01:01:00+00:00','{}') for i in range(600)])
    db.commit();db.close()
    out=P.project_runs(path,limit=500,now=NOW)
    assert out.get('total_count')==600
    assert out.get('coverage',{}).get('items_truncated') is True
    assert out.get('summary',{}).get('by_state',{}).get('RUN_DONE')==600


def test_stale_host_record_cannot_keep_a_success_spotlight(tmp_path):
    path=tmp_path/'data/runtime/n8n_incident_fanin_last.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'ok':True,'as_of':(NOW-timedelta(days=7)).isoformat(),'mode':'live'}))
    rows=P.lane_spotlights({'TRADEAI_STATE_ROOT':str(tmp_path)},now=NOW)
    row=next(r for r in rows if r['lane_id']=='n8n-incident-fanin')
    assert row.get('status')=='STALE'
    assert row.get('ok') is None


def test_first_live_receipt_is_not_a_cutover_receipt(tmp_path):
    path=tmp_path/N.RUNS_REL;path.mkdir(parents=True)
    (path/'d:fixture:live:20261018T1100.json').write_text(json.dumps({'state':'RUN_DONE','mode':'live'}))
    out=N.build(tmp_path,NOW)
    assert not out['cutovers_today']


def empty_sources(root):
    (root/N.RUNS_REL).mkdir(parents=True)
    (root/N.CUTOVER_REL).mkdir(parents=True)
    for rel in (N.RELAY_REL,N.DIAG_REL):
        (root/rel).parent.mkdir(parents=True,exist_ok=True);(root/rel).write_text('')


def put(root,rid,**fields):
    (root/N.RUNS_REL/(rid+'.json')).write_text(json.dumps({'run_id':rid,'lane_id':'fixture','mode':'live','state':'RUN_DONE',**fields}))


def test_valid_empty_read_is_zero_but_missing_stream_is_unknown(tmp_path):
    empty_sources(tmp_path)
    out=N.build(tmp_path,NOW)
    assert out['status']=='OK' and out['runs']['totals']['live']==0 and out['diagnoses']['total']==0
    (tmp_path/N.DIAG_REL).unlink()
    out=N.build(tmp_path,NOW)
    assert out['status']=='PARTIAL' and out['diagnoses']['total'] is None and out['runs']['totals']['live']==0


def test_read_caps_and_corrupt_records_never_establish_full_totals(tmp_path,monkeypatch):
    empty_sources(tmp_path)
    for n in ('1100','1110'):put(tmp_path,'d:fixture:live:20261018T'+n)
    monkeypatch.setattr(N,'MAX_RUN_FILES',1)
    out=N.build(tmp_path,NOW)
    assert out['runs']['totals']['live'] is None and out['runs']['observed_totals']['live']==1
    assert out['coverage']['sources']['runs']['candidate_files']==2
    monkeypatch.setattr(N,'MAX_RUN_FILES',5000)
    (tmp_path/N.RUNS_REL/'d:fixture:live:20261018T1100.json').write_text('{broken')
    out=N.build(tmp_path,NOW)
    assert out['runs']['totals']['live'] is None and out['coverage']['sources']['runs']['invalid_files']==1


def test_live_requested_dry_executed_retry_counts_effective_mode(tmp_path):
    empty_sources(tmp_path)
    put(tmp_path,'p:fixture:live:20261018T1100:a2',mode='dry_run',stage_clamp={'effective_mode':'dry_run'})
    out=N.build(tmp_path,NOW)
    assert out['runs']['totals']['live']==0 and out['runs']['totals']['dry_run']==1
    assert out['coverage']['sources']['runs']['read_files']==1


def test_unknown_effective_mode_is_not_a_known_zero_live_total(tmp_path):
    empty_sources(tmp_path)
    p=tmp_path/N.RUNS_REL/'d:fixture:live:20261018T1100.json'
    p.write_text(json.dumps({'run_id':p.stem,'state':'RUN_DONE'}))
    out=N.build(tmp_path,NOW)
    assert out['runs']['totals']['live'] is None
    assert out['coverage']['sources']['runs']['unknown_effective_mode_receipts']==1


def test_out_of_order_log_rows_and_tail_cap_are_explicit(tmp_path):
    path=tmp_path/'fixture.jsonl'
    today={'at':'2026-10-18T15:00:00+00:00'};old={'at':'2026-10-17T15:00:00+00:00'}
    path.write_text('\n'.join(json.dumps(r) for r in (today,old,today)))
    rows,meta=N._tail_source(path,datetime(2026,10,18,4,tzinfo=timezone.utc),NOW,max_bytes=4096)
    assert len(rows)==2 and meta['complete']
    rows,meta=N._tail_source(path,datetime(2026,10,18,4,tzinfo=timezone.utc),NOW,max_bytes=50)
    assert meta['truncated'] and not meta['complete'] and meta['bytes_read']<=50


def test_cached_last_good_age_advances_and_survives_unavailable_source(tmp_path):
    empty_sources(tmp_path)
    first=N.get_n8n_today(tmp_path,NOW,ttl_s=60)
    assert first['last_good_age_s']==0
    later=N.get_n8n_today(tmp_path,NOW+timedelta(seconds=30),ttl_s=60)
    assert later['cache']=='HIT' and later['last_good_age_s']==30
    (tmp_path/N.DIAG_REL).unlink()
    lost=N.get_n8n_today(tmp_path,NOW+timedelta(seconds=40),ttl_s=60)
    assert lost['diagnoses']['total'] is None and lost['last_good_age_s']==40


@pytest.mark.parametrize('instant,midnight',[('2026-03-08T20:00:00+00:00','2026-03-08T05:00:00+00:00'),('2026-11-01T20:00:00+00:00','2026-11-01T04:00:00+00:00')])
def test_window_uses_et_dst_midnight(instant,midnight):
    _,since=N._day_bounds(datetime.fromisoformat(instant))
    assert since.isoformat()==midnight


def test_corrupt_database_and_bad_receipt_details_are_not_empty_success(tmp_path):
    corrupt=tmp_path/'corrupt.sqlite';corrupt.write_bytes(b'not a database')
    out=P.project_runs(corrupt,now=NOW)
    assert out['status']=='UNAVAILABLE' and out['total_count'] is None
    db=sqlite3.connect(tmp_path/'events.sqlite')
    db.execute('CREATE TABLE receipts(store_key TEXT,lane_id TEXT,state TEXT,receipt_json TEXT,updated_at TEXT)')
    db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',('key','fixture','CONSUMED','{bad',NOW.isoformat()));db.commit();db.close()
    out=P.project(tmp_path/'events.sqlite',now=NOW)
    assert out['status']=='PARTIAL' and out['total_count']==1 and out['count']==0
    assert out['coverage']['invalid_detail_rows']==1


def test_successful_read_then_failure_exposes_last_good_capture_age(tmp_path):
    db=sqlite3.connect(tmp_path/'ledger.sqlite')
    db.execute('CREATE TABLE runs(run_id TEXT,lane_id TEXT,mode TEXT,state TEXT,requested_at TEXT,started_at TEXT,finished_at TEXT,receipt_json TEXT)');db.commit();db.close()
    assert P.project_runs(tmp_path/'ledger.sqlite',now=NOW)['total_count']==0
    (tmp_path/'ledger.sqlite').unlink()
    out=P.project_runs(tmp_path/'ledger.sqlite',now=NOW+timedelta(minutes=2))
    assert out['total_count'] is None and out['last_good_age_s']==120


def test_symlinked_receipt_is_unavailable_not_arbitrary_file_read(tmp_path):
    empty_sources(tmp_path)
    outside=tmp_path/'outside.json';outside.write_text(json.dumps({'state':'RUN_DONE','mode':'live'}))
    (tmp_path/N.RUNS_REL/'d:fixture:live:20261018T1100.json').symlink_to(outside)
    out=N.build(tmp_path,NOW)
    assert out['runs']['totals']['live'] is None
    assert out['coverage']['sources']['runs']['invalid_files']==1
