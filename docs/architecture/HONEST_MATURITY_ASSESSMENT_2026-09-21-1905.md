# Where this actually stands — 2026-09-21, 19:05 ET

Every number below is a query run in the last five minutes, not recalled. I got
three root causes wrong today by reasoning instead of measuring, so nothing here
is asserted from memory.

---

# THE SCORE: **4 / 10**

Not 6, not 7. Here is the arithmetic rather than a feeling.

| dimension | score | why |
|---|---:|---|
| Capital-protection correctness | **7** | the trailing-stop feedback loop is fixed and live; stop alerts resolve cleanly |
| Alert delivery (does it arrive) | **5** | plane B records again, proven live; plane A still links 62 of 7,975 |
| Alert *signal* (is it worth reading) | **3** | 403 storm events in 2h, all suppressed, none acknowledged |
| Identity / GUIDs | **4** | one class fixed and proven; 43,621 outbound events still unlabelled |
| Memory / joinability | **2** | 0 of 199 agent receipts carry a guid; 0 of 52,563 events carry reply lineage |
| Observability of its own failures | **3** | the job that produced 174 tracebacks logged them to a 100 MB file nobody reads |
| Test / gate honesty | **5** | 3 orphans registered today; 971 files remain in the unlisted baseline |
| Deploy discipline | **8** | prepare/promote is strict, verifiable, and refused bad input twice today |

**4/10 means:** the machinery mostly exists and is mostly not wired. Today moved
four specific things from broken to working and proved two of them in
production. It did not change the shape of the system.

The recurring shape, seen four separate times today:

> **A check that passes on the wrong dimension is worse than no check.**

- a CI gate green over a 0% production condition (it tested the pure function, never the write)
- a dry run previewing a *truncated* body while `--apply` used the full one
- a PR monitor reporting "settled" while four checks were still running
- my own guard-scope check that validated row *count* and never row *content*

---

# 1. WHAT CHANGED TODAY — in dependency order

| # | PR | what it fixes | state |
|---|---|---|---|
| 1 | #1166 | classifier matched `orphan` as a bare substring, routing research health to CRITICAL | merged, live |
| 2 | #1167 | `load_prior_state` only looked at `status='open'` → PK collision dropped writes | merged, live, **proven 15:27** |
| 3 | #1168 | two rotted stubs in the alert-blockers suite | merged, live |
| 4 | #1171 | trailing stop computed R from the stop it was moving | merged, live |
| 5 | #1172 | `ENTRY_NEAR` pages only for starred symbols | merged, live |
| 6 | #1173 | three orphaned alert tests now actually run in CI | merged, live |
| 7 | #1169 | entry card names the company, sector, industry | merged, live |
| 8 | #1174 | template boilerplate must not bind an issuer | merged, live, **proven 17:46** |
| 9 | #1170 | `Decimal` kills the strategy-card job | **BLOCKED, 4/5 checks, auto-merge armed** |

Data repairs applied, both reversible:

- **44,987** false identity links archived to `narrative_subjects_quarantine_20260921` and removed
- **37,054** events' fabricated `subject_guid` cleared (bodies untouched)
- **425** correct links backfilled across 154 events (278 correctly resolved to *no* subject)

---

# 2. WHAT WORKS — verified in production, not inferred

**The incident-collision fix.** `a71e498cc5b2106a399d` went `occurrence_count 1 → 2`,
`last_seen 2026-09-16 → 2026-09-21 15:27:37`, and the 14:27 signature
(`duplicate key … alert_incidents_pkey` + `shadow persist skipped`) is absent.

**The identity fix.** The storm fired 13 events at 17:46:12 — *after* the 17:44:56
promote — and wrote **zero** new `AFTER` links. Before that, every cycle wrote ~11.
This is the one proof silence could not have given.

**The trailing-stop guard.** R is now derived from `planned_stop` before the tier
gate, so the gate and the arithmetic share one basis. Proven RED on pristine main
(`r_multiple=2.23, expected ~0.22`), GREEN here.

**Deploy discipline.** `prepare`/`promote` refused to run twice on preconditions
and reported `PASS promote: health ok + /v3/cio=200` each time it did.

**Alert-fatigue auto-downgrade** — `paper_trade_monitor` was moved ALERT→INFO after
4 consecutive days, unprompted. One control that genuinely works.

---

# 3. WHAT DOES NOT WORK — measured tonight

### 3.1 The alert storm is still running
```
403 events in the last 2 hours       newest 19:01:14
```
`claude_escalation_handler.py:725`, cron `*/10`, `MAX_RETRIES=4`, 30-minute re-arm.
`_notify()` calls `send_telegram` **directly** — no dedupe, no cooldown, and zero
`notification_log` rows mention it, so alert-fatigue cannot see it.

Its premise is **false right now**: `pipeline_freshness_monitor.check()` returns
`stale=1, missing=0, ok=9`. The `missing` branch fires because `_age_days_table`
returns `None` for *both* "table absent" and "query raised", and line 94 renders
both as *"no output / table/file absent"*.

### 3.2 Identity is repaired for one class, not in general
```
outbound events still missing subject_guid (30d) : 43,621
INBOUND events with a subject_guid (60d)         : 1 of 252
tripwire residue from other templates            : 9,909 links
```
The quarantine keyed on `AUTO-RETRY` bodies only. The tripwire I installed is
doing its job and reporting ~9,909 links from *other* templates — `ET` 3330,
`QUOTE` 2338, `LIVE` 1413, `ALERT` 1230. Those words now re-resolve to `[]`, so
the set is **historical and not accruing**.

### 3.3 Nothing joins to memory
```
agent consumption receipts carrying a subject_guid : 0 of 199
reply lineage (reply_to_event_id)                  : 0 of 52,563
inbound_operator_questions                         : 5 rows, last 2026-09-06
```
`AGENTS.md:835` requires tagging to be two-way. The inbound tagger exists, has a
DB-touching test, is in CI — and has written nothing since the day it was built.

### 3.4 Channel routing is unanswerable
```
destination_policy_id populated : 0 of 52,562
```
The column exists to record which policy chose the channel. It is referenced in
exactly one file and never written. The system cannot answer your original
question — *"are the right channels used"* — from its own data.

### 3.5 Delivery is still not linked to alerts
```
alert_events with a telegram_message_id (60d) : 62 of 7,975   (0.8%)
alert_incidents : 58 open, 0 resolved, 0 expired
```

### 3.6 Strategy cards are frozen, not empty
```
5,807 of 5,808 cards older than six days; exactly one current (GXO, 17:51)
174 Decimal tracebacks; log at 100 MB
```
I called this "zero cards for six days" repeatedly. Wrong: it is **frozen with a
trickle**. `conn.commit()` sits after the loop, so each run persists whatever it
wrote before the throw — one card, then the crash.

---

# 4. WHAT NEEDS FIXING — ordered by damage per unit of work

| # | fix | why it is first | effort |
|---|---|---|---|
| 1 | **Silence the escalation storm** | 403 events/2h, 82.6% of all suppressed deliveries, corrupted the spine for ten days | small — dedupe + fatigue registration at one call site |
| 2 | **Disambiguate `_age_days_table`'s `None`** | "table absent" and "query failed" are indistinguishable; that is what makes the storm's premise false | tiny — 3 lines |
| 3 | **Deploy + verify #1170** | six days of frozen cards; fix is written and reviewed | waiting on CI, then tomorrow 06:00 |
| 4 | **Tag at `publish_communication`, not the legacy chokepoint** | 43 producers publish directly; exactly 1 tags. This is why 43,621 events are unlabelled | medium — one function, closes all 43 |
| 5 | **Give the outbound identity test a DB** | it asserts the pure extractor and never the write; that is why CI was green over a 0% condition | small |
| 6 | **Second quarantine pass** for the 9,909 residual links | historical, not accruing — genuinely lower priority | small, but *measure first* (see §5) |
| 7 | **Populate `reply_to_event_id` / `causation_id`** | no reply can be traced to what it answers | medium |
| 8 | **Write `destination_policy_id`** | makes the channel question answerable at all | small |
| 9 | **Carry `subject_guid` into consumption receipts** | otherwise memory stays unjoinable even where identity exists | small |
| 10 | **Cap `stop_confirmation_reminder`** | SPCX listed twice in one message, at reminder **#69** | small |

---

# 5. WHERE I WAS WRONG TODAY

Recorded because the pattern matters more than the individual errors.

**Three wrong root causes before measuring.** I blamed ALL-CAPS banner text, then
`AUTO`/`RETRY`, then a stopword gap — each disproved by finally running the real
message body through the real resolver. The answer was the word "After" in the
alert's own closing sentence.

**A fix that closed the cases, not the class.** Pass 1 added a wordlist and made
every example I had tested pass. `RSI` and `AI` were *already* in `_STOPWORDS`;
that list simply was never consulted on the alias path. Caught only because I
fixed a bug in my own dry run.

**I claimed "no regression" after running one of a gate's two files.** Local
acceptance caught the break I had introduced.

**I nearly deleted identity for tracked instruments.** After the backfill I built
a 24-symbol "bad list" and scoped a 62-link removal for `ABOVE`, `ODD`, `EVERY`,
`AGAIN`, `FIX`, `ROOT`, `NEWS`. **All are in `watchlist_items` and
`ticker_snapshot_daily`.** `ABOVE` has its own Command Center link; `FIX` had 431
pre-existing links. Stopped by querying before deleting — not by the reasoning
that led there. Nothing was removed.

**Count errors:** "zero cards for six days" (it is 5,807 stale + 1 current);
"~5,500 storm alerts/day" (403 in 2h ≈ 4,800/day); "four digest-bound evidence
files" was right but unverified when I said it.

---

# 6. THE HONEST SUMMARY

**What you asked, and what you got:**

| your question | answer |
|---|---|
| *"Why do I care if I don't own?"* | the trailing stop wrote phantom stops above market; 62 trades mis-booked, 47 as wins. **Fixed, live.** |
| *"Missing what stock, sector, industry"* | **TLS = Telos Corporation, Technology / Software - Infrastructure.** Data was in `symbol_profiles` all along. **Fixed, live.** |
| *"Only alert when time to purchase"* | `ENTRY_NEAR` pages only for your 12 starred names. **Fixed, live** — real proof tomorrow 09:00, since the cron is `*/30 9-16 * * 1-5`. |
| *"GUIDs for everything, validate, backfill"* | one alert was 57.4% of the spine. **Repaired and proven** — but 43,621 outbound events and all inbound remain unlabelled. |

**Why 4 and not higher:** the four fixes that landed are real and two are proven
in production. But the system's defining trait is unchanged — capability built,
wiring absent, and no measurement of the difference. The inbound tagger, the
`destination_policy_id` column, `reply_to_event_id`, the consumption receipts,
`alert_notification_deliveries` — all present, all empty.

**Why not lower:** the deploy path is genuinely strict, the negative-control
discipline in this repo is real (it caught my own regression), and the tripwire I
installed is already doing its job by reporting residue I would otherwise have
called clean.
