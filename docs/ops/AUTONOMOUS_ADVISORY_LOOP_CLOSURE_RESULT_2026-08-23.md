# Trade AI Autonomous Advisory Loop Closure Result

**Date:** 2026-08-23  
**Authority:** `READ_ONLY_ADVISORY`  
**Memory influence:** `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Final status:** `HOLD`  
**Publication status:** source branches and PRs pushed; not merged or deployed

## Executive result

The autonomous advisory loop is implemented across a sequential stack of review
branches and has passed isolated NOC acceptance. It is **not live production
proof**. GitHub CI is failing before job execution with empty step lists, CURRENT
still serves the older exact release, most advisory/research jobs still execute
the rebuild tree, and physical local-model decommission prerequisites are not
met. No merge, deployment, CURRENT change, cron/systemd change, or model removal
was performed.

Do not report `AUTONOMOUS_ADVISORY_LOOP_PROVEN` until the reviewed stack is green,
merged sequentially, deployed to exact CURRENT, and verified through natural
runs. Do not remove an Ollama model while any source, cron, systemd, OpenClaw,
test, or active-process reference remains.

## Source truth

| Item | Result |
|---|---|
| Starting and final `origin/main` | `9dfe437f6e161cb2b6c9ed2c983e23b9fa9de1b7` |
| CURRENT release | `5e91225a1186659de3cfd65096e037e774506e7f` |
| CURRENT path | `trade-ai-releases/portfolio-server/5e91225a-main-exact-phase2-20260821-193607` |
| PR #460 | CLOSED, unmerged, head `67052266fe534563a6b04e9aa7a1c9cb812f9259` |
| Latest program PR | #472, head `0a91364662e81fbbd6e80fe13490899b4e576e34` |
| Dirty rebuild | Audited but not modified or cleaned |
| Runtime tree audit | 162 entries; 75 drift findings; rebuild 47, hybrid 28, other tree 86, CURRENT 1 |

## Corrections to the handoff

- Research had minted live theses through operator-driven runs: 22 held names,
  17 CURRENT and 5 THIN; reentry 24/25 CURRENT; T1 292/299 CURRENT.
- `cio_investment_product.adjudicate_reentry()` already consumes symbol thesis
  and can block weak or non-governed promotion. Thesis was not a zero-effect
  input.
- The missing lifecycle was automatic research completion to structured delta,
  material thesis reconciliation, deterministic decision gate, reassessment,
  notification decision, feedback, outcome measurement, and learning candidates.
- Historical batch mint/change cards were backfills, not independent changes of
  mind and not proof of autonomous circulation.

## NOC golden loop

The isolated acceptance artifact proves all eight stages in source without
financial writes:

| Field | Result |
|---|---|
| Symbol | NOC |
| Mode | `ISOLATED_SOURCE_ACCEPTANCE`; `live_proven=false` |
| Research | `research_noc_golden_1` |
| Delta | `rtd_96b661450ff4f747a5fc`; `STRENGTHENS` |
| Thesis | `symbol_noc@v1` to `symbol_noc@v2` |
| Decision | `dec_noc_golden_v2`; governed verdict HOLD |
| Feedback | DISAGREE, linked to decision and `symbol_noc@v2` |
| Replay | `NO_NEW_INFO`; no new version, card, decision, Telegram, or request |
| Financial writes | 0 |

The stateful prompt contains the standing thesis/version, prior conclusion,
prior delta, unresolved gaps, deterministic changes, market/sector context,
separate supporting and contradictory RAG evidence, eligible feedback, governed
memory context, ratified lessons, and Financial Senses receipts. No raw
chain-of-thought is stored.

Evidence:

- `docs/_evidence/autonomous_advisory_loop/noc_golden_loop_isolated.json`
- `docs/_evidence/autonomous_advisory_loop/noc_research_prompt_redacted.json`
- `docs/_evidence/autonomous_advisory_loop/noc_golden_browser/manifest.json`

The Playwright preview passed 2/2 browser tests and rendered full NOC thesis,
BND THIN state, APIs, Telegram receipts, and research operations. It was an
isolated preview with `pin_match=false`, not a production deployment.

## Implemented review stack

| PR | Head | Scope | State |
|---:|---|---|---|
| 461 | `07225e5b7b91fa148e3d6876ee8f25c76b249226` | UI truth, denominators, pin/cache provenance | OPEN |
| 462 | `767653eceef33a7896949bd6c7a10640cf3face9` | Stateful research, delta, RAG-first, automatic thesis, decision gate | OPEN |
| 464 | `70415dbcca39e3e99d9084a9c455f6db25d72eb4` | NOC replay, feedback, DecisionPayload, browser acceptance | OPEN |
| 465 | `6b504ce3307257128af4b8fe29715cccfd25c7bd` | Initial local-generative routing retirement | OPEN |
| 466 | `2c1ed2c945ac7f915bbb65f3535d6b95925bce61` | Outcomes, event research, metadata, universe projection | OPEN |
| 467 | `3574f3cdb423a61bb5f8784e43b67ba1d3ee5a2d` | Maturity collectors | OPEN |
| 468 | `55b306b35569bb1f67b1d69e9e62e1044c034127` | CIO stale/conflicted sizing suppression and feedback | OPEN |
| 469 | `82735ed99c9b766fe6595acc6b311e73a664b4b0` | Research hygiene and symbol-scoped reassessment | OPEN |
| 470 | `c9971a80c94e4cfac2279a50e12ebf6f997fb24c` | Authoritative call accounting | OPEN |
| 471 | `2349a65b33a1eaed1c93dcf98a864a242ff31417` | Telegram correctness and unrelated-symbol churn suppression | OPEN |
| 472 | `0a91364662e81fbbd6e80fe13490899b4e576e34` | Scheduled local-generation migration and physical audit | OPEN |

No PR in this program is merged or deployed. PR #472 initially received backend
and frontend failures with `steps: []`; the other required workflows remained
queued. This is consistent with the repository runner/billing failure and does
not satisfy the all-green deployment gate.

## Research, decisions, feedback, and outcomes

- `ResearchThesisDelta@v1`, canonical stateful context, RAG-first support and
  contradiction retrieval, event/staleness selection, material-change
  reconciliation, provenance, and `ThesisDecisionGate` are implemented.
- `INVALIDATES`, broken, conflicted, and insufficient states fail closed.
  `STRENGTHENS` and `CONFIRMS` may improve completeness but cannot independently
  create RE_ENTER or ADD.
- All six operator-visible producers have DecisionPayload emitters with
  change-or-bounded-heartbeat dedupe in the review stack.
- Governed feedback supports AGREE, DISAGREE, DEFER, NEED_DATA, and
  NO_LONGER_RELEVANT. Retro rows are lower trust and excluded from promotion
  recall.
- Outcome records freeze the prediction before governed horizons and compute
  benchmark-relative results without hindsight rewriting. Candidates cannot
  self-promote into policy or financial truth.
- New-schema live feedback/outcome coverage remains `UNMEASURED` until deployment.

## Call accounting

The historical discrepancy is closed:

- 1,336 total provider-bound results = 895 calls sent + 441
  `COST_CAP_EXCEEDED` rejections.
- 971 scheduler dispatches covered 544 symbols; 427 symbols were dispatched
  twice.
- 917 reservations versus 895 sends does not prove hidden provider retries.
- The excess came from repeated dispatch, an additional producer, and the skip
  gate being absent from the live crontab tree.

PR #470 adds producer/run/call identifiers and terminal classification for
scheduled, attempted, retry, fallback, error, cap, deduped, skip-gated, and
reservation-only events.

## Telegram and operator surface

The supplied FCNTX/JTAI messages exposed cross-symbol rebuild churn and invalid
financial-looking cards. PRs #469 and #471:

- scope reassessment to the changed symbol;
- replace false “caused” language with reassessment provenance;
- suppress conflicting FCNTX prices;
- suppress JTAI when distance contradicts the NEAR threshold or long
  invalidation geometry is invalid;
- keep opportunity evidence separate from reentry levels;
- require source/as-of, quote freshness, zone consistency, and stable identity;
- prevent plaintext fallback from becoming a second logical notification.

These fixes are pushed for review but are not present in the live CURRENT UI or
Telegram workers.

## Local-model decommission

Read-only host measurement on 2026-08-23:

| Gate | Result |
|---|---:|
| Generative models installed | 6 |
| Active generative processes | 1: `gemma3:12b`, observed 100% GPU |
| Live rebuild source references | 241 |
| Pending branch source references | 171 |
| Active cron intersections | 45 |
| systemd intersections | 5 |
| Active OpenClaw configuration references | 24 |
| Required-by-tests proven NO | false |
| Seven-day zero-call proof | false |
| Embedding acceptance | false / unmeasured |

Installed generative models are `gemma3:4b`, `gemma3:27b`,
`gemma3-overnight:latest`, `gemma3:12b`, `qwen3:8b`, and
`gemma3:12b-ctx4k`. Embedding candidates are `qwen3-embedding:8b` and
`nomic-embed-text:latest`; only a pinned, accepted `nomic-embed-text` may remain
under an `EMBEDDINGS_ONLY` result.

`PHYSICAL_REMOVAL_READY=false`. Current status is
`GPU_MODE=UNRESOLVED_HOLD`, not an accepted final GPU mode. No model was removed.
The five systemd intersections are `hermes-autonomous-loop`,
`hermes-deep-research-local`, `hermes-external-feedback`,
`high-llm-execution-worker`, and `tradeai-iris-taxonomy`.

## Unexplained-number closure

| Number | Resolution |
|---|---|
| UI coverage 2.4% | Stale cached calculation: 3 CURRENT / 124 material. New payloads declare numerator, denominator, states, and membership scope. |
| Thesis 3 to 12 | Operator/backfill `thesis_mint_from_research.py` circulation, not automatic research completion. |
| 895 versus ~312 | Reconciled by the 1,336-event accounting above. |
| 94 / 735 cards | Batch mint/backfill cards, not independent thesis reversals. |
| 441 cap errors | Provider-gate complement to 895 sent calls. |
| 22 versus ~32 holdings | 22 unique held equity tickers versus account-position, cash, CUSIP, duplicate-account, and remnant rows. |
| 974 versus 3,061 universe | Different legacy projections; the new canonical projection declares membership and denominator. Live result remains unmeasured until deployment. |

## Tests and maturity

- PR #472 migration/domain run: 121 passed.
- Final routing/registry/embedding/entry/topic/Aegis run: 98 passed.
- No-broker-write and release guards: 10 passed with one pre-existing warning.
- Prior stacked PRs include focused tests for delta/replay, DecisionPayload,
  feedback, outcomes, event research, call accounting, Telegram correctness,
  browser acceptance, provider cost, RAG, AIF/Financial Senses, CIO hardening,
  and release readiness.
- Remote CI is not green because jobs are not executing.

Live maturity must therefore remain `UNMEASURED` for new feedback/outcomes and
non-green for GPU policy, pin convergence, and tree-root integrity. Docs and
isolated previews do not count as deployed capability progress.

## Security and authority

- Existing financial MCP remains read-only; no generic HTTP, shell, write, or
  desktop-browser capability was added.
- Broker mutations: 0.
- Order mutations: 0.
- Stop mutations: 0.
- Risk-policy mutations: 0.
- 2FA mutations: 0.
- Trading-authority changes: 0.
- Memory truth overrides: 0 in acceptance.

## Required path to live

1. Restore GitHub runner/billing and obtain every required green workflow.
2. Review and merge the stacked PRs sequentially, reconciling any movement on
   protected main without force-pushing shared branches.
3. Build an exact-main release and verify loaded pin, source pin, process start,
   data age, cache age, and `pin_match=true`.
4. Obtain operator authorization for advisory/research Batch 0 and subsequent
   CURRENT cron/systemd cutover. Broker/order/stop/risk/2FA services remain out
   of scope.
5. Prove natural runs for research, thesis reconciliation, six decision
   producers, feedback, outcomes, Telegram suppression, and NOC replay.
6. Reach zero local-generative callers and active processes, then complete the
   seven-day zero-call proof.
7. Accept pinned embedding reproducibility/GPU/RAG gates or remove the embedding
   models and retire Ollama from Trade AI.

Until all steps pass, the correct status is **HOLD: implemented and pushed for
review, not live**.

## Maturity impact

`MATURITY_IMPACT: research acquisition, research utilization, reasoning,
feedback, outcomes, notification signal/noise, source provenance, pin integrity,
GPU policy compliance, and tree-root integrity. Live metric paths are supplied
by the stacked collectors and scripts/audit_local_model_decommission.py.`
