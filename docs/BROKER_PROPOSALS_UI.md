# Broker Proposals UI — Live Execution Desk (v3)

Command Center → **Trading** → **Broker Proposals** tab (`BrokerProposals.tsx`).

Path B live queue for Schwab/Fidelity equity proposals promoted from the paper-agnostic queue.
See `docs/PROPOSAL_EXECUTION_PATHS.md` for the two-path model (Path A paper vs Path B live).

## Operator workflow

1. **Promote** from Proposals tab → row lands in Broker Proposals queue.
2. **Pick destination account** — Schwab (auto+2FA or manual) or Fidelity (FA manual only).
3. **Refresh prices** — live quote + thesis validity band + sizing recalc.
4. **Run oversight** — local agents (Maria/Risk/Steph) + optional **Grok+ChatGPT** cloud review.
5. **Execute** — Schwab **Auto route (2FA)** when armed, or place at broker and **Executed manually**.

## UI sections (per proposal card)

| Section | Purpose |
|---------|---------|
| **Thesis validity bar** | Visual drift gap — price band where entry zone + min R:R still hold (green/yellow/red) |
| **Account picker** | Grouped Schwab vs Fidelity; shows cash, open trades, daily slot usage |
| **Risk metrics** | Position, max risk, profit @ target, live R:R |
| **AI oversight** | Local review status, Grok/ChatGPT lane verdicts, consensus |
| **Actions** | Refresh prices · Edit trade · Executed manually · Auto route / Record |

## Account selection

| Broker | Modes | UI label |
|--------|-------|----------|
| **Schwab** | API auto (gated, per-order 2FA) **or** manual at Schwab.com | `Schwab — API auto (2FA) or manual` |
| **Fidelity** | Manual only — **Active Trader Pro (FA)** | `Fidelity — FA manual only` |

Changing account re-runs `evaluate-promote` sizing caps for that destination (cash, daily limits).

**Share sizing display:** The card always shows two numbers when they differ:

- **Queued** — `proposed_shares` saved on the proposal (often paper/promote sizing, e.g. 6,760 sh).
- **Cap for [account]** — max allowed for the selected Schwab/Fidelity account (e.g. 292 sh on rollover IRA cash).

Risk metrics show **at queued size** first, then **if resized to cap**. Use **✎ Edit trade** to persist the cap before routing live.

Thesis validity band uses entry/stop/target + live quote — **not** Grok/ChatGPT (cloud is a separate oversight step).

## Thesis validity / drift gap

Computed by `scripts/broker_thesis_validity.py` and attached to every broker queue row as `thesis_validity`.

- **Valid band** — intersection of strategy entry-zone drift (from `proposal_lifecycle`) and min R:R floor (default 2:1).
- **Zone status** — `comfortable` (green) · `approaching` (yellow) · `at_risk` / `invalid` (red).
- **Visual** — stop / entry / valid zone / target markers + live price dot on `ThesisValidityBar.tsx`.

## Refresh prices + recalibrate

**Per card:** `↻ Refresh prices`  
**Queue:** `↻ Refresh all prices`

```bash
curl -s -X POST http://localhost:7777/api/v2/broker-proposals/refresh-prices \
  -H 'Content-Type: application/json' \
  -d '{"proposal_id": 123, "account": "fidelity_rollover_ira"}' | python3 -m json.tool
```

On refresh:

1. Fetches live quote (`_broker_promote_quote` → Schwab transport or `market_quote_provider`).
2. Updates `paper_trade_proposals.current_price` and `price_drift_pct`.
3. Recomputes `thesis_validity`, broker sizing, gates, oversight snapshot.

## Cloud AI oversight (Grok + ChatGPT)

| Action | API |
|--------|-----|
| Queue local reviews | `POST /api/v2/broker-proposals/queue-oversight` |
| Run Grok+ChatGPT | `POST /api/v2/broker-proposals/run-cloud-oversight` |

Backend: `scripts/broker_promote_oversight.py` → `cloud_review.review()`.

- **DISAGREE** → oversight BLOCK (live route disabled until resolved).
- **CAUTION** → WARN (operator may proceed with eyes open).
- **AGREE** → PASS contribution toward promote-ready.
- Per-lane breakdown (Grok / ChatGPT verdict + assessment) shown in `BrokerIntelPanel`.

Requires local thesis text — run **AI Review** on the paper proposal first if cloud returns "No local thesis".

## Manual execution (closed loop)

**Executed manually** on any card → `ManualExecutionModal` → `POST /api/v2/executions/log-manual`.

Tagging + journal linkage: `scripts/manual_execution_tracker.py` (see `docs/OPTIONS_BROKER_EXECUTION_FLOWS.md`).

## API reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v2/broker-proposals` | GET | Fast queue list + accounts (detail lazy-loaded) |
| `/api/v2/broker-proposals/detail` | POST | Intel + sizing gates for one card |
| `/api/v2/broker-proposals/refresh-prices` | POST | Live quote + thesis band + recalibrated sizing |
| `/api/v2/broker-proposals/evaluate-promote` | POST | Account-preview sizing when destination changes |
| `/api/v2/broker-proposals/run-cloud-oversight` | POST | Grok+ChatGPT second opinion |
| `/api/v2/broker-proposals/queue-oversight` | POST | Queue Maria/Risk/Steph + local LLM |
| `/api/v2/broker-proposals/route` | POST | Schwab auto submit (gated) or Fidelity record-only |
| `/api/v2/executions/log-manual` | POST | Log manual fill + lineage |

## Code map

| Layer | Files |
|-------|-------|
| UI | `BrokerProposals.tsx`, `BrokerProposalCard.tsx`, `ThesisValidityBar.tsx`, `BrokerAccountPicker.tsx`, `BrokerIntelPanel.tsx` |
| Thesis math | `scripts/broker_thesis_validity.py` |
| Oversight | `scripts/broker_promote_oversight.py` |
| Sizing | `scripts/broker_promote_sizing.py` |
| API | `scripts/api_v2.py` — `_broker_proposals`, `_broker_refresh_prices`, `_enrich_broker_proposal_row` |
| Tests | `tests/test_broker_thesis_validity.py`, `tests/test_broker_promote_oversight.py` |

## Related docs

- `docs/PROPOSAL_EXECUTION_PATHS.md` — Path A vs Path B
- `docs/OPTIONS_BROKER_EXECUTION_FLOWS.md` — options desk + shared manual-log flow
- `docs/broker-promote-sizing.md` — cash-based sizing caps (if present)