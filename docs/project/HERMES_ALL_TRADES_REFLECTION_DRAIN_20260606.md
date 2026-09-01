# Hermes All-Trades Reflection Drain — Batch 1 (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-06T19:36:39-04:00
Measured at: efcc51365 / not measured

Resumed Hermes reflection generation against the CANONICAL all-trades tier
`closed_trade_needing_reflection` (queries `trade_instances`, all source_systems) — NOT the legacy
paper-only `closed_paper_trade`. CLI: `hermes_autonomous_loop.py --loop ticker_challenger --apply
--max-rows 10` (targeting is wired in get_ticker_targets; no --target-tier flag needed).

## Target / canonical confirmation
- Batch-10 preview sources: held_position 3, schwab_import 5, alpaca_paper 2 → 7/10 carry
  trade_instance_id (held are live, no instance). All-trades, both Schwab + paper selected. ✓
- Every new reflection stamped trade_instance_id; 0 new legacy-only (paper_trade_id-only) rows.

## Batch result (timeout-limited)
- Run window 12:43:55→12:53:15 UTC; **EXIT 124 (hit 560s timeout)** — cut off mid-run, not a failure.
  Per-symbol commits persisted; the 0-byte log is buffered stdout lost on SIGTERM.
- New trade_instance_id-linked reflections: **4** (all schwab_import: AXTI#99, AUUD#89, ARKG#85, APAM#81).
- held_position targets (priority 0) ran first and consumed the early LLM slots before the timeout.

## Linkage before → after
- hermes linked by trade_instance_id: **24 → 28**
- legacy-only (paper_trade_id only): **0** · unlinked (non-trade research: backlog/momentum/youtube): 1403 (expected)
- linked reflections by source_system: alpaca_paper 8, **schwab_import 20**
- backlog closed_trade_needing_reflection: **165 → 161** (alpaca_paper 28, schwab_import 133)
- outcome_fed_back: 25 → 25 (unchanged — Schwab imports are not in proposal_outcome_chain; paper-only chains)

## Skips / malformed
- No malformed-payload retries observed in the committed set; timeout truncated remaining targets (safe —
  they remain in the backlog for the next run). No endless retries.

## Safety
ALPACA_MODE=paper, live disabled. Reflections are research writes only (hermes_research_intelligence via
validated staging path). No broker/order/stop/proposal/GO-WAIT/strategy/live/Phase-205 changes; no
production learning graft.

## Recommendation for next batch
- The scheduled challenger cron already drains this tier continuously (linked 7→24→28 over recent runs).
- For manual batches: use **--max-rows 6** to fit comfortably inside the ~9-min runner window, OR run
  with a longer timeout. Consider deprioritizing held_position during dedicated drain runs so closed-trade
  backlog (Schwab 133 + paper 28) drains faster — held positions currently consume the first slots.
- No code fix required; throughput is purely LLM wall-clock + runner timeout.

---
## Read-only status re-check (2026-06-06, no batch run)

SELECT-only; git unchanged at a428eae. No hermes --apply, no broker/order/proposal/GO-WAIT/strategy/
Phase-205 actions.

### Findings
- Linked reflections: **28 → 28 (unchanged since batch-1)**; backlog **161 → 161** (paper 28, schwab 133).
- Most recent trade-linked reflection: 08:53:03 (batch-1 cutoff) — nothing new since.
- by source_system: alpaca_paper 8, schwab_import 20. legacy-only links: 0. unlinked non-trade: 1403.
- outcome_fed_back: 25/169 (unchanged). Stack healthy (receiver/gov/mon-wd active; Hermes writing 7.6m).
- Phase 205 backup timer: already auto-fired Sat 02:30:42 (CLEAN); next Sun 02:30 — left alone.

### Held-position STARVATION confirmed
A Hermes loop is active and writing, but the trade-linked backlog has NOT advanced. **51 held-position
tickers were researched in the last 24h**, consuming the priority-0 slots. Held-position research on open
Schwab positions isn't even trade_instance-linked (no closed trade → no trade_instance_id), so it
advances neither the linked count nor the closed backlog. The 161 closed-trade backlog (pri-1) sits
behind held (pri-0). **Held priority is starving closed-trade reflection.**

### Decision (per operator rule)
- Backlog is STUCK, not falling → cron alone is not draining it.
- A plain manual `--max-rows 6` batch would be starved the same way (held pri-0 first) → NOT recommended.
- Recommended design change (gated on operator approval, NOT implemented): add a **drain mode** to
  `get_ticker_targets` (flag/env) that temporarily promotes `closed_trade_needing_reflection` above
  `held_position` for dedicated drain runs only, leaving normal 24/7 production priority (held-first)
  untouched. ~10-line reversible targeting change. Then `--drain --max-rows 6` would actually pull down
  the closed backlog (133 schwab + 28 paper).

---
## Drain mode implemented + Batch 2 (2026-06-06)

### Why
Read-only re-check confirmed held-position priority-0 starving closed-trade reflection (backlog flat at
161 while 51 held tickers consumed slots/24h). Fix: explicit, off-by-default drain mode.

### Implementation (scripts/hermes_autonomous_loop.py)
- New CLI flag `--drain-closed-trades` (off by default). `get_ticker_targets(conn, max_rows,
  drain_closed_trades=False)`: when True, `closed_trade_needing_reflection` is the SOLE priority-0 tier
  and held/proposals are skipped FOR THAT RUN ONLY. Normal production cron priority (held-first) unchanged.
- Targets carry canonical `trade_instance_id` (not legacy paper ids). Preview line logged when draining.
- Verified preview — NORMAL: held 2 + schwab 3 + paper 1 (5/6 ti). DRAIN: schwab 4 + paper 2, 6/6 ti,
  zero held_position.

### Batch 2 run
- Command: `--loop ticker_challenger --apply --max-rows 6 --drain-closed-trades`
- EXIT 124 (hit 520s timeout) — 4 of 6 completed; remaining stay in backlog (no blind retry).
- Succeeded: AXTI#98, AUUD#88 (schwab), ASPN#6 (PAPER), APAM#80 (schwab) — 3 schwab + 1 paper, all
  trade_instance_id-linked. Held-position starvation eliminated (drain skipped held).

### Before → after
- linked by trade_instance_id: **28 → 32** (alpaca_paper 8→9, schwab_import 20→23)
- backlog closed_trade_needing_reflection: **161 → 157** (paper 28→27, schwab 133→130)
- legacy-only links: 0 · unlinked non-trade research: 1410
- outcome_fed_back: 25 → 25 (drained trades not in paper proposal_outcome_chain — expected)

### Safety
ALPACA_MODE=paper, live disabled. Research writes only; no broker/order/stop/proposal/GO-WAIT/strategy/
live/Phase-205; no production graft. Normal cron priority untouched (drain is explicit + off by default).

### Recommendation
- Throughput is LLM-bound (~4 reflections per ~8.7-min runner window). Next: `--max-rows 4
  --drain-closed-trades` per run to finish inside the window, OR a longer timeout for bigger batches.
- **Do NOT** wire drain mode into the production cron — it must stay manual/explicit so 24/7 held-position
  monitoring is preserved. Operator-run drain batches (or a separate low-frequency drain timer) only.
- ~157 closed trades remain; each batch is controlled + auditable. No further batch without approval.

---
## Batch 3 (2026-06-06) — clean completion at max-rows 4

Command: `--loop ticker_challenger --apply --max-rows 4 --drain-closed-trades` (operator-authorized single batch).
- **EXIT 0 (clean, no timeout)** — max-rows 4 fits the runner window (the lesson from batch 2's EXIT 124).
- 3 reflections committed: BLMN#39 (paper), BLBD#48 (paper), AXTI#94 (schwab) — all trade_instance_id-linked.
- before→after: linked **33 → 36** (alpaca_paper 10→12, schwab_import 23→24);
  backlog **157 → 154** (paper 27→25, schwab 130→129). legacy-only: 0. outcome_fed_back 25→25.
- Both sources drained (paper + schwab); held-position starvation eliminated; no third batch run.

### Cumulative this session
linked 28 → 36 (+8), backlog 165 → 154 (−11) via drain batches 2–3 + cron. Throughput LLM-bound;
**max-rows 4 is the safe per-batch size** (clean exit). ~154 closed trades remain; operator-approved
batches only — drain mode stays manual (never wired into the production cron).

### Safety
ALPACA_MODE=paper, live disabled. Research writes only; no broker/order/GO-WAIT/strategy/live/Phase-205;
no production graft.

---
## Summary recovery added (2026-06-06)
Residual drain rejects were MISSING-summary (gemma3 using alt keys / drifting shape). Added bounded, quality-gated summary recovery (`hermes_output_recovery.py`) — strict path unchanged; recovery only on missing-summary; generic/evasive/too-short stay rejected; trade_instance_id still required. Validation 10/10. See `HERMES_SUMMARY_RECOVERY_20260606.md`.

---
## FINAL — full drain complete (2026-06-06, driver brpwf0zys, 60-iter cap)

Operator "complete all max drain left" — drained the canonical closed-trade reflection backlog via
`--drain-closed-trades` (driver `scripts/drain_all_closed_trades.sh`, 60-iteration safety cap).

- **Backlog: 145 → 2** (driver END snapshot logged 9 at the cap; the scheduled cron continued draining via
  the canonical closed_trade_needing_reflection tier to 2 shortly after).
- **Hermes trade-linked reflections: 45 → 188 (+143).** By source_system: alpaca_paper 36, schwab_import 151.
- **Residual: 2** — both `GSIT` (schwab_import). Reason: genuinely-sparse local-LLM output (fails the
  summary + evidence_json substance gates); recovery (b8ab67a) correctly rejected, never fabricated. These
  re-attempt automatically on future scheduled cron runs.
- 0 legacy-only links throughout (all canonical trade_instance_id).
- outcome_fed_back unchanged at 25/169 — the drained reflections are Schwab imports, which are not in
  proposal_outcome_chain (paper-proposal chains only); expected, not a gap.

### Fixes that made the full drain possible (all this session)
- 6304065: stamp hermes_agent_name/research_type from code (eliminated the dominant reject class).
- 3707347: stamp deterministic topic from code.
- 206f950 + b8ab67a: bounded, quality-gated summary recovery (alt-key/raw-paragraph), correctly rejecting
  genuinely-sparse output — no fabrication, no quality-bar lowering.

### Safety
Research-only (hermes_research_intelligence writes via validated path; local Ollama). No broker/order/stop/
proposal/GO-WAIT/strategy/live/Phase-205 changes; no production learning graft.
