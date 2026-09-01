# Overnight G3 — Documentation index generator

**Wave:** Overnight G3  
**Date:** 2026-08-31  
**Authority:** READ_ONLY_ADVISORY · no deploy · no cron install  
**Branch:** `fix/overnight-g3-docs-index`  
**Rails:** AGENTS.md §9.3 (lane registry + output_signal before install)

## Finding

`docs/project/PROJECT_DOC_INDEX.md` (and `docs/DOCUMENTATION_INDEX.md`) are
hand-maintained narrative indexes. `scripts/report_docs_inventory.py` already
inventoried the tree and was invoked by nothing. **Do not build a third
mechanism** — wire the existing script.

## Change this tranche

| File | Change |
|------|--------|
| `scripts/report_docs_inventory.py` | Header detection; `--write-index` / `--check-index`; MISSING HEADER count |
| `docs/INDEX.md` | Generated tree listing (committed; regenerate on doc changes) |
| `scripts/run_cio_hardening_ci.py` | Allowlist `overnight_g3_docs_index` + `docs_index_drift` regenerate+diff |
| `config/lane_registry.json` | Additive `docs-index` row with `output_signal` → `docs/INDEX.md` |
| `tests/test_overnight_g3_docs_index.py` | Drift gate, header detector, lane row, allowlist |

Hand-maintained indexes are untouched. `docs/INDEX.md` is the regenerable
listing; it does not claim to supersede DOCUMENTATION_INDEX.

## MISSING HEADER (documentation debt)

A markdown file under `docs/` is **MISSING HEADER** when its first 40 lines
lack YAML front matter and lack structured metadata keys (`**Status:**`,
`**Created:**`, `**Authority:**`, `**Owner:**`, `**Updated:**` / Last updated,
`**Date:**`, `**Document version:**`, or `as_of` / `doc-version`).

| Metric | Value | as_of |
|--------|------:|-------|
| **MISSING HEADER** | **1033** | **2026-08-31T05:39:28Z** |
| Markdown files (excl. INDEX) | 1892 | 2026-08-31T05:40:00Z |
| Header OK | 859 | 2026-08-31T05:40:00Z |
| Files under `docs/` (excl. INDEX) | 2260 | 2026-08-31T05:40:00Z |
| Tree fingerprint | see `docs/INDEX.md` | regenerated with this audit |
| Root | `/home/johnclaw/worktrees/overnight-g3-docs-index` | — |

**MISSING HEADER count as_of 2026-08-31T05:39:28Z: 1033** (stable across adding this
audit, which itself carries an Authority header).

1033 / 1892 ≈ **54.6%** of markdown docs lack a structured header. That is the
honest size of the documentation-header debt; this tranche measures it, it does
not remediate file-by-file.

## Lane registry

```json
{
  "lane_id": "docs-index",
  "state": "NEVER_SCHEDULED",
  "scheduler": {"kind": "none"},
  "output_signal": {"kind": "file_mtime", "path": "docs/INDEX.md"}
}
```

No cron/timer installed (operator-only). CI proves freshness via `--check-index`.

## Proof commands

```bash
python3 scripts/report_docs_inventory.py --write-index --verbose
python3 scripts/report_docs_inventory.py --check-index
python3 -m pytest -q tests/test_overnight_g3_docs_index.py
python3 scripts/check_test_coverage.py --fail-on-new
```

## Deploy

None. Push + merge only.
