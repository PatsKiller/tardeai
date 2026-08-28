# P8.5 — the freshness flip: **not applied**

The brief's condition was explicit: *"Flip it, and confirm the PASS count before and
after is unchanged. If it is not unchanged, stop and report rather than proceeding."*

**It is not unchanged. 6 → 5. Nothing was flipped.**

`[VERIFIED]` = command run against live state, output quoted. `[CODE]` = read from source
in `46bda9d8-main-exact-phase2-20260828-092136` (includes #574).

---

## The measurement `[VERIFIED]`

```
unverified (7): cost_basis, hermes_research, investment_policy,
                model_portfolio, risk, sectors, transactions

PASS today       6   BROKER_RECONCILIATION · INCOME_REVIEW · OPERATOR_REQUEST ·
                     PORTFOLIO_ALLOCATION_REVIEW · RETIREMENT_REVIEW ·
                     WATCH_OR_CATALYST_REVIEW
PASS if blocking 5
purposes lost    PORTFOLIO_ALLOCATION_REVIEW
```

Two things moved since the flip was measured free in P7.5, and they moved in opposite
directions:

- the baseline rose from 5 to **6** — `PORTFOLIO_ALLOCATION_REVIEW` now passes, having
  previously been blocked on `cash_buying_power`;
- and that newly-passing purpose is precisely the one the flip would break.

The earlier "free twice" measurement was correct when taken. Live state changed. This is
why the condition was written as a re-check rather than a recollection.

## Which domains block it `[VERIFIED]`

```
PORTFOLIO_ALLOCATION_REVIEW  would be blocked by  investment_policy, model_portfolio, risk
RISK_OR_STOP_EVENT           would be blocked by  risk
SCHEDULED_CIO_BRIEF          would be blocked by  risk
TAX_REVIEW                   would be blocked by  cost_basis
```

## Why stamping them is not a free workaround

The P7.5 remedy — find the timestamp the producer already emits and read it — does not
transfer here. All three blockers were checked `[VERIFIED]`:

| domain | source | timestamp keys | file mtime | threshold |
|---|---|---|---|---|
| `investment_policy` | `config/investment_policy_statement.json` | **none** | 08-27 18:03 | 168h |
| `model_portfolio` | `config/model_portfolio.json` | **none** | 08-27 18:03 | 168h |
| `risk` | `data/portfolios/state/risk_management.json` | **none** | 08-26 07:31 | **24h** |

Two distinct problems, neither cheap:

**1. `risk` is genuinely stale — 49.9h against a 24h threshold.**

Stamping it honestly does not rescue the flip; it makes the staleness explicit and blocks
*three* purposes instead of one. **The gate would be right and the data is late.** This is
exactly the hole `freshness_unverified` was added to mark in #566: a domain carrying no
stamp is never age-checked, so nothing noticed that risk has not been refreshed in over
two days.

No scheduled writer of `risk_management.json` was identified. Five modules reference it —
`portfolio_signals`, `recovery_watch_daily`, `system_health_agent`,
`check_data_product_freshness`, `generate_integrity_manifest` — and on inspection all
appear to *read* it. That is a heuristic result from pattern-matching write calls, not a
proof; it should be confirmed before being acted on. If it holds, the finding is larger
than the flip: **an AVAILABLE domain required by three run purposes has no producer.**

**2. `investment_policy` and `model_portfolio` live in `config/`, not persistent state.**

They exist only in the release tree, carry no timestamp field, and their mtime is a
checkout/rsync artifact — it records when the file was materialised into a release, not
when the policy last changed. Stamping from it would assert a freshness the source has not
earned, which is the specific thing #574 refused to do ("never `now`"). A real stamp here
means the policy documents gaining an `as_of` the operator maintains — a content change,
not a code change.

## What would make the flip free

In order of cost:

1. Establish who refreshes `risk_management.json`, and on what cadence. Until that is
   answered, flipping the gate converts a silent 50-hour gap into three blocked purposes —
   which is arguably correct, but it is a decision about availability, not a tidy-up.
2. Add an operator-maintained `as_of` to the two policy documents.
3. Re-run the measurement. If it returns to unchanged, the flip is free again.

## Status

**Held, not abandoned.** No code changed. The gate remains advisory, exactly as #574 left
it, and `freshness_unverified` continues to mark the seven domains it always did.

The brief's framing — that the earlier warning was "wrong in the operator's favour" — was
accurate for the state it measured. It is no longer accurate for today's, and the honest
cost of flipping now is one working purpose plus a 50-hour data gap surfaced as three
blocked ones.
