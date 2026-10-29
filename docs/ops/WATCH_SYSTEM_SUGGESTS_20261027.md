# Watch System Suggests: facts and review progress

Design: none. Existing cards and full-screen phone-detail pattern; no navigation, tab or widget is removed.
Design-Task: DSN-20261027-watch-suggests-P1-T1

System Suggests uses the ranked research universe with the existing ownership, membership, dismissal and expiry exclusions. Missing Watch-card coverage is distinct from research-universe membership. The CC data broker batches market evidence for displayed suggestions and resolves CIO truth by confirmed security GUID.

Company facts remain on the shared CIO InstrumentRecord. The existing population writer includes a bounded suggestion target group. Offline captures have no default production selector; the production-only adapter reuses the CC broker, verifies its state-root binding, and refuses incomplete selection. Missing selection makes coverage partial, never complete. The stored prospectus calendar contributes issuer-bound earnings/dividend events only; macro events remain context. Unknown or stale source observation times never borrow the report-generation time.

## Review interface

`GET /api/v3/data-broker/watch-curation?review_status=1&symbols=ZZAA,ZZBB` returns `WatchReviewStatus@v1`, bounded to30 unique validated symbols. It reads the existing priority queue, acquisition ledger and canonical CIO projection. It performs no provider call, send, model call or write. The normal curation interface is unchanged.

Phone actions use the existing review command and shared controller: immediate feedback, durable request ID, next declared processing slot or an explicit unavailable ETA, visible refusals, and one batched progress poll every ten seconds while the page is visible and a request is open. Newer request/attempt clocks win over an older response. Answered outcomes cause a full-row refresh. HTTP errors never become a queued success.

A historical acquisition publication is not a canonical CIO decision. Publication identity, request, GUID, artifact and original publication clock must agree with the canonical readback before a current CIO answer is claimed. An existing valid prospect can receive research.review_lifecycle through the existing writer facade after exact thesis-version readback. That writes ANSWERED_PENDING_CIO only; it changes no stance, conviction or conflict resolution. Missing/facts-only prospects and unacknowledged PG writes remain explicit gaps. Pending memory linkage retries the durable result without another model call. A completion for another request never closes the current request.

Company evidence, research publication, canonical decision and page/transport refresh keep separate clocks. The reload notice compares the executing bundle to served metadata; it does not auto-reload or rename an old observation as fresh.

## Verification and operational boundaries

Synthetic fixtures cover desktop1440 and phones412/390 with all traffic intercepted. Real API captures/screenshots and investigation evidence belong only in the private coordination handoff, never this public repository. Test totals and exact-head CI evidence belong in the PR, not static completion claims here.

Producer registration, independent health-contract review, native framework admission and host receipt proof are separate from code/browser correctness. No host schedules, live flags, relay live list, broker, orders, sizing or stops are changed by these read-model fixes. Do not interpret existing records or a fresh failure receipt as a successful producer run.

Stored calendar events carry their original analyst-capture or dividend-record observation times. Rebuilding a prospectus does not refresh those observations. Events without an original source clock remain explicitly unavailable to company-fact curation; estimated dates retain their estimate label.

Population captures distinguish the injected server-enforced read-only query from the existing in-process CC suggestion selector's independent SELECT sessions. `capture_query_read_only` covers the injected query only; `suggestion_selection.database_transaction_read_only=not_proven` records the remaining admission proof. It must not be presented as proof that all capture sessions share a read-only transaction.

Review queue-write and progress-read failures are recorded through the existing incident ledger with deduplicated fingerprints and safe error classes. An unproven runtime root refuses host-ledger writes and emits a structured warning. No exception message is copied into the operator surface or incident record.

If the incident CLI is available in the merged base, errors use it. Until then structured private warnings and the coordination worklog retain status, owner and next step. Follow-up: integrate the incident ledger from PR2238 after it lands; no local substitute is declared authoritative.
