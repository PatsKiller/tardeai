# Hermes Governance Panel

Read-only operator view of Hermes research scope and budget posture.

**Location:** Command Center v3 → **System → Hermes** tab → "Hermes Research Governance" card
(`/v3/system?tab=Hermes`).

**API:** `GET /api/v2/hermes/research-governance` (served by `scripts/hermes_governance_api.py`
through `api_v2.handle`; read-only, wrapped as `{ok, data}`).

## What it shows

- **Research by tier (30d)** — T0..T4 calls / distinct symbols. T3 (broad universe) is highlighted
  because it is the bucket that the policy converts to metadata-only.
- **LLM calls by lane** — `cloud_free_oauth`, `cloud_paid` (flagged red), `local_gpu`, `other_nonllm`.
- **Local GPU calls (30d).**
- **Budget posture** — broad-universe LLM blocked · paid fallback blocked · market-hours 27B/31B
  blocked.
- **Duplicate / no-trigger / stale** — redundant call count and %, symbols researched with no active
  trigger, symbols whose research is >30d stale.
- **Top expensive sources** — ranked by `calls × lane weight` (paid heaviest).
- **Budget decisions** — ALLOW / DEFER / METADATA_ONLY / BLOCK counts as producers start recording
  them post-migration.

## Safety

- Strictly read-only. The module contains no INSERT/UPDATE/DELETE, no broker calls, no LLM calls,
  no gate bypass (asserted by `tests/test_hermes_governance_api.py`).
- The panel surfaces governance; it does not create trades or research. Any "run now" style action,
  where added, is source-fetch / metadata only and respects the budget guard.

## Caching

The summary runs the full research-scope audit (~3.5s of SELECTs) — too heavy for the single-threaded
request path. It is served from a **disk TTL cache** (`data/runtime/hermes_governance_cache.json`,
`HERMES_GOV_TTL_SEC` default 600s), the same pattern as `finviz-strip-map`:

- Cached read ≈ **1–3ms**; fresh recompute ≈ 3.5s.
- `?fresh=1` forces a recompute.
- **Pre-warmed out of the request path** by cron: `*/10 6-20 * * 1-5 … hermes_governance_api.py --warm`
  (writes the cache atomically; `flock`-guarded). With a 600s TTL and 120s panel poll, every poll is
  a cache hit.
- `api_v2` reaches the module through an mtime-guarded reload (`_hermes_governance_mod()`), so code
  edits land without a full server restart.

## Refresh

The panel polls every 120s via `useApi`. Underlying numbers come from the cached
`hermes_governance_api.governance_summary()` (audit + stored/backfilled tiers).
