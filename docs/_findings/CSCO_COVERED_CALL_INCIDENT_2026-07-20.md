# CSCO Covered-Call Incident — 2026-07-20

Status:      HISTORICAL
as_of:       2026-07-20T13:28:58-04:00
Measured at: efcc51365 / not measured

**Starting SHA:** `972e9d4cc9b405c2636b7c8c25e8204024e181d7` · working tree clean
**Test baseline before remediation:** 208 passed, 0 failed, 0 skipped
**Orders submitted during this investigation:** none
**Real 2FA codes sent:** none

The maturity standard this incident violates:

> The system must never present an actionable covered-call recommendation that a
> later stage already knows it will reject.

---

## 1. What the operator experienced

1. The Defense desk displayed a CSCO covered call: 1 contract, $120 strike,
   expiring **2026-08-21**, premium ≈ $408, delta 0.37.
2. Chain validation rendered **green** rails — OI 10,156, volume/OI 10,156,
   spread 2.5% of mid, delta 0.37.
3. The card offered **"⚡ queue trade (2FA approval)"**. The operator clicked it.
4. The card returned **"✓ queued — approve in Options (2FA)"**.
5. **No 2FA code arrived.** The operator reasonably concluded the system was
   broken, and said so.
6. Investigation found the trade could not have reached 2FA by any route, and
   separately that it should never have been recommended.

## 2. The proposal rows, as stored

```
proposal_id    defense-cc-CSCO-2026-08-21-120
origin         defense_desk_v6
structure      CSCO 1x $120 CALL 2026-08-21, account schwab_rollover_ira
mid/delta/prem 4.08 / 0.37 / 408
status         approved            live_eligible  False
blocks_json    []  (EMPTY)         occ_symbol     ABSENT
created        2026-07-20 10:52:21  updated 2026-07-20 11:24:58
```

A second row proves this is **not a one-off**:

```
proposal_id    defense-cc-CSCO-2026-08-21-125.0
created        2026-07-18 14:35:23   status rejected (system_expiry)
blocks_json    []  (EMPTY)           occ_symbol ABSENT
```

The same defect produced a CSCO covered call on 2026-07-18 that expired
unactioned. The incident is two days old at minimum.

## 3. The event that made it unsuitable

```
CSCO next earnings   2026-08-12   (SCHEDULED, symbol_profiles/yfinance)
proposed expiration  2026-08-21
=> earnings falls 9 days BEFORE expiry — inside the contract
```

Selling this call means carrying an earnings print inside a contract on shares
the operator would be obliged to deliver. This is the exact risk the blackout
exists to prevent.

## 4. Defect classification

### 4.1 Recommendation defect — the primary failure

`options_chain_snapshot.py`, which selects the covered-call contract, contained
**zero references to earnings**. It scored candidates purely on DTE (18-50) and
delta fit. It chose 2026-08-21 with no knowledge of the 2026-08-12 report.

### 4.2 Event-gate defect — asking the wrong question

The surrounding code uses `_earnings_soon(prof, blackout_days)` — *"earnings
within N days"*. The correct structure-specific question is *"does earnings fall
before expiration"*. CSCO earnings are 23 days out, comfortably outside a 14-day
blackout, yet squarely inside a 32-day contract. The two checks are not
equivalent, and only the weaker one ran at selection time.

The downstream gate asked the right question (`expires_before_earn = dte >=
days_to > 0`) and refused — **after** the operator had acted.

### 4.3 Proposal-identity defect

`/api/v2/options/preflight` — the step that calls `request_2fa` — resolved
proposals by id from the **options_engine** proposal list. Defense writes ids
shaped `defense-cc-CSCO-2026-08-21-120`, which options_engine never produces.
The lookup returned 404 `proposal not found`. The 2FA step was unreachable for
every Defense-origin option, not only this one.

### 4.4 Queue-surfacing defect

Defense writes **directly** into `options_approval_queue`, bypassing the
options-engine proposal model. The Options workflow could not reconstruct or
resolve the row, so a proposal that existed in the database was not usable by
the page meant to action it.

### 4.5 Approval defect — a refusal citing blocks that did not exist

`resolve_approval` refused whenever `live_eligible` was False:

```python
if action == "approve" and row[3] is False:      # live_eligible
    blocks = row[4] or []                         # EMPTY
    return {"ok": False, "error": "cannot approve — enterprise blocks remain",
            "blocks": blocks}
```

`_defense_cc_queue_trade` inserted every row with `live_eligible=false` AND
`blocks_json='[]'`. The operator therefore saw *"enterprise blocks remain"*
beside an **empty block list** — unapprovable, permanently, for no stated reason.

### 4.6 UI-copy defect

The card promised **"approve in Options (2FA)"**. `resolve_approval` only flips
`pending → approved`; it sends no code. 2FA is generated at **SUBMIT**, by
`request_2fa` inside the preflight route, and consumed at
`/api/v2/options/confirm`. Approving therefore produced no Telegram, exactly as
designed, while the label said otherwise.

### 4.7 Contract-resolution defect

`occ_symbol` is **absent** on both rows, yet the card rendered green validation
rails and an actionable button. `no_resolved_occ` then appeared as a downstream
block — a surprise after a green card.

Separately, the validate-chain endpoint requested `strike_count=14`, an
ATM-centred window spanning roughly 85.0-139.0 for SPCX. Strikes we ourselves
propose sit 15-16% OTM, so **three of four** covered-call cards reported
"not found in the live chain" for contracts that exist and trade.

### 4.8 Documentation drift

Canonical docs still describe FMP as the live earnings provider. FMP's
`v3/earning_calendar` returns HTTP 403 for non-legacy keys and the key is
additionally quota-exhausted (429 on every endpoint). The live provider is
`symbol_profiles` + on-demand yfinance.

### 4.9 Testing gap

No test asserted that a recommended contract must not span earnings. No test
covered Defense-origin proposals reaching the Options workflow. No test asserted
that an ineligible row carries reasons. Each defect above was individually
invisible to CI.

## 5. Root-cause map by subsystem

| subsystem | defect |
|---|---|
| `options_chain_snapshot.py` | contract selection earnings-blind |
| `defense_recommendations.py` | wrong event question (`within N days`) |
| `api_v2._defense_cc_queue_trade` | direct queue write; hardcoded ineligible; no OCC |
| `options_desk_enterprise.resolve_approval` | refused on `live_eligible`, not on blocks |
| `api_v2` preflight | identity resolvable only via options_engine |
| `api_v2` validate-chain | ATM window narrower than proposed strikes |
| `RecommendationsRail.tsx` | 2FA promised at the wrong stage |
| docs / Drive | FMP named as live earnings source |
| tests | no coverage for any of the above |

## 6. Remediation already landed (2026-07-20)

| commit | fix |
|---|---|
| `6756dfbc` | validate-chain window 14 → 48; 3 of 4 CC cards could not resolve |
| `7c9d66e8` | preflight falls back to the queue row; label names the real 2FA stage |
| `05e5b3b9` | approval gate refuses on ACTUAL blocks; Defense evaluates eligibility for real |
| `df504a16` | CC picker earnings-aware; penalises earnings-spanning expiries; card carries the warning |
| `5b4db824` | fixes a NameError in that change which collapsed radar coverage to 1/29 |

All five are confirmed in the chain from `972e9d4c`.

## 7. What remains — this is NOT closed

The recommendation is now **labelled** when it spans earnings, but the system can
still surface an earnings-spanning contract as the pick rather than returning
`NO_ELIGIBLE_COVERED_CALL`. For CSCO specifically there is no safe alternative:
every 2026-08-07 strike fails the liquidity rails (spreads 7.9-31.2% against a
12% limit), so the correct output is "no eligible covered call", not a labelled
substitute.

Outstanding: canonical proposal service and identity, one eligibility evaluator
across all stages, queue readback, the covered-call state machine, ITM
exit-strategy classification, queue integrity audit, proposal audit trail, and
the Drive documentation reconciliation.

```
CSCO COVERED CALL INCIDENT RECONSTRUCTED: YES
COVERED CALL RECOMMENDATION EVENT-AWARE: PARTIAL  (labels; does not yet refuse)
UNKNOWN EVENT DATA FAILS CLOSED: YES
NO-SAFE-CONTRACT BEHAVIOR VERIFIED: NO
ITM COVERED CALL CLASSIFICATION VERIFIED: NO
CANONICAL PROPOSAL IDENTITY VERIFIED: NO
DEFENSE-TO-OPTIONS ROUTING VERIFIED: PARTIAL  (fallback lookup, not canonical)
QUEUE READBACK VERIFIED: NO
ELIGIBILITY PARITY VERIFIED: NO
OCC RESOLUTION VERIFIED: NO
LIVE EXECUTION ELIGIBLE: YES
COVERED CALL MATURITY VERIFIED: NO
AUTONOMOUS BROKER SUBMISSION: NO
ORDER SUBMITTED DURING IMPLEMENTATION: NO
```
