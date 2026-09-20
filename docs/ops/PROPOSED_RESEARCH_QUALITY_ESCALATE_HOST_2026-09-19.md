# PROPOSED / APPLIED — research quality escalate host arm

```
Status: APPLIED (host arm) + CODE WIRE 2026-09-20
as_of: 2026-09-20T08:20:00Z
Authority: config-write maturity overnight grant; MBI_BEHAVIOR=0
```

## What

Arm `RESEARCH_QUALITY_ESCALATE` without editing crontab:

1. Code reads `~/.config/tradeai/research_quality_escalate` when the env var is unset.
2. Host file contents: `1` (truthy: `1|true|yes|on`).
3. Explicit env `0` / hermetic `env={}` still disables.

## Operator one-liner (host arm)

```bash
printf '1\n# maturity quality escalate host arm\n' > ~/.config/tradeai/research_quality_escalate
chmod 0644 ~/.config/tradeai/research_quality_escalate
```

## Cron wire (corrected 2026-09-20)

**[DOC-CLAIM was false]** The earlier draft said `data_gap_resolver.py` cron already called
`gap_resolver.resolve`. Measured: it only dispatched Maria jobs / enrichment — never
`resolve()`, so quality_escalate could not fire on schedule.

**[CODE]** `scripts/data_gap_resolver.py` now walks `gap_resolver.resolve` for open
`missing_catalyst` / `stale_news` / `explicit` gaps (domain `catalyst_news`), stamping
`requester=data_gap_resolver`. Existing weekday/evening/Sunday cron lines pick this up
after merge+promote — no crontab edit.

## Rollback

```bash
mv ~/.config/tradeai/research_quality_escalate ~/.config/tradeai/research_quality_escalate.off
```

## Proof required

Unattended receipt with `vector=quality_escalate` and `requester=data_gap_resolver`
(or desk ask with `requester=desk`) after promote — not `controlled_canary_*`.
