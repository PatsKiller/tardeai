#!/usr/bin/env python3
"""Fixed read-only drift collector and host signer callback boundary.

The CLI never reads a private key and has no command/provider/action selector.
It obtains installed workflows through the existing SELECT-only inventory reader,
compares them with the current reviewed Git graph, and emits an unsigned signing
request plus a content-addressed snapshot. Without an externally provisioned host
signer, its status is BLOCKED_SIGNER_UNAVAILABLE and exit is1, never verified PASS.

A protected host service may call collect_and_sign with its Ed25519 sign callback.
That callback is not exposed to n8n, HTTP, environment variables or request JSON.
The service must execute this fixed collector itself; signing caller-supplied
payloads would defeat the provenance boundary. No unit is installed by this source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# This is an uninstalled, explicitly blocked host entrypoint; no scheduler or signer caller exists yet.
# The declaration records lifecycle truth for the dark-contract gate. It does not certify provenance.
NO_CONSUMER_REASON = (
    "Not installed: CLI-only read-only host signing-request candidate; protected trust and an isolated "
    "operator-provisioned signer remain unavailable. No scheduler/service consumes this entrypoint. "
    "Unsigned CLI output is BLOCKED_SIGNER_UNAVAILABLE and cannot satisfy the runtime verifier."
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from scripts.lib import n8n_evidence_attestation as A
from scripts.lib import n8n_live_inventory as I
from scripts import check_n8n_workflow_drift as D
from scripts import check_n8n_workflow_framework as F
from scripts import n8n_workflow_templates as T

SCHEMA = 'N8nHostEvidenceSigningRequest@v1'


def source_sha(root: Path = ROOT) -> str:
    """The deployed artifact must publish its exact identity; no Git fallback."""
    value = (root/'GIT_SHA').read_text().strip()
    return A._hex(value,A.SHA,'collector served SHA')


def reviewed_workflows() -> dict:
    result = {}
    for path in F.committed_workflow_files(ROOT):
        doc = A.strict_json(path.read_bytes())
        wid = str(doc.get('id') or '')
        if not wid:
            raise A.EvidenceError('reviewed workflow identity unavailable')
        if wid in result and result[wid] != doc:
            raise A.EvidenceError('ambiguous reviewed workflow identity')
        result[wid] = doc
    return result


def _persist_snapshot(trust, snapshot):
    data = A.canonical(snapshot)
    digest = hashlib.sha256(data).hexdigest()
    # Existing protected service provisioning must create this directory. No arbitrary paths.
    ref = f'workflow-drift-{digest}.json'
    directory = os.open(trust.evidence_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fd = os.open(ref,os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,0o640,dir_fd=directory)
        except FileExistsError:
            if A.read_artifact(trust.evidence_root,ref) != data:
                raise A.EvidenceError('immutable snapshot conflict')
        else:
            with os.fdopen(fd,'wb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.fsync(directory)
    finally:
        os.close(directory)
    return {'ref':ref,'sha256':digest}


def collect_request(trust: A.TrustPolicy, workflow_id: str, key_id: str, *, now=None,
                    read_live=None, read_reviewed=None, read_sha=None) -> dict:
    """Fixed adapter for L5b only. Injected readers exist for hermetic host-adapter tests."""
    fixed_now = now
    now = now or datetime.now(timezone.utc)
    started_at = now
    key = trust.keys.get(key_id)
    if key is None or workflow_id not in key['workflow_ids'] or '23.24-L5b' not in key['obligation_ids'] or A.AUDIENCE not in key['audiences']:
        raise A.EvidenceError('collector outside provisioned signer scope')
    if not A.utc(key['not_before']) <= now < A.utc(key['expires_at']):
        raise A.EvidenceError('signing principal expired or not yet valid')
    sha = (read_sha or source_sha)()
    if sha != trust.served_sha:
        raise A.EvidenceError('collector source/deployment mismatch')
    # Reader exceptions and missing rows stay UNAVAILABLE. No fixture/file/LLM input CLI exists.
    reviewed = (read_reviewed or reviewed_workflows)().get(workflow_id)
    if not isinstance(reviewed,dict):
        raise A.EvidenceError('reviewed workflow unavailable')
    rows = [w for w in (read_live or I.read_workflow_bodies)() if str(w.get('id')) == workflow_id]
    if len(rows) != 1 or rows[0].get('active') is not True:
        raise A.EvidenceError('installed workflow unavailable, ambiguous or inactive')
    live = rows[0]
    through = fixed_now or datetime.now(timezone.utc)
    timestamp = through.isoformat()
    # Only workflow behavior enters evidence; unrelated metadata or server fields are not copied.
    def behavior(workflow):
        return {**{k:workflow.get(k) for k in ('id','name','active','connections','settings')},
                'nodes':[{k:v for k,v in node.items() if k not in D.DROP_NODE_KEYS} for node in workflow.get('nodes') or []]}
    snapshot = {'schema':A.SNAPSHOT_SCHEMA,'source':'host:n8n-live-inventory','workflow_id':workflow_id,
                'graph_sha256':T.graph_hash(reviewed),'policy_sha256':T.policy_hash(),
                'served_sha':sha,'evaluation_id':trust.evaluation_id,'observed_at':timestamp,
                'live_workflow':live,'reviewed_workflow':reviewed}
    A._verify_drift_snapshot(snapshot,{**snapshot,'obligation_id':'23.24-L5b',
                                      'observed_from':started_at.isoformat(),'observed_through':timestamp})
    snapshot['live_workflow'],snapshot['reviewed_workflow']=behavior(live),behavior(reviewed)
    artifact = _persist_snapshot(trust,snapshot)
    # A short-lived observation does not attest schedule uptime or continuous coverage.
    issued = fixed_now or datetime.now(timezone.utc)
    expiry = min(started_at+timedelta(seconds=min(trust.max_age_seconds,900)),A.utc(key['expires_at']))
    if issued >= expiry:
        raise A.EvidenceError('collection exceeded its absolute observation deadline')
    payload = {'evidence_id':uuid.uuid4().hex,'principal':key['principal'],'audience':A.AUDIENCE,
               'workflow_id':workflow_id,'graph_sha256':snapshot['graph_sha256'],'policy_sha256':snapshot['policy_sha256'],
               'served_sha':sha,'evaluation_id':trust.evaluation_id,'obligation_id':'23.24-L5b','verdict':'PASS',
               'observed_from':started_at.isoformat(),'observed_through':timestamp,'issued_at':issued.isoformat(),
               'expires_at':expiry.isoformat(),'artifacts':[artifact]}
    return {'schema':SCHEMA,'state':'BLOCKED_SIGNER_UNAVAILABLE','authenticated':False,
            'required_principal':key['principal'],'key_id':key_id,'payload':payload,
            'qualification':'Point parity only; not continuous coverage or other runtime obligations'}


def collect_and_sign(trust, workflow_id, key_id, *, sign=None, now=None, **readers):
    request = collect_request(trust,workflow_id,key_id,now=now,**readers)
    if sign is None:
        return request
    envelope = A.sign_payload(request['payload'],key_id=key_id,sign=sign)
    expected = {k:request['payload'][k] for k in ('workflow_id','graph_sha256','policy_sha256','served_sha','evaluation_id','obligation_id','audience')}
    verification = A.verify_attestation(envelope,expected=expected,trust=trust,now=now)
    if not verification['ok']:
        raise A.EvidenceError('host signer output failed verification: '+verification['reason'])
    return {'schema':F.RUNTIME_EVIDENCE_SCHEMA,'workflows':{workflow_id:{'23.24-L5b':envelope}}}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--workflow-id',required=True)
    parser.add_argument('--key-id',required=True,help='Existing provisioned public principal; never creates a key')
    args=parser.parse_args(argv)
    try:
        result=collect_and_sign(A.load_trust_policy(),args.workflow_id,args.key_id)
    except Exception as exc:  # Reader failure cannot yield a signable PASS or leak source rows.
        print(json.dumps({'schema':SCHEMA,'state':'UNAVAILABLE','authenticated':False,
                          'reason':type(exc).__name__,'detail':'host trust or fixed observation unavailable'}))
        return 2
    print(json.dumps(result,sort_keys=True))
    return 1  # Standalone CLI has no host signer; an unsigned request never proves runtime evidence.


if __name__ == '__main__':
    raise SystemExit(main())
