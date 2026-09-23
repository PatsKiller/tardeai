# Maturity status — 2026-09-22

**All six phases are BUILT, INTEGRATED, MERGED and DEPLOYED. The SLO timer is
installed, enabled and has fired. The three SLO targets are RATIFIED.**

Supersedes `MATURITY_STATUS_2026-09-21-2205.md` as the current status record.
The roadmap remains `MATURITY_PLAN_4_TO_8.5_2026-09-21_ENHANCED.md`.

Merged as **PR #1184**. `origin/main` is **`f9c77fe1bba414586df6412488c15a39a7ed9dad`**
(merged 2026-09-22T14:42:27Z). This supersedes the earlier revision of this
document, which said "Nothing is pushed. Nothing is deployed." That was true
when written and is no longer true; it is corrected here rather than quietly
overwritten.

---

## 1. The score still has NOT moved to 8.6, and this document will not claim it has

The baseline is **4.75/10** (38/80 across 8 dimensions — divide by 8, not 10).

Deployment removes the *excuse* for an unmeasured score; it does not supply the
measurement. Every phase gate is stated as a production measurement, and the
code has now been live for under two hours. Two of those gates were also found
to be **wrongly stated** and were restated today (§2). A score quoted before a
full measurement window has elapsed against the *corrected* gates would be the
exact defect this program exists to eliminate.

What changed today is that the gates can now be measured at all.

---

## 2. Two gate definitions were provably wrong and have been restated

Both corrections make the gate **harder or unchanged in strictness**. Neither
lowers a threshold.

### 2.1 Phase 1 — the storm baseline was a mid-day count sold as a daily one

The frozen baseline read **1,673**. That was a partial-day count taken mid-day
on 09-21, compared against a *per-day* target. Re-measured 2026-09-22 against
the same unrotated log (continuous since 2026-08-27):

```bash
grep -c '^2026-09-21.*exhausted after' \
  /home/johnclaw/trade-ai-releases/persistent-state/logs/claude_escalation.log
```

| Date | lines | coverage |
|---|---|---|
| 2026-09-18 | 3,682 | full day |
| 2026-09-19 | 2,278 | full day |
| 2026-09-20 | 6,110 | full day |
| **2026-09-21** | **7,627** | **full day — the corrected baseline** |
| 2026-09-22 | 1,433 | partial, to 11:40 EDT |

The gate (<20/day) now demands a **99.74%** reduction where the partial figure
implied 98.8%. **Harder, and honest.**

### 2.2 Phase 2 — the delivery gate had an unreachable denominator

It read "≥95% of last-7-day **alerts** carry a `telegram_message_id`". That
counts every row in `communication_deliveries`, of which **97.67% are
`SUPPRESSED`** — deliberately never handed to Telegram, so no provider id can
exist. The all-rows denominator has a **ceiling of 2.1%**: unpassable by any
amount of correct work.

Restated against DELIVERED (`status IN ('SENT','LEGACY_DELIVERED')`). Measured
7-day window, 2026-09-22:

```
 SUPPRESSED       | 44182 |  0 with id
 LEGACY_DELIVERED |   885 |  0
 RESERVED         |   112 |  0
 SENT             |    57 | 55
 DELIVERED total  |   942 | 55  ->  5.8%   (target 95%, unchanged)
```

The restated gate reports **5.8%**, worse than the 24-hour slice (13.8%, 19 of
138), because the legacy path carried no id for most of the week. The 7-day
window is the one the gate names, so 5.8% is the governing number.

The `SETTLED ≥95%` clause is **withdrawn**: `SETTLED` is not admitted by
`communication_deliveries_status_check` and returns 0 rows by construction.
`destination_policy_id`, restated on the DELIVERED denominator, is **1.9%**
(18 of 942).

---

## 3. Deployment — verified, not asserted

| Claim | Evidence |
|---|---|
| PR #1184 merged | `gh pr view 1184` → `MERGED`, mergeCommit `f9c77fe1b…` |
| `origin/main` = `f9c77fe1b` | `git rev-parse origin/main` |
| Promoted, health gate passed | `~/.local/state/cio-phase2-exact-main/deploy_receipt.json`: `"ok": true, "mode": "promote", "health": "ok", "rolled_back": false`, `"at": "2026-09-22T14:44:45Z"` (10:44:45 EDT) |
| Served release is the new one | `CURRENT` → `f9c77fe1b-main-exact-phase2-20260922-104303` (symlink mtime 10:44); `BUILD_SHA` matches `origin/main` |
| Served `PROJECT_ROOT` resolves | `get_live_project_root()` → that same release directory |
| API healthy | `GET /api/v2/health` → 200, `{"ok": true}` (note: bare `/health` is 404; the deploy gate uses `/api/v2/health`) |

### Disk

`1f8174362` recorded **94% used / 29 GB free and falling → 78% / 101 GB free,
64.4 GB reclaimed**, applied via `disk_hygiene_enforcer --apply` (8 deleted, 0
errors). Measured now: **77% used, 338 GB used, 107 GB available**.

Root cause: `cmd_prepare` has **two** copy paths. `8dc78d9aa` (09-21) added
`--exclude='.claude/'` to the git-tree overlay only; the *other* rsync clones
the **previous release** and carried `.claude/worktrees` — Claude Code session
trees, not application data — forward generation after generation. Excluding a
path in one of two copy paths reclaims nothing.

Result: the new release is **837 MB** against three surviving 13 GB
predecessors. Retention was also switched off count (`keep_n=10` deleted nothing
while nine 13 GB releases sat on disk) to `keep_n=2`.

### SLOs

- `tradeai-slo-burn-rate.timer` — **enabled**, last fired **Tue 2026-09-22
  10:45:43 EDT**; unit finished cleanly (`systemctl --user list-timers`,
  `journalctl --user -u tradeai-slo-burn-rate.service`).
- Receipt written: `artifacts/slo/slo_burn_rate_20260922T144543+0000.json`
  (`"database": "connected"`, `SLOBurnRateReport@v1`).
- `config/slo_targets.json` → **`"status": "RATIFIED"`**, operator-ratified
  2026-09-22. Ratification did **not** loosen a budget: `card_freshness` still
  burns against 36h and that remains the finding.
- The service is **measurement only** — it sends no alert and pages nobody.

---

## 4. Three claims I could not verify, stated as failures

Reality is recorded here even where it contradicts the summary this document was
asked to adopt.

1. **"157 tests pass" is wrong. The measured number is 151.** Running the nine
   test files PR #1184 brought (`git diff --name-only f9c77fe1b^1..f9c77fe1b --
   tests/`) gives `151 passed` in 48s. Per file: alarm_coverage 7,
   alarm_fires_batch6 23, alert_delivery_wiring 31, escalation_queue_reaper 12,
   hermes_escalation_dedupe 7, independence_reviewer_scorer 10,
   phase4_lineage_join 15, publish_chokepoint_identity 14, slo_burn_rate 32 =
   **151**. The earlier "185" is also not reproducible as stated; it counted
   additional gate suites beyond the phase suites.
2. **"escalation queue reaped 18 → 14" is not reproducible.** Measured entry
   counts: **28** (`bak-20260922-090506`, 09:05 EDT) → **18**
   (`bak-20260922-150657`, 11:01 EDT) → **18** (live file, 11:40 EDT). No 14
   was observed. The queue churns continuously in both directions — between
   11:01 and 11:40 four components dropped and four different ones were added —
   so a single before/after pair is a weak instrument here.
3. **The handler shedding review-only items IS confirmed.**
   `claude_escalation.log` at 11:35:18 and 11:40:02 shows
   `🗑 Drop operator/review-only from queue:` for nine and eleven components
   respectively. That part of the claim holds; only the 18 → 14 arithmetic does
   not.

Minor drift, recorded rather than smoothed: the release is 837 MB (not 820 MB),
and disk sits at 77% (the commit receipt recorded 78%).

---

## 5. What each phase delivered

| Phase | Delivered | Gate state after deploy |
|---|---|---|
| 1 — kill the storm | Liveness-based reaping via the producer aggregate; `_escalate` dedupe | Baseline **restated to 7,627/day** (§2.1). Crashes 10/hr → 0 |
| 2 — provable delivery | Call sites wired; legacy settlement passes `provider_message_id`; `destination_policy_id` at the outbox | **Restated denominator** (§2.2). **5.8%** of 942 DELIVERED vs 95% |
| 3 — identity at the chokepoint | `subject_guid` stamped inside `publish_communication` before persist | Forward-only; **no backfill run** |
| 4 — close the memory join | `causation_id` / `parent_event_id` defaults; `subject_guid` into receipt INSERT | Forward-only; 54,928 existing rows untouched |
| 5 — SLOs and burn rate | 3 SLOs on verified feeds + multiwindow burn-rate calculator | Targets **RATIFIED**; timer fired; receipt written |
| 6 — gate honesty | `reviewer != scorer` closed both orders; alarms observed firing; suites promoted | Ratchet widened 188 → **192** (`send_telegram_document` now counted) |

---

## 6. The two defects that only integration could find

Both branches were green in isolation. Neither defect exists on any single
branch. This is the argument for integrating before reporting.

### 6.1 A coverage denominator that shrank when code was edited

`lib/alarm_firing_coverage.call_sites` matched exactly one name,
`TRANSPORT == "send_telegram"`. Phase 2 rewrote six alarm sites to
`send_telegram_with_id(...)`:

```
sites_total  188 -> 182
  scripts/portfolio_alerts.py             baseline 1, actual 0
  scripts/portfolio_live_monitor.py       baseline 1, actual 0
  scripts/stop_decision_brief.py          baseline 1, actual 0
  scripts/stop_drift_alert.py             baseline 1, actual 0
  scripts/stop_over_consensus_monitor.py  baseline 1, actual 0
```

**Five of the six were UNCOVERED sites.** Coverage would have risen because the
measured thing became invisible, while nothing had been tested. Fixed by
counting both public entrypoints. `sites_total` restored to 188, then
deliberately widened to **192** when `send_telegram_document`'s four
never-counted sites were added by operator decision.

### 6.2 A reaper whose probe could not see most of what it deleted

The reaper merged in #1183 probed two named collectors and treated absence from
those two as "condition resolved". A finding's *category* is not owned by a
collector of the same name — `health_agent` has **38 collectors**, several
emitting into one category. Against the live queue the narrow probe reported
**14 entries removable when 8 were LIVE**, including all five research lanes.

Fixed by probing `health_agent.compute()`, the producer's own aggregate, which
builds the identical key `enqueue_escalations` uses at `health_agent.py:3748`.

---

## 7. Known gaps — named, not smoothed over

- **The Phase 2 gate is far from met: 5.8% against 95%.** Restating the
  denominator made it measurable, not met.
- **Phase 5's `alert_delivery` SLO measures provenance, not delivery.** It
  cannot distinguish "not delivered" from "delivered but not recorded". Ratified
  with that caveat explicitly accepted, not silenced.
- **Phase 5's `card_freshness` burns by construction** — the producer runs
  roughly weekly against a 36h budget.
- **No paging path is built on the SLO budgets.** The timer measures; it does
  not notify.
- Phases 3 and 4 are **forward-only**; no backfill has been run.
- **141 alarm sites remain untested**; the cheap single-site helpers are
  exhausted.
- Ten notifiers **discard the transport's verdict**. Recorded, not asserted.
- **14 ruff `F541` errors** are pre-existing; count verified identical on
  `origin/main`.
- `ACTIVE_RELEASE` in the release directory is **stale** (dated 2026-08-11);
  `EXPECTED_RELEASE` and `CURRENT` are both current. The live pointer is
  `CURRENT`, but the stale file is a trap for a reader who picks the
  wrong-looking name.

---

## 8. Operator-only — what remains (AGENTS §0 rule 9, §17)

Done today: push, deploy, SLO ratification, the `send_telegram_document` ratchet
decision, and installing the SLO timer.

Still operator-only and **not done**:

1. **`escalation_queue_reaper.py --apply`** for any further drain — the handler's
   own review-only shedding is running, but a reaper apply is a separate,
   gated action.
2. **Any backfill** for phases 3 and 4 (54,928 rows untouched).
3. **Arming any notification** on the SLO budgets. Measurement is armed;
   paging is not.
4. **Re-measuring both restated gates** after a full window has elapsed, and
   only then revisiting the maturity score.

---

## 9. Verification

**151 tests pass** across the nine suites PR #1184 delivered (§4.1), run on the
deployed `f9c77fe1b` tree. Every phase ships a control that goes red when its
change is reverted. The two restated gates are pinned by
`tests/test_maturity_gate_restatement_20260922.py`, whose negative controls fail
if either gate drifts back to its unreachable or partial-day wording.

One correction worth keeping: an earlier gate run in this session was green
while the alarm ratchet was red, because `tests/test_alarm_coverage.py` was not
in the run. The missing check, not the defect, is the reusable lesson —
**a check that passes on the wrong dimension is worse than no check.**
