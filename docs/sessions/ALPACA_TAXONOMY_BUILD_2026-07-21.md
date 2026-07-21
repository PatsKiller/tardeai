# Alpaca Multi-Account Taxonomy Build — R1–R5 Session Handoff

**Date:** 2026-07-21  
**Machine:** MS-01  
**Final HEAD:** `4fa3ba338bdd07526f5aae5222f906b6ebcf10cc` (tip of R1–R5 stack on `main`)

## Commits (phase)

| Phase | Commit | Notes |
|-------|--------|-------|
| P0 host-lock | `c9f31f6b` | stop/reconcile paper host assert |
| R1 registry | `91dc54a6` | Interlock → broker_accounts + parity log; Fidelity import historical |
| R2 credentials | `1edc3674` | Credential slots + factory |
| R3 migration | `484d9442` | Identity → tradeai_automated + DB backfill |
| R4 scaffolds | `9f2d7c20` | Live scaffolds + capability_gate |
| R5 docs/TV | `b148f094` | TV lanes + D1 doc ratification |
| R5 stamp | `4fa3ba33` | Handoff HEAD stamp |
| R5 | `docs(brokers): R5 …` | TV lanes + docs ratification |

## Operator decisions applied

- D1 keys: `tradeai_automated`, `alpaca_taxable_live`, `alpaca_ira_live`
- D2 slots: `ALPACA_PAPER_*`, `ALPACA_TAXABLE_*`, `ALPACA_IRA_*` (no live values written)
- D3 both live rows DISABLED
- D4 dual-read interlock; legacy `accounts` retained (R1b later)
- D5 hard label migration + backfill
- D6 TV Lane 1 doc + Lane 2 503 stub
- Risk: GitHub token rotation **deferred** (operator 2026-07-21)

## Fidelity flag-back (R1)

| Observation | Action taken |
|-------------|--------------|
| holdings.json: **zero Fidelity** keys; only schwab_* | ACATS-aligned |
| `broker_accounts.fidelity_rollover_ira` | Kept as `environment=import`, `is_enabled=false`, notes historical |
| `accounts.fidelity_401k` | Left in place; interlock aliases → fidelity_rollover_ira |
| **No row delete** without further operator confirm | Flag-back closed as non-destructive |

## Parity log

- Table: `interlock_parity_log`
- Monitor: `scripts/interlock_parity_monitor.py` (Telegram on disagreements)
- Expected early noise: fidelity_rollover_ira canonical=live (import) vs legacy miss; aliases reduce identity drift after R3

## Distinct-identity SQL proof (R3 post)

```
paper_trades.account: tradeai_automated + TOS_PAPER only (no ALPACA_PAPER)
paper_trades.broker: alpaca only
atm_decision_log.target_account: tradeai_automated + UNRESOLVED (no alpaca_paper)
```

Backup tables: `paper_trades_bak_r3_20260721`, `atm_decision_log_bak_r3_20260721`

## Interlock self-test (post R4) — rows verified live

`SELECT account_key, environment, is_enabled, api_read_enabled, api_write_enabled,
 credential_slot, live_arm_token IS NOT NULL AS armed FROM broker_accounts` (2026-07-21):

| account_key | env | is_enabled | r/w | slot | armed |
|-------------|-----|------------|-----|------|-------|
| alpaca_ira_live | live | f | f/f | ALPACA_IRA | f |
| alpaca_taxable_live | live | f | f/f | ALPACA_TAXABLE | f |
| tradeai_automated | paper | t | t/t | ALPACA_PAPER | f |
| (+ schwab×3 live, fidelity_rollover_ira import disabled) | | | | | |

R4 insert is **not** fiction — both live scaffolds exist. Blank `canonical_answer` in
parity log (if any) was pre-insert noise; post-row, canonical resolves to **live** and
interlock REFUSEs with gate-not-passed (not unknown).

- ALLOW: tradeai_automated, alpaca_paper (alias)
- REFUSE live schwab_* (policy off)
- REFUSE fidelity_* (import→live posture / gate)
- REFUSE alpaca_taxable_live / alpaca_ira_live (**live gate refuse**, rows present)
- REFUSE bogus

**FK note:** `proposal_account_routes.selected_account_id` → `broker_accounts` — proposal
routing already consumes the canonical registry (extra consumer vs original audit map).

**Arm CHECK scope:** Alpaca-only (`broker='alpaca'`); Schwab not covered (own pilot stack).

## Factory / credentials

- Paper → AlpacaPaperAdapter
- Live → NotImplementedError
- Slot host never from `ALPACA_BASE_URL` (unit tests)
- Stop/reconcile still host-locked (P0)

## TradingView

- Stub: `POST /api/v2/ingress/tradingview` → **503** when `TRADINGVIEW_INGRESS_ENABLED` unset
- Doc: `docs/brokers/tradingview-lanes.md`

## Explicit next sessions

1. **R1b** — remove interlock legacy fallback after 5–7 clean parity days  
2. **Live adapter** — only after keys + arm protocol + capabilities verified  
3. **TV exposure** — operator chooses Funnel/Tunnel/VPS; enable stub + HMAC  
4. **GitHub token rotation** — deferred risk  

## Holdings checks

Pre/post deploy steps held ~$1.25–1.26M / 36 positions (non-zero). No live orders.

## Docs

- `alpaca-live-accounts.md` (canonical live roadmap)
- `paca-accounts.md` → pointer stub
- `trading-environments.md` D1 names
- `tradingview-lanes.md`
- Audit findings updated for P0 row 1 remediations earlier
