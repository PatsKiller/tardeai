#!/usr/bin/env python3
"""Generate inactive native apply workflow; no import, activation or host scheduler."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import build_n8n_reference_workflow as reference
from scripts import n8n_workflow_templates as T

WID='tradeai-cio-company-facts-populate-native'
LANE='cio-company-facts-populate'
REL='docs/ops/packets/c1-company-population-20261024'
SCHEDULES=['0 35 6 * * 1-5','0 35 15 * * 1-5']


def build():
    wf=deepcopy(reference.build())
    wf['id']=wf['name']=WID
    wf['active']=False
    for node in wf['nodes']:
        node['id']=T._f_node_id(WID,node['name'])
        if node['type']=='n8n-nodes-base.scheduleTrigger':
            node['parameters']={'rule':{'interval':[{'field':'cronExpression','expression':s} for s in SCHEDULES]}}
        if node['type']=='n8n-nodes-base.code':
            text=node['parameters']['jsCode']
            text=text.replace(json.dumps(reference.LANE),json.dumps(LANE)).replace(json.dumps(reference.WID),json.dumps(WID))
            if node['name']==reference.N_CTX:
                text=text.replace('const MODE = "dry_run";','const MODE = "live";').replace('max_attempts: 2','max_attempts: 1')
            node['parameters']['jsCode']=text
    fw=wf['meta']['framework']
    fw.update(owner='cio',stage='canary',lanes=[LANE],effect_process=LANE,runbook_id=LANE,
              runbook_path=REL+'/RUNBOOK.md',health_contract_ref=REL+'/HEALTH_CONTRACT_DRAFT.json',
              connects_to=[f'workflow:{T.RUN_LANE_ID}',f'lane:{LANE} (apply, pending reviewed admission)',
                           f'workflow:{T.FABRIC_ERROR_ID} -> host intent route'],
              rollback='Keep workflow inactive before admission; after approval stop only this workflow, preserve canonical history. No legacy schedule exists.')
    wf['meta'].update(generator='scripts/build_cio_company_facts_workflow.py',kind='proposed-native-apply',
                      admission_status='NOT_ADMITTED; DRAFT owner contract and operator migration/activation pending',
                      stage_basis='INTENDED CANARY ONLY; not an observed runtime stage',
                      schedule_basis='06:35 pre-open and15:35 after nominal last15:25 Hermes catalyst fire; completion ordering unproven until operator acceptance')
    wf['meta']['graph_sha256']=T.graph_hash(wf)
    wf['meta']['policy_sha256']=T.policy_hash()
    return wf


if __name__=='__main__':print(json.dumps(build(),indent=2))
