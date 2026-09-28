---
Status: PROPOSED (PR open; nothing promoted by this campaign yet)
as_of: 2026-09-28T11:40:00-04:00
Measured at: code e2dcfce1a + this branch; served e2dcfce1a
Campaign: LIVEPROOF-20260928
---
# 06 — Changes and promotion

Rule (work order §2.7): no green label from a merged PR alone. Each change lists its test, CI, review, the grant it needs, the served proof it must show after promotion, its rollback and residual risk.

| Change | Files | Tests | Grant needed | Served proof required | Rollback | Residual risk |
|---|---|---|---|---|---|---|
| **C1 — earnings gate fails closed on unknown strategy ids; producer vocabularies map onto one canonical set** (LP-DEF-01) | `scripts/options_desk_enterprise.py` (`NON_BLOCKING_STRATEGIES`, `STRATEGY_ALIASES`, `canonical_strategy`, public wrapper stamping `strategy` + `strategy_raw`), `scripts/lib/buy_ready_options_alternatives.py` (passes its emitted ids `debit_call_vertical`, `leaps_call`) | `tests/test_earnings_gate_vocabulary_20260928.py` (5, drives `build_alternatives` through the REAL gate) + 8 existing options suites (117 pass) | release-write (promote) | (a) served `earnings_blackout_check("AXTI", dte=109, strategy="debit_call_vertical")` → `in_blackout True`; (b) the next natural `cio_entry_state_runner` fire rewrites `buy_ready_options/AXTI.json` with `debit_call_vertical qualified=False` and the packet carries the reason; (c) no card on the Options Desk shows a qualified alternative whose strategy is outside the vocabulary | revert the PR; the 09-28 seven-strategy set (PR #1336) stays | a genuinely new hedge strategy id will be blocked until added to `NON_BLOCKING_STRATEGIES` — that is the intended default |
| **C2 — lane-registry gate: a bare cron schedule is not a pattern** (LP-DEF-19) | `scripts/lib/lane_registry.py` (`_BARE_CRON_SCHEDULE`), `config/lane_registry.json` (dated `inherited_tranches` entry with the six masked lines, provenance recorded) | `tests/test_lane_registry_bare_schedule_20260928.py` (2) + existing lane-registry suites (45 pass); `check_lane_registry --fail-on-new` rc 0 | none (config + gate code; the gate runs from the dev tree in CI and acceptance) | the next CI run on main and the next `report_platform_conformance` show the six lines as known debt, not as declared | revert | the six lines remain unregistered debt until owners declare lanes |
| **C3 — campaign evidence** (`docs/ops/live_proof_20260928/00–07`) | docs only | — | none | — | — | — |

## Promotion plan

1. PR review (independent reader), CI green, then the operator merges (`gh pr merge`) — this session's classifier refuses merges.
2. Promote under the existing release-write path from the dev tree (`prepare` → `promote`), campaign `LIVEPROOF-20260928` named in the grant reason.
3. Post-deploy proof for C1 (the three served checks above) is appended to `04-muted-and-replay-results.jsonl` with `served_sha` = the new pin; until then C1 is INSTALLED, not OBSERVED.
4. No financial-feature flag, no MBI change, no test alert through production channels, no broker call anywhere in this campaign.
