Status:      ACTIVE
as_of:       2026-09-01T15:25:00-04:00
Measured at: CURRENT BUILD_SHA 18a3da0dc (file content), dir 18a3da0dc-main-exact-phase2-20260901-143119
             origin/main ac4b37cea · $PROJ 0a591048b (3 behind — reported, CURRENT measured)
Canonical repo path: docs/ops/litmus/LITMUS_MONEY_2026-09-01.md
Authority:   discovery only. No winner picked. No product change proposed.
See also:    docs/ops/CIO_BANNER_DATA_ASOF_2026-09-01.md · docs/audits/CIO_SURFACE_ASOF_2026-09-01.md
             docs/ops/CIO_DATA_ASOF_GAPS_2026-09-01.md

# Litmus · B money

Every money figure a surface publishes, its formula, its writer, and its clock. **No winner is
picked.** Where two derivations disagree, both are quoted. The $500 question is the operator's.

## Findings

| surface | endpoint | field | writer | clock | as_of | verdict |
|---|---|---|---|---|---|---|
| strip | `/api/v2/overview` | `portfolio_value` | `portfolio_totals.total_value` (canonical) | `holdings.as_of` | 2026-09-01 | **LIVE** |
| strip | `/api/v2/overview` | `derived_total_value` | `sum(market_value)` at read | read time | n/a | **LIVE** |
| strip | `/api/v2/overview` | `total_cash` | `portfolio_totals.total_cash` (stored) | `holdings.as_of` | 2026-09-01 | **LIVE** |
| desk | `/api/v3/cio/home` | `capital_plan.cash_total_usd` | caller-supplied `cash` | `cash_as_of` (separate) | 2026-09-01 | **LIVE** |
| desk | `/api/v3/cio/home` | `capital_plan.cash_earmarked_redeploy_usd` | `min(raw_earmark, cash)` | same | 2026-09-01 | **LIVE** but clamped |
| desk | `/api/v3/cio/home` | `capital_plan.cash_free_unearmarked_usd` | forced by the clamp | same | 2026-09-01 | **EMPTY** (always 0.00) |
| letter | `/api/v3/cio/home` | `cash_letter.cash_usd` | `store.load(CASH_SLEEVE)` | record `cash_written_at` | **2026-08-29** | **STALE** |
| evidence | `/api/v3/cio/home` | `…cc_narrative.evidence_refs[*].total_cash` ×6 | snapshot in the record | record | **2026-08-29** | **STALE** |
| evidence | `/api/v3/cio/home` | `…cc_narrative.evidence_refs[*].total_value` ×13 | snapshot in the record | record | stale | **SPLIT** |
| rows | `holdings.json` | `is_cash` row sum | broker syncs | per-row `as_of` | 2026-09-01 | **LIVE** |

## The two live cash numbers

```
630,513.62  ×7   overview.total_cash · capital_plan.cash_total_usd ·
                 operator_product.cash.cash_usd · operator_product.temperament.cash ·
                 cio.cash.cash_usd · cio.temperament.cash
630,784.82  ×7   cash_letter.cash_usd + 6× evidence_refs[*].total_cash
                                                              delta  $271.20
```

**This is an improvement, not a regression.** `CIO_SURFACE_ASOF_2026-09-01.md` recorded **three**
distinct cash values in one body (630,791.10 / 630,790.42 / 630,784.82) and 14 statements. It is
now two. `temperament.cash` has joined the consolidated value; the stored-field and row-sum
derivations agree.

## The formulas, quoted

**`overview.total_cash`** — `api_v2.py:2605`, and the comment above it is the finding:

```python
# Cash = sum of the actual CASH positions. The stored portfolio_totals.total_cash had drifted to
# $478k while the real cash was $186k. ... the 2026-08-29 Saturday proof
# showed the stored field agreeing with the row sum to the cent
# (630,784.82, source=position_rows, gap 0.00) across holdings.json,
# /v2/overview and /v3/cio.
#
# Read the stored field. Two places deriving the same number is how the
# original drift went unnoticed for three months.
_total_cash = totals.get("total_cash")
```

**The number that comment cites as proof of agreement — `630,784.82` — is today the divergent
one.** `/v2/overview` now reads `630,513.62`; only `cash_letter` and the evidence refs still carry
`630,784.82`. The comment records a gap-0.00 proof that no longer holds, and cites the losing
side. §3: a policy comment that outlived its policy.

The reasoning in it is sound and should be preserved: *two places deriving the same number is how
the original drift went unnoticed.* That is exactly the shape of the remaining split.

**`cash_letter.cash_usd`** — `cio_command_center.py:1477 build_cash_letter_section`:

```python
from scripts.lib.cio_instrument_record import CASH_SLEEVE
rec = store.load(CASH_SLEEVE)
```

It reads the **InstrumentRecord**, not the row sum. That record's clocks:

```
updated_ts        2026-08-30T14:53:41Z
cash_written_at   2026-08-29T23:28:23Z
next_eligible_at  2026-08-31T14:53:41Z   (expired)
```

So the two derivations are not a rounding disagreement — **they are two stores with two clocks.**
The letter is a record snapshot from 08-29; everything else is today's row sum.

**`capital_plan`** — `cio_capital_plan.py:729`. Its envelope is explicitly honest, and worth
quoting because it is the one place that says what its clock means:

```python
# Envelope clock -- when this projection was composed. NOT the age of
# the cash. `cash_as_of` below carries the cash's own evidence clock.
"as_of": now.isoformat(),
"as_of_means": "composition time of this projection, not data age",
```

**`portfolio_value`** — `api_v2.py:2586`, and this comment is also load-bearing:

```python
# portfolio_totals.total_value is CANONICAL. The old ">$500 drift → silently swap to
# derived" rule made the shell header flip $96.9K whenever SPAXX was momentarily
# unpriced ... Derived only fills in when totals are missing entirely;
# drift is FLAGGED, never swapped.
_derived_total = round(sum(p.get("market_value") or 0 for p in holdings), 2)
_total_drift  = round(_derived_total - (total_val or 0), 2)
```

Today `portfolio_value == derived_total_value == 1,277,802.71`, so drift is **0.00** and the
canonical/derived pair agrees. **A $500 threshold appears here as a historical drift rule — it is
unrelated to the retired moomoo row, and the two must not be conflated.**

## Three portfolio totals

```
1,277,802.71  ×5   overview.portfolio_value · derived_total_value ·
                   pricing.derived_total_value · pricing.canonical_total_value ·
                   cio.operator_trust.holdings.total          ← LIVE, agreeing
1,286,402.75  ×8   cio …evidence_refs[*].total_value          ← snapshot
1,287,999.68  ×5   cio …evidence_refs[*].total_value          ← a DIFFERENT snapshot
                                                    spread   $10,196.97
```

**The evidence refs carry two different stale totals**, neither matching live. These are the
figures individual decisions and re-entry candidates cite to justify themselves — a decision's
own evidence block states a portfolio value up to $10,197 from the live one, and two decisions
disagree with each other.

Not judged here: whether a decision *should* cite the total as it stood when the decision was
formed. That is defensible provenance (class S, snapshot-derived) — but it is undated on the
surface, so a reader cannot tell a deliberate snapshot from a stale read.

## The $500 — operator

`holdings.json` no longer carries the `moomoo_taxable_live` CASH row (retired 2026-09-01 on
operator instruction; archived, not deleted). Consequences observable but **not adjudicated here**:

- portfolio total is $500 lower than a pre-retirement figure; any comparison across that boundary
  is a scope change, not a market move.
- `cash_letter` at `630,784.82` predates the retirement; the consolidated `630,513.62` postdates
  it. **Whether the $271.20 delta is the retirement, a reprice, or both is not determined here**
  — $500 − $271.20 = $228.80 is unexplained by the retirement alone, and no attempt is made to
  reconcile it. **That is an operator question.**

## Two other observations, not pursued

- `overview.position_count = 15` while `holdings.json` carries **29 rows** (`api_v2.py:2629`
  counts `active_positions`, a filtered set). Two counts of "positions" on adjacent surfaces with
  no labelled scope. **UNKNOWN** whether any consumer conflates them.
- `cash_earmarked_redeploy_usd == cash_total_usd == 630,513.62` **exactly**, and
  `cash_free_unearmarked_usd == 0.00`. That equality to the cent is the fingerprint of
  `min(raw, cash)` returning `cash` — the clamp documented in `CIO_SURFACE_ASOF_2026-09-01.md`,
  still present.

## Scope

Discovery only. No product change, no PR, no push. `BehaviorWriteRefused` untouched; no Telegram,
no `outcome --apply`, no holdings write, no `.env`, no `$PROJ` fast-forward, no promote, no
crontab, no `AGENTS.md`, no `docs/INDEX.md`.
