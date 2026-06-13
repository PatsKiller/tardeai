# Schwab Widening Promotion Roadmap

**Status:** Planning / operator-approved roadmap only  
**Scope:** Schwab live-real-account widening strategy after Stage 2b micro-canary  
**Last updated:** 2026-06-12  
**Owner:** Operator / Trade AI broker safety track

---

## 1. Standing Truth: Schwab "Sandbox" Is Not Isolated

The Schwab website may show a sandbox selection, but this project treats that as **not sufficient** for fake-money testing.

Current operator fact:

- The Schwab key/app is the **same key/app as before**.
- No new isolated keyset was issued.
- No separate fake-money account has been proven.
- Prior SB-0 read-only proof returned real Schwab accounts and real balances.
- Therefore any order-capable path must be treated as touching real money.

Operational rule:

> Same key/app = real-account risk. Sandbox label alone does not justify widening.

Do not widen based only on a Schwab UI sandbox selection. Widening requires a committed promotion stage, validator updates, an operator runbook, and a rollback/disarm plan.

---

## 2. Non-Negotiable Widening Principles

Widening must remain **commit-controlled**, not runtime-controlled.

Do not widen with:

- `.env` flags alone
- database flags alone
- UI switches alone
- runtime JSON edits
- uncommitted local changes
- temporary manual edits to gate files

Widen only by committed changes to policy and validation files, with a diffable Git record.

Core files that define or validate the envelope:

- `scripts/brokers/canary_gate.py`
- `scripts/brokers/pilot_caps.py`
- `scripts/brokers/execution_guard.py`
- `scripts/validate_schwab_write_policy.py`
- `docs/brokers/stage2b-write-pilot-spec.md`
- `docs/brokers/stage2a-reconciliation-log.md`
- this roadmap

Every widening commit must answer:

1. Which account or accounts are allowed?
2. Which symbols are allowed?
3. What is the maximum price?
4. What is the maximum quantity?
5. What is the maximum notional per order?
6. What is the maximum risk dollars per trade?
7. What is the maximum notional per day and week?
8. Which order types are allowed?
9. Which session date/window is allowed?
10. How many total pilot orders are allowed?
11. What is the abort condition?
12. How is the system disarmed or rolled back?
13. How are canary/test trades excluded from strategy performance?
14. How is read-back reconciliation proven before the next promotion?

---

## 3. Widening Dimensions

Do not widen every dimension at once. Promotion must be gradual across three axes.

### 3.1 Account scope

Promotion path:

1. Taxable only
2. Taxable with larger size
3. Roth IRA tiny pilot
4. Rollover IRA tiny pilot
5. Multiple accounts with per-account caps
6. Portfolio-level weekly caps

Retirement accounts are a separate risk tier. Do not treat them as merely another account selector.

### 3.2 Money envelope

Promotion path:

1. Current micro-canary envelope
2. Taxable-only $500 max notional test
3. Taxable-only $1,000 max notional test
4. Taxable-only $2,000 max notional test
5. Taxable-only $4,000 max notional test
6. Per-week cap with automatic disarm
7. Other accounts only after taxable evidence is clean

### 3.3 Order-type envelope

Promotion path:

1. Buy limit only
2. Buy limit + cancel validation
3. Buy limit + protective stop
4. Buy limit + stop readback / monitoring
5. Buy limit + trailing stop
6. Bracket/OCO structure
7. Multi-target / ladder only after bracket validation

Do not test complex exit structures before simple buy/cancel/readback mechanics are clean.

---

## 4. Current Baseline Stage: W0

W0 is the live micro-canary posture.

Expected current baseline:

- Account: `schwab_taxable` only
- Retirement accounts: blocked
- Symbol allowlist: committed only
- Session date: committed only
- Max quantity: small, committed literal
- Max notional: micro-canary only
- Per-order approval: required
- Readback reconciliation: required
- Uncommitted gate edits: fail validation
- Canary/test trades: excluded from production stats

W0 proves mechanics, not profitability.

W0 must remain the rollback target for all future widening.

---

## 5. Recommended Next Stage: W1 Taxable $500 Test

The next likely widening stage should be **taxable-only**, not other accounts.

### 5.1 Purpose

W1 is designed to prove that the live order path, stop placement, readback, account monitoring, sizing panel, and reconciliation can handle a real but still limited order size.

W1 is not a performance/profitability test.

### 5.2 Proposed envelope

- Account: `schwab_taxable` only
- Retirement accounts: blocked
- Max notional per trade: `$500`
- Max price: committed value suitable for the chosen allowlist
- Max quantity: committed value derived from max notional
- Max open pilot positions: 1 at a time unless explicitly promoted
- Max orders in stage: 5 completed order workflows
- Max weekly notional: `$1,000` during W1
- Order types initially allowed:
  - buy limit
  - cancel
  - protective stop after entry confirmation
- Not allowed yet:
  - trailing stop as first test
  - bracket/OCO as first test
  - multi-target ladder
  - short selling
  - options
  - retirement accounts

### 5.3 W1 required controls

Before W1 is armed:

- `validate_schwab_write_policy.py` must pass.
- Gate files must be clean against Git `HEAD`.
- Manual ToS / broker page must show the active envelope.
- Account cash/buying power must be visible read-only.
- Notional and percent-of-cash math must be visible.
- Stop/risk math must be visible when stop is present.
- Per-order confirmation must be single-use.
- Readback must show the order in Schwab activity before the next workflow proceeds.

### 5.4 W1 pass criteria

W1 can pass only if:

- All 5 workflows reconcile cleanly.
- No order appears outside the allowlist.
- No IRA account is touched.
- No order exceeds max notional.
- No unexpected position remains after cancel/exit tests.
- Protective stop is visible after entry workflow where required.
- All broker events are captured in logs.
- All pilot events are excluded from production strategy stats.
- The system can disarm and return to W0.

### 5.5 W1 abort conditions

Abort W1 immediately if:

- Any order appears in an unauthorized account.
- Any order exceeds the committed envelope.
- The readback stream does not show an order that was believed to be placed.
- A stop does not appear when the workflow required it.
- The validator fails.
- Gate files are dirty against `HEAD`.
- A canary/pilot trade leaks into production performance metrics.
- Any unexpected cancel/replace/trailing behavior occurs.

---

## 6. Stage W2: Taxable $1,000 Test

W2 is the likely next step after W1 is clean.

### 6.1 Proposed envelope

- Account: `schwab_taxable` only
- Max notional per trade: `$1,000`
- Max weekly notional: `$2,000`
- Max concurrent pilot positions: 1 to 2
- Required stop or explicit exit plan
- Required R:R display before ticket generation
- Required account cash/buying-power display
- Required percent-of-cash and percent-of-account display

### 6.2 New order functionality under test

W2 may add:

- buy limit + protective stop
- stop monitoring
- stop readback verification
- account/position monitoring
- alerting on stop visibility mismatch
- post-fill journal linkage

Do not add trailing stop until protective stop behavior is proven clean.

---

## 7. Stage W3: Taxable Stop and Monitoring Pilot

W3 introduces a stronger exit-management test.

### 7.1 Proposed envelope

- Account: `schwab_taxable` only
- Max notional per trade: `$1,000` to `$2,000`
- Max weekly notional: `$4,000`
- Required stop or trailing-stop plan
- Required account-level exposure cap
- Required reconciliation before additional entries

### 7.2 Required system functions

- Detect entry order in read-only Schwab activity.
- Detect fill or partial fill.
- Detect position in read-only Schwab account positions.
- Confirm stop order exists, where applicable.
- Detect stop cancellation or rejection.
- Alert if position exists without expected stop.
- Calculate risk dollars from live position and stop.
- Track per-account exposure.
- Track weekly pilot notional.
- Disarm if weekly cap is hit.

---

## 8. Stage W4: Taxable Trailing Stop Pilot

Trailing stops must be tested separately because runtime behavior and broker interpretation may differ from schema expectations.

### 8.1 Proposed envelope

- Account: `schwab_taxable` only
- Max notional per trade: `$1,000` to `$2,000`
- Max weekly notional: `$4,000`
- Max trailing-stop tests: small fixed sample
- No IRA accounts
- No multi-target ladders

### 8.2 Required observations

- How Schwab represents trailing-stop order status.
- Whether trailing value/percent round-trips correctly.
- Whether the activity stream exposes trail updates.
- Whether position monitor can recognize the trailing stop as protection.
- Whether cancellation behaves as expected.

---

## 9. Stage W5: Bracket / OCO Pilot

Bracket and OCO workflows must come after simple stop behavior.

### 9.1 Proposed envelope

- Account: `schwab_taxable` only
- Max notional per trade: `$1,000` to `$2,000`
- Max weekly notional: `$4,000`
- Required entry, stop, and target
- One bracket/OCO test at a time

### 9.2 Required observations

- Parent/child linkage in Schwab activity.
- Whether child orders appear after parent fill.
- Whether canceling one child cancels the paired order.
- Whether partial fill behavior is captured correctly.
- Whether Trade AI can reconcile the structure without false positives.

---

## 10. Stage W6: Other Account Types

Only move beyond taxable after W1-W5 are clean.

### 10.1 Roth IRA tiny pilot

- Account: Roth only
- Max notional: `$100` to `$250`
- Buy limit only first
- No margin
- No shorts
- No options
- No trailing stop as first test
- Stop behavior only after buy/cancel is clean

### 10.2 Rollover IRA tiny pilot

- Account: Rollover IRA only
- Max notional: `$100` to `$250`
- Same restrictions as Roth pilot
- Must validate settlement/cash behavior separately

### 10.3 Retirement account promotion rules

Retirement account widening requires:

- Separate pilot cap file entry
- Separate validator assertions
- Per-account weekly cap
- No cross-account accidental routing
- Account display in UI before ticket/export
- Clear audit tag for account type

---

## 11. Stage W7: Production-Limited Pilot Envelope

Longer-term target after multiple clean stages:

- Max notional per trade: `$2,000`
- Future possible cap: `$4,000`
- Max weekly notional: committed cap, for example `$5,000` to `$10,000`
- Max number of trades per week: committed cap
- Max concurrent live pilot positions: committed cap
- Per-account cap: committed cap
- Risk cap: percent of account value and/or risk dollars

Suggested production-limited constraints:

- Max per-trade notional: min(`$2,000`, configured percent of account value)
- Future per-trade ceiling: `$4,000` only after clean evidence
- Weekly gross notional cap: committed literal
- Weekly risk-dollar cap: committed literal
- Required stop/exit plan for every trade
- Required read-only reconciliation after every broker event
- Required no-open-exception status before the next order

---

## 12. Required Risk and Sizing Model

Before widening beyond W1, Trade AI should calculate and display:

- Selected account
- Read-only available cash / buying power
- Read-only account value
- Entry price
- Quantity
- Estimated notional
- Percent of available cash
- Percent of account value
- Stop price
- Risk per share
- Total risk dollars
- Percent account at risk
- Target price
- Reward dollars
- Risk/reward ratio
- Weekly consumed pilot notional
- Remaining weekly pilot notional
- Existing open pilot positions
- Whether the trade fits the current envelope

No order should be eligible for a wider pilot if these fields cannot be calculated or explicitly waived in the stage runbook.

---

## 13. Required Monitoring Model

Widening is not only about purchases. It must include monitoring.

Required monitoring functions:

1. Order submitted or manually entered.
2. Schwab read-only activity sees order.
3. Fill or partial fill is detected.
4. Position appears in account positions.
5. Expected stop or exit order appears.
6. Position without expected stop triggers alert.
7. Cancel/replace events are reconciled.
8. Stop/trailing-stop behavior is recognized.
9. Exit is detected.
10. Journal/performance/audit record is updated.
11. Pilot/canary trades are excluded from normal strategy stats.
12. Weekly cap is updated and enforced.

Abort if monitoring cannot confirm the expected broker state.

---

## 14. Validator Requirements for Widening

Every widening stage must update the validator to prove the exact stage policy.

Validator must assert:

- Allowed accounts only.
- Disallowed accounts rejected.
- Max price enforced.
- Max quantity enforced.
- Max notional enforced.
- Max weekly notional enforced, once added.
- Max order count enforced.
- Session/date window enforced.
- Allowed symbols only.
- Allowed order types only.
- Required stop/exit policy enforced where stage requires it.
- Gate files clean against `HEAD`.
- No raw Schwab write bypass.
- All write paths require the official execution guard.
- Per-order confirmation is required.
- Confirmation is single-use or stage-scoped.
- Canary/pilot exclusion remains wired into stats/journals.

Validator output must be captured in the stage log before and after a pilot session.

---

## 15. Commit and Runbook Template

Every widening stage should include:

### Commit title

`stage2x(schwab): widen taxable pilot to <amount> envelope`

### Changed files

- `scripts/brokers/canary_gate.py`
- `scripts/brokers/pilot_caps.py`
- `scripts/validate_schwab_write_policy.py`
- `docs/brokers/stage2b-write-pilot-spec.md`
- `docs/brokers/stage2a-reconciliation-log.md`
- `docs/brokers/schwab_widening_promotion_roadmap.md`
- UI files only if displaying the new envelope

### Required run commands

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .venv/bin/activate
python scripts/validate_schwab_no_writes.py
python scripts/validate_schwab_write_policy.py
cd apps/command-center-v3
npm run build
```

### Required evidence

- Validator output
- Git commit SHA
- Operator approval note
- Active envelope values
- Account allowlist
- Symbol allowlist
- Pilot order count cap
- Weekly cap
- Abort/disarm criteria
- Post-session reconciliation result

---

## 16. Rollback / Disarm Plan

Every widening stage must have a rollback.

Rollback options:

1. Revert to prior W0 canary commit.
2. Commit a disarm envelope with no active session date.
3. Set pilot account allowlist to empty.
4. Set max order count to zero.
5. Keep read-only activity capture running.
6. Keep monitoring open positions until closed.

Rollback must not erase evidence. It must create a new commit or documented operator action.

---

## 17. Next Likely Operator Request

Expected next stage request:

> Prepare the W1 taxable-only widening commit plan for a max `$500` or `$1,000` pilot. Include buy-limit, protective stop, monitoring, readback reconciliation, weekly cap, and validator assertions. Keep retirement accounts blocked.

Preferred next step:

- Start with W1 `$500` taxable-only if no prior live write evidence exists.
- Promote to `$1,000` taxable-only after W1 passes cleanly.
- Add stop/trailing-stop tests as separate staged capabilities, not as an uncontrolled increase.

---

## 18. Summary

The end-state can reasonably target:

- `$2,000` per trade after clean taxable evidence
- possible `$4,000` per trade after additional clean evidence
- committed weekly cap
- per-account cap
- required stop/exit policy
- read-only Schwab reconciliation
- account-aware sizing
- weekly exposure tracking

But the path must be staged:

1. Taxable account first.
2. Small widening first.
3. Stops before trailing stops.
4. Trailing stops before bracket/OCO.
5. Other account types only after taxable is proven.
6. Weekly cap before larger per-trade caps.
7. Validator must prove every envelope.
8. Git commit must record every widening decision.
