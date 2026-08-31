# CIO persistent spine — closeout

Status:      HISTORICAL
as_of:       2026-08-30T11:09:16-04:00
Measured at: efcc51365 / not measured

Date: 2026-08-30 · Authority: `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR=0` · `MBI_COGNITION=1`
Served pin at close: `d4cc7371-main-exact-phase2-20260830-110200`
Board: `scripts/cio_preconditions_board.py` → `CIOPreconditionsBoard@v1`

**Headline: 4 GREEN, 0 RED — and the number is only worth reading because of
what it took to stop it being a lie.** This document keeps the failures, not
just the final state. The board reached 4/4 twice today. The first time was
wrong.

---

## 1. The board, against live CURRENT

```
1. [GREEN] S0 attach + rehydrate (operator turn on the record, read back)
      1 record carries an operator turn with a plan_id and hands it back
      through the gate input
2. [GREEN] CC shows a non-SCHD held narrative + the cash letter, no ping
      12 non-SCHD held narratives and the cash letter are in the payload;
      nothing was pushed
3. [GREEN] Grok critique attach OR reject persisted on a record
      0 attach + 1 reject persisted on records
4. [GREEN] dust / CASH-as-a-ticker cannot mint or fire
      9 refusal probes held, a real ticker still mints, and no stored record
      is dust or cash

TOTAL green=4 red=0 cannot_verify=0
```

### How it got here — the honest sequence

| state | board | why |
|---|---|---|
| Slices A+B live | 2 green, 2 red | records existed; **nothing read them** |
| Slice C merged | 3 green, 1 red | the CC became the reader; check 2 flipped |
| residual_web hop | **4 green — FALSE** | check 3 accepted a bare `last_artifact_id`, so a residual_web artifact satisfied a check named for a *critique* |
| check 3 tightened | 3 green, 1 red | honest again |
| live Grok critique | **4 green — real** | `0 attach + 1 reject` from an actual critique |

The false green was reported to the operator before it was caught. A green
obtained by the wrong artifact type is worse than a red, because a red gets
investigated.

---

## 2. Record counts by kind

```
HELD   15      EXIT   24      SLEEVE  1        total 40
```

Refused at mint: 4 dust (<$50 aggregate MV), 3 non-equity tickers, 25 exits
with no plan or case summary. Three symbols held across multiple accounts
correctly collapse to **one record per subject**.

`SLEEVE:CASH` is a sleeve, never a ticker — a fake CASH holding is exactly how
the $630k question leaks in as an instrument.

---

## 3. The SCHD defer, on the record

```json
{"intent": "defer", "note": "wait for price buffer",
 "plan_id": "plan_79fe9e72f2d4", "ts": "2026-08-11T21:33:52+00:00"}
```

This is the thing the spine exists for. The disposition was made on 2026-08-11
and the plan that carried it closed; the record kept it. A wake on SCHD now
returns `skip / cadence_not_due` instead of re-running research the operator
already answered.

**It did not work on the first attempt.** Slice A seeded the defer into the
narrative *prose* but never pushed `next_eligible_at`, so the defer was narrated
and not honoured — the live record routed to `flash` twice while carrying it.
Two Slice-A bugs surfaced only against the live record:

- the migration seeded the **weight** hash from `market_value` — different
  quantities that happened to share a field name, so every first observation
  looked like a move
- `hash_changed` treated an **unset** hash as a change, so first contact fired a
  spurious event override on every freshly migrated record — overriding the
  very defer the record was created to remember

The migration now routes dispositions through the same `attach_operator_turn`
rule the live loop uses, so there is one definition of what a defer means.

---

## 4. Cognition apply — before / after

`MBI_COGNITION=1` means a lesson must change what the desk does next. A write
that moves none of `next_research_question`, `next_eligible_at`,
`notify_priority`, `cc_narrative` raises `CognitionNoOp` — a **failed** persist.

**Operator defer (`HELD:SCHD`)**

```
before  next_research_question: null
        next_eligible_at:       null
after   next_research_question: "Has a catalyst or earnings event changed the
                                 condition behind the defer (wait for price
                                 buffer)?"
        next_eligible_at:       2026-09-06   (+7d)
        notify_priority:        cc
        cc_narrative.what:      "Operator deferred: wait for price buffer. ..."
        changed: [next_research_question, next_eligible_at,
                  notify_priority, cc_narrative]
```

**Grok critique REJECT (`HELD:SCHD`)**

```
before  next_research_question: "Has a catalyst or earnings event changed ..."
after   next_research_question: "Prior research was refused (rejected). What
                                 INDEPENDENT evidence would settle this
                                 without restating it?"
        last_artifact_id:       grok_critique_ebb4120ba659
        last_outcome:           rejected
        research_blocked:       true
```

The reframe is the point: re-asking a prompt that failed closed is how a desk
spends a budget learning nothing.

**Provenance alone is not a persist.** A lesson attached with no decision moved
raises `CognitionNoOp`. Silence is how a memory system convinces itself it is
learning.

---

## 5. The live Grok critique

Lane `grok` on `maria_research_critique`, model `grok-3`, through the OAuth
proxy. Verdict **REJECT**, four reasons, the first of which is the system
catching its own core failure mode:

> "Includes explicit `recommendation` field directing `hold_with_thesis` which
> constitutes an action instruction"
>
> "Internally contradictory: states 18% weight exceeds 12% desk maximum yet
> recommends hold"

**The lane was never blocked.** `cio_grok_critique.py` carried a comment saying
`POLICY_NOT_ALLOWED` "because no research/critique process lists lane=grok". It
does — `allowed_lanes: ["fast","deepseek-v4-flash","grok"]` in **both** the file
registry and `llm_process_config`. The comment outlived its condition and was
quoted twice as current policy. Corrected in place.

---

## 6. The cash letter, on `/v3/cio`

```json
{"what": "Cash sleeve 630784.82.",
 "option_ids": ["hold_cash", "stage_into_X", "wait_until_month"],
 "recommendation_option_id": "hold_cash",
 "standalone_sell": false,
 "month_context": "August (historically_stronger_in_almanac_literature) · worst-six-months window",
 "next_eligible_at": "2026-08-31T14:53:41+00:00"}
```

Shape enforced in code, not requested in a prompt: the option ids are a closed
set, `standalone_sell` is always false, and a regex guard **refuses**
"deploy $N into TICKER" — a dollar amount pointed at a ticker is an instruction
wearing a letter's clothes.

Honest limit: `what` is still the migration's deterministic string
(`writer: migration:deterministic`), not agent prose. The pipe works; no real
cash letter has been written yet.

Alongside it: **37 instrument narratives** in the payload.

---

## 7. MBI evidence

`MBI_BEHAVIOR=0` is enforced, not asserted. `apply_cognition()` **raises**
`BehaviorWriteRefused` on `recommended_delta_usd`, `size_usd`, `shares`, `qty`,
`order`, `stop`, `limit`, `target_weight_pct`, `trade`, `execution`. Refused
outright rather than filtered — a silently dropped size field *looks* honoured.

| suite | tests |
|---|---:|
| `test_cio_instrument_record.py` | 44 |
| `test_cio_rehydrate_slice_b.py` | 15 |
| `test_cio_cc_record_narrative_slice_c.py` | 20 |
| `test_cio_research_budget_slice_d.py` | 51 |
| `test_cio_preconditions_board.py` | 32 |
| `test_cio_residual_web_lane.py` + live path | 89 |
| `test_board_check3_requires_a_critique.py` | 8 |

Acceptance green on all six flags at every promote.

---

## 8. Rails at close — the true values, not the intended ones

| rail | value |
|---|---|
| `telegram_sent` (CC block) | **false** |
| `CIO_SITUATION_NOTIFY` | **1** — delivery is ON |
| `CIO_TELEGRAM_INTERDICT` | **0** — not raised |
| `notify_situation_types` | `S6_CONCENTRATION_OR_DISPOSITION` only |
| `MBI_BEHAVIOR` / `MBI_COGNITION` | 0 / 1 |
| financial action | none |

The original slice spec pinned `CIO_SITUATION_NOTIFY=0` and "INTERDICT on".
**Those pins are superseded** by an explicit operator decision earlier the same
day: Telegram on, channel `@tradeai_cio_bot`, bar S6 fire only. The board reads
and prints the live flag values rather than restating the pin — a board that
lies about its own rails is worse than no board.

`telegram_sent: false` is not a claim that notify is off. It is the Wave 3E CC
block being render-only: `producer: null`, `would_send: false` on every row.

---

## 9. Cost governance (same session, adjacent)

- **Test rows were 99% of a day's apparent spend.** Sixteen `test_*`
  reservations carrying synthetic amounts totalled $2.71 against real
  production of $0.0141, and two never settled — blocking a live hop with
  `COST_CAP_EXCEEDED`. Excluded from the budget; the stale holds released.
- **Prices were 2.30x low.** DeepSeek output was 0.28 against a true 0.66
  off-peak / 1.32 peak, and no peak/off-peak concept existed at all. Restated:
  ~$0.267/day, not $0.116.
- **Five ungoverned cloud spend paths** bypassed the ledger entirely — OpenAI,
  xAI and Anthropic, all reachable from cron. All now route through `llm_lane`;
  `KNOWN_UNGOVERNED` is **empty**, with a ratchet test that blocks new ones.
- **Two callers named retired models** (`claude-sonnet-4-20250514`,
  `claude-opus-4-20250514`) that cannot succeed on the first-party API at all.
- All 15 peak-window batch jobs now run under the `PEAK_SKIP` gate
  (`--official`), which permits NY market hours whenever it is off-peak.
  Saving ~$0.019/day — trivial in dollars, and not the reason it mattered.

A residual web hop costs **$0.000172**.

---

## 10. What is still not true

- **No scheduled wake consumes the spine.** Check 1 is GREEN on the
  *mechanism* and says so inline: a working mechanism, not yet a working loop.
- **The librarian has no data.** `research_source_index.json` does not exist in
  any tree; the shelf-life law is fully tested and a no-op live.
- **The cash letter is deterministic text**, not agent prose.
- **The re-entry status source is a dedup cache**, not the adjudicated
  Surface A book — the budget report says so in its own output.
- **SearXNG's engine pool is degraded** — brave, duckduckgo and startpage all
  suspended on CAPTCHA — so result quality rests on what remains.

---

## Appendix — the recurring failure

Nearly every defect this session was one shape: **a surface reporting on a set
it never read, or a guard not wired to its input.**

Two `total_cash` writers. A notify block reading a 12-row window. A repricer
writing a tree nobody serves. A hygiene sweep run from the wrong cwd. An
evidence refresher that only filled gaps. A freshness guard blind to
`total_cash=` because an underscore is a word character. A cost ledger that
could not see three vendors. A board check whose name promised more than its
code verified. A policy comment that outlived its policy.

Where a fix could not be completed, the debt is recorded in a test that fails
if it grows — `KNOWN_UNGOVERNED`, the check-3 shape rule, the stale-comment
assertion — rather than in a comment nobody re-reads.
