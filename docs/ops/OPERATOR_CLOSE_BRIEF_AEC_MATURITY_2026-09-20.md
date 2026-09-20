# Operator close brief — Trade AI AEC maturity goal

```
Status: ACTIVE
as_of: 2026-09-20T13:24:00-04:00
Measured at: worktree tip c607cd2ba; live pin 5b7e24c95…114233; email messageId=1a0bfd7aeb84edd4 sent
Canonical repo path: docs/ops/OPERATOR_CLOSE_BRIEF_AEC_MATURITY_2026-09-20.md
Authority: AGENTS.md §15 · §17; operator close brief emailed (messageId=1a0bfd7aeb84edd4)
Supersedes: internal operator-close-brief-1317 (file-only draft)
See also: docs/audits/DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19_LOG.md · AGENTS.md §15 · §17
```

```
Verdict: NOT COMPLETE
as_of: 2026-09-20T13:24:00-04:00 (2026-09-20T17:24:00Z)
Worktree: /home/johnclaw/tradeai-wt-cc-lean-docs-20260915
Branch: cursor/aec-post-1140-remasure-667c @ c607cd2ba
origin/main: b03838001 (#1140 MERGED)
Live pin: 5b7e24c95-main-exact-phase2-20260920-114233
SOURCE_COMMIT / BUILD_SHA: 5b7e24c95f29b94cf1ce2f3366de1f806ec93767
Email: messageId=1a0bfd7aeb84edd4 (operator close brief sent)
```

**Do not mark the goal complete.** No grants invented. No operator reply recorded on the three §17 proposes.

---

## Measured now `[VERIFIED]`

| surface | result |
|---|---|
| Organic stance | **PARTIAL** · `organic_rc=2` · organic=0 · non_organic=2 · total=2 · path=`~/.local/state/tradeai/cio_telegram_stance_holds.jsonl` · awaits Mon–Fri `source=check_investment_send` |
| M1–M5 | **all OBSERVED** · `m1m5_rc=0` · as_of=`2026-09-20T17:19:02Z` · pin above |
| M4 soak / census | streak=**6** soak_ready=YES · census pass=11 warn=**0** fail=0 |
| Soft SLO | **PASS** · soft_unsupported=**14**/1030 · share=**0.014** ≤0.15 · ungrounded_share=0.0 · `soft_rc=0` (`--json --check-slo`) |
| MBI / broker | **HELD** (no agent touch) |
| Stance timers | **armed** Mon 2026-09-21 **06:35** + **09:05** ET (see below) |
| §17 proposes | all three still `Status: PROPOSED` / `Effective-Date: PENDING` |
| Stance timer install propose | `CONFIRMED` (host install already done under overnight cron grant) |

### Organic (stdout)

```
Organic stance hold: PARTIAL organic=0 non_organic=2 total=2 path=/home/johnclaw/.local/state/tradeai/cio_telegram_stance_holds.jsonl
  latest: none — awaits Mon–Fri GO/scalp/proposal hold with source=check_investment_send
  next windows ET: scalp 06:00/06:30 · observe-early 06:35 · GO */15 + proposal */2 from 09:00 · observe 09:05
organic_rc=2
```

### Soft SLO (JSON fields)

```
soft_unsupported=14
soft_unsupported_share=0.014
slo.verdict=PASS  slo.ok=True  slo.results=1030
```

---

## Open PRs (stack)

| PR | state | base ← head | notes |
|---|---|---|---|
| [#1142](https://github.com/PatsKiller/tardeai/pull/1142) | **OPEN** | `main` ← `cursor/aec-post-1140-remasure-667c` @ `c607cd2ba` | tip includes #1144 merge; cio-hardening in progress / others pass at last measure |
| [#1144](https://github.com/PatsKiller/tardeai/pull/1144) | **MERGED** @ 2026-09-20T17:21:32Z | into #1142 tip (`c607cd2ba`) | fix: stance `active_days` weekday ints |

Merge order remaining: **#1142 → main** when green. Docs/units/lanes — live pin need not move for goal remasure; promote only if served code must change.

---

## Stance timers `list-timers` `[VERIFIED]`

```
NEXT                        LEFT UNIT                                       ACTIVATES
Mon 2026-09-21 06:35:14 EDT  ~17h tradeai-stance-organic-observe-early.timer → tradeai-stance-organic-observe.service
Mon 2026-09-21 09:05:23 EDT  ~19h tradeai-stance-organic-observe.timer       → tradeai-stance-organic-observe.service
```

Both **enabled** / **active (waiting)** since 2026-09-20 13:11:32 EDT. Propose file `docs/ops/PROPOSED_INSTALL_STANCE_ORGANIC_OBSERVE_TIMERS_2026-09-20.md` → **CONFIRMED**.

---

## §17 propose statuses (unchanged — no grant)

| park | file | Status |
|---|---|---|
| Bitemporal `:5432` | `docs/ops/PROPOSED_BITTEMPORAL_PROD_5432_2026-09-20-1051.md` | PROPOSED · PENDING |
| Hermes RETIRE | `docs/ops/PROPOSED_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE_2026-09-19.md` | PROPOSED · PENDING |
| Relationship spine | `docs/ops/PROPOSED_RELATIONSHIP_SPINE_SOURCES_2026-09-19.md` | PROPOSED · PENDING |
| Stance timer install | `docs/ops/PROPOSED_INSTALL_STANCE_ORGANIC_OBSERVE_TIMERS_2026-09-20.md` | **CONFIRMED** (not blocking) |

---

## Exact tokens that close the remaining gates

Record the token on the propose file (and ledger). **DEFER / REJECT / continue-park close the goal gate** without starting a build. **APPROVE_*** starts a follow-on PR — not auto-apply. Agents invent no grants.

### A. Three §17 gates (one line each)

| gate | reply exactly one of |
|---|---|
| Bitemporal | `DEFER` · `REJECT` · `APPROVE_BITTEMPORAL_PROD_PREREQS` |
| Hermes | `DEFER` · `WIRE` · `APPROVE_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE` |
| Relationship | `DEFER` · `REJECT` · `APPROVE_RELATIONSHIP_MANUAL_ONLY` · `APPROVE_RELATIONSHIP_SOURCE_<N>` (name 1/2/3) |

**Continue-park / close-without-build (copy-paste):**

```
DEFER
DEFER
DEFER
```

(one `DEFER` on each of the three propose files above — closes O1/O6 parks for goal accounting.)

### B. Optional stance park (if not waiting for Monday organic)

```
PARK_STANCE_AWAIT_ORGANIC
```

or

```
CLOSE_STANCE_WONT_WAIT
```

(with reason). Else: wait Mon natural hold → `python3 scripts/report_organic_stance_hold.py` **exit 0**.

---

## Goal complete iff (all three)

1. Organic stance exit **0** **or** explicit stance park token above, **and**
2. All three §17 proposes settled (`DEFER` / `REJECT` / grant / continue-park recorded), **and**
3. Fresh remasure still: M1–M5 OBSERVED · soft ≤0.15 · MBI=0.

**Today:** (1) and (2) open · (3) holds. **NOT COMPLETE.**
