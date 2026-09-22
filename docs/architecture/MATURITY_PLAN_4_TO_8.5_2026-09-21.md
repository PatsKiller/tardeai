# Getting from 4 to 8.5 — the plan, with the arithmetic shown

**2026-09-21, 20:45 ET.** Every number here was queried in the last thirty
minutes. Where it contradicts the 19:05 assessment, the newer number wins and
the correction is stated — three of that document's headline claims were wrong,
all in the direction of *worse*.

---

## 0. What "8.5" means, so it is not a number I grade myself against

A self-invented scale that I both set and score is worthless. The target is
pinned to four external bars:

| source | the bar it sets |
|---|---|
| [DORA 2025](https://getdx.com/blog/dora-metrics/) | top-15% = change-failure rate < 4%, lead time < 1 day, recovery < 1 hour, deploy on demand |
| [Google SRE Workbook — alerting on SLOs](https://sre.google/workbook/alerting-on-slos/) | multiwindow, multi-burn-rate alerting against an error budget |
| [SRE alerting practice](https://incident.io/blog/sre-alerting-best-practices) | *"if the on-call engineer cannot take a specific action, the alert should not exist"* |
| [PagerDuty Operations Maturity Model](https://www.pagerduty.com/blog/real-time-operations-maturity-model/) | five tiers: Manual → Reactive → **Responsive** → **Proactive** → Preventive |

On PagerDuty's ladder this platform is **Reactive** today: issues are discovered
when the operator reports them, and real-time visibility into production
problems is largely absent. **8.5 = solidly Proactive** — most issues surfaced
and resolved before the operator notices, with the system's own learnings
recorded and joinable.

The single most important consequence of that framing:

> **`grep -rl "error_budget\|slo_target\|burn_rate" scripts/ config/` returns
> nothing.** There is no SLO, anywhere, for anything.

Every alert in this system is therefore a threshold alert on a cause, not a
symptom alert on a budget. That is the root of the alert-signal score, and no
amount of per-alert tuning fixes it.

---

## 1. The score, re-measured tonight

| # | dimension | 19:05 | **now** | target | Δ | the measurement |
|---|---|---:|---:|---:|---:|---|
| 1 | Capital-protection correctness | 7 | **7** | 9 | +2 | trailing-stop fix live; starred gate fed (12 symbols); `kill_switch_state` **0 rows** |
| 2 | Alert delivery (does it arrive) | 5 | **5** | 9 | +4 | 62 of 7,991 alerts carry a `telegram_message_id` (0.78%); **79 SETTLED** of 52,930 |
| 3 | Alert *signal* (worth reading) | 3 | **2** | 9 | +7 | storm is **78/hour, every hour**; 40,444 lifetime; `notification_log` blind |
| 4 | Identity / GUIDs | 4 | **5** | 9 | +4 | tripwire residue 9,909 → **16**; outbound 8,691/52,678 = 16.5%; inbound **1 of 252** |
| 5 | Memory / joinability | 2 | **3** | 8 | +5 | `correlation_id` + `thread_id` **100%**; `causation_id` + `parent_event_id` **0** |
| 6 | Observability of its own failures | 3 | **3** | 8 | +5 | 128 monitors, 26 in cron; 100 MB log holding 212 tracebacks; **no SLO** |
| 7 | Test / gate honesty | 5 | **5** | 8 | +3 | CI runs 971 of 1,445 test files (67%); alarm firing coverage **35/187 = 18.7%** |
| 8 | Deploy discipline | 8 | **8** | 9 | +1 | served is 2 doc-commits behind main; `prepare`/`promote` strict and refusing |

**38 / 80 = 4.75 today. 69 / 80 = 8.6 at target. The gap is +31 points, and
dimension 3 alone is +7 of it.**

### Corrections to the 19:05 assessment

1. **The storm was under-counted and mis-located.** It does not appear in
   `alert_events` at all — `_notify()` at `claude_escalation_handler.py:552-557`
   calls `send_telegram` directly, bypassing the alert plane. Counted from its
   own log: `logs/claude_escalation.log` is **68 MB**, holds **40,444**
   AUTO-RETRY notifications and **34,036** exhaustion lines, **1,569 today** — a
   flat **78 per hour** at 13:00, 14:00, 15:00, 16:00, 17:00, 18:00 and 19:00.
   Both earlier figures ("403 in 2h", "~4,800/day") were wrong. The true rate is
   metronomic and cannot converge: `BACKOFF_MINUTES = [0, 5, 15, 30]` with
   `EXHAUST_RESET_SEC = 1800`.
2. **`destination_policy_id` was measured against a table that does not have
   it.** It lives on `communication_deliveries` and `communication_outbox`, not
   `communication_events`. Re-derived: **0 of 52,929** and **0 of 52,928**. The
   finding survives; the citation was wrong.
3. **Lineage is half-built, not missing.** `correlation_id` and `thread_id` are
   populated on **100%** of 52,930 events. Only `causation_id` and
   `parent_event_id` are zero. This is wiring two existing columns, not
   designing a lineage model — a much smaller job than the assessment implied.

---

## 2. The one structural cause

Four separate defects today, one shape:

> **A check that passes on the wrong dimension is worse than no check.**

Tonight added three more instances, all caught only by running things:

- the disk guard reported `over_threshold: false` at `df` 89%, because
  `used/total` counts the root reserve that `used/(used+avail)` excludes;
- a `COVERS` pin at `:118` silently stopped matching when an unrelated docstring
  moved the call to `:132` — the gate went red about a site carrying six tests;
- the firing test satisfied the coverage ratchet while sitting outside the CI
  gate list entirely, because `declared_covers()` globs every `tests/test_*.py`
  regardless of whether CI runs it.

**Every phase below therefore ships its gate as a measurement of the production
condition, never of a pure function.** A phase is not done when its code merges.
It is done when a query over production data crosses a stated threshold.

---

## 3. The plan

### Phase 0 — Collect what is already paid for (now → tomorrow 09:00)

No new code. Three things are written, merged and unproven.

| item | proof due | how |
|---|---|---|
| #1176 disk guard + worktree retention | on merge | CI green, then install the two timers |
| #1170 strategy cards | **06:00** | `watchlist_strategy_cards` fresh count > 1 of 5,808 |
| #1172 starred-only paging | **09:00** | zero `ENTRY_NEAR` pages for unstarred names |

Deploy the 2-commit gap so Drive picks up tonight's documents.

**Gate:** all three verified by query, not by exit code.

---

### Phase 1 — Kill the storm (week 1) · dimension 3: 2 → 7

The largest single gain available, and the cheapest. One call site.

1. **Route `_notify()` through the chokepoint.** `claude_escalation_handler.py:552`
   calls `send_telegram` directly. Send it through `publish_communication` so it
   is deduped, fatigue-tracked and recorded like everything else.
2. **Disambiguate `_age_days_table`'s `None`.** It returns `None` for both
   "table absent" and "query raised", and line 94 renders both as *"no output"* —
   which is why the storm's premise is false while it fires. Three lines.
3. **Register it with alert fatigue.** `notification_log` holds 177 rows and
   **0** mention escalation; the largest alert source is invisible to the one
   control designed to suppress it.
4. **Cap re-arm.** A condition that has exhausted 40,444 times is not a
   transient; after N exhaustions it becomes one open incident, not a new page.

**Gate:** escalation notifications/day **< 20** (from ~1,872), and
`notification_log` rows referencing escalation **> 0**. Both queried at day 7.

---

### Phase 2 — Make delivery provable (week 1-2) · dimension 2: 5 → 9

Three one-line breaks, already named:

1. `telegram_alert._raw_send_telegram_result()` captures `message_id`;
   `_legacy_send()` returns a bare bool and discards it one frame later.
2. `alert_event_writer.py:67` accepts `telegram_message_id` and writes it at
   :98-111 — **zero of 26 call sites pass it**.
3. `provider_settlement_state` is `UNSETTLED` on 51,193 of 52,930 rows. Settle it
   on send confirmation.

Then write `destination_policy_id` at the outbox so the question *"are the right
channels used"* becomes answerable from the system's own data — today it is
0-populated on both tables that carry the column.

**Gate:** ≥ 95% of last-7-day alerts carry a `telegram_message_id`; `SETTLED`
≥ 95% of last-7-day events; `destination_policy_id` non-null ≥ 95%.

---

### Phase 3 — Identity at the publish chokepoint (week 2) · dimension 4: 5 → 9

The repair proved the *mechanism* works (residue 9,909 → 16) but covered one
template. 43 producers publish directly and exactly one tags.

- Tag inside `publish_communication`, not the legacy path — one function closes
  all 43 producers.
- Give the outbound identity test a database. It asserts the pure extractor and
  never the write; that is exactly why CI was green over a 0% condition.
- Backfill 30 days once the writer is proven.

**Gate:** outbound `subject_guid` ≥ 95% (from 16.5%); inbound ≥ 90% (from
**1 of 252**); the DB-touching test fails RED when the writer is reverted.

---

### Phase 4 — Close the memory join (week 3) · dimension 5: 3 → 8

Smaller than it looked, because `correlation_id` and `thread_id` are already
100% populated.

- Populate `causation_id` and `parent_event_id` at publish — both exist, both 0.
- Carry `subject_guid` into agent consumption receipts (0 of 199 today).
- `AGENTS.md:835` requires two-way tagging; the inbound tagger exists, is in CI,
  and has written nothing since it was built.

**Gate:** every reply in a 7-day window resolves to the event that caused it;
agent receipts joinable to a subject by GUID ≥ 90%.

---

### Phase 5 — SLOs and self-observability (week 3-4) · dimension 6: 3 → 8

This is the phase the external research changes most, because the finding is
*absence*, not weakness.

1. **Define error budgets.** None exist. Start with three that matter: alert
   delivery success, card freshness, quote freshness.
2. **Convert to burn-rate alerting** — multiwindow, multi-burn-rate, per the SRE
   workbook. Alert on symptoms against budget, not on causes crossing thresholds.
3. **A runbook link on every alert.** The SRE production-readiness bar: each
   alert explains why it fired and what to check first.
4. **Rotate `.jsonl`.** `rotate_runtime_logs.sh` matches only `*.log`, so
   `safe_flock_events.jsonl` (86 MB) and `llm_router_safety.jsonl` (55 MB) grow
   unbounded — and `watchlist_strategy_cards.log` sits at exactly 100 MB holding
   212 tracebacks nobody reads.
5. **Consolidate 128 monitors** onto `lib/alert_condition_state`, which 7
   scheduled scripts already use correctly. A monitor that has never fired is
   proven by a negative control or archived.

**Gate:** ≥ 3 SLOs defined with budgets; every alert carries a runbook link; no
log file > 100 MB; every scheduled monitor either fired or has a passing
negative control.

---

### Phase 6 — Gate honesty (continuous) · dimension 7: 5 → 8

- Alarm firing coverage **18.7% → 60%** (35 of 187 today). The ratchet only
  moves down; batching stopped 2026-09-01 by decision and should resume.
- CI test files **67% → 85%** (971 of 1,445).
- Close the `reviewer != scorer` gap in `contracts.py` — producer ≠ reviewer is
  enforced, but one agent may still both review and score the same artifact.
- Declare the 522-entry `undeclared_baseline` down toward zero.

**Gate:** coverage ratchet at 60%; no new `send_telegram` site merges without a
firing test **listed in the gate**, not merely declared in `COVERS`.

---

## 4. Sequence and why this order

```
Phase 0  ──►  Phase 1  ──►  Phase 2  ──►  Phase 3  ──►  Phase 4
(collect)     (storm)       (delivery)    (identity)    (lineage)
                 │              │
                 └──────────────┴──►  Phase 5 (SLOs)  ──►  Phase 6 (gates)
```

The storm is first because it is 82.6% of suppressed deliveries and it corrupted
the identity spine for ten days — every downstream measurement is noisy until it
stops. Delivery precedes identity because an untracked send cannot be verified
as correctly tagged. SLOs come after 1-2 because an error budget computed over
storm traffic would be meaningless.

## 5. What would falsify this plan

- If Phase 1 lands and escalation volume does **not** fall below 20/day, the
  cause is not the notify path and the premise fix is wrong.
- If Phase 3 lands and outbound tagging does not exceed 95%, then producers are
  not routing through `publish_communication` either, and the chokepoint theory
  is wrong — the work becomes 43 call sites, not one function.
- If after Phase 5 the monitors still never fire, consolidation was the wrong
  answer and the monitors were measuring conditions that do not occur.

## 6. What this plan deliberately does not do

- **No broker execution.** `MBI_BEHAVIOR = 0` throughout.
- **No deletions.** Archive with tripwire, per AGENTS §0 rule 6. The tripwire
  installed today is already earning its place — it reported residue I would
  otherwise have called clean.
- **No new cron or systemd entry without operator approval** (§17).
- **`market_quotes` stays at 90 days.** The 7-day cut recommended earlier was
  wrong: `rotation_ladders._sector_momentum_returns` reads it at 21/63/126-day
  lookbacks. The correct fix is downsampling (117.4 intraday rows per daily
  close), which reclaims ~5.67 GB *and* extends history — a separate PR.

---

## 7. Operator review, 2026-09-21 — five enhancements, two corrections

An independent review of this plan proposed five additions. Four are adopted as
written. One is adopted with a **material change of location**, and the review's
headline arithmetic needs correcting.

### Correction A — the score

The review states 38/80 as **3.8/10**. It is **4.75/10** (38 ÷ 8 dimensions, not
÷ 10). This matters: it sizes the remaining work at **+31 points**, not +47.

### Correction B — where the stance interdict must live

The review places the 24/7 CIO stance gate inside `publish_communication`.
**Verified against the source, that placement would not hold a message on the
default path.**

```
telegram_alert.send_telegram, legacy branch:
    ok = _legacy_send(...)                                   # <- message is SENT
    _best_effort_comms_publish(message, delivered=bool(ok))  # <- ledger write
    return ok
```

`publish_communication` runs **after** the send on the legacy path, and only
before it on the gateway path (`Order: publish_communication →
send_via_gateway(..., deliver=True)`). Since `COMMS_GATEWAY_MODE` fails closed to
`OFF`, the legacy path is the default — so a gate there would interdict ~79
messages and merely *annotate* the other ~53,000.

That is the review's own "annotate-not-hold" defect (its item 2), reproduced one
layer down.

**Correct host: `telegram_transport.send_message()`** — *"the only module allowed
to know the sendMessage / editMessageText Bot API"*. Both paths import it (legacy
via `telegram_alert:19`, gateway via `channel_adapters`), it is pre-send by
construction, and it already hosts `_interdicted()`, which proves the pattern
works at that layer and notes that any caller reaching past it bypasses the
interdict entirely.

### What already exists (so this is wiring, not building)

`scripts/lib/cio_telegram_stance_gate.py` — `CioTelegramStanceGate@v1` — already
implements the hard gate *and* Enhancement 3's fail-closed rule verbatim:

> *"Missing CIO row, unreadable store, or non-aligned action → hold
> (`allow=False` + `held_reason`). Never annotate-and-send from here."*

It writes durable hold receipts to `cio_telegram_stance_holds.jsonl` for
`LIVE-cio-stance-governance`. `cio_decisions` is healthy: **53,410 rows**, newest
2026-09-21 16:20.

**But only five publishers call it** — `send_telegram_proposal_alert`,
`screener_go_alerts`, `social_scalp_scanner`, `comms_editor`,
`report_organic_stance_hold`. That scatter is exactly the ungated-publisher
finding. Moving the call to the transport closes it for every current and future
producer at once.

### Adopted

| # | enhancement | phase | change from the review |
|---|---|---|---|
| 1 | 24/7 stance interdict | **3** | host at `telegram_transport.send_message`, not `publish_communication` |
| 2 | `AdjudicationReceipt@v1` written synchronously before operator commit | **4** | adopted as written |
| 3 | Fail-closed on stale/unknown stance | **1+3** | **already implemented** in the existing gate — wire it, don't build it |
| 4 | Hermetic negative-control test: synthetic BUY against an active AVOID must hold | **6** | adopted as written; this is the discipline the whole plan runs on |
| 5 | `MemoryRetrievalUnit@v1` bounded context (12k cap) for Telegram briefs | **5** | adopted as written |

Enhancement 4 deserves emphasis. Every gate added tonight shipped with a control
proving it can fail — a stubbed body failing 3 of 6 tests, a shadowed import
going RED on pristine main. A stance gate without that control would be the
seventh instance of a check passing on the wrong dimension.

### Not verified here

The review cites a Telegram layer audit at **32/100** and agent controls at
**21/30**. Those come from its own sources; I have not reproduced them and do not
restate them as measured facts.
