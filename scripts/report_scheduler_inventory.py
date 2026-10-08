#!/usr/bin/env python3
"""Normalize saved, redacted host observations into SchedulerLaneInventory@v1.

Consumer: runtime convergence evidence/report. Reads snapshots, registry and source
contracts. Writes only the explicitly supplied evidence directory. Never runs lanes.
Unknown execution, ownership, notification and writer facts remain null.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NO_CONSUMER_REASON = (
    'Manually invoked saved-snapshot audit CLI; its JSON artifacts are reviewed by the operator '
    'in docs/_evidence/runtime-convergence. Not a deployed or scheduled producer. '
    'The REST projection imports scheduler_operations directly, not this CLI.'
)
sys.path.insert(0, str(ROOT))
from scripts.lib import cron_last_fire
from scripts.lib.scheduler_operations import build_projection, cron_collides, parse_crontab, read_lock_metrics

FIELDS = ('lane_id business_domain owner declared_state actual_scheduler scheduler_expression runtime_kind '
          'command actual_executable actual_code_root expected_code_root interpreter working_directory lock '
          'lock_kind timeout market_day_gate receipt output_signal output_signal_age last_requested last_started '
          'last_finished last_exit last_duration next_due consumer writer_tables_files cost_bearing '
          'notification_bearing broker_bearing live_mutation_bearing current_pinned declared_in_lane_registry '
          'declared_in_expected_services alternate_schedulers health_verdict evidence_source').split()


def cron_analysis(text: str, *, start: datetime) -> dict:
    entries = parse_crontab(text, default_timezone='America/New_York')
    heat, collisions, histogram = Counter(), Counter(), Counter()
    jobs = []
    for e in entries:
        spec = cron_last_fire.parse(e['expression'])
        fires = weekday = weekend = 0
        intervals = []
        if spec:
            slots = sorted(h*60+m for h in spec['hours'] for m in spec['minutes'])
            intervals = [b-a for a,b in zip(slots, slots[1:])]
            for offset in range(7):
                day = start.date()+timedelta(days=offset)
                if cron_last_fire._day_matches(spec, day):
                    for h in spec['hours']:
                        for m in spec['minutes']:
                            fires += 1
                            weekday += day.weekday() < 5
                            weekend += day.weekday() >= 5
                            heat[str(h)] += 1
                            collisions[f'{day.isoformat()} {h:02}:{m:02}'] += 1
        interval = min(intervals) if intervals else None
        histogram[str(interval) if interval is not None else 'daily_or_less_or_unparsed'] += 1
        c = e['command']
        root = ('CURRENT' if '$PROJ' in c or '/CURRENT' in c else 'DEV_TREE' if '/trade-ai-v12-rebuild/' in c else 'OTHER_OR_UNKNOWN')
        # Shared venv alone is not dev-tree code execution.
        scripts = re.findall(r'(?:[\w./~-]+/)?[\w.-]+\.(?:py|sh|mjs|js)\b', c)
        jobs.append({**e, 'estimated_fires_7d': fires, 'estimated_weekday_fires_5d': weekday,
                     'estimated_weekend_fires_2d': weekend, 'minimum_scheduled_interval_minutes': interval,
                     'lock_kind': 'safe_flock' if 'safe_flock' in c else 'flock' if re.search(r'\bflock\b',c) else None,
                     'scheduled_root': root, 'scripts': scripts})
    raw = text.splitlines()
    counts = {'raw_lines': len(raw), 'job_lines': len(entries),
              'comment_lines': sum(s.strip().startswith('#') for s in raw),
              'env_lines': sum(bool(re.match(r'^\s*\w+\s*=',s)) for s in raw),
              'blank_lines': sum(not s.strip() for s in raw),
              'distinct_commands': len({e['command'] for e in entries}),
              'distinct_scripts': len({s for e in jobs for s in e['scripts']}),
              'locked': sum(e['lock_kind'] is not None for e in jobs),
              'unlocked': sum(e['lock_kind'] is None for e in jobs),
              'safe_flock': sum(e['lock_kind']=='safe_flock' for e in jobs),
              'bare_flock': sum(e['lock_kind']=='flock' for e in jobs),
              'execution_roots': dict(Counter(e['scheduled_root'] for e in jobs))}
    return {'schema': 'CronReMeasurement@v1', 'evidence_class': 'OBSERVED_HOST', 'counts': counts,
            'estimate_class': 'SOURCE_ONLY', 'estimate_window_start': start.date().isoformat(),
            'estimate_note': 'Next seven local calendar days; schedule fires before market gates, locks and failures. @reboot is unestimated. This window has no DST transition.',
            'estimated_weekday_fires_5d': sum(e['estimated_weekday_fires_5d'] for e in jobs),
            'estimated_weekend_fires_2d': sum(e['estimated_weekend_fires_2d'] for e in jobs),
            'estimated_fires_7d': sum(e['estimated_fires_7d'] for e in jobs),
            'cadence_histogram_minutes': dict(histogram), 'hour_heatmap_fires_7d': dict(sorted(heat.items(), key=lambda x:int(x[0]))),
            'top_minute_collisions': collisions.most_common(30),
            'top_30_highest_fire_jobs': sorted(jobs,key=lambda e:e['estimated_fires_7d'],reverse=True)[:30], 'jobs': jobs}


def normalize(projection: dict, registry: dict, allowlist: dict, expected: dict) -> list[dict]:
    declarations = {r['lane_id']:r for r in registry['lanes']}
    allows = {r['lane_id']:r for r in allowlist['lanes']}
    expected_names = {r['unit'] for r in expected['units']}
    rows = []
    for r in projection['rows']:
        lane = declarations.get(r['lane_id'], {})
        allow = allows.get(r['lane_id'], {})
        sched = lane.get('scheduler') or {}
        observations = r['scheduler_observations']
        commands = [e.get('command') or e.get('properties', {}).get('ExecStart') for e in observations]
        commands = [c for c in commands if c]
        command = commands[0] if commands else None
        props = next((e['properties'] for e in reversed(observations) if e.get('properties')), {})
        row = dict.fromkeys(FIELDS)
        row.update(lane_id=r['lane_id'], business_domain=r['domain'], owner=r['owner'],
          declared_state=r['declared_state'], actual_scheduler=r['scheduler_type'],
          scheduler_expression=r['schedule'], runtime_kind='daemon_or_timer' if r['scheduler_type']=='systemd' else r['scheduler_type'],
          command=command, actual_code_root=r['code_root'] if r['code_root_evidence']=='OBSERVED_DB' or props.get('process_cwd') else None,
          actual_executable=props.get('process_executable'), working_directory=props.get('WorkingDirectory'),
          expected_code_root='/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT',
          lock=allow.get('lock'), lock_kind=allow.get('lock_kind'), timeout=allow.get('timeout_s'),
          market_day_gate=allow.get('market_gate'), receipt=r['receipt'], output_signal=r['output_signal'],
          output_signal_age=r['output_age'], last_requested=r['last_requested'], last_started=r['last_started'],
          last_finished=r['last_completed'], last_exit=r['last_exit'], last_duration=r['duration'], next_due=r['next_due'],
          consumer=r['consumer'], declared_in_lane_registry=r['declared_in_registry'],
          declared_in_expected_services=any(e.get('id') in expected_names for e in observations),
          alternate_schedulers=[e.get('id') for e in observations] if r['duplicate_scheduler'] else [],
          health_verdict=r['runtime_state'], evidence_source=r['evidence_sources'] or r['evidence_class'])
        if command:
            match = re.search(r'(/[^\s;\x27\"]+\.lock)\b',command)
            row['lock'] = row['lock'] or (match[1] if match else None)
            row['lock_kind'] = row['lock_kind'] or ('safe_flock' if 'safe_flock' in command else 'flock' if re.search(r'\bflock\b',command) else None)
            row['market_day_gate'] = row['market_day_gate'] if row['market_day_gate'] is not None else 'market_day_gate' in command
            row['current_pinned'] = bool('/CURRENT' in command or '$PROJ' in command or '/CURRENT' in (row['working_directory'] or ''))
        row['authority'] = 'READ_ONLY_ADVISORY'
        row['unknown_fields'] = [k for k in FIELDS if row[k] is None]
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--evidence', type=Path, required=True)
    args = ap.parse_args()
    out = args.evidence
    def read(name):
        return json.loads((out/name).read_text())
    host = read('00-host.json')
    units = read('04-systemd-units.json')
    n8n = read('06-n8n-db.json')
    oc = read('05-openclaw.json')
    runs = read('08-host-run-ledger.json')
    registry = json.loads((ROOT/'config/lane_registry.json').read_text())
    allow = json.loads((ROOT/'config/n8n_run_allowlist.json').read_text())
    expected = json.loads((ROOT/'config/expected_services.json').read_text())
    at = datetime.fromisoformat(host['as_of'].replace('Z','+00:00'))
    analysis = cron_analysis(host['cron']['stdout'], start=at+timedelta(days=1))
    observations = {'cron': {'measured':host['cron']['exit']==0,'entries':analysis['jobs'],'as_of':host['as_of']},
      'systemd': {'measured':True,'units':{k:v['properties'] for k,v in units['units'].items()},'as_of':units['as_of']},
      'n8n': {'measured':n8n['results']['workflow_counts']['exit']==0,'workflows':n8n['results']['workflow_metadata']['data'],'as_of':n8n['as_of']},
      'openclaw': {'measured':True,'jobs':oc['jobs'],'as_of':oc['as_of']}}
    supplemental = out/'01-live-scheduler-observations.json'
    if supplemental.is_file():
        latest = json.loads(supplemental.read_text())
        observations = latest['observations']
        at = datetime.fromisoformat(latest['as_of'].replace('Z','+00:00'))
        analysis = cron_analysis(host['cron']['stdout'], start=at+timedelta(days=1))
    observations['lock_telemetry'] = read_lock_metrics(Path('/home/johnclaw/trade-ai-releases/persistent-state/logs/safe_flock_events.jsonl'), at)
    projection = build_projection(registry,observations,root=Path('/home/johnclaw/trade-ai-releases/persistent-state'),
                                  now=at,runs=runs['runs'],runs_measured=True)
    inventory = normalize(projection,registry,allow,expected)
    duplicate_groups = []
    for key in ('command','lock'):
        groups = defaultdict(list)
        for job in analysis['jobs']:
            value = job['command'] if key=='command' else (re.search(r'(/[^\s;\x27\"]+\.lock)\b',job['command']))
            value = value[1] if key=='lock' and value else value
            if value:
                groups[str(value)].append(job['id'])
        jobs_by_id = {j['id']: j for j in analysis['jobs']}
        for value, ids in groups.items():
            if len(ids) < 2:
                continue
            collision = any(cron_collides(jobs_by_id[a], jobs_by_id[b], at)
                            for i,a in enumerate(ids) for b in ids[i+1:])
            duplicate_groups.append({'kind':key,'value':value,'entries':ids,
              'schedules':[jobs_by_id[i]['expression'] for i in ids], 'scheduled_collision':collision,
              'verdict':'REVIEW_COLLISION' if collision else 'NON_COLLIDING_WINDOWS_REVIEW_CONTRACT',
              'priority':'P1' if collision and key=='command' else 'P2' if collision else 'P3'})
    outputs = defaultdict(list)
    for lane in registry['lanes']:
        if lane['state']=='ACTIVE':
            sig = lane.get('output_signal') or {}
            if sig.get('path') or sig.get('table'):
                outputs[sig.get('path') or sig['table']].append(lane['lane_id'])
    conflicts = {'schema':'SchedulerConflicts@v1','as_of':at.isoformat(), 'duplicates':duplicate_groups,
      'shared_output_candidates':[{'output':v,'lanes':ids,'verdict':'NOT_MEASURED writer synchronization'} for v,ids in outputs.items() if len(ids)>1],
      'registry_drift':[{'lane_id':r['lane_id'],'status':r['runtime_state'],'reason':r['health_reason']} for r in projection['rows'] if r['scheduler_drift']],
      'unowned':[r['lane_id'] for r in inventory if not r['declared_in_lane_registry']],
      'benign_overlaps':['A shared interpreter venv is not dev-tree code execution.','A shadow schedule is coordination overlap; side-effect safety requires receipts, not a lock alone.'],
      'dangerous_overlaps':'Exact duplicates and active shared-writer/lock candidates require contract review; lock skips are not completed work.'}
    for name,data in [('01-scheduler-lane-inventory.json',{'schema':'SchedulerLaneInventory@v1','as_of':at.isoformat(),'rows':inventory}),
                      ('02-duplicates-conflicts.json',conflicts),('03-cron-remeasurement.json',analysis),
                      ('14-scheduler-operations-snapshot.json',projection)]:
        (out/name).write_text(json.dumps(data,indent=2,default=str)+'\n')
    print(json.dumps({'inventory_rows':len(inventory),'cron':analysis['counts'],'fires_7d':analysis['estimated_fires_7d'],
                      'duplicate_groups':len(duplicate_groups),'unregistered':len(conflicts['unowned'])}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
