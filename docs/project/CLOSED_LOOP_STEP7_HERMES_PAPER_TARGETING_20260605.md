> **Canonical model note:** Paper trades are the first executable source and first backfilled source. The canonical learning loop is all-trades, broker/account neutral (`trade_instances`). `paper_trade_id` is a compatibility key; `trade_instance_id` is the canonical key going forward. See `CLOSED_LOOP_ALL_TRADES_ABSTRACTION_20260606.md`.

# Closed-Loop Step 7 — Hermes Paper-Loop Targeting (2026-06-05)

Status:      ACTIVE
as_of:       2026-06-05T23:46:56-04:00
Measured at: efcc51365 / not measured

## Gap (from re-audit v2)
Hermes related_trade_id was 2/1256 — the **write-path** (Step 2) was correct, but **targeting** sent the
challenger at live Schwab held positions (no paper_trade to link). Root cause: the closed-trade tier
deduped by **symbol** against `researched_ever`, so any paper symbol ever researched (16 of them) was
permanently excluded from per-trade reflection → 42 of 43 closed paper trades never got a trade-id link.

## Fix (research-only; no trading change)
`hermes_autonomous_loop.get_ticker_targets`: added a dedicated **closed_paper_trade** tier — closed
paper trades (ticker) that have NO hermes reflection linked yet. It is keyed on trade-linkage (NOT
symbol freshness), so it bypasses `researched_recent` and carries the exact `paper_trade.id`, which the
return path uses as `related_trade_id` (no symbol-resolution ambiguity). Priority 1 (with proposals);
held-position research at priority 0 is preserved.

## Proof (live run, --apply --max-rows 4)
- targeting now surfaces closed paper trades with exact ids (AGNC→30, ANY→48, ASPN→27, BLBD→16, …), 6/6 linked.
- ran the challenger: hermes related_trade_id **2 → 4** (AGNC#30, ANY#48 freshly stamped; 1 held target
  rejected on a malformed LLM payload — unrelated to targeting).
- ~40 closed paper trades remain unlinked; the scheduled challenger now works through them automatically.

## Safety
Research-only (writes hermes_research_intelligence via the validated staging path). Local LLM (Ollama).
No order/broker/GO-WAIT/strategy/proposal/live/Phase-205 changes. ALPACA_MODE=paper.
