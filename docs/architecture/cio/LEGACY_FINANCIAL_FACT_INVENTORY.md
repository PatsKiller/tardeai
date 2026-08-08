# Legacy Financial Fact Inventory

**Date:** 2026-08-08
**Phase:** P2.1 Operator Profile + Financial Context
**Status:** AUDIT COMPLETE

---

## Summary

A comprehensive audit of the codebase, OpenClaw workspaces, and Trade AI data directories was performed to discover any existing financial facts, profiles, investment policy statements, or operator-specific financial data. The audit found no authoritative operator-specific financial facts stored anywhere in the system.

---

## Audit Results by Location

### 1. Trade AI Data Directory (`data/`)

| Path | Content | Financial Facts? |
|------|---------|-----------------|
| `data/advisory/operator_choices/2026-06-01_choices.jsonl` | Operator choices from advisory dual-opinion pipeline | Generic advisory choices, no personal financial data |
| `data/advisory/dual_opinion/` | Dual opinion outputs | Pipeline data, not operator-specific |
| `data/advisory/backtest_dual_opinions/` | Backtest opinions | Pipeline data |
| `data/advisory/high_llm_reviews/` | LLM review results | Pipeline data |
| `data/advisory/journal_dual_opinions/` | Journal opinions | Pipeline data |
| `data/advisory/evidence_remediation/` | Evidence remediation | Pipeline data |
| `data/advisory/outcomes/` | Dual opinion outcomes | Pipeline data |
| `data/runtime/schwab_browser_profile` | Browser profile for Schwab | Technical browser profile, not financial profile |

**Conclusion:** No operator-specific financial profile, IPS, goals, or constraints exist in Trade AI data directories.

### 2. OpenClaw Workspaces

| Workspace | Files | Financial Facts? |
|-----------|-------|-----------------|
| `workspace-alex/` | MEMORY.md, USER.md, IDENTITY.md, SOUL.md, TOOLS.md, HEARTBEAT.md, BOOTSTRAP.md, AGENTS.md | MEMORY.md explicitly states non-authoritative communication style only. Explicitly warns: "Authoritative financial state must be reconstructed from Trade AI for every material CIO run." USER.md contains only communication preferences. |
| `workspace-maria/` | IDENTITY.md, SOUL.md, TOOLS.md, USER.md, HEARTBEAT.md, AGENTS.md, contacts, docs | No financial facts. PA/concierge identity only. |
| `workspace-steph/` | IDENTITY.md, SOUL.md, TOOLS.md, USER.md, HEARTBEAT.md, AGENTS.md | No financial facts. Wealth advisor identity only. |
| `workspace-guardian/` | IDENTITY.md, SOUL.md, TOOLS.md | Skeleton only. No financial facts. |
| `workspace-ledger/` | IDENTITY.md, SOUL.md, TOOLS.md | Skeleton only. No financial facts. |

**Conclusion:** No operator-specific financial facts exist in any OpenClaw workspace. Alex MEMORY.md is properly structured as non-authoritative.

### 3. OpenClaw Skills

| Path | Content | Financial Facts? |
|------|---------|-----------------|
| `skills/wealth/steph-wealth-advisor/` | Skill definition, data-priority refs | Skill configuration, no operator data |
| `skills/wealth/daily-portfolio-brief/` | Portfolio brief skill | Skill configuration, no operator data |

**Conclusion:** Skills contain configuration only, no operator-specific financial data.

### 4. OpenClaw Backup Files

| Path | Content | Financial Facts? |
|------|---------|-----------------|
| Various `.bak` files in `agents/main/agent/` | Model configs, auth profiles, SQLite DB backups | Technical configuration backups only |

**Conclusion:** No operator financial data in backup files.

### 5. Repository Codebase

| Path | Content | Financial Facts? |
|------|---------|-----------------|
| `scripts/strategy_regime_profiler.py` | Strategy regime profiling | Market analysis tool, not operator profile |
| `scripts/build_symbol_profiles.py` | Symbol profiles | Market data profiles, not operator profile |
| `scripts/rotation_round_trips.py` | Rotation tracking | Market analysis |
| `scripts/lib/data_broker/symbol_profile.py` | Symbol profile data model | Market data model |

**Conclusion:** Profile-related code is all market/symbol profiling, not operator profile.

---

## Inventory

Since no operator-specific financial facts exist in the system, there are no legacy facts to migrate. All operator profile data must be collected fresh from the operator.

| Field | Legacy Source | Current Trade AI Value | Conflict | Operator Confirmation Required | Migration Status |
|-------|--------------|----------------------|----------|-------------------------------|-----------------|
| (All fields) | NONE | N/A — no data exists | N/A | YES — all fields must be operator-provided | NOT_STARTED |

---

## Required Operator Facts (to be collected)

The following categories of financial facts are required for Alex to provide material financial advice. None currently exist in the system.

1. **Operator Profile:** Name, tax filing status, employment status, income sources
2. **Investment Policy Statement:** Investment objectives, risk tolerance, constraints
3. **Goals:** Short/medium/long-term goals with target dates and amounts
4. **Account Constraints:** Taxable, IRA, Roth, HSA, 401k rules and contribution limits
5. **Cash Liquidity Needs:** Emergency fund target, near-term expense requirements
6. **Risk Constraints:** Maximum concentration, maximum drawdown, VaR limits
7. **Tax Constraints:** Filing status, marginal rate, IRMAA thresholds, state residency
8. **Retirement Constraints:** Target retirement age, income needs, RMD status, Social Security timing
9. **Income Needs:** Annual income requirements, income sources
10. **Time Horizon:** Investment phases with ages and risk glide path
11. **Communication Preferences:** Preferred channels, frequency, format

---

## Next Steps

The operator must provide fact values through the `cio_operator_profile.py` service. All facts start as UNVERIFIED. The operator must explicitly confirm each fact to move it to OPERATOR_CONFIRMED status. Only OPERATOR_CONFIRMED facts can support material financial advice.
