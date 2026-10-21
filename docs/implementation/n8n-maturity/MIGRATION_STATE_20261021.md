# Cron → n8n migration state — 2026-10-21

```
Status:      ACTIVE (snapshot; supersedes the unmerged MIGRATION_STATE_20261014.md of PR #1727)
as_of:       2026-10-21T15:50:00-04:00
Measured at: origin/main 7faa8cddf; CURRENT 7faa8cddf-main-exact-phase2-20261021-154546; host crontab and the
             coordination ledger (mode=ro) read 2026-10-21 15:45–15:50 ET
Owner:       platform (n8n maturity program)
Policy:      AGENTS.md §23 (§23.12, §23.14, §23.23, §23.24, §23.25). Cutover standard: AGENTS.md §23.21, 16.0.0
             PROPOSED (rebuilt from 8.0.0 / PR #1727), awaiting APPROVE_AGENTS_POLICY_16_0_0
```

Evidence tags (AGENTS.md §4): **[M]** measured by this file's author at `as_of` with the command named · **[DOC]**
another document, not re-measured · **[I]** inferred. This file replaces no live tracker; the per-lane truth is the
coordination ledger and `config/lane_registry.json`.

## 1. The standard, and its policy state

Operator ruling 2026-10-14 ~11:05 ET, verbatim: *"new standards apply when i say so fix and dry and regression
testing, yes it should run live successful to many road blocks to testing"*. A lane cuts over when (1) its defect is
fixed and served, (2) its n8n dry run passes (a forced `dry_run` fire counts), (3) its lane regression tests pass
under `TRADE_AI_CI=1`, and (4) it has at least one successful `live` n8n run with the cron line still present under
the shared lock: the dispatcher's slot, or a live fire the operator forces inside the lane's window. The cron line
is then commented, never deleted, and the commented line is the fallback.

**Policy state.** The ruling was first written as AGENTS.md 8.0.0 (PR #1727), which was closed without ratification.
Main nonetheless depends on it: §23.23 (4) and §23.25 cite "§23.21 cutover standard", and
`scripts/n8n_cutover_wave.py` describes every wave as "§23.21: fix + dry run + regression + at least one live n8n run
with the cron line still present; no soaks". On 2026-10-21 the operator said "yes rebuild 1727"; the rebuild is
AGENTS.md **16.0.0, PROPOSED**. Until `APPROVE_AGENTS_POLICY_16_0_0 <pr> <sha>` is given and merged, the ACTIVE text
of §23.3 and §23.14 still states the `trade-ai-scalp-live` three-clean-market-day fallback, and onboarding step 8
still states the natural shadow slot. The operator has waived that wait per lane in words (§4).

## 2. Counts [M]

| Measure | Value | How measured |
|---|---|---|
| Registry lanes | 653 | `config/lane_registry.json` at 7faa8cddf |
| Dispatcher rows at `stage: cutover` (n8n the only scheduler) | 13 | registry, `scheduler.stage == "cutover"` |
| Cron rows at `canary` (`dispatch.mode: live`, cron line live under the shared lock) | 34 | registry `kind cron`, `stage canary` |
| Cron rows at `shadow` (`dispatch.mode: dry_run`) | 39 | registry |
| Dispatcher rows at `canary` / `shadow` | 9 / 3 | registry `expression dispatcher` |
| Host crontab active job lines | 346 | `crontab -l`, non-comment, non-blank |
| `# RETIRED … n8n-cutover` lines | 16 | `crontab -l` |
| Ledger runs (all time) | 26,108 on 131 lanes | `runs` table |
| Ledger since 2026-10-14 | dry_run `RUN_DONE` 10,758; live `RUN_DONE` 9,382, `RUN_SKIPPED_LOCK` 113, `RUN_FAILED` 6, `RUN_TIMEOUT` 1 | `runs` grouped by mode, state |
| Lanes with a live `RUN_DONE` | 56 since 2026-10-14; 45 on 2026-10-21 | `runs`, distinct `lane_id` |
| Executor workers | 4 (drop-in `40-memory-workers-20261014.conf` overrides the 3 of `10-executor-v2.conf`) | `systemctl --user cat tradeai-n8n-run-executor.service` |

## 3. Retired cron lines (the fallback) [M]

`crontab -l` carries 16 commented `# RETIRED <date> n8n-cutover <lane>` lines:

| Date | Lanes |
|---|---|
| 2026-10-09 | `crontab-snapshot-for-health-agent`, `n8n-pilot-dispatch`, `n8n-incident-fanin`, `n8n-research-intake-consumer` |
| 2026-10-13 | `research-insight-extractor` |
| 2026-10-16 | `record-decision-outcome`, `hermes-news-bridge`, `source-attribution-monitor`, `wire-advisory-lessons`, `hermes-governance-api`, `hermes-analyst-signal-discovery`, `document-mentions-backfill`, `identity-sweep-stage0`, `material-change-detector-stage1`, `catalyst-symbol-impact`, `catalyst-graph` |

The registry's 13 cutover rows are `source-attribution-monitor`, `identity-sweep-stage0`,
`material-change-detector-stage1`, `document-mentions-backfill`, `catalyst-symbol-impact`, `catalyst-graph`,
`hermes-momentum-catalyst-scalp`, `hermes-governance-api`, `hermes-analyst-signal-discovery`, `hermes-news-bridge`,
`research-insight-extractor`, `record-decision-outcome` and `wire-advisory-lessons`. The four 2026-10-09 lanes are
platform lanes whose rows predate the dispatcher row shape **[I]**. `hermes-momentum-catalyst-scalp` is a cutover row
whose line was commented on 2026-10-16 with a different tag, `# N8N-ONLY TEST 2026-10-16 (operator: comment out to test
n8n; fallback = uncomment)` (crontab line 717) **[M]**; `_cutover.py rollback --lane` does not parse that tag, so its
fallback is the hand uncomment the tag names.

## 4. Today: `hermes-watchlist-scorer` under an operator waiver

- Shadow: released in `a6ac0ebbe` (PR #1899). Dry runs `RUN_DONE` at 12:55 and 13:00 ET, 1408 items, 812 scored, 0
  errored **[DOC]** (commit `d1cb7cf5b`).
- Waiver, operator 2026-10-21 ~13:05 ET, verbatim: "push live now" (waives the 3-market-day shadow wait of
  onboarding step 8), and "comment out whats working now this can be a fallback". Recorded in the registry row's
  `canary.operator_waiver` and the contract's `review.stage_rereview`.
- Canary: registry `kind cron`, `stage canary`, `dispatch.mode live`; allowlist `live_arg []`, lock
  `/tmp/hermes_scorer.lock` = the cron line's `flock` lock. Merged in #1904 and served in CURRENT
  `7faa8cddf-…-154546` **[M]**.
- At 15:45 ET the ledger still shows only `dry_run` fires for the lane (latest 19:45Z) **[M]**: the dispatcher's
  live requests are demoted until step 2 of `docs/ops/packets/hermes-scorer-canary-20261021/README.md` adds the lane to
  `TRADEAI_N8N_RELAY_LIVE_LANES`. The cron line is live (1 active match in `crontab -l`).
- Next: first live `RUN_DONE` with rows written → `02_retire_cron_line.sh` comments the line under a `cron` grant
  (`n8n_cutover_wave.py comment-cron`) → registry PR `n8n_cutover_wave.py cutover`.

Under 16.0.0 the waiver is not needed: the two `RUN_DONE` dry runs meet criterion (2).

## 5. `trade-ai-scalp-live`

Registry `kind cron`, `stage canary`, `dispatch.mode live`, lock `/tmp/tradeai_scalp_live.lock` **[M]**. Its dispatcher
fires today are `dry_run` `RUN_DONE` every 5 minutes **[M]**. Its cron line stays the fallback under the ACTIVE
§23.3 / §23.14 text until 16.0.0 is ratified; after that, criterion (4) — one in-window live `RUN_DONE` with the cron
line present — is the condition.

## 6. Open items

1. **Ratify 16.0.0** — the standard main already cites; the patch and its test are on branch
   `agents/cutover-standard-23-21-20261021`.
2. **`scripts/n8n_cutover_checklist.py`** now accepts `OPERATOR_FORCED_LIVE` for criterion (4), but its shadow step
   still asks for two natural `dry_run` slots. It is a read-only reporter; its shadow verdict is not a cutover blocker.
3. **Forced live fires are refused for keyed lanes** (`run_key_namespace_refused`), so the dispatcher's slot is the
   usual live proof; this is by design (audit DD03), not a defect.
4. **`N8N_ONBOARDING_STANDARD.md` step 8** still states the natural-slot gate; the 16.0.0 ratifying edit corrects it.

## 7. Evidence

| Evidence | Path |
|---|---|
| Coordination ledger | `~/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite` (`mode=ro`) |
| Registry, allowlist, contracts, effect keys | `config/lane_registry.json`, `config/n8n_run_allowlist.json`, `config/n8n_health_contracts.json`, `config/n8n_effect_keys.json` |
| Cutover receipts | `$TRADEAI_STATE_ROOT/data/runtime/n8n_cutover/` |
| Today's packet | `docs/ops/packets/hermes-scorer-canary-20261021/` |
| Procedure | [`RUNBOOK_CUTOVER_ROLLBACK.md`](RUNBOOK_CUTOVER_ROLLBACK.md) |
| Architecture | [`N8N_RUNTIME_ARCHITECTURE.md`](N8N_RUNTIME_ARCHITECTURE.md) |
| Previous snapshot (unmerged) | PR #1727, `docs/implementation/n8n-maturity/MIGRATION_STATE_20261014.md` on branch `docs/n8n-migration-state-20261014` |
