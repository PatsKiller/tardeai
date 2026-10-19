"""hermes-learning cutover PR-2 (2026-10-15, operator-approved 2026-10-16): the process step lanes it moves to canary.

One list for every pin that reads stage / live_arg / effect state, as tests/support/n8n_cutover_waves.py does for the
cutover waves. LEARN_LIVE: the learn steps that run live on the fabric (registry stage canary, allowlist live_arg
= the spec's cutover_live_arg, cron_claim true from PR-1): the four cut over 2026-10-16.
Historical feedback packet: docs/ops/packets/hermes-feedback-cutover-20261017/ and operator 2026-10-17
"fix now move to n8n now". The registered future `--apply --notify queue` adapter remains, but current
2026-10-18 source holds outcome_feedback_agent at shadow/live_arg null pending its own qualified output,
consumer and transactional cutover evidence. Its capability does not establish a sixth live stage.
TUNE_LIVE (2026-10-17 tune cutover, operator 2026-10-17
00:25 ET; packet docs/ops/packets/hermes-tune-cutover-20261017/): the tune stage's one step, autonomous_self_tune, at
canary with the cron step's own argv (both halves: auto-graft + archive-first self-purge; no --learn), live_arg
[--apply], cron_claim true. LIVE = four learn steps plus tune. HELD = feedback only.
"""

from __future__ import annotations

LEARN_LIVE = (
    "hermes-learning-outcome-grader",
    "hermes-learning-tag-engine",
    "hermes-learning-outcome-learning",
    "hermes-learning-config-governor",
)
#: No feedback activation is established by its registered future adapter.
FEEDBACK_LIVE: tuple[str, ...] = ()
TUNE_LIVE = ("hermes-learning-autonomous-self-tune",)
LIVE = LEARN_LIVE + TUNE_LIVE
HELD = ("hermes-learning-outcome-feedback-agent",)
