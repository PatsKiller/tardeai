# D2 — OUTCOME_PENDING_DATA triage (2026-08-31)

**Authority:** `READ_ONLY_ADVISORY` · behaviour rail = unconditional raise · MBI=0  
**as_of:** 2026-08-31T04:30:48+00:00 UTC  
**Root:** `/home/johnclaw/trade-ai-releases/persistent-state`  
**Branch:** `fix/overnight-d2-pending-data`  
**No deploy.**

---

## What the store showed

Latest fold of `data/cio/outcome_checkpoints.jsonl`
(`[VERIFIED]` 2026-08-31T04:30Z):

| status | count |
|---|---|
| SCHEDULED | 645 |
| OUTCOME_PENDING_DATA | **153** |
| NOT_PRICE_RESOLVABLE | 60 |
| RESOLVED | 6 |

All 153 PENDING_DATA rows carried `resolution_reason =
no_price_history_for_comparison`. They were written on 2026-08-29 (152) and
2026-08-31 (1). After that mark, `due_checkpoints()` never selected them again
— it only considers `SCHEDULED` — so they sat terminal-looking but not terminal.

| symbol | pending |
|---|---|
| SCHD | 42 |
| SRNE | 26 |
| ARKX | 24 |
| XLI | 22 |
| JEPI | 20 |
| SPCX | 13 |
| NOC | 6 |

152/153 have `entity_type=UNRESOLVED` (no security_guid at bind time); 1 is a
`TRIM` on SCHD with no entity_type. Prior reason on every row:
`no_price_history_for_comparison`.

---

## Classification (dry-run)

`scripts/resolve_due_checkpoints.py` now always censuses PENDING_DATA:

| class | meaning | action |
|---|---|---|
| `future_dated` | `due_at` still in the future | leave |
| `obtainable` | both price ends exist in `ticker_prices` | resolve (env-gated) |
| `stuck_waiting_data` | structurally price-comparable; prices still missing | leave |
| `never_resolvable` | cash / no subject / no decision ts / unregistered | **expire** (env-gated) |

Live dry-run against the production state root (`[VERIFIED]`):

```
── PENDING_DATA triage ──
as_of                  2026-08-31T04:30:48+00:00
root                   /home/johnclaw/trade-ai-releases/persistent-state
pending_total          153
future_dated           0
obtainable             153
stuck_waiting_data     0
never_resolvable       0
applied                False
resolved               0
expired                0
  pending reason: 153x  price_history_available
  would-resolve XLI    +0.03%  2026-08-28→2026-08-30  cid=962819565211079a846b
  would-resolve SRNE   -99.70%  2026-08-28→2026-08-30  cid=66e1893df54c9e0ec085
  would-resolve SCHD   +0.06%  2026-08-28→2026-08-30  cid=ba18c4fac15f8bedd462
```

Prices for every pending symbol are present in `ticker_prices` through
2026-08-30. The backlog is obtainable, not future-dated, not structurally
never-resolvable. The defect was **no retry path** after the first
PENDING_DATA append.

`--apply-pending-data` without `TRADEAI_PENDING_DATA_APPLY=1`:

```
APPLY_REFUSED: --apply-pending-data refused unless TRADEAI_PENDING_DATA_APPLY=1.
Even when armed, writes are append-only resolve/expire receipts.
applied                False
expired                0
```

`[VERIFIED]` same session. Cron `--apply` (SCHEDULED-only) is unchanged and
does not require the new env gate.

---

## What shipped

| file | change |
|---|---|
| `scripts/lib/outcome_resolution.py` | `STATUS_EXPIRED`, `classify_pending_checkpoint`, `triage_pending_data` |
| `scripts/resolve_due_checkpoints.py` | always-on PENDING census; `--apply-pending-data` + env gate |
| `tests/test_overnight_d2_pending_data.py` | classification + refuse/expire/resolve receipts |
| `scripts/run_cio_hardening_ci.py` | gate `overnight_d2_pending_data` |

Expire receipts use status `OUTCOME_EXPIRED` and reason
`pending_data_expired:<cause>`. Append-only; original PENDING row retained.

---

## Counts to report (as_of + root above)

| metric | count |
|---|---|
| pending_total | 153 |
| future_dated | 0 |
| stuck_waiting_data | 0 |
| obtainable (would_resolve) | 153 |
| never_resolvable (would_expire) | 0 |
| expired this run | 0 (dry-run; no live mutation) |

Operator may later arm `TRADEAI_PENDING_DATA_APPLY=1` and run
`--apply-pending-data` to append the 153 resolve receipts. That is a separate
explicit step — not this PR, not deploy, not cron.
