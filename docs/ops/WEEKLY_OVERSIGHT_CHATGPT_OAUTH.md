# Weekly oversight — ChatGPT OAuth auto, paid manual

**Date:** 2026-08-21  
**Authority:** READ_ONLY_ADVISORY  
**Flags unchanged:** `RESEARCH_SKIP_GATE` unset/0 · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**CURRENT:** do **not** promote for this during the 8/21–8/27 payload window.

## What fired

Friday 2026-08-21 18:15 ET crontab:

```
15 18 * * 5 cd $PROJ && flock -n /tmp/weekly_paid_review.lock bash -c \
  "set -a; . ./.env; set +a; .venv/bin/python scripts/defense_weekly_paid_review.py"
```

`$PROJ` = rebuild. Script saw `oversight_paid.weekly_paid_review=true` and called
`run_paid_review(seats=["paid"])` → Anthropic `claude-opus-4-8` → Telegram
`[OPERATIONAL] Weekly paid oversight (claude-opus-4-8): ok · $0.396`.

Operator: auto = OAuth ChatGPT; paid needs manual approval.

## Policy

| Path | How | Spends |
|---|---|---|
| Friday cron (no flags) | `run_free_critiques(seats=["chatgpt"])` via `llm_lane` ChatGPT OAuth `:8646` | $0 |
| Paid Claude / metered seat | `python scripts/defense_weekly_paid_review.py --apply-paid` (optional `--seat paid`) | budget-gated |
| `--dry-run` | prints mode, no DB / LLM / Telegram | $0 |

`oversight_paid.weekly_paid_review` is **false**. The old script treated that
key as an auto-fire; leaving it false means a stale tree cannot spend Opus.
`--apply-paid` is the only paid gate on the new script — config cannot auto-spend.

`oversight_free.weekly_auto_review=true`, `weekly_auto_seat=chatgpt`.

## Cron

Keep the same command. **Never** pass `--apply-paid`. After 8/27 close, retarget
`$PROJ` to CURRENT with cutover Batch C.

## Metric

- `oversight_reviews` Friday rows: `seat=chatgpt` (auto) vs `seat=paid` (only after `--apply-paid`)
- `logs/weekly_paid_review.log` line `[weekly-oversight] auto oauth chatgpt`
- Telegram: `Weekly oversight (chatgpt oauth): … · $0` — not `Weekly paid oversight`

## MATURITY_IMPACT

Cost-routing defect: weekly auto spent paid Claude. Live path is ChatGPT OAuth.
Tests: `tests/test_defense_weekly_oversight.py`. No DecisionPayload producer
change. No CURRENT promote (scripts+config would fail docs-only pin hygiene and
restart the 5-day clock).
