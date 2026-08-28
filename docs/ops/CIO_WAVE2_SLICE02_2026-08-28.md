# CIO Wave 2 Slice 02 — PRIM thesis hole

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## Dry (before --apply)

| Check | Result |
|-------|--------|
| Why `missing_symbol_thesis` | No `symbol_prim` in `cio_theses.jsonl` (0 hits). Coverage `RESEARCH_REQUIRED`. |
| On-disk research | **yes** — 10 `hermes_external_research` rows. Latest id **48254** chatgpt 2026-08-27. |
| Existing mint path | PRIM is T1-WATCH. Joined rec+dissent+evidence grades **A / CURRENT**. |
| Sample | Paper-trade / sandbox challenge, not a broker order. Operator rule: sandbox is not ignore; a good thesis moves to normal CIO. |
| would_mint | CURRENT |
| would_notify | false (default; `--notify` opt-in) |
| applied | 0 before `--apply-live --symbols PRIM` |

Grok latest sibling row is execution-language / profile refusal (272 chars). Not used. Distinct-on-symbol picks chatgpt 48254.

## Apply once

```
scripts/thesis_mint_from_research.py --symbols PRIM --apply-live
# notify default off
```

| Field | Value |
|-------|--------|
| applied_mint | **1** (`symbol_prim@v1`) |
| notify Telegram | **false** (desk card only; `CIO_THESIS_TELEGRAM (default off)`) |
| home `/api/v3/cio/home` NEW_POSITION_IF PRIM | **CURRENT** |
| telegram_sent | false |

Persist of operator/investment product used production `PYTHONPATH=.../CURRENT/scripts` (not the worktree). A first persist from the worktree thinned watch/reentry (`ModuleNotFoundError: lib`); rebuilt from production path. Last-good restored: watch_block 21 / ready 4 / fires_s7 false / reentry 67 / NKE PFSI PRIM SH XLU CURRENT.

## Code

- `scripts/lib/symbol_thesis_mint_gate.py` — paper-trade is sandbox; PASS still mints. Skip empty / cost-cap / true broker-exec only. `sandbox_to_cio_thesis_text` strips the execute-wrapper and stamps "Not an order."
- `scripts/thesis_mint_from_research.py` — `--symbols`, `--notify` default off, uses the gate for `would_say`.

No new LLM. No fake thesis. PRIM is CURRENT from existing research.
