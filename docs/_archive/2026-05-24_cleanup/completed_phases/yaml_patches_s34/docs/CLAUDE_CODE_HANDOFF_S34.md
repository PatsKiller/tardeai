# Claude Code Handoff — Session 34 Overnight Window Hotfix

**URGENT: Tonight's 23:00 deep overnight LLM window will crash on the same bug it crashed on at 17:38 today unless these hotfixes ship first.**

Paste this entire file as your opening prompt to Claude Code on MS-01.

---

## Context

You're Claude Code running in tmux on MS-01 (`johnclaw@192.168.50.16`). The project is **Trade AI v12** at:

```
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
```

Venv: `.venv`. Holdings sacred: `$1,190,695 / 47 positions` as of last check.

The 2026-05-13 manual 150-job overnight run crashed at job 73 of 150 with this error:

```
psycopg2.errors.InvalidTextRepresentation:
invalid input syntax for type numeric: "1.5-3.0"
```

The `covered_call_scoring` writer is inserting a range string into a NUMERIC column. The 23:00 auto window will hit this same bug. Plus three more issues:

1. `rag_content_curation` queue-build fails: `column "created_at" does not exist`
2. `risk_synthesis` and `growth_strategy_scan` time out at 180s (need 300s)
3. One job stuck in `running` state will block the queue
4. 10 job types flagged "Unknown" during queue build

The Session 34 patch package is at:

```
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/session34_patches.tar.gz
```

## What this package does

**Phase 1 (read-only diagnostic):** Discovers actual table/column names, file paths, and current queue state. Writes a report to `backups/`.

**Phase 2 (apply):** Resets the stuck running job, marks pending `covered_call_scoring` as skipped (so they don't crash tonight), bumps the 180s timeout to 300s.

**Phase 3 (manual, after diagnostic):** Schema fix for `covered_call_scoring` (widen numeric col to TEXT) and RAG SQL fix. These require you to read the diagnostic first to know which exact column/file to touch.

## IRON RULE

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .env
python -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; c=len(d['holdings']); print(f'Holdings: \${v:,.0f} / {c}'); assert v>1_000_000; assert c>=30"
```

If this fails, **STOP IMMEDIATELY**.

## Execution sequence

### Phase A — Unpack and prep

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .env
source .venv/bin/activate

# Verify deps
pip list | grep -iE '^(psycopg2)' || pip install psycopg2-binary --break-system-packages

# Unpack the tarball
cd docs
ls -la session34_patches.tar.gz   # confirm it's there
tar xzf session34_patches.tar.gz
ls yaml_patches_s34/scripts/
# Should show 6 scripts

cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
cp docs/yaml_patches_s34/scripts/*.py scripts/

# Safety snapshot (the queue state)
mkdir -p backups
psql -d tradeai -c "\copy (SELECT * FROM llm_overnight_queue) TO 'backups/llm_overnight_queue_pre_session34.csv' CSV HEADER"
```

### Phase B — Run the diagnostic

```bash
python scripts/deploy_session34_hotfix.py --phase diagnose
```

This:
- Runs Iron Rule check (must pass)
- Writes `backups/session34_diagnose_<timestamp>.md`
- Prints instructions for next steps

**Open the diagnostic file and read every section.** From it, extract these three facts:

| You need | Where to find it |
|---|---|
| Table+column for the `1.5-3.0` numeric value | Section 1 — look for the NUMERIC column on a covered_call table |
| File containing `ORDER BY created_at DESC LIMIT 8` and correct timestamp column | Section 2 |
| That the timeout bumper will find the 180s references | Section 3 |

**Paste Sections 1, 2, and 3 of the diagnostic into your reply to John before running Phase C.** He needs to confirm the targets before any writes happen.

### Phase C — DRY-RUN the apply phase (no writes)

```bash
python scripts/deploy_session34_hotfix.py --phase apply --dry-run --skip-covered-call
```

Should report:
- Iron Rule: OK
- Stuck running jobs: 1 (the covered_call ARKG job) — would reset to failed
- Pending covered_call jobs: ~1 — would skip
- Timeout bump: 1+ references found, would change 180 → 300
- Post-flight Iron Rule: OK

**If anything looks off (e.g. it wants to reset more than 1 running job, or finds zero 180s timeouts), STOP and paste the output to John.**

### Phase D — APPLY (this is the actual fix)

```bash
python scripts/deploy_session34_hotfix.py --phase apply --apply --skip-covered-call
```

This commits the queue triage + timeout bump. Tonight's 23:00 window is now safe.

### Phase E — Schema and SQL fixes (manual, run after John confirms targets)

**Do NOT run these without John's explicit confirmation of the table/column/file from the diagnostic.**

```bash
# 1. covered_call_scoring NUMERIC → TEXT widening
#    John must give you: TABLE name and COLUMN name from Section 1
python scripts/session34_fix_covered_call_schema.py \
    --table <TABLE_FROM_DIAGNOSTIC> \
    --column <COLUMN_FROM_DIAGNOSTIC> \
    --dry-run

# After reviewing dry-run output:
python scripts/session34_fix_covered_call_schema.py \
    --table <TABLE> --column <COLUMN> --apply

# 2. rag_content_curation SQL fix
#    John must give you: FILE path and replacement column name from Section 2
python scripts/session34_fix_rag_sql.py \
    --file <FILE_FROM_DIAGNOSTIC> \
    --replacement-column <ACTUAL_TIMESTAMP_COL> \
    --dry-run

# After reviewing dry-run output:
python scripts/session34_fix_rag_sql.py \
    --file <FILE> --replacement-column <COL> --apply
```

### Phase F — Verify and commit

```bash
# Final state check
python -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; c=len(d['holdings']); print(f'Holdings: \${v:,.0f} / {c}')"

# Queue should now be clean
psql -d tradeai -c "SELECT status, COUNT(*) FROM llm_overnight_queue GROUP BY status ORDER BY status;"

# Show what we changed
git status
git diff --stat scripts/

# Stage and commit (Phase D only, NOT schema changes)
git add scripts/session34_*.py scripts/deploy_session34_hotfix.py
git add scripts/run_deep_overnight_llm_queue.py   # for timeout bump
git commit -F- <<'MSG'
Session 34 hotfix: overnight queue triage + heavy-job timeout bump

Resolves crash from 2026-05-13 manual 150-job run:
- Reset stuck 'running' covered_call_scoring job to 'failed'
- Marked pending covered_call_scoring jobs as 'skipped' until schema fix
- Bumped LLM call timeout 180s -> 300s for heavy job types
  (risk_synthesis, growth_strategy_scan, rebalance_analysis observed
  needing up to 350s)

Iron Rule verified: holdings $1,190,695 / 47 positions, pre and post.

Schema fix for covered_call_scoring and SQL fix for rag_content_curation
intentionally NOT in this commit — both need the diagnostic to identify
exact targets and will land in separate, carefully reviewed commits.

Co-authored-by: Claude <noreply@anthropic.com>
MSG

# Stage the schema/SQL fixes separately if you ran Phase E
git status
# If schema/SQL fixes were applied, commit them in a separate commit
```

**DO NOT push yet.** Show John `git log --oneline -5` so he can review.

## Report back to John

```
=== SESSION 34 DEPLOYMENT REPORT ===

Iron Rule (pre):  Holdings $______ / __ positions
Iron Rule (post): Holdings $______ / __ positions

Phase 1 Diagnostic findings:
  covered_call table: _______________
  covered_call column to widen: _______________ (current type: _______)
  rag SQL file: _______________
  rag actual timestamp column: _______________
  180s timeout references found: __

Phase 2 Apply results:
  Stuck 'running' jobs reset: __
  Pending covered_call jobs skipped: __
  180s -> 300s replacements made: __

Phase E (schema/SQL fixes):
  covered_call schema fix run: [ ] yes (dry+apply) [ ] no
  rag SQL fix run:             [ ] yes (dry+apply) [ ] no

Queue state after fix:
  pending:  ___
  running:  ___ (should be 0)
  done:     ___
  failed:   ___
  skipped:  ___

Errors / warnings:
  <paste any, or "none">

Commits created:
  <git log --oneline -3 output>

Backups created:
  backups/session34_diagnose_*.md
  backups/llm_overnight_queue_pre_session34.csv
  backups/session34_timeout_*/
  backups/session34_schema_*/  (if Phase E ran)
  backups/session34_rag_sql_*/  (if Phase E ran)

=== END REPORT ===
```

## Failure modes — when to STOP

1. **Iron Rule fails at any point.** Holdings don't match — STOP, do not run any writes.
2. **Diagnostic Section 1 finds zero numeric columns on covered_call tables.** The bug must come from somewhere else; STOP and ask John.
3. **Phase C dry-run reports more than 1 stuck running job.** Something else is going on; STOP.
4. **Phase C dry-run reports zero 180s timeout references.** The regex didn't catch the actual timeout location; STOP and paste the "Showing all 'timeout' lines" output.
5. **Any psycopg2 error during Phase D apply.** Roll back (the script wraps in a transaction) and STOP.
6. **Tonight's 23:00 auto window is less than 30 minutes away.** Stop trying to land Phase E; just commit Phase D and call it done. Phase E can wait until tomorrow morning.

## DON'T do

- Don't run Phase E (schema/SQL fixes) without explicit confirmation from John on the exact table/column/file.
- Don't `git rm` anything — the failing job types are bugs, not garbage to delete.
- Don't push without John reviewing `git log --oneline`.
- Don't try to "fix" the 10 "Unknown job type" warnings tonight. That's a Session 35 job (registry sync) — not blocking.
- Don't restart any cron jobs. The 23:00 window auto-fires from `crontab -l`; just let it run after your fixes land.

That's the job. Run it, report back. The 23:00 window has to launch cleanly.
