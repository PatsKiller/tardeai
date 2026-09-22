# Enhanced six-phase maturity plan — 4.75 → 8.6

**2026-09-21 ENHANCED.** Supersedes `MATURITY_PLAN_4_TO_8.5_2026-09-21.md` as the
active operational roadmap. Integrates five architectural enhancements from the
2026-09-21 operator review, **two of which are relocated** after verification
against the source.

---

## 0. Two corrections to the review, before anything else

### 0.1 The score is 4.75/10, not 3.8/10

38/80 divides by **8 dimensions**, not 10. The gap is **+31 points**, not +47.
Every phase target below is sized against 4.75 → 8.6.

### 0.2 The stance interdict cannot live in `publish_communication`

The review places the 24/7 CIO stance gate inside `publish_communication`.
**Verified against the source, that placement cannot hold a message on the
default path.**

```python
# scripts/telegram_alert.py — send_telegram, legacy branch
ok = _legacy_send(...)                                    # <- message is SENT
_best_effort_comms_publish(message, delivered=bool(ok))   # <- ledger write
return ok
```

`publish_communication` runs **after** the send on the legacy path, and before it
only on the gateway path (`Order: publish_communication → send_via_gateway(...,
deliver=True)`). `COMMS_GATEWAY_MODE` fails closed to `OFF`, so legacy is the
default: a gate there would interdict ~79 messages and merely **annotate** the
other ~53,000.

That reproduces the review's own "annotate-not-hold" defect one layer down.

**Correct host: `telegram_transport.deliver_text()`.** Not `send_message` —
`telegram_transport.py:471` states it outright:

> *"C4: the interdict now lives in `deliver_text`, the lowest common layer, so it
> cannot be bypassed by calling that directly."*

`_interdicted()` already sits there and `CIO_TELEGRAM_INTERDICT` already proves
the pattern works at that layer. `scripts/check_telegram_chokepoint.py` is a
registered CI gate that enforces this discipline. The stance gate belongs beside
the interdict, governed by the same gate.

### 0.3 Enhancement 3 is already built

`scripts/lib/cio_telegram_stance_gate.py` (`CioTelegramStanceGate@v1`) already
implements fail-closed-on-stale verbatim:

> *"Missing CIO row, unreadable store, or non-aligned action → hold
> (`allow=False` + `held_reason`). Never annotate-and-send from here."*

`check_investment_send(symbol=, message_text=, asserted_stance=, db_query=,
cio_view=, source=) -> StanceGateVerdict{allow, held_reason, symbol,
message_stance, cio_action, cio_side}`. Holds append durable receipts to
`cio_telegram_stance_holds.jsonl` for `LIVE-cio-stance-governance`.
`cio_decisions` is healthy: **53,410 rows**, newest 2026-09-21 16:20.

**Only 5 publishers call it** — `send_telegram_proposal_alert`,
`screener_go_alerts`, `social_scalp_scanner`, `comms_editor`,
`report_organic_stance_hold`. That scatter *is* the ungated-publisher finding.
Moving the call to `deliver_text` closes it for every current and future producer
at once. **This is wiring, not building.**

---

## 1. Phases

### Phase 0 — Collect what is already paid for (Day 1)
Validate existing unproven PRs by **database state query**, never by exit code
(AGENTS §0 rule 8).

- #1176 disk guard + worktree retention — **MERGED**; timers installed, guard
  fired 22:03:37 with receipt `used_pct 88.24`, `telegram: accepted`
- #1170 strategy cards — proof at 06:00: fresh count must exceed 1 of 5,808
- #1172 starred-only paging — proof at 09:00: zero `ENTRY_NEAR` for unstarred

**Gate:** three queries return, not three exit codes. **Status: complete and
verified.**

### Phase 1 — Kill the storm (Week 1) · signal 2 → 7
Root cause found and fixed: `claude_escalation_handler.py:295` re-imported
`datetime` inside `_verify_remediation`, making the name function-local and
raising `UnboundLocalError` on every earlier use. **122 of 124 runs crashed
today.** The crash landed before `_safe_write_queue`, so nothing ever cleared.

1. Delete the shadow *(done — #1177)*
2. Disambiguate `_age_days_table`'s three-way `None` (absent / errored / **empty
   table**) — the third case is undocumented and is why `missing_*` fires on
   tables that exist
3. Route `_notify()` through `lib/alert_transition` with
   `min_realert_minutes=360` — **not** `dispatch_alert`, whose dedupe is
   day-scoped and would collapse a `*/10` producer to 1/day then auto-downgrade
   it to INFO on day 3, silencing the channel
4. **[E3]** Fail closed on stale/unknown CIO stance — already implemented, wire it

**Gate:** escalation notifications/day **< 20** against the frozen baseline
**7,627 — one FULL day, 2026-09-21** — measured by the identical command before
and after:
```bash
grep -c '^<DATE>.*exhausted after' logs/claude_escalation.log
```

**Baseline corrected 2026-09-22. The figure previously frozen here, 1,673, was a
PARTIAL day.** It was taken mid-day on 09-21 while the storm was still
producing, and was then compared against a *per-day* target — part of one day
measured against all of another. Re-measured 2026-09-22 against the same
unrotated log (`persistent-state/logs/claude_escalation.log`, continuous since
2026-08-27, so each date below is complete unless marked otherwise):

| Date | `exhausted after` lines | Coverage |
|---|---|---|
| 2026-09-18 | 3,682 | full day |
| 2026-09-19 | 2,278 | full day |
| 2026-09-20 | 6,110 | full day |
| **2026-09-21** | **7,627** | **full day — THE BASELINE** |
| 2026-09-22 | 1,433 | partial, to 11:40 EDT — *not a daily rate* |

The correction makes this gate **harder, not easier**: clearing it now demands a
**99.74%** reduction (7,627 → <20) where the partial figure implied 98.8%. Any
future reading must cover a whole calendar day. A mid-day count is not a daily
rate, and must never again be frozen as one.

### Phase 2 — Provable delivery (Weeks 1-2) · delivery 5 → 9
**MERGED (#1179).** `attach_telegram_message_id()` added — additive, because
`send_telegram`'s bare-bool contract has ≥36 verified boolean callers (182 across
150 files by the code's own count). `send_telegram_with_id()` and
`last_message_id()` already existed.

Remaining: wire the 27 call sites; write `destination_policy_id` at the outbox
(0 of 52,929 today); pass `provider_message_id` to `settle_delivery` on the
legacy path, which currently cannot write `SETTLED` at all.

**Gate (restated 2026-09-22 — the original denominator was unreachable):**
≥95% of **DELIVERED** messages in the last 7 days carry a `provider_message_id`,
where DELIVERED means `status IN ('SENT','LEGACY_DELIVERED')`.
`destination_policy_id` non-null ≥95% **on that same DELIVERED denominator**.

#### Why the original wording could never pass

It read "≥95% of last-7-day **alerts**", which counts every row in
`communication_deliveries` — and **97.67% of those rows are `SUPPRESSED`**. The
router deliberately never hands a suppressed row to Telegram, so no provider can
ever return an id for it; `NULL` is the correct and honest value there, not a
defect. Even if every message that actually reached Telegram carried an id, the
all-rows denominator would top out at **2.1%** (942 / 45,236). The gate as
written was unpassable by any amount of correct work — it measured the router's
suppression policy, not delivery provenance.

Measured 2026-09-22, 7-day window:

```sql
SELECT status, count(*) AS rows,
       count(provider_message_id) AS with_id,
       round(100.0*count(provider_message_id)/count(*),1) AS pct
FROM communication_deliveries
WHERE reserved_at >= now() - interval '7 days'
GROUP BY status ORDER BY rows DESC;
```

```
 SUPPRESSED       | 44182 |  0 |   0.0
 LEGACY_DELIVERED |   885 |  0 |   0.0
 RESERVED         |   112 |  0 |   0.0
 SENT             |    57 | 55 |  96.5
```

```sql
SELECT count(*) AS delivered,
       count(provider_message_id) AS with_id,
       round(100.0*count(provider_message_id)/NULLIF(count(*),0),1) AS pct
FROM communication_deliveries
WHERE reserved_at >= now() - interval '7 days'
  AND status IN ('SENT','LEGACY_DELIVERED');
```

```
 942 | 55 | 5.8
```

So the restated gate stands at **5.8% against an unchanged 95% target** (55 of
942). Only the denominator is corrected. The honest denominator reports a
**worse** number than the 24-hour slice (13.8%, 19 of 138), because the legacy
path carried no id for most of the week — the 7-day window the gate names is the
one that governs.

`destination_policy_id` on the same DELIVERED denominator: **1.9%** (18 of 942).
Across all rows it is 0.4% (186 of 45,236).

#### The `SETTLED ≥95%` clause is withdrawn — `SETTLED` is not a legal status

`communication_deliveries_status_check` admits only RESERVED, SENDING, SENT,
DELIVERED, ACKNOWLEDGED, FAILED, BOUNCED, SUPPRESSED, EXPIRED, CANCELLED,
UNKNOWN, LEGACY_DELIVERED. `SELECT count(*) FROM communication_deliveries WHERE
status='SETTLED'` returns **0**, and always will — the constraint forbids the
value. A gate demanding ≥95% of a status the schema cannot hold is not a strict
gate, it is an unmeasurable one. The terminal success states are the two named
in the restated gate above.

### Phase 3 — Identity + stance at the chokepoint (Week 2) · identity 5 → 9
Tag `subject_guid` inside `publish_communication` — one function closes all 43
producers.

**[E1 — relocated]** Wire `check_investment_send()` into
`telegram_transport.deliver_text()`, beside `_interdicted()`:

- bullish stance (`BUY` / `Accumulate` / `GO`) against an active `AVOID`/`HOLD`
  → `held_reason=cio_stance_conflict`, **suppress**
- unknown or stale (>72h) stance → `held_reason=cio_stance_unknown`, demote to
  `COMMAND_CENTER_ONLY`
- 24/7, every asset class, every day — no weekday or equity-only carve-out
- non-investment traffic is a **no-op**; the gate must not block ordinary alerts

**Gate:** outbound `subject_guid` ≥95% (from 16.4%); inbound ≥90% (from 1 of
252); a synthetic BUY against an AVOID symbol is held, proven by receipt.

### Phase 4 — Close the memory join (Week 3) · memory 3 → 8
`correlation_id` and `thread_id` are already **100%** populated; only
`causation_id` and `parent_event_id` are zero. This is wiring two existing
columns.

- **[E2]** Write `AdjudicationReceipt@v1` **synchronously to PostgreSQL before
  the operator commit**, so replay reads the recorded decision instead of
  re-invoking an LLM judge (TOKI N1 replay inconsistency)
- **[E5]** Telegram Narrator briefings draw from `MemoryRetrievalUnit@v1`
  envelopes capped at **12k tokens**, not raw transcripts
- Carry `subject_guid` into agent consumption receipts (0 of 199 today)

**Gate:** every reply in a 7-day window resolves to its cause; GUID join ≥90%.

### Phase 5 — SLOs and self-observability (Weeks 3-4) · observability 3 → 8
`grep -rl "error_budget\|slo_target\|burn_rate" scripts/ config/` returns
**nothing**. There is no SLO for anything, which is why every alert is a
threshold alert on a cause rather than a symptom alert against a budget.

1. Define three error budgets: alert delivery, card freshness, quote freshness
2. Multiwindow, multi-burn-rate alerting (SRE Workbook)
3. A runbook link on every alert
4. Rotate `.jsonl` — `rotate_runtime_logs.sh` matches only `*.log`, so
   `safe_flock_events.jsonl` (86 MB) grows unbounded
5. Consolidate 128 monitors onto `lib/alert_condition_state` — first fixing its
   two known hazards: a corrupt state file re-alerts all 1,681 conditions then
   silently erases history, and the whole-file read-modify-write is unlocked

**Gate:** ≥3 SLOs with budgets; every alert has a runbook; no log >100 MB; every
scheduled monitor fired or has a passing negative control.

### Phase 6 — Gate honesty (continuous) · gates 5 → 8
- Alarm firing coverage **19.1% → 60%** (36 of 188)
- CI test files **67% → 85%** (971 of 1,446)
- Enforce `producer ≠ reviewer ≠ scorer` in `contracts.py` — producer ≠ reviewer
  is enforced; one agent may still both review and score
- **[E4]** Hermetic negative control: publish a synthetic `BUY` against a symbol
  with an active `AVOID`. **Fails red if emitted; passes green only when
  `held_reason=cio_stance_conflict` appears in the ledger, with no external
  HTTP.**

**Gate:** ratchet at 60%; no new `send_telegram` site merges without a firing
test **listed in the gate**, not merely declared in `COVERS`.

---

## 2. Why E4 is the load-bearing enhancement

Seven checks in this repo were found passing on the wrong dimension on 2026-09-21
alone — a dry run that skipped the crashing path, a test that passed against the
unpatched file, a test whose result depended on import order, a negative control
that skipped every assertion, a gate wrapper rewritten four times, a raw pattern
count nearly reported as 166 bugs when triage showed 1, and a guard whose exit
code made a successful run look failed.

Every gate added under this plan ships with a control proving it can fail. A
stance gate without one would be the eighth.

> **A check that passes on the wrong dimension is worse than no check.**

## 3. Not verified here

The review cites a Telegram layer audit at 32/100 and agent controls at 21/30.
Those come from its own sources; they are not reproduced here and are not
restated as measured facts.
