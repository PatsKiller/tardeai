Ask hourly native n8n and business-health packet — DSN-20261026-ask-hourly-P1-T4

State: SOURCE + SYNTHETIC PROOF ONLY. Nothing in this packet was imported,
activated or written into the shared scheduler/config files. The coordinator
reviews the contract and shared proposals; live and first-natural-slot evidence
remain pending. No task completion claim is made.

Exact native schedules (America/New_York, all seven days):
  cio-ask-lifecycle       0 0 * * * *    on every hour, runner --once
  cio-ask-material-events 0 */5 * * * *  every five minutes, --once --events-only
Both invoke scripts/cio_ask_lifecycle.py and share /tmp/cio_ask_lifecycle.lock.
Material runs poll existing material feeds/cursors and process only new events
or retryable blockers. They never do off-hour hourly checks. The six-hour answer
cooldown gates another answer, never an hourly evidence check.

workflow.native.candidate.json is actual, INACTIVE native n8n JSON. Both branches
reuse the existing dispatcher graph: authenticated GET relay /due with the exact
lane filter obtains a server-minted d: key; authenticated POST relay /run sends
only lane, mode, key and execution identity; the relay signs the coordination
request and the existing host executor enforces admission. The only credential
material is the existing tradeai-run-relay credential NAME/ID reference. No secret
value, direct provider call, public webhook, unauthenticated /run, caller-generated
p: key or global EVENT_MODES/effect-slot widening is introduced.

Existing generic dispatcher can observe the same admitted schedule rows. Both
paths use the same host-minted slot key and ledger/effect dedupe; importing the
native workflow must not create another logical slot or a host cron twin. The
native trigger's existence/activation still needs observed n8n metadata; receipt
health does not invent proof of import/activation from a successful host run.

Shared-config proposal files (PACKET ONLY, do not auto-apply):
  lane-registry.rows.candidate.json — two LaneRegistry@v1 rows, owner cio,
    state NEVER_SCHEDULED, scheduler n8n/native, stage shadow, class llm,
    dispatch.mode dry_run, timezone America/New_York, active_days 0..6.
  run-allowlist.rows.candidate.json — N8nRunAllowlist lane rows, command above,
    dry_run_arg [--dry-run], live_arg null, output_receipt v2, timeout600s,
    llm_route via cio-governed-bridge / process_ids:
      cio_ask_reanswer
      cio_ask_critique_deepseek
      cio_ask_critique_grok
      cio_ask_critique_chatgpt
    The executor binds the exact complete set in TRADEAI_LLM_PROCESS_IDS;
    no singular process_id is present. Each critic keeps its separately
    registered provider identity and existing spend/request gates.
  health-contracts.candidate.json — complete N8nHealthContract@v1 bodies,
    DRAFT, null reviewer, structurally checked both as DRAFT and as a copied
    REVIEWED candidate. N8nExpectedOutput@v1 uses typed empty reasons only.
    A cooldown never authorizes empty per-thread BUSINESS checks.
  shared-config.proposed.patch — exact additive proposals for the three
    currently claimed shared files. Root reconciles against their owners.
  automated-process-admission.candidate.json — caller/task/process identity,
    not a spend grant. The root/policy owner must admit all four process_ids in
    governed_process_routes and the process routing/cap registry. Missing any
    critic route refuses the entire lane before a child can run. This packet
    changes no request/USD limit and never borrows the manual deep-research
    operator-intent header. Missing route remains llm_process_route_not_registered.

Business proof, read-only:
  Native scheduled slot -> matching successful immutable LaneRunReceipt@v2
  host attempt -> CioAskLifecycleReceipt@v1 summary -> canonical tracked-thread
  last_checked_at/last_check_outcome and last_answer_at -> memory_sync -> exact
  canonical Ask consumer_readback -> delivered/verified or typed not_required.
  Aggregate source_errors and failures stay visible. accepted/queued is not
  delivered. Missing/old schemas or attempts remain UNAVAILABLE. Dry-run
  RUN_DONE, exit0, historical ok_at and a file mtime never prove this chain.

Inputs: canonical data/cio/cio_ask_events.jsonl projection and
  data/runtime/cio-ask-lifecycle_last.json
  data/runtime/cio-ask-material-events_last.json
  data/runtime/lane_attempts/<lane>/<run_id sanitized by existing helper>.json
The summary can be top-level or LaneRunReceipt@v2.summary. The immutable attempt
must carry the same summary, lane_id, run_id, live mode, status ok and exit0.
A bounded 32-copy history per lane retains a material thread check when a later
no-event poll replaces the latest receipt; latest schedule freshness is checked
independently.
The collector invokes no model, DB, provider, sender, executor or writer.

Freshness: next hourly evidence check may be at most fifteen minutes late.
An artificially distant next_check_at cannot mask last_checked_at+one hour.
Material polling older than fifteen minutes warns independently. Memory pending,
consumer readback pending and delivery pending are independent conditions.
Untracked threads owe no checks; an expired monitoring_active flag cannot hide
a still-tracked thread. the real live receipts still
must exist. CI with no explicit fixture root returns UNAVAILABLE and never opens
a host store.

Actual health registration: scripts/lib/research_lane_health.py collect_report
calls collect_cio_ask_lifecycle_health beside the CIO Hermes collector and folds
its lane into firing/ok. That existing report feeds health_agent's research
heartbeat. The executor-binding regression validates both proposed entries against an
injected route registry, binds the full set using the actual executor helper,
and verifies bridge admission for all four IDs and refusal outside the set.
The integration regression invokes the DEFAULT registered collector
with synthetic readers, proving registration instead of merely testing a helper.
A separate standalone CLI prints the same read-only projection; --strict exits3
for a finding, not CPython crash1.

Verification (no live services):
  TRADE_AI_CI=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \
    tests/test_cio_ask_lifecycle_health_20261026.py tests/test_research_lane_health.py
  python3 scripts/cio_ask_lifecycle_health.py --root <empty-fixture-root> \
    --now 2026-10-26T17:10:00Z --dry-run --strict
  Expected empty fixture: UNAVAILABLE / evidence_read_failed, exit3, no writes.

Coordinator handoff:
1. Integrate engine summary and immutable v2 output contract; rerun health tests
   with the engine's actual enum/ref shapes. Preserve automation process identity.
2. Have shared-config owners reconcile packet rows and admit the automated
   bridge route, Ask writer authority and material reader/cursor inventory.
3. Review contracts with real reviewer/date, then stage shadow without cron.
   Validate native workflow metadata/admission and dry-run write-free behavior.
4. After bounded canaries and approved activation, retain run/attempt/ledger
   evidence for one first natural hourly slot and one material slot. Confirm
   per-thread checks, memory, consumer readback and delivery, including cooldown,
   a no-change case, a pending-memory case and an unavailable source.
5. Only coordinator can settle the full task against that evidence. This worker
   commits local implementation and proposal artifacts; no push/merge/release.
