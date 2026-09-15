# Trade AI — Work Log: everything changed from 2026-09-13 20:00 to 2026-09-14 23:44

```
Status:        ACTIVE
Updated:       2026-09-14 23:44 EDT
Covers:        2026-09-13 20:00 EDT (PR #997 merge) → 2026-09-14 23:44 EDT
Live at:       341bce2c1 (PR #1025) — origin/main = release CURRENT = dev tree; dev tree git status empty
Author:        Claude Code session af450ed8 (operator John), from PR bodies, deploy receipts, crontab backups,
               memory notes and live read-only checks. Every time is America/New_York unless marked Z.
Authority:     READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Broker execution subsystem untouched.
Companions:    TRADE_AI_AS_IS_2026-09-14.md · TRADE_AI_FUTURE_STATE_2026-09-14.md ·
               TRADE_AI_AS_IS_LIFECYCLES_2026-09-14.md · TRADE_AI_FUTURE_STATE_LIFECYCLES_2026-09-14.md ·
               RESEARCH_ESCALATION_2026-09-14.md · lifecycles/LIFECYCLE_FACTBASE_{A..F}_2026-09-14.md
```

This log is the record of one working day on the platform. It lists every merged change with its
merge time and live commit, the incident or operator request behind it, the evidence it shipped
with, the host changes made outside git, the operator decisions taken, and what is still open.
The As-Is and Future-State documents were updated from it; where they differ, this log records
what changed and they record the resulting state.

---

## 1. Summary

| Measure | Value |
|---|---|
| Pull requests merged and deployed | **29** (#997–#1025), all live |
| Releases promoted on 2026-09-14 | **22** (`c594d8600` 00:07 → `341bce2c1` 23:06) |
| Live commit at close | `341bce2c1` — main = release = dev tree; `git status` empty |
| Governance | `AGENTS.md` Policy-Version **1.2.0 ACTIVE**, Effective-Date 2026-09-14 (operator approval, PR #1024) |
| Global LLM spend cap | **$2.00/day of actual spend** (was $0.50 nominal, $7.00 forgotten override, $1.50 on the server) |
| Scheduled paid work | inside the operator window: weekdays 09:00–21:00 ET or weekends, never at DeepSeek billing peak |
| New timers / cron lanes | source litmus, Finviz view contracts, EOD consolidated close, screener GO alerts, bridge watchdog, DeepSeek balance snapshot, spend texts (daily/weekly/monthly), morning brief 07:30 |
| Lane registry | 107 declared lanes (73 ACTIVE), 0 undeclared, clean |
| Incidents found and fixed | dictated ticker; research not delivered; unlabelled pills; corrupt prices and units; duplicate briefs and lost GO alerts; alert ledger collisions; research queue 62 % failing; long replies refused; model bridge wedged; phantom spend and caps; shared spend label; dirty git; deploy that did not reach the dev tree; a date-dependent test; expired Google token |
| Open verification | label split on real traffic (09-15 10:03 ET check), 09:05 holdings run, 07:05 spend text, Communications Editor shadow → live review, research circle phases 2–4 |

```dot-wide
digraph timeline {
  graph [rankdir=TB, fontname="Helvetica", fontsize=12, label="2026-09-14 — the day in merges (ET)", labelloc=t, nodesep=0.2, ranksep=0.3, pad=0.3, newrank=true];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9, color="#2B5797", fillcolor="#EAF1FB"];
  edge [color="#8497B0", arrowsize=0.6];
  subgraph cluster_night { label="Night 13th→14th"; style="rounded,filled"; fillcolor="#F4F6F9"; color="#C9D3DF";
    n997 [label="20:14 #997\nhealth alert copy"]; n998 [label="21:52 #998\nCC-first routing,\ngap queue"]; n999 [label="22:10 #999\nrule G0 + number check"];
    n1000 [label="22:42 #1000\nsubject answers"]; n1001 [label="23:20 #1001\nchat memory by GUID"]; n1002 [label="00:07 #1002\nsynthesis budget"];
    n1003 [label="00:33 #1003\nAs-Is / Future v1"]; n1004 [label="01:22 #1004\nlifecycles v2"]; }
  subgraph cluster_morning { label="Morning"; style="rounded,filled"; fillcolor="#EEF6EE"; color="#B9D7B9";
    n1005 [label="09:17 #1005\ndictated tickers,\ndossier, pills"]; n1006 [label="10:34 #1006\nHermes join-back"]; n1007 [label="11:20 #1007\npills spelled out"];
    n1008 [label="11:34 #1008\nprice/unit litmus"]; }
  subgraph cluster_midday { label="Midday"; style="rounded,filled"; fillcolor="#FFF7E6"; color="#E8D3A5";
    n1009 [label="12:01 #1009\nComms Editor,\n07:30 brief, GO"]; n1010 [label="12:47 #1010\nresearch escalation doc"]; n1011 [label="13:08 #1011\nGO alerts delivered"];
    n1012 [label="13:31 #1012\nResearch Circle ph.1"]; n1013 [label="13:49 #1013\nrepeat-alert ledger"]; }
  subgraph cluster_afternoon { label="Afternoon"; style="rounded,filled"; fillcolor="#FBEFEF"; color="#E3BDBD";
    n1014 [label="14:35 #1014\nresearch heartbeat"]; n1016 [label="14:53 #1016\nlong replies in parts"]; n1015 [label="15:09 #1015\nreal spend, $2 cap"];
    n1017 [label="15:52 #1017\nlane registry"]; n1018 [label="16:41 #1018\nrich alerts"]; n1019 [label="17:16 #1019\nbridge wedge fix"]; }
  subgraph cluster_evening { label="Evening"; style="rounded,filled"; fillcolor="#F1ECF8"; color="#CDBFE3";
    n1020 [label="19:14 #1020\noperator window,\nbalance check"]; n1021 [label="20:08 #1021\nspend label split"]; n1022 [label="21:15 #1022\nSOP sync"];
    n1024 [label="21:30 #1024\nAGENTS 1.2.0 ACTIVE"]; n1023 [label="21:50 #1023\ngit clean"]; n1025 [label="23:05 #1025\ndeploy reaches dev tree"]; }
  {rank=same; n997; n998; n999; n1000; n1001; n1002; n1003; n1004;}
  {rank=same; n1005; n1006; n1007; n1008;}
  {rank=same; n1009; n1010; n1011; n1012; n1013;}
  {rank=same; n1014; n1016; n1015; n1017; n1018; n1019;}
  {rank=same; n1020; n1021; n1022; n1024; n1023; n1025;}
  n997 -> n998 -> n999 -> n1000 -> n1001 -> n1002 -> n1003 -> n1004;
  n1005 -> n1006 -> n1007 -> n1008;
  n1009 -> n1010 -> n1011 -> n1012 -> n1013;
  n1014 -> n1016 -> n1015 -> n1017 -> n1018 -> n1019;
  n1020 -> n1021 -> n1022 -> n1024 -> n1023 -> n1025;
  n997 -> n1005 -> n1009 -> n1014 -> n1020 [style=invis, weight=20];
}
```

---

## 2. Every change, in merge order

Merge times are when GitHub merged the PR; each was promoted within minutes (release directory
timestamps in Appendix A). "Evidence" is what the PR shipped with.

| # | Merged (ET) | Live commit | Change | Why (trigger) | Evidence shipped |
|---|---|---|---|---|---|
| #997 | 09-13 20:14 | `c00e23eda` | Data-source-health alert rewritten for the operator: what each source feeds, what is wrong, next run, action; engineer detail at the end | first live alert printed cron strings; operator asked "what does this mean to me" | acceptance 162 PASS; 44 decay tests |
| #998 | 09-13 21:52 | `8513d12e9` | One reply chokepoint with a Sources line; house facts first; subject resolution (misroutes 14 → 0 on 36 real questions); symbol-scoped re-entry; one writer for `data_gap_registry`; resolved only on proof; ETA-aware expiry; agent narrative input cap 4,000 → 8,000 | SCHG got the whole book; a seasonality answer claimed cash was empty | acceptance 162 PASS; 211 tests; dry run SCHG gap #74 |
| #999 | 09-13 22:10 | `73a977a3b` | Rule G0 "use only supplied facts" in every agent contract; number check after every answer; demote to RESEARCH_MORE at ≥ 3 unsupported numbers and ≥ 50 % | operator asked that agents use Command Center data only | calibration over 300 stored results; 164 PASS |
| #1000 | 09-13 22:42 | `99e1925ec` | Named-stock answers: price, 30-day move, levels, analysts with age, research, "what this means"; honest pending-close text; checked DeepSeek summary | SpaceX close said "within 2h" at 9.4 h; Visa got options-desk rows | V dry run; 339 tests |
| #1001 | 09-13 23:20 | `a8a62217e` | Chat remembers each company by subject GUID; `operator_conversation` registry domain; Moomoo sync lane declared | operator asked for memory recall per subject | V recall dry run; 201 tests |
| #1002 | 09-14 00:07 | `c594d8600` | CIO synthesis prompt budget (newest 2 results per agent, 40,000 chars); synthesis cron cap 16,000 → 32,000 | DXCM synthesis failed 26×; CRXP 86 results would fail | CRXP 57.8k → 4.2k tokens |
| #1003 | 09-14 00:33 | `9a593e85a` | Platform docs sync 09-12..14; whole-platform As-Is and Future-State v1 | operator asked for all docs current | 184 doc tests |
| #1004 | 09-14 01:22 | `59d02f788` | Lifecycle As-Is and Future-State v2 (26 lifecycles, 57 feedback edges) + six fact bases | v1 rejected as "a snapshot, not the complete picture" | six read-only measurement passes |
| #1005 | 09-14 09:17 | `e7404e9e5` | Dictated tickers (`a x t i`) resolve; Flash may not demote a re-entry ask; freeform facts carry price and levels; subject dossier with 🟢/🔵/🟣 pills; Origin line on every reply | 08:23 AXTI reply said DATA_UNAVAILABLE while the house held it all | real-question dry run; 345 tests |
| #1006 | 09-14 10:34 | `94b5f6f82` | Hermes research joined back to the operator's pending question by id; research-only asks answered now with house facts; failed runs close immediately; monitor `RESEARCH_LANDED_UNSENT` | HPE research finished 09:16; operator never received it | real-ledger dry run: fulfilled=1 |
| #1007 | 09-14 11:20 | `afb63dcc8` | Pills spelled out: `🟢 Trade-AI data` · `🔵 Looked up outside Trade-AI` · `🟣 AI model (DeepSeek)`; a Key line on every reply | "I don't know what the color bubbles represent" | 181 tests |
| #1008 | 09-14 11:34 | `a3e7f94b6` | Repricer uses canonical mark (never position value); Alpaca prev_close from `dailyBar`; Finviz CSV parsed by header with contracts and explicit units; unit-aware consumers; Alpha Vantage health and symbol selection; litmus and view-contract tools; retention FK guard; EOD consolidated closes; three timers | "Garbage in, garbage out. This is critical." XLI stored 7.49 vs 169 | repricer dry run 9 corrected; litmus BLOCK on market_quotes |
| #1009 | 09-14 12:01 | `32897e80a` | Communications Editor at the send chokepoint (off/shadow/live); one 07:30 ET brief; chat routing map; "CIO Run Complete" noise removed; scalp GO criteria and screener GO alerts | 50 duplicate briefs, 299 raw-Markdown messages, 0 GO alerts since 07-13 | ARMP A+ and ELMT qualify |
| #1010 | 09-14 12:47 | `f8cb65638` | Research escalation measured and documented; Research Escalation Circle design; AGENTS "What 2026-09-14 taught" | "when does Hermes / Brave / DeepSeek hand off?" | code, flags, receipts, 88 tests |
| #1011 | 09-14 13:08 | `091a68efb` | GO alerts bypass the legacy digest router; a failed send is not recorded as sent | ARMP/ELMT filed as telemetry and suppressed | delivery confirmed 13:15 |
| #1012 | 09-14 13:31 | `3c2383044` | Research Escalation Circle phase 1: question GUID, free channels, deterministic score, grounded Context Analyzer, targeted second lap, check-ins (dry run by default) | operator: "an escalation circle with some intelligence" | HPE 2 laps, ANSWERED_PARTIAL; ELMT sufficient |
| #1013 | 09-14 13:49 | `65183522c` | Repeated alerts get their own ledger identity (body hash + minute) | 638 events for 638 openings; 14,163 illegal settles | 39 comms tests |
| #1014 | 09-14 14:35 | `06b9695ff` | Research heartbeat: queue lane, projection lock, restore lost requests, replay transients, guard false positives masked, health score reads research, escalation retries fixed (rc=127) | 136/219 requests failed; 32 lost; 36,365 dead retries | 12 restored, 1 replayed live |
| #1016 | 09-14 14:53 | `97ffd8ab2` | Long desk answers sent as ordered parts; phone rendering; undelivered replies logged as such | AXTI 4,571-char answer refused silently | 2 parts, 1,695 + 2,672 units |
| #1015 | 09-14 15:09 | `f8881c10e` | Real spend by provider/model/process; scheduled vs ad hoc; peak vs off-peak; Spend panel; daily/weekly/monthly Telegram texts; calibrated reservations; one $2.00 cap | "$7 limit but we never go above 7 cents" | real $4.73/wk vs projection $214.61 |
| #1017 | 09-14 15:52 | `3cc0bfb73` | Four research_scheduler cron lanes declared | cap change made 4 lines undeclared | lane registry clean |
| #1018 | 09-14 16:41 | `71979c627` | Rich GO, entry and material-change alerts: links, buttons, chart preview; `REPLY_NOT_DELIVERED` monitor | "no rich HTML context in Telegram" | ARMP renders 797 units |
| #1019 | 09-14 17:16 | `2e8ca5fd1` | Model bridge: 150 s wall-clock upstream deadline, threaded server with 4 in-flight slots, `GET /health`, watchdog every 5 min | DeepSeek held calls ~906 s; single-threaded bridge blocked everyone | 13 tests; /health < 20 ms live |
| #1020 | 09-14 19:14 | `eae7bfd5f` | Scheduled paid work only in the operator window and never at DeepSeek peak; spend checked against DeepSeek balance hourly | operator window rule; verify DeepSeek's real prices | gate 8 cases; rebill $5.42 vs $5.45 |
| #1021 | 09-14 20:08 | `0162d0f19` | Shared `advisory_desk_opinion` label split into eight named callers with their own caps | 88 % of spend under one unattributable id | 8-process label tests |
| #1022 | 09-14 21:15 | `d5a073a15` | AGENTS.md and reference docs record today's SOPs, traps, pricing and operator window; bridge MemoryMax in the repo unit | "validate everything is documented" | policy tests, release proof |
| #1024 | 09-14 21:30 | `839e86e2e` | AGENTS.md Policy-Version 1.2.0 ACTIVE on the operator's approval, bound to PR #1022 head `ad5c533b2` | operator sent `APPROVE_AGENTS_POLICY_1_2_0` | 55 policy/SOP tests |
| #1023 | 09-14 21:50 | `66a4250d7` | Three data files served from persistent state untracked; `archive/weekly/` ignored | dev tree never reported clean | temp-index dry run: status empty |
| #1025 | 09-14 23:05 | `341bce2c1` | `promote` fast-forwards the dev tree (or fails loudly), handling only the symlinked-untracked case automatically | a deploy said success with the dev tree on the old commit | 7 tests; first live run succeeded |

Also on 09-14, outside a PR: `test_research_circle_20260914` lifecycle test dated its evidence from
the real clock (it broke `cio-hardening` on main at 00:00Z); the fix rode #1022.

---

## 3. Incidents and root causes

### 3.1 Desk answers (AXTI, HPE, pills, long replies)

| When | What the operator saw | Root cause | Fix |
|---|---|---|---|
| 08:23 | "What is a x t i price…" → price and levels DATA_UNAVAILABLE | voice dictation spelled the ticker; Flash reclassified the ask as freeform; freeform context had no price or levels | #1005 |
| 09:12 | HPE research ask → a queue ticket, no facts; research never arrived | pending waited for a promoted HRI row the Hermes worker never writes | #1006 (delivered 10:36) |
| 10:36 | "I don't know what the color bubbles represent" | pills defined in two places, unlabelled on follow-ups | #1007 |
| 13:47 | AXTI question → silence ("5 minutes no reply") | 4,571-character answer over Telegram's 4,096 UTF-16 limit; plain retry refused; log said "replied" | #1016 (parts), #1018 (monitor) |

```dot
digraph desk {
  graph [rankdir=TB, fontname="Helvetica", fontsize=12, label="Telegram desk answer path after 2026-09-14", labelloc=t, nodesep=0.35, ranksep=0.45, pad=0.3];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9.5, color="#2B5797", fillcolor="#EAF1FB"];
  edge [color="#44546A", fontname="Helvetica", fontsize=8.5];
  q [label="Operator question\n(voice or text)", shape=oval, fillcolor="#FFF2CC", color="#BF9000"];
  poll [label="Poller / CIO bot\nclaim + checkpoint"];
  res [label="Subject resolver\nspelled tickers (a x t i → AXTI) #1005\nregistry + book only"];
  intent [label="Intent\nheuristic first; Flash may not demote\nre-entry / levels asks #1005"];
  ev [label="House evidence\nholdings · prices · levels · analysts ·\nresearch · subject memory #1001"];
  dossier [label="Subject dossier\n🟢 Trade-AI data · 🔵 outside · 🟣 AI model\n(spelled out #1007)"];
  hermes [label="Hermes research queued\nplan_id + research_id on the pending #1006", fillcolor="#F1ECF8", color="#7030A0"];
  now [label="Answer now with house facts\n+ \"Deeper research queued\" line #1006"];
  join [label="Join-back: result → pending\nfollow-up quotes the question #1006", fillcolor="#F1ECF8", color="#7030A0"];
  render [label="Phone rendering\nPart i of N · plain footer ·\nprovenance in expandable quote #1016"];
  send [label="send_message\nsplit ≤ 4,096 UTF-16 units\nok only if every part delivered #1016"];
  mon [label="Answer-quality monitor\nREPLY_NOT_DELIVERED #1018\nRESEARCH_LANDED_UNSENT #1006", fillcolor="#FBEFEF", color="#C00000"];
  q -> poll -> res -> intent -> ev -> dossier -> now -> render -> send;
  ev -> hermes [label="research gap"];
  hermes -> join [label="Hermes completes"];
  join -> render;
  send -> mon [style=dashed, label="turn has no message id"];
  hermes -> mon [style=dashed, label="landed, unsent > 10 min"];
}
```

### 3.2 Data integrity (#1008)

| Defect | Evidence | Effect | Fix |
|---|---|---|---|
| Repricer wrote a fractional position's **value** as its close | XLI 7.49 vs 169; NOC 123 vs 531; SCHG 8.05 vs 35 (9 of 25 holdings) | XLI sector RS −94.9 reached an operator answer | canonical mark, else value ÷ shares; refuse > 50 % from live quote |
| Alpaca `prev_close` from `prevDailyBar` | HPE 55.23 vs Friday 62.09 | false +12.4 % day | `dailyBar.c` when the bar predates today ET |
| Finviz read by column position | two hand "COL-FIX" edits | silent column shift | `lib/finviz_csv` DictReader + required-header contracts |
| Finviz units mislabelled 1,000× | market cap in millions stored as `market_cap_b` | $50B floor admitted $50M names | unit-aware consumers |
| Alpha Vantage health "unknown" since 05-09 | cron does not source `.env` | lane invisible | `.env` fallback; holdings-first selection |

```dot-wide
digraph data {
  graph [rankdir=LR, fontname="Helvetica", fontsize=12, label="Price and unit integrity controls (live 2026-09-14 11:35)", labelloc=t, nodesep=0.3, ranksep=0.5, pad=0.3];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9.5, color="#2B5797", fillcolor="#EAF1FB"];
  edge [color="#44546A", fontname="Helvetica", fontsize=8.5];
  subgraph cluster_src { label="Sources"; style=rounded; color="#C9D3DF";
    schwab [label="Schwab holdings\n(read-only sync)"]; alpaca [label="Alpaca snapshots"]; finviz [label="Finviz exports\nv=141 / v=152"]; yahoo [label="Yahoo Finance\n(independent reference)", fillcolor="#EEF6EE", color="#548235"]; }
  subgraph cluster_fix { label="Write-path fixes"; style=rounded; color="#C9D3DF";
    rep [label="Repricer\ncanonical mark, refuse > 50 %\nfrom live quote"]; prev [label="prev_close\ndailyBar when stale"]; csv [label="lib/finviz_csv\nheader contracts + units"]; }
  store [label="ticker_prices ·\nmarket_quotes ·\nsymbol enrichment", shape=cylinder, fillcolor="#FFF2CC", color="#BF9000"];
  subgraph cluster_ctrl { label="Drift controls (timers)"; style=rounded; color="#E3BDBD";
    litmus [label="Source litmus vs Yahoo\nTue–Sat 07:45\nBLOCK > 2 % off by > 10 %", fillcolor="#FBEFEF", color="#C00000"];
    views [label="Finviz view contracts\nMon–Fri 06:05", fillcolor="#FBEFEF", color="#C00000"];
    eod [label="EOD consolidated close\nMon–Fri 17:15\nreplace IEX closes > 1 % off", fillcolor="#FBEFEF", color="#C00000"]; }
  schwab -> rep -> store; alpaca -> prev -> store; finviz -> csv -> store;
  yahoo -> litmus; store -> litmus; finviz -> views; yahoo -> eod -> store;
}
```

### 3.3 Communications (#1009, #1011, #1013, #1018)

| Finding (5 Telegram exports) | Evidence | Fix |
|---|---|---|
| Duplicate morning briefs | 50 identical in 16 days, most at ~20:00 ET | one brief 07:30 ET weekdays; 20:00 and 08:05 senders retired (#1009) |
| Literal Markdown | 299 messages with raw asterisks | Communications Editor (HTML), rich layouts (#1009, #1018) |
| CIO Desk noise | 86 of 95 were "CIO Run Complete" | no check-in without an advisory action |
| Wrong chat | health/stop alerts in the Proposal Decisions group | routing map: DM · CIO Desk · proposals · OpenClaw |
| No GO alerts since 07-13 | GO rows every week in `trade_ai_scans` | scalp GO criteria + screener GO alerts (#1009); router bypass (#1011) |
| Repeated alerts collided in the ledger | 638 events for 638 openings; 14,163 illegal settles | body-hash + minute identity (#1013) |

```dot-wide
digraph comms {
  graph [rankdir=LR, fontname="Helvetica", fontsize=12, label="Outbound Telegram after 2026-09-14", labelloc=t, nodesep=0.3, ranksep=0.55, pad=0.3];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9.5, color="#2B5797", fillcolor="#EAF1FB"];
  edge [color="#44546A", fontname="Helvetica", fontsize=8.5];
  subgraph cluster_p { label="Producers"; style=rounded; color="#C9D3DF";
    brief [label="Morning brief\n07:30 ET weekdays"]; go [label="Screener GO alerts\n*/15 9–16 · scalp criteria"]; entry [label="Entry planner\nENTRY ALERT"]; mc [label="Material change"]; health [label="Health / sentinel alerts"]; desk [label="Desk replies"]; }
  chk [label="telegram_transport.deliver_text\n(send chokepoint)", shape=hexagon, fillcolor="#FFF2CC", color="#BF9000"];
  editor [label="Communications Editor\noff | SHADOW (09-14) | live\nHTML · GUIDs · dedupe 20 h ·\nCIO agreement · CC links · pills"];
  rich [label="telegram_rich layout\nlinks · buttons · chart preview\nkill switch TELEGRAM_RICH_ALERTS=0"];
  ledger [label="communication_events\nidentity = body hash + minute", shape=cylinder, fillcolor="#FFF2CC", color="#BF9000"];
  subgraph cluster_c { label="Chats (routing map)"; style=rounded; color="#B9D7B9";
    dm [label="Bot DM\nurgent + brief", fillcolor="#EEF6EE", color="#548235"]; cio [label="CIO Desk\ndecisions + Q&A", fillcolor="#EEF6EE", color="#548235"]; prop [label="Proposal Decisions\nproposals only", fillcolor="#EEF6EE", color="#548235"]; oc [label="OpenClaw\nAegis / Iris", fillcolor="#EEF6EE", color="#548235"]; }
  go -> rich [label="bypass legacy router #1011"]; entry -> rich; mc -> rich;
  brief -> chk; rich -> chk; health -> chk; desk -> chk;
  chk -> editor -> dm; editor -> cio; editor -> prop; editor -> oc;
  chk -> ledger [style=dashed];
}
```

### 3.4 Research heartbeat and the model bridge (#1014, #1019)

| Defect | Measured | Fix |
|---|---|---|
| CIO Hermes queue failing | 136 / 219 in 7 days (62 %); 13 / 18 in 24 h | lane `cio-hermes-queue`, health score reads it |
| Requests lost | 32 missing from a 30 MB unlocked projection | `projection_transaction` flock; `restore_lost_requests` |
| Transients never retried | 22 circuit/disconnect + 8 provider errors | classified retryable; `replay_retryable_failures` |
| Guard false positives | 63 refusals quoting third-party labels | labels masked; one guarded rewrite |
| Auto-fix dead | 36,365 retries exited 127 since 08-07 | `resolve_relative_venv` |
| Bridge wedged from 15:15 | DeepSeek held calls ~906 s; single-threaded server; `/health` absent | deadline 150 s, 4 threads, 503 BRIDGE_BUSY, `/health`, watchdog, MemoryMax 768M |

```dot
digraph bridge {
  graph [rankdir=TB, fontname="Helvetica", fontsize=12, label="Governed model bridge :8766 — before and after the 2026-09-14 wedge", labelloc=t, nodesep=0.3, ranksep=0.55, pad=0.3, compound=true];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9.5, color="#2B5797", fillcolor="#EAF1FB"];
  edge [color="#44546A", fontname="Helvetica", fontsize=8.5];
  subgraph cluster_before { label="Before (15:15–17:17)"; style="rounded,filled"; fillcolor="#FBEFEF"; color="#E3BDBD";
    c1 [label="Hermes jobs · desk · advisory"]; b1 [label="HTTPServer\n1 thread", fillcolor="#F8D7D7", color="#C00000"]; d1 [label="DeepSeek\nholds call ~906 s\n(keep-alive trickle)", fillcolor="#F8D7D7", color="#C00000"];
    c1 -> b1 [label="queue behind\neach held call"]; b1 -> d1 [label="90 s read timeout\nnever fires"]; }
  subgraph cluster_after { label="After (#1019, live 17:17)"; style="rounded,filled"; fillcolor="#EEF6EE"; color="#B9D7B9";
    c2 [label="Callers\n(name their task_type #1021)"]; b2 [label="ThreadingHTTPServer\n≤ 4 in-flight\nfull → 503 BRIDGE_BUSY (retryable)"];
    d2 [label="DeepSeek\nstreamed read\n150 s wall-clock deadline → TIMEOUT"]; h [label="GET /health\ninflight · oldest age · circuit"];
    w [label="cio_bridge_watchdog */5\nOK · BUSY_UPSTREAM · CIRCUIT_OPEN · WEDGED\nrestart after 2 misses (30 min cooldown)\nnever restarts for provider problems", fillcolor="#FFF2CC", color="#BF9000"];
    c2 -> b2 -> d2; w -> h [label="probe"]; h -> b2 [style=dashed]; }
}
```

### 3.5 Spend truth, the operator window and the label split (#1015, #1017, #1020, #1021)

| Question the operator asked | Measured | Change |
|---|---|---|
| "$7 limit but we never go above 7 cents or 50 cents" | real $4.73 / week; cap ledger counted $5.50; worst-case projection $214.61; live cap a forgotten $7.00 override | caps count actual spend; one $2.00/day cap; calibrated reservations (#1015) |
| Which LLM, which process, peak or off-peak, daily/weekly/monthly | week of 09-07: $5.45, 38 % on peak; Advisory Desk 8,424 scheduled peak calls | Spend panel `/v3/consumption`; Telegram texts 07:05 / Mon 07:10 / 1st 07:15 (#1015) |
| Was last week backfill or status quo? | mostly a one-time usefulness backfill (09-06 → 09-09); status quo ≈ $0.49/day | — |
| Could peak work run off-peak? Verify DeepSeek's prices | peak 01–04 and 06–10 UTC Mon–Fri at double; flash off-peak $0.003 hit / $0.15 miss / $0.60 out per 1M; rebill $5.42 vs $5.45 | operator window gate; timers moved; hourly balance reconciliation (#1020) |
| Who spent the money? | 88 % under `advisory_desk_opinion`, shared by ≥ 6 callers | eight named callers with own caps (#1021) |

```dot
digraph window {
  graph [rankdir=TB, fontname="Helvetica", fontsize=12, label="Scheduled paid-work gate (should_scheduled_skip, #1020)", labelloc=t, nodesep=0.35, ranksep=0.4, pad=0.3];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9.5, color="#2B5797", fillcolor="#EAF1FB"];
  edge [color="#44546A", fontname="Helvetica", fontsize=9];
  start [label="Cron line wrapped with\nrun_with_deepseek_offpeak.sh --scheduled", shape=oval, fillcolor="#FFF2CC", color="#BF9000"];
  manual [label="Manual / operator run?", shape=diamond];
  override [label="TRADEAI_ALLOW_SCHEDULED_PEAK=1?", shape=diamond];
  win [label="In operator window?\nweekday 09:00–21:00 ET or weekend", shape=diamond];
  peak [label="DeepSeek billing peak?\n01–04 or 06–10 UTC, Mon–Fri", shape=diamond];
  run [label="RUN", shape=oval, fillcolor="#EEF6EE", color="#548235"];
  skip [label="SKIP (logged)", shape=oval, fillcolor="#FBEFEF", color="#C00000"];
  start -> manual; manual -> run [label="yes — never gated"]; manual -> override [label="no"];
  override -> run [label="yes (one run)"]; override -> win [label="no"];
  win -> skip [label="no"]; win -> peak [label="yes"];
  peak -> skip [label="yes\n(e.g. Sun 21–24 ET,\nwinter 20–21 EST)"]; peak -> run [label="no"];
}
```

```dot-wide
digraph labels {
  graph [rankdir=LR, fontname="Helvetica", fontsize=12, label="LLM spend attribution after the label split (#1021)", labelloc=t, nodesep=0.22, ranksep=0.7, pad=0.3];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9, color="#2B5797", fillcolor="#EAF1FB"];
  edge [color="#44546A", fontname="Helvetica", fontsize=8];
  subgraph cluster_callers { label="Callers (send task_type)"; style=rounded; color="#C9D3DF";
    a [label="Telegram converse +\noperator desk loop (3 calls)"]; b [label="CIO plan enrichment"]; c [label="CIO prompt judge"]; d [label="Research circle analyzer"];
    e [label="hermes_llm_failover.chat_json"]; f [label="Usefulness scorer"]; g [label="Hermes CIO research backend"]; h [label="Hermes golden judge"]; i [label="Advisory opinion engine"]; }
  bridge [label="Governed bridge\nCALLER_TASK_PROCESS_MAP[advisory_desk]", shape=hexagon, fillcolor="#FFF2CC", color="#BF9000"];
  subgraph cluster_ids { label="Process ids (caps $/day · calls/day · mode)"; style=rounded; color="#B9D7B9";
    p1 [label="cio_operator_reply\n0.60 · 400 · manual", fillcolor="#EEF6EE", color="#548235"]; p2 [label="cio_plan_enrichment\n0.50 · 400"]; p3 [label="cio_prompt_judge\n0.10 · 150"];
    p4 [label="research_circle_analyzer\n0.10 · 40 · manual", fillcolor="#EEF6EE", color="#548235"]; p5 [label="hermes_cloud_json\n0.30 · 300"]; p6 [label="hermes_usefulness_score\n0.30 · 600"];
    p7 [label="cio_hermes_research\n0.40 · 200"]; p8 [label="hermes_golden_judge\n0.10 · 150"]; p9 [label="advisory_desk_opinion\n(advisory_opinion + unknown)"]; }
  cap [label="Global cap $2.00/day\n(actual spend)", shape=octagon, fillcolor="#FBEFEF", color="#C00000"];
  a -> bridge [label="operator_reply"]; b -> bridge [label="plan_enrichment"]; c -> bridge [label="prompt_judge"]; d -> bridge [label="research_circle"];
  e -> bridge [label="hermes_cloud_json"]; f -> bridge [label="usefulness_score"]; g -> bridge [label="hermes_research_job"]; h -> bridge [label="golden_judge"]; i -> bridge [label="advisory_opinion"];
  bridge -> p1; bridge -> p2; bridge -> p3; bridge -> p4; bridge -> p5; bridge -> p6; bridge -> p7; bridge -> p8; bridge -> p9;
  p1 -> cap [style=dashed]; p6 -> cap [style=dashed]; p9 -> cap [style=dashed];
}
```

### 3.6 Research Escalation Circle, phase 1 (#1010, #1012)

Measured first (#1010): no quality-based escalation existed; for operator questions Brave was
off and Hermes was the only step that ran; Brave spilled to SearXNG only on quota or 429.

```dot
digraph circle {
  graph [rankdir=TB, fontname="Helvetica", fontsize=12, label="Research Escalation Circle — phase 1 lifecycle (dry run by default)", labelloc=t, nodesep=0.35, ranksep=0.55, pad=0.3];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9.5, color="#2B5797", fillcolor="#EAF1FB"];
  edge [color="#44546A", fontname="Helvetica", fontsize=8.5];
  asked [label="ASKED\nquestion_guid (uuid5)", shape=oval, fillcolor="#FFF2CC", color="#BF9000"];
  gather [label="GATHERING (lap n)\nhouse · Yahoo (quote, analysts, volume,\nearnings, news, bar levels) ·\nSEC Form 4 · SearXNG"];
  score [label="Deterministic score\nstale + contradiction capped;\nundated never stamped today"];
  analyze [label="ANALYZED\nContext Analyzer (DeepSeek Flash via bridge)\nrejects unknown evidence ids"];
  lap2 [label="Targeted lap\nqueries from missing facts;\nno new evidence → stop, no model call"];
  ans [label="ANSWERED", fillcolor="#EEF6EE", color="#548235"]; part [label="ANSWERED_PARTIAL\nmissing facts named", fillcolor="#FFF7E6", color="#BF9000"];
  sched [label="SCHEDULED check-in\nday after catalyst · analyzer horizon · 7 / 14 d", shape=oval, fillcolor="#F1ECF8", color="#7030A0"];
  asked -> gather -> score -> analyze;
  analyze -> lap2 [label="targeted_lap"]; lap2 -> gather [style=dashed];
  analyze -> ans [label="sufficient"]; analyze -> part [label="bound reached"];
  ans -> sched; part -> sched;
}
```

Next phases (not built): Brave when the analyzer names it; Hermes over house + web evidence; critic
and DeepSeek Pro; check-in sweep REVISITED → SETTLED; desk wiring behind a flag.

### 3.7 Git, deploy and the dev tree (#1023, #1025)

| When | What happened | Fix |
|---|---|---|
| 20:10 | a regenerate step meant for a worktree ran in the live dev tree and staged 119 files (`git add -A`); the commit hook refused | list saved; only those paths unstaged; working files untouched |
| 20:10 | `sync_cio_process_caps.py --help` ran a live upsert (no argument parsing) | values matched the registry; recorded as a trap |
| 21:50 | three tracked files behind `data/runtime` / `data/audit` symlinks showed as deleted | untracked (#1023) |
| 21:51 | the deploy's `git merge --ff-only && git log` swallowed a refused fast-forward and reported success | index-only fix by hand (hashes unchanged), then #1025 |
| 23:06 | first live run of promote's new step | "dev tree fast-forwarded to 341bce2c1" |

```dot
digraph deploy {
  graph [rankdir=TB, fontname="Helvetica", fontsize=12, label="Exact-main deploy after #1025", labelloc=t, nodesep=0.35, ranksep=0.38, pad=0.3];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9.5, color="#2B5797", fillcolor="#EAF1FB"];
  edge [color="#44546A", fontname="Helvetica", fontsize=8.5];
  merge [label="PR merged at tested head\n(--match-head-commit)", shape=oval, fillcolor="#FFF2CC", color="#BF9000"];
  prep [label="prepare\nclone CURRENT, overlay origin/main,\nbuild frontend, stamp SHA"];
  prom [label="promote\nCURRENT → release; restart portfolio-server\n+ bound units; health check"];
  rb [label="rollback to PREV\n(not PROMOTE OK)", fillcolor="#FBEFEF", color="#C00000"];
  pin [label="expected-release pin + receipt\nPROMOTE OK"];
  ff [label="ff_dev_tree_after_promote (#1025)\nfetch in CANONICAL_SOURCE"];
  plain [label="fast-forward", shape=diamond];
  safe [label="blocked only by files the target no longer\ntracks, behind a symlink, live copy exists?", shape=diamond];
  fix [label="hash live copies → git rm --cached\n→ retry → re-hash"];
  ok [label="dev tree = release = main", shape=oval, fillcolor="#EEF6EE", color="#548235"];
  die [label="exit non-zero:\nrelease live, dev tree NOT fast-forwarded", shape=oval, fillcolor="#FBEFEF", color="#C00000"];
  manual [label="Still manual (runbook step 7):\nrestart tradeai-cio-telegram · install new user units ·\ndeclare crontab edits", fillcolor="#F4F6F9", color="#8497B0"];
  merge -> prep -> prom; prom -> rb [label="health fails"]; prom -> pin [label="health ok"]; pin -> ff -> plain;
  plain -> ok [label="succeeds"]; plain -> safe [label="refused"]; safe -> fix [label="yes"]; safe -> die [label="no"];
  fix -> ok [label="hashes equal"]; fix -> die [label="retry refused\n(index restored)"]; ok -> manual [style=dashed];
}
```

### 3.8 Other incidents

- **OpenClaw weekly "Gemma4:26B on Volken Intel B50" job** (09:03–09:25): timed out, misnamed the GPU, delivered garbled tool text, and did not use the local model (it ran on ChatGPT). Operator chose **Disable**; row kept.
- **Date-dependent test** (00:00Z → 21:1x): `test_a_lap_writes_the_lifecycle_only_when_applied` dated evidence 09-14 while `run_lap` reads the real clock; broke `cio-hardening` on main at UTC midnight. Fixed by dating that test's evidence from the real clock.
- **Google token for mcporter** failing since at least 09-01 ("gcloud auth print-access-token returned empty"). Operator re-authenticated at 23:4x; refresh succeeded.
- **Answer-quality alert at 23:22Z**: all three findings were turns asked before the day's fixes deployed (AXTI 13:47 before #1016; HPE 09:12 before #1006).

---

## 4. Operator decisions recorded

| Time | Decision (operator's words where given) | Implemented |
|---|---|---|
| 09-13 ~21:00 | Reconnect the desk to the gap queue | #998 |
| 09-14 ~09:05 | Architect gaps: quarantine corrupt prices (archive + tripwire); schedule the commitment sweep; gap resolver live for free vectors; Comms Editor shadow 1 trading day then live | partly — see open items |
| 09-14 ~09:12 | Disable the OpenClaw Gemma job | disabled, row kept |
| 09-14 ~10:40 | Data integrity: "1. approve 2. yes 3. yes 4. yes or finviz or schwab" — fractional Schwab price (consumer-side); retention may hard-delete with FK guard; schedule litmus and view contracts; consolidated EOD closes (Yahoo) | #1008 |
| 09-14 ~11:00 | Comms: routing map yes; one 07:30 ET weekday brief; GO alerts on Trade-AI scalp criteria incl. social; noise → digest | #1009 |
| 09-14 ~14:00 | Caps count actual spend; durable $2.00/day global cap; retire the $7 override | #1015 + host cap consolidation |
| 09-14 ~16:00 | "install the bot API and let's make this happen" (rich Telegram) | #1018 |
| 09-14 ~18:40 | Operator window: "9 a.m. to 9 p.m. Eastern … and on the weekends, and only a la carte stuff that is urgent, that's requested by the operator, is ran during peak hours"; then "yes" to the five proposals | #1020, #1021 |
| 09-14 ~21:20 | "fix everything now" (SOP on main, git clean) | #1022, #1023 |
| 09-14 ~21:25 | `APPROVE_AGENTS_POLICY_1_2_0` (activates every PROPOSED 1.2.0 row) | #1024 |
| 09-14 ~23:10 | "add the fix to the repo" (deploy fast-forward) | #1025 |
| 09-14 ~23:15 | Check the label split tomorrow morning | scheduled 09-15 10:03 ET |
| Pending | Thesis catalog v2: approve / revise / reject 28 theses and 5 re-curation cadences | awaiting operator |
| Pending (dismissed) | Strategy approval baseline and thesis-catalog wiring questions | on hold by operator |

---

## 5. Host and runtime changes outside git

| Time | Change | Backup / receipt |
|---|---|---|
| 09-13 22:46 | Moomoo read-only sync re-enabled | `crontab_backup_before_moomoo_reenable_20260913224613.txt` |
| 09-14 09:25 | OpenClaw cron job `e7b71848…` disabled | `openclaw cron get` → enabled False |
| 09-14 11:00–11:03 | Crontab: brief 08:00 → 07:30; 08:05 delivery and 20:00 aegis duplicate commented out | `crontab_backup_20260914_1100.txt` |
| 09-14 11:35 | Timers enabled: source litmus, Finviz view contracts, EOD consolidated close | systemd user units |
| 09-14 12:02 | Comms Editor mode file `~/.config/tradeai/comms_editor_mode` = shadow; GO alerts cron `*/15 9-16 * * 1-5` | `crontab_backup_pre_go_1202.txt` |
| 09-14 15:11 | Cap consolidation: one `~/.config/tradeai/llm_global_daily_usd_cap.env` = 2.00 via `99-llm-global-cap.conf`; $7.00 and $1.50 overrides archived with a tripwire README; six inline cron values; three spend-text cron lines | `crontab_backup_pre_spend_1511.txt` |
| 09-14 17:18 | Bridge watchdog cron `*/5`; bridge restarted onto #1019 | `crontab_backup_pre_bridge_watchdog_20260914T171856.txt` |
| 09-14 18:18 | Bridge drop-in `90-memory.conf` MemoryMax=768M | systemd drop-in |
| 09-14 19:16 | Operator-window schedules: holdings 08:00 → 09:05; scorer and DDQ wrapped `--scheduled`; flash market 9–19; balance snapshot `50 * * * *`; lessons-reflect 19:40; shadow-seed 19:45; cache-worker drop-in 09..19 ET | `crontab_backup_pre_offpeak_20260914T191645.txt` |
| 09-14 20:10 | Bridge restarted at 0 in-flight onto the label-split map; `llm_process_config` caps synced for 8 processes | live `/health` |
| 09-14 23:4x | Google credential re-authenticated (operator); mcporter token refresh succeeded | unit Result=success |
| Live now | crontab 511 active lines; lane registry 107 declared / 73 ACTIVE / 0 undeclared | `check_lane_registry.py` clean |

---

## 6. Governance and documentation

- **AGENTS.md 1.2.0 ACTIVE** (Effective-Date 2026-09-14). Activates the multi-agent SOP controls
  (session receipts, worktree identity, file leases, changed-file quality), the guarded push/deploy
  approval workflow, the `delivery_owner` rule, reply and data-gap rules, the MAJOR §7A/§17
  data-source ownership change, the $2.00 cap, and today's SOPs: replies split at 4,096 UTF-16 units;
  callers name their task type; bridge liveness (deadline, slots, /health, watchdog); diagnose at the
  bridge first; balance reconciliation; the operator scheduled-work window; six tooling traps.
- **Reference docs updated today:** `GOVERNED_MODEL_BRIDGE.md`, `CIO_TELEGRAM_PRODUCT_STANDARD.md`,
  `RESEARCH_PRIORITIZATION.md`, `HEALTH_AGENT.md`, `LLM_SPEND.md`, `RESEARCH_CIRCLE.md`,
  `RESEARCH_ESCALATION_2026-09-14.md`, `GAP_RESOLUTION.md`, `OPERATOR_REPLY_ROUTING.md`,
  `FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md` (promote now fast-forwards the dev tree), `CHANGELOG.md`.
- **This documentation set** (As-Is, Future State, lifecycle pair, six fact bases, research escalation,
  this log) re-issued as Word documents with diagrams, published to Google Drive and in the repo.

---

## 7. Research and advisory work products (not code)

| Product | State | Where |
|---|---|---|
| Research & Spend Matrix | published | claude.ai artifact `aeaa0c42-8699-4832-bbf9-e3178cfc756f` |
| Thesis Catalog v2 — 28 theses in 10 families (calendar & politics, geopolitics & defense, macro & rates, AI infrastructure, secular growth, mispriced quality, income, financials, events, risk & hedges), 5 proposed re-curation cadences, a "considered and not proposed" list | **awaiting operator decisions**; v1 errors corrected (missed Iran/Hormuz, rate thesis reversed to hikes, no midterm cycle, BDCs, AI capex counter-thesis, SpaceX unlocks) | claude.ai artifact `2c65d016-be50-4014-8ef5-fa02b06b2e95` (decisions saved in its database) |
| Strategy wiring finding | 22 strategy YAMLs; persistent CIO/desk agents do not read them; no operator approval records; discovery lane idle | on hold by operator |

---

## 8. Open items and verification schedule

| Item | Check | When |
|---|---|---|
| Label split on real traffic | `llm_consumption_log` rows under the 8 new ids; operator replies manual | **09-15 10:03 ET** (scheduled) |
| Operator-window schedules | 09:05 holdings run; gated scorer/DDQ; balance snapshot history growth | 09-15 daytime |
| Spend text | 07:05 text shows outside-window and balance lines | 09-15 07:05 |
| Communications Editor | review one trading day of shadow receipts, then switch to live (already approved) | after 09-15 close |
| Rich GO / entry alerts | first market-hours alerts render with links and buttons | 09-15 market hours |
| Research circle | phases 2–4 (Brave on demand, Hermes over web evidence, critic + Pro, check-in sweep, desk wiring) | not started |
| Architect gaps still open | quarantine corrupt prices; commitment sweep cron; gap resolver live; finding ledger; unit install in deploy; restore drill | per plan |
| Deploy still manual | restart `tradeai-cio-telegram` after desk changes; install new user units | every deploy |
| Pre-existing failing tests outside CI | `test_cio_operator_desk_loop*` (3), `test_governed_agent_flash_market::test_scheduled_canary…`, `test_research_lane_health_alert::test_fix_hint_is_not_stale_import` and others noted in PRs | backlog |
| Thesis catalog and strategy approvals | operator decisions | operator |

---

## 9. Traps learned today

| Trap | Rule |
|---|---|
| Parallel shell calls share one working directory | give every command an explicit `cd` or `git -C` |
| `regenerate_generated_files.sh` runs `git add -A` | run it only inside a worktree; check staged names before committing |
| `sync_cio_process_caps.py` has no argument parsing | read `main()` first; treat any run as live |
| `Path.read_text`/`write_text` rewrite CRLF files | edit mixed-CRLF files byte-wise (bridge, caps sync, Telegram standard) |
| Registry JSON uses `\u` escapes | re-dump with `ensure_ascii=True`, indent 2 |
| `sys.modules` stubs leak across tests | load new modules by file path in tests |
| Worktrees lack `.venv` and live data | link the dev tree venv; some tests only pass in the dev tree |
| Docs index drifts after merging main | regenerate after every merge commit |
| Only 4 SOP evidence files are digest-bound | never sed the whole folder |
| `set -e` ignores failures inside `&&` lists | check the result explicitly; deploy now asserts dev tree = main |
| Tracked files behind a symlink look deleted to git | untrack them; `ff_dev_tree` handles the fast-forward |
| A test with a fixed date breaks at UTC midnight when the code reads the clock | date test evidence from the real clock or pass `now` |
| Telegram limits count UTF-16 units | split long bodies; a missing message id means not delivered |
| A held provider call can wedge a single-threaded server | wall-clock deadline, threads, /health, watchdog |
| Voice dictation spells tickers | resolvers must accept spaced and dotted letters |
| A bare "yes" to an either/or question is ambiguous | state the reading taken |
| Operator approval does not lift AGENTS §0 rails | find the consumer-side fix and say so |
| `gog drive upload --dry-run` uploads for real | search the folder first |

---

## Appendix A — Releases promoted on 2026-09-14

| Release directory (sha-label-timestamp) | PR |
|---|---|
| `c594d8600-main-exact-phase2-20260914-000703` | #1002 |
| `9a593e85a-main-exact-phase2-20260914-003355` | #1003 |
| `59d02f788-main-exact-phase2-20260914-012306` | #1004 |
| `e7404e9e5-main-exact-phase2-20260914-091759` | #1005 |
| `94b5f6f82-main-exact-phase2-20260914-103415` | #1006 |
| `afb63dcc8-main-exact-phase2-20260914-112033` | #1007 |
| `a3e7f94b6-main-exact-phase2-20260914-113442` | #1008 |
| `32897e80a-main-exact-phase2-20260914-120132` | #1009 |
| `091a68efb-main-exact-phase2-20260914-130816` | #1011 (includes #1010) |
| `65183522c-main-exact-phase2-20260914-135003` | #1013 (includes #1012) |
| `06b9695ff-main-exact-phase2-20260914-143551` | #1014 |
| `97ffd8ab2-main-exact-phase2-20260914-145326` | #1016 |
| `f8881c10e-main-exact-phase2-20260914-150934` | #1015 |
| `3cc0bfb73-main-exact-phase2-20260914-155243` | #1017 |
| `71979c627-main-exact-phase2-20260914-164205` | #1018 |
| `2e8ca5fd1-main-exact-phase2-20260914-171643` | #1019 |
| `eae7bfd5f-main-exact-phase2-20260914-191450` | #1020 |
| `0162d0f19-main-exact-phase2-20260914-200906` | #1021 |
| `d5a073a15-main-exact-phase2-20260914-211606` | #1022 |
| `839e86e2e-main-exact-phase2-20260914-213050` | #1024 |
| `66a4250d7-main-exact-phase2-20260914-215028` | #1023 |
| `341bce2c1-main-exact-phase2-20260914-230556` | #1025 |

## Appendix B — Sources

PR bodies #997–#1025 (GitHub); `~/.local/state/cio-phase2-exact-main/deploy_receipt.json`; release
directory names; crontab backups in the session scratchpad; `check_lane_registry.py`; `systemctl --user
list-timers`; bridge `/health`; memory notes of 2026-09-13/14; the session transcript.
