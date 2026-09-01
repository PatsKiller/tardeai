Status:      ACTIVE
as_of:       2026-08-31T23:36:49-04:00 (America/New_York) — measurement window 23:12 → 23:37 ET
Measured at: served release pin `d276657b7` — CURRENT -> /home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546 (symlink mtime Aug 31 22:56 EDT, unchanged across this audit); audit worktree repo sha `c0ae53cf1` at open, `d660d7cea` mid-run, `542cb502d` at close (the coordinator moved the worktree onto `overnight/maturity-maceration-2026-09-01` and committed under me — see Corrections)
Canonical repo path: docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md
Authority:   dated re-measurement of AS-IS node status; not a behaviour spec
Supersedes:  none — this RE-MEASURES docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md, it does not replace it
See also:    docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md, AGENTS.md §13.4 §15

# CIO dark contracts — re-measurement, 2026-09-01

Four parts: (1) the AS-IS node map re-measured; (2) store splits by hash;
(3) who calls `load-by-subject` on a timer; (4) the real Telegram send gate.

**Roots used throughout.** Every measurement below names one of these:

```
REL   /home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546
      the SERVED release. CURRENT resolves here. git pin d276657b7.
PSTATE /home/johnclaw/trade-ai-releases/persistent-state
      REL/logs and REL/data/{cio,health,runtime} are SYMLINKS into here.
PROJ  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
      the main checkout; `$PROJ` in crontab.
WT    /home/johnclaw/tradeai-wt-final-operator-convergence
      this audit worktree. No runtime reads from it.
TMPWT /tmp/wt-cio-phase-a
      a FOURTH root. One production cron line runs from it — §2.5.
```

Served-release pin, verified at open and again at close:

```
$ readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
/home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546
$ cd $REL && git log -1 --format='%H %s %ci'
d276657b721011ae126d234b6300c9225d651a3e Merge pull request #810 from PatsKiller/feat/cio-p1-load-by-subject 2026-08-31 22:55:27 -0400
```
`[VERIFIED]` as_of 2026-08-31T23:12, 23:22 and 23:36 ET, root REL. **It did not rotate during this audit** — the symlink mtime read `Aug 31 22:56` at all three checks. Every runtime claim below is therefore attributable to this one pin.

---

# PART 1 — the AS-IS node map, re-measured

`docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md` is a dated reading whose own
header says *"re-measure before quoting any of them."* This is that re-measurement,
32 hours later. Legend unchanged:

```
█  LIVE     runs on schedule, produces durable output, verified at runtime
▓  PARTIAL  runs, but incomplete, degraded, or its consumer is unproven
░  UNWIRED  the code exists and is correct; nothing calls it or consumes it
✗  DARK     never executed, or produces nothing, in recorded history
```

## 1.1 THE MOVERS — headline, both directions

Eight nodes moved in 32 hours. **Four advanced, four regressed.** A regression is
as important as an advance, and three of the four regressions are cases where the
2026-08-30 reading was simply too generous — the node had not moved; the
measurement had been wrong.

### Advanced (4)

| node | 08-30 | tonight | what changed | tag |
|---|---|---|---|---|
| **OUTCOME edge / `OutcomeCheckpoint@v1`** | ✗ DARK | **▓ PARTIAL** | 1,127 unique checkpoints (was ~791); **158 RESOLVED**; `OUTCOME_PENDING_DATA` collapsed from "a large block" to **6**, each with a named reason (`no_price_history_either_end`). 157 outcome observations carry a real realized price delta. An hourly settler now exists in cron (line 964). | `[VERIFIED]` |
| **LESSON / HYPOTHESIS** | ▓ (all research-fed) | **▓ PARTIAL** | The **first outcome-derived lesson exists**, n=1 of 345. The doc's headline *"the system learns from WHAT IT READ, not from WHAT HAPPENED"* is now false **by exactly one lesson**. 343/345 = 99.4% still research-fed. | `[VERIFIED]` |
| **`SpecialistArtifact@v1-lite`** | ░ UNWIRED (no formal type) | **▓ PARTIAL** | A formal type now exists — `cio_specialist_artifact.py` declares the schema, `PROVIDERS`, `OUTCOMES`, a raising `build()` and a `validate()`, and is registered as `cio.specialist_artifacts`. The doc's *"no formal type — informal dict convention"* is out of date. The N=100 gate still **FAILS**. | `[VERIFIED]` |
| **`MODEL_CALL_RECORDED`** | ✗ (receipt with no call) | **✗ DARK, but the phantom receipt is FIXED** | The lane is still dark — no model is called. But the false receipt **stopped firing on 2026-08-28T13:46:33Z**; hundreds of syntheses have completed since with zero receipts. `LLM_GLOBAL_DAILY_USD_CAP=0.50` is now set. | `[VERIFIED]` |

### Regressed (4)

| node | 08-30 | tonight | what changed | tag |
|---|---|---|---|---|
| **`CIOCouncilSynthesis@v1`** | █ LIVE | **░ UNWIRED** | Exactly **one** artifact of this schema exists, `cio_council_synthesis.json`, mtime **2026-08-26 11:46 ET — five days stale**. Its only production caller is `cio_wave3b_report.py`, which is **not in crontab**. `DISPUTED` appears **zero** times, so *"DISPUTED stands"* is unfalsifiable on the served data. | `[VERIFIED]` |
| **NOTIFICATION POLICY — `IMMEDIATE`, `COMMAND_CENTER_ONLY`** | █ LIVE (all four) | **✗ DARK (2 of 4)** | Over 2,046 scanner wakes and 6,246 candidate decisions: `IMMEDIATE` **0 all-time**, `COMMAND_CENTER_ONLY` **0 all-time**. Only `SUPPRESSED` (4,611) and `DIGEST` (38) have ever fired. Separately, the `NotificationPolicy@v1` module is not on the live delivery path at all (§4.5). | `[VERIFIED]` |
| **DELIVERY RECEIPT (`DeliveryReceipt@v1`)** | █ LIVE | **░ UNWIRED** | **n=1**, written 2026-08-29 14:30 ET, and that single row is `SUPPRESSED / would_send=false`. 114 real Telegram deliveries produced zero receipts. Writer `cio_wave3c_report.py` is not in crontab. *(The DEDUPE half is genuinely live — §1.3 row 9.)* | `[VERIFIED]` |
| **OPERATOR turn / `S0_OPERATOR_CONVERSE`** | ▓ ("the turn lands on the record and is read back") | **✗ DARK** | **Zero `operator_turns` on any instrument record** — 131 record lines, 40 subjects, 0 turns, including superseded lines. The dedicated turn store `data/cio/cio_operator_turns.jsonl` **does not exist in any root**. The doc's *"no scheduled wake proven to consume it"* is weaker than reality: **there is nothing to consume.** | `[VERIFIED]` |

**Also moved, and it is the reason this audit exists:** `load-by-subject`
░ UNWIRED → **(b) CODE-WIRED, RUNTIME-UNPROVEN at pin d276657b7** for the
pre-claim consult, and **still (a) dark** for the `ResearchNeedDecision.decide()`
half that PR #810 was named for. Full treatment in Part 3; the M5 verdict belongs
to Worker A and is not issued here.

## 1.2 A measurement trap that fired twice tonight — read before trusting any row

`REL/data/cio`, `REL/data/runtime`, `REL/data/health` and `REL/logs` are
**symlinks** into `PSTATE` (§2.0). `grep -r` and `find` do **not** follow
symlinks encountered during traversal.

```
$ grep -rl "CIOCouncilSynthesis" $REL/data/          # naive traversal
                                                     (no output)
$ grep -rl "CIOCouncilSynthesis" $PSTATE/data/cio/   # resolved root
/home/johnclaw/trade-ai-releases/persistent-state/data/cio/cio_council_synthesis.json
```
`[VERIFIED]` as_of 2026-08-31T23:40 ET.

**The first form returns nothing and would have been reported as "zero artifacts,
never produced" — a ✗ DARK verdict founded entirely on a traversal artifact.**
It very nearly was. The true reading is one stale artifact, which is ░ UNWIRED,
not ✗ DARK. Every row below was taken from a resolved root; where a row says
ABSENT it was checked at `PSTATE`, `PROJ` and `REL` separately.

## 1.3 The rows

Every row carries node · 08-30 symbol · tonight's symbol · command · as_of · root · tag · note.
Root shorthand per the header. All `as_of` are America/New_York on 2026-08-31.

| # | node | 08-30 | tonight | command | as_of | root | tag | note |
|---|---|---|---|---|---|---|---|---|
| 1 | OUTCOME edge / `OutcomeCheckpoint@v1` | ✗ | **▓** | `python3` last-write-wins census over `outcome_checkpoints.jsonl` | 23:39 | PSTATE | `[VERIFIED]` | `unique=1127 {SCHEDULED:877, RESOLVED:158, NOT_PRICE_RESOLVABLE:86, OUTCOME_PENDING_DATA:6}`. Edge no longer dark — but see 1a. |
| 1a | — the hourly settler | (n/a) | **▓** | `crontab -l \| grep -n resolve_due` → line 964 `20 * * * * … resolve_due_checkpoints.py --apply`; then `grep '^resolved' logs/resolve_due_checkpoints.log \| uniq -c` | 23:18 | crontab + PSTATE | `[VERIFIED]` | **23 logged runs, every one `resolved 0`.** All 152 real resolutions came from a single manual triage at 13:07Z today. Trap (b) resolved: "ran and found nothing due", not "never started". |
| 2 | LESSON / HYPOTHESIS | ▓ | **▓** | `wc -l lesson_candidates.jsonl` + provenance census | 23:19 | PSTATE | `[VERIFIED]` | 345 rows / 344 ids. Field counted: **`lesson_provenance`** — absent on 337, `RESEARCH_DERIVED` 7, `OUTCOME_DERIVED` **1**. `supporting_outcome_ids` non-empty on **0**; the one outcome lesson links via `correlated_outcome_ids`. Producer scheduled (cron 965, 06:40). |
| 3 | `AgentView@v1` / `AGENT_COMMITMENT@v1` | (no producer) | **✗ DARK** | `grep -rl AGENT_COMMITMENT $PSTATE/data/cio/` → no output; 16 code hits, all constants/tests | 23:20 | PSTATE + REL | `[VERIFIED]` | Zero instances. **No write site exists**, so trap (b) resolves to "never started". `cio_lesson_bind.py:36` actively **forbids** the status. |
| 4 | Librarian grade / stale-out index | ░ | **░** | `ls -la {REL,PSTATE,PROJ}/data/cio/research_source_index.json` | 23:20 | all three | `[VERIFIED]` | **Absent in all three roots.** `SourceLibrarian@v1` declares the full shelf-life law (`STALE_AFTER_DAYS {A:365,B:90,C:30,D:14,X:0}`) and writes into a file that does not exist. Also **not registered** in `CanonicalStoreRegistry` — an unregistered store. Unchanged since 08-30. |
| 5 | `SpecialistArtifact@v1-lite` | ░ | **▓** | `wc -l cio_specialist_artifacts.jsonl`; re-ran `scripts/cio_specialist_sample_audit.py --limit 100` | 23:25 | PSTATE + REL | `[VERIFIED]` | Formal type now exists. On disk: **2 artifacts, both `workflow_id: null`**. Gate re-run tonight: `same_workflow_id 0.66`, `same_instrument_record 0.59`, `orphan_workflow 34`, `orphan_instrument 41`, `workflow_id_stamped_on_live 0`. vs 08-30: workflow bind 50→66% **improved**, instrument bind 64→59% **regressed**. Gate demands zero orphans — **still FAILS**. 98/100 of the "sample" is fixture projection. |
| 6 | LLM lane / `MODEL_CALL_RECORDED` | ✗ | **✗** | event-type census of `cio_runs.jsonl` (3,395 events) | 23:21 | PSTATE | `[VERIFIED]` | `CIO_RUN_MODEL_CALL_RECORDED = 46`, **latest 2026-08-28T13:46:33Z**, while `CIO_RUN_COMPLETED` ran at 23:18 ET tonight. All 46 carry `cost_usd: 0.001` — one hardcoded constant, **no token fields at all**. Receipt fixed at `cio_run_worker.py:908` (`dispatch_kind = DETERMINISTIC_PRODUCT`). Lane still dark: no model is called. |
| 6a | — the cost-cap that failed it closed | (n/a) | **cleared** | `grep '^LLM_GLOBAL_DAILY_USD_CAP' /run/user/1000/tradeai/env` → `0.50` | 23:21 | `/run/user/1000/tradeai/env` | `[VERIFIED]` | The ~5-week fail-closed cause is gone from the env file. **UNKNOWN** whether it is exported into every cron lane — not verified per job. |
| 7 | `CIOCouncilSynthesis@v1` | █ | **░ UNWIRED** | `grep -rl CIOCouncilSynthesis $PSTATE/data/cio/`; `ls -la`; `grep -c DISPUTED` | 23:40 | PSTATE | `[VERIFIED]` | **One** artifact, 11,113 B, **mtime 2026-08-26 11:46 ET**. `DISPUTED` count **0**. Sole production caller `cio_wave3b_report.py`, **not in crontab**. The sibling `.jsonl` (4 rows, 993 B) is a **different schema** from `cio_committee.py`. **Correction: an earlier pass of this audit read "zero artifacts" — that was the §1.2 traversal trap.** |
| 8 | NOTIFICATION POLICY — SUPPRESSED | █ | **█ LIVE** | class census of `cio_notification_audit.jsonl` on field `notification_class` | 23:41 | PSTATE | `[VERIFIED]` | 4,611 all-time / **1,504 last 7d**, latest 2026-08-31T13:21:09Z. |
| 8a | — DIGEST | █ | **█ LIVE** | same | 23:41 | PSTATE | `[VERIFIED]` | 38 all-time / **13 last 7d**, latest 2026-08-31T13:11:09Z. |
| 8b | — IMMEDIATE | █ | **✗ DARK** | same | 23:41 | PSTATE | `[VERIFIED]` | **0 all-time.** Trap (b) resolved: not "never started" — the scanner ran 2,046 times and routed 99.4% to SUPPRESSED. The module docstring admits it: *"nothing in this PR returns [IMMEDIATE] without an explicit operator-directed flag."* |
| 8c | — COMMAND_CENTER_ONLY | █ | **✗ DARK** | same | 23:41 | PSTATE | `[VERIFIED]` | **0 all-time.** |
| 8d | — the `NotificationPolicy@v1` module itself | █ | **░ UNWIRED** | `grep -rn cio_notification_policy`; `ls cio_notification_policy.jsonl` | 23:21 | REL + PSTATE | `[VERIFIED]` | Declared store **does not exist**; two unscheduled report scripts + one dashboard import it; the live producer never calls it. Full trace §4.5. |
| 9 | DELIVERY RECEIPT — `DeliveryReceipt@v1` | █ | **░ UNWIRED** | `wc -l cio_delivery_receipts.jsonl`; `cat` | 23:19 | PSTATE | `[VERIFIED]` | **n=1**, 410 B, mtime 2026-08-29 14:30 ET, `decision: SUPPRESSED, would_send: false`. Writer not in cron. By construction it can never record a send. |
| 9a | — DEDUPE / the real delivery lane | █ | **█ LIVE** | outbox event census + `cat cio_outbound_dedupe.jsonl` | 23:19 | PSTATE | `[VERIFIED]` | `NOTIFICATION_ENQUEUED / DELIVERY_CLAIMED / DELIVERY_CONFIRMED` = 115 each, latest 2026-09-01T00:22:02Z; dedupe ledger 4 live keys, TTL-pruned. **This half is genuinely live.** Note `cio_telegram_receipts.jsonl` (160 rows) is stale since 2026-08-18. |
| 10 | `CognitionNoOp` | ▓ | **✗ never observed firing** | raise site `cio_instrument_record.py:438`; `grep -rl CognitionNoOp` over 4,274 log files in PSTATE+PROJ | 23:21 | REL + PSTATE + PROJ | `[VERIFIED]` | Zero hits. Trap (b): **"never started"** — `cio_instrument_records.jsonl` has had **no append in 36 h** (mtime 2026-08-30 10:58:17), so the cognition write path is not being exercised. `[CODE]`-true, runtime-unobserved. |
| 10a | `MBI_BEHAVIOR` rail | █ | **█ CONFIRMED** | `grep -n "raise BehaviorWriteRefused"` at REL **and** PROJ | 23:24 | REL + PROJ | `[VERIFIED]` | **Line 390 in both roots** — AGENTS.md's citation is exact. Nuance: it is syntactically guarded by `if forbidden:` at `:388`, so it fires only when a caller passes a behaviour kwarg; zero log hits means the rail has never been exercised in production. Read only; nothing modified. |
| 10b | `MBI_COGNITION = 1` | ▓ | **▓ a constant, not a mechanism** | `grep -rn "MBI_COGNITION"` | 23:21 | REL | `[CODE]` | A module constant in `cio_instrument_record.py:34`, `cio_research_budget.py:59`, `cio_residual_web.py:66` — and **inconsistently `MBI_COGNITION = 0`** in `cio_preconditions_board.py:54`. Nothing reads it as a gate. |
| 11 | `CanonicalStoreRegistry@v1` | █ | **█ LIVE** | `resolve_store()` over all `STORES` from REL; `cio_missing_stores_g6.py --host-check` | 23:24 | REL → PSTATE | `[VERIFIED]` | 34 declared stores, `production_state_root()` → PSTATE (matches the symlinks). **6 of 34 missing in every root** (`cio.decisions`, `cio.lesson_binds`, `cio.notification_policy`, `learning.weekly`, `notifications.outbox`, `runtime.audit_claims`). Loaded by scheduled jobs (cron 964 hourly, 965 daily, 631 every 15 min). Its own drift tool honestly reports 3 of the 6. Stalest present: `portfolio.watchlist` 115 days, `runtime.maturity` 65 days. |
| 12 | S0_OPERATOR_CONVERSE / OPERATOR turn | ▓ | **✗ DARK** | `operator_turns` census over `cio_instrument_records.jsonl`; `ls cio_operator_turns.jsonl` in all roots | 23:39 | PSTATE | `[VERIFIED]` | `lines=131 total_operator_turns=0 records_with_turns=0`. Turn store **absent in every root**. 9 S0 plans exist but the newest is 2026-08-20 — **started, then stopped**, not "never started". The read-back site `cio_research_preflight.py:53` iterates an array empty on all 40 subjects. |
| 13 | Catalyst family completion | ▓ ~1.5% | **▓ 1.49%** | re-ran `scripts/cio_event_lifecycle_census.py --root $REL` | 23:22 | REL | `[VERIFIED]` | `catalyst_earnings: accepted 39,478 → full 1.49% / processed 1.42%`. Unchanged. `min_full_lifecycle=1.49%`, `weighted=2.16%` (was 2.17%). |
| 13a | — the non-symbol-in-symbol-column defect | ▓ | **fix in code, NOT in the served data** | re-ran `scripts/build_catalyst_graph.py --diagnose-staleness` | 23:22 | REL → PSTATE | `[VERIFIED]` + `[CODE]` | Guards exist (`symbol_validation.py:119 is_research_directive_slug`, `catalyst_graph.py:110`). But `graph age_h=105.4, scheduled=False — build_catalyst_graph.py is NOT in crontab`. The 35,928 `symbol_not_registered` drops are the **pre-filter** tally. The 1.49% cannot move without an operator-gated `--apply` rebuild. |
| 14 | Residual web / engine pool | ▓ DEGRADED | **▓ DEGRADED, quantified** | `docker logs --since 24h searxng \| grep -oE "ERROR:searx\.engines\.[a-z0-9_]+…"` | 23:23 | live `searxng` container | `[VERIFIED]` | **4 engines suspended in 24 h; 3 in the last hour.** duckduckgo 291 CAPTCHA, brave 87 rate-limit, startpage 24 (3600 s suspension as of 23:11 ET), wikipedia 3. No outbound search was issued — read from the service's own logs. |
| 14a | — the durable health file | (not in doc) | **✗ never written** | `ls -la $REL/data/runtime/search_health.json`; `find … -name "search_health*"` | 23:23 | REL + PSTATE + PROJ | `[VERIFIED]` | `search_health_degradation.py` declares `data/runtime/search_health.json` as the durable status *"so a dry reader (and CI) can report per-source state without probing"*. **It has never been written.** So the degradation is real, ongoing, and **nothing on any research record says so**. |

## 1.4 What did NOT move

* The librarian index (row 4) — absent in all three roots, exactly as on 08-30.
* Catalyst completion (row 13) — 1.49%, statistically identical.
* The engine pool (row 14) — still CAPTCHA-degraded, now with numbers.
* **The doc's closing count.** *"Agent-originated fields reaching any operator
  surface: zero"* is unchallenged by anything measured tonight. Every producer
  that could originate a non-deterministic field — `cio_wave3b_report.py`,
  `cio_wave3c_report.py`, `build_catalyst_graph.py`, the S0 turn writer, any
  model call — is either absent from crontab or has produced nothing.

## 1.5 The one-sentence version, re-measured

The 08-30 doc says: *"The nervous system is built and running; the cortex was
never wired."* That still holds, with one clause weakened and one strengthened:

* **Weakened:** the outcome edge is no longer dark. 158 checkpoints are RESOLVED,
  157 observations carry a real price delta, and exactly one lesson is
  outcome-derived. The cortex has fired once.
* **Strengthened:** the operator half is worse than recorded. The turn does not
  land on the record — there are zero operator turns on any of the 40 subjects,
  and the turn store does not exist. `S0_OPERATOR_CONVERSE` is not a loop whose
  consumer is unproven; it is a loop with no input.

**And a structural note that outranks both.** Three of tonight's four regressions
— council synthesis, delivery receipt, notification policy — share one shape:
*a correct, tested module whose only caller is a report script that is not in
crontab.* That is not four separate defects. It is one defect with four
instances, and it is the same one Part 3 finds inside PR #810.
---

# PART 2 — store splits, hashes only

**AGENTS.md §0 rule 5 and §17 apply to every row below. Nothing here was
remediated, reconciled, copied or chosen between. Paths, sizes, mtimes, sha256
and record counts only. Collapsing any of these is an OPERATOR-ONLY decision:
proposed at §2.7 and stopped there.**

## 2.0 The topology the AS-IS doc does not have — and the traversal trap

"Checkout-relative" implies two roots. There are **four**, and the one that
actually holds CIO state is not in the AS-IS doc at all.

```
$ ls -ld $REL/logs $REL/data $REL/data/cio $REL/data/runtime $REL/data/health
lrwxrwxrwx  … $REL/logs         -> /home/johnclaw/trade-ai-releases/persistent-state/logs
drwx------  … $REL/data                                        <-- a REAL per-release directory
lrwxrwxrwx  … $REL/data/cio     -> /home/johnclaw/trade-ai-releases/persistent-state/data/cio
lrwxrwxrwx  … $REL/data/runtime -> /home/johnclaw/trade-ai-releases/persistent-state/data/runtime
lrwxrwxrwx  … $REL/data/health  -> /home/johnclaw/trade-ai-releases/persistent-state/data/health
```
`[VERIFIED]` as_of 2026-08-31T23:13 ET, root REL.

> **Traversal trap, recorded because it produced a wrong number before it was
> caught.** A bare `find` under the release tree does **not** follow these
> symlinks and reports **zero** copies of files that plainly exist. Every sweep
> below used `find -L` or `readlink -f`-resolved roots, and says which.
> **A split count that is an artifact of traversal is not a measurement.**

The declared root, read from the served release `[CODE]`
(`$REL/scripts/lib/persistent_state_root.py:26`):

```python
GOOD_PERSISTENT_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"
DEFAULT_LEGACY_SOURCE = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
```

## 2.1 The cause, in one artifact and one count

```
$ cat /home/johnclaw/trade-ai-releases/persistent-state/PERSISTENT_STATE_ROOT.json
{
  "schema": "PersistentStateRoot@v1",
  "as_of": "2026-08-26T14:31:57+00:00",
  "path": "/home/johnclaw/trade-ai-releases/persistent-state",
  "legacy_source": "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild",
  "legacy_read_only": false,
  "n_copied": 16771,
  "mismatches": [],
  "note": "Copy verified. Source tree not deleted. LEGACY_MIGRATION_SOURCE until soak."
}
$ crontab -l | grep -oE '/home/johnclaw/(trade-ai-v12-rebuild/trade-ai-v12-rebuild|trade-ai-releases/portfolio-server/CURRENT|trade-ai-releases/persistent-state)' | sort | uniq -c | sort -rn
    266 /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
     45 /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
$ crontab -l | grep -c .
953
```
`[VERIFIED]` as_of 2026-08-31T23:33 ET, roots PSTATE and the user crontab.

**`"legacy_read_only": false`, plus 266 cron invocations rooted at PROJ against
45 at CURRENT, and zero naming `persistent-state`.** The migration copied
16,771 files on 2026-08-26 and deliberately left the source writable. Five days
later, both trees are still being written. This is not four incidental splits —
it is a **continuous systemic dual-write**, and it is the mechanism behind every
row in §2.2–§2.4.

## 2.2 The four claimed splits, re-measured

| # | claimed store | verdict | detail |
|---|---|---|---|
| 1 | release-local logs | **DIVERGE — and it is a 3-way** | §2.2.1 |
| 2 | two holdings copies | **the named store AGREES; six others in the family diverge** | §2.2.2 |
| 3 | risk state | **DIVERGE — in the opposite direction to the logs** | §2.2.3 |
| 4 | evening packet | **DIVERGE, 6 days stale, 3-vs-9 content keys** | §2.2.4 |

### 2.2.1 Logs

| path | size | mtime | lines | sha256 |
|---|---|---|---|---|
| `PSTATE/logs/cio_wake_dispatcher.log` (= `REL/logs/…`) | 1442365 | 2026-08-31T23:13:05-04:00 | 11879 | `56139914fdf7d006838c33a83452b466152ee35020d6a56b9c060fcbabc7839a` |
| `PROJ/logs/cio_wake_dispatcher.log` | 74581 | 2026-08-14T16:55:05-04:00 | 787 | `bbae8e38a8a95c65a5bcdf39514b7f88d039fc5bbdb536f42b8e470aedc16470` |
| `PSTATE/logs/cio_decisions.log` | — | **ABSENT** | | |
| `PROJ/logs/cio_decisions.log` | 26253 | 2026-08-07T07:00:02-04:00 | 200 | `92eae044c091d854186e664dfc8cbdc44d4cfab1868207ca2e655035d062f73b` |
| `/home/johnclaw/logs/cio_decisions.log` | 270 | 2026-05-27T07:00:01-04:00 | 5 | `bc620a0abec0778319887758ec702847e812b4df49688905df25770bfad58cc5` |

`[VERIFIED]` sha256 pair for `cio_wake_dispatcher.log` re-run by me directly,
as_of 2026-08-31T23:13 ET. **`cio_decisions.log` is a three-way split and the
served release has no copy at all** — a fifth root, `/home/johnclaw/logs`.

Whole-tree log intersection: **33 files shared, 1 agrees, 32 diverge.** 16
PSTATE-only, 7,560 PROJ-only. Several diverge while **both sides are live
simultaneously** — `claude_escalation.log`, `safe_flock_events.jsonl`,
`hermes_scope_governor.log` all carry mtimes within minutes of each other on
both roots. That is concurrent dual-writing, not a stale fork.

### 2.2.2 Holdings — the doc names the copy that agrees

| path | size | mtime | sha256 | records |
|---|---|---|---|---|
| `PSTATE/data/portfolios/state/holdings.json` | 232863 | 2026-08-31T16:52:14-04:00 | `c0fc4e57cdf06e7eed485740e213fe94cd54c344a321d4fd7ef2d077038b3131` | `holdings[]` = 30 |
| `PROJ/data/portfolios/state/holdings.json` | 232863 | 2026-08-31T16:52:14-04:00 | `c0fc4e57cdf06e7eed485740e213fe94cd54c344a321d4fd7ef2d077038b3131` | `holdings[]` = 30 |

**AGREE** — byte-identical, separate inodes (4404220 / 2930606, both `nlink=1`),
so genuinely dual-written and coincidentally in sync right now. It is the
registry's only `AUTHORITATIVE` store.

The holdings store that **DIVERGES**:

| path | size | mtime | sha256 | `as_of` inside |
|---|---|---|---|---|
| `PSTATE/data/cio/holdings_snapshot_latest.json` | 4901 | 2026-08-31T23:05:21-04:00 | `91eb08cb02a64cda5bcf1ba25213ca993b648c0568645a9859867af7db7cf8bc` | 2026-08-29 |
| `PROJ/data/cio/holdings_snapshot_latest.json` | 4897 | 2026-08-26T10:24:37-04:00 | `ae76681eb39b8f13db151edd4acfe477c27f683588194e0bcc7c376a17d4f7ca` | 2026-08-26 |

Plus four more in the family: `holdings_symbol_state.json`,
`ai_deep_holdings.json`, `hermes_holdings_lifecycle.json`,
`hermes_holdings_lifecycle_audit.jsonl`, `holdings_agent_enqueue_latest.json`.
**"Two holdings copies" is six divergent holdings stores, and the one named is
the one that currently agrees.**

### 2.2.3 Risk state

| path | size | mtime | sha256 | `generated_at` inside |
|---|---|---|---|---|
| `PSTATE/data/portfolios/state/risk_management.json` | 10554 | 2026-08-30T15:15:40-04:00 | `b87c658b49a51beae2ac8c407bbf47fafcdf6f4e37f507e2383a67933e2fdd2d` | 2026-08-30T11:30:02Z |
| `PROJ/data/portfolios/state/risk_management.json` | 10541 | 2026-08-31T06:15:02-04:00 | `bc60b831b47a75406e27d620be2ae104fd2fd078a49548caf320ec64477af1a7` | 2026-08-31T10:15:02Z |

**DIVERGE — and PROJ is 20 hours NEWER than the served copy.** There is no
consistent "one root is stale" story; direction varies per store. A remediation
that picked a root globally would destroy data in one direction or the other.
Also `data/portfolios/state/data_broker/risk_snapshot.json` is REL-only (12928 B,
2026-08-31T23:22:17-04:00), absent from PROJ.

### 2.2.4 Evening packet

| path | size | mtime | sha256 | `cio` sub-keys |
|---|---|---|---|---|
| `PSTATE/data/runtime/aegis_evening_packet.json` | 6124 | 2026-08-31T20:00:13-04:00 | `5d7733bea2d89d9974e90d87a2e49bd5a5b79e6ea7b4d0acd4747cb935618cdc` | 9 |
| `PROJ/data/runtime/aegis_evening_packet.json` | 1704 | 2026-08-25T20:00:17-04:00 | `71a046be5999da97f84db3614fa7845bd49d83896740ce00921009e7f9237ae7` | 3 |

**DIVERGE.** 6-day-stale fork, 3.6× size delta. Crontab comment at line 972 —
*"cio_command_center.py:995 loads data/runtime/aegis_evening_packet.json"* —
means a command-centre process resolving PROJ reads the 3-key version.

## 2.3 The systematic sweep — the count the doc says is unknown

Scope: `data/cio`, `data/runtime`, `data/health`, `data/portfolios/state`,
`data/hermes`, `data/research`, `data/audit`, `data/state`, `data/reconciliation`,
traversed with `find -L` from REL so symlinks resolve into PSTATE, versus the
same relative paths under PROJ. **`data/agent*` does not exist in either root**
(`ls -d $REL/data/agent* $PROJ/data/agent*` → No such file or directory, both);
agent state lives at `data/runtime/agent_runtime_journals/` and
`data/cio/agent_run_traces.jsonl`, both covered.

```
REL_files=16979  PROJ_files=25639
BOTH=15916  REL_ONLY=1063  PROJ_ONLY=9723
AGREE=15633  DIVERGE=283
```
`[VERIFIED]` as_of 2026-08-31T23:2x ET, roots REL(-L)/PSTATE and PROJ.

**Measured answer: 315 divergent files — 283 under `data/`, 32 under `logs/` —
plus 10,786 paths present in only one root.**

The doc claims four. **The measured count is 315, and the four named are four
instances of a systemic dual-write, not the population.** One of the four
(`holdings.json`) is not currently divergent at all.

Divergences by directory:

```
102 data/runtime      84 data/cio      55 data/portfolios/state
 20 data/runtime/watchlist_intelligence/artifacts
  4 data/runtime/ri_snapshots     4 data/runtime/advisory_shadow
  4 data/runtime/advisory_notif_broker    3 data/runtime/provider_cost
  2 data/runtime/opening_intelligence     1 each: data/state, data/hermes,
    data/runtime/run_summaries/2026-08-28, data/runtime/audit_ledger,
    data/portfolios/state/data_broker
```

**Stability caveat, recorded rather than smoothed:** three consecutive runs gave
`PROJ_files` = 25633 / 25638 / 25639. The system writes during measurement, so
315 is a **lower bound at a moving instant**, not a frozen snapshot.

### Registry-declared vs undeclared

`CanonicalStoreRegistry@v1` declares **34** stores
(`$REL/scripts/lib/canonical_store_registry.py`). Against the sweep:

```
DIVERGE 17 | MISSING_IN_BOTH 6 | REL_ONLY 5 | AGREE 5 | dir 1
```

Six registry-declared stores **do not exist under either root**:
`cio.notification_policy` (`data/cio/cio_notification_policy.jsonl` — see §4.5),
`cio.decisions`, `cio.lesson_binds`, `notifications.outbox`
(`data/cio/cio_notification_outbox.jsonl` — note the *live* outbox is
`operator_notification_outbox.jsonl`, a different filename), `learning.weekly`,
`runtime.audit_claims`. `[VERIFIED]` individually, as_of 2026-08-31T23:2x ET.

**266 of the 283 data divergences have no registry contract at all.** Including
three of the four the AS-IS doc names.

## 2.4 A fifth split class the doc does not have: per-release stranding

This is my own sweep, and it is the sharper version of "checkout-relative".

```
$ cd /home/johnclaw/trade-ai-releases/portfolio-server && ls -1d */ | wc -l
302
$ for d in */; do if [ -L "$d/data/cio" ]; then sym=…; elif [ -d "$d/data/cio" ]; then real=…; else none=…; fi; done
data/cio symlink=283 real_dir=9 absent=10
```
`[VERIFIED]` as_of 2026-08-31T23:28 ET, root `/home/johnclaw/trade-ai-releases/portfolio-server`.

**302 release trees.** `data/cio` is symlinked into PSTATE in 283 of them. The
9 with a **real** `data/cio` directory are all historical and pre-date the
convention — eight from 2026-08-12 (50 files, ~4.5 MB each) and one from
2026-08-18 (8 files, 44 KB). Reported for completeness, not as an active hazard:
CIO state stranding was resolved before the 08-26 migration.

`REL/data` itself is still a **real per-release directory**, and nine of its
children are not symlinked: `audit  broker_cloud_inflight  hermes  merged
paper_trading  portfolios  raw  reconciliation  state`.

**Which of those are being written by the SERVED release right now** — i.e.
which will be stranded at the next promote:

```
$ stat -c '%y' …/CURRENT           → 2026-08-31 22:56:46
$ find data -maxdepth 1 -type d ! -type l | while read d; do find "$d" -type f -newermt "2026-08-31 22:55:46"; done
2026-08-31 23:25:05     359  data/audit/cio_defer_revisit_last.json
2026-08-31 23:25:21   40888  data/audit/cio_material_scan_last.json
2026-08-31 23:27:47      36  data/state/finviz_throttle.json
```
`[VERIFIED]` as_of 2026-08-31T23:29 ET, root REL. **Exactly three.**

The first two are the durable state of two **CIO systemd timers**
(`tradeai-cio-defer-revisit.service`, `tradeai-cio-material-scan.service`), both
of which run with `WorkingDirectory=…/portfolio-server/CURRENT`. Their split
census across all 302 release trees:

| store | copies | distinct sha256 | served copy sha256 |
|---|---|---|---|
| `data/audit/cio_defer_revisit_last.json` | **254** | **119** | `e2f17ff2af5d047056481a4511fb2a3b0f7d5ccb07eff997e8fa998e12254cdc` |
| `data/audit/cio_material_scan_last.json` | **258** | **232** | `d32df17a0a39c2bd3305b1b3155445e0316aa8fca5e9febd5b9d34b531690a6b` |
| `data/state/finviz_throttle.json` | **267** | **197** | `0fa74947e83d759e5fca9d61041d715ca0ba0a42e5ec21eb11bf1ebac273a098` |

`[VERIFIED]` `find … -exec sha256sum` then `sort -u | wc -l`, as_of
2026-08-31T23:30 ET, root `/home/johnclaw/trade-ai-releases/portfolio-server`.

**Read that carefully.** These are not stale duplicates of one store — they are
**779 copies, 548 of them distinct**, each frozen at the instant its release
stopped being CURRENT. Every promote hands these two CIO timers a **fresh, empty
or months-old** last-run file. Their dedupe and cursor state does not survive a
deploy, and there have been twelve promotes today alone. Neither timer can know
this: reading a missing last-run file is indistinguishable, to them, from a
first run.

**This is a live CIO defect that no existing document counts, and it is invisible
to any sweep that compares only two roots.**

## 2.4b Three conventions for the same directory, across release history

The per-release picture is not one convention that changed once. `data/state`
has had **three** different meanings across the 302 release trees:

```
$ ls -ld 448c3d3d-pr296-beta-visible-20260805-193505/data/state
lrwxrwxrwx … data/state -> /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/state
$ ls -ld d276657b7-main-exact-phase2-20260831-225546/data/state
drwxrwxr-x … (a real per-release directory)
$ ls -ld d276657b7-main-exact-phase2-20260831-225546/data/cio
lrwxrwxrwx … data/cio -> /home/johnclaw/trade-ai-releases/persistent-state/data/cio
```
`[VERIFIED]` as_of 2026-08-31T23:35 ET.

1. **August-05 era:** `data/state` symlinked to **PROJ** — the legacy checkout.
2. **Current:** `data/state` is a **real per-release directory**.
3. **`data/cio` and friends:** symlinked to **PSTATE**.

So the served release's `finviz_throttle.json` and the August-05 releases'
`finviz_throttle.json` are two different physical files with two live writers,
one minute apart:

```
$ stat -c '%d:%i %y %n' 448c3d3d-…/data/state/finviz_throttle.json
66306:3223608  2026-08-31 23:34:…  (resolves to PROJ/data/state/finviz_throttle.json)
$ stat -c '%d:%i %y %n' d276657b7-…/data/state/finviz_throttle.json
66306:20723539 2026-08-31 23:33:47
```
`[VERIFIED]` as_of 2026-08-31T23:34 ET. **Different inodes. A genuine live split.**

## 2.4c Two declared persistent trees the release never links to

`persistent_state_root.py` declares seven `PERSISTENT_TREES`. Two of them exist
in PSTATE but the served release does **not** symlink to them:

```
$ sed -n '32,40p' $REL/scripts/lib/persistent_state_root.py
PERSISTENT_TREES = ("data/cio","data/portfolios/state","data/research",
                    "data/hermes","data/health","data/runtime","logs")
```
```
                                          type    files  newest
REL/data/hermes                           REAL       1   2026-08-23 18:15
PSTATE/data/hermes                        REAL      71   2026-08-26 10:30   <- FROZEN at migration
PROJ/data/hermes                          REAL      74   2026-08-31 15:25   <- LIVE
REL/data/research                         REAL       0   —
PSTATE/data/research                      REAL       2   2026-08-07 12:51
PROJ/data/research                        REAL       2   2026-08-07 12:51
```
`[VERIFIED]` as_of 2026-08-31T23:36 ET, all three roots.

**2 of 7 declared persistent trees are unwired.** `PSTATE/data/hermes` is a dead
tree the registry believes is persistent: 71 files frozen at the 08-26 migration,
while the live writer keeps appending to PROJ. This is the same defect class as
Part 1's regressions — a correct declaration with nothing wired to it.

## 2.4d Live appends into release trees abandoned days ago

The sharpest instance, and the one an audit reading only `CURRENT/logs` cannot see:

```
$ ls -ld 40360117-main-exact-phase2-20260826-202631/logs
drwxrwxr-x … (a REAL directory — this release predates the logs symlink)
$ stat -c '%n size=%s mtime=%y inode=%i' 40360117-…/logs/claude_escalation_daemon.log
…/logs/claude_escalation_daemon.log  size=20107689  mtime=2026-08-31 23:22:42  inode=9765579
$ stat -c … 61578899-main-exact-phase2-20260827-111704/logs/cio_governed_bridge.log
…/logs/cio_governed_bridge.log       size=214178   mtime=2026-08-31 23:12:01  inode=4092589
$ stat /home/johnclaw/trade-ai-releases/persistent-state/logs/claude_escalation_daemon.log
No such file or directory
```
`[VERIFIED]` as_of 2026-08-31T23:37 ET.

**A 20 MB log was appended tonight into a release promoted away on 2026-08-26,
and that file does not exist in `PSTATE/logs` at all.** Long-running daemons
started from those releases still hold open handles into their real `logs/`
directories. The code comments the cause itself
(`persistent_state_root.py:30`): *"G1: logs joins the set — release-local logs/
forks orphan escalation queues and append-only health history on every promote
(#569)."* The fix landed; the processes started before it did not restart.

**Consequence for every log-based claim in this programme:** a lane can be
running, logging, and completely invisible to anyone reading `CURRENT/logs`.

## 2.5 A fourth and fifth root, named

* `TMPWT = /tmp/wt-cio-phase-a` — a **git worktree of PROJ**
  (`cat .git` → `gitdir: …/trade-ai-v12-rebuild/.git/worktrees/wt-cio-phase-a`),
  not a release checkout. `find -L …/data -type f` → **6 files, none of them CIO
  stores**, so it does **not** change the split count. It is a *code* root, and a
  production availability dependency on `/tmp`. Crontab line 952 runs a
  **production** lane from it: `15 12,17 * * 1-5 TRADEAI_SRC=/tmp/wt-cio-phase-a …/run_governed_cio_tis_digest.sh >> …/logs/cio_tis_digest.log` (`TRADEAI_GOVERNED_WORKER cio-tis-digest`).
  `ls -ld` → `drwx------ 43 johnclaw johnclaw 1820 Aug 31 20:56`. `[VERIFIED]`
  as_of 2026-08-31T23:23 ET. It is under no release pin and survives no reboot
  that clears `/tmp`.
* `/home/johnclaw/logs` — holds `cio_decisions.log` and `cio_draft_hygiene.log`;
  crontab line 997 writes `cio_draft_hygiene` there explicitly. `[VERIFIED]`.

## 2.6 What this sweep could NOT see

1. **SQLite databases — entirely unmeasured.** `PROJ/data` holds `state.db`,
   `trade_ai.db`, `trade_ai_v12.db`, `tradeai.db`; PSTATE has no `data/*.db`.
   sha256 is the wrong instrument here in both directions: VACUUM/page-layout
   differences produce false divergence, and WAL-pending content can let two
   logically different databases hash the same. **UNKNOWN — needs row-level
   comparison.**
2. **The other 301 release trees were only spot-swept.** I censused `data/cio`
   symlink-vs-real across all 302 and hashed three specific files across all of
   them. I did not hash their full `data/` trees. Given §2.4's ratios, the true
   per-release split population is **large and unmeasured.**
3. **~200 splits-in-waiting in unswept `data/` subdirs.** 17 PROJ `data/`
   subdirs were out of scope (`advisory`, `audits`, `bakeoff`, `learning`,
   `searxng_queries`, `system_events`, …), none of which exist under PSTATE.
4. **Hardcoded absolute write paths were not grepped.** Two third-location
   stores were found by targeted search; there may be more.
5. **Live-write race.** Counts moved by up to 6 files between runs. 315 is a
   lower bound.
6. **Divergent sha256 ≠ semantic divergence.** A `generated_at` field or key
   ordering flips a hash. Semantic divergence was confirmed only for the four
   headline stores. **And AGREE does not mean safe** —
   `data/runtime/flash_portfolio_risk.json` agrees only because both copies have
   been dead for four weeks.
7. **`agent_runtime_journals` — 5,255 PROJ-only files** not in the migration's
   `CACHE_EXCLUDES` and not present on PSTATE. An undeclared, unmigrated gap,
   not measured further.
8. **Nothing was read through the running server.**

## 2.7 OPERATOR-ONLY — proposed, and stopped

Per AGENTS.md §0 rule 5 and §17, **no copy was chosen, merged, deleted or
reconciled, and none should be by any agent.** Three decisions are put to the
operator and are not acted on here:

1. **The holdings pair.** `holdings.json` currently agrees byte-for-byte across
   PSTATE and PROJ. Collapsing it is operator-only. Note the trap: it agrees
   *today*, so a collapse looks free — but both roots are being actively written
   by different cron lines, so the two will diverge again on any day the writers
   disagree. The safe framing is not "which copy wins" but "which of the 266
   PROJ-rooted cron lines should be re-rooted", which is a deploy-boundary
   decision.
2. **`"legacy_read_only": false`.** Flipping it to `true` is the single change
   that would stop 315 divergences from growing. It is a deploy-protocol change
   and is not this worker's to make.
3. **The three per-release stranding stores (§2.4).** Symlinking
   `data/audit` and `data/state` into PSTATE, as `data/cio` already is, would fix
   two CIO timers' state loss. **Proposed. Not done.** Note that doing it would
   silently merge 779 divergent copies into one — which is exactly the
   destructive act rule 5 forbids an agent from choosing.
---

# PART 3 — who calls `load-by-subject` on a timer?

## 3.1 The answer, stated first

The literal question splits in two, and the two halves have different answers.
Conflating them is how this node has been mis-scored in both directions.

| the call | is it scheduled? | verdict |
|---|---|---|
| `load-by-subject` **before the wake is claimed** (`InstrumentRecordStore.load(key)` inside the dispatcher's record consult) | **YES** — cron `*/5` wake dispatcher | **(b) CODE-WIRED. Runtime adjudication handed to Worker A.** |
| `load-by-subject` **before `ResearchNeedDecision.decide()`** — the thing PR #810 was named for | **NO** — its only entrypoint caller sits behind `--dry-run`, which the cron does not pass | **(a) nothing scheduled calls it. The dark contract stands.** |

**My formal claim is capped at (b) for the first row, per this audit's brief.**
I have not issued, and may not issue, the M5 verdict. See §3.5.

## 3.2 The scheduled entity, verbatim

`crontab -l` line 934, quoted exactly:

```
*/5 * * * * cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/cio_wake_dispatch_entrypoint.py >> logs/cio_wake_dispatcher.log 2>&1  # 24/7 2026-08-27: was 9-16 M-F. Catalysts, filings and overnight news do not keep market hours; a wake created outside the window sat unprocessed until the next weekday morning.
```
`[VERIFIED]` `$ crontab -l | grep -n cio` — as_of 2026-08-31T23:12 ET, root: the user crontab.

Note what the line does **not** contain: `--dry-run`. This is load-bearing for §3.4.

There is no systemd unit for the wake dispatcher. `systemctl --user list-timers --all`
shows four CIO units — `tradeai-cio-reactive`, `tradeai-cio-delivery`,
`tradeai-cio-material-scan`, `tradeai-cio-defer-revisit` — none of which is the
wake dispatcher. `[VERIFIED]` as_of 2026-08-31T23:17 ET.

## 3.3 The call site, path:line — the pre-claim consult

Entrypoint: `REL/scripts/cio_wake_dispatch_entrypoint.py`. `main()` (`:90`) takes the
non-`--dry-run` branch at `:98` and reaches `poll_and_dispatch` at `:133`.

The chain, all at root REL, pin d276657b7, `[CODE]`:

```
scripts/cio_wake_dispatch_entrypoint.py:133   result = dispatcher.poll_and_dispatch(max_dispatches=5)
scripts/lib/cio_wake_dispatcher.py:164        from scripts.lib.cio_wake_subject import decide as _subject_decide
scripts/lib/cio_wake_dispatcher.py:167        _rec_store = InstrumentRecordStore()
scripts/lib/cio_wake_dispatcher.py:197        _d = _subject_decide(wake, store=_rec_store, known_keys=_known_keys)
scripts/lib/cio_wake_subject.py:168               rec = store.load(key)      # <-- load-by-subject
scripts/lib/cio_wake_dispatcher.py:200        if _d["verdict"] == _SKIP_CADENCE: ... skipped.append(...); continue
scripts/lib/cio_wake_dispatcher.py:369        "record_consult": _summarise_subject(subject_decisions),
scripts/cio_wake_dispatch_entrypoint.py:148   log.info("record_consult: ...")
scripts/cio_wake_dispatch_entrypoint.py:163   _p = _PROJECT / "data" / "cio" / "wake_record_consult.json"
```

This is a real gate, not a label: `:200` **skips the wake and never claims it**
when the record's `next_eligible_at` is in the future. `[CODE]`

## 3.4 The half that is still dark — PR #810's own contract

`REL/scripts/lib/cio_research_preflight.py:1` states its purpose in its first line:

> `"""P1 / M5 — load InstrumentRecord before ResearchNeedDecision.decide().`

Every caller of `decide_after_load` in the served release:

```
$ grep -rn "cio_research_preflight\|decide_after_load" --include=*.py $REL/
scripts/cio_wake_dispatch_entrypoint.py:45      from scripts.lib.cio_research_preflight import decide_after_load
scripts/cio_wake_dispatch_entrypoint.py:62              research = decide_after_load(
scripts/cio_research_gate_report.py:27          from scripts.lib.cio_research_preflight import decide_after_load
scripts/cio_research_gate_report.py:84              decisions.append(decide_after_load(
tests/test_cio_p1_load_by_subject.py:15,17,66,106,156,175
```
`[VERIFIED]` command + output, as_of 2026-08-31T23:14 ET, root REL.

Both non-test callers are unreachable from any schedule:

* `cio_wake_dispatch_entrypoint.py:45/:62` sit inside `dry_run_record_consult()`
  (`:36`), which `main()` calls **only** under `if args.dry_run:` (`:98`). The
  cron line does not pass `--dry-run`. `[CODE]`
* `cio_research_gate_report.py` is a dry report. `$ crontab -l | grep -n "cio_research_gate_report\|research_gate"`
  returns nothing. `[VERIFIED]` as_of 2026-08-31T23:15 ET.

So the module merged into the served release forty minutes before this audit —
the one whose branch is literally named `feat/cio-p1-load-by-subject` — has
**no scheduled caller**. This is the repository's named recurring defect
(AGENTS.md §3: *a contract built and a caller never wired*) reproduced inside
the PR that was meant to close it.

**Verdict for this half: (a). The dark contract stands.**

`[CODE]` supporting fact for Worker A, offered without a verdict:
`cio_reactive_cycle.py:208–211` now carries the event's own subject onto the
wake it enqueues, with the comment *"Without this the wake is subject-less and
the record consult in the dispatcher has nothing to load by — which is exactly
why `load-by-subject` was never called: 0 of 1,513 wakes carried a subject."*
That is the join that makes the pre-claim consult capable of resolving a subject
at all.

## 3.5 What I observed, and why I am not scoring it

The dispatcher log is at `PSTATE/logs/cio_wake_dispatcher.log` (REL/logs is a
symlink — §2.1), so it accumulates **across release rotations**. Lines in it
predating 22:56 tonight were written by an EARLIER release, not by pin
d276657b7. Attributing them to the served pin would be wrong.

Every dispatcher cycle at or after the 22:56 promotion:

```
$ awk '$1=="2026-08-31" && $2>="22:56"' $PSTATE/logs/cio_wake_dispatcher.log | grep -E "record_consult|skipped by record|dispatched="
2026-08-31 22:58:00,000 dispatched=3 skipped=0 errors=0
2026-08-31 22:58:00,000 record_consult: wakes=3 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=3
2026-08-31 23:03:06,532 dispatched=1 skipped=0 errors=0
2026-08-31 23:03:06,532 record_consult: wakes=1 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=1
2026-08-31 23:07:50,514 dispatched=0 skipped=0 errors=0
2026-08-31 23:07:50,515 record_consult: wakes=0 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=0
2026-08-31 23:12:58,690 dispatched=0 skipped=0 errors=0
2026-08-31 23:12:58,691 record_consult: wakes=0 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=0
```
`[VERIFIED]` as_of 2026-08-31T23:14 ET, root PSTATE (reached via REL/logs).

**Read this carefully — it is the trap, not the proof.** `subject_resolved=0` on
every post-promotion cycle. `cio_wake_subject.decide` returns at `:163` with
`NO_SUBJECT` **before** reaching `store.load(key)` at `:168`. So under the
SERVED PIN, `load-by-subject` has been reached zero times. The
`record_consult:` telemetry line fires every five minutes regardless — it is
emitted from the summariser, not from the loader.

> **A telemetry line that fires on an empty set is indistinguishable from one
> that fires on work done.** `record_consult: wakes=0 …` is what this lane
> prints when it did nothing at all. Anyone reading only the presence of that
> line would score this node LIVE.

Earlier lines in the same file (written by earlier releases, whose dispatcher
code for this path is identical by `git log -S`) do show the loader reached and
the record changing an outcome:

```
$ grep -c "skipped by record" $PSTATE/logs/cio_wake_dispatcher.log
389
$ grep "skipped by record" ... | awk '{print $1}' | sort | uniq -c
      3 2026-08-30
    386 2026-08-31
$ grep -n "skipped by record" ... | tail -1
9978:2026-08-31 10:57:32,920 [tradeai.cio_wake_dispatcher] wake wake_ev_morgan_5834af04fedb410d_2026083110 skipped by record: HELD:SCHD: the record defers research until 2026-08-31T14:58:17.884559+00:00 (0.0h away). The disposition was recorded earlier and nobody replayed it.
```
`[VERIFIED]` as_of 2026-08-31T23:13 ET, root PSTATE.

That is 389 wakes the record stopped, all on one subject (`HELD:SCHD`), all
before 10:58 ET today, at which point the deferral expired and the skips ceased.

**I am not scoring this.** Rung 1 evidence — an unattended fire on the served
release observed consuming the record — is Worker A's M5 timer watch
(`docs/ops/CIO_M5_TIMER_WATCH_2026-09-01.md`). Three facts are handed over:

1. Under pin d276657b7 the loader has been reached **zero** times in four cycles.
2. The 389 blocking decisions were written by a **prior** release into a shared
   log; the served pin cannot claim them.
3. The whole 389 came from **one** subject key. `PSTATE/data/cio/cio_instrument_records.jsonl`
   was last written `2026-08-30 10:58:17 -0400` — its `next_eligible_at` stamps
   are 24h old and now all in the past, so a repeat of that skip requires a new
   write to the record store, which has not happened in 36 hours.
   `[VERIFIED]` `ls -la --time-style=full-iso`, as_of 2026-08-31T23:18 ET, root PSTATE.

**My claim, capped: (b) CODE-WIRED, RUNTIME-UNPROVEN AT PIN d276657b7.**
---

# PART 4 — the real Telegram send gate

AGENTS.md §13.4 instructs: *"grep the actual send gate that reaches the operator
family and name that symbol. INTERDICT is not that gate."* Done below, read-only.
**The instruction's conclusion is now one day stale, and the finding wins.**

## 4.1 `CIO_TELEGRAM_INTERDICT` — every occurrence, and what it actually gates

```
$ grep -rn "CIO_TELEGRAM_INTERDICT" --include=*.py --include=*.md --include=*.sh --include=*.json .
```
`[VERIFIED]` as_of 2026-08-31T23:12 ET, root REL. 41 hits. Classified:

| class | count | representative |
|---|---|---|
| prose / docs | 2 | `AGENTS.md:337`, `AGENTS.md:819` |
| CI + test harness forcing it to 1 | 6 | `run_cio_hardening_ci.py:297`, `run_cio_adversarial_suite.py:22`, `r11_tier0.sh:6` |
| deploy / mode-switch shell that WRITES it into a systemd drop-in | 7 | `cio_telegram_mode.sh:44,57–58`, `cio_phase13_canary_deploy.sh:182` |
| readout / census / audit surfaces that only REPORT it | 8 | `cio_wave2_census.py:202`, `cio_delivery_audit.py:24`, `cio_preconditions_board.py:598` |
| **code that actually branches on it in a delivery path** | **4** | `cio_telegram_transport.py:51`, `telegram_transport.py:105`, `cio_delivery_mode.py:30`, `cio_notification_policy.py:56` |

**The name asserts:** Telegram sends are interdicted.

**What the code does, at pin d276657b7:** it is read by exactly one function that
sits between a CIO notification and an HTTP POST — `telegram_transport._interdicted()`
(`REL/scripts/telegram_transport.py:86`) — and that function is now invoked at the
lowest common layer, `deliver_text` (`:164`), before the request is built.

**The gap, quantified.** Two numbers, in opposite directions:

* **Narrower than the name, by 46.** `deliver_text` is not the only path to the
  operator's device. `REL/config/telegram_chokepoint_baseline.json` enumerates
  **46 files** that build `https://api.telegram.org/bot…` directly and never
  touch `telegram_transport`. Its own `_note` reads *"Known Telegram chokepoint
  bypasses. Ratchet only — may shrink, never grow."* Setting
  `CIO_TELEGRAM_INTERDICT=1` stops none of those 46.
  `[VERIFIED]` `python3 -c "import json;print(len(json.load(open(...))['files']))"` → `46`,
  as_of 2026-08-31T23:21 ET, root REL.
* **Wider than AGENTS.md says, by one commit.** `telegram_transport.py:86–100`
  carries a dated comment: *"C4, 2026-08-31. This check lived only in
  `send_message`, which then delegates to `deliver_text` — and `deliver_text` is
  exported and callable directly. Any caller reaching it bypassed the interdict
  entirely… The check now sits at the LOWEST COMMON LAYER."* So for the CIO
  family, `CIO_TELEGRAM_INTERDICT` **does** now gate the send, as of today.
  `[CODE]`, root REL.

**Correction to AGENTS.md §13.4 / §7 table row.** The line *"`CIO_TELEGRAM_INTERDICT`
… does not gate the family that reaches the operator"* was true when written and
is no longer precisely true. It should read: *gates the CIO family at
`telegram_transport.deliver_text`; does not gate the 46 chokepoint bypasses.*
Reported here per AGENTS.md §0 rule 10; amendment PR not opened by this worker
(docs-only, out of declared file set).

## 4.2 The real path, notification → operator's device

Traced all the way to the network call, not to the first function named "send".

```
 tradeai-cio-delivery.timer                      systemd --user, every 5 min
   └─ tradeai-cio-delivery.service
        WorkingDirectory=…/portfolio-server/CURRENT
        EnvironmentFile=-/run/user/%U/tradeai/env
        EnvironmentFile=-%h/.config/tradeai/cio-telegram.env
        EnvironmentFile=-%h/.config/tradeai/cio-operator-live.env
        ExecStart=…/.venv/bin/python scripts/cio_delivery_worker.py --once --mode live
   └─ cio_delivery_worker.py:38    CIONotificationDeliveryWorker(outbox, mode="live")
   └─ cio_notification_delivery.py:217  mode=="live"  → RealTelegramAdapter
   └─ cio_notification_delivery.py:243  poll_and_deliver()  — reads outbox status=PENDING
   └─ cio_notification_delivery.py:104  RealTelegramAdapter.send()
   └─ cio_telegram_transport.py:230     send_cio_message()
   └─ telegram_transport.py:275         send_message()
   └─ telegram_transport.py:146         deliver_text()          ← LOWEST COMMON LAYER
   └─ telegram_transport.py:61          _http_post()  → requests.post(api.telegram.org)
```
`[VERIFIED]` unit definitions via `systemctl --user cat`, as_of 2026-08-31T23:17 ET;
`[CODE]` for the call chain, root REL, pin d276657b7.

**Where the notification comes from.** `CIORunWorker` enqueues it directly:
`REL/scripts/lib/cio_run_worker.py:1139–1152` builds
`{"message_class": "checkin", "channel_targets": ["telegram"], …}` and calls
`self.notification_outbox.enqueue(...)`. The outbox file is
`PSTATE/data/cio/operator_notification_outbox.jsonl` (346 event lines,
`[VERIFIED]` `wc -l`, as_of 2026-08-31T23:19 ET, root PSTATE). `[CODE]`

## 4.3 The ordered gate list

Every branch between the notification decision and the network call. "Effective
value" is read from the env the delivery service actually composes.

| # | symbol | path:line (root REL) | reads | effective value / effect |
|---|---|---|---|---|
| 1 | `CIORunWorker._emit_notifications` | `scripts/lib/cio_run_worker.py:1152` | nothing | enqueues unconditionally. **Does not consult `NotificationPolicy@v1`** — §4.5 |
| 2 | `NotificationOutbox.enqueue` content key | `scripts/lib/cio_notification_outbox.py:161` | `message_class=="checkin"` + `body_hash` | content-keyed only for `checkin`; every other class falls through (`:192`) |
| 3 | `--mode` | `scripts/cio_delivery_worker.py:30` | argv | default `shadow`; **the unit passes `--mode live`** |
| 4 | adapter select | `scripts/lib/cio_notification_delivery.py:217` | `mode` | `live` → `RealTelegramAdapter`; else `FakeDeliveryAdapter` |
| 5 | expiry / claim | `cio_notification_delivery.py` `poll_and_deliver` +14, +28, +36 | `expires_at`, `current_status` | skips DELIVERED / DEAD_LETTERED |
| 6 | `is_raw_product_dump_body` | `scripts/lib/cio_notification_delivery.py:112` (def `:31`) | message text | belt-and-suspenders content suppressor |
| 7 | `network_interdicted()` | called `cio_notification_delivery.py:131`; def `scripts/lib/cio_telegram_transport.py:47` | `PYTEST_CURRENT_TEST`, `CIO_TELEGRAM_INTERDICT`, `ENABLE_TELEGRAM`, `CI` | **False** — see 4.4 |
| 8 | `RealTelegramAdapter._live` | `cio_notification_delivery.py:140` (set `:102`) | `TELEGRAM_CIO_BOT_TOKEN`, `TELEGRAM_CIO_CHAT_IDS` | **True** (both SET) |
| 9 | `network_interdicted()` again | `scripts/lib/cio_telegram_transport.py:268` | as #7 | **False** |
| 10 | `live_authorized()` | called `:274`; def `scripts/lib/cio_telegram_transport.py:61` | `AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY` | **True** (`=1`) |
| 11 | `credentials_ready()` | called `:279`; def `:107` | CIO token + chat ids | **True** |
| 12 | `was_recently_sent()` | called `:290`; def `:125` | `PSTATE/data/cio/cio_outbound_dedupe.jsonl`, 6h TTL | fires often; §4.6 |
| 13 | `send_message` early return | `scripts/telegram_transport.py:288` | `_interdicted()` | **False** |
| 14 | **`_interdicted()` at `deliver_text`** | called `scripts/telegram_transport.py:164`; def `:86` | `PYTEST_CURRENT_TEST`, `CIO_TELEGRAM_INTERDICT` | **False → the POST proceeds** |
| 15 | `_http_post` | `scripts/telegram_transport.py:61` | — | `requests.post(https://api.telegram.org/bot…/sendMessage)` |

## 4.4 The ONE symbol that is the true send gate

> **`telegram_transport._interdicted()` — `REL/scripts/telegram_transport.py:86`,
> enforced at `deliver_text`, `REL/scripts/telegram_transport.py:164`.**

It is the true gate because it is the **last** branch before `_http_post`, it sits
at the lowest layer both `send_message` and any direct `deliver_text` caller must
pass, and it is the only one of the fifteen that no caller of this transport can
route around. Its input **is** `CIO_TELEGRAM_INTERDICT`.

Scope, stated honestly: it is the true gate **for the CIO family that flows
through `telegram_transport`**. It is not a gate on the operator's Telegram
device in general — the 46 chokepoint bypasses reach the same device without
passing it.

The gate that has actually *differentiated* in recorded history is a different
one: `live_authorized()` / `AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY`
(`scripts/lib/cio_telegram_transport.py:61`). See §4.6.

## 4.5 ENABLED or INTERDICTED — and on what evidence

**Telegram to the operator family is currently ENABLED.** Not interdicted.

Flag readout, at the exact env the delivery unit composes:

```
$ set -a; . /run/user/1000/tradeai/env; . ~/.config/tradeai/cio-telegram.env; . ~/.config/tradeai/cio-operator-live.env; set +a
CIO_TELEGRAM_INTERDICT=0
ENABLE_TELEGRAM=1
AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1
CIO_SITUATION_NOTIFY=0
CIO_THESIS_TELEGRAM=<unset>
TELEGRAM_CIO_BOT_TOKEN=SET (len=46)
TELEGRAM_CIO_CHAT_IDS=SET (len=31)
TELEGRAM_CIO_ALLOWLIST=MISSING
```
`[VERIFIED]` as_of 2026-08-31T23:18 ET, roots `/run/user/1000/tradeai/env`
(mtime 2026-08-31 22:56:47), `~/.config/tradeai/cio-telegram.env` (mtime
2026-08-20 14:32:48), `~/.config/tradeai/cio-operator-live.env` (mtime
2026-08-26 10:36:32). Values of secrets never read or printed — presence and
length only.

**A flag readout is rung 5. The rung-2 proof that the path is open:** a message
actually left the machine tonight.

```
$ journalctl --user -u tradeai-cio-delivery.service --since "2026-08-31 20:15" --until "2026-08-31 20:30"
Aug 31 20:22:01 python[1780737]: telegram parse_mode fallback: first send failed (code=400), resent as plain text. … chat=6993102664 ok=False
Aug 31 20:22:02 python[1780737]: telegram parse_mode fallback: first send failed (code=400), resent as plain text. … chat=780672608 ok=False
Aug 31 20:22:02 python[1780737]:   delivered_count=1 failed_count=0 mode=live
```
`[VERIFIED]` as_of 2026-08-31T23:20 ET, root: systemd user journal.

And the durable artifact that would not exist if no send had succeeded —
`mark_sent` is called only on `ok_any` (`cio_telegram_transport.py:329–330`):

```
$ cat $PSTATE/data/cio/cio_outbound_dedupe.jsonl
{"key": "16dbbb34809326d7060f2af4e585bee7", "ts": 1788208839.402004, "at": "2026-08-31T20:40:39.402006+00:00", "meta": {"kind": "checkin", "decision_id": null}}
{"key": "404f7deedbdb3fb59afefe4ec135bb57", "ts": 1788214573.1117249, "at": "2026-08-31T22:16:13.111728+00:00", "meta": {"kind": "checkin", "decision_id": null}}
{"key": "36ac465213d69163905f4756ab7d1a7e", "ts": 1788219102.6183035, "at": "2026-08-31T23:31:42.618306+00:00", "meta": {"kind": "checkin", "decision_id": null}}
{"key": "7d8c5a1b1bee089641c8c1fcae765fc1", "ts": 1788222122.6812017, "at": "2026-09-01T00:22:02.681204+00:00", "meta": {"kind": "checkin", "decision_id": null}}
```
`[VERIFIED]` as_of 2026-08-31T23:19 ET, root PSTATE. Four successful CIO sends
inside the 6h TTL window, latest `2026-09-01T00:22:02Z` = 20:22:02 ET, matching
the journal line above to the millisecond. **Rung 1: an unattended systemd fire,
on its own schedule, put a message on the operator's device.**

Delivery volume, all time, from the same unit:

```
$ journalctl --user -u tradeai-cio-delivery.service | grep -oE "delivered_count=[0-9]+ failed_count=[0-9]+" | sort | uniq -c | sort -rn
   4623 delivered_count=0 failed_count=0
     42 delivered_count=1 failed_count=0
     19 delivered_count=2 failed_count=0
      8 delivered_count=3 failed_count=0
      2 delivered_count=5 failed_count=0
```
`[VERIFIED]` as_of 2026-08-31T23:20 ET. 4,694 runs since 2026-08-15 09:58;
**114 messages delivered; 4,623 runs (98.5%) delivered nothing.** Zero failures,
ever — which is itself worth noting: a lane with 4,694 runs and not one recorded
failure has either never had one or is not recording them.

### The `NotificationPolicy@v1` finding — the standing incident, repeated

The AS-IS map scores `█ NOTIFICATION POLICY` and its four classes
(IMMEDIATE / DIGEST / COMMAND_CENTER_ONLY / SUPPRESSED) as LIVE.
**It is not on the live delivery path at all.**

```
$ grep -n "notification_policy\|NotificationPolicy" $REL/scripts/lib/cio_run_worker.py
                (no output)
$ grep -rn "cio_notification_policy" --include=*.py $REL/scripts $REL/apps | grep -v "cio_notification_policy.py:"
scripts/cio_wave3b_report.py:22:from scripts.lib import cio_notification_policy as policy
scripts/cio_wave3c_report.py:24:from scripts.lib import cio_notification_policy as policy
scripts/lib/canonical_store_registry.py:420,424  (declares the store + names the writer)
scripts/lib/cio_command_center.py:1031           (a read surface)
$ ls -la $PSTATE/data/cio/cio_notification_policy.jsonl
ls: cannot access '…/cio_notification_policy.jsonl': No such file or directory
$ crontab -l | grep -n "wave3b\|wave3c"
                (no output)
```
`[VERIFIED]` as_of 2026-08-31T23:21 ET, roots REL and PSTATE.

So: the router that decides IMMEDIATE vs DIGEST vs SUPPRESSED is imported by two
unscheduled report scripts and one dashboard; the store the
`CanonicalStoreRegistry` declares for it **does not exist on disk**; and the
producer that actually reaches the operator (`cio_run_worker.py:1152`) never
calls it. This is the standing incident's exact shape — *a router classifying
into a table nothing delivers* — inverted: here the delivery happens and the
router is the thing nobody calls. Either way the classification is decorative.

## 4.6 Has this gate ever been OBSERVED firing? — *a guard verified by presence is not a guard*

Checked in both directions, across every log surface I could reach.

```
$ for pat in INTERDICTED_TEST_OR_FLAG network_interdicted_pytest_or_flag DELIVERY_INTERDICTED "CIO telegram interdicted" live_not_authorized; do
    journalctl --user --no-pager --since "2026-07-01" | grep -c "$pat"; done
0
0
0
0
0
$ grep -rl "INTERDICTED_TEST_OR_FLAG" $PSTATE/logs $PROJ/logs /home/johnclaw/logs
                (no output)
```
`[VERIFIED]` as_of 2026-08-31T23:22 ET, roots: systemd user journal (since
2026-07-01), `PSTATE/logs`, `PROJ/logs`, `/home/johnclaw/logs`.

**Finding: the true send gate — `_interdicted()` — has NEVER been observed firing,
in either direction, anywhere in recorded history reachable from this machine.**
It has only ever been observed *not* firing. It is, on the evidence, a guard
verified by presence: its code is correct, its placement (post-C4) is correct,
and nothing has ever exercised it in production. Two candidate explanations,
which I cannot separate and which have opposite fixes — the `attempts_24h`
lesson (AGENTS.md §3):

1. `CIO_TELEGRAM_INTERDICT` has simply been `0` for the whole recorded window,
   so the branch is never taken. (Supported: `cio-telegram.env` mtime
   2026-08-20, `cio-operator-live.env` mtime 2026-08-26, both `=0`.)
2. The interdicted result is returned as a dict and **never logged** at
   `telegram_transport.py:110–116` — `_interdicted_result()` writes no log line
   at all. So a firing at gate #14 would leave **no trace anywhere**.
   `[CODE]`, root REL.

Explanation 2 is confirmed by reading the code: gate #14 is silent by
construction. **A gate that cannot be observed firing cannot be shown to work.**
Positive-controlling it would require setting the flag and attempting a send —
which is a live Telegram operation and is a HARD PIN for this worker. **Not
attempted. Proposed and stopped.** (AGENTS.md §0 rule 9.)

Two adjacent gates *have* been observed refusing, which is why I do not claim the
whole chain is unexercised:

```
$ grep -o '"reason": "[a-z_]*"' $PROJ/logs/cio_tis_digest.log | sort | uniq -c
      1 "reason": "cio_credentials_missing"
      1 "reason": "sent"
```
`[VERIFIED]` as_of 2026-08-31T23:22 ET, root PROJ (`logs/cio_tis_digest.log`,
mtime 2026-08-31 17:15:01). Gate #11 fired once on a schedule. Separately, an
agent transcript in `/home/johnclaw/logs/cursor-agent-audit.jsonl` records a
hand-run on 2026-08-20T17:00 returning `"reason": "live_not_authorized"`
(gate #10) — rung 2 at best, from a scratch worktree, not the served release.

## 4.7 Two defects found while tracing, neither remediated

* **The adapter's chat-id containment is decorative.**
  `RealTelegramAdapter.__init__` sets `self.chat_ids = [chat_id]` — a single id —
  when both args are supplied (`cio_notification_delivery.py:99`), which is
  exactly how `CIONotificationDeliveryWorker` constructs it (`:218–220`). But the
  actual fan-out loop is `for cid in cio_chat_ids()` (`cio_telegram_transport.py:310`),
  re-read from the environment. The 20:22 journal shows the send reaching **two**
  chats while the adapter believed it held one. Same allowlist, so no leak — but
  the adapter field bounds nothing. `[CODE]` + `[VERIFIED]` (the journal line).
* **`DeliveryReceipt@v1` has no writer on the delivery path.**
  `PSTATE/data/cio/cio_delivery_receipts.jsonl` is 410 bytes, one row, mtime
  2026-08-29 14:30:52 — and that row is `"decision": "SUPPRESSED", "would_send": false`.
  114 real deliveries produced zero receipts. The registry names
  `scripts.lib.cio_delivery_receipt` as the writer
  (`canonical_store_registry.py:433–437`); its only non-test importer is
  `cio_wave3c_report.py:22`, which is not scheduled. `[VERIFIED]` as_of
  2026-08-31T23:19 ET, roots PSTATE + REL. This downgrades the AS-IS
  `█ DELIVERY RECEIPT / DEDUPE` node — see Part 1.
---

# Corrections

Kept in the document, per AGENTS.md §4 — the correction is often the finding.

1. **My own repo pin moved mid-audit.** I opened at worktree sha `c0ae53cf1`
   (branch `feat/cio-p1-load-by-subject`), read `d660d7cea` mid-run and
   `542cb502d` at close, on branch `overnight/maturity-maceration-2026-09-01`;
   the coordinator moved the worktree and committed under me, twice. No measurement in this document was taken *from* the
   worktree — every root is REL, PSTATE, PROJ, the crontab, the journal or the
   env files — so no number is affected. Recording it because a reader
   reconciling this file against a single sha would otherwise find a mismatch.
   The **served** pin `d276657b7` did not rotate (checked at 23:12 and 23:22 ET).

2. **I nearly scored `load-by-subject` as (c) on the first pass.** The
   `record_consult:` telemetry line fires every five minutes and the log holds
   389 `skipped by record` entries — which reads, at a glance, as an unattended
   fire consuming the record. Two facts killed that reading: `REL/logs` is a
   **symlink into `PSTATE`**, so the log spans release rotations and the 389
   belong to earlier pins; and every post-promotion cycle shows
   `subject_resolved=0`, meaning `cio_wake_subject.decide` returns at `:163`
   before ever reaching `store.load(key)` at `:168`. **The telemetry line fires
   on an empty set.** This is the §3 trap — a surface reporting on a set it never
   read — and it very nearly cost this audit its central claim.

3. **AGENTS.md §7 / §13.4 on `CIO_TELEGRAM_INTERDICT` is one day stale.**
   The table row *"does not gate the family that reaches the operator"* was
   correct until commit C4 (dated in-code 2026-08-31) moved `_interdicted()` to
   `deliver_text`, the lowest common layer. For the CIO family it now **is** the
   gate. The claim remains correct for the 46 chokepoint bypasses. The brief I
   was given repeats the stale form; per AGENTS.md §0 rule 10 the finding wins.
   No amendment PR opened — outside this worker's declared file set.

4. **`AGENTS.md`'s `cio_instrument_record.py:390` citation is still exact.**
   Verified at the served pin: `:390  raise BehaviorWriteRefused(f"MBI_BEHAVIOR=0: cognition may not carry {bad}")`,
   an unconditional raise inside `if forbidden:` at `:388`. `CognitionNoOp` raises
   at `:438`. `[VERIFIED]` as_of 2026-08-31T23:24 ET, root REL. Cited because
   AGENTS.md §3 warns that a symbol's home quoted from memory has been wrong
   here — this one is not.

5. **I published a zero that was a detector artifact, and caught it by accident.**
   Checking whether stranded release trees were still being written, I ran
   `find … -newermt "-90 minutes"` and got **0**. One minute later a direct `ls`
   on the same six paths showed mtimes of `23:32:45`. The relative-time form
   matched nothing silently. Re-run with an absolute timestamp, the query worked.
   **This is AGENTS.md §3's "positive-control before publishing a zero" exactly,
   and I had not done one.** Every zero elsewhere in this document should be read
   with that in mind; §"cannot see" item 3 says which of them are unvalidated.

6. **A "six stranded writes" finding collapsed to one write under an inode check.**
   Six August-05 release directories appeared to receive a write simultaneously
   with CURRENT. `stat -c '%d:%i'` showed all six on **one inode** (`66306:3223608`)
   with `nlink=1` — impossible for hardlinks, which meant path aliasing. Their
   `data/state` is a symlink to **PROJ**. So it was **one** write to PROJ seen
   through six paths, not six stranded writes. Recorded because the inflated form
   is the more alarming one and would have been published. *Separately verified as
   real and not aliasing:* the two **log** appends in §2.4d, whose release-local
   `logs/` are genuine directories with distinct inodes and no PSTATE counterpart.

7. **Inode-dedup confirmed the per-release census was NOT inflated.** Re-running
   §2.4's counts with `-printf '%D:%i'` gave `paths=267 DISTINCT_INODES=267` for
   `finviz_throttle.json` (and 258/258, 254/254, 220/220 for the others) — `find`
   without `-L` never descended the aliasing symlinks, so those are genuinely
   separate files. The 267/197 figures stand. Recorded because correction 6 made
   it reasonable to doubt them, and doubting them was the right instinct.

---

# What this audit structurally cannot see

Stated so the gaps are not mistaken for negatives.

1. **A gate that returns silently.** `telegram_transport._interdicted_result()`
   (`:110`) writes no log line. If gate #14 had ever fired, this audit would have
   no way to know. Every "never observed firing" claim in Part 4 is therefore
   *never observed*, not *never happened* — and for that specific gate the two
   are indistinguishable by construction. Fixing the observability is a code
   change; proving the gate by exercising it is a live Telegram send, which is a
   HARD PIN for this worker.

2. **The counter-vs-cause ambiguity (AGENTS.md §3, `attempts_24h`).** Where I
   report a zero — `subject_resolved=0`, `delivered_count=0`, a gate never
   logged — I could distinguish "never started" from "failed on the first
   instruction" only where a second artifact existed. Where I could not, the row
   says UNKNOWN.

3. **No positive control was injected anywhere.** AGENTS.md §3 asks for one
   before publishing a zero. Every available positive control here writes durable
   state, sends to an operator surface, or spends money — all pinned. So the
   zeros in this document are unvalidated detectors. That is a real weakness and
   it is the honest state of the evidence.

4. **Only pin `d276657b7` was observed at runtime**, for roughly thirty minutes.
   Four dispatcher cycles and eight delivery cycles is not a schedule. Anything
   this document says about the served pin's *runtime* behaviour rests on that
   window. Earlier behaviour in shared logs belongs to earlier pins and is
   labelled as such.

5. **Shared, rotation-spanning logs mean log evidence cannot be attributed to a
   pin without a timestamp cut.** `REL/logs -> PSTATE/logs`. Any claim of the
   form "the log shows X, therefore the served release does X" is invalid in this
   system unless X is timestamped after the symlink's mtime. I applied that cut;
   other documents in this programme may not have.

6. **Content was never read.** I confirmed that Telegram messages were sent and
   when; I did not read a message body, and the dedupe ledger stores only a hash.
   Whether the operator received something *useful* is outside what any of this
   measures.

7. **Nothing was measured through the running server process.** Every reading is
   from files, the journal, the crontab and systemd unit definitions. A value
   held only in a live process's memory, or a route's response, is invisible here.

8. **`/tmp/wt-cio-phase-a` was inspected but not audited.** A production cron line
   runs from it (§2.5). Its contents are not under any release pin and were not
   hashed against REL.

9. **Logs written into abandoned release trees are invisible to a `CURRENT/logs`
   reader — including to most of this document.** §2.4d shows a 20 MB log
   appended tonight into a release promoted away on 2026-08-26, with no
   counterpart in `PSTATE/logs`. My "never observed firing" sweeps (§4.6) covered
   `PSTATE/logs`, `PROJ/logs`, `/home/johnclaw/logs` and the systemd journal —
   **they did not cover the `logs/` directories of the other 301 release trees.**
   A gate could have fired into one of those and I would not have seen it. This
   is the single largest hole in Part 4's negative findings.

10. **The 302 release trees were sampled, not swept.** Four per-release paths were
   hashed across all of them; the rest were not. Pre-migration releases hold full
   real `data/cio` and `data/runtime` trees that were never enumerated. Every
   per-release count in §2.4 is a **floor**.
