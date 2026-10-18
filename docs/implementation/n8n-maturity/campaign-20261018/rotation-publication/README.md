# Rotation digest root cause and publication contract

Status: DRAFT
as_of: 2026-10-18T23:08:01.939604+00:00
Measured at: source 6d1e43043d1c23c48503fa11ccbda4669604b2e2; production a2aef7b4d2de17e737526337a2ffc37848deda4f

The retained October 18 cache contains SCHG→DNP, PFLT→DNP and NOC→DNP twice each.
The API expands repeated endorsed target rows into proposals; the digest then
prints the first five without deduplication. Distinct accounts also hold SCHG,
but the digest omits account identity. The API's symbol-only first-position join
can attach one account's shares to another account's proposal.

A soft LLM `broken` verdict has severity 4 and `deterministic: false`. The API's
severity threshold labels it a stop hit and produces a 50–100% review range,
even when the same digest reports zero deterministic stop signals. A fresh
cache timestamp also hides explicit STALE source account state. The DNP
recommendation is conditional ADD_ON_PULLBACK with thin analyst coverage, which
the old digest omits. No broker or trade action was performed in this audit.
The retained snapshot matches the supplied alert's pairs; exact delivered
attempt/provider-message binding and the upstream DB duplicate origin remain
unproven. Account identifiers in the retained audit are hashed.

The fix binds proposals to account+symbol and deduplicates only the original
selected target window and raw six-proposal cap. It preserves ranking,
selection and financial formulas. Unsupported deterministic-stop claims are
withheld rather than replaced with new financial math. Every required position
and account source clock uses the existing AccountState and portfolio market
calendar rules; weekends alone do not establish staleness. Engine age and cache
age are separate. A cache restamp cannot refresh old output.

| Interface | Producer / storage | Consumers | Shape and semantic enforcement | Failure / compatibility | Status and proof |
| --- | --- | --- | --- | --- | --- |
| RotationPublication@v1 | api_v2._rotation_summary; existing memory/disk cache | host digest; three summary POST routes; four CC views in paired reader tranche | lib.rotation_publication.project_summary at fresh output and every cache read; ready/publication_refusal before POST effects; shared UI display validator | STALE/UNAVAILABLE clears advice and unmeasured totals; unsupported/old cache is readable but held; GET never starts a cache producer | Implemented locally and independently reviewed; not deployed; baseline/candidate tests and immutable artifact manifest |

The digest preserves source account and target context, reports source clocks
and refuses to seed research from held advice. POST grok-rebalance-review,
oversight and research-gaps return a typed 503 before LLM or DB work when source
publication is unavailable. Ready output still requires normal host authority;
this interface grants no financial action or broker access.

Eight original behavioral assertions fail on actual 7af baseline and pass on the
candidate. Independent review then found four more source-clock/structured-action
cases, followed by a future-account-clock consumer gap. Those unchanged tests
fail for the expected assertions before their fixes. Final nonauthor validation
passes 68 tests; author regressions pass 130 tests. The native suite is added to
the canonical CIO runner. The exact-head full local acceptance, hosted checks,
PR review/merge and canonical release remain distinct gates.

Old already-open UI clients are a staged rollout concern, tracked with PR #1856.
The paired reader tranche and compatible version rollout must pass before release
acceptance. Underlying research/card/LLM provenance beyond these scoped clocks,
actual Telegram delivery and restored useful business output remain unproven.
No learning, digest, broker refresh, notification or research effect was rerun
for proof. Production remains on a2aef7b4d after the rejected 7af release rollback.
