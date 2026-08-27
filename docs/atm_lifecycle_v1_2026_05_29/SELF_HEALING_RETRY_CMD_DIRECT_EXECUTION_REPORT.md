# Self-Healing retry_cmd Direct Execution Report

**Date:** 2026-05-29
**P1 Gap:** Escalation handler retry_cmd direct execution

## Changes

### 1. Allowlist Config (`config/claude_escalation_allowlist.yaml`)
- 17 allowed script patterns (enrichment, health checks, pipeline requeue, cache, news)
- 19 blocked patterns (orders, broker, DB mutations, sudo, crontab, destructive)
- Environment guards: ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true
- Max runtime: 120 seconds

### 2. Escalation Handler (`scripts/claude_escalation_handler.py`)
Rewritten with 3-tier processing:

| Tier | Action | When |
|------|--------|------|
| **Tier 1** | Direct retry_cmd execution | fixable=true, retry_cmd present, passes allowlist |
| **Tier 2** | Local LLM diagnosis | Remaining fixable items after Tier 1 |
| **Tier 3** | Claude Code CLI | All remaining unresolved items |

### 3. Retry Execution Logging (`logs/claude_escalation_retry_cmd.jsonl`)
Every retry_cmd attempt logs: timestamp, component, command, hash, allowlist result, status, exit_code, stdout/stderr tail, duration, env guard state.

## Allowlist Test Results

| Test | Expected | Result |
|------|----------|--------|
| Enrichment retry | Allowed | **PASS** |
| Health check | Allowed | **PASS** |
| RAG reindex | Allowed | **PASS** |
| sudo command | Blocked | **PASS** |
| Trading mutation | Blocked | **PASS** |
| Destructive rm | Blocked | **PASS** |
| Unknown script | Blocked | **PASS** |

**7/7 tests passed.**

## Live Queue Dry-Run

| Metric | Value |
|--------|-------|
| Queue items | 3 (2 portfolio_risk informational, 1 pipeline_output) |
| Fixable with retry_cmd | 0 (pipeline_output has no retry_cmd) |
| Would execute | 0 |
| LLM diagnosis | Triggered for pipeline_output item |
| Claude Code | Would invoke for unresolved item |

## Status

| Check | Result |
|-------|--------|
| retry_cmd P1 resolved | **YES** |
| Allowlist added | YES |
| Blocked patterns added | YES |
| Direct execution added | YES |
| Dry-run mode | YES (existing --dry-run flag) |
| Destructive commands blocked | YES |
| Trading state protected | YES (env guards + blocked patterns) |
| Logging complete | YES (JSONL + interventions table + Telegram) |
| Remaining P0 gaps | None |
| Remaining P1 gaps | UI dashboard for retry_cmd history |

## Rollback

```bash
git revert <commit_hash>  # Restores old handler without direct execution
```
The allowlist config is additive — removing it makes all commands require manual review (safe default).
