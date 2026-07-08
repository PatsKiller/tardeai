# Phantom Elimination — Broker-Confirmation Gate (DESIGN, vendor-neutral)

**Status: DESIGN / test-and-design only. NOT wired into the live execution path. The gate's
counting logic is NOT changed until approved.** This document is the STEP 1 report.

## Why broker-agnostic is the fix (not just future-proofing)

STEP 0 proved the phantoms come from two broker-coupled creation paths that bypass the
order-confirmation discipline the clean submit path enforces:

- `proposal_approved` (5/8 phantoms): promoted `pending → open` by **symbol match**, dropping
  the order id.
- `alpaca_sync` (3/8 phantoms): a **broker-named** path that writes `open` from a position
  snapshot, never capturing an order id.

The clean `alpaca_paper_adapter.submit_entry` path produced **zero** phantoms because it goes
through one door: await fill → stamp `broker_order_id` → write. An adapter interface forces
*every* path, for *every* broker, through that same `confirm_fill()` door. **Agnosticism and
phantom-elimination are the same change: one confirmation door, no broker creates a counted
row without walking through it.**

## 1. The `BrokerAdapter` contract (vendor-neutral interface)

A formal contract every broker implements. Callers depend on this, never on a concrete broker.

```python
# scripts/broker_adapter.py  (NEW — pure interface, no broker logic)
from typing import Protocol, Optional
from dataclasses import dataclass

@dataclass
class FillConfirmation:
    confirmed: bool                 # broker affirms this order is filled
    broker_order_id: Optional[str]  # the broker's authoritative order id
    filled_qty: Optional[float]
    filled_price: Optional[float]
    fill_time: Optional[str]        # ISO; the broker's fill timestamp
    status: str                     # 'filled' | 'partial' | 'pending' | 'canceled' | 'unknown'
    raw: Optional[dict] = None

class BrokerAdapter(Protocol):
    broker_name: str                # 'alpaca' | 'schwab' | ... — set by the impl, NEVER read by callers

    def submit_order(self, *, symbol, qty, side, order_type, limit_price=None,
                     stop_price=None, client_order_id=None) -> FillConfirmation: ...
    def get_order_status(self, order_id: str) -> FillConfirmation: ...
    def confirm_fill(self, order_id: str) -> FillConfirmation: ...     # poll-until-resolved
    def get_positions(self) -> list: ...
    def get_open_orders(self) -> list: ...
    def get_account(self) -> dict: ...
    def get_status(self) -> dict: ...
```

**Already present** on all three adapters: `get_positions/get_open_orders/get_account/get_status/
submit_entry/sync_positions`. **New to add to the contract:** `get_order_status(order_id)` and
`confirm_fill(order_id)` (Alpaca's submit_entry already polls for fill internally — that logic is
*extracted* into `confirm_fill`, not rewritten). `submit_entry` is adapted to return a
`FillConfirmation`.

## 2. Adapter resolution — from the ACCOUNT, never a broker name

```python
# the gate NEVER names a broker; it resolves the adapter from the account
from broker_config import get_account_broker      # already exists
def adapter_for(account_label) -> BrokerAdapter:
    broker = get_account_broker(account_label)     # 'alpaca' | 'schwab' | ...
    return _ADAPTER_REGISTRY[broker](account_label=account_label)
```

`_ADAPTER_REGISTRY` maps a broker name → its implementation class. Adding Schwab/IBKR later =
one registry entry + one adapter file. The gate code is untouched.

## 3. The confirmation gate (broker-neutral)

```python
# scripts/broker_confirmation_gate.py  (NEW — zero broker literals)
def confirm_and_finalize(trade_id, account_label, order_id, *, timeout_s=120):
    adapter = adapter_for(account_label)
    fc = adapter.confirm_fill(order_id)            # polls the broker, whichever it is
    if fc.confirmed:
        # stamp the GENERIC columns that already exist
        _update(trade_id, broker=adapter.broker_name, broker_order_id=fc.broker_order_id,
                broker_status='filled', broker_filled_at=fc.fill_time,
                entry_price=fc.filled_price, shares=fc.filled_qty,
                status='open', confirmation_state='BROKER_CONFIRMED')
    else:
        _update(trade_id, confirmation_state='PENDING_CONFIRMATION')   # never COUNTED
    return fc
```

## 4. Closing the two phantom holes

**Hole A — `proposal_approved` symbol-match promotion** (`alpaca_paper_adapter.py:151`).
Today: `WHERE symbol=%s AND status='pending'` → promotes a pending row against *any* same-symbol
position, dropping the order id.
Fix: promotion is **order-anchored** — a pending row is promoted only when
`adapter.confirm_fill(its_own client/broker order id)` confirms. A pending row with no order id
(never actually submitted) **cannot** be promoted by a position sync. Matching key = the order id,
not the symbol.

**Hole B — `alpaca_sync` broker-named silent write** (`alpaca_paper_adapter.py:178`).
Today: writes `open` from a position snapshot with `opened_via='alpaca_sync'`, no order id.
Fix: rename to a generic `broker_sync` that routes through the same gate. A sync-discovered
position must reconcile to a confirmed order or be explicitly quarantined as
`UNLINKED_BROKER_POSITION` — **never** silently counted. (This preserves the legitimate recovery
case like ANY #48, but as an explicitly-flagged unlinked state, not a clean `open`.)

**Hole C — exit-side FALSE phantom (IMPLEMENTED 2026-07-08).** The mirror of A/B: `paper_trade_monitor.py`
voided any DB-open trade whose symbol wasn't in the *current* Alpaca positions snapshot as
`phantom_no_alpaca_position` (P&L=0) **without checking whether the entry order filled**. A position that
filled and then legitimately closed on the broker (its OCO stop/target leg filled) is no longer in the
positions list → it was wrongly booked as a never-existed phantom, voiding real P&L. This surged to 57% of
closes the week of 2026-07-06 (5 trades incl. an AGNC **+$298.86 target win** buried as $0; +$265.45 net
recovered). Root of the surge: the monitor's frequent phantom sweep races ahead of the hourly
`alpaca_paper_adapter.detect_closed_positions` (the proper exit recorder, `WHERE status='open'`), closing the
trade first so the recorder never sees it.
Fix: `_reconcile_broker_exit()` classifies from broker truth before any void —
- entry order **not filled** → `phantom` (void to $0, legacy behavior, correct);
- entry filled + an OCO exit leg filled → `reconciled` — book the REAL exit price / P&L / verdict
  (`broker_stop_hit_reconciled` / `broker_target_hit_reconciled` — canonical `stop_hit`/`target_hit`
  substrings so the journal/postmortem classifiers auto-tag the exit correctly);
- entry filled but exit **not yet resolvable** → `filled_no_exit` — **leave open** (never void a filled
  position); the hourly adapter close-sync reconciles it.
Wired into **both** phantom paths (`_fix_integrity_issues` Fix 2 and the `monitor()` loop). The 5 historical
false-phantoms were backfill-corrected and their journal thesis-reviews regenerated to real WIN/LOSS.

## 5. Two-source verification (TradeAI + Hermes)

```python
# TradeAI verification — independent re-query (read-only)
def trade_ai_verify(trade):
    adapter = adapter_for(trade['account'])
    s = adapter.get_order_status(trade['broker_order_id'])
    ok = s.confirmed and qty_matches(s, trade) and price_matches(s, trade)
    stamp(trade['id'], fill_verified_by='tradeai', fill_verified_at=now(), fill_verified_ok=ok)
    return ok
```

Hermes re-verifies **independently and read-only**, writing its verdict to a NEW staging table
`hermes_fill_verifications` — it **never** mutates `paper_trades` (challenger-wall intact):

```sql
CREATE TABLE hermes_fill_verifications (
    paper_trade_id bigint, broker text, broker_order_id text,
    hermes_confirmed boolean, qty_match boolean, price_match boolean,
    verdict text, checked_at timestamptz DEFAULT now()
);
```

## 6. The COUNTED rule (the gate's input — change NOT applied yet)

A trade counts toward win-rate / live-trading-gate **only if all hold**:
1. `broker_order_id` is non-null, **and**
2. `adapter.confirm_fill` confirmed it filled, **and**
3. TradeAI verified (order exists, qty/price match), **and**
4. Hermes independently verified (both agree).

Otherwise → `confirmation_state ∈ {PENDING_CONFIRMATION, UNLINKED_BROKER_POSITION, QUARANTINED}`
and is **excluded** from the metric. This is principled exclusion: *only count broker-proven
fills* — not "drop trades that look bad."

## 7. Schema delta (additive, additive only — not applied in this pass)

Generic columns that **already exist** and are reused: `broker`, `broker_order_id`,
`broker_status`, `broker_submitted_at`, `broker_filled_at`, `client_order_id`,
`broker_confirmed`.

New (additive, nullable — no rewrite of existing rows):
- `paper_trades.confirmation_state text` (`BROKER_CONFIRMED | PENDING_CONFIRMATION |
  UNLINKED_BROKER_POSITION | QUARANTINED`)
- `paper_trades.fill_verified_by text`, `fill_verified_at timestamptz`, `fill_verified_ok boolean`
- new table `hermes_fill_verifications` (above)

## 8. Agnosticism proof obligations (to verify when built)

- `broker_adapter.py`, `broker_confirmation_gate.py`, and the verification logic contain **zero**
  `"alpaca"` string literals — grep-asserted in the test.
- `"alpaca"` appears only in `alpaca_paper_adapter.py` (the implementation).
- `broker_name` is stored in the existing generic `broker` column; no vendor-named columns added.

## 9. STEP 2 test plan (paper, on approval)

1. Run a paper trade through `confirm_and_finalize` end-to-end: submit → confirm via interface →
   TradeAI verify → Hermes verify → row stamped `BROKER_CONFIRMED`.
2. Replay the 8 historical phantoms through the verifier: assert each is flagged
   unconfirmed/quarantine (no `broker_order_id` → fails rule 1).
3. Report before/after win rate (should move 45.8% → ~58.3% as unconfirmed rows leave the
   denominator) — **computed, not applied** to the gate until approved.
4. Grep-assert zero `"alpaca"` literals in gate/verification files.

## What stays untouched in this pass
- Live execution path (`proposal_paper_submitter.py`), the symbol-match promotion, and the gate's
  counting logic are **NOT modified**. Only this design doc exists so far.
- Live book is clean (3/4 open positions fully order-linked; ANY #48 is the one real-but-unlinked
  recovery) — no open position is touched by any of this.
