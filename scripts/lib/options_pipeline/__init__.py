"""options_pipeline — paper-only options strategy proposal generators.

Stage A (discovery candidate #339, APPROVED_RESEARCH_ONLY): deep-ITM call
stock-replacement modeled as a paper strategy. Proposals land ONLY in the
existing options-desk approval queue (options_approval_queue via
options_desk_enterprise.sync_approval_queue) in the manual-review lane with
educational/paper flags and live_eligible=False — the desk's own fail-closed
gates (resolve_approval + check_preflight_approval) then make live approval
and live submit structurally impossible.

HARD SAFETY (test-enforced by tests/test_options_pipeline_deep_itm.py):
no broker submit / order / approval / 2FA module is imported anywhere in
this package. Chain data comes exclusively from the AST-proven read-only
research adapter lib.strategy_research.options_chain.
"""
from .deep_itm_generator import (  # noqa: F401
    generate_deep_itm_proposals,
    load_pipeline_config,
    submit_to_desk_queue,
)
