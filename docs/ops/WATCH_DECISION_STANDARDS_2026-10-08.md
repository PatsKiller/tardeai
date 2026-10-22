# Watch decision standards — the Communications standards on the Watchlist (2026-10-08)

Operator 2026-10-07, after the Communications hub shipped: "watchlist etc". The Command Center standards apply to
the Watchlist. Every item carries a category, a priority, a confidence score, a TTL with an expiry timestamp, a
status and an actionability indicator. Items are sortable by priority, confidence, risk, reward and time
sensitivity, and the page answers the six at-a-glance questions.

## Where it lives

| Piece | File |
|---|---|
| Rules, TTLs, thresholds | `config/watch_decision_standards.yaml` |
| Computation (read-only, zero provider calls) | `scripts/lib/data_broker/watch_decision.py` |
| Projection wiring | `scripts/lib/data_broker/watch_intelligence.py` → `/api/v3/data-broker/watch-intelligence` (`card.decision`, `decision_board`, view `expired`, decision filters and sorts) |
| UI | `apps/command-center-v3/src/components/watch/WatchDecisionParts.tsx` on `/watch` → Intelligence (`WatchIntelligenceUnified.tsx`) |
| Tests / gate | `tests/test_watch_decision_standards_20261008.py`, gate `watch_decision_standards_20261008` |

## Inputs

Batched once per request: the latest `watchlist_entry_plans` row, `watchlist_strategy_cards`, the latest
non-superseded `watchlist_final_synthesis`, `symbol_profiles.next_earnings_date`, and the deterministic re-entry
desk (`lib/data_broker/reentry_decision_desk.build_decision_desk`, cached 120 s). The card itself supplies the
quote, near-trigger, street upside, Trade AI state, proposal eligibility and review times.

## Rules (first match wins)

| Rule | Category | Base priority | Actionable |
|---|---|---|---|
| held + synthesis SELL / TRIM / AVOID | Risk | high | yes |
| held + Trade AI AVOID / BLOCKED / FAIL | Risk | high | yes |
| re-entry desk READY TO REVIEW | Re-Entry (confirmed) | high | yes |
| re-entry desk NEAR ENTRY | Re-Entry (potential) | medium | yes |
| re-entry desk WAIT / OVERBOUGHT / MISSING | Re-Entry (opportunity) | low | no |
| proposal allowed | High Conviction Opportunity | high | yes |
| ready plan, in zone, confidence ≥ 0.6, R:R ≥ 2 | High Conviction Opportunity | high | yes |
| ready plan | Reward | medium | yes |
| near trigger | Reward | medium | yes |
| near-entry plan | Reward | low | no |
| held, nothing negative | Held Position | low | no |
| anything else | Watchlist Candidate | low | no |

Scores (0..1):
- **Confidence:** planner → strategy card → synthesis → 0.3.
- **Reward:** R:R ÷ 6, or street upside ÷ 30%.
- **Risk:** stop distance ÷ 15%, raised for held-and-negative, earnings within 7 days, a blocked state, or a stated risk.
- **Time sensitivity:** 1.0 in zone, READY or proposal; otherwise from distance to the trigger, plan urgency and earnings.

`priority_score = 100 × (0.35·time + 0.25·max(risk, reward) + 0.20·confidence + 0.20·tier)` is the same formula
as Communications. The label never falls below the rule's base priority and rises at most one tier above it.

## TTL and status

- TTL: 96 h for Re-Entry, Risk, Reward and High Conviction; 168 h for Watchlist Candidate and Held Position. It
  counts from the newest evidence: a fresh entry plan (≤ 7 d), a synthesis (≤ 14 d), a completed review, or, for
  re-entry, the desk's quote time (the desk recomputes, so new data reaffirms it).
- **active:** evidence inside the TTL.
- **needs_data:** no evidence at all (shown, flagged "needs fresh analysis").
- **expired:** past the TTL.
- **invalidated:** a non-held idea the CIO synthesis marked AVOID / IGNORE / SELL, or Trade AI AVOID / BLOCKED / FAIL.
- **What expires is the signal, never the membership.** Expired and invalidated items leave the active views and
  appear under view `expired`. Nothing is deleted, and removing a name stays an operator action
  (`watchlist_hygiene.py` keeps its own weekly rules).
- **Held positions never leave the views.** A held name with an old signal shows "signal expired — review".
- **A search always finds the name,** with its status badge.

## Measured on live data (2026-10-08 ~03:30Z, view `all`, 188 symbols)

- **Live and actionable:** 141 live, 7 actionable.
- **Status:** 16 active, 122 needs fresh analysis, 3 expired, 50 invalidated.
- **Top Ideas:** unchanged at 21, mostly held positions.
- **Response time:** about 3.6 s, against a 3.2 s baseline.

122 of 188 symbols having no plan, synthesis or review inside the window is the main finding. The pipeline is not
producing evidence for most of the watchlist. The page now says so instead of showing every name as equally live.

## Accuracy fixes (2026-10-22 Watch audit)

A read-only audit of the Watch page found nine defects. Each is fixed and has a test in
`tests/test_watch_accuracy_20261022.py` (gate `watch_accuracy_20261022`).

| # | Defect | Fix |
|---|---|---|
| 1 | Held names (RTX, NVDA, CSWC, LDOS, BAH) got "High conviction / Review entry" while Trade AI said MANAGING | Every entry rule (`proposal_ready`, `plan_ready_strong`, `plan_ready`, `near_trigger`, `plan_near`) now has `held: false`. A held name falls through to `held_watch` (Held Position, manage lane). The decision carries `lane: manage \| entry`. |
| 2 | FATN and AXTI showed "actionable / Set a re-entry alert" while Trade AI said DETERMINISTIC_FAIL / NO TRADE ACTION | `non_actionable_trade_states: [DETERMINISTIC_FAIL, BLOCKED, AVOID]`. A non-held idea in one of these states is never actionable, whatever rule matched. `actionable_blocked_by` names the state. Held risk reviews (`held_blocked`) are unchanged. |
| 3 | Held came from three readers. `membership_held` asked `portfolio_snapshot` for a `holdings` key that projection never has, so it fell back to holdings.json on every call. Three delisted CUSIP rows made Held 23 against 20 held cards. | `watch_domains.held_positions()` is now the one reader. `membership_held`, `watchlist_intelligence._held_set` and `rockville.live_projection` all use it. It returns an explicit freshness verdict (`source`, `as_of`, `age_s`, `stale`). It resolves CUSIP rows through the identity registry; a CUSIP with no ticker in the registry is reported in `unresolved` and never counted as a held card. The payload has `counts.held_cards`, `counts.held_unresolved` and `source_status.held`. |
| 4 | DT showed MANAGING from a 2026-10-11 packet after the position was gone | Current holdings decide ownership (`project_watch_decision(current_held=…)`). A packet's own ownership flag counts only when holdings cannot be read, and only while the packet is inside its TTL (`freshness.valid_until`, else `generated_at` + 12 h). The decision carries `packet_freshness`. |
| 5 | "live" counted held names whose signal had expired, and the counts mixed scopes | `is_live()` means status active or needs_data. `in_view()` is live plus every held name, so expired held names stay listed but are not counted live. Every count declares its scope: `counts.scopes`, `count_scopes`, `scope_definitions`, `decision_board.panels[*].scope` and `facets_scope`. The scopes are `page`, `matched`, `live`, `view` and `all`. `facets_live` sits next to `facets` (scope all). The UI prints the scope under each number. |
| 6 | "Highest reward" counted expired and needs-data cards | The reward panel counts only `status == active`. |
| 7 | The Re-entry tile counted 3 watch names while the re-entry desk had 1 READY + 15 NEAR of 92 rows | The tile is labelled "Re-entry (watch names)" and carries `desk: {ready, near, rows}` from `reentry_desk_counts()`, printed under the number. |
| 8 | POST `/api/v2/pullback-macd/dismiss` was registered twice in `scripts/api_v2.py` | The unreachable second registration was removed. The first (200/400) handles every call, so behaviour is unchanged. A test fails on any exact duplicate route line. |
| 9 | WAIT cards said "SET CONDITION ALERT" with no button | The Watch cards and the symbol page now have a SET CONDITION ALERT button. It opens the Re-Entry pages' `ReEntryAlertArmModal`, which POSTs to `/api/v2/watch/alerts`, with the note tagged `watch-condition`. It is advisory only and never places an order. |

**The positions_current switch is an operator grant.** `held.positions_store_reader` in
`config/watch_decision_standards.yaml` shipped `false` in #1926. The registry (`config/data_source_authority.json`, domain
`positions_store`) says the store has no reader until the operator approves a phase-3 reader batch (AGENTS.md
§7A, §17). With the switch on, a fresh `positions_current` wins. Fresh means the `positions_sync` contract: 30 min
in session, 72 h when closed. A stale store falls back to holdings.json with `fallback_reason`.

**Granted 2026-10-22: positions reader batch #1 = the Watch held flag.** The operator's reply, verbatim, to the
recommendation "Use the broker-synced store for 'held' on Watch: Watch becomes positions batch #1 … Recommend: yes"
was "I take your recommendations on above." Branch `feat/positions-reader-batch1-watch-held-20261022`:

- `held.positions_store_reader: true` and `held.positions_store_reader_surfaces: [watch]`. Only a caller that passes
  `surface="watch"` (`WATCH_SURFACE`) reads the store: `watch_intelligence`, `watchlist_intelligence._held_set` and
  `rockville.live_projection.current_held_set`. Other `membership_held()` callers (advice digest, opportunity) pass no
  surface and still read holdings.json. Adding them is a later batch. A missing surface list reads nothing.
- Only the held flag comes from the store, meaning the set of symbols with qty > 0. Qty, basis and value on Watch
  still come from their existing readers.
- Freshness guard, unchanged from #1926: if the store is stale, empty or unreadable, holdings.json serves and
  `fallback_reason` says why (`positions_store_stale`, `positions_store_empty` or
  `positions_store_error:<type>`). If neither source can be read, `source` is `unavailable` and `stale` is true.
  The verdict reaches the payload through `held_detail_public` (`source_status.held`).
- The registry row `positions_store` now carries `approved_readers[batch 1]` with the operator's approval, and a
  `reader_gate`. `check_data_source_authority.py` fails `UNAPPROVED_READER` if any other file under scripts/ reads
  `positions_current`, `position_lots`, `realized_lots` or `position_snapshots`. Exempt are the writer, an approved
  reader and the two measured pre-batch readers. The first is `positions_proof_daily.py`, the phase-2 grader. The
  second is `stop_health_check.py`, which has read positions_current since 2026-10-06 with no batch approval; it is
  reported, not approved. The gate fails `READER_GRANT_INVALID` if a grant is incomplete or stale.
- Tests: `tests/test_positions_reader_batch1_20261022.py` (gate `positions_reader_batch1_20261022`).

A read-only check on 2026-10-22 ~11:50 ET found the two sources agree. `positions_current` was fresh at 11.5 min
old. It held the same 20 names as holdings.json, with the same 3 unresolved CUSIPs.

**Measured, not changed:** 1,794 of 1,841 live decision packets are past their TTL. This PR stops a stale packet
from setting **ownership**. It does not turn every past-TTL packet into STALE, because that would relabel about 97%
of the Watch cards at once. That decision is the operator's (see the PR).
