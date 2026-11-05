# Ticker Prospectus — cheaper Watch reports (batch, medium effort, ~5k tokens)

Operator 2026-10-26: "implement this cost savings right now; we don't need it immediately". Code:
`scripts/lib/prospectus/batch.py`, `generate.py` (per-scope settings, `finish_doc`), `pipeline.py` (`persist_doc`,
Watch rows skipped by the synchronous runner), `scripts/prospectus_build.py` (collect + submit after the queue run).

## Per-scope generation — `config/prospectus_generation.json`

| Scope | Effort | Max output tokens | Words / section | Path |
|---|---|---|---|---|
| holding | high | 16,000 | 120-260 | synchronous (unchanged) |
| watch | medium | 5,000 | 50-110 (same section set, concise) | Message Batches API (50% price) |

Kept in its own file so it does not collide with concurrent edits to `config/prospectus.json`. Blocks and charts are
unchanged (they are data, not prose). Delta (weekly) rewrites keep `delta_max_output_tokens`.

## Batch path

1. Watch rows queued by the cadence / first build / gate rewrites accumulate. Holdings, and anything the operator asked
   for (`Rewrite now` = `operator_refresh`, `--symbols` = `operator_cli`, priority 1), stay synchronous.
2. `submit_due` fires when ≥ `batch.min_items` (10) Watch rows are queued or the oldest has waited
   `batch.max_wait_hours` (6); `--batch-now` forces it. For each row: house inputs → the data-quality gate (HARD_FAIL
   parks it as `blocked_data`, nothing is submitted) → the web planning turn (synchronous) → the concise writer prompt →
   `AnthropicTransport.submit_batch` (Opus 5.5, credit tier `long_form`, `effort: medium`, 5,000 tokens). Each row is
   its own single-request batch, so the credit book, process cap and per-request ledger stay exact. The queue row moves
   to `batch_pending`; the packet is kept in the private store (`data/prospectus/batch_pending/<SYM>.json`).
3. `collect` (every `--apply` run) polls each pending entry. A succeeded result is validated (`finish_doc`: grounding,
   MBI guard, gate layer 3) and written by `pipeline.persist_doc` (render, store, index, gate rewrite) — the same path
   as a synchronous report. Errored, expired (> `lost_after_hours`, 30) or lost results re-queue the row; the third
   failure marks it `failed`.
4. Idempotent: the transport refuses a second ledger row (`ALREADY_COLLECTED`), and a closed local entry is never
   collected again.

Governance: the native per-process reservation is opened before submit and settled at the projected hold right after
the batch is accepted (a batch outlives the 30-minute stale-reservation recovery), so the process daily cap counts
the conservative hold; the credit book settles the actual batch cost on collect. Transport change: `submit_batch`
takes an explicit `effort` and accepts the tiers in `anthropic_credit_policy.batch_tiers` (`bulk`, `standard`,
`long_form`).

## Cost per Watch report (estimate)

From the 45 stored Watch reports: median about 10.6k input and 10.7k output tokens, about $0.31 each. New path:
writer turn (10.6k in, ~4k out, Opus 5.5, 50%) ≈ $0.06 + the web planning turn (unchanged, synchronous) ≈ $0.05 +
the gate's Haiku read ≈ $0.001 → **about $0.12 per Watch report** (worst case at the 5k cap about $0.13).

## Commands

```
python3 scripts/prospectus_build.py --scope watch --limit 3        # dry: shows batch=true, effort=medium, estimate
python3 scripts/prospectus_build.py --apply --due --limit 12       # holdings sync; Watch: collect, then submit if due
python3 scripts/prospectus_build.py --apply --batch-now            # submit every queued Watch row now
python3 scripts/prospectus_build.py --apply --no-batch             # everything synchronous this run
```
