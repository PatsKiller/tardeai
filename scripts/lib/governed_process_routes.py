"""Existing server-approved governed process routes, shared without importing the bridge runtime.

No model selection, credentials or process registrations live here. Moving the existing
maps preserves server routing; host callers can prove the exact process before transport.
"""
from __future__ import annotations

CALLER_PROCESS_MAP = {'alex': 'alex_cio_synthesis', 'maria': 'maria_research_critique', 'steph': 'steph_allocation_review', 'guardian': 'guardian_risk_critique', 'ledger': 'ledger_tax_critique', 'morgan': 'morgan_wealth_synthesis', 'advisory_desk': 'advisory_desk_opinion', 'n8n_model_job': 'n8n_material_digest_draft'}

CALLER_TASK_PROCESS_MAP = {'n8n_model_job': {'model_job': 'n8n_material_digest_draft', 'ops_summary': 'n8n_ops_summary_draft', 'lane_failure_diagnosis': 'n8n_lane_failure_diagnosis'}, 'advisory_desk': {'advisory_opinion': 'advisory_desk_opinion', 'advisory_synthesis': 'advisory_desk_synthesis', 'operator_reply': 'cio_operator_reply', 'plan_enrichment': 'cio_plan_enrichment', 'prompt_judge': 'cio_prompt_judge', 'research_circle': 'research_circle_analyzer', 'hermes_cloud_json': 'hermes_cloud_json', 'usefulness_score': 'hermes_usefulness_score', 'hermes_research_job': 'cio_hermes_research', 'golden_judge': 'hermes_golden_judge', 'hermes_tag_engine': 'hermes_tag_engine'}}

def route_for_process(process_id: str) -> tuple[str, str] | None:
    """An existing caller/task pair, or None. Never invent a route from a client ID."""
    for caller, tasks in CALLER_TASK_PROCESS_MAP.items():
        for task, declared in tasks.items():
            if declared == process_id:
                return caller, task
    for caller, declared in CALLER_PROCESS_MAP.items():
        if declared == process_id:
            return caller, "model_job"
    return None
