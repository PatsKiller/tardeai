# Hourly Ask the CIO lifecycle

Design: DSN-20261026-ask-hourly. This change is source and fixture verified work;
production scheduling, real provider dispatch and delivered notifications are
separate acceptance steps. Never treat a green dry-run receipt as fresh research.

## Observed fault

The old operator questions had initial answers but no active hourly evidence-check
loop. A successfully scheduled research dry run did not update their answers.
The deep path omitted operator intent, legacy provider pinning prevented the new
primary route, and the questions surface conflated research memory with shadow
prospect stance. Source/search refusals lost their routing reason. These are
separate conditions and remain separately reported.

## Runtime contract

The existing canonical Ask event ledger remains the sole lifecycle writer.
Native n8n runs `scripts/cio_ask_lifecycle.py --once` on the hour, seven days per
week in America/New_York. A second native five-minute schedule uses
`--events-only` to poll existing material sources. Both use the same dispatcher
executor lock and per-thread ledger locks. There are no host cron additions.

A source check records its original source receipts and fingerprint, then records
last_checked_at independently from last_answer_at. An unchanged complete answer
gets no model call and no new answer version. Changed evidence, incomplete answers
and genuine operator refreshes can request research. Automatic answers retain
the six-hour per-thread cooldown and ten-answers/day ceiling. Deferred events
remain eligible after cooldown without requiring another feed event.

Manual API and scheduler drains share thread locking and re-read state after
acquiring it. Stable request ids suppress duplicate taps. A crashed paid attempt
with uncertain usage retains its reservation and requires reconciliation; it is
never silently repeated. Retry attempts for the same evidence/day are bounded.
Ask admission is atomic across jobs: existing $5/day and $0.50/question caps plus
the shared 30 native-request/day ceiling remain binding. Actual usage settles
holds only with positive provenance. Missing usage remains held. Native global,
process and provider controls remain authoritative too.

Primary analysis uses the governed Anthropic Opus route; independent critiques
use separately admitted DeepSeek, Grok and ChatGPT identities. A refusal or
missing review remains a named partial result, never synthetic agreement. Source
searches use the existing governed search router (including Brave when routed
there); failures and provider receipts are retained. No browser/provider bypass
or ungoverned paid call is introduced.

The shared CIO research memory receives full gathered facts through its existing
writer and security identity. A persisted retry payload permits memory recovery
without recollecting sources or rerunning models. Memory sink acknowledgement,
not a planned-write count, proves synchronization. Failed notification enqueue
can retry from saved answer bytes. Queued delivery remains queued until a genuine
delivery receipt exists; it never appears as delivered by inference.

## Operator surface and health

My questions displays evidence-check time, answer time, next check/eligibility,
source/provider receipts, partial/refused reasons, shared-memory synchronization
and delivery. Shadow prospect stance is a different fact. Manual refresh updates
the existing thread without reloading or scrolling through unrelated rows.

The health collector is registered in research-lane health. It joins native slot,
immutable host attempt, measured summary counts, canonical tracked threads,
memory acknowledgement, consumer readback and delivery. Both schedule receipts
must be independently fresh. Missing, dry-run, failed, stale or malformed evidence
cannot pass. Pending sink writes stay visible. Typed zero-work outcomes distinguish
no tracked threads, no new events and no due threads.

## Admission and verification

Candidate native workflow, health contracts, lane/allowlist rows and process
registrations are in `packets/ask-hourly-20261026/`. The canonical process/routing registries now include the automatic primary and
three independent critics. The existing manual process keeps its free-fallback
behavior; the Ask adapter still verifies the actually served provider and never
counts a fallback as an Opus opinion. All prior registry rows and caps are
preserved. The two lane contracts received CIO source-owner review against the
integrated engine, native executor binding and synthetic health proofs. Candidate
packet files retain their original draft/proposal status for audit; the canonical
config files hold the reviewed source registrations. Both lanes remain
NEVER_SCHEDULED at shadow with live_arg:null until staged runtime admission. The legacy read-only
research dry run is not an accepted replacement for either new schedule.

Tests use synthetic securities, pinned clocks, isolated ledgers, mocked sources,
models and memory. The suite proves unchanged checks, caps under contention,
manual intent, duplicates, interrupted holds, material cooldown retry, source
refusal, memory/delivery-only recovery and dry-run write freedom. UI fixtures
cover desktop and phone layouts with all network responses intercepted. No live
Command Center traffic, secret reads, provider spend or sends form part of this
source proof.

Before activation: publish and review this exact head, run required CI, admit the
process and reviewed contracts, stage bounded native canaries, then retain real
immutable hourly and material-slot receipts plus canonical consumer readback.
Only that evidence establishes production acceptance.

## CI integration and runtime blockers

PR #2195 is published. Its first CI run found integration defects beyond the
focused fixture suite. The follow-up isolates shared Ask accounting, material
readers and pure freshness policy from operator UI and broker dependencies.
The operator core retains its explicit global-cap precheck. Native workers make
only a typed route precheck; the mandatory bridge still reserves authoritative
process, global, provider and promotional budgets before dispatch. No measured
budget balance is inferred from configuration.

The generated inactive workflow now has reproducible source metadata, native
recovery declarations and explicit business-output rules. The registry remains
an offline reconciler fixed point without changing any host schedule. An absent
review timestamp is an availability observation, not a new source event every
hour. Private-entity memory acknowledgement requires the exact answer and entity
to be read back from the canonical Ask ledger.

Two runtime blockers remain separate from source validation. The installed
deploy poller resolves its default Git repository to a release without Git
metadata; the separate deploy-repo fix also aligns clean canonical source before
native prepare. Installing/bootstrap-testing that correction is still required.
The mandatory n8n import gate requires authenticated runtime evidence even for
inactive imports, but its semantic verifier currently implements only L5b.
Unsupported obligation adapters and the authenticated bootstrap path must be
resolved before import. An ordinary cron grant or unsigned JSON cannot satisfy
that requirement. Exact conditional checks and the unresolved boundary are in
`packets/ask-hourly-20261026/n8n/OPERATOR_READINESS.txt`.


Local verification on 2026-10-26: the integration-correction suite passed 815
hidden-PostgreSQL tests with one skip. After the final memory-acknowledgement
review fix, all 224 affected Ask/research/health tests passed, including nine
negative cases for zero-count failed or unmeasured retries. These are overlapping
runs, not additive totals. The unchanged UI has a successful integrated build and
12 fixture-browser cases with 23 screenshots at 1440, 412 and 390 px. Workflow
source/framework checks, registry checks, docs index, Ruff and both test ratchets
pass. No live provider or scheduler acceptance is implied. The archived scheduler
snapshot was used only in reconciler CHECK mode; it is an offline structural
proof, not a fresh host census. Current host schedules were never read or changed
in this task.
