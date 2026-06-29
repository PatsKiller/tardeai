# Hermes Research Budget Policy

_Governs how much Hermes researches and at what cost. Same methodology as the Finviz screener
governance + LLM/cloud budget control plane: **measure first, then tier and cap.** Advisory only —
nothing here places a trade, touches the broker, or bypasses any gate._

Config: `config/hermes_research_budget.yaml` · Guard: `scripts/hermes_research_budget_guard.py` ·
Audit: `scripts/hermes_research_scope_audit.py` → `docs/HERMES_RESEARCH_SCOPE_AUDIT.md`

## Why

The scope audit found Hermes was researching **~1,200 distinct symbols / 30d** via the cloud lanes,
**~931 in a single day**, with **~88% of external calls (20.5k / 30d) driven by one broad-universe
source** (`top20_curation`) and **~11.7k redundant repeat calls (≈50%)**. That is broad-universe LLM
research with weak triggers — exactly what tiering is meant to stop.

## Decisions

The guard returns one of: **ALLOW · DEFER · METADATA_ONLY · BLOCK**.

## Tiers

| Tier | What | LLM? | Cloud (free-OAuth)? | Per-run symbol cap | Notes |
|---|---|---|---|---|---|
| **T0** | Holdings, open positions, open proposals | ✅ | ✅ | 200 | Capital exposed — always eligible |
| **T1** | GO candidates, approval queue, high-rank watchlist (score ≥ 70) | ✅ | ✅ | 50 | Near-term decision; capped to stay fast |
| **T2** | Active directives, sector themes, WAIT candidates | ✅ | ✅ | 80 | **Requires an active trigger**; without one, drops to T3 |
| **T3** | Broad discovery universe, snapshots, `top20_curation` default | ❌ | ❌ | 1000 | **Metadata only — never calls an LLM** |
| **T4** | Cold universe, unranked | ❌ | ❌ | — | No research at all |

`trigger_source → tier` is an explicit map. **Anything unmapped fails closed → BLOCK.**

## Hard invariants (enforced + tested)

1. **Broad universe never calls an LLM.** A T3/T4 source requesting any LLM lane is downgraded to
   `METADATA_ONLY` (or `BLOCK` for cold).
2. **Fail closed.** Unknown / empty `trigger_source` → `BLOCK`.
3. **No paid fallback.** A paid model (`claude-*`, `gpt-4o`) is never an allowed automated lane →
   `BLOCK`. (The deliberate, operator-authorized Claude oversight lane is separate and not an
   automatic fallback.)
4. **Market-hours local-heavy block.** `gemma3:27b` / `gemma4-31b` are blocked locally during
   06:00–12:00 ET — matches `docs/diligence/current/LOCAL_LLM_RUNTIME_POLICY.md`.
5. **Cloud unavailable → DEFER.** If a free-OAuth lane is down, the job defers; it never falls back
   to a paid key or a local heavy model.
6. **Duplicate suppression.** Same `(symbol, research_type, lane)` inside the 12h freshness window
   → `DEFER`.
7. **Caps.** Per-tier per-run symbol caps and per-day call caps → `DEFER` once exceeded.

## Where it is enforced (producers patched)

- **`hermes_top20_external_intel.py`** (the 20k-row broad driver): every `(symbol, lane)` is gated.
  Broad names get `METADATA_ONLY`; only held/proposed/directive/high-rank names reach a free-OAuth
  lane, and per-tier caps DEFER the tail. In a live dry-run over 923 candidates this cut the cloud
  fan-out to ~104 ALLOW / 815 DEFER / 4 METADATA_ONLY (~89% reduction) — full coverage preserved
  within caps.
- **`hermes_external_researcher.py`** (central chokepoint for all shell-through producers): enforces
  the broad-universe-no-LLM + fail-closed cuts before any external call and records provenance.

## Provenance

`scripts/migrate_hermes_research_provenance.py` adds nullable columns to `hermes_external_research`
and `hermes_research_intelligence`: `trigger_source`, `trigger_id`, `budget_tier`, `budget_decision`,
`lane_used`, `research_expires_at`, `research_reason`, `downstream_outcome`. New research rows record
the real tier-driving trigger and the budget decision instead of a blanket `top20_curation`.

**Historical backfill** — `scripts/backfill_hermes_research_provenance.py` populates the ~29.4k
pre-enforcement rows from what each already records (trigger_reason / research_type / lane / model):
factual `trigger_source` + `budget_tier` + `lane_used` + `research_expires_at = created_at + tier TTL`,
and `budget_decision = 'legacy'` (we do **not** fabricate ALLOW/DEFER for rows that ran before the
guard existed). Idempotent (`WHERE budget_tier IS NULL`), grouped UPDATEs, `--dry-run` available.
Result: 0 rows left UNMAPPED; the panel now reads stored tiers instead of inferring them. The
retrospective what-if showed **23,275 of 29,413 historical rows (79%) would have been
METADATA_ONLY** under the current policy — the size of the broad-universe LLM problem now closed.

## Verify

```bash
python3 scripts/hermes_research_scope_audit.py --json
python3 scripts/hermes_research_budget_guard.py --selftest      # exits non-zero on any invariant break
python3 tests/test_hermes_research_budget_guard.py
python3 tests/test_hermes_governance_api.py
```
