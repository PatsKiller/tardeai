# Trade-AI scalp scan every 5 minutes, one feed for both engines, runner GO with catalyst (2026-10-09)

Your requests:

- "active trader firing but nothing on tradeai"
- "these are scalps should be every 5 minutes at least fix now legacy … same should be feeding both tradeai and also
  active trader"
- "allow GO for 40+ with catalyst"

## What was wrong (read-only investigation)

- **Two schedulers write the same runs.** The system unit `tradeai-continuous.service` runs the continuous runner from
  the dev tree. Cron `run_orchestrator_slot.sh --no-llm` runs at 9/10/12/14/16.
  - Both stamp run_label 0900. `process_reaper` allows one `trade_ai_orchestrator` at a time, so the 10:00 cron slot
    was killed ("Terminated").
  - "PARTIAL · run 55/40" was the label holding the union of both writers plus the live cycles.
- **Market-hours coverage has gaps.** Runner windows leave 11:00–11:30, 12:15–13:30 and 14:15–15:15 uncovered.
- **No enrichment on `--no-llm` runs.** Finviz enrichment ran only `if use_llm`. At 0900, 36 of 48 MANUAL_REVIEW rows
  were unenriched top-gainer injects (no RVOL/gap/float).
- **Every runner is capped by design.** The warrior lanes and catalyst exception hold every runner at MANUAL_REVIEW
  ("never auto-GO"), so a 40+ runner with a catalyst could not be GO.
- **The engines never see each other.** Active Trader's universe was `scalp_scan_results` (social scanners) only. The
  Finviz screener pull (`run_finviz_momentum_scalp_scan`, every 5 min, 06:00–11:59) wrote to
  `screener_symbol_membership`, which AT never read. Trade-AI never showed AT alerts.

## Changes

| Change | Where |
|---|---|
| **Runner GO with catalyst.** A MANUAL_REVIEW runner (high-RVOL / momentum / low-price) scoring at or above the GO threshold (40, plus the VIX add-on) with a verified catalyst becomes GO. Reverse-split squeezes, micro-float runners and unenriched injects keep the ceiling. The scalp critic still reviews every GO. Rollback: set `catalyst_runner_go: false`. | `lib/catalyst_exception.promote_catalyst_go`, `scoring.py`, `assets/weights.yaml` |
| **Enrichment without the LLM.** Finviz enrichment runs on `--no-llm` runs too. Rollback: `TRADEAI_ENRICH_WITHOUT_LLM=0`. | `trade_ai_orchestrator.py` |
| **5-minute RTH scalp lane.** `run_trade_ai_scalp_live.py` runs one deterministic live cycle (no paid LLM) over the scalp screeners (`scalp` run window), under its own run_label `scalp`. Its alert memory is saved between runs, so a GO alerts once. It never overwrites the main dashboard or `live_run_state.json`. Cycle time: 470 s cold, 204 s warm; `flock -n` skips a start while one is running. | `scripts/run_trade_ai_scalp_live.py`, `continuous_runner.py` (`CycleState.to_dict/from_dict`, `publish_dashboard`), `assets/screeners.yaml` |
| **One feed for both engines.** The scalp lane writes `persistent-state/data/trade_ai/scalp_universe_latest.json` (one writer). Active Trader's universe adds that projection (if under 15 min old), the live Finviz screener snapshot, and today's Trade-AI GO/WAIT/MANUAL_REVIEW names. All pass the same float/price fail-closed checks. Live check: universe 43 → 53. | `scalp_shadow_logger.shared_feed_rows`, `scalp_projection_rows`, `config/scalp_signal_engine.yaml` `shared_feeds` |
| **Header counts the FULL run.** Live-cycle rows no longer inflate "scanned". | `api_v2.py` |
| **AT fires on the Trade AI tab.** Shows today's sent Active Trader alerts, with Trade-AI's verdict for the same symbol. | `components/tradeai/ActiveTraderFiresStrip.tsx` |
| **Cron.** Add `trade-ai-scalp-live` (`*/5 9-15`). Drop the 09:00 and 10:00 orchestrator slots, which collide with the runner's FULL runs at those anchors. Keep 12/14/16 and 17:30. | `config/lane_registry.json`; crontab change under a cron grant |

**Operator action still open.** The system unit `/etc/systemd/system/tradeai-continuous.service` runs from the dev
tree. Promote fast-forwards the dev tree, so its code matches the release after each deploy. Changing the unit itself
needs root.

## Where n8n fits

The n8n program is coordination only. n8n never calls an LLM, never scores, and never writes market data. For this
pipeline it can mature:

1. **Scheduler of record.** The 5-minute scalp lane becomes an n8n schedule with run receipts, retries, overlap guard
   and an alert when a run is late or fails. It replaces cron plus flock once N1 shadow proves it.
2. **One fan-out per tick.** One n8n tick triggers the Finviz pull lane, then the Trade-AI scalp lane, then the AT
   universe refresh, in order, with a receipt for each step. This removes clock-based coupling between separate cron
   lines.
3. **Event bridge.** An Active Trader TRIGGERED event (the gateway `event` route) can request an immediate Trade-AI
   rescore of that one symbol, through a governed lane, instead of waiting for the next tick.
4. **Watchdog.** n8n checks the projection's age and raises one Communications event if it is older than 15 minutes
   during market hours.

None of this is on the critical path. The lane ships on cron today.
