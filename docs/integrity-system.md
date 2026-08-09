# File Integrity Verification System

**Last Updated:** 2026-08-07
**Part of:** [Trade AI Health Inspection System](./health-inspection-system.md), Layer 9

---

## The Problem It Solves

### Stale Release Directories

The Trade AI server is often deployed from a release directory (e.g., `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`) but may be configured to read state files from an older release directory. Over time, multiple release directories accumulate, each containing copies of critical state files like `holdings.json`, `finviz_quote_cache.json`, and `trade_ai_cache.json`.

When the health agent detects a stale file and attempts to patch it, it may unknowingly patch a **copy** in the wrong directory — one that isn't the canonical, authoritative version the live server reads. This creates a false sense of remediation: the stale flag is cleared, but the server continues serving old data.

### Silent Wrong-File Patching

The core danger pattern:

1. Health agent detects `trade_ai_cache.json` is stale
2. Agent runs remediation script
3. Script patches `data/runtime/trade_ai_cache.json` in the dev directory
4. Server is actually reading from `/old-release-path/data/runtime/trade_ai_cache.json`
5. Server continues serving stale data, but health check now says "OK"
6. **Operator is misled into thinking the problem is fixed**

### The NEVER-Silently-Patch Principle

The integrity system enforces a strict rule:

> **If file integrity is violated, NEVER silently patch. Always escalate.**

- Hash mismatch on canonical file → **P0 CRITICAL alert**, investigate corruption/tampering
- Server reading non-canonical file → **P0 CRITICAL alert**, fix server configuration
- Multiple copies of critical files on disk → **P1 WARNING**, recommend cleanup
- File simply stale (old timestamp, **hash matches**) → **Safe to trigger refresh pipeline**

---

## How the Manifest Works

### Manifest Location

```
data/runtime/file_integrity_manifest.json
```

### Manifest Structure

The manifest is a JSON document that records **canonical paths**, **expected SHA-256 hashes**, and **staleness thresholds** for all critical state files.

```json
{
  "version": "1",
  "generated": "2026-08-07T16:38:56.410773+00:00",
  "description": "File Integrity Manifest — canonical paths, expected hashes...",
  "files": {
    "finviz_quote_cache": {
      "canonical_path": "data/portfolios/state/finviz_quote_cache.json",
      "sha256": "16e2e7d9e52bfd5551cd3709777b85d8be6e8a659c415942b498d7d83411a739",
      "size": 29834,
      "source_pipeline": "external_market_data_ingest.py",
      "max_age_minutes": 30,
      "consumers": ["portfolio_dashboard", "holdings_cards", "system_health_agent"]
    }
    // ... 10 more files
  },
  "critical_basenames": [
    "finviz_quote_cache.json",
    "trade_ai_cache.json",
    "holdings.json",
    // ... 10 more basenames
  ]
}
```

### Tracked Files (11 critical state files)

| Key | Canonical Path | Max Age | Source Pipeline |
|-----|---------------|---------|-----------------|
| `finviz_quote_cache` | `data/portfolios/state/finviz_quote_cache.json` | 30 min | `external_market_data_ingest.py` |
| `trade_ai_cache` | `data/runtime/trade_ai_cache.json` | 180 min | `trade_ai_orchestrator.py` |
| `holdings` | `data/portfolios/state/holdings.json` | 30 min | `portfolio_repricer.py` |
| `ai_analysis_cache` | `data/portfolios/state/ai_analysis_cache.json` | 720 min | `ai_portfolio_analyzer.py` |
| `ai_deep_holdings` | `data/portfolios/state/ai_deep_holdings.json` | 720 min | `ai_deep_holdings_analyzer.py` |
| `ticker_enrichment_cache` | `data/portfolios/state/ticker_enrichment_cache.json` | 360 min | `ticker_enrichment_engine.py` |
| `price_cache` | `data/portfolios/state/price_cache.json` | 30 min | `market_quote_ingest.py` |
| `price_ohlc_cache` | `data/portfolios/state/price_ohlc_cache.json` | 60 min | `ohlc_ingest.py` |
| `staleness_escalation_queue` | `data/runtime/staleness_escalation_queue.json` | 1440 min | `system_health_agent.py` |
| `trade_ai_health` | `data/portfolios/state/trade_ai_health.json` | 60 min | `trade_ai_health.py` |
| `risk_management` | `data/portfolios/state/risk_management.json` | 120 min | `risk_autopilot.py` |

---

## How `check_file_integrity.py` Works (4-Step Pipeline)

The integrity check runs as a 4-step pipeline:

```
check_file_integrity.py
  ├── STEP 1: Runtime Awareness
  │   └── Discovers live server PID, directory, cache paths
  ├── STEP 2: Canonical File Integrity
  │   └── Verifies each file in the manifest against its expected SHA-256 hash
  ├── STEP 3: Server Cross-Check
  │   └── Compares what the server reads vs canonical paths
  └── STEP 4: Stale Copy Detection
      └── Scans filesystem for extra copies of critical files outside canonical paths
```

### Step 1: Runtime Awareness

Uses `RuntimeAwareness` to discover:
- What process listens on port 7777
- What directory the live server is running from
- What cache file it reads
- Whether the live directory differs from the dev directory

### Step 2: Canonical File Integrity

For each file in the manifest, the verifier:
1. Reads the expected SHA-256 hash from the manifest
2. Computes the actual hash of the canonical file on disk
3. Compares hashes — mismatch = P0 CRITICAL (possible corruption/tampering)
4. Compares file sizes (secondary check; hash is authoritative)
5. Checks staleness if hash matches (old timestamp with matching content = safe to refresh)

**Status outcomes:**

| Status | Hash Match | Stale | Action |
|--------|-----------|-------|--------|
| `OK` | Yes | No | Nothing needed |
| `STALE` | Yes | Yes | Trigger refresh pipeline (safe) |
| `HASH_MISMATCH` | No | — | P0 alert, investigate corruption |
| `SIZE_MISMATCH` | — | — | P0 alert, file modified |
| `MISSING` | — | — | P0 alert, file not found |
| `UNREADABLE` | — | — | P0 alert, permissions issue |

### Step 3: Server Cross-Check

The cross-checker determines whether the live server is reading canonical files:
1. Discovers the server's working directory (from `/proc/PID/cwd`)
2. For each file in the manifest, checks if a copy exists in the server directory
3. Resolves both canonical and server paths to absolute paths
4. Determines if the server reads the canonical file (same resolved path)

**Alert scenarios:**

| Server Has File | Paths Match | Hash Match | Severity | Meaning |
|----------------|-------------|------------|----------|---------|
| Yes | No | Yes | P0 | Server reads old release copy, same content — update server config |
| Yes | No | No | P0 | Server reads stale/wrong file with different content — CRITICAL |
| No | — | — | P1 | File missing from server directory |

### Step 4: Stale Copy Detection

Scans the entire project tree for files named like critical basenames:
1. Walks the project root, skipping `.git`, `__pycache__`, `venv`, `node_modules`, `.cursor`
2. For each critical basename, finds all copies on disk
3. Excludes: the canonical path itself, backup directories (`file_backups/`, `backups/`), `.bak` files
4. For each extra copy found: computes hash, compares to canonical entry
5. Reports as P1 WARNING

### Output Formats

```bash
# Human-readable report with emoji indicators
python scripts/check_file_integrity.py

# Machine-readable JSON (for programmatic consumption)
python scripts/check_file_integrity.py --json

# Summary only
python scripts/check_file_integrity.py --summary

# Stale copy scan only
python scripts/check_file_integrity.py --stale-copies-only

# Canonical integrity only (skip server cross-check)
python scripts/check_file_integrity.py --canonical-only

# Server cross-check only
python scripts/check_file_integrity.py --cross-check-only
```

### Exit Codes

- `0` — All files healthy
- `1` — P1 warnings (stale copies, stale files with matching hashes)
- `2` — P0 critical (hash mismatch, missing canonical files, server reading non-canonical)

---

## How to Regenerate the Manifest After Deployment

After every deployment that modifies state files, regenerate the manifest:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Regenerate all entries
.venv/bin/python scripts/generate_integrity_manifest.py

# Preview changes without writing
.venv/bin/python scripts/generate_integrity_manifest.py --dry-run

# Regenerate only specific files
.venv/bin/python scripts/generate_integrity_manifest.py --file finviz_quote_cache --file holdings
```

The generator:
1. Loads the existing manifest (preserving source_pipeline, max_age_minutes, consumers metadata)
2. Computes fresh SHA-256 hashes for all canonical files on disk
3. Records current file sizes
4. Updates `critical_basenames` list
5. Sets `last_validated` to current timestamp
6. Reports a diff of what changed (hash changes, size changes, path changes)

---

## How to Add New Files to the Manifest

Use the `--add` flag to register a new file:

```bash
.venv/bin/python scripts/generate_integrity_manifest.py \
  --add my_new_state_file data/path/to/file.json \
  --add-source my_pipeline.py \
  --add-max-age 60
```

Or edit `DEFAULT_FILES` in `scripts/generate_integrity_manifest.py` and add a new entry:

```python
{
    "key": "my_new_state_file",
    "canonical_path": "data/path/to/file.json",
    "source_pipeline": "my_pipeline.py",
    "max_age_minutes": 60,
    "consumers": ["portfolio_dashboard"],
},
```

Then run the generator to include it in the manifest.

---

## P0/P1 Alert Hierarchy for Integrity Violations

### P0 — CRITICAL (blocks automated remediation)

| Alert Type | Condition | Action |
|-----------|-----------|--------|
| `HASH_MISMATCH` | Canonical file hash differs from manifest | Investigate corruption/tampering. DO NOT PATCH. Run `generate_integrity_manifest.py` if this is a legitimate update. |
| `SIZE_MISMATCH` | Canonical file size differs from manifest | File has been modified. Run `generate_integrity_manifest.py` to update manifest. |
| `MISSING` | Canonical file does not exist | Restore from backup or regenerate. |
| `UNREADABLE` | Cannot read canonical file (permissions?) | Fix filesystem permissions. |
| `NON_CANONICAL_SAME_CONTENT` | Server reads file from non-canonical path, content matches | Update server to read from canonical path or regenerate release. |
| `NON_CANONICAL_STALE` | Server reads file from non-canonical path, content DIFFERS | DO NOT PATCH the stale file. Fix server configuration to read canonical path. |
| `UNKNOWN_FILE` | File key referenced but not in manifest | Add the file to manifest or fix the reference. |

### P1 — WARNING (does not block but requires attention)

| Alert Type | Condition | Action |
|-----------|-----------|--------|
| `STALE` | File hash matches but timestamp exceeds max_age_minutes | Trigger refresh pipeline. Safe because content is verified correct. |
| `STALE_COPY` | Extra copy of critical file found outside canonical path | Clean up old release directories. Remove stale copies. |
| `MISSING_ON_SERVER` | Canonical file exists but is missing from server directory | Copy file to server directory or regenerate release. |
| `STALE+CORRUPT` | File is both stale AND has integrity issues | Fix integrity first, then refresh. |

### P2 — INFORMATIONAL

| Alert Type | Condition | Action |
|-----------|-----------|--------|
| `NO_SERVER_FOUND` | No process listening on port 7777 | Expected if server is stopped outside trading hours. |

---

## Integration with Health Pipeline

### In `system_health_agent.py`

The system health agent now includes integrity checks in its monitoring pipeline. When integrity violations are detected, the agent:
1. Does NOT auto-retry (violates NEVER-silently-patch)
2. Escalates critical findings to the operator via Telegram
3. Writes findings to the escalation queue for code-level investigation

### In `health_agent.py`

The `run_auto_remediation()` function checks file integrity as a prerequisite before any patching. If integrity is violated, auto-remediation is blocked for affected files.

### In `inspect_all.py`

The health inspector's `inspect_all.py` runs `check_runtime_awareness.py` first, which provides the live directory context that `check_file_integrity.py` needs for its server cross-check step.

---

## Key Design Decisions

1. **SHA-256 is authoritative**: Size comparison is secondary. Hash comparison is the source of truth.
2. **Staleness is separate from integrity**: A file can be stale (old) but still have correct content (hash matches). These are different problem classes with different remediation strategies.
3. **Manifest is deployment-local**: Each deployment generates its own manifest reflecting the state files at that deployment point.
4. **Manifest is NOT a backup**: It records expected hashes, not actual file content. Actual backups live in `file_backups/` and `backups/`.
5. **Stale copy detection scans the full project tree**: Finds copies in old release directories, not just the canonical location.
6. **Server cross-check uses `/proc/PID/cwd`**: Ground truth about what the live server is actually reading, not assumptions.
