# Maturity status — 2026-09-22

**All six phases are BUILT and INTEGRATED. Nothing is pushed. Nothing is deployed.
Nothing is scheduled or armed.**

Supersedes `MATURITY_STATUS_2026-09-21-2205.md` as the current status record.
The roadmap remains `MATURITY_PLAN_4_TO_8.5_2026-09-21_ENHANCED.md`.

Integration branch: `integrate/maturity-phases-20260922` @ `215e9235a`
— 13 commits, 41 files, +3,778 / −122 against `origin/main` (`ecd585710`).

---

## 1. The score has NOT moved to 8.6, and this document will not claim it has

The baseline is **4.75/10** (38/80 across 8 dimensions — divide by 8, not 10).

Every phase gate in the plan is stated as a **production measurement**: alert
notifications per day, percentage of alerts carrying a `telegram_message_id`,
outbound `subject_guid` coverage, GUID join rate. Those numbers are produced by
the running system. **This code is not running**: `origin/main` is unchanged, the
served release is unchanged, and no timer or cron was added.

So the honest statement is: the **capability** for phases 1–6 now exists and is
gated by tests that fail when it is removed. The **maturity score** is a
measurement of live behaviour and cannot move until this is deployed and the
gates are re-measured against production. Claiming 8.6 today would be the exact
defect this program was created to eliminate — a number that improves because of
what was written rather than what was observed.

---

## 2. What each phase actually delivered

| Phase | Branch @ HEAD | Delivered | Gate state |
|---|---|---|---|
| 1 — kill the storm | `7624192ee` | Liveness-based reaping via the producer aggregate; `_escalate` dedupe | Crashes 10/hr → 0 (measured). Queue drain is **operator-gated** |
| 2 — provable delivery | `6a9c32b11` | 7 call sites wired; legacy settlement passes `provider_message_id`; `destination_policy_id` at the outbox | **Unmet.** ~20 SIEM-only sites have no id to attach |
| 3 — identity at the chokepoint | `3e647b793` | `subject_guid` stamped inside `publish_communication` before persist | Forward-only; **no backfill run** |
| 4 — close the memory join | `43f9fc47e` | `causation_id` / `parent_event_id` defaults; `subject_guid` into receipt INSERT | Forward-only; 54,928 existing rows untouched |
| 5 — SLOs and burn rate | `af1ecf687` | 3 SLOs on verified feeds + multiwindow multi-burn-rate calculator | Targets are **`PROPOSED`**, unratified |
| 6 — gate honesty | `dfb9ab2c1` | `reviewer != scorer` closed in both orders; 10 alarms observed firing; 10 suites promoted | Coverage 34.6% → **35.4%** |

---

## 3. The two defects that only integration could find

Both branches were green in isolation. Neither defect exists on any single
branch. This is the argument for integrating before reporting.

### 3.1 A coverage denominator that shrank when code was edited

`lib/alarm_firing_coverage.call_sites` matched exactly one name,
`TRANSPORT == "send_telegram"`. Phase 2 rewrote six alarm sites to
`send_telegram_with_id(...)` to capture the provider message id:

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
counting both public entrypoints — `telegram_alert.py:636` defines
`send_telegram_with_id` as "`send_telegram()`, plus the provider message id it
already had". `sites_total` restored to exactly **188**.

### 3.2 A reaper whose probe could not see most of what it deleted

The reaper merged in #1183 probed two named collectors and treated absence from
those two as "condition resolved". A finding's *category* is not owned by a
collector of the same name — `health_agent` has **38 collectors**, several
emitting into one category. Against the live queue the narrow probe reported
**14 entries removable when 8 were LIVE**, including all five research lanes.

Fixed by probing `health_agent.compute()`, the producer's own aggregate, which
builds the identical key `enqueue_escalations` uses at `health_agent.py:3748`.

---

## 4. Known gaps — named, not smoothed over

- **`send_telegram_document` has 4 call sites and has NEVER been counted**, on
  this branch or on main. Counting it expands the ratchet 188 → 192 and needs
  four new baseline entries. Deliberate widening, left for an explicit decision.
- **Phase 5's `alert_delivery` SLO measures provenance, not delivery.** With 11
  of 866 rows carrying an id, it cannot distinguish "not delivered" from
  "delivered but not recorded".
- **Phase 5's `card_freshness` burns by construction** — the producer runs
  roughly weekly; the 36h budget is a documented choice, not a ratified target.
- **141 alarm sites remain untested**; the cheap single-site helpers are
  exhausted.
- **939 files remain unlisted** in the coverage baseline.
- Ten notifiers **discard the transport's verdict** — `stop_health_check`
  returned `True` even when the send was refused. Recorded, not asserted.
- **14 ruff `F541` errors** are pre-existing; count verified identical on
  `origin/main`.

---

## 5. Operator-only — nothing below was done (AGENTS §0 rule 9, §17)

1. **Push.** §17 two-push rule; needs explicit intent plus the override flags.
2. **Deploy.** `cio_phase2_exact_main_deploy.sh prepare` then `promote`. The
   escalation handler resolves `PROJECT_ROOT` to the **served release**, so a
   dev-tree fast-forward is not a deploy.
3. **`escalation_queue_reaper.py --apply`** — 5 entries currently removable, all
   proven absent by the full probe. Dry run quoted in the branch.
4. **Ratify the three SLO targets**, all `PROPOSED`.
5. **The `send_telegram_document` ratchet decision** (§4 above).
6. **Any scheduling or arming.** No cron, no timer, no unit was added.

---

## 6. Verification

185 tests pass across all six phase suites plus the alarm ratchet and the
coverage, docs-index and both SOP gates. Every phase ships a control that goes
red when its change is reverted.

One correction worth recording: an earlier gate run in this session was green
while the alarm ratchet was red, because `tests/test_alarm_coverage.py` was not
in the run. The missing check, not the defect, is the reusable lesson —
**a check that passes on the wrong dimension is worse than no check.**

Control-surface digest for the integrated tree: `01ff7baa2c8e` (six branches
each rebound the same four evidence files; collapsed to one after the merge).
