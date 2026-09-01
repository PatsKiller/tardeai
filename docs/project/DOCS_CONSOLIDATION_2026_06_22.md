# Documentation Consolidation — 2026-06-22 (A1A)

Status:      HISTORICAL
as_of:       2026-06-22T11:33:45-04:00
Measured at: efcc51365 / not measured

**Operator request:** Align `/docs` with live system; purge outdated counts; commit pending runtime/config changes.

## What changed

### 1. Live facts authority (`docs/LIVE_SYSTEM_FACTS.md`)
- New canonical pointer for all scale counts (tables, crons, scripts, strategies).
- Policy: active docs reference LIVE_SYSTEM_FACTS or `scripts/generate_system_facts.py` — no hard-coded scale numbers.

### 2. Canonical docs rewritten (counts → pointers)
| Doc | Change |
|-----|--------|
| `MASTER_SYSTEM_DOCUMENTATION.md` | Header 2026-06-22; System Scale table → live keys; DB layer table count → pointer; 23 strategies |
| `EXECUTIVE_ARCHITECTURE_OVERVIEW.md` | 23 strategies; footer → LIVE_SYSTEM_FACTS |
| `CHEAT_SHEET.md` | Header 2026-06-22; DB size lever → pointer |
| `COST_MODEL.md` | RDS storage row → pointer |

### 3. Drift detector hardened (`scripts/generate_system_facts.py`)
- Scans active top-level `docs/*.md` only (excludes CHANGELOG, LIVE_SYSTEM_FACTS).
- Tighter regex — no false positives on `python3 scripts/` or `strategy-specific`.
- Historical docs (`CHANGELOG`, `_archive/`, `PHASE*`) exempt by policy.

### 4. Purged / not modified (intentional)
| Material | Disposition |
|----------|-------------|
| `docs/CHANGELOG.md` | Historical — past counts preserved |
| `docs/_archive/**` | Point-in-time snapshots — unchanged |
| `docs/project/PHASE*_CLOSEOUT.md` | Phase evidence — unchanged |
| `docs/COMMAND_CENTER_PAGE_MATRIX.md` | Page inventory — historical build log; not a live-count doc |

### 5. Runtime + config committed (32 dirty files)
| Category | Files | Nature |
|----------|-------|--------|
| Strategy YAMLs | 17 | `performance_context` refresh from weekly feedback loop |
| Runtime JSON | 7 | catalyst calibration, source attribution, Hermes capabilities (cron-generated) |
| Scripts | 3 modified + 3 new | Finviz global throttle (`alpaca_throttle.py`), OHLC charts, health agent; new throttle + diag scripts |

## Verification

```bash
.venv/bin/python3 scripts/generate_system_facts.py
# Expect doc drift → 0 on canonical top-level docs after this consolidation
```

## Ownership

| Component | Owner script |
|-----------|--------------|
| Live facts | `scripts/generate_system_facts.py` |
| Doc protocol | `docs/A1A.md` |
| Doc index | `docs/DOCUMENTATION_INDEX.md`, `docs/project/PROJECT_DOC_INDEX.md` |
| Drive sync | `scripts/sync-docs-to-drive.sh` (gog CLI) |