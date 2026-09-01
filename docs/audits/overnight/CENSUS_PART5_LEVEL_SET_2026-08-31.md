# Census Part 5 — Operator level-set

**Authority:** `READ_ONLY_ADVISORY` · behaviour rail = unconditional raise at
`scripts/lib/cio_instrument_record.py:343` (the name `MBI_BEHAVIOR` is prose only — see §7).
**as_of (this document):** 2026-08-31T04:00Z UTC
**Served pin:** `5e8cad8fb` →
`/home/johnclaw/trade-ai-releases/portfolio-server/5e8cad8fb-main-exact-phase2-20260830-235204`
`[VERIFIED]` `readlink -f …/CURRENT`
**Hub tip at write:** `origin/main` = `5e8cad8fb` (Wave B #743)
**Sources:** Census Part 1 backend (`/home/johnclaw/census-part1-backend`, as_of 2026-08-30T23:30Z,
root `/home/johnclaw/r20-r24-exact-main-deploy` @ `79a3f573`); Census Part 2 Command Center
(`/home/johnclaw/census-part2-cc`, pin window `a9389f67`→`865a4a1d`); Wave A reconcile
(`/tmp/overnight_wave_a_reconcile.md`, as_of 2026-08-31T03:29Z); Wave B PRs #737–#743; `AGENTS.md` §7 / §15.

This is one plain-language document for the operator. It is not a table dump. Every claim is tagged.
Every number carries an `as_of` and the root it was read from.

---

## 1. What runs today

The live path after Wave B deploy, proved from the served pin — not from a checkout.

**Release identity.** The process on port 7777 is the pin on disk.

```
$ readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
/home/johnclaw/trade-ai-releases/portfolio-server/5e8cad8fb-main-exact-phase2-20260830-235204

$ curl -sS http://127.0.0.1:7777/api/v3/cio/home | …['_serving']
pin_match=True  loaded_pin=5e8cad8fb…  current_pin_sha=5e8cad8fb…  data_as_of≈2026-08-31T03:55Z
```

`[VERIFIED]` 2026-08-31T03:55Z. `PROMOTE OK` is not this proof; the live directory and `_serving`
are.

**Operator home.** `/api/v3/cio/home` returns 200 with `canonical_cio_source =
cio.operator_product.current`, a cash block that now carries its own `as_of` (oldest balance, not
composition time), `block_as_of`, and `provenance_footer.model_produced: false`.
`[VERIFIED]` same probe: `cash.as_of=2026-08-03`, `cash.class=D`, earnings list non-empty (e.g. NOC
dated), `reentry_books` present with scope labels (`a` / `b`, not merged).

**Schedulers that still move the system.** Part 1 measured **492** real cron job lines and **65**
enabled tradeai-family user timers (78 unit files, 13 disabled), as_of 2026-08-30T23:15–23:20Z,
from the live crontab / `systemctl --user`. Union of scheduler-named tracked modules: **358**.
Lane registry over HTTP: **56** processes (not 563). `[VERIFIED]` Part 1 §1–§2.

Most cron lines still execute in the **hub** checkout (`$PROJ`), not from `CURRENT` — only ~30 of
492 run from the served release. `[VERIFIED]` Part 1 Finding C-03. A promote therefore does not
reach most scheduled work until those lines are repointed (operator decision; not done tonight).

**Stage proof commands (re-run from the pin, not invent):**

| stage | command that proves it |
|---|---|
| Pin match | `readlink -f …/CURRENT` and `/api/v3/cio/home` → `_serving.pin_match` |
| Cash honesty (Wave B4/B5) | same home payload → `cash.as_of` / `cash_as_of` / `block_as_of.cash` |
| Earnings on the brief (Wave B1) | home → `earnings` list with dated events, commentary only when present |
| Re-entry scope (Wave B6) | home → `reentry_books.a` / `.b` each naming population + question |
| Failure surfaces (Wave B2/B3) | code on pin; natural proof is the next failed orchestrator / aegis row carrying a diagnostic instead of `"errors":"2"` or a COMPLETE after PHASE FAILED — `[CODE]` until that fire |

---

## 2. What is built and unwired

Things that exist in the tree, and either have no schedule, no reader, or no path to an operator
surface.

- **~1,168 modules left `UNKNOWN`** in Part 1 — mostly `NO_INBOUND` (811), plus test-only and
  nonlive-only imports. Not adjudicated as dark because low-cadence jobs and one-day-old modules
  look identical to abandoned ones on a single observation. `[DOC-CLAIM]` Part 1 §8.2,
  as_of 2026-08-30T23:30Z, N=3,449 tracked `.py`, root `79a3f573`.
- **Seven registered stores with no non-test reader**, including
  `cio.operator_product.current` / `.history` (written every 6h; every consumer re-derives instead)
  and `cio.product.history` (written every 5 min by the wake entrypoint; sibling `.current` *is*
  read). `[VERIFIED]` Part 1 §7.
- **Modules one day old at census** (`cio_specialist_artifact`, `cio_notification_policy`,
  `cio_delivery_receipt`, `cio_lesson_bind`) — look unused; recorded `UNKNOWN`, not dark.
- **Archive Batch A** (Wave A2): ONE_SHOT paper-canary + five Command Center pages proposed;
  **not executed**. Archiving is operator-only. `[DOC-CLAIM]` Wave A reconcile 2026-08-31T03:29Z.
- **Lane registry undeclared baseline 563** still stands as inherited debt; live HTTP registry
  shows 56 declared processes. Five retirement reasons remain honest `UNKNOWN`.
  `[DOC-CLAIM]` Wave A4 / Part 1 Finding C-02 (563 was never a job count in-repo).
- **`sys.path` dual-load risk ~20–25 scheduled entrypoints** still carry
  `NORMALIZE_LIB_PATH` / `DUAL_ROOT` / `REWRITE_PYTHON_C` patterns. Morning-brief chain was fixed
  earlier; Wave A3 sample probes from a pinned release under cwd=/tmp exited 0 for several
  unrelated entrypoints — that sizes the normalisation wave, it does not finish it.
  `[DOC-CLAIM]` Wave A3.
- **Schema literals:** 437 versioned; 376 (86%) with zero consumer; 9 (2%) ever read back at
  runtime. `[VERIFIED]` Part 1 §8.3, as_of 2026-08-30T23:25Z.

---

## 3. What appears to work and does not

- **`LIVE_UNCONSUMED` (3 modules).** They run on schedule and write artifacts nobody reads:
  `refresh_operator_product.py` (every 6h from CURRENT), the product-history arm of
  `cio_wake_dispatch_entrypoint.py` (every 5 min), and the `memory.canonical` snapshot writers.
  Compute spent; operator value zero. `[VERIFIED]` Part 1 §7.2.
- **Constants rendered as judgment (Wave A6 → partly fixed in Wave B).**
  `portfolio_implication` was a standing-policy sentence shown as situation guidance; Wave B5
  cleared it from OP/home and stamped `provenance_footer.model_produced: false`. Re-entry
  boilerplate and frozen `next_review` / confidence fields on decision cards remain a Part 2
  finding (7 of 12 fields byte-identical across 25 cards). `[VERIFIED]` live home after B;
  `[DOC-CLAIM]` Part 2 §5 for the frozen-card measurement under earlier pins.
- **Cash `as_of` was a lie; labelling is fixed, dollars are not reconciled.** Wave B4 stamps cash
  with the **oldest** contributing balance (`cash.as_of=2026-08-03` on the live probe). The two
  cash writers can still disagree by tens of thousands of dollars — that is a **correctness**
  finding, deliberately not averaged away. `[VERIFIED]` / `[DOC-CLAIM]` B4/B5 audit note.
- **Silent success / opaque failure (Wave B2/B3 shipped).** Before B: orchestrator failures stored
  `{"errors":"2"}`; aegis could print COMPLETE after PHASE FAILED; CC could stamp
  `canonical_cio_source` after a render exception; underfilled runs still published dashboards.
  Code on pin `5e8cad8fb` makes those claims conditional. Natural unattended proof waits for the
  next real failure. `[CODE]` + `[DOC-CLAIM]` overnight B2/B3 note.
- **Green surfaces that are permanently red by design.** Example: `decision_field_parity.ok =
  false` forever because it demands `recommended_delta_usd`, which the behaviour rail forbids.
  `[DOC-CLAIM]` Part 2 §7.

---

## 4. What nobody can determine

- Whether most of the 811 `NO_INBOUND` modules are truly dark, low-cadence, or waiting to be
  wired — cadence unknown ⇒ verdict `UNKNOWN`.
- Intended cadence for `portfolio.watchlist` and `runtime.maturity` (no cron/systemd found;
  files look stale).
- Aggregate count of all `except ImportError` sites that launder vs legitimately catch — Wave A5
  positive-controlled the class, listed confirmed dual-path instances, and **withheld** the
  aggregate number because the detector cannot cleanly separate laundering guards from broad
  catches. `[DOC-CLAIM]` Wave A5.
- Whether the two holdings copies, dual identity-mint schemes, and dual quote pipes have silently
  disagreed in production recently — Wave A1 classified clusters as LABELING vs CORRECTNESS risk
  and did not merge anything.
- Full end-to-end maturity proofs M1–M5 under AGENTS.md §15 criteria (see §5) — several adjacent
  mechanisms exist; the bar is observed runtime proof from the served release with the command
  quoted, and that bar is not claimed here.

---

## 5. Maturity proofs M1–M5 (`AGENTS.md` §15)

Honest reading. `NOT OBSERVED` is expected.

| # | proof | status |
|---|---|---|
| M1 | Research — system raised a research request itself, it completed, and it changed a named field on a named record (show the diff) | **NOT OBSERVED** |
| M2 | Advice — a critique verdict changed `next_research_question` rather than being logged beside it (show both questions) | **NOT OBSERVED** |
| M3 | Feedback — an operator reply landed on a record and changed the next wake's behaviour (show with/without) | **NOT OBSERVED** |
| M4 | Consistency — every operator-facing number traces to one regenerable producer; no unlabeled dual statement of the same quantity | **NOT OBSERVED** (cash dual writers and frozen card fields remain) |
| M5 | Persistence — a scheduled wake loads the record before acting; a disposition days earlier is still honoured | **NOT OBSERVED** as §15 proof tonight. Commits #723/#724 shipped record-consult machinery and evidence emission `[DOC-CLAIM]`; this level-set does not re-quote an unattended served-release observation that closes the bar. |

A truthful zero-of-five is worth more than a claimed five. Adjacent shipped work (earnings dates on
the brief, cash age labelling, failure diagnostics, re-entry scope labels) improves honesty; it
does not satisfy §15 by itself.

---

## 6. Defect classes (stated once)

### Detector shape — six instances

Before trusting a zero, state what property the detector keys on. These six are working tools that
answered an adjacent question (`AGENTS.md` §7):

1. `ast.parse` compile sweep — keys on parseability; cannot see files Python refuses to import.
2. Catalyst skip aggregate — keys on a count; cannot see its own members.
3. Preconditions board check — keys on artifact *presence*; cannot see artifact *type*.
4. Agent-origination scan — keys on invariance; cannot see generated prose (maximally variable).
5. Root-sensitivity control — two arms; both resolved to one file through a symlink.
6. Synthetic bootstrap probe — one import spelling; not the spelling the failing job uses.

### Controls whose name exceeds their code — five instances

1. `CIO_TELEGRAM_INTERDICT` — name asserts Telegram sends are interdicted; does not gate the family
   that reaches the operator.
2. `BehaviorWriteRefused` — name asserts behaviour writes are refused; covers the InstrumentRecord
   path only, not broker transport.
3. `shadow` (situation detector) — name asserts detections are held back; written into payloads /
   plans / summaries; gates no emission. `notify` is the real gate.
4. `BLOCKED_ACTIONS_WHEN_NOT_READY` — name asserts these actions are blocked; defined once, read
   nowhere.
5. `MBI_BEHAVIOR` — name asserts an env var holding the behaviour rail at 0; **nothing reads it**
   (all occurrences are prose). The rail is the unconditional raise at
   `scripts/lib/cio_instrument_record.py:343`. Stronger than a flag; dangerous to reason about as a
   setting.

`[CODE]` / `[DOC-CLAIM]` `AGENTS.md` §7, as_of document on `origin/main` @ `5e8cad8fb`.

---

## 7. CI coverage (with caveat)

`run_cio_hardening_ci.py` uses a hand-maintained allowlist. `AGENTS.md` records **59 of 1,027 test
files — 5.74%** — behind the only required context on `main` (`as_of` 2026-08-30; that job also runs
other real gates). Historical overnight language has said "~4.9%" / "~5%"; treat any single
percentage as perishable. **Re-measure rather than quote.** Unregistered new tests are invisible to
the required gate (`test_ci_test_coverage_gate.py`). `[DOC-CLAIM]` `AGENTS.md` §8; PR #714 made the
rest of the suite visible and bounded without pretending the allowlist is the whole tree.

---

## 8. Five-doors finding (tonight)

Related to the security incident (keys rotated and dead; remaining incident work is operator-only —
credentials, history scrub, hooks, PR #736). Six regeneration doors that could keep writing
`reports/portfolio_live.html`-class artifacts were shut. Shape, as stated for this close-out:

- **one** crontab-visible scheduler path,
- **four** systemd timers,
- **one** `--cadence all` argument on the portfolio-maintenance pipeline (manual dry-run / test only;
  warns on `--apply`; never scheduled in production — `[CODE]`
  `scripts/pipelines/run_portfolio_maintenance_pipeline.sh`).

Do **not** re-enable any of them from this programme. Incident close-out stays with the operator.
`[DOC-CLAIM]` overnight brief §0 / Wave C instructions; this agent did not re-enumerate the
stopped unit names (out of scope for the incident lane).

---

## 9. Wave A reconcile highlights

From coordinator reconcile as_of 2026-08-31T03:29Z, code pin probed `c3e98d4d…`:

- **A1 duplication — LABELING vs CORRECTNESS.** Labeling: two re-entry books, home dual pipes,
  IP vs OP, dual lineage products, FIGI vs uuid5. Correctness risk: parallel identity-mint schemes,
  memory shadow vs live, lineage `workflow_id` fork, quote dual pipes. **No merges.**
- **A2 archive.** Batch A proposed (ONE_SHOT canary + 5 CC pages). DARK adjudicated = 0. UNKNOWN ≈
  1,168. **Not executed.**
- **A3 `sys.path`.** Sample cron-form probes from pinned release, cwd=/tmp, exited 0 for several
  entrypoints; static dual-load risk ~**20–25** entrypoints remain.
- **A4 lane registry.** 33 declared lanes in the reconcile note; undeclared baseline **563**; keep
  five honest UNKNOWN retirement reasons; operator-readiness→CORRELATED proposed only.
- **A5 except-laundering.** Positive control: `morning_command_digest.py:76`. Confirmed dual-path
  `try: from lib.X / except ImportError: from scripts.lib.X` instances listed (reconcile ~66;
  a pin re-scan of that exact pattern on `5e8cad8fb` found 18 sites — different matcher, same
  class). Aggregate all-ImportError count **WITHHELD**.
- **A6 operator fields.** Constants-as-judgment and cash composition-`as_of` inheritance — **cash
  labelling and provenance footer fixed in Wave B** (B4/B5). Frozen judgment-looking fields and
  dual cash writers remain.

---

## 10. Wave B shipped

| PR | title | merge SHA |
|---|---|---|
| #737 | docs(cio): repoint agent-brief CLAUDE.md cites to AGENTS.md §2 | `fa7386763` |
| #738 | docs: Goose `.goosehints` adapter + §0 parity | `82305296e` |
| #739 | test: align AI work-policy hooks with AGENTS.md hub | `1b8002903` |
| #740 | fix(cio): B1 earnings renderer — dated events on the brief | `49d094032` |
| #741 | fix(cio): B6 stamp re-entry population on both surfaces | `f8502f428` |
| #742 | fix(cio): B4+B5 per-block cash as_of and provenance at display | `8141cdc94` |
| #743 | fix(overnight): B2+B3 failure surfaces | `5e8cad8fb` |

**Live pin after Wave B deploy:** `5e8cad8fb` /
`5e8cad8fb-main-exact-phase2-20260830-235204`. `[VERIFIED]` `readlink -f CURRENT` and
`_serving.pin_match=true` at 2026-08-31T03:55Z.

Not touched tonight: credentials, hooks, secrets guards, git history, PR **#736**, broker
subsystem.

---

## 11. Closing counts — the honest maturity figure

From Census Part 1 verdict table (`as_of` 2026-08-30T23:30Z, root
`/home/johnclaw/r20-r24-exact-main-deploy` @ `79a3f573`, N = **3,449** tracked `.py` files)
`[DOC-CLAIM]`:

| verdict | count | fraction of repo |
|---|---:|---:|
| `LIVE` | **1,248** | **36.18%** |
| `LIVE_UNCONSUMED` | **3** | **0.09%** |
| `DARK` (adjudicated) | **0** | **0%** |
| `UNKNOWN` | **1,168** | **33.86%** |
| tests (no live/dark verdict) | 1,029 | 29.83% |
| `ONE_SHOT` | 1 | 0.03% |

**How to read this.** Roughly a third of the repository is demonstrably live, a third is tests, and
a third is unadjudicated. Zero adjudicated `DARK` is not "nothing is dark" — it is "we refused to
call monthly jobs dead on a Tuesday." The LIVE / UNKNOWN / LIVE_UNCONSUMED ratio above is the
honest maturity figure for this programme. It is more informative than any single percentage the
suite has produced.

Part 2 (operator surface) found the CIO home path **LIVE with stale data** under the census-night
pins, and most other CC routes LIVE as HTTP surfaces; that does not upgrade backend UNKNOWN
modules. `[DOC-CLAIM]` Part 2 §7 route verdicts.

---

## Operator-only (unchanged / still open)

Security incident remainder · PR #736 · re-enabling any stopped timer/cron · approving Archive
Batch A · collapsing dual holdings / identity / quote copies · any broker work · raising the
behaviour rail · inventing reasons for UNKNOWN retirements.
