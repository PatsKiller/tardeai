# Trade AI v12 — Collaboration Handoff Guide

**Version:** 1.1  
**As-of:** 2026-04-20 (Tier 1-3 complete, 12 tasks shipped)  
**Audience:** Solo architect picking up while John takes a break from this AI assistant  
**Companion docs:** `schemas_reference_2026-04-19.md`, `roadmap_database_and_enhancements_2026-04-19.md`

This doc covers: how to pick up where I (Claude) left off, how to push to GitHub, commit conventions, branching, and how to coordinate without stepping on each other.

---

## Project direction (updated 2026-04-20)

This system now serves three roles:
1. **Trade AI** — scalp/day-trade screener and scoring engine (Finviz → scoring → dashboard)
2. **Portfolio Intelligence** — portfolio monitoring, AI analysis, reporting, and performance tracking (the data/reporting layer)
3. **Future: OpenClaw Portfolio Advisor-Agent** — an autonomous agent that uses the accumulated Postgres history (signals, briefs, performance, snapshots) as memory for long-term portfolio advice, dividend/compounding strategy, and forecast continuity

**Infrastructure approach:** Local-first with Ollama (qwen3:1.7b for fast inference) for daily analysis; optional Claude Sonnet/Opus or OpenAI GPT-4o for deep monthly synthesis. All data stored locally in Postgres + JSON on MS-01.

---

## Quick start: First 30 minutes on the project

If you're new to this codebase, do these in order:

```bash
# 1. Pull latest
ssh johnclaw@ms01-openclaw          # or wherever the server is
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
git pull origin main                 # see "Git remote setup" below if not yet configured

# 2. Confirm system state
git log --oneline | head -15         # last 15 commits
git status --short                   # clean? expected modified files?
sudo systemctl status tradeai-portfolio-server.service
curl -s http://localhost:7777/api/health

# 3. Confirm database state
PGPASSWORD="$DB_PASSWORD" psql -U trade_ai -h localhost -d trade_ai -c "
SELECT schemaname, tablename,
    (SELECT count(*) FROM pg_class c WHERE c.relname = tablename) as exists
FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"

# 4. Read the docs (in this order)
cat docs/handoff_2026-04-19/schemas_reference_2026-04-19.md      # what data lives where
cat docs/handoff_2026-04-19/roadmap_database_and_enhancements_2026-04-19.md  # what's next
cat docs/handoff_2026-04-19/portfolio_ai_analyst_rewrite_scope.md          # full project scope
cat docs/handoff_2026-04-19/session_2026-04-19_complete.md      # what shipped today
```

After this, you should have a complete mental model of the system.

---

## Git remote setup (one-time, if not already configured)

The repo is currently local-only. To enable GitHub collaboration:

### 1. Create GitHub repo

Go to github.com, create a new **private** repo named `trade-ai-v12` (or whatever you prefer). Don't initialize with README — we already have content.

### 2. Configure SSH key on MS-01

```bash
# Check if key exists
ls -la ~/.ssh/id_ed25519.pub

# If not, generate one
ssh-keygen -t ed25519 -C "johnclaw@ms01-openclaw"
# Press Enter for default location, set passphrase if desired

# Show public key — copy this to GitHub Settings → SSH Keys
cat ~/.ssh/id_ed25519.pub

# Test connection
ssh -T git@github.com
# Expected: "Hi <username>! You've successfully authenticated..."
```

### 3. Add GitHub remote and push

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
git remote add origin git@github.com:<USERNAME>/trade-ai-v12.git
git remote -v
# Expected: origin  git@github.com:USERNAME/trade-ai-v12.git (fetch)
#           origin  git@github.com:USERNAME/trade-ai-v12.git (push)

# Push current main with all 13 commits today
git push -u origin main
```

### 4. Verify .gitignore protects secrets

Before first push, double-check:

```bash
cat .gitignore | head -30
git ls-files | grep -E "\.env|\.key|password" || echo "OK: no secrets tracked"
```

The current .gitignore excludes:
- `.env`
- `data/` (state files, holdings, etc.)
- `__pycache__/`
- `.venv/`
- backup files (`*.pre-*`, `*.bak`)
- test_*.txt files

If any of these show in tracked files, fix the .gitignore and `git rm --cached` them BEFORE pushing.

### 5. Branch protection (recommended)

In GitHub Settings → Branches → Add rule for `main`:
- Require pull request before merging
- Require linear history (no merge commits, force squash or rebase)
- Don't allow force push

This prevents accidents when multiple people work on the repo.

---

## Branching strategy

**Main rule:** `main` is always deployable. The systemd service runs whatever's on `main`.

### For feature work

```bash
# Start a phase or sub-phase as a feature branch
git checkout -b phase-8d3c
# ... do work, commit small incrementally ...
git push -u origin phase-8d3c

# When ready, open a PR on GitHub
# Squash-merge to main when reviewed
```

### For bug fixes

```bash
git checkout -b fix-<short-description>
# ... fix and commit ...
git push -u origin fix-<short-description>
# PR → squash-merge
```

### For experimental / risky work

```bash
git checkout -b experiment-<name>
# work freely, may abandon
# If it works, clean up and squash-merge to main
# If it doesn't, just delete the branch
```

### When NOT to branch

For tiny edits (typo fix, comment adjustment), commit directly to main with a clear message. Branching overhead isn't worth it for one-line changes.

---

## Commit message conventions

Match what John & I have been doing today. Pattern:

```
Phase X-Y: Short description

Longer explanation of what changed and why.

Specific changes:
- Change 1
- Change 2

Verified end-to-end:
- Test 1: result
- Test 2: result

Files committed:
- path/to/file.py (~N lines)
```

### Real example from today

```
Phase 8D-1: Historical reconstruction endpoint with corrected dual-write semantics

Adds GET /api/personal/as_of/<YYYY-MM-DD> endpoint for time-travel
queries. Foundation for 8D-3 time-travel UI.

New functions in scripts/portfolio_server.py:
- _reconstruct_personal_as_of(target_date): Walks personal_history
  via SELECT DISTINCT ON to find each editable field's most recent
  value as-of target_date.
- _handle_personal_as_of(handler, date): HTTP handler with date
  format validation.

Finding 1 fix - dual-write semantics corrected:
- Previous: insert change['from'] (OLD value) with effective_date=last_updated
- New: insert change['to'] (NEW value) with effective_date=today
- Reconstruction logic becomes trivial: latest row IS the truth

Verified end-to-end:
- Reconstruction at today: matches JSON current
- POST changes value, reconstruction reflects new value
- Invalid date returns HTTP 400
- No dual-write errors in service logs

Files committed:
- scripts/portfolio_server.py (~150 lines added)
```

### Why this format

- **Phase X-Y prefix** — easy to grep history (`git log --grep "Phase 8D"`)
- **Verification section** — proves the change works, not just that it compiles
- **Files committed** — quick scan of scope without reading the diff

---

## How to pick up where Claude left off

### Resume from session docs

The freshest context is in:
1. `docs/handoff_2026-04-19/session_2026-04-19_complete.md` — full session log
2. `docs/handoff_2026-04-19/roadmap_database_and_enhancements_2026-04-19.md` — what's next
3. `docs/handoff_2026-04-19/portfolio_ai_analyst_rewrite_scope.md` — full phase scope

Read those + this doc + the schemas reference. Should be ~30 min to full context.

### Resume on a specific phase

Phase docs in scope_doc tell you the design intent. Existing code shows what shipped. Pattern to follow:

```bash
# 1. Find the phase in scope doc
grep -n "Phase 8D-3c\|^## Phase" docs/handoff_2026-04-19/portfolio_ai_analyst_rewrite_scope.md

# 2. Read the section
sed -n '1380,1450p' docs/handoff_2026-04-19/portfolio_ai_analyst_rewrite_scope.md

# 3. Find existing related code
grep -rn "_personal_context\|personal_history" scripts/ | head -20

# 4. Study how previous sub-phases were structured
git log --oneline --grep "Phase 8D"
git show 2dbf19a    # see how Finding 1 fix looked
git show 4bcc8bc    # see how 8D-2 looked
```

### Resume on debugging something broken

```bash
# What changed recently?
git log --oneline | head -20
git log --since='1 day ago' --stat

# What files am I likely interested in?
git log --since='1 day ago' --name-only | sort -u

# Service logs
sudo journalctl -u tradeai-portfolio-server.service -n 100 --no-pager

# Recent errors
sudo journalctl -u tradeai-portfolio-server.service --since='1 hour ago' | grep -i error
```

---

## Working with Claude (this AI) and another architect simultaneously

Likely scenario: John uses Claude (me) for some work, and you (architect) for other work. Coordinate via:

### 1. Explicit phase ownership

Pick phases you own. Document in a shared location (project README or pinned issue) who's working what.

Example:
```
WIP assignments (as of 2026-04-19):
- Phase 8D-3c (AI HISTORICAL CONTEXT)  → Claude session  
- Phase P2-1 (snapshot writes)         → Architect (you)
- Phase 0 (data freshness gate)        → Architect (you), starts after P2
```

### 2. Don't both work on the same file

If two changes hit `portfolio_server.py` simultaneously, you get merge conflicts. Coordinate.

If unavoidable: one person owns the file for the duration of the change. Other person waits.

### 3. Pull before starting work

```bash
git pull origin main
# resolve any conflicts NOW, not after you've made local changes
```

### 4. Push small commits often

Don't accumulate days of work locally. Each verified phase or sub-phase = a push. Lets the other person see progress and avoid duplicating work.

### 5. Status updates in commit messages

If you're partway through a phase, mention what's done and what's next:

```
Phase 0 partial: Data freshness audit script

Investigation phase complete. State files inventoried in
data/portfolios/state/ - found 18 distinct files with varying
update frequencies (range: every-pipeline-run to once-monthly).

Next steps for next session:
- Design unified refresh_all.sh script
- Add freshness check to portfolio_ai_analyst.py startup
- Telegram alert if any state file > 24 hr stale

Files committed:
- linux_port_v2/audit/state_inventory.py
- linux_port_v2/audit/state_freshness_report.md
```

---

## Pre-commit checklist

Before every commit (especially when sharing with another developer):

- [ ] `git status --short` — confirm only intended files changed
- [ ] `git diff` — review your own diff, catch accidents
- [ ] Python syntax: `python3 -c "import ast; ast.parse(open('changed_file.py').read())"`
- [ ] If web file changed: hard-reload browser, click through the feature
- [ ] If schema changed: also update `schemas_reference.md`
- [ ] If new phase: also update `roadmap` doc and `portfolio_ai_analyst_rewrite_scope.md`
- [ ] Service restart if needed: `sudo systemctl restart tradeai-portfolio-server.service`
- [ ] Verify service comes up: `curl http://localhost:7777/api/health`
- [ ] `git log --oneline | head -3` after commit — confirm landed

---

## Common pitfalls and how to avoid them

These are things that bit John & me today. Don't repeat them.

### 1. systemd does NOT inherit shell environment

Symptom: `db_adapter.USE_DB` is False even though .env is set.  
Cause: systemd unit doesn't see your shell exports.  
Fix: Load .env explicitly at module top of any systemd-run script (see `portfolio_server.py` for the pattern).

### 2. Multi-line `replace()` patterns silently fail

Symptom: Python heredoc reports "Pattern not found" but you proceed anyway.  
Cause: Whitespace mismatch between expected and actual file content.  
Fix: Use single-line replacements when possible. ALWAYS check the success message before proceeding. For complex patches, hand off to Claude Code which can interactively diagnose.

### 3. JS `toISOString()` returns UTC, not local

Symptom: After 8 PM EDT, "today" displays as tomorrow.  
Cause: `new Date().toISOString()` converts to UTC.  
Fix: Use local time getters: `getFullYear() + '-' + getMonth() + '-' + getDate()`.

### 4. Backfill timestamps must precede live edits

Symptom: Reconstruction picks the backfill row instead of the live edit.  
Cause: Backfill ran with `recorded_at = NOW()` which was AFTER the live edit.  
Fix: Backfills use `recorded_at = 'YYYY-MM-DDT00:00:00'` (midnight) so any same-day live edit always has later recorded_at.

### 5. Browser cache hides JS changes

Symptom: You changed command_center.html but reload shows old behavior.  
Cause: Browser cached the old version.  
Fix: Always **hard reload** (Ctrl+Shift+R / Cmd+Shift+R) after changing reports/*.html.

### 6. dual-write semantics — insert NEW value, not OLD

Symptom: personal_history shows wrong values, reconstruction returns wrong data.  
Cause: Initial implementation inserted the OLD (superseded) value.  
Fix: Insert `change["to"]` (NEW value) with `effective_date = today`.

### 7. Don't `git add .`

Symptom: Accidentally committed .env, secrets, or generated reports.  
Cause: `git add .` stages everything.  
Fix: Always `git add path/to/specific_file.py`. Use `git status --short` to verify what's staged before commit.

---

## Recovery patterns

### Roll back the last commit (not yet pushed)

```bash
git reset --soft HEAD~1     # keeps changes staged, undoes commit
git reset HEAD~1            # keeps changes unstaged, undoes commit
git reset --hard HEAD~1     # DESTRUCTIVE: discards changes too
```

### Roll back a commit that was already pushed

```bash
git revert <commit-hash>    # creates a new commit that reverses the bad one
git push origin main
```

Never `git push --force` to main.

### Undo a file modification (not yet staged)

```bash
git checkout -- path/to/file.py
```

### See what a commit changed

```bash
git show <commit-hash>           # full diff
git show <commit-hash> --stat    # files changed summary
git show <commit-hash>:path/to/file.py    # file contents at that commit
```

### Find when something broke

```bash
git bisect start
git bisect bad                   # current commit is broken
git bisect good <commit-hash>    # this older commit was working
# git checks out commits in between, you test each one
git bisect good   # or  git bisect bad
# repeat until git identifies the breaking commit
git bisect reset
```

---

## Working with Claude Code

Today's session showed Claude Code (the agentic CLI tool) is excellent for:
- Multi-step verification (database changes + code changes + browser tests)
- Investigation reports (read 11K-line files and report structure)
- Single-prompt complete implementations (with explicit acceptance criteria)

### Pattern that works

```
Phase X-Y implementation: <one-line goal>

Context: <prerequisite shipping commits and what they enable>

Investigation findings (from /tmp/phase_X_investigation.md):
- <key finding 1>
- <key finding 2>

IMPLEMENTATION:

STEP 1 - <description>
<exact code/commands>

STEP 2 - <description>
<exact code/commands>

STEP N - Verification
<exact test commands>

REPORT:
- Each step pass/fail
- Specific test results

Acceptance criteria:
✓ Criterion 1
✓ Criterion 2
✓ ...

DO NOT commit. Just implement and report.
```

### Pattern that fails

- Vague goals ("improve the dashboard")
- No acceptance criteria ("make it nice")
- Multi-day scope in one prompt
- No verification steps
- Permission to commit without human review

### When to use Claude Code vs direct edits

- **Claude Code:** Multi-step, multi-file, requires verification chain
- **Direct edit:** Single-line fix, typo, comment update
- **Human + Claude (chat):** Design discussions, scope decisions, roadmap planning

---

## Recommended tools

### Already installed
- Python 3.13+ in `.venv`
- PostgreSQL 17.9
- Node.js (for some build tools)
- Claude Code (latest)

### Worth adding
- `tmux` for persistent terminal sessions across SSH disconnects
- `htop` for system monitoring
- `pgcli` for nicer Postgres CLI (`pip install pgcli`)
- `git-extras` for utilities like `git changelog`

### Optional
- VSCode with Remote-SSH extension for browsing the codebase locally
- DataGrip or pgAdmin for visual DB management

---

## Final notes

### Trust but verify

Today's biggest lessons:
- **Verify code change BEFORE committing** (lesson from P1's broken commit)
- **Browser-test HTML/JS changes with actual interaction** (lesson from 8D-3a verification gap)
- **Check timezones for any date code** (lesson from 8D-3b UTC bug)

### Commit small, push often

Don't accumulate days of local commits. Each shippable feature → push.

### When stuck, write a doc

If you're confused about what something does or how phases relate, writing it down helps. Add to `schemas_reference.md` or `roadmap.md` rather than keeping it in your head.

### Be honest in commit messages

Don't claim "all tests pass" when you didn't run them. Don't say "verified in browser" when you didn't open a browser. The git log is permanent — make it accurate.

---

*Handoff doc last updated 2026-04-19. Update this whenever you change collaboration practices or hit a new pitfall worth documenting.*
