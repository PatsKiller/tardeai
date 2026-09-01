Status:      ACTIVE
as_of:       2026-09-01T17:30:00-04:00
Measured at: CURRENT BUILD_SHA 433511415766f539d45325b88c64d418f0b429e0 (file content)
             dir 433511415-main-exact-phase2-20260901-171402
             origin/main 433511415 · $PROJ 0a591048b (behind — reported; measured CURRENT)
Canonical repo path: docs/ops/CIO_OVERNIGHT_AUTONOMY_SCOREBOARD_2026-09-02.md
Authority:   READ_ONLY_ADVISORY overnight scoreboard. Not a behaviour spec.
             No verdict here authorises an action. MBI_BEHAVIOR = 0.
See also:    docs/ops/litmus/LITMUS_WAKE_2026-09-01.md
             docs/ops/litmus/LITMUS_MONEY_2026-09-01.md
             docs/ops/litmus/LITMUS_COVERAGE_2026-09-01.md
             docs/ops/CIO_M5_FIRST_FIRE_2026-09-01.md
             AGENTS.md §15

# Overnight autonomy scoreboard — 2026-09-02

Gate: **21:00 ET or four SHAs.** Four merge SHAs on `origin/main` before 21:00 —
scoreboard written on that trigger. **No open product PR was merged from this
session.** Open work (#835, #836, #777) is listed, not finished.

---

## Pre-flight

```
worktree      /home/johnclaw/wt-overnight-scoreboard
              docs/overnight-autonomy-scoreboard-2026-09-02 @ 433511415
origin/main   433511415
CURRENT       433511415766f539d45325b88c64d418f0b429e0  [BUILD_SHA file content]
$PROJ         0a591048b  ≠ origin/main (behind) — reported; measured CURRENT
twin PR       none for this title
```

---

## The four SHAs

| # | merge SHA | merged (ET) | title | what it changed |
|---|---|---|---|---|
| **#831** | `9428294ee` | 15:42 | docs(ops): CC/lane/money/coverage/wake litmus | discovery pack only |
| **#832** | `b11086081` | 15:56 | fix(cio): wake_research_persist retains research hits | artifact keeps `hits[]`; idle overwrite no longer erases the fire |
| **#833** | `2fde58aa3` | 16:27 | fix(cio): cash_letter publishes row-sum cash, not CASH_SLEEVE fossil | letter `cash_usd` follows capital_plan, not the sleeve fossil number |
| **#834** | `433511415` | 16:48 | fix(ops): declare portfolio_repricer lane | lane_registry names the money writer; CURRENT pin |

Served release **is** the fourth SHA (`CURRENT` == `origin/main` == `433511415`).

---

## Maturity bar (AGENTS.md §15) — re-measured on CURRENT

Per §15: not a percentage. Admissible here: `NOT_OBSERVED` · `CANDIDATE` ·
documented failure. **No OBSERVED claim.**

| # | proof | verdict | pin / as_of | one sentence |
|---|---|---|---|---|
| **M1** | Research | **NOT_OBSERVED** | `433511415` · 17:26 ET | Research still completes; production writes now exist on EXIT:* records, but they are cadence stamps from the wake path — not a research request changing a named field end-to-end under schedule. |
| **M2** | Advice | **NOT_OBSERVED** | same | Critique → `next_research_question` still not shown on a scheduled council path; council store not re-lit this session. |
| **M3** | Feedback | **NOT_OBSERVED** | same | **Zero** records with `operator_turns` (40 subjects, 135 lines). Turn store still empty. |
| **M4** | Consistency | **NOT_OBSERVED** — failure case | same | `/api/v3/cio/home` still carries **multiple** cash totals in one body (see Money). Naming the failure is not the proof. |
| **M5** | Persistence | **`M5_CANDIDATE`** | same | Unattended `*/5` still fires; dispositions exist and same-cycle `cadence_not_due` repeats; **days-earlier** honor not yet logged. |

### M5 detail (candidate, not observed)

```
future next_eligible_at (8 of 40 subjects), including:
  EXIT:WLDS  until 2026-09-04T17:35:11Z   (13:35 first fire)
  EXIT:LGPS  until 2026-09-04T20:13:57Z
  EXIT:GXAI  until 2026-09-04T20:29:06Z
  EXIT:RGNT  until 2026-09-04T20:34:43Z

wake_research_persist.json  (#832 live on CURRENT)
  schema   WakeResearchPersist@v1
  hits     3   (LGPS / GXAI / RGNT — research_called>0, persisted=1)
  current  as_of 2026-09-01T21:24:39Z  research_called=0 persisted=0
```

Same-cycle honor (flash → skip/cadence_not_due) continues to appear in the log
and in `hits[]`. **Conversion to OBSERVED still requires** an unattended
`cadence_not_due` for a disposition made **days** earlier, on a served pin,
without a hand-run. Not claimed.

**Writer stamp still wrong on those rows:** all four EXIT:* carries
`cc_narrative.writer = migration:deterministic` after live wakes. Open #836
addresses it; **this scoreboard did not merge it.**

---

## Money (from LITMUS_MONEY + live re-measure)

| surface | field | value | verdict |
|---|---|---|---|
| holdings / overview | `total_cash` | **630,513.62** | **LIVE** (`position_rows`) |
| capital_plan / cash_letter.cash_usd | cash | **630,290.46** | **LIVE** dollars after #833; letter source `capital_plan.cash_total_usd` |
| cash_letter.what | prose | still **"Cash sleeve 630784.82."** | **STALE** — number field moved; fossil sentence remains |
| evidence_refs[*].total_cash | ×7 | **630,784.82** | **STALE** — record snapshots still cited |
| cash_as_of block | oldest | **2026-08-14** | **STALE** vs row `as_of` 2026-09-01 (`canonical_mark_as_of` preference) |
| overview `data_as_of` | | **2026-09-01** / `alpaca_taxable_live` | **LIVE** |

**#833 closed the letter-vs-plan dollar split; it did not clear the fossil prose or
the evidence_refs.** #777 (one cash-as-of derivation) remains open — not finished here.

Distinct cash-like values still coexist in one `/api/v3/cio/home` body
(`630784.82`, `630513.62`, `630290.46`, …). M4 stays a documented failure.

---

## Coverage (from LITMUS_COVERAGE — not re-litigated)

RE_ENTER rule holding: desk READY/NEAR ≠ governed RE_ENTER; `verdicts=[]`.
S2/S4 dark this measure; S3 open plans do not cover held equity by design.
No minting from this scoreboard.

---

## Open work — listed, not finished

| PR | title | state | this session |
|---|---|---|---|
| **#835** | fix(cio): admit WATCH instrument records (cognition only) | **MERGED** to `243fa65a8` after this measure | **not touched** — owner merged; scoreboard rebased onto it for INDEX only |
| **#836** | fix(cio): wake persist stamps cc_narrative.writer with the live path | OPEN | **not merged** |
| **#777** | fix(cio): one derivation of cash as-of… | OPEN | **not touched** |

Live numbers above were taken on CURRENT/`origin/main` **`433511415`** (four-SHA gate).
`#835` landed afterward; this file was not re-lit against `243fa65a8`.

Pins honored: no Telegram, no notify-on, no `outcome --apply`, no holdings write,
no `.env`, no `$PROJ` fast-forward, no promote, `BehaviorWriteRefused` untouched.

---

## Headline

**Four SHAs landed. Autonomy bar is still zero of five OBSERVED; M5 is a living
candidate with durable hits and future deferrals; money is less split than
overnight but not single-valued; open product PRs were left for their owners.**
