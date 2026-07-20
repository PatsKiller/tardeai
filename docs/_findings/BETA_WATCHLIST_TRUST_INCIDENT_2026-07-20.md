# BETA Watchlist Trust Incident — 2026-07-20

**Starting SHA:** `aa5e7ac117f335b4c279b9e902e6557edf176c78` · working tree clean
**Orders submitted during this investigation:** none · **2FA codes sent:** none
**BETA position:** 0 shares, $0 — never traded, in any account, ever

---

## 1. What the operator saw, and what was actually stored

The operator saw a card reading `IGNORE` on a stock up ~20% in a month and ~7%
that day, with no entry plan and a packet ~2.9 days stale, and asked whether the
system could be trusted. Three of the premises in that question turn out to be
wrong — and the real findings are worse than the ones suspected.

| Operator's premise | What the database says |
|---|---|
| "Grok and ChatGPT both endorse IGNORE" | **Only Grok answered.** `chatgpt_recommendation` is NULL |
| "✓ 2 models agree" | `models_agree` is **NULL** for BETA — the badge renders nothing |
| Stale packet is the main defect | The packet is stale, but the *label itself* is what blocked the fix |

The stored synthesis row:

```
recommendation          IGNORE            confidence  0.45
grok_recommendation     IGNORE            chatgpt_recommendation  NULL
models_agree            NULL
dual_consensus_json     {"grok": {...}, "chatgpt": null, "agree": null,
                         "consensus": "IGNORE"}          <-- consensus of ONE
updated_at              2026-07-20 13:16:30
research_expires_at     2026-04-30 12:16:31   <-- expired 81 days ago
decision_safety         unsafe    actionable  false    human_review_required  true
```

`"consensus": "IGNORE"` was written with one lane present and the other null.
This is rare — 2 rows in 3,088 — but it is a real defect: a consensus of one is
not a consensus, and nothing in the write path required a second opinion to
exist before naming the result one.

## 2. The primary defect: the label starves the analysis that would correct it

`watchlist_entry_planner.py:300` and `:360` gate plan generation on the label:

```sql
WHERE UPPER(rc.latest_recommendation) IN ('BUY','STRONG_BUY','ADD','ADD_ON_PULLBACK')
   OR UPPER(fs.recommendation)        IN ('BUY','STRONG_BUY','ADD','ADD_ON_PULLBACK')
```

A symbol labelled `IGNORE` can never receive an entry plan. The card then reports
"no entry plan", which reads as further evidence against the symbol. The label
produces the absence, and the absence corroborates the label.

BETA has been on the watchlist since **2026-04-29 — 82 days** — and
`watchlist_entry_plans` has **zero BETA rows**, ever.

This is not specific to BETA. Plan coverage across the live watchlist:

| label | symbols | with plan | rate |
|---|---:|---:|---:|
| BUY | 280 | 269 | **96%** |
| ADD_ON_PULLBACK | 242 | 233 | **96%** |
| ADD | 105 | 95 | **90%** |
| AVOID | 1,647 | 548 | 33% |
| IGNORE | 1,229 | 363 | 30% |
| HOLD | 1,180 | 370 | 31% |
| RESEARCH_MORE | 246 | 5 | 2% |
| (no label) | 159 | 0 | 0% |

**4,591 symbols are label-locked out of planning.** The 30-33% residue on the
avoid-side is stale plans left over from when those names were rated buy-side —
which is why the cliff is a step, not a slope.

The one-word label is therefore not merely a lossy summary. It is a **routing
decision** that determines which symbols receive analysis at all, and it routes
on a dimension ("do we like it?") that has no bearing on the question the
planner answers ("where would one enter?").

## 3. Contributing defects, each independently sufficient

### 3.1 The verdict flipped four times in 106 minutes

```
11:30:20  AVOID   conf 0.33     12:43:23  AVOID   conf 0.32
13:15:49  AVOID   conf 0.63     13:16:30  IGNORE  conf 0.45   <-- current
```

Two of these are 41 seconds apart with a 0.18 confidence swing. Nothing in the
card exposes this instability; the operator sees only the last one.

### 3.2 An agent hallucinated a $1.3M position

Steph (12:44:17) recommended **TRIM** with reason codes
`concentration_risk, overvalued`, reasoning from an assumed **17.3% / $1.3M**
BETA holding. Ground truth is 0 shares, $0. The synthesis recorded the conflict
(`safety_reasons: contradictory_synthesis — "Says underweight but recommends
reduction"`) and still shipped the label. The hallucinated `TRIM` then
propagated onto the strategy card as `card->>'agent_rec'`.

This is the same class as the Maria watchlist-fabrication rule already in the
SOULs: an agent inventing portfolio structure that does not exist.

### 3.3 The earnings date was in the database and never parsed

`catalyst_events`, published 2026-07-15 07:00:

> "BETA Technologies to Announce Second Quarter 2026 Results on **August 12, 2026**"

`symbol_profiles.next_earnings_date` for BETA: **NULL**. The system ingested the
date as a headline and never extracted it into the field every event gate reads.
Every downstream earnings check therefore saw "no scheduled earnings" for a stock
with a confirmed print inside any August contract.

### 3.4 A stored hallucination about the company itself

`analyst_consensus_history` (11:25:57) records
*"BETA Technologies is privately held; no public sell-side analyst coverage"* —
for a symbol the rest of the system quotes on the tape at $19.10 with a live
option chain. Meanwhile Maria's narrative cites a $21.00 B. Riley target that
`research_insights` never extracted (all 22 rows have `price_target = NULL`).

### 3.5 Stale technicals, live price, no reconciliation

The packet every agent reasoned from was cached **2026-07-17 15:31** (RSI 53.75,
ATR 1.11). The tape at synthesis time was $19.10, RSI 60.29, RVOL 6.07. The
synthesis reasoned at "$18.61-18.95" and flagged its own inputs as 2.9 days old —
then produced an actionable-looking label anyway.

### 3.6 Six catalysts in one morning did not trigger re-analysis

Between 01:05 and 08:33 on 2026-07-20: GE Aerospace hybrid military aircraft, the
MV250 unveil, Loganair adding ALIA CTOL, a GE/NASA/Boeing high-altitude hybrid
flight (impact 6.6, confidence 0.94-1.00), and a Lockheed Martin partnership.
The scope governor did promote S2 → S1 on `fresh_catalyst`. No entry plan
followed, because §2.

### 3.7 The anchored review prompt

`cloud_review.py:48` opens *"You are an INDEPENDENT reviewer"* and then supplies
the local verdict verbatim, asking whether it is sound. Two consequences:

1. **Anchoring** — both lanes receive the same prior, so their agreement is
   correlated by construction.
2. **Grammar** — the verdict vocabulary is `AGREE / CAUTION / DISAGREE`. Those
   are opinions *about another answer*. There is no token for "constructive long
   term, extended short term, wait for a pullback". A reviewer cannot express an
   independent view even if it holds one.

(2) is why improving the prompt text would not have fixed this. **582 rows**
currently carry `models_agree = TRUE` and render an `AGREE` badge produced by
this path. BETA is not among them.

## 4. What shipped

| file | what it does |
|---|---|
| `scripts/decision_packet.py` | six independent dimensions; retires `IGNORE`/`AVOID`; refuses model-authored arithmetic; refuses vague language |
| `scripts/trade_blueprints.py` | deterministic construction + payoff arithmetic for shares, CSP, verticals, long options, shorts; every rejection names its rule |
| `scripts/blind_review.py` | blind facts packet (anchor keys refused recursively), independent output shape, per-dimension agreement, self-disclosing badge |
| `tests/test_decision_packet.py` | 62 tests, 6 generalised fixtures, plus a test asserting no module contains a BETA-specific conditional |

What BETA should have produced, and now can:

```
LONG TERM    SPECULATIVE_CONSTRUCTIVE   $3.9B backlog / 991 aircraft, $1.589B cash,
                                        against a $122.3M quarterly loss
TACTICAL     WAIT_FOR_PULLBACK          +20.6% 20d, +6.85% today, RSI 60, pressing
                                        resistance 19.20-19.75
EVENT        CAUTION                    earnings 2026-08-12 — inside any Aug contract
DATA         STALE                      technicals cached 07-17, price live
INSTRUMENT   staged shares 25% starter / 25% pullback / 25% breakout+retest /
             25% reserved through earnings; invalidation below 15.15
```

## 5. Not done

Wiring. The modules are built, tested and correct, but nothing calls them yet:
the producers still write one word, the consumers still branch on it, and the
card still renders it. Specifically outstanding:

- migrate `watchlist_final_synthesis` to carry a decision packet
- replace the six divergent avoid-set definitions
  (`_CONSERV`, `watchlist_priority.py`, `api_v2.py:5882`, `api_v2.py:6121`,
  `cioAvoid`, `cioBlocksEntry` — three of which disagree on whether `TRIM`
  blocks) with one import
- **remove the label gate from `watchlist_entry_planner.py`** — the single
  highest-value change in this document
- on-demand `BUILD PLAN NOW` wired to the existing `--symbols` path
- blind pass wired into `process_watchlist_agent_jobs.py`; rename the anchored
  badge in `WatchlistCardV4.tsx:371`
- parse `catalyst_events` earnings headlines into `symbol_profiles`
- position-truth guard so no agent can reason from a holding that does not exist
- missed-opportunity ledger; historical replay; Drive sync

```
BETA INCIDENT RECONSTRUCTED: YES
LONG-TERM / TACTICAL SEPARATION VERIFIED: PARTIAL  (built + tested, not wired)
BLIND MODEL INDEPENDENCE VERIFIED: PARTIAL  (built + tested, not wired)
ON-DEMAND PLAN VERIFIED: NO
WATCH-TO-OPTIONS ROUTER VERIFIED: PARTIAL  (constructors + matrix, no live chain wiring)
MISSED-OPPORTUNITY ATTRIBUTION VERIFIED: NO
BETA STRATEGIC PACKET VERIFIED: YES  (as a fixture)
HISTORICAL REPLAY SUFFICIENT: NO
GIT-TO-DRIVE SYNC VERIFIED: NO
LIVE EXECUTION ELIGIBLE: YES
NEW DECISION ARCHITECTURE EXECUTION AUTHORITY: NO
AUTONOMOUS BROKER SUBMISSION: NO
ORDER SUBMITTED DURING IMPLEMENTATION: NO
```
