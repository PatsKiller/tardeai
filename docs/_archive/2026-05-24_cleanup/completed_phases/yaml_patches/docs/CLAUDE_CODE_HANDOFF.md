# Claude Code Handoff — Session 33 Strategy YAML Patch Package

**Paste this entire file as your opening prompt to Claude Code on MS-01.**

---

## Context

You're Claude Code running in tmux on MS-01 (`johnclaw@192.168.50.16`). The project is **Trade AI v12** at:

```
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
```

Venv: `.venv`. Server runs on `0.0.0.0:7777`. Holdings are `~$1,192,934 across 47 positions`. **This number is sacred** — verify before and after every step.

I've prepared a complete patch package that resolves the 63-issue YAML audit from Session 32. The package is sitting in `~/session33_patches/` after John SCP'd it. Your job is to execute the deployment, verify success, and report back.

## What the package does (in plain English)

The 20 strategy YAMLs are all missing three blocks: `vix_rules`, `technical_indicators_required`, `performance_context`. Six of them use the old v1.0 schema (`setup_qualification` instead of `entry_criteria`). The `earnings_catalyst` strategy is doing two jobs that should be split. The screener-to-strategy mapping has gaps that explain why only 2 of 20 strategies generate proposals.

This package:

1. Adds the three missing blocks to all YAMLs (with per-strategy values, not stubs)
2. Converts 6 v1.0 files to v1.0.0 schema
3. Adds 3 new strategies: `fib_retracement_bounce`, `earnings_pre_buildup`, `earnings_post_momentum`
4. Marks `earnings_catalyst.yaml` as DEPRECATED (does NOT delete it)
5. Adds 8 new screeners with strategy-routing wired in
6. Wires a nightly cron to refresh `performance_context` from `paper_performance_governance`
7. Provides a replacement validator script that walks nested keys correctly

## IRON RULE

**Before touching anything**, run:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
python -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; c=len(d['holdings']); print(f'Holdings: \${v:,.0f} / {c} positions'); assert v>1_000_000, 'ABORT'; assert c>=30, 'ABORT'"
```

If this fails, **STOP IMMEDIATELY** and tell me. Do not run any other script.

## Execution sequence

```bash
# 0. Pre-flight checks
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .venv/bin/activate
python -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; c=len(d['holdings']); print(f'Holdings: \${v:,.0f} / {c} positions'); assert v>1_000_000; assert c>=30"
pip list | grep -iE '^(ruamel|psycopg2|pyyaml)'
# If any are missing:
pip install ruamel.yaml psycopg2-binary pyyaml --break-system-packages

# 1. Copy scripts into project
cp ~/session33_patches/scripts/*.py scripts/
ls scripts/bulk_patch_strategy_yamls.py scripts/convert_v1_to_v1_0_0_schema.py \
   scripts/validate_strategy_yamls.py scripts/patch_screeners_yaml.py \
   scripts/populate_performance_context.py scripts/deploy_yaml_patches.py

# 2. Take a manual safety snapshot (in ADDITION to script backups)
mkdir -p backups
tar czf backups/session33_pre_deploy_$(date +%Y%m%d_%H%M%S).tar.gz \
    config/strategies/ assets/screeners.yaml

# 3. DRY-RUN
python scripts/deploy_yaml_patches.py --dry-run \
    --new-yamls-dir ~/session33_patches/config_additions

# Read the dry-run output. It should show:
#   - Pre-flight: OK ($1.19M+ / 47)
#   - Baseline validation: ~25-30 real issues across 20 files
#   - Schema conversion: 6 files would be patched
#   - 3 new YAMLs would be copied
#   - Bulk patches: ~60 blocks would be added
#   - Final validation: significantly fewer issues
#   - Post-flight: OK

# 4. APPLY
python scripts/deploy_yaml_patches.py --apply \
    --new-yamls-dir ~/session33_patches/config_additions

# 5. Verify the YAML side
ls config/strategies/*.yaml | wc -l            # expect 22 (or 23 with shared_risk_rules)
ls config/strategies/fib_retracement_bounce.yaml \
   config/strategies/earnings_pre_buildup.yaml \
   config/strategies/earnings_post_momentum.yaml
grep -A 3 'status:' config/strategies/earnings_catalyst.yaml | head -5
# Should show: status: DEPRECATED

# Spot-check the new blocks landed
grep -l 'vix_rules:' config/strategies/*.yaml | wc -l           # expect 22
grep -l 'technical_indicators_required:' config/strategies/*.yaml | wc -l  # expect 22
grep -l 'performance_context:' config/strategies/*.yaml | wc -l # expect 22

# 6. Patch screeners (separate file, separate step)
python scripts/patch_screeners_yaml.py --dry-run
python scripts/patch_screeners_yaml.py --apply

# 7. Run perf-context populator manually once (soft-fails if DB is down)
python scripts/populate_performance_context.py --dry-run
python scripts/populate_performance_context.py --apply

# 8. Wire the nightly cron for perf-context refresh
crontab -l > /tmp/crontab_session33_before.txt
cp /tmp/crontab_session33_before.txt /tmp/crontab_session33_after.txt
# Only add if not already present:
grep -q populate_performance_context /tmp/crontab_session33_after.txt || cat >> /tmp/crontab_session33_after.txt <<'CRON'

# Session 33: nightly refresh of strategy YAML performance_context blocks
30 2 * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/populate_performance_context.py --apply >> logs/perf_context.log 2>&1
CRON
crontab /tmp/crontab_session33_after.txt
crontab -l | grep populate_performance_context

# 9. Final iron-rule check
python -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; c=len(d['holdings']); print(f'Holdings: \${v:,.0f} / {c} positions')"
```

## Report back to John with

When you're done, paste back **exactly** this report. Fill in actual numbers, don't paraphrase:

```
=== SESSION 33 DEPLOYMENT REPORT ===

Iron Rule (pre):  Holdings $______ / __ positions
Iron Rule (post): Holdings $______ / __ positions
(must be identical)

Strategy YAML count: __ (expect 22, or 23 with shared_risk_rules.yaml)

Validation:
  Baseline issues: __
  Final issues:    __
  Reduction:       __%

Required blocks (each should be 22):
  vix_rules:                       __
  technical_indicators_required:   __
  performance_context:             __

New strategies present (each should exist):
  fib_retracement_bounce.yaml:     [ ] yes / [ ] no
  earnings_pre_buildup.yaml:       [ ] yes / [ ] no
  earnings_post_momentum.yaml:     [ ] yes / [ ] no
  earnings_catalyst marked DEPRECATED: [ ] yes / [ ] no

Screener count: __ (was 19 — expect 27)

Perf-context cron wired:  [ ] yes / [ ] no

Sample vix_rules block from momentum_scalp.yaml:
<paste output of: grep -A 12 'vix_rules:' config/strategies/momentum_scalp.yaml>

Errors / warnings encountered:
<paste any, or write "none">

Backups created:
  backups/session33_pre_deploy_*.tar.gz
  backups/strategy_yaml_*/
  backups/schema_convert_*/
  backups/screeners_*/
  backups/yaml_validation_baseline_*.md
  backups/yaml_validation_final_*.md

=== END REPORT ===
```

## Failure modes — when to STOP and ask

1. **Pre-flight check fails** (holdings != ~$1.19M or count < 30) — STOP. Restore from latest known-good before doing anything.
2. **Post-flight check fails** (holdings degraded mid-run) — STOP. Run the rollback procedure in `docs/README.md`.
3. **Bulk patcher reports errors > 0** — STOP. Read the error. Most likely a YAML parse problem in a specific file — fix that one file manually and re-run.
4. **Validator final count > baseline count** — STOP. Something broke. Don't proceed to screener patching until investigated.
5. **A YAML stops parsing** (`python -c 'import yaml; yaml.safe_load(open("config/strategies/<file>.yaml"))'` raises) — STOP. Restore that one file from the script's backup dir.

## DON'T do

- Don't `git rm earnings_catalyst.yaml`. It's marked DEPRECATED on purpose so anything still referencing it doesn't crash.
- Don't manually edit YAMLs to "clean up" the patcher's indentation. ruamel preserves source formatting but appends new blocks at the end — that's intentional and the LLM doesn't care about key order.
- Don't skip the dry-run.
- Don't skip the post-flight check.
- Don't run `populate_performance_context.py` before `bulk_patch_strategy_yamls.py` — it depends on the blocks already being there.
- Don't add anything to git yet. Let John review the diffs first.

## Reference files

Inside `~/session33_patches/`:

- `docs/README.md` — full runbook (you've already seen the short version above)
- `docs/CLAUDE_CODE_HANDOFF.md` — this file
- `scripts/*.py` — six scripts, all idempotent, all with `--dry-run` mode
- `config_additions/*.yaml` — three new strategy YAMLs to copy in

That's the whole job. Run it, report back, stop.
