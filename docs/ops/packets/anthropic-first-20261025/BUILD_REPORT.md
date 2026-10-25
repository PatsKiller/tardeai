# Anthropic-first review correction

PR #2181; branch `work/DSN-20261025-anthropic-first-P1-T1`. No merge, release or real provider call by the worker.

The correction implements both independent reviews and retains the coordinator's partial credit/transport work after testing. Shipping activation is disabled. Opus 5.5 is the operator-selected general/high model; eleven named bulk processes use Haiku. Fable is excluded. Original route lanes, independent provider identities, manual/question/process/request/paid-cap authority and off-peak paid deferral remain intact. Credit total $190, UTC daily $10 and all per-call ceilings remain unchanged.

Credit/transport fixes cover typed refusals and free fallback, 429/529 nonbilling, uncertain total holds with reservation-day pacing, non-growing expiry-boundary settlement, paid-vs-promotional components, bounded accounting cooldown, append-only operator reset, model thinking settings and idempotent batch collection. Interruptions after a batch collection claim retain their hold for reconciliation rather than allowing another ledger emission.

Monitoring is cached, exception-contained and based on non-secret configuration presence. Billing P1 is one-shot per promotion; auth alone repeats under the existing window. UNAVAILABLE/stuck-pause P2, empty-digest silence, per-model today/7d usage, fallback-reason detail and private corrected fixtures are implemented. Platform health and Jobs display the shared projection. Needs-action probe/rule are tested but the one-line `api_v2.py` registration awaits its active owner; see OWNER_HANDOFF.md.

Verification checkpoint: the earlier 150-test regression set passed with psycopg2 hidden; the integrated edge-case checkpoint passed 184 tests. Further accounting-boundary changes are included and final combined/native-profile and UI verification must be recorded in verification.json before publication. Prior 263-test proof belongs to the earlier source head, not this correction.

Current Sonnet 5.5 cache-read price is $0.10/MTok in the official pricing page and announcement fetched 2026-10-25; review A's $0.20 correction was not applied. Current dry-run proposal: 67 eligible processes (56 Opus,11 Haiku),23 unchanged; observed-subset token comparison $5.050121/day. Full-day volume/cost is NOT_MEASURED.

Browser/phone execution and screenshots remain NOT_VERIFIED after sandbox refusal; no alternate browser, live server or synthetic screenshot substitution was used. Exact-head GitHub CI and live key-org/tier/forced-exhaustion canaries are not yet proved. Keep the correction unmerged pending those applicable decisions and owner handoffs.
