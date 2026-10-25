"""Fact-only CIO population: isolated stores, pinned clocks, fake PG only.
ANCHOR: CIO_COMPANY_POPULATION_20261024. No production/provider/DB/credentials.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import pytest
ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT/'scripts'):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
from scripts.lib import cio_company_population as P, cio_instrument_record as I
from scripts.lib.data_broker.cio_company_facts import load_snapshot, for_security

NOW = datetime(2026,10,24,20,tzinfo=timezone.utc)
G='5f0c6a3e-1111-5111-8111-000000000001'
ISS='5f0c6a3e-1111-5111-8111-0000000000a1'
IDS={'AAA': {'security_guid':G,'subject_guid':G,'issuer_guid':ISS,'identity_status':'CONFIRMED','symbol':'AAA'}}
REG={'domains':[{'domain':'cio_prospect','approval':{'approved_by':'SYNTHETIC_TEST_ONLY'}}]}
ON={I.PROSPECT_DUAL_WRITE_ENV:'1'}

@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(P,'resolve_security_identity',lambda sym,**kw:deepcopy(IDS.get(sym,{'identity_status':'UNRESOLVED'})))
    monkeypatch.setattr(P,'stored_catalysts',lambda *_:{})
    monkeypatch.setattr(P.facts,'collect_inputs',lambda *a,**kw:{'errors':[], 'profiles':{},'finviz':{},'identity_profiles':{
        'AAA':{'company':'Acme Instruments','updated_at':NOW.isoformat()}}})
    monkeypatch.setattr(I,'_now',lambda:NOW.isoformat())
    c={'captured_at':NOW.isoformat(),'database_read_only':True,'my_watchlist':['AAA'],'held':[], 'formerly_held':[],
       'catalyst_events':{'status':'ok','rows':{}},'identities':deepcopy(IDS),'profiles':{'AAA':{'description':'Makes precision instruments.','sector':'Industrials',
       'industry':'Scientific Instruments','updated_at':NOW.isoformat(),'source':'stored_fixture'}},'gaps':[]}
    return tmp_path,c

def run(world,**kw):
    root,c=world
    return P.populate(root,c,now=NOW,env={},**kw)

def tip(root):return I.InstrumentRecordStore(root/I.DEFAULT_PATH).all()[0]

class FakePg:
    def __init__(self,ready=True,fail=False):self.ready=ready;self.fail=fail;self.calls=[];self.rows={}
    def table_present(self):self.calls.append('probe');return True
    def fact_only_ready(self):self.calls.append('schema');return self.ready
    def write_fact_only(self,row):
        self.calls.append('write')
        if self.fail:raise RuntimeError('secret-value-must-never-appear')
        self.rows[row['security_guid']]=deepcopy(row)
        return {'ok':True,'upserted':1}
    def write(self,row,*a):
        self.calls.append('write_judged');self.rows[row['security_guid']]=deepcopy(row)
        return {'ok':True,'upserted':1}
    def company_facts_equal(self,guid,expected):
        self.calls.append('readback');return (self.rows.get(guid,{}).get('research') or {}).get('company_facts')==expected


def test_preview_creates_only_in_memory_and_actual_apply_reads_same_guid(world):
    root,c=world
    preview=run(world)
    assert preview['would_create']==1 and not (root/I.DEFAULT_PATH).exists()
    r=run(world,apply=True)
    rec=tip(root)
    assert r['writes']==1 and r['created']==1 and r['judgment_writes']==r['prospect_promotions']==0
    assert I.is_fact_only_record(rec) and not I.is_prospect_record(rec)
    assert not any(k in rec for k in ('stage','stance','conviction','evidence_at','expires_at','prospect_schema'))
    public=for_security(load_snapshot(records=[rec]),'AAA',G,now=NOW)['company_facts']
    assert public['company']['value']=='Acme Instruments' and public['description']['value']=='Makes precision instruments.'
    assert public['description']['observed_at']==NOW.isoformat() and r['after']['my_watchlist']['complete']==1


def test_repeated_identical_evidence_is_noop_but_real_conflicts_preserved(world,monkeypatch):
    root,c=world
    monkeypatch.setattr(P.facts,'collect_inputs',lambda *a,**kw:{'errors':[], 'profiles':{},'finviz':{
        'AAA':{'as_of':NOW.isoformat(),'record':{'sector':'Different sector'}}},'identity_profiles':{
        'AAA':{'company':'Acme Instruments','updated_at':NOW.isoformat()}}})
    run(world,apply=True)
    raw=(root/I.DEFAULT_PATH).read_bytes();r=run(world,apply=True)
    assert r['writes']==0 and r['unchanged']==1 and (root/I.DEFAULT_PATH).read_bytes()==raw
    sector=next(x for x in tip(root)['research']['company_facts']['conflicts'] if x['field']=='sector')
    assert {x['value'] for x in sector['values']}=={'Industrials','Different sector'}
    assert all(x['source'] and x['observed_at'] for x in sector['values'])


def test_confirmed_security_without_issuer_is_a_fact_gap_not_a_fake_prospect(world,monkeypatch):
    root,c=world
    ident={**IDS['AAA'],'issuer_guid':None}
    monkeypatch.setattr(P,'resolve_security_identity',lambda *a,**kw:ident)
    r=run(world,apply=True)
    assert r['writes']==1 and r['after']['my_watchlist']['complete']==1
    assert tip(root).get('issuer_guid') is None and r['identity_gaps'][0]['reason'].startswith('issuer_guid_missing')
    with pytest.raises(I.ProspectInvalid):I.apply_prospect(tip(root),prospect={'stage':'watching','stance':'WATCH',
        'conviction':50,'evidence_at':NOW.isoformat(),'expires_at':(NOW+timedelta(days=1)).isoformat()})


@pytest.mark.parametrize('key',['stage','stance','conviction','expires_at','next_action'])
def test_fact_mode_refuses_even_null_judgment_keys(world,key):
    root,c=world
    P.populate(root,c,apply=True,now=NOW,env={});rec=tip(root)
    with pytest.raises(I.ProspectInvalid):I.apply_prospect(rec,prospect={key:None,'research':{'company_facts':rec['research']['company_facts']}},fact_only=True)


def test_unresolved_security_and_capture_guid_drift_never_mint(world,monkeypatch):
    root,c=world
    c['identities']['AAA']['security_guid']=ISS
    assert run(world,apply=True)['gaps'][0]['reason']=='capture_registry_identity_drift'
    assert not (root/I.DEFAULT_PATH).exists()
    monkeypatch.setattr(P,'resolve_security_identity',lambda *a,**kw:{'identity_status':'UNRESOLVED'})
    r=run(world,apply=True)
    assert r['writes']==0 and r['gaps'][0]['reason']=='identity_not_confirmed'
    assert not (root/I.DEFAULT_PATH).exists()


def test_default_prospect_validation_is_unchanged(world):
    root,c=world
    rec=I.new_record('SECURITY','AAA',symbols=['AAA'],**IDS['AAA'])
    with pytest.raises(I.ProspectInvalid):I.apply_prospect(rec,prospect={'research':{'company_facts':{}}})


def judged(root):
    rec=I.new_record('SECURITY','AAA',symbols=['AAA'],**IDS['AAA'])
    rec,_=I.apply_prospect(rec,prospect={'stage':'actionable','stance':'ADD','conviction':72,
        'evidence_at':NOW.isoformat(),'expires_at':(NOW+timedelta(days=2)).isoformat(),
        'research':{'private_notes':'KEEP','review_lifecycle':{'request_id':'fixture'}}})
    I.InstrumentRecordStore(root/I.DEFAULT_PATH).upsert(rec)
    return rec


def test_existing_judgment_and_sibling_research_preserved(world):
    root,c=world;before=judged(root);run(world,apply=True);after=tip(root)
    for k in ('stage','stance','conviction','evidence_at','expires_at','security_guid','issuer_guid','subject_key'):
        assert after[k]==before[k]
    assert after['research']['private_notes']=='KEEP' and after['research']['review_lifecycle']=={'request_id':'fixture'}
    assert I.is_prospect_record(after) and not I.is_fact_only_record(after)


def test_live_pg_flag_requires_schema_before_any_canonical_append(world):
    root,c=world;pg=FakePg(ready=False)
    r=P.populate(root,c,apply=True,now=NOW,env=ON,registry=REG,backend=pg)
    assert r['writes']==0 and r['gaps'][0]['reason']=='fact_only_migration_required'
    assert not (root/I.DEFAULT_PATH).exists() and 'write' not in pg.calls


def test_flag_off_never_connects_pg_and_enabled_pg_reads_same_guid(world):
    root,c=world
    class NoPg:
        def table_present(self):raise AssertionError('flag-off DB call')
    r=run(world,apply=True,backend=NoPg())
    assert r['pg_sync']=='NOT_REQUESTED_FLAG_OFF'
    # Enabling PG after a JSONL-only pass cannot silently claim sync or backfill PG.
    pg=FakePg();r=P.populate(root,c,apply=True,now=NOW,env=ON,registry=REG,backend=pg)
    assert not r['ok'] and r['writes']==0 and r['gaps'][0]['reason']=='unchanged_pg_divergence_owner_reconciliation_required'


def test_enabled_fake_pg_ack_then_idempotent_exact_readback(world):
    root,c=world;pg=FakePg()
    r=P.populate(root,c,apply=True,now=NOW,env=ON,registry=REG,backend=pg)
    assert r['ok'] and r['writes']==1 and pg.rows[G]['record_kind']=='FACTS_ONLY'
    raw=(root/I.DEFAULT_PATH).read_bytes()
    again=P.populate(root,c,apply=True,now=NOW,env=ON,registry=REG,backend=pg)
    assert again['ok'] and again['writes']==0 and 'readback' in pg.calls and (root/I.DEFAULT_PATH).read_bytes()==raw


def test_pg_failure_keeps_named_partial_receipt_and_retry_cannot_turn_green(world):
    root,c=world;pg=FakePg(fail=True)
    r=P.populate(root,c,apply=True,now=NOW,env=ON,registry=REG,backend=pg)
    assert r['writes']==1 and not r['ok'] and tip(root)['research']['company_facts']
    assert 'secret-value' not in json.dumps(r) and r['pg'][0]['error']=='RuntimeError'
    again=P.populate(root,c,apply=True,now=NOW,env=ON,registry=REG,backend=pg)
    assert again['writes']==0 and not again['ok'] and len(pg.rows)==0


def test_fact_preview_cannot_overwrite_a_later_cio_judgment(world):
    root,c=world;run(world,apply=True);st=I.InstrumentRecordStore(root/I.DEFAULT_PATH);old=deepcopy(tip(root))
    old['research']['company_facts']['description']['value']='New evidence'
    late=judged(root)
    out=st.upsert_prospect(old,fact_only=True,env={})['row']
    assert out['stance']=='ADD' and out['conviction']==72 and out['research']['private_notes']=='KEEP'
    assert out['research']['company_facts']['description']['value']=='New evidence'


def test_projection_query_excludes_fact_only_rows_without_requiring_migration_columns():
    from scripts.lib.data_broker.cio_prospect import get_prospects
    calls=[]
    get_prospects(db_query=lambda sql:(calls.append(sql) or []),status={'live':True},now=NOW)
    assert 'stage IS NOT NULL' in calls[0] and 'stance IS NOT NULL' in calls[0] and 'conviction IS NOT NULL' in calls[0]


def test_migration_has_no_new_table_delete_or_fabricated_judgment():
    sql=(ROOT/'migrations/2026_10_24_cio_company_facts_only.sql').read_text()
    assert 'CREATE TABLE' not in sql and 'DELETE FROM' not in sql
    assert "AND issuer_guid IS NOT NULL AND stage IS NOT NULL" in sql
    assert "coalesce(provenance->>'record_kind','PROSPECT')='FACTS_ONLY'" in sql
    assert "AND stance IS NULL AND conviction IS NULL" in sql


def test_cli_preview_writes_nothing_and_apply_writes_exact_receipts(world,monkeypatch,capsys):
    from scripts import cio_company_facts_populate as cli
    import types
    root,c=world;capture=root/'capture.json';capture.write_text(json.dumps(c))
    # No real DB dependency is even imported; explicit lazy fake provider only.
    monkeypatch.setitem(sys.modules,'scripts.session13_db',types.SimpleNamespace(get_conn=lambda:pytest.fail('DB connected')))
    monkeypatch.delenv(I.PROSPECT_DUAL_WRITE_ENV,raising=False)
    args=['--input-capture',str(capture),'--state-root',str(root),'--now',NOW.isoformat()]
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert cli.main(args)==0
    assert {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}==before
    assert cli.main(args+['--apply'])==0
    rec=json.loads((root/P.RECEIPT_REL).read_text())
    assert rec['status']=='ok' and rec['produced_count']==1 and rec['schema']=='LaneRunReceipt@v2'
    assert json.loads((root/'data/runtime/cio_company_facts_populate_report_latest.json').read_text())['pg_sync']=='NOT_REQUESTED_FLAG_OFF'


def test_cli_failed_input_has_sanitized_failed_receipt_and_no_canonical_write(world,capsys):
    from scripts import cio_company_facts_populate as cli
    root,c=world;p=root/'broken.json';p.write_text('secret-invalid-json')
    assert cli.main(['--apply','--input-capture',str(p),'--state-root',str(root),'--now',NOW.isoformat()])==1
    out=capsys.readouterr().out
    assert 'secret-invalid-json' not in out
    r=json.loads((root/P.RECEIPT_REL).read_text())
    assert r['status']=='failed' and r['produced_count']==0
    assert not (root/I.DEFAULT_PATH).exists()


def test_capture_shape_refuses_missing_membership(world):
    root,c=world;c.pop('held')
    with pytest.raises(ValueError,match='membership_and_profiles_capture_required'):run(world,apply=True)
    assert not (root/I.DEFAULT_PATH).exists()


def test_malformed_canonical_row_refuses_atomic_append(world):
    root,c=world
    r=run(world);fake=I.new_record('SECURITY','AAA',symbols=['AAA'],**IDS['AAA'])
    f,_=I.apply_prospect(fake,prospect={'research':{'company_facts':P.facts.assemble('AAA',IDS['AAA'],P.facts.collect_inputs(root,['AAA'],now=NOW),now=NOW)}},fact_only=True)
    path=root/I.DEFAULT_PATH;path.parent.mkdir(parents=True);path.write_text('[]\n')
    with pytest.raises(I.ProspectInvalid,match='subject key'):I.InstrumentRecordStore(path).upsert_prospect(f,fact_only=True,env={})
    assert path.read_text()=='[]\n'


def test_native_proposal_is_valid_apply_inactive_and_draft_cannot_be_admitted():
    from scripts import build_cio_company_facts_workflow as B, n8n_workflow_templates as T
    from scripts.lib import n8n_health_contracts as H
    from scripts.lib.lane_registry import validate_registry
    wf=B.build();packet=ROOT/B.REL
    assert wf==json.loads((packet/'workflow.json').read_text()) and wf['active'] is False
    assert not T.validate_fabric_workflow(wf,{B.WID,T.RUN_LANE_ID,T.FABRIC_ERROR_ID}) and not T.process_problems(wf)
    triggers=[n for n in wf['nodes'] if n['type']=='n8n-nodes-base.scheduleTrigger']
    assert len(triggers)==1 and [x['expression'] for x in triggers[0]['parameters']['rule']['interval']]==B.SCHEDULES
    assert wf['settings']['timezone']=='America/New_York'
    code='\n'.join(n.get('parameters',{}).get('jsCode','') for n in wf['nodes'])
    assert 'const MODE = "live";' in code and 'max_attempts: 1' in code
    reg=json.loads((ROOT/'config/lane_registry.json').read_text());assert not validate_registry(reg)
    row=next(r for r in reg['lanes'] if r['lane_id']==P.LANE_ID)
    assert row['state']=='NEVER_SCHEDULED' and row['scheduler']['kind']=='none' and 'dispatch' not in row
    contract=json.loads((packet/'HEALTH_CONTRACT_DRAFT.json').read_text());assert not H.validate_contract(contract)
    assert contract['status']=='DRAFT' and contract['review']['reviewed_by'] is None
    assert any('DRAFT_NOT_GRANDFATHERED' in x for x in H.check({'contracts':[contract]},reg,{})['errors'])
    allow=json.loads((packet/'ALLOWLIST_PROPOSAL.json').read_text())
    assert allow['live_arg']==['--apply'] and allow['dry_run_arg']==['--dry-run'] and allow['timeout_s']==600
    assert '--with-db --state-root' in ' '.join(allow['command']) and allow['lock']=='/tmp/tradeai_cio_company_facts_populate.lock'
    assert not any('BROKER' in x or 'LLM' in x for x in allow['env_names'])


def test_actual_pg_backend_refuses_divergent_row_and_rolls_back(world):
    root,c=world;run(world,apply=True);record=tip(root)
    class Cursor:
        rowcount=0
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def execute(self,sql,params):
            assert 'ON CONFLICT (security_guid)' in sql
            assert "record_kind'='FACTS_ONLY'" in sql
            assert params['security_guid']==G
            assert not any(k in params for k in ('stance','stage','conviction','evidence_at','expires_at'))
    class Conn:
        def __init__(self):self.rollback_count=0;self.closed=False
        def cursor(self):return Cursor()
        def commit(self):pytest.fail('divergent write committed')
        def rollback(self):self.rollback_count+=1
        def close(self):self.closed=True
    conn=Conn()
    with pytest.raises(I.ProspectInvalid,match='diverges'):I.ProspectPgBackend(lambda:conn).write_fact_only(record)
    assert conn.rollback_count==1 and conn.closed


def test_new_fact_only_record_is_consumed_by_actual_symbol_guid_ask_and_cognition(world,monkeypatch):
    from scripts.lib import cio_ask_research as ask,cio_persistent_cognition as pc
    root,c=world;run(world,apply=True);rec=tip(root)
    assert I.subject_key_for_symbol('AAA',root=root)=='SECURITY:AAA'
    for kwargs in ({'symbol':'AAA'},{'subject_guid':G},{'subject_key_hint':'SECURITY:AAA'}):
        loaded=I.load_instrument_record_for_wake(root=root,**kwargs)
        assert loaded['ok'] and loaded['record']['research']['company_facts']==rec['research']['company_facts']
        assert not loaded['record'].get('stance') and not loaded['record'].get('conviction')
    monkeypatch.setattr(pc,'resolve_identity',lambda *a:deepcopy(IDS['AAA']))
    row=pc.cognition_for_symbol(root,'AAA')
    assert row['cio_record_research']['company_facts']['description']['value']=='Makes precision instruments.'
    assert pc.telegram_fields(row)['cio_record_research']==row['cio_record_research']
    source=ask._src_cio_record_research(ask.Entity('Acme','listed',symbol='AAA',security_guid=G),
        ask.ResearchContext('What does AAA do?',state_root=root,now=NOW))
    assert any('Makes precision instruments.' in x.claim for x in source)
    wrong=ask._src_cio_record_research(ask.Entity('Acme','listed',symbol='AAA',security_guid=ISS),
        ask.ResearchContext('What does AAA do?',state_root=root,now=NOW))
    assert not any('Makes precision instruments.' in x.claim for x in wrong)


def test_stale_normal_writer_cannot_erase_new_facts_and_sibling_research(world):
    root,c=world;before=judged(root)
    slow=I.InstrumentRecordStore(root/I.DEFAULT_PATH)
    stale=slow.load(before['subject_key'])  # deliberately mutate this cached dict, as legacy callers do
    stale['research']['private_notes']='Writer wants a new note'
    run(world,apply=True)
    newfacts=tip(root)['research']['company_facts']
    stale['stance']='HOLD'
    raw=(root/I.DEFAULT_PATH).read_bytes()
    with pytest.raises(I.StaleInstrumentRecordWrite,match='tip changed'):slow.upsert(stale)
    assert (root/I.DEFAULT_PATH).read_bytes()==raw
    actual=tip(root)
    assert actual['stance']=='ADD' and actual['research']['company_facts']==newfacts
    assert actual['research']['private_notes']=='KEEP' and actual['research']['review_lifecycle']=={'request_id':'fixture'}
    # The writer must explicitly re-read and reapply its own patch; no automatic
    # choice is made between conflicting versions.
    fresh=I.InstrumentRecordStore(root/I.DEFAULT_PATH);updated=deepcopy(fresh.load(before['subject_key']))
    updated['stance']='HOLD';updated['research']['private_notes']='Writer wants a new note';fresh.upsert(updated)
    actual=tip(root)
    assert actual['stance']=='HOLD' and actual['research']['company_facts']==newfacts
    assert actual['research']['review_lifecycle']=={'request_id':'fixture'}


def test_capture_uses_canonical_position_accessor_with_explicit_copy_root(tmp_path,monkeypatch):
    from scripts.lib import portfolio_positions as pp
    from scripts.lib.data_broker import watch_domains as wd
    root=tmp_path/'copy';canonical=pp.store_path(root)
    assert canonical==root.joinpath(*pp.STORE_REL)
    calls=[]
    monkeypatch.setattr(pp,'load_store',lambda path:(calls.append(path) or {'holdings':[{'symbol':'AAA','shares':2}], 'as_of':NOW.isoformat()}))
    monkeypatch.setattr(wd,'membership_operator',lambda q:{'names':{'AAA':{}},'sources':{'fixture':{'status':'ok'}}})
    capture=P.capture_readonly_inputs(root,lambda *args:[],now=NOW)
    assert calls==[canonical] and capture['held']==['AAA']
    assert capture['held_source']['as_of']==NOW.isoformat()
    assert not root.exists(), 'path selection/read fixture must never write or fall back to live state'


def test_company_lane_admission_precedes_the_generated_registry_suffix():
    from scripts import reconcile_lane_registry as R
    rows=json.loads((ROOT/'config/lane_registry.json').read_text())['lanes']
    own=next(i for i,r in enumerate(rows) if r['lane_id']==P.LANE_ID)
    generated=next(i for i,r in enumerate(rows) if r.get('generated_by')==R.GENERATOR_VERSION)
    assert own<generated, 'manual native admission must survive regeneration without reordering'
    assert rows[own].get('generated_by') is None
    assert rows[own]['state']=='NEVER_SCHEDULED' and rows[own]['scheduler']['kind']=='none'
