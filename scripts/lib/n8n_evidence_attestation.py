"""Signed host observations, never grants. Public trust configuration is operator provisioned.

The default root-owned trust file pins deployment/generation, public signer keys and
exact workflow/obligation scopes. No key in an evidence envelope establishes trust.
No private-key file or environment is read here. Rechecking the same observation is
safe; reuse for another subject or admission generation is refused. Missing crypto,
trust, artifacts or a semantic adapter is UNPROVEN, never PASS.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = 'N8nHostEvidenceAttestation@v1'
TRUST_SCHEMA = 'N8nEvidenceTrust@v1'
SNAPSHOT_SCHEMA = 'N8nHostDriftSnapshot@v1'
DEFAULT_TRUST = Path('/etc/tradeai/n8n-evidence-trust.json')
AUDIENCE = 'n8n-framework-activation'
DIGEST = re.compile(r'[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')
MAX_BYTES = 16 * 1024 * 1024
PAYLOAD_FIELDS = frozenset({'evidence_id','principal','audience','workflow_id','graph_sha256','policy_sha256',
    'served_sha','evaluation_id','obligation_id','verdict','observed_from','observed_through','issued_at','expires_at','artifacts'})


class EvidenceError(ValueError):
    pass


def _closed(doc: Any, fields, label: str):
    if not isinstance(doc, dict) or set(doc) != set(fields):
        raise EvidenceError(f'{label}: missing or unknown fields')
    return doc


def _pairs(pairs):
    doc = {}
    for key, value in pairs:
        if key in doc:
            raise EvidenceError('duplicate JSON member')
        doc[key] = value
    return doc


def _number(text):
    val = float(text)
    if not math.isfinite(val):
        raise EvidenceError('nonfinite JSON number')
    return val


def strict_json(data: str | bytes):
    try:
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=_number, parse_float=_number)
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise EvidenceError(f'invalid JSON: {exc}') from exc


def canonical(doc: Mapping) -> bytes:
    try:
        return json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    except (ValueError, TypeError) as exc:
        raise EvidenceError('noncanonical evidence') from exc


def utc(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise EvidenceError('invalid UTC timestamp')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise EvidenceError('invalid UTC timestamp') from exc
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise EvidenceError('timestamp must be UTC aware')
    return result.astimezone(timezone.utc)


def _text(value, label):
    if not isinstance(value, str) or not value or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise EvidenceError(f'invalid {label}')
    return value


def _hex(value, pattern, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise EvidenceError(f'invalid {label}')
    return value


def _b64(value, size):
    if not isinstance(value, str):
        raise EvidenceError('invalid base64')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise EvidenceError('invalid base64') from exc
    if len(raw) != size:
        raise EvidenceError('invalid key or signature size')
    return raw


@dataclass(frozen=True)
class TrustPolicy:
    served_sha: str
    evaluation_id: str
    evidence_root: Path
    max_age_seconds: int
    keys: dict[str, dict]


def parse_trust_policy(doc: dict) -> TrustPolicy:
    """Parse an already authenticated host config; callers must not use evidence-supplied keys."""
    _closed(doc, {'schema','served_sha','evaluation_id','evidence_root','max_age_seconds','keys'}, 'trust')
    if doc['schema'] != TRUST_SCHEMA:
        raise EvidenceError('unsupported trust schema')
    _hex(doc['served_sha'], SHA, 'served SHA')
    _text(doc['evaluation_id'], 'evaluation generation')
    root = Path(_text(doc['evidence_root'], 'evidence root'))
    if not root.is_absolute() or '..' in root.parts:
        raise EvidenceError('evidence root must be absolute')
    age = doc['max_age_seconds']
    if type(age) is not int or not 1 <= age <= 86400:
        raise EvidenceError('max evidence age out of range')
    if not isinstance(doc['keys'], list) or not doc['keys'] or len(doc['keys']) > 32:
        raise EvidenceError('missing public signing principals')
    keys = {}
    for key in doc['keys']:
        _closed(key, {'key_id','principal','public_key_base64','audiences','workflow_ids','obligation_ids','not_before','expires_at'}, 'signer')
        kid = _text(key['key_id'], 'key id')
        if kid in keys:
            raise EvidenceError('duplicate key id')
        _text(key['principal'], 'signing principal')
        _b64(key['public_key_base64'], 32)
        for field in ('audiences','workflow_ids','obligation_ids'):
            values = key[field]
            if not isinstance(values, list) or not values or len(values) != len(set(map(str, values))):
                raise EvidenceError(f'invalid {field}')
            for value in values:
                _text(value, field)
                if '*' in value:
                    raise EvidenceError('wildcard signer scope forbidden')
        if utc(key['not_before']) >= utc(key['expires_at']):
            raise EvidenceError('invalid signer validity')
        keys[kid] = dict(key)
    return TrustPolicy(doc['served_sha'], doc['evaluation_id'], root, age, keys)


def load_trust_policy(path: Path = DEFAULT_TRUST) -> TrustPolicy:
    """Only root-owned, non-writable config and ancestor directories establish CLI trust.

    There is deliberately no environment override or CLI flag to supply untrusted keys.
    Public key rotation/revocation and context changes are external operator actions.
    """
    path = Path(path)
    if not path.is_absolute():
        raise EvidenceError('trust config must be absolute')
    try:
        for part in [path, *path.parents]:
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise EvidenceError('trust config path is not root-protected')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > MAX_BYTES:
                raise EvidenceError('trust config is not a protected regular file')
            data = stream.read(MAX_BYTES + 1)
        return parse_trust_policy(strict_json(data))
    except OSError as exc:
        raise EvidenceError('trusted host signer configuration unavailable') from exc


def read_artifact(root: Path, ref: str) -> bytes:
    """Open beneath the protected configured root with no symlink traversal; bounded reads."""
    if not isinstance(ref, str) or not ref or len(ref) > 1024 or '\\' in ref:
        raise EvidenceError('invalid artifact reference')
    parts = ref.split('/')
    if any(p in ('', '.', '..') for p in parts) or Path(ref).is_absolute():
        raise EvidenceError('artifact reference escapes evidence root')
    fds = []
    try:
        fds.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for part in parts[:-1]:
            fds.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fds[-1])
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise EvidenceError('artifact is not a bounded regular file')
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise EvidenceError('artifact too large')
        return data
    except OSError as exc:
        raise EvidenceError('artifact unavailable or symlinked') from exc
    finally:
        for fd in reversed(fds):
            os.close(fd)


def _backend():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise EvidenceError('Ed25519 verification backend unavailable') from exc
    return Ed25519PublicKey


def verify_attestation(envelope: dict, *, expected: Mapping, trust: TrustPolicy, now: datetime | None = None) -> dict:
    """One verifier shared by framework and later observation/retirement adapters.

    Signature authenticates origin; the registered semantic adapter establishes meaning.
    Observations are reusable for the identical context while fresh; they grant no action.
    """
    try:
        _closed(envelope, {'schema','payload','signature'}, 'attestation')
        if envelope['schema'] != SCHEMA:
            raise EvidenceError('unsupported attestation version')
        p = _closed(envelope['payload'], PAYLOAD_FIELDS, 'payload')
        signature = _closed(envelope['signature'], {'algorithm','key_id','value'}, 'signature')
        if signature['algorithm'] != 'Ed25519':
            raise EvidenceError('unsupported signature algorithm')
        key = trust.keys.get(_text(signature['key_id'], 'key id'))
        if key is None:
            raise EvidenceError('unknown or revoked signing principal')
        _hex(p['graph_sha256'], DIGEST, 'graph digest'); _hex(p['policy_sha256'], DIGEST, 'policy digest')
        _hex(p['served_sha'], SHA, 'served SHA')
        for name in ('evidence_id','principal','audience','workflow_id','evaluation_id','obligation_id'):
            _text(p[name], name)
        for name in ('workflow_id','graph_sha256','policy_sha256','served_sha','evaluation_id','obligation_id','audience'):
            if p[name] != expected.get(name):
                raise EvidenceError(f'evidence identity mismatch: {name}')
        if p['served_sha'] != trust.served_sha or p['evaluation_id'] != trust.evaluation_id:
            raise EvidenceError('deployment or evaluation generation changed')
        if p['principal'] != key['principal']:
            raise EvidenceError('principal mismatch')
        for name, scope in (('audience','audiences'),('workflow_id','workflow_ids'),('obligation_id','obligation_ids')):
            if p[name] not in key[scope]:
                raise EvidenceError(f'signer outside {scope}')
        instant = now or datetime.now(timezone.utc)
        if not isinstance(instant, datetime) or instant.tzinfo is None:
            raise EvidenceError('verifier clock unavailable')
        start, end, issued, expires = [utc(p[x]) for x in ('observed_from','observed_through','issued_at','expires_at')]
        age = trust.max_age_seconds
        if not (utc(key['not_before']) <= start <= end <= issued <= instant < expires <= utc(key['expires_at'])):
            raise EvidenceError('invalid, future, expired or revoked evidence window')
        if (instant - start).total_seconds() > age or (expires - start).total_seconds() > age:
            raise EvidenceError('stale evidence window')
        if p['verdict'] not in ('PASS','FAIL','UNAVAILABLE'):
            raise EvidenceError('invalid evidence verdict')
        public = _backend().from_public_bytes(_b64(key['public_key_base64'],32))
        try:
            public.verify(_b64(signature['value'],64), canonical(p))
        except Exception as exc:
            raise EvidenceError('invalid evidence signature') from exc
        artifacts = p['artifacts']
        if not isinstance(artifacts,list) or len(artifacts) != 1:
            raise EvidenceError('registered drift adapter needs one artifact')
        artifact = _closed(artifacts[0], {'ref','sha256'}, 'artifact')
        digest = _hex(artifact['sha256'],DIGEST,'artifact digest')
        raw = read_artifact(trust.evidence_root,artifact['ref'])
        if hashlib.sha256(raw).hexdigest() != digest:
            raise EvidenceError('artifact digest mismatch')
        if p['verdict'] != 'PASS':
            raise EvidenceError(f'host observation {p["verdict"]}')
        _verify_drift_snapshot(strict_json(raw), p)
        return {'ok':True,'state':'VERIFIED','evidence_id':p['evidence_id'],'principal':p['principal'],
                'key_id':signature['key_id'],'observed_at':p['observed_through'],'artifacts':artifacts}
    except (EvidenceError, TypeError, ValueError, KeyError) as exc:
        return {'ok':False,'state':'UNPROVEN','reason':str(exc)}


def _verify_drift_snapshot(doc: dict, p: dict) -> None:
    """Recompute actual live-vs-reviewed graph parity, not a caller's CLEAN/PASS flag."""
    if p['obligation_id'] != '23.24-L5b':
        raise EvidenceError('semantic evidence adapter unavailable for obligation')
    _closed(doc, {'schema','source','workflow_id','graph_sha256','policy_sha256','served_sha','evaluation_id',
                  'observed_at','live_workflow','reviewed_workflow'}, 'drift snapshot')
    if doc['schema'] != SNAPSHOT_SCHEMA or doc['source'] != 'host:n8n-live-inventory':
        raise EvidenceError('unsupported live observation provenance')
    for field in ('workflow_id','graph_sha256','policy_sha256','served_sha','evaluation_id'):
        if doc[field] != p[field]:
            raise EvidenceError(f'artifact identity mismatch: {field}')
    if not utc(p['observed_from']) <= utc(doc['observed_at']) <= utc(p['observed_through']):
        raise EvidenceError('artifact outside observation window')
    live, reviewed = doc['live_workflow'],doc['reviewed_workflow']
    if not isinstance(live,dict) or not isinstance(reviewed,dict) or live.get('id') != p['workflow_id'] or reviewed.get('id') != p['workflow_id'] or live.get('active') is not True:
        raise EvidenceError('live workflow missing, inactive or another identity')
    for workflow in (live, reviewed):
        if not isinstance(workflow.get('nodes'), list) or not isinstance(workflow.get('connections'), dict) or not isinstance(workflow.get('settings'), dict):
            raise EvidenceError('malformed observed workflow graph')
        names, ids = set(), set()
        for node in workflow['nodes']:
            if not isinstance(node, dict):
                raise EvidenceError('malformed observed workflow node')
            name = _text(node.get('name'), 'node name')
            nid = _text(node.get('id'), 'node id')
            if name in names or nid in ids:
                raise EvidenceError('duplicate observed workflow node identity')
            names.add(name); ids.add(nid)
    if 'RELAY_HOST' in json.dumps(live['nodes']):
        raise EvidenceError('installed relay placeholder unresolved')
    from scripts import check_n8n_workflow_drift as D
    from scripts import n8n_workflow_templates as T
    if T.graph_hash(reviewed) != p['graph_sha256'] or D.diff_fields(D.normalise(live), D.normalise(reviewed)):
        raise EvidenceError('live workflow graph/settings drift')


def sign_payload(payload: dict, *, key_id: str, sign) -> dict:
    """Host adapter interface: callback owns private key; never accepts an executable/key path.

    Only the fixed collector calls this in a production integration, after collection.
    This function creates no authority; every result is reverified against public trust.
    """
    signature = sign(canonical(payload))
    return {'schema':SCHEMA,'payload':payload,'signature':{'algorithm':'Ed25519','key_id':key_id,
            'value':base64.b64encode(signature).decode('ascii')}}
