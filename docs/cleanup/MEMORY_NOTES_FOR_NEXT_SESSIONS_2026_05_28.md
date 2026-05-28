# Memory Notes for Next Sessions - 2026-05-28

Key context that must be carried into future sessions. This file captures decisions, blockers, and protection rules from the docs cleanup audit.

---

## Active Work -- Do Not Archive or Delete

### v4.0 Recurring Backtest / LLM Coverage
- Implemented outside the ChatGPT plan -- treat as ACTIVE, not orphaned
- Implementation report: `V4_0_RECURRING_BACKTEST_LLM_COVERAGE_IMPLEMENTATION_REPORT.md`
- Design directory: `backtest_llm_coverage_v4_0_design/`
- Built entirely by Claude Code sessions

### v4.1 Backtesting Filters
- Currently being fixed (pre-apply backup in `docs/atm_lifecycle_v1_2026_05_28/`)
- Must account for v4.0 data sources when fixing filters
- Pre-apply backup: `Backtesting.tsx` (58 KB)

### v3.8 LLM Backtesting -- Partially Implemented
- Stage 1 v1 reviews were PARTIAL -- quality was insufficient
- Stage 1 v2 prompt/parser improvement implemented (2026-05-28) but requires validation before trusting delayed reviews
- Prompt parser diagnosis document is actively referenced: `LLM_BACKTESTING_V3_8_STAGE1_PROMPT_PARSER_DIAGNOSIS.md`
- All v3.8 design and implementation files are DO_NOT_DELETE

### v3.9 Delayed Review -- BLOCKED
- Blocked until v3.8 produces meaningful Stage 1 `close_analysis` rows
- Design directory preserved: `llm_delayed_monthly_v3_9_design/`
- Do not attempt to implement v3.9 until v3.8 Stage 1 v2 is producing valid output

---

## Protection Rules

### Do Not Delete
- v3.8 / v3.9 LLM docs -- active/blocked work
- v4.0 backtest coverage docs -- just implemented
- BLMN/APPS repair evidence -- audit trail required
- Source exports (`source_exports/`) -- needed until final project closeout
- Screenshots (`screenshots/`) -- visual evidence until final project closeout
- All pre-apply backups in `backups/` directories

### Broker Configuration
- `broker_config.py` is now the canonical source for account configuration
- 8 brokers configured, 2 adapter scaffoldings (Schwab, Tastytrade)
- Any changes to broker config must update this central module

---

## System Architecture Notes

### Health Agent (3-tier Escalation)
1. **Python self-heal** -- Automatic recovery for known failure modes
2. **Claude Code escalation** -- For issues requiring code changes
3. **LLM nightly review** -- health_agent_llm_review.py summarizes daily findings

### Monitoring
- 26 monitored components with self-heal
- Alert dedup: staleness 4h, proposals 30min, after-hours suppression

### Ollama / Local LLM
- Intel Arc B580 / Vulkan still has instability issues
- qwen3:14b running at ~15s/chunk but Vulkan driver crashes occur
- This blocks higher-quality local LLM reviews

---

## Session Reference

- `docs/SESSION_2026_05_27.md` has the complete 38-commit session log for the most recent major session
- Morning briefs are generated daily: `docs/openclaw_aegis_morning_brief_2026-MM-DD.md`

---

## Cleanup Status

- This audit inventoried ~765 files across docs/
- ~62 files identified as safe to archive (superseded designs with implementation reports)
- ~400+ files protected (DO_NOT_DELETE or KEEP_*)
- No files were deleted or moved -- this was a READ-ONLY audit
- Cleanup manifests created in `docs/cleanup/` for future action

---

## Next Steps for Cleanup (When Ready)

1. Create `docs/_archived/` directory
2. Move the ~62 ARCHIVE_SUPERSEDED_DESIGN and ARCHIVE_OLD_PROMPT files
3. Keep all evidence, backups, and source exports in place
4. Re-validate after v3.8 Stage 1 v2 produces stable output
5. Consider archiving Reference Architecture .bak files after v4.1 is verified stable
6. Do NOT clean up source_exports or screenshots until project closeout decision
