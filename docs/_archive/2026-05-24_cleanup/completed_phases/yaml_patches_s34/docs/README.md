# Session 34 Hotfix Package

Patch package for resolving the 2026-05-13 overnight LLM queue crash.

**Target:** MS-01 (`johnclaw@192.168.50.16`), project root `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`.

**Tarball lives at:** `<project_root>/docs/session34_patches.tar.gz`.

## Files

```
yaml_patches_s34/
├── scripts/
│   ├── deploy_session34_hotfix.py             # 2-phase orchestrator (diagnose → apply)
│   ├── session34_diagnose.py                  # Read-only: dumps schema + state + grep findings
│   ├── session34_queue_triage.py              # Resets stuck running, skips pending covered_call
│   ├── session34_bump_timeouts.py             # Bumps 180s → 300s in queue runner
│   ├── session34_fix_covered_call_schema.py   # MANUAL: widens NUMERIC col to TEXT (needs args)
│   └── session34_fix_rag_sql.py               # MANUAL: replaces created_at with real col (needs args)
└── docs/
    ├── CLAUDE_CODE_HANDOFF_S34.md             # Opening prompt to paste into Claude Code
    └── README.md                              # This file
```

## What ships tonight (auto)

- Queue triage: reset stuck running, skip pending covered_call_scoring
- Heavy-job timeout bump: 180s → 300s

## What requires manual review before applying

- `session34_fix_covered_call_schema.py` (needs `--table` + `--column` from diagnostic)
- `session34_fix_rag_sql.py` (needs `--file` + `--replacement-column` from diagnostic)

Run them tomorrow morning when there's time to read the dry-run output carefully.

## Iron Rule

All scripts run a pre-flight check against `data/portfolios/state/holdings.json` and abort if total < $1M or count < 30. The orchestrator also runs a post-flight check after Phase 2.

## Idempotency

- `queue_triage`: idempotent (UPDATE WHERE status = 'running' returns 0 if nothing stuck)
- `bump_timeouts`: idempotent (regex matches `\b180\b` only; second run finds 0 hits)
- `fix_covered_call_schema`: idempotent (checks current type, skips if already TEXT)
- `fix_rag_sql`: idempotent (string replace; second run finds 0 occurrences)

## Rollback

Every apply step writes a timestamped backup under `backups/session34_*/`. To roll back:

```bash
# Timeout bump
cp backups/session34_timeout_<ts>/run_deep_overnight_llm_queue.py scripts/

# RAG SQL fix
cp backups/session34_rag_sql_<ts>/<filename> <original_location>

# Queue state (if needed)
\copy llm_overnight_queue FROM 'backups/llm_overnight_queue_pre_session34.csv' CSV HEADER

# Schema change (covered_call) — review the JSON backup, ALTER TABLE manually
# This is the highest-risk rollback; the JSON dump preserves all original data
```
