# Proposal: you.com search as a registered provider (§7A), not built

Status: PROPOSED — operator decision (AGENTS.md §17, §7A). No client, key, lane or code calls you.com.

**Why.** Operator 2026-10-31, verbatim: "It should also click off separate Hermes searches and Brave and you.com searches
related to all of this." The rotation advisor's research fan-out (`scripts/lib/market_risk/cio_memory_fanout.py`) plans
you.com jobs for every leadership transition, selloff-type change and re-entry flip. They are reported as
`unavailable: no registered provider`, because none exists. A grep on 2026-10-31 found no `you.com`, `youcom` or
`you_com` provider, client, registry row or lane in `scripts/` or `config/`.

**What a row would need** (`config/data_source_authority.json`, same shape as the `brave` provider row):

| Field | Proposal |
|---|---|
| provider id | `youcom` |
| purpose | `web_search` research for market-risk triggers only (caller `market_risk_rotation`) |
| single caller path | through a governed router with the same ledger discipline as `brave_router` (`scripts/lib/search_budget.py`) |
| budget | operator sets daily and monthly limits; the fan-out caps jobs per day under policy `leadership.fanout.youcom` |
| credential | operator creates the key in the secret store (Bitwarden); agents never read it (§24.7) |
| results | appended to the governed research feed like Brave, with corroboration required before CIO memory admits them |
| stale_after / no_coverage | 24 h / `say_so` |

**Decision needed.** Whether to fund and register you.com. Until then the fan-out keeps reporting the jobs as
unavailable, and Brave plus Hermes carry the research.
