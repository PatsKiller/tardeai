"""C3 exact request -> worker -> canonical CIO record/memory -> actual Ask/panel.

ANCHOR: CIO_REVIEW_LIFECYCLE_20261024. Pinned clocks, temporary stores, fake PG
and model boundary only; no live provider, service bus, broker or sender.
"""
from __future__ import annotations
import importlib.util
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / 'scripts'):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
from scripts.lib import cio_review_lifecycle as life, cio_instrument_record as ir

NOW = datetime(2026, 10, 24, 16, tzinfo=timezone.utc)
AT = '2026-10-24T14:00:00+00:00'
GUID = '5f0c6a3e-2222-5222-8222-000000000001'
ISSUER = '5f0c6a3e-2222-5222-8222-000000000002'
IDENT = {'symbol': 'TSLA', 'security_guid': GUID, 'issuer_guid': ISSUER, 'identity_status': 'CONFIRMED'}
REQ = {**IDENT, 'request_id': 'review-fixture-1', 'requested_at': AT, 'research_id': 'res-fixture'}
REG = {'domains': [{'domain': 'cio_prospect', 'approval': {'approved_by': 'offline fixture'}}]}
ENV = {ir.PROSPECT_DUAL_WRITE_ENV: '1'}


class PG:
    def __init__(self, fail=False): self.writes=[]; self.fail=fail
    def table_present(self): return True
    def write(self, row, event, lifecycle=()):
        if self.fail: raise RuntimeError('private DB detail')
        self.writes.append(deepcopy(row)); return {'ok': True}


def seed(root, conflict=False):
    st = ir.InstrumentRecordStore(root / ir.DEFAULT_PATH)
    rec = {'subject_key': 'WATCH:TSLA', 'kind': 'WATCH', 'symbols': ['TSLA'], **IDENT,
           'stage': 'watching', 'stance': 'WATCH', 'conviction': 61, 'evidence_at': AT,
           'expires_at': '2026-10-26T16:00:00+00:00', 'research': {'company_facts': {'schema': 'CIOCompanyFacts@v1',
           'security_guid': GUID, 'company': {'value': 'Tesla Inc.'}}, 'private': {'account': 'never-public'}},
           'conflicts': [{'field':'stance','values':[{'value':'WATCH','source':'house','at':AT},{'value':'AVOID','source':'scanner','at':AT}], 'resolved':False}] if conflict else []}
    rec, _ = ir.apply_prospect(rec, prospect={'research': rec['research']}, strict=False)
    st.upsert(rec)
    return st


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(life, 'identity', lambda sym, root=None: IDENT if sym == 'TSLA' else {})
    monkeypatch.setattr(life, 'now', lambda: NOW.isoformat())
    monkeypatch.delenv(ir.PROSPECT_DUAL_WRITE_ENV, raising=False)
    st=seed(tmp_path)
    pg=PG(); mem=[]
    def memory(*a, **kw): mem.append(kw); return {'ok':True}
    return st, pg, mem, {'root':tmp_path,'store':st,'backend':pg,'registry':REG,'env':ENV,'memory_writer':memory,'apply':True}


def test_created_researching_answered_are_saved_by_canonical_facade_and_spine(setup):
    st,pg,mem,opts=setup
    before=deepcopy(st.all()[0])
    for status,at in [('REQUESTED',AT),('RESEARCHING','2026-10-24T14:10:00+00:00'),('ANSWERED_PENDING_CIO','2026-10-24T15:00:00+00:00')]:
        assert life.observe(REQ,status,at=at,reason='Evidence answered; CIO pending',**opts)['ok']
    saved=life.read('TSLA',root=opts['root'],store=st)
    assert saved['status']=='ANSWERED_PENDING_CIO' and saved['research_id']=='res-fixture'
    assert saved['new_stance'] is None and saved['created_at']==AT
    assert len(pg.writes)==len(mem)==3 and all(m['thesis_patch'] is None for m in mem)
    assert st.all()[0]['stance']==before['stance'] and st.all()[0]['conviction']==before['conviction']
    assert st.all()[0]['research']['company_facts']==before['research']['company_facts']
    assert 'private' not in json.dumps(life.research_for_symbols(['TSLA'],root=opts['root']))


def test_delayed_or_duplicate_events_do_not_regress_or_assert_consumer_acceptance(setup):
    st,pg,mem,opts=setup
    life.observe(REQ,'ANSWERED_PENDING_CIO',at=NOW.isoformat(),**opts)
    before=st.path.read_bytes()
    delayed=life.observe(REQ,'REQUESTED',at=AT,**opts)
    assert not delayed['ok'] and delayed['reason']=='delayed_event_ignored_consumer_ack_not_measured'
    duplicate=life.observe(REQ,'ANSWERED_PENDING_CIO',at=NOW.isoformat(),**opts)
    assert not duplicate['ok'] and 'ack_not_measured' in duplicate['reason']
    assert st.path.read_bytes()==before and len(mem)==1


@pytest.mark.parametrize('failure',['pg','memory'])
def test_partial_plane_failure_replay_never_becomes_false_success(setup,failure):
    st,pg,mem,opts=setup
    if failure=='pg': opts['backend']=PG(fail=True)
    else: opts['memory_writer']=lambda *a,**k:{'ok':False}
    first=life.observe(REQ,'REQUESTED',at=AT,**opts)
    assert not first['ok'] and first['record_written']
    assert 'private DB detail' not in json.dumps(first)
    before=st.path.read_bytes()
    replay=life.observe(REQ,'REQUESTED',at=AT,**opts)
    assert not replay['ok'] and st.path.read_bytes()==before


def thesis():
    return {'thesis_version':'symbol_TSLA@v2','symbol':'TSLA','security_guid':GUID,'stance':'watch','owner_agent':'alex',
            'published_ts':'2026-10-24T15:30:00+00:00','extra':{'write_provenance':{'security_guid':GUID,'review_request_ids':[REQ['request_id']],'source_research_ids':['res-fixture']}}}


def test_resolution_requires_linked_cio_publication_and_clean_actual_record(setup):
    st,pg,mem,opts=setup
    life.observe(REQ,'ANSWERED_PENDING_CIO',at='2026-10-24T15:00:00+00:00',**opts)
    req={**REQ,'published_version':'symbol_TSLA@v2','thesis_id':'symbol_TSLA'}
    assert life.observe(REQ,'CONFLICT_RESOLVED',**opts)['ok'] is False
    assert life.observe_cio_readback(req,thesis_reader=lambda _:thesis(),**opts)['ok']
    r=life.read('TSLA',root=opts['root'],store=st)
    assert r['status']=='CONFLICT_RESOLVED' and r['old_stance']==r['new_stance']=='WATCH'


@pytest.mark.parametrize('change',[{'symbol':'OTHER'},{'security_guid':ISSUER},{'published_ts':'2026-10-23T00:00:00+00:00'}, {'published_ts':'2030-01-01T00:00:00+00:00'},
                                   {'extra':{'write_provenance':{'security_guid':GUID,'review_request_ids':['unrelated']}}}])
def test_unrelated_old_or_wrong_guid_publication_cannot_resolve(setup,change):
    st,pg,mem,opts=setup
    life.observe(REQ,'ANSWERED_PENDING_CIO',**opts)
    before=st.path.read_bytes()
    result=life.observe_cio_readback({**REQ,'published_version':'symbol_TSLA@v2','thesis_id':'symbol_TSLA'},
                                   thesis_reader=lambda _:{**thesis(),**change},**opts)
    assert not result['ok'] and st.path.read_bytes()==before


def test_unconfirmed_and_legacy_records_are_held_without_minting(setup):
    st,pg,mem,opts=setup
    before=st.path.read_bytes()
    assert life.observe({**REQ,'identity_status':'CANDIDATE'},'REQUESTED',**opts)['reason']=='identity_not_confirmed'
    assert st.path.read_bytes()==before
    rec=deepcopy(st.all()[0]); rec.pop('prospect_schema'); st.upsert(rec)
    before=st.path.read_bytes()
    assert life.observe(REQ,'REQUESTED',**opts)['reason']=='legacy_record_needs_cio_promotion'
    assert st.path.read_bytes()==before


def test_exact_request_aging_distinguishes_cio_wait_legacy_and_failed_consumers(setup):
    st,pg,mem,opts=setup
    life.observe(REQ,'ANSWERED_PENDING_CIO',at=AT,**opts)
    doc=life.aging(opts['root'],requests=[REQ],at=NOW+timedelta(days=2))
    assert doc['findings'][0]['phase']=='ANSWERED_PENDING_CIO' and doc['findings'][0]['age_basis']=='answered_at'
    legacy={**REQ}; legacy.pop('request_id')
    doc=life.aging(opts['root'],requests=[legacy,{**REQ,'request_id':'different','lifecycle_persist':{'ok':False,'pg_mode':'inert'}}],at=NOW+timedelta(days=2))
    assert all(f['status']!='OVERDUE' for f in doc['findings'])
    assert any(f['status']=='CONSUMER_WRITE_INCOMPLETE' for f in doc['findings'])
    assert doc['alert_delivery']=='NOT_MEASURED' and doc['writes']==0


def test_read_only_health_cli_never_reports_missing_or_malformed_input_as_empty(tmp_path,capsys):
    from scripts import cio_review_lifecycle_health as cli
    assert cli.main(['--root',str(tmp_path),'--now',NOW.isoformat()])==1
    assert json.loads(capsys.readouterr().out)['input_measurements'][0]['status']=='NOT_MEASURED'
    p=tmp_path/'data/cio/symbol_thesis_priority_queue.jsonl';p.parent.mkdir(parents=True);p.write_text('bad json\n')
    assert cli.main(['--root',str(tmp_path),'--now',NOW.isoformat()])==1
    assert json.loads(capsys.readouterr().out)['input_measurements'][0]['status']=='PARTIAL'


def test_real_button_queue_has_stable_id_and_aged_pending_remains_visible(setup,monkeypatch):
    from scripts.lib import symbol_thesis_priority as priority
    from scripts import api_v3_opportunities as api
    st,pg,mem,opts=setup
    req=priority.request('TSLA',reason='operator review',source='operator_opportunity_view',root=opts['root'],now=NOW)
    assert req['request_id'].startswith('review-') and req['security_guid']==GUID
    assert priority.latest_request('TSLA',opts['root'])['request_id']==req['request_id']
    folded=priority._rows(opts['root'].joinpath(*priority.RELPATH))
    assert len(folded)==1 and folded[0]['lifecycle_persist']['pg_mode']=='inert'
    assert len(opts['root'].joinpath(*priority.RELPATH).read_text().splitlines())==2
    monkeypatch.setattr(api,'_priority',lambda:priority)
    oldroot=priority._root
    monkeypatch.setattr(priority,'_root',lambda root: oldroot(opts['root']))
    monkeypatch.setattr(priority,'open_requests_ranked',lambda:[])
    monkeypatch.setattr(life,'_store',lambda root=None:ir.InstrumentRecordStore(opts['root']/ir.DEFAULT_PATH))
    state=api.review_state('TSLA')
    assert state['open'] and not state['queue_eligible'] and 'remains pending' in state['next_run']


def test_native_spine_consumer_recalls_same_review_guid_and_refs(setup):
    from scripts.lib.cross_asset.security_research_spine import load_latest, view_for_silo
    st,pg,mem,opts=setup
    native={k:v for k,v in opts.items() if k!='memory_writer'}
    result=life.observe(REQ,'ANSWERED_PENDING_CIO',at=NOW.isoformat(),reason='Actual evidence accepted; CIO decision pending',**native)
    assert result['memory_ok']
    tip=load_latest('TSLA',root=opts['root'])
    assert tip['subject_guid']==GUID and 'review-fixture-1' in json.dumps(tip)
    from scripts.lib.cio_ask_memory import SpineAskMemory
    from scripts.lib.cio_ask_contract import EntityRef
    recalled=SpineAskMemory(spine_path=opts['root']/'data/cio/security_research_spine.jsonl').recall(
        entity=EntityRef(name='Tesla',symbol='TSLA',security_guid=GUID,issuer_guid=ISSUER))
    assert 'ANSWERED_PENDING_CIO' in json.dumps(recalled)


def test_company_catalyst_ages_equally_in_quick_ask_without_mutating_record(setup):
    st,pg,mem,opts=setup
    rec=deepcopy(st.all()[0]); rec['research']['company_facts']['catalyst']={
        'status':'CURRENT','headline':'Prior evidence','published_at':'2026-08-01T00:00:00+00:00'}
    st.upsert(rec); before=st.path.read_bytes()
    facts=life.research_for_symbols(['TSLA'],root=opts['root'],at=NOW)
    assert facts['TSLA']['company_facts']['catalyst']['status']=='STALE'
    assert st.path.read_bytes()==before


def _ask_test_helpers():
    spec=importlib.util.spec_from_file_location('c3_ask_helpers',ROOT/'tests/test_cio_ask_20261023.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


def test_actual_quick_ask_model_and_persisted_answer_read_fresh_cio_record(setup,monkeypatch):
    from scripts.lib import cio_ask_core as core, cio_converse_core as conv, cio_operator_desk_loop as desk
    import scripts.lib.cross_asset.hooks as hooks
    import scripts.lib.hermes_subject_join as hj
    import scripts.lib.cio_event_bus as bus
    helpers=_ask_test_helpers()
    st,pg,mem,opts=setup
    tmp=opts['root']
    deps=helpers.make_deps(tmp/'ask',mirror=False)
    deps.resolver=lambda q:[helpers.C.EntityRef(name='Tesla',symbol='TSLA',security_guid=GUID,issuer_guid=ISSUER)]
    # No test fake replaces the desk, gather wrapper, model facts serializer,
    # answer validation, compose/finalize, or finish_turn.
    monkeypatch.setattr(desk,'PROJECT_ROOT',tmp)
    monkeypatch.setattr(desk,'_now',lambda:NOW.isoformat())
    monkeypatch.setenv('CIO_OPERATOR_FREEFORM_QUEUE','0')
    monkeypatch.setenv('TRADEAI_HERMES_JOIN_DB','0')
    monkeypatch.setattr(desk,'analyze_operator_intent',lambda text:{'ok':True,'intent':'freeform','symbols':['TSLA'],'needs':[],'text':text})
    monkeypatch.setattr(desk,'_gather_tradeai_evidence_core',lambda intent:{'ok':True,'complete':True,'available':{'freeform_context':{'symbols_mentioned':['TSLA']}},'gaps':[],'blocking_gaps':[],'sources':['fixture stored inputs']})
    monkeypatch.setattr(desk,'_attach_subject_dossier',lambda *a:None)
    monkeypatch.setattr(desk,'subject_memory',lambda *a,**k:{})
    monkeypatch.setattr(desk,'_open_pending_row',lambda *a,**k:None)
    monkeypatch.setattr(desk,'_emit_telegram_desk_payload',lambda *a,**k:None)
    monkeypatch.setattr(desk,'_freeform_flash_enabled',lambda:True)
    monkeypatch.setattr(hooks,'notify_llm_curation',lambda *a,**k:None)
    monkeypatch.setattr(hj,'join_subject_hermes',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('offline')))
    monkeypatch.setattr(conv,'enqueue_operator_wake_channel',lambda **k:'fixture_wake')
    monkeypatch.setattr(conv,'record_decision_thread_note',lambda *a,**k:None)
    class Bus:
        def emit(self,*a,**k):return {'event_id':'fixture_event'}
    monkeypatch.setattr(bus,'CIOEventBus',Bus)
    for name in ('scripts.lib.cio_operator_feedback_loop','lib.cio_operator_feedback_loop'):
        try:
            mod=__import__(name,fromlist=['x']);monkeypatch.setattr(mod,'ingest_operator_feedback',lambda *a,**k:None)
        except ImportError: pass
    captured=[]
    def model(messages):
        text=messages[1]['content'];facts=json.loads(text.split('TRADE_AI_FACTS:\n',1)[1].split('\n\nSOFT_GAPS:',1)[0])
        captured.append(facts)
        return {'ok':True,'content':'The saved CIO review evidence is available. READ_ONLY_ADVISORY','model':'offline fixture'}
    monkeypatch.setattr(desk,'_operator_reply_llm',model)
    def converse(**kwargs):
        return conv.process_operator_message(**kwargs,dedup_path=tmp/'dedup.jsonl',msg_map_path=tmp/'msgmap.jsonl',rate_path=tmp/'rate.jsonl')
    from scripts.lib import symbol_thesis_priority as priority
    from scripts import api_v3_opportunities as api
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromisoformat(AT)
    monkeypatch.setattr(priority,'datetime',Clock)
    monkeypatch.setattr(priority,'_root',lambda root:tmp)
    monkeypatch.setattr(api,'_priority',lambda:priority)
    monkeypatch.setattr(life,'_store',lambda root=None:ir.InstrumentRecordStore(tmp/ir.DEFAULT_PATH))
    code,created=api.request_review('TSLA',{'note':'Resolve the guidance conflict'})
    assert code==200 and created['ok'] and created['review']['open']
    req={**REQ,'request_id':created['review']['lifecycle']['request_id']}
    requested_view=deepcopy(created['review'])
    # The actual request writer refreshed a different store instance.
    st._cache=None
    life.observe(req,'RESEARCHING',at='2026-10-24T14:10:00+00:00',**opts)
    life.observe(req,'ANSWERED_PENDING_CIO',at='2026-10-24T15:00:00+00:00',reason='Evidence A accepted, canonical decision pending',**opts)
    answered_view=api.review_state('TSLA')
    first=core.ask_from_cc('Explain the TSLA review outcome',request_id='c3-ask-one',chat_id='fixture-chat',deps=deps,converse=converse)
    assert first['ok'] and 'Evidence A accepted' in first['answer_text']
    assert captured[-1]['cio_record_research']['TSLA']['review_lifecycle']['request_id']==req['request_id']
    from scripts.lib import cio_theses
    from scripts.lib.symbol_thesis_publish import publish_symbol_thesis
    monkeypatch.setattr(cio_theses,'_now',lambda:'2026-10-24T15:30:00+00:00')
    thesis_store=cio_theses.CIOThesisStore(event_path=tmp/'data/cio/cio_theses_events.jsonl',projection_path=tmp/'data/cio/cio_theses_projection.json')
    monkeypatch.setattr(ir,'_now',lambda:NOW.isoformat())
    published=publish_symbol_thesis('TSLA',summary='Cited filing resolves the outdated guidance conflict',stance='add',
        store=thesis_store,notify=False,change_note='Cited filing resolves the outdated guidance conflict',
        provenance={'review_request_ids':[req['request_id']],'security_guid':GUID,'source_research_ids':['res-fixture'],
                    'reason_for_change':'Cited filing resolves the outdated guidance conflict'})
    rec=deepcopy(st.all()[0]);rec,_=ir.apply_prospect(rec,prospect={'stance':'ADD','conflicts':[]})
    st.upsert_prospect(rec,backend=pg,registry=REG,env=ENV)
    receipt=life.observe_cio_readback({**req,'published_version':published['thesis_version'],'thesis_id':published['thesis_id']},**opts)
    assert receipt['ok'],receipt
    second=core.ask_from_cc('Explain the TSLA review outcome',request_id='c3-ask-two',chat_id='fixture-chat',deps=deps,converse=converse)
    assert second['ok'] and 'Cited filing resolves the outdated guidance conflict' in second['answer_text']
    assert captured[-1]['cio_record_research']['TSLA']['review_lifecycle']['reason']=='Cited filing resolves the outdated guidance conflict'
    assert 'WATCH → ADD' in second['answer_text'] and 'res-fixture' in second['answer_text']
    assert 'never-public' not in json.dumps(captured)
    assert 'Cited filing resolves the outdated guidance conflict' in (tmp/'ask/cio_ask_events.jsonl').read_text()



    if os.environ.get('C3_UI_FIXTURE_OUT'):
        Path(os.environ['C3_UI_FIXTURE_OUT']).write_text(json.dumps({
            'fixture_only':True,'generated_by':'actual API request_review/review_state + real CIO publisher/IR/spine in isolated pinned fixtures',
            'requested':requested_view,'answered':answered_view,'resolved':api.review_state('TSLA'),
            'answer_text':second['answer_text'],
            'assessment_snapshot':{'symbol':'TSLA','security_guid':GUID,'stance':'WATCH','conviction':61,'as_of':AT},
            'canonical_assessment':{'symbol':'TSLA','security_guid':st.all()[0]['security_guid'],'stance':st.all()[0]['stance'],'conviction':st.all()[0]['conviction'],'as_of':st.all()[0]['updated_ts']},
            'published_thesis':{k:published.get(k) for k in ('thesis_version','summary','stance','owner_agent','updated_at','created_at','write_provenance')}},indent=2)+'\n')


def test_new_causal_request_survives_old_ttl_and_only_exact_terminal_closes(tmp_path):
    from scripts.lib import symbol_thesis_priority as p
    root=tmp_path/'data/cio';root.mkdir(parents=True)
    row={**REQ,'source':'operator_opportunity_view','requested_at':'2026-10-01T00:00:00+00:00'}
    (root/'symbol_thesis_priority_queue.jsonl').write_text(json.dumps(row)+'\n')
    assert p.open_requests(tmp_path,now=NOW)==['TSLA']
    done={'symbol':'TSLA','as_of':NOW.isoformat(),'status':'PUBLISHED','review_request_id':'wrong-id'}
    ledger=root/'symbol_thesis_acquisition_ledger.jsonl';ledger.write_text(json.dumps(done)+'\n')
    assert p.open_requests(tmp_path,now=NOW)==['TSLA']
    done['review_request_id']=REQ['request_id'];ledger.write_text(json.dumps(done)+'\n')
    assert p.open_requests(tmp_path,now=NOW)==[]


@pytest.mark.parametrize('result_status,expected',[('completed','ANSWERED_PENDING_CIO'),('truncated','BLOCKED'),('failed','BLOCKED')])
def test_actual_hermes_reuse_keeps_new_request_identity_and_quality_gate(setup,monkeypatch,result_status,expected):
    import importlib
    from scripts.lib import hermes_research_loop as loop
    st,pg,mem,opts=setup
    tmp=opts['root'];monkeypatch.chdir(tmp)
    life.observe(REQ,'REQUESTED',at=AT,**opts)
    plan={**REQ,'review_request_id':REQ['request_id'],'plan_id':'plan_fixture','symbols':['TSLA']}
    result={'research_id':'res-existing','result_id':'result-existing','status':result_status,'symbol':'TSLA',
            'subject_guid':GUID,'as_of':'2026-10-24T15:00:00+00:00','summary':'Accepted cited evidence',
            'sources':[{'url':'https://example.invalid/filing','title':'Tesla filing'}]}
    fakeplan={'plan_id':'plan_fixture','symbols':['TSLA'],'hermes_result_id':'result-existing','extra':{}}
    class Plans:
        def get_plan(self,p):return deepcopy(fakeplan)
        def update_plan(self,p,**kw):return {**fakeplan,**kw}
    monkeypatch.setattr(loop,'_import_plans',lambda:Plans)
    monkeypatch.setattr(loop,'_merge_evidence_on_plan_id',lambda *a,**kw:deepcopy(fakeplan))
    monkeypatch.setattr(loop,'expire_overlay_for_plan',lambda *a,**k:{'ok':True})
    monkeypatch.setattr(loop,'_now',lambda:NOW.isoformat())
    for prefix in ('scripts.lib.','lib.'):
        quality=importlib.import_module(prefix+'research_quality')
        monkeypatch.setattr(quality,'critique',lambda *a,**k:{'verdict':'VALID'})
        if prefix=='scripts.lib.':
            original=quality.evidence_eligibility
            monkeypatch.setattr(quality,'evidence_eligibility',lambda req,res,crit,**kw:original(req,res,crit,now=NOW))
        bridge=importlib.import_module(prefix+'research_memory_bridge');monkeypatch.setattr(bridge,'admit_from_research',lambda *a,**k:{'ok':True})
        circuit=importlib.import_module(prefix+'research_circuit');monkeypatch.setattr(circuit,'record_success',lambda:None)
        graph=importlib.import_module(prefix+'ticker_knowledge_graph')
        monkeypatch.setattr(graph,'ingest_hermes_result',lambda *a,**k:{})
        monkeypatch.setattr(graph,'ingest_existing_hermes_context',lambda *a,**k:{})
        case=importlib.import_module(prefix+'hermes_case_summary');monkeypatch.setattr(case,'mint_case_summary_from_attached_research',lambda *a,**k:{})
        enrich=importlib.import_module(prefix+'cio_plan_enrichment');monkeypatch.setattr(enrich,'enrich_plan',lambda *a,**k:{'plan':fakeplan})
        monkeypatch.setattr(enrich,'maybe_notify_plan',lambda *a,**k:pytest.fail('no notification allowed'))
        reassess=importlib.import_module(prefix+'cio_product_reassessment');monkeypatch.setattr(reassess,'reassess_on_research_completed',lambda *a,**k:{'ok':True})
        lineage=importlib.import_module(prefix+'intelligence_lineage');monkeypatch.setattr(lineage,'attach_research_completed',lambda *a,**k:{})
        monkeypatch.setattr(lineage,'cio_dir',lambda *a,**k:tmp/'data/cio')
        memo=importlib.import_module(prefix+'cio_desk_synthesis');monkeypatch.setattr(memo,'generate_desk_synthesis_v1',lambda *a,**k:None)
    gap=importlib.import_module('scripts.lib.research_gap');monkeypatch.setattr(gap,'reconcile_research_completion',lambda *a,**k:{})
    safe=life.safe_observe
    def bound(request,status,**kw):
        return safe(request,status,root=tmp,store=st,backend=pg,registry=REG,env=ENV,memory_writer=opts['memory_writer'],**kw)
    monkeypatch.setattr(life,'safe_observe',bound)
    out=loop.on_hermes_reused(plan,{'research_id':'res-existing','existing':result})
    assert out['review_lifecycle']['ok']
    saved=life.read('TSLA',root=tmp,store=st)
    assert saved['request_id']==REQ['request_id'] and saved['research_id']=='res-existing'
    assert saved['status']==expected and st.all()[0]['stance']=='WATCH'



def test_queue_append_failure_cannot_claim_canonical_requested(setup,monkeypatch):
    from scripts.lib import symbol_thesis_priority as priority
    st,pg,mem,opts=setup
    original=Path.open
    before=st.path.read_bytes()
    def denied(path,*a,**kw):
        if path.name=='symbol_thesis_priority_queue.jsonl':raise OSError('fixture queue full')
        return original(path,*a,**kw)
    monkeypatch.setattr(Path,'open',denied)
    with pytest.raises(OSError):priority.request('TSLA',reason='review',source='operator_opportunity_view',root=opts['root'],now=NOW)
    assert st.path.read_bytes()==before and mem==[] and pg.writes==[]
