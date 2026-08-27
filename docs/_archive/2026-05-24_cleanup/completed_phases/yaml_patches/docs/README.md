# Trade AI v12 — Session 33 Strategy YAML Patch Package

**Purpose:** Resolve the 63 YAML issues identified in the Session 32 audit by:
1. Fixing the broken audit script (real issue count was inflated by nested-key blindness)
2. Converting 6 v1.0 TESTING files to v1.0.0 schema
3. Splitting `earnings_catalyst` into `earnings_pre_buildup` + `earnings_post_momentum`
4. Adding `fib_retracement_bounce` as a new strategy
5. Adding three missing blocks to all 20 (now 22) strategies: `vix_rules`, `technical_indicators_required`, `performance_context`
6. Patching `assets/screeners.yaml` so the 18 quiet strategies start generating proposals
7. Wiring `performance_context` to be populated nightly from paper trade governance

**Target:** MS-01 (`johnclaw@192.168.50.16`), project root `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`

**Date:** 2026-05-13
**Author:** Patch package generated from Claude analysis of `strategy_yaml_audit.md` (Session 32)
**Iron Rule:** Holdings state check at start AND end. Abort if holdings != ~$1.19M / 47 positions.

---

## Files in this package

```
scripts/
├── bulk_patch_strategy_yamls.py         # adds vix/technical/performance blocks to all 22 YAMLs
├── convert_v1_to_v1_0_0_schema.py       # converts 6 TESTING files to v1.0.0
├── validate_strategy_yamls.py           # replacement for broken audit script
├── patch_screeners_yaml.py              # adds 8 new screeners, lowers thresholds on income screens
├── populate_performance_context.py      # nightly cron — populates perf stats from DB
└── deploy_yaml_patches.py               # orchestrator (runs steps 1-5 in order)

config_additions/
├── fib_retracement_bounce.yaml          # new strategy (gets copied into config/strategies/)
├── earnings_pre_buildup.yaml            # new strategy (split from earnings_catalyst)
└── earnings_post_momentum.yaml          # new strategy (split from earnings_catalyst)

docs/
└── README.md                            # this file
```

---

## Pre-deployment checklist

Run BEFORE doing anything else:

```bash
ssh johnclaw@192.168.50.16
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .venv/bin/activate

# 1. Iron Rule: verify holdings state
python -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; c=len(d['holdings']); print(f'Holdings: \${v:,.0f} across {c} positions'); assert v>1_000_000, 'ABORT: holdings degraded'; assert c>=30, 'ABORT: count low'"

# 2. Verify .venv has ruamel.yaml + psycopg2
pip list | grep -E '^(ruamel.yaml|psycopg2|PyYAML)'
# If missing:
pip install ruamel.yaml psycopg2-binary pyyaml --break-system-packages

# 3. Verify tmux is available (so SSH disconnect doesn't kill the run)
which tmux

# 4. Confirm 22 strategy YAMLs exist (20 current + 0 if no convert; will be 22 after deploy)
ls config/strategies/*.yaml | wc -l

# 5. Snapshot current state of config/strategies (in addition to script's own backups)
tar czf backups/session33_pre_deploy_$(date +%Y%m%d_%H%M%S).tar.gz config/strategies/ assets/screeners.yaml
```

If any of the above fails, **STOP** and investigate before proceeding.

---

## Deployment sequence

### Step 0: Upload the patch package to MS-01

From wherever this package lives:

```bash
# From local machine (LENOVO_AURA or wherever)
scp -r yaml_patches/ johnclaw@192.168.50.16:~/session33_patches/
```

Or, on MS-01 directly, if files were copied via another method:

```bash
ls ~/session33_patches/scripts/
ls ~/session33_patches/config_additions/
```

### Step 1: Copy scripts into project's scripts/ directory

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
cp ~/session33_patches/scripts/*.py scripts/
chmod +x scripts/bulk_patch_strategy_yamls.py scripts/convert_v1_to_v1_0_0_schema.py \
         scripts/validate_strategy_yamls.py scripts/patch_screeners_yaml.py \
         scripts/populate_performance_context.py scripts/deploy_yaml_patches.py
```

### Step 2: Start tmux session

```bash
tmux new -s session33
```

(Inside tmux from here forward. If disconnected, reattach with `tmux a -t session33`.)

### Step 3: Run the deploy script in DRY-RUN mode first

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .venv/bin/activate

python scripts/deploy_yaml_patches.py --dry-run \
    --new-yamls-dir ~/session33_patches/config_additions
```

**Read the dry-run output carefully.** It should report:

- Pre-flight: OK ($1.19M+ holdings)
- Baseline validation: ~25-30 real issues across 20 files
- Schema conversion: 6 files patched (gap_and_go, momentum_scalp, swing_breakout, income_add, sector_rotation, earnings_catalyst-deprecated)
- New YAMLs: 3 would be copied
- Bulk patches: ~60 blocks added across 22 files (vix_rules × 22, technical_indicators × 22, performance_context × 22, minus any already present)
- Final validation: ~5-10 remaining issues (mostly informational)
- Post-flight: OK (holdings unchanged)

If the dry-run shows anything unexpected (errors, holdings degradation, parse failures), **STOP** and investigate.

### Step 4: Apply patches

```bash
python scripts/deploy_yaml_patches.py --apply \
    --new-yamls-dir ~/session33_patches/config_additions
```

This will:
- Create timestamped backup at `backups/strategy_yaml_<ts>/`, `backups/schema_convert_<ts>/`
- Write changes to all 22 YAML files
- Generate `backups/yaml_validation_baseline_<ts>.md` and `backups/yaml_validation_final_<ts>.md`

### Step 5: Verify

```bash
# Compare baseline vs final issue counts
diff backups/yaml_validation_baseline_*.md backups/yaml_validation_final_*.md | head -50

# Verify holdings still intact
python -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; c=len(d['holdings']); print(f'Holdings: \${v:,.0f} across {c} positions')"

# Confirm 22 strategy files now exist
ls config/strategies/*.yaml | wc -l   # expect 22 (or 23 if shared_risk_rules.yaml is included)

# Spot-check a converted file
grep -A 5 'vix_rules:' config/strategies/momentum_scalp.yaml | head -20
grep -A 5 'technical_indicators_required:' config/strategies/swing_breakout.yaml | head -20
grep -A 5 'performance_context:' config/strategies/income_add.yaml | head -10

# Confirm new strategies exist
ls config/strategies/fib_retracement_bounce.yaml \
   config/strategies/earnings_pre_buildup.yaml \
   config/strategies/earnings_post_momentum.yaml

# Confirm deprecated marker on old earnings_catalyst
grep -A 2 'status:' config/strategies/earnings_catalyst.yaml
# Should show: status: DEPRECATED
```

### Step 6: Patch screeners.yaml

Separate step because it touches a different file and has different rollback risk:

```bash
# Dry-run first
python scripts/patch_screeners_yaml.py --dry-run

# Read output carefully — verify it's adding the 8 new screeners and adjusting thresholds
# Then apply:
python scripts/patch_screeners_yaml.py --apply
```

### Step 7: Wire performance_context cron

```bash
# Test the script first
python scripts/populate_performance_context.py --dry-run

# If output looks reasonable (or shows "no governance data" — that's OK, it falls back to paper_trades):
python scripts/populate_performance_context.py --apply

# Add cron entry
crontab -l > /tmp/crontab_current.txt
echo "" >> /tmp/crontab_current.txt
echo "# Populate strategy YAML performance_context blocks (Session 33)" >> /tmp/crontab_current.txt
echo "30 2 * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/populate_performance_context.py --apply >> logs/perf_context.log 2>&1" >> /tmp/crontab_current.txt
crontab /tmp/crontab_current.txt

# Verify
crontab -l | grep populate_performance_context
```

### Step 8: Tonight's deep overnight run will use the new context

The next 23:00 LLM window will read the updated YAMLs. Monitor:

```bash
tail -F logs/llm_overnight.log
```

The LLM should now see (in proposal prompts):
- `vix_rules` blocks → can correctly pause/accelerate strategies by regime
- `technical_indicators_required` → can evaluate proposals against actual gates
- `performance_context` → can weight evaluation by track record

---

## Rollback procedure

If anything goes wrong:

### Rollback option 1: Use the script's own backups

```bash
# Each script created its own timestamped backup dir under backups/
ls backups/strategy_yaml_*
ls backups/schema_convert_*
ls backups/screeners_*

# Restore from the most recent batch (replace <ts> with the actual timestamp)
TS=20260513_201500   # example
cp backups/strategy_yaml_${TS}/*.yaml config/strategies/
cp backups/schema_convert_${TS}/*.yaml config/strategies/
cp backups/screeners_${TS}/screeners.yaml assets/
```

### Rollback option 2: Use the pre-deploy tarball

```bash
# From step 5 of pre-deployment checklist
ls backups/session33_pre_deploy_*.tar.gz
tar xzf backups/session33_pre_deploy_<TS>.tar.gz
```

### Rollback option 3: Git revert (if scripts/ and config/ are committed)

```bash
git status config/strategies/ assets/screeners.yaml scripts/
git diff config/strategies/
git checkout -- config/strategies/ assets/screeners.yaml
```

After any rollback, verify holdings state again before doing anything else.

---

## Known gotchas

1. **`ruamel.yaml` indentation:** preserves source formatting but is picky about quoting. If a YAML diff looks weirdly indented after patching, that's cosmetic, not a parse error. Run `python -c 'import yaml; yaml.safe_load(open("config/strategies/<file>.yaml"))'` to confirm it still parses.

2. **The `earnings_catalyst.yaml` file is marked DEPRECATED, not deleted.** This lets any orchestrator that still references it not crash. After 30 days of stable operation with the new split strategies, you can `git rm config/strategies/earnings_catalyst.yaml`.

3. **`paper_performance_governance` table may not exist yet.** The `populate_performance_context.py` script falls back to computing stats from `paper_trades` directly. This works but won't include drawdown calculations. If your full governance pipeline is running, that's fine — it'll prefer the governance table.

4. **The Finviz URLs in `patch_screeners_yaml.py` are templated.** Adjust to match your Elite account's saved screeners if needed — they're placeholders matching Finviz's documented filter syntax. The KEY thing is the `strategies:` field on each screener — that's what the router uses.

5. **YAML key order:** ruamel preserves the order keys appear in the source file. Newly added keys (vix_rules etc.) will appear at the END of each YAML, not interleaved. That's fine for the LLM and for git diffs, but if you want them in a canonical order, run a separate pass with a key-order normalizer (not included in this package — kept simple).

6. **Don't run `bulk_patch_strategy_yamls.py` twice without `--dry-run`.** It's idempotent (skips already-present blocks) but the second backup directory will be empty/wasteful.

---

## Success criteria

When this is complete, the following should be true:

- [ ] `ls config/strategies/*.yaml | wc -l` shows 22 (or 23 with shared_risk_rules)
- [ ] `python scripts/validate_strategy_yamls.py` reports ≤ 10 issues total across all files (down from 63)
- [ ] Every YAML in `config/strategies/` has all three new blocks: `vix_rules`, `technical_indicators_required`, `performance_context`
- [ ] `fib_retracement_bounce.yaml`, `earnings_pre_buildup.yaml`, `earnings_post_momentum.yaml` all exist
- [ ] `earnings_catalyst.yaml` has `status: DEPRECATED`
- [ ] `assets/screeners.yaml` includes at least: `quality_pullback`, `oversold_quality`, `dividend_value_pullback`, `post_earnings_gappers`, `sector_leadership_rs`, `covered_call_candidates`, `speculative_growth_breakouts`, `defensive_quality`
- [ ] Cron entry for `populate_performance_context.py` is active (`crontab -l | grep populate`)
- [ ] Holdings still show ~$1.19M / 47 positions
- [ ] Tomorrow morning's proposal generation surfaces candidates for at least 4 strategies (not just `swing_breakout` and `gap_and_go`)

---

## Reporting back

After the deployment, please report:

1. **Final issue count from validate_strategy_yamls.py** (expected: ≤ 10, down from 63)
2. **Holdings state check before/after** (must be identical)
3. **Any errors or warnings** during any step
4. **Sample of the new vix_rules block** for one strategy (paste from `grep -A 15 vix_rules: config/strategies/momentum_scalp.yaml`)
5. **Confirmation that the 23:00 overnight LLM window ran cleanly** the night after deployment
6. **Within 48 hours: how many distinct strategies generated proposals** (should be > 2)

That last metric is the real-world test that the screener-to-strategy mapping fix worked.
