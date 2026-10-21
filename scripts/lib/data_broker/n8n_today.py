"""Bounded read-only daily receipt projection, N8nToday@v2.

Counts describe the specified semantic-slot ET date and available receipt namespaces,
never all business activity. v1 inferred cutovers and zero-filled missing sources;
v2 uses null/coverage and keeps first live observations separate from cutover receipts.
No provider, SQL, scheduler or notification effect is reachable from this reader.
"""
from __future__ import annotations

import collections
import json
import os
import stat
import threading
import time
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Optional
from zoneinfo import ZoneInfo
from scripts.lib import recovery_validator as RV

ET=ZoneInfo('America/New_York')
SCHEMA='N8nToday@v2'
LEGACY_SCHEMA='N8nToday@v1'
CACHE_TTL_S=60.0
MAX_RELAY_BYTES=32*1024*1024
MAX_RECEIPT_BYTES=256*1024
MAX_RUN_BYTES=32*1024*1024
MAX_RUN_FILES=5000
MAX_LIST=200
RUNS_REL=Path('data/runtime/n8n_runs')
RELAY_REL=Path('data/runtime/n8n_relay/relay_log.jsonl')
DIAG_REL=Path('data/runtime/n8n_diagnoses/diagnoses.jsonl')
CUTOVER_REL=Path('data/runtime/n8n_cutover')
HEAL_DECISIONS={'heal','retry','remediate','rerun','auto_heal','self_heal'}
_CACHE:dict[str,Any]={}
_LOCK=threading.Lock()


def default_state_root():
    return Path(os.environ.get('TRADEAI_STATE_ROOT') or (Path.home()/'trade-ai-releases/persistent-state'))


def _parse(value):
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except (ValueError,TypeError):return None
    return dt if dt.tzinfo else None


def _mtime(path):
    try:return path.stat().st_mtime
    except OSError:return None


def _day_bounds(now):
    local=now.astimezone(ET)
    midnight=datetime(local.year,local.month,local.day,tzinfo=ET)
    return local.date().isoformat(),midnight.astimezone(timezone.utc)


def _tail_source(path,since,until,*,max_bytes=MAX_RELAY_BYTES):
    meta={'status':'UNAVAILABLE','complete':False,'truncated':False,'last_record_at':None,'invalid_rows':0,
          'window':{'since':since.isoformat(),'through':until.isoformat()},'bytes_read':0}
    try:
        with path.open('rb') as fh:
            size=os.fstat(fh.fileno()).st_size
            start=max(0,size-max_bytes);fh.seek(start)
            raw=fh.read(max_bytes)
        meta.update(bytes_read=len(raw),truncated=start>0)
        if start:raw=raw.partition(b'\n')[2]  # never parse a partial first record
        rows=[];last=None
        for line in raw.splitlines():
            if not line.strip():continue
            try:row=json.loads(line)
            except (ValueError,UnicodeError):meta['invalid_rows']+=1;continue
            at=_parse(row.get('at')) if isinstance(row,dict) else None
            if at is None or at>until:meta['invalid_rows']+=1;continue
            last=max(last,at) if last else at
            if at>=since:rows.append(row)
        meta.update(last_record_at=last.isoformat() if last else None,complete=not start and not meta['invalid_rows'])
        meta['status']='AVAILABLE' if meta['complete'] else 'PARTIAL'
        return rows,meta
    except OSError:return [],meta


def tail_rows_since(path,since,*,max_bytes=MAX_RELAY_BYTES,block=1<<20):
    """Legacy helper pair remains readable; build v2 carries unavailable/partial metadata."""
    rows,meta=_tail_source(path,since,datetime.max.replace(tzinfo=timezone.utc),max_bytes=max_bytes)
    return rows,meta['truncated']


def _json(path, budget=None):
    bound=MAX_RECEIPT_BYTES if budget is None else min(MAX_RECEIPT_BYTES,max(0,MAX_RUN_BYTES-budget[0]))
    fd=os.open(path,os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):raise ValueError('receipt is not a regular file')
        raw=fh.read(bound+1)
    if budget is not None:budget[0]+=len(raw)
    if len(raw)>bound:raise ValueError('receipt exceeds read bound')
    doc=json.loads(raw)
    if not isinstance(doc,dict):raise ValueError('receipt is not an object')
    return doc,len(raw)


def build(state_root:Optional[Path]=None,now:Optional[datetime]=None)->dict[str,Any]:
    root=Path(state_root or default_state_root());now=now or datetime.now(timezone.utc)
    day,since=_day_bounds(now);frag=day.replace('-','')+'T'
    by_mode={mode:collections.Counter() for mode in ('live','dry_run','unknown')}
    failures=[];skips=collections.Counter();lanes=set();live_lanes=set();first_live={};namespaces=collections.Counter()
    lane_states=collections.defaultdict(collections.Counter)  # per live lane: state -> n (needs-action, 2026-10-21)
    matching=[];invalid=0;read_bytes=0
    source={'status':'UNAVAILABLE','complete':False,'candidate_files':None,'read_files':0,'invalid_files':0,
            'max_files':MAX_RUN_FILES,'max_bytes':MAX_RUN_BYTES,'time_basis':'semantic slot date in America/New_York'}
    try:
        names=os.listdir(root/RUNS_REL)
        for name in names:
            if not name.endswith('.json'):continue
            rid=name[:-5];match=RV.SEMANTIC_KEY_RE.fullmatch(rid)
            namespaces[rid.split(':',1)[0] if ':' in rid else 'undated/other']+=1
            if match:
                ns,lane,requested,slot=match.groups()
                if requested=='live' and (lane not in first_live or slot<first_live[lane]):first_live[lane]=slot
                if slot.startswith(frag):matching.append((name,lane,requested,slot,ns))
        source.update(candidate_files=len(matching),status='AVAILABLE',complete=True)
    except OSError:matching=[]
    budget=[0]
    for name,lane,requested,slot,ns in sorted(matching,reverse=True)[:MAX_RUN_FILES]:
        if budget[0]>=MAX_RUN_BYTES:break
        try:
            doc,size=_json(root/RUNS_REL/name,budget)
            if doc.get('lane_id') not in (None,lane) or doc.get('run_id') not in (None,name[:-5]):raise ValueError('identity mismatch')
            finished=_parse(doc.get('finished_at'))
            if finished and finished>now:raise ValueError('future receipt')
        except (OSError,ValueError,UnicodeError):invalid+=1;continue
        source['read_files']+=1
        try:mode=RV.effective_mode({'mode':requested,'receipt':doc}) or 'unknown'
        except (TypeError,ValueError):mode='unknown'
        state=str(doc.get('state') or 'UNKNOWN');by_mode[mode][state]+=1;lanes.add(lane)
        if mode=='live':live_lanes.add(lane);lane_states[lane][state]+=1
        if state=='RUN_SKIPPED_LOCK':skips[(lane,mode)]+=1
        elif state in ('RUN_FAILED','RUN_REFUSED','RUN_TIMEOUT') or state.endswith('FAILED'):
            failures.append({'lane':lane,'mode':mode,'requested_mode':requested,'slot':slot,'state':state,'reason':doc.get('reason'),
                'exit_code':doc.get('exit_code'),'finished_at':doc.get('finished_at'),'run_id':doc.get('run_id') or name[:-5],
                'attempt':doc.get('attempt'),'served_sha':doc.get('code_sha'),'owner':doc.get('owner'),'workflow_id':doc.get('workflow_id'),
                'execution_id':doc.get('execution_id'),'evidence':str(RUNS_REL/name)})
    if source['status']!='UNAVAILABLE':
        source.update(invalid_files=invalid,bytes_read=budget[0],
            complete=not invalid and source['read_files']==len(matching))
        source['unknown_effective_mode_receipts']=sum(by_mode['unknown'].values())
        source['complete']=source['complete'] and source['unknown_effective_mode_receipts']==0
        source['status']='AVAILABLE' if source['complete'] else 'PARTIAL'
    full_runs=source['complete']
    relay_rows,relay_meta=_tail_source(root/RELAY_REL,since,now)
    diag_rows,diag_meta=_tail_source(root/DIAG_REL,since,now)
    relay=collections.Counter();workflow_errors=[]
    for r in relay_rows:
        relay[f"{r.get('op') or 'run'}:{r.get('state')}"]+=1
        if r.get('op')=='event' and r.get('lane_id')=='n8n-workflow-error':
            workflow_errors.append({k:r.get(k) for k in ('at','workflow_id','node','execution_id','duplicate')})
    diag_by=collections.Counter();heals=[];diagnoses=[]
    for d in diag_rows:
        decision=d.get('decision') if isinstance(d.get('decision'),dict) else {};kind=str(decision.get('kind') or '')
        diag_by[f"{d.get('event_type')}:{kind or 'none'}"]+=1
        row={k:d.get(k) for k in ('at','lane','event_type','cause','outcome','remediation_run_id','incident_key','run_id')}
        row.update(decision=kind or None,priority=decision.get('priority'),run=(d.get('incident_refs') or {}).get('run') if isinstance(d.get('incident_refs'),dict) else None)
        (heals if kind.lower() in HEAL_DECISIONS or d.get('remediation_run_id') else diagnoses).append(row)
    cutovers=[];cut_meta={'status':'UNAVAILABLE','complete':False,'candidate_files':None,'invalid_files':0}
    try:
        cut_names=[n for n in os.listdir(root/CUTOVER_REL) if n.endswith('-cutover.json')]
        cut_meta.update(candidate_files=len(cut_names),complete=len(cut_names)<=MAX_RUN_FILES)
        cut_budget=[0];cut_read=0
        for name in sorted(cut_names,reverse=True)[:MAX_RUN_FILES]:
            if cut_budget[0]>=MAX_RUN_BYTES:break
            try:doc,_=_json(root/CUTOVER_REL/name,cut_budget);cut_read+=1
            except (OSError,ValueError,UnicodeError):cut_meta['invalid_files']+=1;continue
            at=_parse(doc.get('at'))
            if at and since<=at<=now and doc.get('applied') and doc.get('action')=='cutover':
                cutovers.append({'lane':doc.get('lane_id'),'at':doc.get('at'),'source':'cutover_receipt',
                    'scheduler_before':(doc.get('scheduler_before') or {}).get('kind'),'evidence':str(CUTOVER_REL/name)})
        cut_meta['complete']=cut_meta['complete'] and not cut_meta['invalid_files'] and cut_read==len(cut_names)
        cut_meta.update(bytes_read=cut_budget[0],max_bytes=MAX_RUN_BYTES)
        cut_meta['status']='AVAILABLE' if cut_meta['complete'] else 'PARTIAL'
    except OSError:pass
    sources={'runs':source,'relay':relay_meta,'diagnoses':diag_meta,'cutovers':cut_meta}
    status='OK' if all(s['complete'] for s in sources.values()) else 'UNAVAILABLE' if all(s['status']=='UNAVAILABLE' for s in sources.values()) else 'PARTIAL'
    totals={m:sum(c.values()) if full_runs else None for m,c in by_mode.items()}
    failures.sort(key=lambda r:str(r.get('slot')),reverse=True)
    return {'schema':SCHEMA,'status':status,'day':day,'as_of':now.isoformat(),'authority':'READ_ONLY_ADVISORY',
        'runs':{'by_mode_state':{m:dict(c) for m,c in by_mode.items()} if full_runs else None,'observed_by_mode_state':{m:dict(c) for m,c in by_mode.items()},
                'totals':totals,'observed_totals':{m:sum(c.values()) for m,c in by_mode.items()},
                'lanes_active':len(lanes) if full_runs else None,'lanes_live':len(live_lanes) if full_runs else None},
        'failures':failures[:MAX_LIST],'failures_total':len(failures) if full_runs else None,
        'failures_returned':min(len(failures),MAX_LIST),'failures_truncated':len(failures)>MAX_LIST,
        'live_lane_states':{lane:dict(c) for lane,c in sorted(lane_states.items())},
        'lock_skips':[{'lane':lane,'mode':mode,'count':n} for (lane,mode),n in sorted(skips.items(),key=lambda kv:(-kv[1],kv[0]))],
        'relay':{'counts':dict(relay) if relay_meta['complete'] else None,'observed_counts':dict(relay),'truncated':relay_meta['truncated'],'workflow_errors':workflow_errors[-MAX_LIST:]},
        'diagnoses':{'counts':dict(diag_by) if diag_meta['complete'] else None,'by_lane':dict(collections.Counter(str(r.get('lane')) for r in diagnoses).most_common(30)),
                     'recent':diagnoses[-50:][::-1],'total':len(diagnoses) if diag_meta['complete'] else None,'observed_total':len(diagnoses),'truncated':diag_meta['truncated']},
        'heals':heals[-MAX_LIST:][::-1],'heals_total':len(heals) if diag_meta['complete'] else None,
        'cutovers_today':cutovers,'cutovers_total':len(cutovers) if cut_meta['complete'] else None,
        'first_live_observed_today':[{'lane':lane,'slot':slot,'source':'first_retained_live_slot_name'} for lane,slot in sorted(first_live.items()) if slot.startswith(frag)],
        'coverage':{'window':{'since':since.isoformat(),'through':now.isoformat(),'timezone':'America/New_York'},'sources':sources,
                    'run_namespaces':{'included':['d','e','g','p'],'observed_file_counts':dict(namespaces),
                                      'excluded':'undated n8n-wf-* and other names; relay requests are a separate admission count'},
                    'qualification':'Receipt/state observations only; no claim of all effects, delivery, acknowledgement, business recovery or continuous uptime'},
        'sources':[str(RUNS_REL),str(RELAY_REL),str(DIAG_REL),str(CUTOVER_REL)],
        'note':'Runs use semantic slot date in ET, including d/e/g/p namespaces and retry keys. Requested and effective modes are separate. Recovery actions are requests, not proven heals; first live observation is not cutover proof.'}


def get_n8n_today(state_root:Optional[Path]=None,now:Optional[datetime]=None,*,ttl_s=CACHE_TTL_S):
    root=Path(state_root or default_state_root());clock=now or datetime.now(timezone.utc)
    key=(str(root),clock.astimezone(ET).date().isoformat(),*(_mtime(root/p) for p in (RUNS_REL,RELAY_REL,DIAG_REL,CUTOVER_REL)))
    with _LOCK:
        previous=_CACHE.get(str(root))
        if previous and previous['key']==key and time.monotonic()-previous['at']<ttl_s:
            doc={**previous['doc'],'cache':'HIT'}
            last=_parse(doc.get('last_good_at'))
            doc['last_good_age_s']=max(0,int((clock-last).total_seconds())) if last else None
            return doc
    doc=build(root,clock)
    last=doc['as_of'] if doc['status']=='OK' else (previous or {}).get('last_good_at')
    age=(clock-_parse(last)).total_seconds() if _parse(last) else None
    doc.update(last_good_at=last,last_good_age_s=max(0,int(age)) if age is not None else None)
    with _LOCK:_CACHE[str(root)]={'key':key,'at':time.monotonic(),'doc':doc,'last_good_at':last}
    return {**doc,'cache':'MISS'}


__all__=['build','get_n8n_today','tail_rows_since','SCHEMA']
