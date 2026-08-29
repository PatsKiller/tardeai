# Notify preconditions — four checks (2026-08-29)

**Telegram send stays OFF.** `CIO_SITUATION_NOTIFY` 0, INTERDICT on,
`telegram_sent` false, 0 Telegram API calls in this PR. This document is not a
request to turn it on.

| # | check | result |
|---|---|---|
| 1 | S0 attaches to plan_id and rehydrates | **PASS** — shipped in #652 |
| 2 | CC shows more than SCHD without a ping | **PASS** — bug found and fixed |
| 3 | Grok critique can attach or reject for real | **BLOCKED** — second allowlist, documented below |
| 4 | Dust / CASH cannot produce a fire | **PASS** — one legacy plan flagged |

## 1. S0 attach + rehydrate — PASS

Merged as #652, live on `1d5f3343`.

- "what about RTX", no open plan → **one S0**, symbol RTX, registry load
- second RTX turn → **same plan_id, new operator_turn_id**
- "SCHD defer" → **attaches to `plan_schd_s6`**, no duplicate S6
- CASH / dust / TEST → **refuse mint**, recorded not minted
- product shows `operator last: defer (2026-08-29)` when present

Root cause was that `extract_symbols` existed in `cio_telegram_converse` and was
never wired into `cio_converse_core`'s mint path, so free-text questions minted
`symbols: []` — which is why the desk appeared to know only SCHD.

## 2. CC beyond SCHD — PASS, after fixing a real bug

`coverage.with_plan_symbols` already carried **15 names** — AMANX, ARKX, BAH,
BND, CSWC, DIV, NOC, PFLT, **RTX**, SCHD, SPCX, V, XAR, XLB, XLI — over
`open_plans_considered: 450`. HOLD/WATCH names are in coverage, not silent.

But the notification block read **`plans`**, which `api_v3_cio.py:1139` builds as
`get_cio_plans(limit=12)` — the CIO NOW window. So it reported:

    considered 8 · surfaced 0 · suppressed 8 · s0_open 0

against 450 real open plans. Now fed `coverage_plans`, the full open store:

    considered 467 · surfaced 4 · suppressed 463 · s0_open 6

A count that looks like the whole picture and is not is the same error as
showing only the survivors. **NOW stays capped at 5 cards; the block is not a
card**, and no cards were added.

## 3. Grok critique — BLOCKED by a second allowlist

The authorised line was applied to **that process only**. A semantic diff of the
registry confirms exactly one process changed:

    maria_research_critique
      allowed_lanes  ['fast','deepseek-v4-flash'] -> [..., 'grok']
      lane_policy    deepseek_only -> either
      daily_cost_cap_usd 0.3 (unchanged — no cap raise)
    process count 56 -> 56

`should_call(maria_research_critique, 'grok')` still returns
**`POLICY_NOT_ALLOWED`**, because there are two allowlists:

1. `config/llm_process_registry.json` — the file, now updated
2. **`llm_process_config.allowed_lanes` in Postgres** — what `should_call`
   actually reads

`sync_process_policies_from_registry()` bridges them and *does* append any lane
in the registry entry. It reported `updated: 56` and grok still did not land —
because `REGISTRY_PATH` resolves relative to the **running release**
(`ROOT/config/...`), and the running release is the promoted pin, which does not
yet contain this change.

So the sequence is: **merge → promote → sync → hop.** The hop was not forced by
hand-editing a release, and no second process was widened.

Per the instruction — *"If POLICY_NOT_ALLOWED persists: document the second
allowlist, stop"* — item 3 stops here. **No Flash-critique, no
`grok_execution_review`, no hop.**

## 4. Dust / CASH cannot fire — PASS

15 tests covering the four named subjects:

| subject | S0 mint | graph impact | detector |
|---|---|---|---|
| SCHG 0.2294 | refuse `dust_residual` | skip `dust_residual` | skip `dust_residual` |
| SRNE $0.90 | refuse `dust_residual` | skip `dust_residual` | skip `dust_residual` |
| CASH | refuse `cash_or_non_entity` | skip `cash_or_non_entity` | skipped |
| QCOM not held | S0 question allowed | skip `not_held` | n/a |

A CUSIP skips as `not_a_ticker`, and **unknown market value is HELD, never
dust** — `dust_residual@v1` does not guess a missing price away. Skips carry a
*reason* rather than an empty result, which is what stops the 20-minute re-fire:
a skip that is not recorded happens again next cycle.

### One legacy plan, flagged not actioned

`plan_7bd81581b9d4` — an open **S1 draft on SRNE** ($0.90 dust) predating the
rule. The existing hygiene would expire it, but its dry run shows
**`would_expire: 49`** — it targets all revisit-overdue drafts, far wider than
the one plan named. Running it was not authorised here, so it was not run. The
new guards prevent *new* dust fires; this one needs your call.

## Verification

`/health` 200 · `/v3/cio` 200 · cash **630,784.82** unchanged ·
`cio_run` `DETERMINISTIC_PRODUCT` · dry eligible **4, 0 paid calls** ·
`telegram_sent` **false** · INTERDICT **true** · **0 Telegram API calls**.

587 green plus 16 CC-block tests; acceptance green. `cio_command_center.py` is
CRLF, edited via `safe_text_edit`, 0 stray LF.

## Forbidden, and not done

No "Telegram on", no Maria send, no CIO bot send, no digest schedule, no
IMMEDIATE delivery, INTERDICT not lifted, `CIO_SITUATION_NOTIFY` not set. MBI 0,
ROTATE advisory-only, council DISPUTED stands, no R1 widen, no cap raise, no
checkpoint history rewritten.

Delivery stays off until the operator sentence: **"Telegram on"** + channel
(CIO bot | Maria /cio) + bar (S6 fire only | digest only | CC already enough).
