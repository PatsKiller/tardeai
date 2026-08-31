# Watch Quality Governance — 2026-07-25

Status:      HISTORICAL
as_of:       2026-07-26T11:32:09-04:00
Measured at: efcc51365 / not measured

## Status

Draft PR #172 is a deterministic-first remediation of the Watch decision system. It is based on PR #171 so the deployed support/resistance and valuation-card changes are preserved. PR #170 remains the backend valuation-source dependency.

This document is not activation authority. No production packet rebuild, static deployment, scheduler change, provider call, paid lane, broker action, order, trade, approval or 2FA action is authorized by the PR.

## Live defects that motivated the tranche

The captured Watch desk showed several evidence horizons presented as one decision:

1. `stale >7d` was Street-consensus age, while the same card reported current technical and strategy timestamps.
2. The sovereign card state could be `WAIT` while a non-primary long-term family displayed `READY`.
3. Discovery rank and analyst enthusiasm allowed low-priced, extreme-volatility, high-P/S and deterministically unattractive names to consume the active operator surface.
4. Arithmetic PASS did not answer the separate instrument-quality question.
5. `REVIEW_REQUIRED` could be labeled as deterministic verification.
6. Missing validation could fall back to a synthetic PASS in an older packet path.
7. OAuth critic invocation and evidence curation were insufficient for dependable independent review.

## Governing hierarchy

The release hierarchy is fixed:

1. source provenance and freshness;
2. deterministic quality admission;
3. deterministic ticket arithmetic, ordering, proximity, event and risk checks;
4. exact-ticket local/OAuth independent critique;
5. optional operator-selected paid escalation;
6. separate proposal review;
7. existing trading, approval and 2FA controls.

A later layer cannot waive an earlier failure. Models never create, repair or move entry, stop, target, size, trigger or option contract values.

## Quality admission contract

Policy: `config/watch_quality_policy.json`  
Engine: `scripts/watch_quality_policy.py`  
Version: `watch-quality-admission-v1`

States:

- `ADMITTED`: the instrument clears the quality layer. All remaining gates still apply.
- `RESEARCH_ONLY`: evidence remains available, but current new-entry mechanics are withheld.
- `QUARANTINED`: hard new-entry refusal; retained for audit or existing-position management.

The policy currently governs:

- minimum price: $5;
- minimum float: 20 million shares;
- minimum market capitalization: $500 million;
- preferred market-cap tier: $1 billion;
- preferred ATR ceiling: 7% of price;
- hard extreme-volatility ceiling: 10% of price;
- preferred pre-profit P/S ceiling: 20x;
- hard pre-profit P/S ceiling: 40x;
- explicit exclusion of scalping, low-float and social-momentum structures.

These are governed policy values, not hidden constants. Threshold changes require review and regression evidence.

Existing holdings remain visible for management. A held-name exception never grants a new add.

## Deterministic ticket contract

`strategy_ticket_validator.py` evaluates quality and ticket mechanics independently. It preserves a recomputed arithmetic audit even when quality fails. A quality refusal strips current entry mechanics before they may be presented as actionable.

The canonical packet selector in `watch_packet_quality.py` scans both `current_actionable_plan` and retained family structures. A stripped failed ticket therefore remains visible as `FAIL / QUARANTINED` rather than disappearing as `UNASSESSED`.

The browser selector in `apps/command-center-v3/src/lib/watchPacketQuality.ts` mirrors this rule.

## Independent-review contract

Contract: `watch-ticket-independent-review-v2`

Every local/OAuth critic receives the same immutable packet:

- exact ticket;
- deterministic recomputation;
- quality-admission result;
- current price, ATR, RVOL, float and timestamps;
- whitelisted raw fundamentals;
- deterministic thesis factors;
- compact technical evidence and freshness;
- data-quality state, events and recent catalysts.

Excluded anchoring inputs:

- Street recommendation;
- CIO/model verdict;
- Hermes rank;
- social popularity;
- another critic's verdict.

The response schema is strict. Incomplete or malformed output is `UNAVAILABLE`, never inferred. OAuth uses the supported prompt-first `lane=` contract.

The paid lane is never scheduled or automatically called. Reconciliation can only recommend operator-selected escalation and state the reason.

## Operator semantics

Contract: `watch-quality-governance-v1`

- Street-consensus age is labeled `STREET DATA >7D`.
- Price, technical, packet and review freshness remain separate fields.
- One operator state governs the card.
- Only the selected primary family may display `READY`, and only when the card is `READY`.
- Non-primary long-term evidence is `OWNERSHIP ELIGIBLE`.
- Other non-primary constructible evidence is `MECHANICS VALID`.
- The ticket panel identifies its canonical validation source.
- Free review remains disabled before deterministic validation and quality admission.

## Scheduler contract

Local deterministic work comes first. It may assess unassessed symbols or refresh admitted/research names.

OAuth blind work requires all of:

- `quality == ADMITTED`;
- `new_entry_allowed != false`;
- `deterministic == PASS`;
- an existing packet beyond the governed blind cadence.

Non-held, non-starred quarantined names are deferred from the active scheduler budget. Starred or held names remain visible for research/management but do not receive an admission exemption.

Premium review is never scheduled.

## Required rollout sequence

### Gate 1 — exact-ref source validation

Run `scripts/validate_watch_quality_governance_from_ref.sh` from the exact reviewed PR head. Required final status:

`PASS_WATCH_QUALITY_GOVERNANCE_VALIDATION`

This gate compiles focused Python modules, runs pure regression tests, runs TypeScript, builds Vite and verifies UI markers from a temporary Git archive. It does not touch live `dist` or the database.

### Gate 2 — read-only before census

Run `scripts/watch_quality_audit.py --limit 200` in a forced PostgreSQL read-only session. Preserve the sanitized output. Review:

- admitted / research-only / quarantined / unassessed counts;
- deterministic PASS / REVIEW_REQUIRED / FAIL / NOT_RUN counts;
- packet freshness counts;
- held-management exceptions;
- presentation conflicts;
- missing packets.

### Gate 3 — bounded local-only packet rebuild

Only after Gates 1 and 2 pass, prepare a separately reviewed operator command that rebuilds a small named sample using `LOCAL_QUANT` with provider lanes disabled. The sample must include:

- one expected institutional-quality admission;
- one expected research-only name;
- one expected quarantine;
- one held-management exception;
- one previously contradictory WAIT/READY card.

No OAuth, paid, broker, order or approval action belongs in this gate.

### Gate 4 — read-only after census and card inspection

Repeat the census and inspect exact card contracts. Quality and deterministic states must match the retained packet evidence; no synthetic PASS, generic stale badge or simultaneous READY/WAIT command may remain.

### Gate 5 — separate UI deployment decision

A static deployment requires a new exact source commit, an atomic backup/rollback packet, TypeScript/build/browser proof and explicit operator approval. It must preserve PR #170/#171 data and card work.

### Gate 6 — separate scheduler decision

Do not change cron or service schedules in the same action as UI deployment. First run the scheduler in dry-run mode and review local/OAuth counts, deferred quarantine count, tier distribution and estimated lane calls. Schedule activation requires separate approval.

## Current blockers

- GitHub-hosted workflow jobs are terminating before step 1, so they provide no compiler or test evidence.
- Exact-ref host validation has not yet been run against the latest head.
- The production population has not yet been censused using the new read-only audit.
- Existing packets have not been rebuilt with quality-admission evidence.
- No live UI or scheduler change from PR #172 has been authorized.
