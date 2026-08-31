# Master Test Plan — Schwab Broker Integration (dormant phase)

Status:      ACTIVE
as_of:       2026-06-11T18:20:34-04:00
Measured at: efcc51365 / not measured

**Audience:** external developer review · **Status:** Levels 1–2 automated & passing; Level 3 awaiting
operator approval; Level 4 gated · **Last run evidence:** 46/46 scaffold tests, 30/30 translation review,
validator 12/12.

---

## 0. System under test & the core problem

We are building Schwab order support that is **implemented but dormant**. Schwab offers **no sandbox or
paper environment for individual accounts** — the API touches only the real account, and thinkorswim
paperMoney is invisible to the API. Therefore everything is verified in three tiers:

| Tier | What it proves | How |
|---|---|---|
| Schema (VERIFIED-SDK) | our payloads match the official SDK's order schema | static, from the installed schwab-py enums/builders |
| Translation (Level 1–2 below) | our canonical model converts deterministically and correctly to those payloads | automated tests, zero network |
| Runtime (Level 3–4 below) | Schwab's LIVE system actually accepts/represents/handles those structures | shadow observation of manual orders; later gated micro-canaries |

**The thing we can never assume:** that schema == runtime. Every runtime behavior is tagged `UNVERIFIED`
until Level 3/4 observes it.

## 1. Safety invariants (must hold in EVERY test, asserted continuously)

| # | Invariant | Enforced by | Verified by |
|---|---|---|---|
| S1 | No code path can call a Schwab order endpoint | transport `NotProvenWrite` fence; translators are pure (no I/O); adapter stub raises unconditionally | `validate_schwab_no_writes.py` (12 guards, incl. runtime raise-check + import-boundary scan); scaffold test §7, §9 |
| S2 | Execution guard fails closed | unknown broker/config/capability ⇒ BLOCKED | scaffold tests §5–6 (`env flag alone cannot unlock live`) |
| S3 | Alpaca paper training is never re-pointable to Schwab | disjoint ExecutionMode enum values, disjoint adapters | scaffold test §6 + code review (no shared registry path) |
| S4 | Future live submission requires per-trade 2FA (web AND telegram), single-use, TTL'd | approval_service, guard 4th lock | scaffold tests §10 (12 assertions) |
| S5 | Every action attempt is audited with a reason | `intent_state_events` written on every guard decision | scaffold test §8; visible in CC → Trading → Broker Orders → Safety log |
| S6 | No trade record may exist ahead of broker truth | intent state machine: BLOCKED terminal-with-reason; FILLED only via broker ack | design (ADR-B2); regression class proven by the ATOS phantom fix |

## 2. Level 1 — Scaffold unit tests (automated, no network)

**File:** `tests/test_broker_scaffold.py` · **Run:** `.venv/bin/python tests/test_broker_scaffold.py` ·
**Current:** 46/46.

| Section | Asserts |
|---|---|
| §1 Canonical validation (8) | stop/entry/target ordering per direction; exactly-one quantity basis; target % sums to 100; ladder ≥2 legs + % sum; trailing offset>0; options ⇒ BLOCKED_CAPABILITY |
| §2 Serde (1) | to_dict → JSON → from_dict round-trip equality (incl. ladders, trailing) |
| §3 Schwab translation (10) | bracket ⇒ TRIGGER→child-OCO{LIMIT,STOP}; native TRAILING_STOP carries basis/type/offset; SHORT ⇒ SELL_SHORT/BUY_TO_COVER; ladder expands N orders w/ qty split + "coordinated by US" note; multi-target carries UNVERIFIED flag |
| §4 Alpaca parity (2) | canonical bracket ⇒ exact `order_class=bracket` shape our paper pipeline uses; trailing ⇒ explicit DEGRADED note |
| §5 Capability registry (4) | per-broker native/composed/degraded/blocked; unknown capability AND unknown broker fail closed |
| §6 Execution guard (4) | Schwab submit BLOCKED by default; `require()` raises; Alpaca PAPER_TRAINING allowed; env flag alone cannot unlock LIVE |
| §7 Adapter stub (3) | submit/replace/cancel raise `ExecutionBlocked` unconditionally |
| §8 Audit (2) | intent persisted + loadable; guard + state events recorded |
| §9 Boundary (1) | no schwab-py import anywhere in `scripts/brokers/`; transport only in the adapter (reads); no write-call syntax |
| §10 2FA lifecycle (12) | both channels created; zero/one confirmation insufficient; wrong telegram code rejected; both ⇒ fully approved; re-confirm blocked (single-use); consume; expiry rejected |

## 3. Level 2 — Translation review (automated, repeatable, "Stage 1")

**File:** `scripts/brokers/translation_review.py` · **Output:** `docs/brokers/stage1-translation-review-log.md`
· **Current:** 30/30 CLEAN · Fixtures use **qty=2 (canary size)** and real recent symbols/prices
(geometry-sanitized), each labeled "Stage-1 translation fixture: <case>".

**Hypothesis per case family:** "for intent shape X, the translator emits exactly the Schwab payload an
expert would hand-write." Field-level assertions: order/strategy types, leg instructions, prices in correct
fields, durations/sessions, trailing parameters, child-graph shape, qty conservation across ladders/splits,
UNVERIFIED flags present where runtime is unproven, and the 3 negative cases (bad geometry REJECTED,
options BLOCKED, notional BLOCKED). Guard must grant **0** executions across all 30.

## 4. Level 3 — Stage 2a shadow validation (manual orders + read-only API; AWAITING OPERATOR APPROVAL)

**Doc:** `stage2a-canary-protocol.md` · **Cost:** ≈$0 for orders 1–6 (far-from-market, cancelled); one
attended ~$16 fill for orders 7–9 · **Instrument:** ITUB (live-screened: $7.91, $0.02 spread, zero system
footprint) · **API surface used: READ-ONLY.** Operator places orders **manually in thinkorswim**.

| Order | Hypothesis being tested | Pass criterion | Resolves UNVERIFIED # |
|---|---|---|---|
| 1 far LIMIT + cancel | Schwab's order-response JSON matches translator-predicted field names/nesting; status lifecycle enum captured | reconciliation diff = ∅ (modulo documented renames) | response-shape baseline |
| 2 GTC + PM session | duration/session round-trip faithfully | read-back shows GOOD_TILL_CANCEL/PM | #8 |
| 3 OTOCO far + cancel | TRIGGER→OCO accepted & represented as SDK schema implies; parent-cancel cancels children | children visible in read-back; all states CANCELED after one cancel | #1 (partial), #3 (cancel semantics) |
| 4 OTOCO w/ TRAILING_STOP + cancel | trailing fields (basis/type/offset) accepted & echoed | read-back carries the 3 fields | trailing runtime |
| 5 multi-target OCO on live position | Schwab accepts OCO of 2 limits with qty split 1/1 | both children WORKING | #1 |
| 6 modify in ToS | how a replace is represented (new ID? amended?) | order-ID continuity documented | #2 (read side) |
| 7 marketable 2-sh fill | fill event payloads (status, ACCT_ACTIVITY message shape) | fill captured by stream + poll | #6 |
| 8 OCO exits on live position | children activate against a real position | exits WORKING, one cancels other on close | #3 |
| 9 close + ingestion | round trip flows into schwab_round_trips with canary tag, excluded from stats | journal shows tagged row; analytics unchanged | ingestion path |

**Pre-session requirements (built before the session is approved to run):** canary_symbols analytics
exclusion · shadow-reconciliation harness (auto-diff read-back vs translator expectation every 30s) ·
ACCT_ACTIVITY read-only capture · all watched live in CC → Broker Orders.

## 5. Level 4 — Stage 2b micro-canary (API writes; SEPARATELY GATED, not approved)

Only for what Level 3 cannot observe: API-side `replace_order` semantics (#2), `priceLink*` on submission
(#7), API reject taxonomy (#9 — intentionally malformed orders). Protocol: attended; far-from-market LIMIT
qty=1 on <$10 stock; ACK→read-back→CANCEL; one at a time. **Gate:** signed `broker_live_approvals` record +
validator extended with canary-mode assertions FIRST + 2FA per order.

## 6. UI / 2FA acceptance tests (manual, CC → Trading → Broker Orders)

1. Open a draft → details → **edit modal**: change qty/prices → Re-preview → translation updates + validation
   errors surface inline. 2. Request approval → Telegram arrives in proposals chat with ✅/❌ buttons.
3. Confirm web only ⇒ status shows 1/2, NOT fully approved. 4. Tap Telegram ✅ ⇒ fully approved badge;
   execution still shows BLOCKED (correct). 5. Wait 10 min ⇒ expired. 6. Re-use ⇒ rejected.

## 7. Traceability: UNVERIFIED register ↔ resolving test

#1 multi-target → L3-5 · #2 replace → L3-6 (read) + L4 (API) · #3 TRIGGER children → L3-3/8 · #4 fractional
→ official docs only · #5 rate limits → L3 traffic observation · #6 ACCT_ACTIVITY → L3-7 · #7 priceLink →
L4 · #8 sessions → L3-2 · #9 reject taxonomy → L4 · #10 options → out of scope.

## 8. Entry/exit criteria

| Stage | Enter when | Exit when |
|---|---|---|
| L1/L2 | always (CI-able) | any failure = stop ship |
| L3 | operator approves the session plan | 9/9 reconciled, log published, UNVERIFIED register updated |
| L4 | signed approval + validator extension | listed items resolved or explicitly waived |

## 9. Known limitations / risks for reviewer attention

True partial fills are unforceable on a liquid canary (documented best-effort) · paperMoney is structure-only
evidence, never fill-behavior · 7-day OAuth cycle means any Level-3/4 session must start with a fresh token ·
the reconciliation harness (L3 prerequisite) is designed but not yet built — it is the next build item before
any session is scheduled.
