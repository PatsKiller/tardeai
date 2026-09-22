# Single-letter ticker `S` — link bleed / research-first / stale quotes

```
Status:      ACTIVE
as_of:       2026-09-22T18:20:00-04:00
Measured at: origin/main tip was 857931d41 (PR #1187+#1191 promoted) ·
             residual live failure ~17:49 ET · fix SHA f08425299 (this PR)
Canonical repo path: docs/audits/SINGLE_LETTER_TICKER_S_FIX_2026-09-22.md
Authority:   live operator paste + hermetic dual-import proof (AGENTS.md §8)
Supersedes:  PR_ONLY note on docs branch cursor/docs-ticker-s-sync-667c (PR #1188)
See also:    docs/OPERATOR_REPLY_ROUTING.md ·
             docs/audit/message-identity-audit-2026-09-21.md §4 ·
             docs/plan-s-hollow-research-then-answer.md (store) ·
             AGENTS.md §7 operator replies · §9.1 rich layout
```

## Live verdict timeline

| when | pin | verdict |
|---|---|---|
| morning 2026-09-22 | `466c781d0…` | **PR_ONLY** — #1187 draft only |
| ~17:05 ET promote | `857931d41-main-exact-phase2-20260922-170257` | #1187+#1191 **on tip**; telegram cwd matched |
| ~17:49 ET operator ask | same pin | **RESIDUAL FAIL** — TROW/HODO chrome + hollow buy-perspective |
| this PR | pending promote | dual-import chrome + research-first deferred |

Hermetic PASS ≠ OBSERVED_LIVE. Re-ask `S` from Telegram after this PR promotes before claiming OBSERVED.

## What broke (three waves)

### Wave A — pre-#1187 (served `466c781d0`)

1. Link-chrome bleed (TROW class) from body-extract subjects.
2. Single-letter `S` extract / bind gaps.
3. Soft research gaps prompted `research S` instead of auto-enqueue.

### Wave B — #1187 + #1191 promoted (`857931d41`) — still failed live

1. **Dual-import ContextVar.** Cron puts `scripts/` on `sys.path`, so
   `lib.comms_editor` ≠ `scripts.lib.comms_editor`. Converse set
   `primary_symbols` on one module; `deliver_text` read the other → footer still
   `S:84601d7d TROW:69403c08 HODO:dc347eda`. `[VERIFIED]` dual-import dry-run.
2. **Hollow buy/perspective.** Phase 2A answer-now + Hermes pending still led with
   a DeepSeek reword of thin/STALE house facts (Sep-04 $19.84, 432h) for
   "im thinking of buying S give me the perspective".
3. **Stale quotes.** STALE labeled but still narrated as perspective substrate.

## What this fix changes (`f08425299`)

| area | change |
|---|---|
| `scripts/lib/comms_editor.py` | Process-global primary-symbol bucket via `sys.modules` (survives dual import) |
| `scripts/telegram_transport.py` | `send_message(..., primary_symbols=)` → `deliver_text` |
| `scripts/lib/cio_operator_desk_loop.py` | Buy/perspective → research+analyst needs; thin research or stale quote → **blocking**; lead with deferred research-first (no hollow essay); stale quotes emit `quote_price` / `missing_market_data` |
| `tests/test_single_letter_tickers.py` | Dual-import chrome + buy-perspective deferred + non-buy soft path |

MBI=0; no broker; no new quote writer — refresh rides existing gap_resolver vectors.

## Dry-run after (hermetic)

```
kind=deferred source=buy_perspective_research_first
🧠 Alex · Research first — no hollow perspective
… will not invent one from thin or stale house facts …
Queued: Hermes research + quote refresh · ≈ 30 min · Pending opr_…
chrome footer: S:84601d7d only (no TROW/HODO)
```

## Related PRs

| PR | role |
|---|---|
| #1187 | single-letter + primary_symbols (merged) |
| #1190 / #1191 | soft pending + STALE label (merged; #1190 superseded) |
| #1188 | docs PR_ONLY snapshot — **superseded by this note**; close or land as historical |
| this PR | dual-import + research-first residual |

## Honesty bar

- Promote of #1187/#1191 was real; residual live failure was also real.
- Do not inflate hermetic dual-import PASS to OBSERVED_LIVE until Telegram on the
  new pin is re-asked.
