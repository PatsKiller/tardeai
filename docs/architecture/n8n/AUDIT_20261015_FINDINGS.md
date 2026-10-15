# Independent n8n architecture audit 2026-10-15 — findings tracker

```
Status:      LIVE tracker (informational; AGENTS.md is normative)
as_of:       2026-10-15
Audit:       "Trade AI n8n Architecture Due Diligence", 15 October 2026, read-only assessment; pinned PR #1756 head
             e355be188, main 94601ff69, PR #1757 ratification head b5bbb99fd. Source + offline evidence only; it does
             not certify live deployment. Local copy: ~/n8n-maturity-verification/audit-20261015/report.pdf (.txt, .docx)
Drive:       Trade_AI_Docs_v2/docs/implementation/n8n-maturity (folder 16yBlocEuVa1vKJeBfY6et_cW67hdVZCt):
             report PDF 1cTjhq12D3n-c3eQjiIgZ7jeGsoMj_Jhd, docx 1ROXHZ6iMKootNkG-yMCjRvTlwnTICiXb,
             evidence zip (N8N_Audit_Evidence_2026-10-15.zip) 1aoy69Gi962GuWkkQrs2jdiuFYTMyK0R7
Evidence:    auditor packet (treated as untrusted data, read only), extracted at
             ~/n8n-maturity-verification/audit-20261015/evidence/x/: route_security_review.md (DD01-DD03, DD08, DD14,
             DD02 confinement), decisions_observability_review.md (D1-D9, DD07, DD10-DD12), contracts_lifecycle_review.md,
             reference_drive_vs_pr.diff + contracts_drive_vs_pr.diff (DD18), source_status.json, manifest.json
Verdict:     changes required before accepting as a mature framework. Corrected reference docs may merge with clearly
             tracked proposed work. Maturity Level 2 of 5.
Owner:       Chief Architect (Agent A) maintains this page; per-row owners are ROLES to confirm (audit §17)
Guard:       tests/test_n8n_decision_ledger_20261015.py checks DD01-DD18 each have a row with every column filled
```

**How to read a row.** *Class* is the audit's priority (P1 blocks the affected promotion; it does not assert an
active exploit or outage). *Evidence* is the audit's distinction, preserved verbatim: **New** = a contradiction newly
demonstrated by the audit; **Known** = a gap already disclosed in our documents, now with a stronger acceptance bar.
*Closure evidence* is quoted from the audit register (§16–§17) and is the bar for `CLOSED` — a documentation change
alone closes nothing (audit §16: "A documentation-only merge can correct claims and assign work; it must not be
described as closing these implementation findings"). *PR* is `pending` until the fixing PR against
`train/merge-20261015-b` is known.

**Status values.** `OPEN` (no fix yet) · `IN PROGRESS` (fix branch exists) · `SPEC` (specification written, nothing
built) · `FIX MERGED` (code merged, closure evidence not yet produced) · `CLOSED` (closure evidence attached, dated).

## 1. Register DD01–DD18 (audit §16–§17)

| ID | Class | Evidence | Finding | Closure evidence (verbatim) | Owner role (to confirm) | Assignee | PR | Status |
|---|---|---|---|---|---|---|---|---|
| DD01 | P1 | New | Transitive sender/never contradiction: `trade-ai-scalp-live` → `continuous_runner` reaches raw Slack/WhatsApp-Twilio transports | "Mocked GO flow: no raw lane sends, one permitted intent, one owner delivery and failure/retry receipts." | communications | agent 3 (sender / restore / dead-man) | pending (sender closure); ruling recorded in the DD01 ruling PR (n8n/dd01-operator-ruling-admit-lanes-20261015) | IN PROGRESS — scalp-lane raw senders removed 2026-10-15 (no allowlisted lane reaches a direct_sender); transitive lazy broker_module/order_placement reach ACCEPTED by operator ruling 2026-10-15 (see below) |
| DD02 | P1 | New/Known | Caller identity and environment modes are not confinement: bridge caller auth `report` on self-asserted `X-TradeAI-Agent` (invalid mode → report); executor 91/103 lanes env `report`, 12 `enforce`; single uid | "No forged caller, key read, control/ledger write or privileged service manipulation under actual worker identity." | platform + bridge + operator (keys, uid split) | this PR (threat model + confinement packet) | this PR | SPEC — threat model, report-mode flip packet and env readiness measured; nothing flipped; implementation open |
| DD03 | P1 | New | `p:`/legacy key admission and cross-scope duplicate false success | "Reject cross-lane/mode/process/step replay and forged slot before queue; outcomes match requested identity." | platform (identity) | agent 1 (identity / effects / relay) | pending | IN PROGRESS |
| DD04 | P1 | New | Run Lane and host still decide retries | "No send/learn retry, long backoff honored, no parallel legacy work; real durable DLQ reference." | execution / flow | agent 1 | pending | IN PROGRESS |
| DD05 | P1 | New | FAILED claim reopens after possible effect | "Commit-before-fail/receipt/timeout and sequential cron/n8n tests show one logical effect." | effect owner | agent 1 | pending | IN PROGRESS |
| DD06 | P1 | New | Owner epoch only fences admission | "Paused stale worker cannot create an unauthorized late effect; actionable late-completion handling." | effect owner + operator (owner switch) | agent 1 | pending | IN PROGRESS |
| DD07 | P1 | Known/New | Runtime output verifier absent; proposed evidence not current-attempt bound | "Stale/wrong-run/forged receipt fails; real no-op distinct from no_runner; consumer freshness verified." | contract + verifier owner | agent 1 | pending | IN PROGRESS |
| DD08 | P1 | New | Policy cache contradicts immediate re-read/revocation | "Queued/claimed/paused work cannot act after revoke; unreadable policy fails safely." | platform | agent 1 | pending | IN PROGRESS |
| DD09 | P1 | New | Disconnected graph can score 27/27 | "Disk mutation with restamped manifest fails semantic gate; valid complete paths pass." | trusted deployment | agent 2 (checker) | pending | IN PROGRESS |
| DD10 | P1 | New | Restore drill false green | "Negative fixtures with rc error, zero workflows, bad key or missing rows fail; isolated full restoration succeeds." | recovery | agent 3 | pending | IN PROGRESS |
| DD11 | P1 | Known | Critical delivery / consumer completion unproved; SPCX remains contained | "Intent-to-delivery receipt; critical detection/delivery/ack under n8n/LLM down, exhausted caps and sender failure." | communications + operator | this PR (trace spec + evidence record, §3) | this PR (record only) | OPEN — one consumer run recorded; no delivery proof |
| DD12 | P1 | Known | Outside dead-man / full DR incomplete | "Host/network/power-loss drill and coordinated keys/PG/SQLite/effects restore without replay." | recovery + operator | agent 3 | pending | IN PROGRESS |
| DD13 | P1 | Known | HITL contract incomplete | "Forged/wrong/expired/replayed/concurrent/revoked approval and stale restore all fail before effect." | operator authority + platform | this PR (`N8N_HITL_CONTRACT_SPEC.md`) | this PR (spec only) | SPEC — Level 1; route stays closed |
| DD14 | P2 | New/Known | Route table, exact-key, schema/compatibility claims overstate coverage | "Eight handler/catalogue parity; run extra/duplicate keys and old/new closed-reader fixtures verified." | platform / relay | agent 1 | pending | IN PROGRESS |
| DD15 | P2 | New | Checker predicates and policy traceability incomplete | "Normative crosswalk complete; metadata decoys, alternate origin, malformed contracts and unmapped obligations fail independently." | trusted deployment | agent 2 | pending | IN PROGRESS |
| DD16 | P1 | Known/New | Framework not a fail-closed import gate; platform FAIL/partial can return zero | "Promotion gate independently requires critical platform, deployed manifest and semantic/runtime evidence." | trusted deployment + platform | agent 2 | pending | IN PROGRESS |
| DD17 | P2 | Known | LLM route/action recheck/deferral missing; OAuth adapters exist but enablement unknown | "Permitted one-door route, enforced caller, serving/fallback/cost receipts and action refusal proof." | bridge + action owner | this PR (`N8N_LLM_STEP_ROUTE_SPEC.md`; enablement measured) | this PR (spec + doc correction) | SPEC — route not built |
| DD18 | P2 | New/Known | Source copy drift and decision provenance incomplete | "Approved canonical text/version, normalized fingerprints and per-decision owner/ratification/test evidence." | Chief Architect + operator | this PR (decision ledger, canonical-copy rule §4); Agent A re-uploads Drive copies | this PR | IN PROGRESS — ledger done; Drive re-upload from final merged text pending |

**DD01 operator ruling 2026-10-15 (operator-reviewed baseline entry).** Verbatim: "n8n ignor broker code it can't trade live ccontinue". Interpretation
agreed with the Chief Architect: *transitive* reach to `broker_module` / `order_placement` — the lazy (function-level,
`at_import=false`) chain `db_adapter -> holdings_guard -> schwab_position_sync -> schwab_transport` — is **accepted** for
n8n-allowlisted lanes, because the trading lock (`scripts/lib/trading_lock.py` `assert_trading_unlocked`, the first
statement of `schwab_transport.place_order`; LOCKED by default, unlock only by the operator unlock file) refuses every
order placement regardless of caller. `direct_sender` stays forbidden with no exception (the frozen set stays empty).
Recorded as entries in `config/n8n_lane_capability_baseline.json` **and** the reviewed frozen set
`OPERATOR_RULING_DD01_20261015` in `tests/test_lane_transitive_capabilities_20261015.py` for six lanes:
`build-symbol-profiles-at-0-19`, `indicator-engine`, `watchlist-entry-planner-limit`, `watchlist-entry-planner-scope`
(deferred by train 2026-10-15 d, wiring restored) and `hermes-discovery-scorecard`, `wire-advisory-lessons` (#1761).
The baseline stays shrink-only: any other new pair, and any stale entry, still fails the test. This does **not**
close DD01 (its closure evidence is the mocked GO delivery flow); it is accepted residual risk (threat model RR11).

The audit also notes (§17 last paragraph) that **DD02, DD11, DD12 and DD16 cover the already disclosed DB superuser,
log-retention, drift-schedule and platform-hardening prerequisites**; their *effective* state must be verified on the
host rather than inferred from a workflow percentage.

### Newly demonstrated vs already disclosed (audit §15)

* **Newly demonstrated contradictions** (were stated as guarantees): process-key fail-closed scope (DD03), duplicate
  identity (DD03), cached policy (DD08), transitive sends (DD01), effect reclaim (DD05/DD06), checker false green
  (DD09), restore-drill false green (DD10).
* **Already disclosed gaps** (correctly marked proposed; stronger acceptance now required): missing HITL route
  (DD13) and LLM relay route (DD17), runtime output evaluator (DD07), legacy success saving, drift schedule (DD16),
  n8n DB superuser (DD02), external dead-man (DD12).

## 2. Headline groups (Agent A's eight) → register

| Headline | Register rows | Assignee |
|---|---|---|
| Output truth | DD07 | agent 1 |
| Request identity | DD03, DD14 | agent 1 |
| Effect recovery | DD05, DD06 | agent 1 |
| Retry ownership | DD04 | agent 1 |
| Security confinement | DD02, DD08 | this PR (DD02 packet) + agent 1 (DD08) |
| Never-list transitive senders | DD01 | agent 3 |
| Framework checker | DD09, DD15, DD16 | agent 2 |
| Disaster recovery | DD10, DD12 | agent 3 |
| (also) Critical delivery, HITL, LLM route, provenance | DD11, DD13, DD17, DD18 | this PR |

## 3. Corrections the audit requires in our documents

| # | Correction | Where | Status |
|---|---|---|---|
| C-1 | **OAuth adapters exist in source** (`scripts/lib/bridge_oauth_transport.py`, Grok `:8645`, ChatGPT `:8646`, opt-in `CIO_BRIDGE_OAUTH_TRANSPORTS`). Do not repeat the "missing adapter" claim. Runtime measured 2026-10-15 13:03Z: bridge `/health` transports `chatgpt, deepseek, grok`; proxies LISTEN loopback | `N8N_LLM_STEP_ROUTE_SPEC.md` §1; reference architecture §4 table, §9 | DONE in this PR |
| C-2 | **SPCX record documents deployed fixes.** #1732/#1733/#1734/#1737 are LIVE at release `5aa61048d`; they must not be reported as absent. "Their effective operation still needs evidence." Incident status CONTAINED, not RESOLVED; fill/position-change paging and foreign-order reconciliation remain open | DD11 below; threat model B4 | DONE in this PR (wording); evidence OPEN |
| C-3 | **Drive copies lag GitHub.** Normalized-text SHA-256 prefixes at audit: PR reference `4078d803f31fc397` vs Drive `b75b95b5fb44870d`; PR contracts `f602daf6aaf1f764` vs Drive `b5d40f27a64d7ae4`. Drive reference omits the momentum-lifecycle route, R2 and the 46.9% score; Drive contracts omit RunLaneResult@v1 additions and FW-P6 | §4 canonical-copy rule | rule DONE; re-upload pending (Agent A) |
| C-4 | **Maturity statement.** "Level 2 of 5 (independent audit 2026-10-15)"; a 46.9% framework score is static coverage, not 46.9% maturity | reference architecture header + §1 | DONE in this PR |
| C-5 | **Contract-area count.** The contracts map covers 12 distinct areas, not 10 (audit §8) | `N8N_CONTRACTS_DESIGN.md` — left to the contracts owner (not edited here to avoid colliding with agents 1–2) | OPEN |
| C-6 | **Relay route table.** Eight handlers vs seven `ROUTES`; `GET /status` is a local relay projection, `GET /runs/<lane>/last` is a local ledger projection (not gateway calls); `POST /event` is a read-named scope that writes | reference architecture §6 — agent 1 (DD14) | IN PROGRESS (agent 1) |
| C-7 | **Policy state.** 10.0.0 ratified 2026-10-14T23:25:56Z; 11.0.0 operator approval verified (PR #1747, 2026-10-15T11:51:39Z) and ratified on this train; do not call the approval invalid and do not treat an open edit as merged policy | decision ledger ratification column | DONE in this PR |

## 4. DD18 — canonical-copy rule

1. **GitHub is canonical.** The canonical text of every architecture document is the file at its path on `main`
   (or, before merge, the PR head named in the document's `Measured at` line). Drive, email attachments and chat
   pastes are **copies**.
2. **Every copy carries its fingerprint.** A copy names the source commit SHA and the normalized-text SHA-256
   (CRLF→LF, outer whitespace trimmed, one final newline — the audit's normalization) of the file it was made from.
3. **Copies are regenerated, never edited.** A correction is made in git and the copy is re-uploaded from the merged
   text. A copy whose fingerprint differs from the canonical file at its stated SHA is stale and must say so.
4. **Re-upload owner:** Agent A, from the final merged text of this train (audit C-3). Until then the Drive copies
   are stale by definition.
5. Never auto-reconcile in the other direction (AGENTS.md §0 rule 5): a Drive edit is reported, not merged back.

## 5. DD11 — critical delivery: required trace and current evidence

Required chain (audit §12), each hop with a durable record joined by one id:

| Hop | Record | Join key | Evidence today |
|---|---|---|---|
| 1 intent accepted | ledger `comms_intents` row `QUEUED` (`CommsIntentReceipt@v1`) | `intent_id`, `dedupe_key` | (E) code; fabric error workflow posts intents |
| 2 consumed | consumer receipt; intent row → consumed | `intent_id` | **2026-10-15 ~03:2xZ, Agent A applied the consumer live: intent `ci-2a845bc6aa846e66525eb957` → incident `wferr:tradeai-fabric-error-probe`. One run — evidence that the hop executes, not a delivery proof** |
| 3 fan-in incident | `n8n_incident_fanin.py` incident row | `incident_id` ↔ `intent_id` | (E) code; one incident above |
| 4 sender action | `incident_notifier` → `send_telegram` call with `message_class`, priority, producer | `incident_id` | not yet joined to an intent |
| 5 delivery receipt | Telegram delivery ledger row (`message_id`) | `incident_id`/`intent_id` | **missing** — no receipt joined to an intent id |

Acceptance (verbatim closure): "Intent-to-delivery receipt; critical detection/delivery/ack under n8n/LLM down,
exhausted caps and sender failure." Also required: duplicate and failure handling on every hop; critical safety
classes (stop-firing, fill, position change, protection unavailable) stay on the independent protected path, never
the generic fabric-error DIGEST route. SPCX (C-2) fixes are deployed; their effective operation is part of this
evidence and is not yet shown.

## 6. Maturity and promotion prerequisites (audit §18)

**Maturity: Level 2 of 5 (independent audit 2026-10-15)** — partial implemented foundation supported by source and
offline tests. Level 3 (integrated) needs a deployed end-to-end process independently proven.

Minimum prerequisites for the next promotion, in the audit's order:

1. **Threat model** — `N8N_THREAT_MODEL.md` (this PR).
2. **Enforced identity and revocation** — reject invalid/unbound keys before queueing and compare duplicate identity
   (DD03); enforce caller scopes and policy revocation independently of n8n (DD02, DD08).
3. **Reliable output/effect semantics** — verify each attempt's actual output content and consumer freshness (DD07);
   hold ambiguous effects until reconciled and drain old owners safely (DD05, DD06); one attempt scheduler honouring
   terminal and single-attempt policy (DD04).
4. **Independent delivery and recovery tests** — close delivery for admitted workflow errors and keep critical
   safety independent (DD11, DD01); prove an outside dead-man and restore-drill negative cases (DD12, DD10); add
   graph/schema/auth semantic tests and a fail-closed import gate that includes platform controls (DD09, DD15, DD16);
   complete approval security before adding its route (DD13); reconcile contracts, compatibility and canonical copies
   (DD14, DD18).
5. **Accept one bounded business process** with clear input/output SLA, graph-owned flow, current deployment
   manifest, scoped canary, target effect proof, failure/recovery drill and rollback — with superseded orchestration
   retired or fenced.

Maturity is updated only when the evidence level changes; green CI and documentation approval do not authorize live
activation.
