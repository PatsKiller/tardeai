# P9.5 — capability boundaries

Status:      HISTORICAL
as_of:       2026-08-28T09:21:26-04:00
Measured at: efcc51365 / not measured

What the operator expected, sorted into exactly one bucket each. **No code. No
recommendation** — scoping is the operator's.

`[VERIFIED]` = command run against live state, output quoted. `[CODE]` = read from
source in `9783395a-main-exact-phase2-20260828-082142`.

The headline: **three of the draft's four candidate boundaries are wrong.** They are
described as capabilities that do not exist. They exist, run, and produce data that
never reaches a surface. That distinction changes what it costs to fix them, which is
why the memo insists on it.

---

## Summary

| expectation | verdict |
|---|---|
| commentary on earnings | **built and unwired** |
| new candidate names outside the former-holdings set | **built and unwired** |
| cash deployment guidance | **built and broken** |
| rotation guidance | **never built** |
| a view on a named security not held | **built and unwired**, partially |

Only one of the five is genuinely absent.

---

## 1. Commentary on earnings — **built and unwired**

Ingestion exists at scale `[VERIFIED]`:

```
data/portfolios/state/earnings_dates.json   55 symbols, fetched 2026-08-24
  sample: V -> {"earnings_date": "2026-10-27", "fetched_at": "2026-08-24T08:34:40"}
transcript_intel_history                    4,150 rows
youtube_transcripts                         2,836 rows
aegis_transcript_discovery.py               cronned, weekdays 09:00
```

Six modules read `earnings_dates` `[CODE]` — `portfolio_signals`, `options_strategy_scanner`,
`portfolio_orchestrator`, `earnings_date_enrichment`, `earnings_provider`,
`update_lockup_earnings_dates`.

And the operator-facing field is empty `[VERIFIED]`:

```
brief["earnings"]                          0 items
cio_operator_product REQUIRED_SECTIONS     "earnings" present, populated from brief
```

**The dates are collected, the transcripts are ingested by the thousand, and the
earnings section of the product is an empty list.** Nothing converts either into
commentary. The gap is a renderer, not a data source.

## 2. New candidate names outside the former-holdings set — **built and unwired**

The draft says no lane generates names outside the former-holdings set. Measured, the
queue does `[VERIFIED]`:

```
collect_queue()   94 items   sources: reentry 46 · advisory 40 · defense 8

source      symbols   former holdings   held   genuinely NEW
reentry        46          41             0         0
advisory       40          37             3         0
defense         8           0             3         5   <- NKE, PFSI, PRIM, SH, XLU
```

Five genuinely new names entered the queue today, from the defense lane. The
opportunity book's code also explicitly handles them — it computes
`vs_re = "not_former"` for a symbol absent from the re-entry set
`[CODE cio_investment_product.py:652]`.

But what surfaces is `[VERIFIED]`:

```
opportunity_book.count      20
sources of the top 20       reentry × 20
genuinely new names in it    0
action_book NEW_POSITION_IF  0
watch names outside the re-entry set   0 of 22
```

**New names enter and are ranked out before display.** The book's own note states the
design — *"New capital uses ranked against cash and former holdings"* — so ranking
against the former-holdings set is deliberate; surfacing none of the newcomers may not
be.

This is the cheapest of the five to change and the one most likely to alter what the
operator sees tomorrow.

## 3. Cash deployment guidance — **built and broken**

The lane exists at every level except the answer.

- Situations are raised: **32 `S5_CASH_DEPLOYMENT`** research requests `[VERIFIED, P9.2]`
- A bucket exists: `action_book.HOLD_CASH_FOR`
- A stage exists: surface B reports `cash STAGE_0` `[VERIFIED, P9.3]`

And the output `[VERIFIED]`:

```
action_book.HOLD_CASH_FOR   1 entry
  symbol "CASH"
  why    "Preserve quality growth exposure, keep cash for dislocations, and do not
          force lower-quality replacements..."
temperament.cash            None
```

That `why` is the `portfolio_implication` constant — the unconditional hardcoded string
identified as the worst member of the P9.0 defect list, reproduced verbatim as the
system's cash guidance `[CODE cio_investment_product.py:502-506]`.

**Broken rather than unwired**, because the machinery runs end to end and delivers a
constant. An operator asking "what should I do with cash?" receives the same sentence
regardless of cash level, regime, or opportunity set — and `temperament.cash` is `None`,
so the amount of cash is not even carried into the field that advises on it.

## 4. Rotation guidance — **never built**

The only one of the five with no lane at all `[VERIFIED]`:

```
action_book buckets present: DO_NOW, WATCH_CLOSELY, RE_ENTER_IF, NEW_POSITION_IF,
                             HOLD_CASH_FOR, AVOID, CURRENT_HOLDINGS_THESIS, RESEARCH_NEXT
ROTATE / ROTATION bucket:    absent
```

No bucket, no situation type, no store. Rotation — selling X to fund Y — requires
reasoning across two positions simultaneously, and nothing in the action book is
shaped to hold a pair. **This is new capability, not a defect.** Anything that looks
like rotation advice today is two independent single-name opinions read next to each
other.

## 5. A view on a named security not held — **built and unwired, partially**

What exists `[VERIFIED]`:

```
CURRENT_HOLDINGS_THESIS   23 entries   (held names only)
AVOID                     15 entries   (former holdings — a negative view)
symbol thesis machinery   thesis_state CURRENT 35 · RESEARCH_REQUIRED 29 · THIN 3
```

So the system forms and carries views on named securities — but only inside two sets:
what is held, and what was previously held. The five new names from the defense lane
(NKE, PFSI, PRIM, SH, XLU) reach the queue and receive no thesis, no bucket, and no
surface.

The thesis machinery is general — `thesis_fields_for_symbol(sym)` takes any symbol
`[CODE cio_investment_product.py:653]`. It is the *candidate set* that is restricted,
not the capability.

---

## What this means for the draft

The draft's four boundaries were stated as *"no lane exists that..."*. Measured:

| draft's claim | actual |
|---|---|
| reads or reacts to earnings calls or transcripts | **reads them** — 4,150 transcript rows, 55 earnings dates. Does not react. |
| generates new candidate names outside the former-holdings set | **generates them** — 5 today. Does not surface them. |
| answers cash deployment or rotation questions | **cash: answers with a constant. rotation: correct, no lane.** |
| forms a view on a named security the operator did not already hold | **forms views on former holdings**, not on new names. Machinery is general; the candidate set is not. |

Three of four describe a delivery failure as an absence. That matters for scoping: wiring
an existing lane to a surface is a different order of work from building a research
capability, and the draft's phrasing would have led to the second estimate for three
items that need the first.

The one genuine absence — **rotation** — is worth stating in the operator's own words:
*the system has never been able to tell you to sell one thing to buy another, and
nothing in it is shaped to.*

## Bearing on the surfaces feeling empty

The draft's closing observation — *"the output format currently implies a breadth of
judgment the system does not have"* — is confirmed by P9.0, but the cause is narrower
than "the system cannot do these things". For three of the five, the system **did** the
work today and threw the result away before the operator saw it: 4,150 transcripts, 5 new
names, 32 cash-deployment research requests. The surfaces are not empty because nothing
happened. They are empty because what happened does not reach them.
