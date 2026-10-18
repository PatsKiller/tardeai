"""hermes-learning cutover PR-2 (2026-10-15, operator-approved 2026-10-16): the process step lanes it moves to canary.

One list for every pin that reads stage / live_arg / effect state, as tests/support/n8n_cutover_waves.py does for the
cutover waves. LEARN_LIVE: the learn steps that run live on the fabric (registry stage canary, allowlist live_arg
= the spec's cutover_live_arg, cron_claim true from PR-1): the four cut over 2026-10-16, plus outcome_feedback_agent
(2026-10-17 feedback cutover, operator 2026-10-17 "fix now move to n8n now"; packet
docs/ops/packets/hermes-feedback-cutover-20261017/), whose live argv `--apply --notify queue` queues each alert as a
host comms intent and calls no sender; the allowlist sender-token gates admit exactly that argv for exactly that lane
(scripts/lib/lane_dispatch.py QUEUE_ONLY_NOTIFY_ARGV). TUNE_LIVE (2026-10-17 tune cutover, operator 2026-10-17
00:25 ET; packet docs/ops/packets/hermes-tune-cutover-20261017/): the tune stage's one step, autonomous_self_tune, at
canary with the cron step's own argv (both halves: auto-graft + archive-first self-purge; no --learn), live_arg
[--apply], cron_claim true. LIVE = both. HELD: empty since the feedback cutover (kept so the pins that iterate it stay
meaningful if a step is ever held again).
"""
from __future__ import annotations

LEARN_LIVE = (
    "hermes-learning-outcome-grader",
    "hermes-learning-tag-engine",
    "hermes-learning-outcome-learning",
    "hermes-learning-config-governor",
    "hermes-learning-outcome-feedback-agent",
)
#: the 2026-10-17 feedback cutover's one lane (subset of LEARN_LIVE)
FEEDBACK_LIVE = ("hermes-learning-outcome-feedback-agent",)
TUNE_LIVE = ("hermes-learning-autonomous-self-tune",)
LIVE = LEARN_LIVE + TUNE_LIVE
HELD: tuple[str, ...] = ()
