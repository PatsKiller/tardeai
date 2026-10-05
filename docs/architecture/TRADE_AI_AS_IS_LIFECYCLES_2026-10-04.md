# Trade AI Platform — AS-IS Lifecycles, 2026-10-04 (re-measurement)

```
Status:      ACTIVE
as_of:       2026-10-04T23:30:00-04:00
Measured at: 4f932b88a (main = dev tree = CURRENT release 4f932b88a-main-exact-phase2-20261004-202102)
Supersedes:  TRADE_AI_AS_IS_LIFECYCLES_2026-09-14.md (kept; this document re-measures it)
Method:      seven read-only measurement passes, one per lifecycle family, each writing a fact base
             (docs/architecture/lifecycles/LIFECYCLE_FACTBASE_<FAMILY>_2026-10-04.md), then this synthesis.
             No writes, no broker calls, SELECT-only database reads, GET-only API reads.
Labels:      MEASURED (command, SQL or file:line in the fact base) · DOCUMENTED · INFERRED
```

## How to read this document

This is the summary layer. Every number below comes from one of the seven fact bases, which hold
the per-lifecycle anatomy (purpose · state machine · flow · iterations · questions · measurements ·
failure paths · per-stage maturity · target) and the evidence for each claim. Where this document
and a fact base disagree, the fact base wins.

Maturity uses the 09-14 scale: **L0** absent or broken · **L1** exists, unmeasured · **L2** measured ·
**L3** closed loop with a counter · **L4** loop proven to change behaviour · **L5** self-improving.
Family scores are the mean of per-stage levels, with L0 stages counted. The 09-14 baseline published
qualitative levels only, so the "09-14" column is reconstructed from its stage tables.

---

## 1. Executive summary

**The platform moved from about 1.3 to about 1.8 out of 5 in three weeks.** The gains are mostly
"the pipe now runs": research jobs complete, watchlist jobs complete, messages are deduplicated and
settled, approvals close over Telegram, releases are smaller and gated. **No lifecycle reaches L4.**
Nothing yet proves that an outcome changed a later decision.

| Family | 09-14 | 10-04 | Biggest change | Biggest open break |
|---|---|---|---|---|
| A · Data and sources | ~1.8 | **~1.9** | plausibility timer daily; CUSIP identities 5,014 → 5,292; event bus re-chained | no price quarantine; Finviz down ~74 h; Schwab book misses every other session |
| B · Questions and research | ~1.0 | **~1.7** | Hermes queue 78 % failing → 92 % completing; pending replies close | research verdicts change nothing; topic ingestion silently dead since 09-28 |
| C · Watchlist, proposals, learning | ~1.0 | **~1.4** | agent jobs 2.9 % → 95.1 % complete | approval without review (55/55); approval thrash 266 → 2,107 flips; ticket queue stalled since 09-30 |
| D · Cognition (CIO, agents, memory) | ~0.9 | **~1.5** | judgments vary, critic disagrees, checkpoints resolve; 12 % cap ratified | 0 commitments scored; one 09-11 ADBE turn drives a third of wakes; lineage ≤ 4/21 LIVE |
| E · Communications | ~1.3 | **~2.0** | comms editor live (452 duplicates blocked); guard approvals close in ~8 s | noise flood (9,245 rows/week, 92 % suppressed); 40 % wrong subject tags; outbox fake confirmations |
| F · Engineering and operations | ~2.0 | **~2.3** | 408 PRs merged; release grant binding; dev tree auto fast-forward; releases 108 G → 1.2 G | main CI red since 10-04 10:57Z and promote does not check it; 65 unexplained API exits |
| G · Trading desks and Active Trader (new) | — | **~1.9** | Phase 1 L2 alerts built and live-configured; moomoo L2 proven 60 levels | ignition engine dark 09-17 → 10-04; Schwab token hard expiry 10-05 12:06 ET; protection alarms muted |
| **Platform (mean of families)** | **~1.3** | **~1.8** | | |

### The ten facts that matter most today

1. **Main is red and red code shipped.** Every 10-04 promote went live on a commit whose post-merge
   CI failed (`alarm_fires`: the two new Telegram alert senders had no firing test). Fix and a PR-run
   trigger: PR #1435. Promote still does not read post-merge CI. (F)
2. **The Schwab token hard-expires Monday 2026-10-05 12:06 ET.** Without an operator re-login, quotes,
   protective stops and orders on Schwab fail. (G)
3. **The momentum-scalp ignition engine wrote nothing from 09-18 to 10-04** (150 of 150 runs crashed on
   a schema lock). Fixed in #1424; Monday 10-05 is the first live proof. (G)
4. **Active Trader Phase 1 alerts are configured to send to Telegram from Monday's open**, but have never
   run on a live session: no journal or heartbeat exists yet. (G)
5. **Research does not change decisions.** 14 thesis-challenging Hermes verdicts in 7 days produced 0
   material changes and 0 notifications. (B)
6. **The learning loop closes on nothing.** 883 commitments swept, 0 scored, 0 lessons promoted; 10,217
   checkpoints can never come due; outcome verdicts are 96 % NEUTRAL. (C, D)
7. **Approval is effectively unreviewed.** All 55 proposals approved in 30 days still have an open agent
   review, and an unattributed writer flips proposals between approved and pending (2,107 times). (C)
8. **Outbound messaging is mostly noise.** One "Health Inspector [DEGRADED]" body is 56 % of 9,245
   outbound rows a week; 40 % of tagged messages carry a non-company subject tag. (E)
9. **The API process exits without a cause** 65 times since 09-28, at a ~1.5–1.7 G memory peak against
   a 1.5 G soft limit; swap is full. (F)
10. **Several controls are documented but muted:** "Protected: NO" logged 397 times with sending off;
    the lane-registry alert is suppressed; 108 open incidents with none acknowledged. (G, F)

---

## 2. What changed since 2026-09-14

### 2.1 Delivered (measured working)

| Area | 09-14 | 10-04 | Family |
|---|---|---|---|
| Hermes CIO research queue | 79 % of 7-day jobs failed | 182/197 completed (92.4 %), median 11.2 min | B |
| Operator pending replies | not joined to research; subject lost | 7 of 8 fulfilled from Hermes since 09-14; subject kept | B |
| Watchlist agent jobs | 2.9 % complete; global cost cap starved the lane | 95.1 % complete, median 0.26 h; 0 cost-cap refusals in a week | C |
| CIO judgments | identical; critic accepted 11/11 | 95 distinct judgments in 113 views; critic said revise 9 times | D |
| Checkpoints | 163 resolved | 477 resolved; new checkpoints get a 30-day due date | D |
| Capital plan policy | thesis fallback | 12 % single-name cap ratified by the operator 10-04, sourced "ratified" | D |
| CIO event bus | (fork unknown) | fork at line 2447 found and re-chained 10-05 00:22Z; archive + sha256; gate A.1 49/49 | A, D |
| Comms editor | shadow | live; 822 sent, 452 duplicates blocked, 102 held in 7 days | E |
| Message settlement | suppressed rows never settled | settle since 09-30; 70 % of delivered rows carry a Telegram id | E |
| Guard approvals | absent | 132 approved by Telegram button in 7 days, median 8 s | E, F |
| Releases | 56 dirs, 108 G; manual dev-tree catch-up | 9 dirs, 1.2 G; promote fast-forwards the dev tree (142 times) | F |
| Release authority | none | release-write grant must name the PR or SHA; refuses otherwise | F |
| Health score | 70, 11 critical | 82, 2 critical | F |
| Momentum-scalp lane | paper submit from the 9–4 generator | 06:00–11:50 advisory lane; paper submit off (10-04, operator) | C, G |
| Active Trader | read-only Stage 0 | Phase 1 L2-confirmed alerts, Alerts tab, send mode (10-04) | G |
| Lesson queue | — | 633 boilerplate lessons archived (10-04, operator) | C |

### 2.2 New breaks found by this re-measurement

| Break | Evidence summary | Family |
|---|---|---|
| Topic ingestion skipped since 09-28 | gate calls a Python path that does not exist in the release, prints "skipping job", exits 0 | B |
| Watch decision ticket queue stalled since 09-30 | 706 queued, 0 complete, 4 RUNNING orphans | C |
| Proposal approve – pending thrash | 266 → 2,107 flips in 30 days; no actor recorded | C |
| CIO outbox fake confirmations | 1,694 CONFIRMED with message id "None"; 1,204 orphans | E |
| Schwab book stream lock collision | ~24 h runs lock out the next 09:31 start; every other session lost | A |
| Main CI red, red promotes | 11 consecutive failures; promote does not check | F |
| Live pilot arm | `pilot_armed_until=2099-12-31`, `BROKER_LIVE_ENABLED=true`; per-order 2FA is the only Schwab control | G |
| Motion service | runs a pinned 07-29 deployment; 355 restarts; no lease can be admitted | G |

---

## 3. The platform lifecycle, end to end (as measured)

```
 sources ──► data point ──► identity ──► material change ──► question / research
   (A)          (A)            (A)            (A)                   (B)
                                                                     │
   watchlist item ◄──────────────────────────────────────────────────┘
        (C) ──► proposal ──► review ──► approval (operator) ──► [execution: operator, 2FA]
                  (C)          (C)           (C)                         (G)
        │                                                                │
        ▼                                                                ▼
   CIO wake ──► judgment ──► commitment ──► checkpoint ──► outcome ──► lesson ──► (behaviour)
     (D)          (D)            (D)            (C/D)         (C/D)      (C/D)        ✗ never
        │
        ▼
   message ──► comms editor ──► Telegram / email ──► operator reply ──► (wake)
     (E)           (E)               (E)                  (E)             ✗ rarely

   momentum scanner ──► ignition engine ──► moomoo L2 + tape ──► ARMED / TRIGGERED alert (G)
                         ✗ dark 09-17→10-04                      first live run 10-05
```

The pipe runs further than on 09-14 at every stage up to "judgment". The loop still breaks at the
same three places: **outcome → lesson → behaviour**, **research → decision**, and **operator reply →
cognition**.

---

## 4. Lifecycle index

| ID | Lifecycle | Fact base | 10-04 maturity |
|---|---|---|---|
| A1 | Market / reference data point | A | L1–L2 |
| A2 | Data source (provider) and data plane | A | L1–L2 |
| A3 | Identity (mention → subject_guid) | A | L2 |
| A4 | Material change | A | L1–L2 |
| B1 | Operator question | B | 2.4 |
| B2 | System-raised questions | B | 1.7 |
| B3 | Hermes research | B | 2.3 |
| B4 | Topic research | B | 0.5 |
| C1 | Watchlist item | C | 1.5 |
| C2 | Proposal (to the approval boundary) | C | 0.8 |
| C3 | Review and learning | C | 1.2 |
| C4 | Agent-job budget admission | C | 2.0 |
| D1 | Hourly persistent wake | D | 1.9 |
| D2 | Commitment → checkpoint → outcome → lesson | D | 1.1 |
| D3 | Reflection and agent runtimes | D | 1.1 |
| D4 | CIO run (reactive cycle, wake jobs, situations, event bus) | D | 1.7 |
| D5 | Epoch (promote → wakes → acceptance) | D | 1.0 |
| D6 | Decision lineage and operator evidence (new) | D | 1.7 |
| D7 | Capital-plan policy (new) | D | 1.8 |
| E1 | Outbound message | E | L2 |
| E2 | Inbound operator reply | E | L1–L2 |
| E3 | Platform-monitor alert | E | L2 |
| E4 | Email and Drive publication | E | L1–L2 |
| F1 | Change (request → deploy → record) | F | see fact base |
| F2 | LLM call | F | not re-measured (unchanged 09-14) |
| F3 | Scheduled lane and service | F | see fact base |
| F4 | Finding / incident | F | see fact base |
| F5 | Secrets, backup and host | F | L0 for restore drill and rotation |
| G1 | Momentum-scalp discovery → ignition engine | G | dark until 10-05 |
| G2 | Active Trader Phase 1 alerts | G | built, not yet run live |
| G3 | Motion / T2 leases / momentum exit | G | shadow; no lease ever admitted |
| G4 | Strategy review gate | G | 3/30 exact trades |
| G5 | Options desk | G | contract built; 0 fills; live not authorized |
| G6 | Live execution gates | G | strong refusals; standing pilot arm |
| G7 | Stops and protection | G | alarms muted |

---

## 5. Family A — data and sources (≈1.9 / 5)

**What works.** The plausibility timer runs daily (8 of 12 checks blocking); the Yahoo cross-check and
end-of-day close correction run; confirmed identities grew 5,014 → 5,292; the material-change feed
lives in persistent state; the event bus chain verifies (13,394 records, 0 link breaks).

**What does not.**
- Corrupt closes from 09-04/09-11 were overwritten with plausible values, not quarantined; the
  quarantine table's last entry is 08-27. 123 day-over-day jumps above 50 % came from quote-sourced
  closes since 09-15, and some Finviz rows dated Sunday 10-04 were written today.
- Finviz has returned 0 rows since 10-02 06:25 (cookie); the movers job prints "10/10 signals" on
  empty runs. Alpha Vantage last succeeded 09-21 (pacing fix in 4f932b88a; first run 10-05 08:00).
  YouTube flaps on HTTP 429 and its cookie alert is suppressed to the digest.
- The Schwab NASDAQ_BOOK stream misses every other regular session (lock collision). moomoo L2 is
  used for alerts but its registry row still says `service_down`, scope "positions"; neither order
  book is a declared data domain.
- The gap resolver ran 8,339 times and answered 4; 91 % of runs were refused for budget.
- Four retired provider keys are still rendered into the runtime environment.

## 6. Family B — questions and research (≈1.7 / 5)

**What works.** Hermes completes 92 % of jobs; operator questions close on their research with the
subject kept; free-search fallback answered every Brave-capped request through SearXNG; plan expiry
fires (643 in 7 days).

**What does not.**
- Research verdicts never mark a plan material or notify; provenance says "used" on 97 of 129 items
  but carries no decision id.
- Topic ingestion has been silently skipped since 09-28 (gate interpreter path); the same gate wraps
  other research jobs.
- 20 high-priority Hermes jobs from 08-31 → 09-12 are stuck outside every restore and health window.
- No question store reaches a terminal state: due-diligence questions 0 of 2,341 closed; 118 research
  gaps never attempted; research objects 2.7 % consumed; promoted research never expires.
- Target selection is still alphabetical; Maria's reply text is not recorded.

## 7. Family C — watchlist, proposals and learning (≈1.4 / 5)

**What works.** Agent jobs complete 95 % with no budget refusals; the auto-queue no longer bans a
symbol forever after one identity rejection; the lesson digest and calibration API are honest about
an empty signal.

**What does not.**
- 9,392 proposal reviews pending; 55 of 55 approvals in 30 days still have an open review.
- Approve – pending thrash: 2,107 flips in 30 days, up to 149 on one proposal, writer unrecorded.
- Watch decision tickets stalled since 09-30 (706 queued, 4 orphaned RUNNING).
- 10,217 checkpoints have no due date; outcomes are 96 % NEUTRAL; one agent is calibrated.
- The strategy review gate cannot move the strategies with evidence (momentum_scalp 3/30;
  pullback_macd_reversal 0 signals despite 109 paper trades).
- The incubator → proposal lane is still dead in the ledger.

## 8. Family D — cognition: CIO, agents, memory (≈1.5 / 5)

**What works.** Wakes run (2 missed slots since 09-14); judgments and falsifiers vary and the critic
writes questions back; checkpoints resolve; agent runtimes complete jobs in shadow (1,206 in 24 h);
the ratified policy drives capital-plan sizing; LLM spend stays under the $2/day cap.

**What does not.**
- The commitment sweep scores nothing: 883 swept, 883 unfalsifiable; minting now refuses boilerplate,
  so almost nothing new is minted.
- One 09-11 ADBE operator turn is replayed on 25 of 75 wakes a day.
- Decision lineage: at most 4 of 21 stages LIVE on probed decisions.
- Memory influence is zero; attribution covers 49 of 32,071 retrievals.
- Registries disagree with the runtime (3 agents ACTIVE vs DESIGNED; 2 lanes); wake-job over-enqueue
  (5,414 superseded; 193 streams older than 4 h).

## 9. Family E — communications (≈2.0 / 5)

**What works.** The comms editor is the live outbound gate (dedupe, CIO-stance holds, receipts);
settlement and Telegram ids are recorded; guard approvals are the first closed loop (button → grant
in ~8 s); platform alerts resolve and remind on a schedule; the CIO bot and poller run CURRENT.

**What does not.**
- 9,245 outbound rows a week, 92 % suppressed; one health body is 5,216 of them.
- 40 % of tagged editor decisions carry a non-company tag (fixes for ET/API/Monday shipped 10-04;
  PRICE, ALERT, OI, NONE, OFF, LIVE remain).
- The CIO outbox recorded 1,694 confirmations without a real message id; 1,204 orphans.
- Operator replies rarely reach cognition: 0 of 501 intake receipts linked to a wake; desk replies are
  not in the communication ledger.
- The Google token refresh has failed since ~09-20 (operator re-login needed).
- Active Trader alerts: the missing-CIO exemption is deployed but not yet exercised; the 10-04 test
  alert took the CIO-disagreement path (SOUN = RESEARCH_MORE → WATCH), as designed.

## 10. Family F — engineering and operations (≈2.3 / 5)

**What works.** 408 PRs merged since 09-14; two required checks enforced on admins; release-grant
binding; promote re-binds four services and reads their working directory back; cron runs from
CURRENT; lane registry 162 declared and 0 undeclared new lines; AGENTS.md 1.3.0 active; 16
pre-existing test failures fixed on 10-04.

**What does not.**
- Post-merge CI on main red for 11 runs; promote ignores it (PR #1435 fixes the cause and makes PR
  runs select the alarm gates; gating promote remains open).
- 65 unexplained API exits since 09-28; no exit cause logged; restart counter resets each promote.
- The ops agent and motion service run code from outside the release; 7 repo units never installed.
- No restore drill and no secret rotation (L0); the repo is public with keys in history.
- 108 open incidents, none acknowledged; remediation success 1.5 %; lane alert suppressed.
- Worktrees grew 454 → 793; the deploy receipt is a single overwritten file.

## 11. Family G — trading desks and Active Trader (≈1.9 / 5, new)

**What works.** Refusals are strong: live session coerced off, Alpaca live raises, moomoo order paths
refuse, per-order 2FA on Schwab, MBI_BEHAVIOR = 0. moomoo Level 2 is proven at 60 levels through the
OpenD quote context. Phase 1 alerts (ARMED / TRIGGERED, fail-closed, journaled, scored at 1/5/15 min)
are built, tested (35 + 13 + firing tests) and set to send from 10-05.

**What does not.**
- The ignition engine was dark 09-17 → 10-04; `scalp_decision_outcomes` has 0 rows.
- No live alert session yet; no journal or heartbeat exists.
- Motion service pinned to a 07-29 build, 355 restarts, 0 leases (a lease needs an ACTIVE session,
  which is hard-off).
- momentum_scalp is 3/30 toward its gate; 83 real family-scalp trades do not count. Thresholds
  disagree (profit factor 1.25 vs 1.3; live gate 30 vs 100 trades).
- Options: authorization contract built; 0 fills, 0 journal events; 2,808 blocked approvals; live
  options not authorized.
- Standing live arm (`pilot_armed_until=2099-12-31`, canary and protective gates removed).
- "Protected: NO" logged 397 times with sending disabled; weekend supervisor runs of unknown origin.
- Schwab token hard expiry 2026-10-05 12:06 ET.

**Phase 2 / 3 gating facts (unchanged policy).** Automated entry needs a signed session envelope (not
built), live session activation (hard-off), a running engine and a scored alert record (both zero),
the momentum_scalp gate (3/30), and live trading allowed by governance. Schwab automation also needs
the interlock on the order path and a non-expiring token.

---

## 12. Cross-lifecycle analysis

### X1 · Feedback edges

The loops that now close are mechanical: job completion, duplicate suppression, settlement, approval
by button, checkpoint resolution, critic write-back. The loops that would make the platform learn
still do not close:

| Edge | 09-14 | 10-04 |
|---|---|---|
| outcome → lesson → behaviour | none | none (0 scored; 0 promoted; lessons archived) |
| research verdict → plan / decision | none | none (0 material of 180) |
| operator reply → wake | partial | none since 09-25 for genuine text |
| alert precision → alert rules | — | built (scoring ledger), no data yet |
| incident → owner → resolution | none | resolves on recovery; 0 acknowledged |

### X2 · Where lifecycles should meet and do not

- Research provenance – decisions (no decision ids on provenance).
- Capital-plan decisions – checkpoints (no join at mint time).
- Communication events – desk replies (desk replies unledgered).
- Data-source registry – real data planes (order books undeclared; moomoo row stale).
- Post-merge CI – promote (not read).

### X3 · Risks (ranked)

1. Schwab token expiry 10-05 12:06 ET (stops and orders fail).
2. Red main ships; API exits without cause.
3. Approval without review plus unattributed approval thrash.
4. Learning signal empty but presented as metrics (96 % NEUTRAL; "settled 427").
5. Muted protection and lane alarms; noise flood hides real alerts.
6. Prices without a quarantine contract feed stops and technicals.
7. Standing live arm with a single control.

### X4 · Recommendations (ranked)

1. **Before 12:06 ET Monday:** re-authenticate Schwab (operator).
2. **Monday 09:35 ET:** verify ignition rows, the alert heartbeat and 0 tracebacks; then the 08:00 Alpha
   Vantage run and the 10:05 Fidelity stop sync.
3. Merge PR #1435; then make promote refuse a SHA whose post-merge CI is not green.
4. Make approval require a closed review; add an actor to proposal status events; cap thrash.
5. Price plausibility contract wired to an automatic quarantine; refuse weekend-dated writes.
6. Send health alerts on state change only; accept a subject tag only when the text marks it.
7. Give every checkpoint and question store a due date or terminal state.
8. Feed research verdicts into materiality; stamp decision ids on provenance.
9. Log the API's exit cause; decide memory limit vs peak reduction.
10. Bring the motion service and ops agent under promote.

### X5 · Operator decisions required

| Decision | Why it is yours |
|---|---|
| Re-login Schwab (10-05 before 12:06 ET); renew the Finviz cookie; `gcloud auth login` | credentials |
| Keep or end `pilot_armed_until=2099-12-31` | live-trading gate (§17) |
| Extend the comms-editor exemption to scalp advisory alerts (an "A+" grade advisory with no CIO decision is held) | communication policy |
| How momentum_scalp can reach its validation gate with advisory-only delivery | strategy governance |
| Reconcile the thresholds (PF 1.25 vs 1.3; live gate 30 vs 100) | policy |
| Retire the 4 provider keys from the secret store; schedule a restore drill and rotation | operator-only (§17) |
| Turn on paging for sustained "Protected: NO" | protection policy |

---

## 13. Corrections to the 09-14 As-Is

- The 09-14 document did not know the CIO event bus had already forked (08-26, line 2447). It has
  since been re-chained without loss (archive retained).
- Family scores here are reconstructed for 09-14; the 09-14 document published qualitative levels.
- Lifecycle family G (trading desks, Active Trader) is new; 09-14 covered execution only as a
  boundary.

## 14. The one-sentence version

The platform now reliably runs its pipes — research, jobs, messages, approvals, releases — but it
still does not learn from outcomes, act on research, or hear the operator, and three controls
(post-merge CI, protection alarms, the Schwab token) need attention before Monday's session.
