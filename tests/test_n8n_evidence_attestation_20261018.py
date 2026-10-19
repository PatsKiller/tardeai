"""Authentic host evidence: ephemeral Ed25519 fixtures and fake artifacts only."""
from scripts import check_n8n_workflow_framework as F


def row():
    return {'id':'fixture-workflow','elements':{'FW-W1':{'status':F.PASS,'reason':'fixture'}},
            'runtime':[{'id':'23.24-L5b','status':F.UNPROVEN,'evidence_required':'host live parity'}],
            'runtime_outcome':{'status':F.UNPROVEN},'deployed_parity':{'status':F.UNPROVEN}}


def test_self_asserted_v1_references_never_satisfy_activation():
    r=row()
    evidence={'schema':'N8nFrameworkRuntimeEvidence@v1','workflows':{r['id']:{'23.24-L5b':{'ref':'made-up.json','observed_at':'2099-01-01'}}}}
    result=F.gate_workflow(r,platform={},runtime_evidence=evidence,exceptions=[])
    assert result['eligible'] is False


def test_self_asserted_operator_exception_never_creates_authority():
    r=row();r['runtime']=[];r['elements']['FW-W1']['status']=F.FAIL
    exc={'workflow_id':r['id'],'element':'FW-W1','accepted_by':'operator','pr':123,'expires':'2099-01-01'}
    result=F.gate_workflow(r,platform={},runtime_evidence={},exceptions=[exc],today='2026-10-18')
    assert result['eligible'] is False


def test_legacy_v1_remains_readable_but_unproven_in_report():
    r=row()
    evidence={'schema':'N8nFrameworkRuntimeEvidence@v1','workflows':{r['id']:{'23.24-L5b':{'ref':'old-receipt.json','observed_at':'2026-10-15'}}}}
    F.apply_runtime_evidence(r,evidence)
    assert r['runtime'][0]['status']==F.UNPROVEN
    assert r['deployed_parity']['status']==F.UNPROVEN

import base64
import copy
import hashlib
import json
from datetime import datetime,timedelta,timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.lib import n8n_evidence_attestation as A
from scripts import n8n_evidence_host_collector as C
from scripts import n8n_workflow_templates as T

NOW=datetime(2026,10,18,19,tzinfo=timezone.utc)


@pytest.fixture
def signed(tmp_path):
    private=Ed25519PrivateKey.generate()  # ephemeral in-memory fixture only; never persisted
    doc={'schema':A.TRUST_SCHEMA,'served_sha':'a'*40,'evaluation_id':'fixture-admission-generation-1',
         'evidence_root':str(tmp_path),'max_age_seconds':900,'keys':[{
         'key_id':'fixture-key','principal':'host:fixture-collector',
         'public_key_base64':base64.b64encode(private.public_key().public_bytes_raw()).decode(),
         'audiences':[A.AUDIENCE],'workflow_ids':['fixture-workflow'],'obligation_ids':['23.24-L5b'],
         'not_before':(NOW-timedelta(days=1)).isoformat(),'expires_at':(NOW+timedelta(days=1)).isoformat()}]}
    trust=A.parse_trust_policy(doc)
    reviewed={'id':'fixture-workflow','name':'Fixture','active':False,'nodes':[], 'connections':{},'settings':{}}
    live={**reviewed,'active':True}
    readers=dict(read_live=lambda:[copy.deepcopy(live)],read_reviewed=lambda:{reviewed['id']:copy.deepcopy(reviewed)},read_sha=lambda:'a'*40)
    bundle=C.collect_and_sign(trust,'fixture-workflow','fixture-key',sign=private.sign,now=NOW,**readers)
    envelope=bundle['workflows']['fixture-workflow']['23.24-L5b']
    expected={k:envelope['payload'][k] for k in ('workflow_id','graph_sha256','policy_sha256','served_sha','evaluation_id','obligation_id','audience')}
    return dict(private=private,trust=trust,doc=doc,bundle=bundle,envelope=envelope,expected=expected,readers=readers,root=tmp_path)


def verify(fixture,envelope=None,**kwargs):
    return A.verify_attestation(envelope or fixture['envelope'],expected=fixture['expected'],trust=fixture['trust'],now=kwargs.pop('now',NOW),**kwargs)


def resign(fixture,payload):
    return A.sign_payload(payload,key_id='fixture-key',sign=fixture['private'].sign)


def test_genuine_fixed_collector_signature_reaches_same_shared_gate(signed):
    assert verify(signed)['ok']
    r=row();r['evidence_identity']={k:signed['expected'][k] for k in ('workflow_id','graph_sha256','policy_sha256')}
    F.apply_runtime_evidence(r,signed['bundle'],evidence_trust=signed['trust'],now=NOW)
    assert r['runtime'][0]['status']==F.EVIDENCED and r['deployed_parity']['status']==F.EVIDENCED
    assert F.gate_workflow(r,platform={},runtime_evidence=signed['bundle'],exceptions=[],evidence_trust=signed['trust'],now=NOW)['eligible']
    # Revocation is consulted again; a previously populated EVIDENCED row is not a cache of authority.
    revoked=A.TrustPolicy(signed['trust'].served_sha,signed['trust'].evaluation_id,signed['root'],900,{})
    F.apply_runtime_evidence(r,signed['bundle'],evidence_trust=revoked,now=NOW)
    assert r['runtime'][0]['status']==F.UNPROVEN
    assert not F.gate_workflow(r,platform={},runtime_evidence=signed['bundle'],exceptions=[],evidence_trust=revoked,now=NOW)['eligible']


@pytest.mark.parametrize('field,value',[
    ('workflow_id','other-workflow'),('graph_sha256','b'*64),('policy_sha256','c'*64),
    ('served_sha','b'*40),('evaluation_id','fixture-admission-generation-2'),
    ('obligation_id','23.24-R2b'),('audience','n8n-retirement'),('principal','host:other')])
def test_valid_signature_cannot_replay_for_another_exact_identity(signed,field,value):
    payload=copy.deepcopy(signed['envelope']['payload']);payload[field]=value
    result=verify(signed,resign(signed,payload))
    assert not result['ok'] and result['state']=='UNPROVEN'


def test_identical_fresh_observation_can_be_rechecked_but_new_generation_refused(signed):
    assert verify(signed)['ok'] and verify(signed)['ok']
    changed=A.TrustPolicy(signed['trust'].served_sha,'new-host-admission-generation',signed['root'],900,signed['trust'].keys)
    assert not A.verify_attestation(signed['envelope'],expected=signed['expected'],trust=changed,now=NOW)['ok']


def test_forged_signature_and_unprovisioned_key_refused(signed):
    attacker=Ed25519PrivateKey.generate()
    assert not verify(signed,A.sign_payload(signed['envelope']['payload'],key_id='fixture-key',sign=attacker.sign))['ok']
    envelope=copy.deepcopy(signed['envelope']);envelope['signature']['key_id']='unprovisioned-key'
    assert not verify(signed,envelope)['ok']


@pytest.mark.parametrize('offset',[-901,1])
def test_stale_or_future_observation_never_passes(signed,offset):
    p=copy.deepcopy(signed['envelope']['payload'])
    instant=NOW+timedelta(seconds=offset)
    for field in ('observed_from','observed_through','issued_at'):p[field]=instant.isoformat()
    assert not verify(signed,resign(signed,p))['ok']


def test_expired_key_and_expired_evidence_refused(signed):
    assert not verify(signed,now=NOW+timedelta(seconds=900))['ok']
    signed['trust'].keys['fixture-key']['expires_at']=NOW.isoformat()
    assert not verify(signed)['ok']


@pytest.mark.parametrize('verdict',['FAIL','UNAVAILABLE','SYSTEM RECOVERED','pass'])
def test_wrong_host_verdict_never_means_pass(signed,verdict):
    payload=copy.deepcopy(signed['envelope']['payload']);payload['verdict']=verdict
    assert not verify(signed,resign(signed,payload))['ok']


def test_artifact_tampering_and_signed_lying_semantics_refused(signed):
    path=signed['root']/signed['envelope']['payload']['artifacts'][0]['ref']
    original=path.read_bytes();path.write_bytes(b'{}')
    assert not verify(signed)['ok']
    path.write_bytes(original)
    snapshot=A.strict_json(original)
    snapshot['live_workflow']['settings']={'executionTimeout':1}
    raw=A.canonical(snapshot);path.write_bytes(raw)
    p=copy.deepcopy(signed['envelope']['payload']);p['artifacts'][0]['sha256']=hashlib.sha256(raw).hexdigest()
    result=verify(signed,resign(signed,p))
    assert not result['ok'] and 'drift' in result['reason']


@pytest.mark.parametrize('ref',['../outside.json','/etc/passwd','dir/../../outside','https://fixture.invalid/data','./snapshot'])
def test_artifact_escape_and_indirect_destinations_refused(signed,ref):
    p=copy.deepcopy(signed['envelope']['payload']);p['artifacts'][0]['ref']=ref
    assert not verify(signed,resign(signed,p))['ok']


def test_symlinked_artifact_refused(signed):
    original=signed['envelope']['payload']['artifacts'][0]['ref']
    (signed['root']/'linked.json').symlink_to(signed['root']/original)
    p=copy.deepcopy(signed['envelope']['payload']);p['artifacts'][0]['ref']='linked.json'
    assert not verify(signed,resign(signed,p))['ok']


@pytest.mark.parametrize('where',['envelope','payload','signature','artifact'])
def test_unknown_signed_contract_fields_refused(signed,where):
    envelope=copy.deepcopy(signed['envelope'])
    target={'envelope':envelope,'payload':envelope['payload'],'signature':envelope['signature'],'artifact':envelope['payload']['artifacts'][0]}[where]
    target['extra_authority']='anything'
    assert not verify(signed,envelope)['ok']


@pytest.mark.parametrize('raw',['{"a":1,"a":2}','{"claim":{"same":1,"s\\u0061me":2}}','{"a":NaN}','{"a":1e309}'])
def test_duplicate_and_nonfinite_authority_json_rejected(raw):
    with pytest.raises(A.EvidenceError):A.strict_json(raw)


def test_missing_crypto_backend_and_artifact_fail_closed(signed,monkeypatch):
    def unavailable():raise A.EvidenceError('Ed25519 verification backend unavailable')
    monkeypatch.setattr(A,'_backend',unavailable)
    assert not verify(signed)['ok']
    monkeypatch.undo()
    (signed['root']/signed['envelope']['payload']['artifacts'][0]['ref']).unlink()
    assert not verify(signed)['ok']


def test_unprotected_trust_file_cannot_supply_a_signing_principal(signed):
    path=signed['root']/'trust.json';path.write_text(json.dumps(signed['doc']))
    with pytest.raises(A.EvidenceError,match='root-protected'):A.load_trust_policy(path)


@pytest.mark.parametrize('mutation',[lambda d:d.update(extra='authority'), lambda d:d.update(schema='N8nEvidenceTrust@v2'), lambda d:d['keys'][0].update(workflow_ids=['*']), lambda d:d.update(max_age_seconds=True)])
def test_closed_provisioned_trust_rejects_unsafe_shape(signed,mutation):
    doc=copy.deepcopy(signed['doc']);mutation(doc)
    with pytest.raises(A.EvidenceError):A.parse_trust_policy(doc)


def test_version_pairs_and_unknown_major_have_explicit_behavior(signed,tmp_path):
    path=tmp_path/'runtime.json'
    old={'schema':F.LEGACY_RUNTIME_EVIDENCE_SCHEMA,'workflows':{}}
    path.write_text(json.dumps(old));assert F._load_optional(str(path),F.RUNTIME_EVIDENCE_SCHEMA)==old
    path.write_text(json.dumps(signed['bundle']));assert F._load_optional(str(path),F.RUNTIME_EVIDENCE_SCHEMA)==signed['bundle']
    with pytest.raises(ValueError):F._load_optional(str(path),F.LEGACY_RUNTIME_EVIDENCE_SCHEMA)
    path.write_text('{"schema":"N8nFrameworkRuntimeEvidence@v99","workflows":{}}')
    with pytest.raises(ValueError):F._load_optional(str(path),F.RUNTIME_EVIDENCE_SCHEMA)


def test_runtime_loader_rejects_duplicate_members(signed,tmp_path):
    path=tmp_path/'runtime.json';path.write_text('{"schema":"N8nFrameworkRuntimeEvidence@v2","workflows":{},"workflows":{}}')
    with pytest.raises(ValueError):F._load_optional(str(path),F.RUNTIME_EVIDENCE_SCHEMA)


def test_absent_external_trust_is_unproven_even_for_valid_signature(signed,monkeypatch):
    def unavailable():raise A.EvidenceError('trusted host signer configuration unavailable')
    monkeypatch.setattr(A,'load_trust_policy',unavailable)
    r=row();r['evidence_identity']={k:signed['expected'][k] for k in ('workflow_id','graph_sha256','policy_sha256')}
    result=F.gate_workflow(r,platform={},runtime_evidence=signed['bundle'],exceptions=[],now=NOW)
    assert not result['eligible'] and 'configuration unavailable' in ' '.join(result['blocking'])


def test_collector_without_signer_never_emits_verified_success(signed):
    request=C.collect_and_sign(signed['trust'],'fixture-workflow','fixture-key',now=NOW,**signed['readers'])
    assert request['state']=='BLOCKED_SIGNER_UNAVAILABLE' and request['authenticated'] is False
    assert request['schema']==C.SCHEMA and 'signature' not in request


@pytest.mark.parametrize('kind',['unavailable','missing','inactive','drift','wrong_release'])
def test_fixed_collector_failures_never_emit_a_signable_pass(signed,kind):
    readers=copy.copy(signed['readers'])
    if kind=='unavailable':
        def bad():raise OSError('fixture DB unavailable')
        readers['read_live']=bad
    elif kind=='missing':readers['read_live']=lambda:[]
    elif kind=='inactive':readers['read_live']=lambda:[{'id':'fixture-workflow','active':False}]
    elif kind=='drift':readers['read_live']=lambda:[{'id':'fixture-workflow','active':True,'nodes':[],'settings':{'executionTimeout':1}}]
    else:readers['read_sha']=lambda:'b'*40
    with pytest.raises((A.EvidenceError,OSError)):
        C.collect_and_sign(signed['trust'],'fixture-workflow','fixture-key',now=NOW,**readers)


def test_collector_cli_has_no_trust_key_or_executable_override(capsys):
    with pytest.raises(SystemExit):C.main(['--workflow-id','fixture-workflow','--key-id','fixture-key','--trust','untrusted.json'])
    assert 'unrecognized arguments' in capsys.readouterr().err


@pytest.mark.parametrize('nodes',[[None],[{'id':'one','name':'same'},{'id':'two','name':'same'}]])
def test_even_signed_malformed_or_duplicate_live_nodes_are_unproven(signed,nodes):
    path=signed['root']/signed['envelope']['payload']['artifacts'][0]['ref']
    snapshot=A.strict_json(path.read_bytes());snapshot['live_workflow']['nodes']=nodes
    data=A.canonical(snapshot);path.write_bytes(data)
    p=copy.deepcopy(signed['envelope']['payload']);p['artifacts'][0]['sha256']=hashlib.sha256(data).hexdigest()
    assert not verify(signed,resign(signed,p))['ok']


def test_production_collector_path_uses_existing_live_reader_without_accepting_payload(signed,monkeypatch):
    reads=[]
    def read_live():
        reads.append('fixed-live-inventory')
        return signed['readers']['read_live']()
    monkeypatch.setattr(C.I,'read_workflow_bodies',read_live)
    monkeypatch.setattr(C,'reviewed_workflows',signed['readers']['read_reviewed'])
    monkeypatch.setattr(C,'source_sha',signed['readers']['read_sha'])
    request=C.collect_and_sign(signed['trust'],'fixture-workflow','fixture-key',now=NOW)
    assert reads==['fixed-live-inventory']
    assert request['state']=='BLOCKED_SIGNER_UNAVAILABLE'


def test_wrong_signer_callback_is_rejected_after_real_collector(signed):
    with pytest.raises(A.EvidenceError,match='failed verification'):
        C.collect_and_sign(signed['trust'],'fixture-workflow','fixture-key',sign=Ed25519PrivateKey.generate().sign,now=NOW,**signed['readers'])


def test_unregistered_runtime_obligation_has_no_semantic_pass_adapter(signed):
    p=copy.deepcopy(signed['envelope']['payload']);p['obligation_id']='23.24-R2b'
    expected={**signed['expected'],'obligation_id':'23.24-R2b'}
    signed['trust'].keys['fixture-key']['obligation_ids'].append('23.24-R2b')
    result=A.verify_attestation(resign(signed,p),expected=expected,trust=signed['trust'],now=NOW)
    assert not result['ok'] and 'adapter unavailable' in result['reason']


@pytest.mark.parametrize('workflows',[[{'anything':'authority'}],{'fixture-workflow':[]},{'fixture-workflow':{'23.24-L5b':{'schema':A.SCHEMA}}}])
def test_v2_nested_shape_is_closed_at_loader(signed,tmp_path,workflows):
    path=tmp_path/'bad-runtime.json';path.write_text(json.dumps({'schema':F.RUNTIME_EVIDENCE_SCHEMA,'workflows':workflows}))
    with pytest.raises(ValueError):F._load_optional(str(path),F.RUNTIME_EVIDENCE_SCHEMA)


def test_collector_does_not_persist_unrelated_workflow_metadata(signed):
    readers=copy.copy(signed['readers'])
    def live():
        return [{**signed['readers']['read_live']()[0],'meta':{'unrelated':'never copied'}}]
    readers['read_live']=live
    req=C.collect_request(signed['trust'],'fixture-workflow','fixture-key',now=NOW,**readers)
    raw=A.read_artifact(signed['root'],req['payload']['artifacts'][0]['ref'])
    assert b'never copied' not in raw
