# Monitoring integration handoffs — not completed

The claim gate refused these paths. No override or alternate writer was used.

- `scripts/lib/platform_health.py`, `scripts/lib/needs_action.py`: owner session `claude-watchdog-activate`, claim `20261025T183349Z-claude-0d776804`.
- `scripts/api_v2.py`: owner session `perf-pages-20261025`, claim `20261025T175818Z-claude-af5d8508`.
- `apps/command-center-v3/src/components/JobsHealth.tsx`: owner session `crosscut-gaps-20261025`, claim `20261025T203103Z-claude-5e06965a`.

Please hand off the additive integration normally, or integrate the following in the owning branches:

1. Reuse `lib.anthropic_monitoring.snapshot(root)`; never call a provider or read a credential value for health. The projection has provider status, last success/error, today/7-day usage, per-model costs, fallback reasons, credit/pace/expiry and `p1_continuous_failure`.
2. Platform health: add an Anthropic row from this projection. Configured without successful observations is DEGRADED; absent key is NOT_CONFIGURED; accounting failure is UNAVAILABLE. Do not turn either into healthy zeroes.
3. Needs-action: add a probe and rule backed by the same projection. P1 when `p1_continuous_failure` is true; P2 for unavailable credit evidence. Link to LLM Spend. Preserve the existing unavailable-source handling and timeout budget. Add pinned-time fixtures.
4. Jobs & health: show the existing `llm-provider-health` lane's Anthropic projection/last successful observation. A fresh heartbeat proves that the observer ran, not that Anthropic answered. Add synthetic phone fixture proof, without live CC traffic.

LLM Spend already reads the projection through the existing consumption overview route. Provider-health heartbeat, runtime-health observer and daily digest are wired in this branch. This handoff is not evidence that the other screens are wired.
