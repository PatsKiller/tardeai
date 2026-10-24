#!/usr/bin/env python3
"""Operator-only source promotion. Default plan writes nothing; never imports/schedules/runs cleanup.

All source configuration and the reviewed draft are digest-bound. A pending or
peer-invented review cannot write. Coordinator must regenerate pins after union
integration before the operator reviews the exact final source proposal.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

PACKET = Path(__file__).resolve().parent
ROOT = PACKET.parents[3]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def promotion(config_dir, packet, review):
    raw_pins = (packet / 'activation-input-sha256.json').read_bytes()
    pins = json.loads(raw_pins)
    if review.get('source_config_pins_sha256') != sha(raw_pins):
        raise ValueError('review_source_pins_mismatch')
    if review.get('rules_sha256') != pins.get('disk_hygiene_rules.json'):
        raise ValueError('review_rules_sha_mismatch')
    docs = {}
    for name, expected in pins.items():
        raw = (config_dir / name).read_bytes()
        if sha(raw) != expected:
            raise ValueError('source_config_changed:' + name)
        docs[name] = json.loads(raw)
    raw = (packet / 'standing-contract.draft.json').read_bytes()
    if sha(raw) != review.get('draft_contract_sha256'):
        raise ValueError('review_contract_hash_mismatch')
    if review.get('decision') != 'APPROVE_DISK_STANDING_APPLY' or not review.get('approved_by'):
        raise ValueError('operator_review_pending')
    ts = datetime.fromisoformat(review.get('approved_at') or '')
    if not ts.tzinfo:
        raise ValueError('operator_review_timestamp')
    rules = docs['disk_hygiene_rules.json']['standing_apply']
    if rules.get('enabled') is not False:
        raise ValueError('standing_not_disabled')
    rules['approval'] = {'status': 'APPROVED', 'approved_by': review['approved_by'], 'approved_at': review['approved_at'],
                         'source': 'Exact draft/source config review supplied by operator'}
    rules['approved_by'] = review['approved_by']
    rules['enabled'] = True
    lane = next(x for x in docs['lane_registry.json']['lanes'] if x.get('lane_id') == 'disk-hygiene')
    lane['scheduler']['cadence'] = '0 4 * * 1,3,5,0'
    lane['dispatch'].update(cron=['0 4 * * 1,3,5,0'], tz='America/New_York', retry_policy='none')
    lane['expected_cadence_hours'] = 48
    lane['state_reason'] = 'Operator-reviewed native A/S/W standing cleanup; max40GiB and <=2h exact manifest/rules binding; manual grant retained.'
    lane['note'] = 'Native standing result reports and pending/applied path journal; current source/evidence revalidated before each item. No direct sender.'
    entry = next(x for x in docs['n8n_run_allowlist.json']['lanes'] if x.get('lane_id') == 'disk-hygiene')
    entry.update(live_arg=['--standing','--apply'],dry_run_arg=['--standing','--dry-run'])
    entry['source'] = 'Operator-reviewed native standing A/S/W scope; disabled until exact source review. One native attempt; no automatic destructive partial retry.'
    entry['env_evidence'] = 'Existing request identity and persistent root; manual grant remains manual only. Fresh local cron/units/proc/fds/coordination/pointers plus sanctioned gh api GET PR capture; no new credential values or direct sender.'
    contract = json.loads(raw)
    contract.update(status='REVIEWED',reviewed_by=review['approved_by'],reviewed_at=review['approved_at'],state_note='Operator reviewed exact standing source/contract; previous plan review retained as history.')
    contract['previous_plan_review'] = copy.deepcopy(next(x for x in docs['n8n_health_contracts.json']['contracts'] if x.get('id') == 'disk-hygiene'))
    docs['n8n_health_contracts.json']['contracts'] = [contract if x.get('id') == 'disk-hygiene' else x for x in docs['n8n_health_contracts.json']['contracts']]
    for name in ('lane_registry.json','n8n_run_allowlist.json','n8n_health_contracts.json'):
        docs[name].get('pending_changes', {}).pop('disk-hygiene-standing-apply-20261024', None)
    encoded = {name: (json.dumps(doc,indent=2,ensure_ascii=False)+'\n').encode() for name, doc in docs.items()}
    digest = sha(json.dumps({name:sha(raw) for name,raw in encoded.items()},sort_keys=True).encode())
    return encoded, digest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir',type=Path,default=ROOT/'config')
    parser.add_argument('--review-file',type=Path,default=PACKET/'review.required.json')
    parser.add_argument('--write',action='store_true')
    parser.add_argument('--plan-sha256')
    args=parser.parse_args(argv)
    written=[]
    try:
        review=json.loads(args.review_file.read_text())
        encoded,digest=promotion(args.config_dir,PACKET,review)
        if args.write and args.plan_sha256 != digest:
            raise ValueError('exact_plan_digest_required')
        if args.write:
            # Source-only operator action. Not a filesystem transaction across files:
            # perform in a stopped/isolated review worktree, then gates and one release.
            for name in sorted(encoded,key=lambda n:(n=="disk_hygiene_rules.json",n)):
                (args.config_dir/name).write_bytes(encoded[name])
                written.append(name)
        print(json.dumps({'mode':'write' if args.write else 'plan','plan_sha256':digest,'files':sorted(encoded),
                          'live_actions':False,'requires':'all native admission gates and operator/coordinator publication'}))
        return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'refused':str(exc) if isinstance(exc,ValueError) else type(exc).__name__,'writes':bool(written),'written_files':written}))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
