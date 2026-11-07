# Catalyst momentum engine — cron side of the B8 consolidation (2026-10-22)

Operator-run packet. The 2026-10-11 consolidation (`scripts/run_family_slot.py --family catalyst-momentum-engine`)
declared the lane ACTIVE and the two legacy lines RETIRED in `config/lane_registry.json`, but its crontab install
never happened, so the legacy lines still run and the family line is absent
(`check_registry_runtime_truth`: ACTIVE_CRON_LINE_ABSENT + 2x DECLARED_OFF_CRON_LINE_ACTIVE).

Since then the legacy lines gained `env ALPACA_MODE=paper`. The family's proposal modes now carry it too
(`scripts/lib/family_slot_jobs.py` `CATALYST_PAPER_ENV`); the script refuses unless the served release has it.

2026-11-07 (LQ-20261107-49): the proposal modes also carry `SEARCH_ROUTING_ENGINE=1`. The cron-run engine has had
no catalyst search since 2026-10-29: without the flag `search_catalyst` takes the legacy SearXNG call
(`time_range=day`, google news / bing news / duckduckgo), those engines answer CAPTCHA or parsing error, every
candidate comes back empty, and `hermes_research_intelligence` has no `momentum_catalyst` row after 10-29 08:00 ET
(so `hermes_news_bridge` bridges 0). The n8n-run scalp researcher has the flag and finds catalysts through the same
function. Installing this packet is therefore also the starvation fix; the script refuses unless the served release
has the flag. The overnight line (0 18,22) is not touched by this packet and stays on the legacy search.

    bash apply-operator.sh --preview   # changes nothing
    bash apply-operator.sh             # backup, diff, type APPLY, install, verify against a captured file

Rollback: `crontab <backup path printed by the script>`. Approval: operator 2026-10-22, "yes i approve 'approve all'
(A–L)" (item D, lane-registry truth) — the crontab change itself is the operator's act at the TTY.
