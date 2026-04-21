# Restart Here — 2026-04-21

**For:** Any developer or Claude session picking up this project.

---

## System Status: OPERATIONAL + UNCOMMITTED

Everything works. 18 Postgres tables active. Daily pipeline writes observations, escalations, recommendations, market intelligence. **But all code changes are uncommitted.**

## What is done

- **18 Postgres tables** with dual-write from JSON (operational layer complete)
- **Advisor memory:** observations (7/day), escalations (3/day), daily Ollama summary, recommendation drafts (2/day with Yahoo + article context)
- **Market intelligence:** 84-ticker daily snapshots, 36-stock Yahoo analyst targets, 40+ article/day index, analyst consensus history
- **Watchlist:** user + analyst-curated (manual add/remove only), CC modal, Postgres-backed with provenance. Automated analyst-curated ingestion from news/signals is deferred.
- **Steph bridge:** read-only advisor memory access (5 query types)
- **Backups:** automated backup mechanism implemented (daily pg_dump timer, 30-day retention). Manual ad-hoc dump path needs re-verified .env-safe DB dump command before treating backups as fully validated.
- **Bug fixes:** RVOL/gap scoring, Telegram emojis, clipboard copy
- **67 documentation files** in `docs/handoff_2026-04-19/`

## What to do first

1. **Commit.** Run the prepared git commands from the latest commit handoff.
2. **Verify pipeline runs tomorrow morning** (Mon-Fri 07:00 via portfolio-daily.timer)
3. **Check Postgres accumulation** after 2-3 days:
   ```sql
   SELECT tablename, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;
   ```

## What to read

| Priority | Document |
|----------|----------|
| 1 | `master_state_and_deliverables_2026-04-21.md` (this session's full ledger) |
| 2 | `schemas_reference_2026-04-19.md` (v2.0, database/file map) |
| 3 | `openclaw_portfolio_advisor_planning_brief_2026-04-20.md` (future architecture) |
| 4 | `openclaw_supervisory_schema_plan_2026-04-20.md` (notification/approval design) |

## What is most important next

1. **Notification planning** — design `notification_log` + Gmail daily digest
2. **Task 10 implementation** — extract hardcoded `HOLDING_YIELDS` to live data
3. **Escalation expiration cleanup** — add `WHERE expires_at < CURRENT_DATE` update

## What NOT to do next

- Do NOT start the forecast engine yet (needs 30+ days of accumulated data)
- Do NOT register the advisor as an OpenClaw conversational agent (it's a background service)
- Do NOT auto-approve recommendations (all drafts must stay status='draft' until approval layer exists)
- Do NOT push to remote without scrubbing git history (plaintext password in baseline commit)

## Key semantic rule

**Yahoo analyst targets (`yahoo_analyst_targets_history`) are authoritative.** Finviz `analyst_consensus_history` is a placeholder — do NOT let recommendation logic treat it as true consensus.

## Architecture principle

```
Agent OBSERVES → Agent ESCALATES → Agent DRAFTS → Steph VALIDATES → Human DECIDES
```

No level is skippable. The agent never acts. The agent only writes to memory and proposes.

---

*Restart doc created 2026-04-21.*
