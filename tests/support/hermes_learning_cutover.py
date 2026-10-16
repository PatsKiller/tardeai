"""hermes-learning cutover PR-2 (2026-10-15, operator-approved 2026-10-16): the process step lanes it moves to canary.

One list for every pin that reads stage / live_arg / effect state, as tests/support/n8n_cutover_waves.py does for the
cutover waves. LIVE: the four learn steps that run live on the fabric (registry stage canary, allowlist live_arg =
the spec's cutover_live_arg, cron_claim true from PR-1). HELD: outcome_feedback_agent stays shadow (live_arg null,
owner row cron, so the cron stage runner keeps running it live) because its `--notify queue` argv trips the allowlist
sender token gate; it moves in a follow-up once the operator-approved gate alignment is served. The tune lane
(autonomous_self_tune) is neither: it waits for the manifest split.
"""
from __future__ import annotations

LIVE = (
    "hermes-learning-outcome-grader",
    "hermes-learning-tag-engine",
    "hermes-learning-outcome-learning",
    "hermes-learning-config-governor",
)
HELD = ("hermes-learning-outcome-feedback-agent",)
