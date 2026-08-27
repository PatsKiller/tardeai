# MISS-1 DWSN Case Study

## Timeline

| Event | Time (ET) | Delta |
|-------|-----------|-------|
| Proposal created | 12:47 | 0 |
| Telegram alert | None sent (ALERT-1 not yet live) | — |
| Operator sees proposal | ~13:15 (estimated) | +28 min |
| Check Execution run | 13:19 | +32 min |
| Execution result | BLOCKED_PRICE_MOVED | — |

## At Creation (12:47)

- Entry: $3.91
- Stop: $3.71
- Target: $4.30
- R:R: 1.95 (already below 2.0 minimum)
- Strategy: momentum_scalp
- Source: incubator promoter
- Quote: not checked at creation

## At Check Execution (13:19, +32 min)

- Quote: $4.46 (Alpaca)
- Price moved: +14.1%
- Spread: 14.8%
- Volume: 1,873
- R:R: recalculated would be ~0 (price above target)
- Blockers: price moved, spread too wide, no volume

## Classification

**Status:** `rebuild_required` / `blocked_before_action`

The proposal was never actionable:
- R:R was 1.95 at creation (below 2.0 minimum)
- PROMOTE-1 gate would now block this
- No Telegram alert was sent (ALERT-1 not yet live at creation time)
- Even if alert was instant, R:R was already below minimum

## What Would Be Different Now

| Gate | Would Block? |
|------|-------------|
| PROMOTE-1 (R:R < 2.0) | **Yes — would not create proposal** |
| ALERT-1 (Telegram) | Would send BLOCKED alert immediately |
| ALERT-2 (Callback) | Would show REBUILD, not APPROVE |
| Q-1 (Quote refresh) | Would detect stale quote |

## Conclusion

DWSN was an **avoided bad trade**, not a missed opportunity. The system correctly
blocked approval. The real improvement is PROMOTE-1 preventing the proposal from
being created at all with R:R 1.95.
