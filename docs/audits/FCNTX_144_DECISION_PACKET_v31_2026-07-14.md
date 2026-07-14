# FCNTX event #144 — operator decision packet (version-bound)

**BOUND TO plan version 31** · generated 2026-07-14T17:00:43.365626+00:00 · generator `phase_b_2.0.0` ·
decision policy `decision_1.1.0` ·
regime basis `risk_off` · **advisory only — this desk places no orders.**
If the workstation shows a different plan version, REGENERATE this packet before relying on it.

## Event
Sold **FCNTX** in `schwab_rollover_ira` on 2026-07-14; net proceeds $107,023.01; settlement `verified`.
Capital ledger: account visible cash $149,252.68, open claims $127,825.23, allocatable $149,252.68; this event: `claim_within_capital`.

## System recommendation
**DECISIVE**

**Primary: Plan F** — destination **Plan B**,
implementation **staged** (score 73.6).
Staged implementation of the Plan B destination — the current regime is risk-off and entry risk is elevated

| Amount | Value |
|---|---|
| Ultimate target | $25,380.43 |
| Implement now (stage-1) | $3,264.29 |
| Pending future stages | $20,801.22 |
| Uncommitted cash | $103,758.72 |
| Reserve | $81,094.50 |
| Whole-share residual | $548.08 |

Reconciliation: legs $25,380.43 + reserve
$81,094.50 + residual $548.08
= $107,023.01 vs deployable $107,023.01
→ reconciles: **True**.

Income: plan $3,484.08/yr · vs post-sale
$3,484.08 (post-sale baseline = uninvested cash (sweep yield not modeled → $0)) · vs pre-sale
$-1,085.80 (pre-sale baseline = sold fund trailing distributions).

Destination restoration: capped 84.4% · over-restoration
$0.00 · unrestored $16,706.41 · tracking error
$16,706.41.

| Leg | Role | Dollars | Shares |
|---|---|---:|---:|
| QQQ | sector_restoration:Technology | $6,482.61 | 9 |
| XLC | sector_restoration:Communication Services | $5,803.98 | 52 |
| XLF | sector_restoration:Financial Services | $3,994.46 | 71 |
| XLY | sector_restoration:Consumer Cyclical | $2,662.25 | 23 |
| XLI | sector_restoration:Industrials | $1,983.85 | 11 |
| XLV | sector_restoration:Healthcare | $632.64 | 4 |
| AGG | fixed_income_ballast | $3,820.64 | 39 |
| BIL | cash_reserve | $81,094.50 | 886 |

## Scoreboard
F 73.6 · B 61.1 · C 53.9 · G 47.4 · E 46.4 · D 45.5 · A 42.7

Why primary: sold exposure restoration: restores 84% of removed sector dollars (deployed share included); diversification overlap: 7 legs, 1 overlap flags; fees efficiency: weighted ER 0.116% on invested sleeve

### Alternatives
- Plan B (score 61.1): choose when reducing single-fund/manager concentration matters more than tracking the sold mandate closely
- Plan C (score 53.9): choose when current income is more important than full upside participation

### Do not choose
- Plan E: addresses portfolio gaps but does not replace the sold mandate — never a substitute for the sold exposure on a major sale
- Plan D: concentration caps violated: AGG 70% exceeds the single-ETF cap 45%

## Governance
Oversight (latest runs): chatgpt: needs_review (2026-07-14 12:48); grok: pass (2026-07-14 12:48); chatgpt: pass (2026-07-14 12:48); grok: pass (2026-07-14 12:48). Readiness:
ANALYTICS READY — OVERSIGHT PENDING. Audit lineage rows: 74.
Pending oversight is NOT operator-ready; adjudicate the lanes to proceed.
