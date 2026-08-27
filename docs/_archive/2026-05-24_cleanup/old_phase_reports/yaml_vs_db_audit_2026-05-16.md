# Strategy Config Source-of-Truth Audit — 2026-05-16

## Findings

### YAML inventory
- Total YAML files: **26** (23 strategies + 3 schemas/shared)
- Last modified: 2026-05-15 (all strategy YAMLs updated by B-1b freshness block addition)
- Oldest modified: 2026-05-05 (shared_risk_rules.yaml)

### Human editing of YAML
- Authors touching config/strategies/ in last 60 days: **John only** (7 commits)
- YAML-only commits (no co-modified code): **0** — every YAML change was part of a code session
- Verdict: **CODE-ONLY** — YAML is edited by Claude Code sessions, not manually by operator

### Sync mechanism
- Sync function exists: **Yes** — `strategy_config_loader.py:168` writes to strategy_registry
- `strategy_registry` config columns present: **Yes** — config_hash, yaml_version, last_yaml_sync_at all exist
- `last_yaml_sync_at` freshness: **STALE (2026-05-07)** — 9 days ago. The YAMLs were updated May 15 but the sync never re-ran.
- Sync cron entry: **No dedicated cron** — only `populate_performance_context.py` (nightly) which writes performance blocks, not config hashes

### Runtime reads
- `get_eligible_signals` reads: **Neither** — reads from `strategy_signals` table (pre-computed)
- `_load_strategy_configs()` (strategy_signal_sync.py): **YAML** — opens and parses all 23 YAMLs on every signal sync call
- `_load_strategy_config()` (auto_proposal_generator.py): **YAML** — opens individual YAML per strategy
- `_validate_against_strategy_criteria()`: **YAML** via `_load_strategy_config()`
- Other YAML readers at runtime: **3 files** (multi_strategy_classifier, proposal_lifecycle, strategy_signal_sync)
- Other DB readers (strategy_registry): **12 call sites** across risk_gate, agent_router, proposal_quality, etc.

### YAML vs DB agreement
- Strategies with matching hash: **0**
- Strategies with mismatch: **20** (all strategies — YAML updated May 15, DB hash from May 7)
- Strategies missing in DB: **3** (earnings_post_momentum, earnings_pre_buildup, fib_retracement_bounce)

### Operator workflow
- Docs telling operator to edit YAML: **Yes** (archived docs reference this workflow)
- UI/Telegram commands writing YAML: **Yes** — `api_v2.py:1778` yaml.dump, `populate_performance_context.py:205` yaml.dump, `bulk_patch_strategy_yamls.py:609` yaml.dump
- UI/Telegram commands writing strategy_registry: **Yes** — `strategy_config_loader.py:168`, `strategy_weekly_review.py:161`
- ScreenerConfigModal writes to: **DB only** (`finviz_screeners` table, not YAML)

## Architecture Reality

**YAML is the primary source of truth for strategy parameters** (screen_filters, stop distances, hold times, indicators). The DB (`strategy_registry`) stores a subset of metadata (active status, display_name, rules) and a config_hash for change detection — but it's 9 days stale.

**Runtime reads are SPLIT:**
- Signal generation + proposal creation: read YAML (3 files)
- Risk assessment + agent routing + governance: read strategy_registry DB (12 sites)

**The sync is broken.** YAMLs were updated May 15 (freshness blocks added). DB config_hash is from May 7. Three strategies exist in YAML but not in DB at all.

## Recommendation

**Option: YAML as source + fix the sync** (correct approach for this system)

Evidence:
1. YAML files are actively maintained (updated every session)
2. Runtime signal generation reads YAML directly (3 critical paths)
3. No human edits YAML manually (Claude Code sessions are the editor)
4. The sync mechanism EXISTS but its cron is missing
5. The DB-only approach (ScreenerConfigModal) is only used for screeners, not strategies

**Action for Phase B-1b:**
- Add freshness config to YAML (already done in B-1b)
- Fix the YAML→DB sync cron (run `strategy_config_loader.py` nightly)
- Add the 3 missing strategies to strategy_registry
- The watchpool evaluator should read freshness config from YAML (via the existing `_load_strategy_config()` pattern)

**Do NOT move to DB-only** — it would require rewriting 3 runtime-critical files that currently open YAML directly, with no operational benefit since the operator never edits YAML manually anyway.
