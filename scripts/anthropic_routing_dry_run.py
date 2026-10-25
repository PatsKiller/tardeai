#!/usr/bin/env python3
"""Counts-only routing/cost comparison; never imports a caller or contacts a provider."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.lib.anthropic_transport import price_usage  # noqa: E402

NO_CONSUMER_REASON = 'Operator-requested offline review CLI; invoked by Anthropic real-layout CI proof, never a scheduled dispatch.'


def report(root: Path, observations: dict) -> tuple[list[dict], Decimal]:
    registry=json.loads((root/'config/llm_process_registry.json').read_text())
    routing=json.loads((root/'config/llm_routing_policy.json').read_text())
    credit=json.loads((root/'config/anthropic_credit_policy.json').read_text())
    models=json.loads((root/'config/llm_model_registry.json').read_text())
    routes=routing['policies'][routing['default_policy_id']]['processes']
    rows=[];total=Decimal(0)
    for process in registry['processes']:
        pid=process['id'];row=routes[pid];old=row['primary'];logical=old['policy']
        tier='high' if process.get('reasoning_tier')=='high' else credit['policy_tiers'][logical]
        eligible=process.get('anthropic_first') is True and pid not in credit['excluded_processes']
        new=credit['models'][tier] if eligible else 'unchanged'
        observed=observations.get('by_registered_process',{}).get(pid)
        cost=None
        if observed and not observed.get('token_counts_missing') and eligible:
            # Comparable-token estimate only: not a forecast of Claude thinking/output.
            cost=price_usage({'input_tokens':observed['input_tokens'],'output_tokens':observed['output_tokens']},credit['pricing'][new])
            total+=cost
        if old['provider']=='deepseek':
            spec=models['logical_policies'][logical]
            old_model=models['providers']['deepseek']['models'][spec['model']]['model_id']
        else:
            old_model='proxy-selected (not pinned in routing row)'
        rows.append({'process':pid,'old':old['provider']+' / '+old_model,
                     'new':('anthropic / '+new) if eligible else 'EXCLUDED / unchanged',
                     'tier':tier,'admission':'DECLARED_USD_REQUEST_CAPS' if process.get('daily_cost_cap_usd') and process.get('daily_soft_cap') else 'DB_BUDGET_NOT_MEASURED','observed_calls':observed['events'] if observed else 'NOT_MEASURED',
                     'comparable_token_usd':str(cost) if cost is not None else 'NOT_MEASURED'})
    return rows,total


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=Path(os.environ.get('PROJECT_ROOT') or Path(__file__).resolve().parents[1]))
    ap.add_argument('--observations',type=Path,required=True)
    args=ap.parse_args()
    rows,total=report(args.project_root,json.loads(args.observations.read_text()))
    print('| Process | Old provider / model | New provider / model | Tier | Budget admission | Observed calls | Comparable-token USD |')
    print('|---|---|---|---|---|---:|---:|')
    for row in rows: print('| '+' | '.join(str(row[k]) for k in ('process','old','new','tier','admission','observed_calls','comparable_token_usd'))+' |')
    print(f'\nObserved-subset comparable-token estimate: ${total:.8f} against $10/day. Full-day cost: NOT_MEASURED.')
    print('Assumes usable key/credit, identical observed input/output volumes and no cache savings; no dispatch. Provider output/thinking and unobserved OAuth calls can change actual spend. UTC pacing differs from captured ET-day census.')


if __name__=='__main__':main()
