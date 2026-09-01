# Overnight G2 — Import normalisation (A3 dual-load hot paths)

**Wave:** Overnight G2  
**Date:** 2026-08-31  
**Authority:** READ_ONLY_ADVISORY · `MBI_BEHAVIOR=0`  
**Branch:** `fix/overnight-g2-import-normalise`  
**Deploy:** none  
**Sized by:** Wave A3 — static dual-load risk ~20–25 scheduled entrypoints
(`NORMALIZE_LIB_PATH` / `DUAL_ROOT` / spelling fallbacks). Morning-brief chain
was restored earlier (`scripts/lib/__init__.py` bootstrap +
`assert_single_import_identity`); this wave normalises the hot paths so both
spellings are not loaded as distinct module objects.

---

## Rule

Pick **one** mode per entrypoint — never both:

| Mode | `sys.path` insert | Import spelling |
|---|---|---|
| **root-only + scripts.lib** | repository root only | `from scripts.lib.X import …` |
| **scripts-only + lib** | `scripts/` only (cron path-run already provides this) | `from lib.X import …` |

Also removed on these files:

- `try: from lib.X … except …: from scripts.lib.X …` (and the reverse)
- bare imports of `scripts/lib` modules that dual with `lib.X` (e.g. `from watchlist_priority` alongside `from lib.…`)
- inserting **both** root and `scripts/`, or **both** `scripts/` and `scripts/lib`

Kept:

- `assert_single_import_identity()` — called from entrypoints **after imports settle**
- bootstrap in `scripts/lib/__init__.py` — **does not raise at package-init** (a check
  during `__init__` would be theatre: no submodule has loaded yet)

---

## Files normalised this tranche (10)

| File | Mode | Notes |
|---|---|---|
| `scripts/process_watchlist_agent_jobs.py` | scripts-only + lib | Dropped `scripts/lib` insert; bare lib-mods → `lib.*`; removed bare↔`lib.*` ImportError fallbacks on `agent_job_provider_policy` |
| `scripts/hermes_watchlist_scorer.py` | scripts-only + lib | Dropped dual `scripts`+`scripts/lib`; `watchlist_priority` → `lib.watchlist_priority` |
| `scripts/hermes_top20_external_intel.py` | scripts-only + lib | Dropped dual path; `cio_agent_contract` → `lib.cio_agent_contract` |
| `scripts/schwab_position_sync.py` | scripts-only + lib | Dropped dual path; `holdings_sanity` → `lib.holdings_sanity` |
| `scripts/moomoo_live_read_sync.py` | scripts-only + lib | Dropped dual path; `env_bootstrap` → `lib.env_bootstrap` |
| `scripts/holdings_gain_guardian.py` | scripts-only + lib | Dropped nested `scripts/lib` insert; `holdings_sanity` → `lib.holdings_sanity` |
| `scripts/cio_reactive_cycle.py` | root-only + scripts.lib | Dropped `scripts/` insert; all `lib.*` → `scripts.lib.*`; removed reassessment spelling fallback |
| `scripts/provider_cost_reconcile.py` | root-only + scripts.lib | Dropped `scripts/` insert (already `scripts.lib.*`) |
| `scripts/research_lane_health.py` | root-only + scripts.lib | Dropped `scripts/` insert |
| `scripts/memory_shadow_project.py` | root-only + scripts.lib | Dropped `scripts/` insert |

**Already clean (recorded, not rewritten):** `scripts/alert_dispatcher.py` — no
`sys.path.insert`, no spelling fallback.

---

## Tests / CI

| Artifact | Role |
|---|---|
| `tests/test_overnight_g2_import_normalise.py` | Allowlist + dual-path / spelling / mode / identity / cron-form probes |
| `scripts/run_cio_hardening_ci.py` gate `overnight_g2_import_normalise` | Coverage allowlist registration |

Soft dependency stubs that are **not** spelling fallbacks (kept): e.g.
`pipeline_registry` optional stub in `process_watchlist_agent_jobs.py`.

---

## Rails

| Rail | How |
|---|---|
| Never both path modes | static AST check on allowlisted files |
| Never spelling fallback | regex gate on `try lib / except scripts.lib` |
| Mode↔spelling consistency | root-only forbids `from lib.`; scripts-only forbids `from scripts.lib.` |
| Identity assertion present | each allowlisted entrypoint references `assert_single_import_identity` |
| No raise at package-init | AST on `scripts/lib/__init__.py` |
| Cron-form import | subprocess by path, cwd=/tmp for a root-only and a scripts-only probe |

---

## Out of scope

- Remaining ~10–15 dual-load entrypoints beyond this allowlist (later tranche)
- Rewriting all 3,244 `scripts.` / `lib.` statements repo-wide
- Deploy / promote / cron repoint
- Changing `scripts/lib/__init__.py` bootstrap behaviour
