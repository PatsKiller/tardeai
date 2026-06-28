# Trade AI — Maturity Score

_Generated: 2026-06-28T02:07:44.233618+00:00_
_Source: `python3 scripts/compute_maturity_score.py --json`_

## Result

- Raw weighted score: **4.95 / 5**
- Final maturity (after caps): **4.95 / 5**
- ✅ **4.5 MET**

The score is earned from machine-derived evidence and bounded by hard caps below — it is
never asserted. LLMs are advisory only and cannot affect any gate.

## Weighted breakdown

| Dimension | Weight | Score (0–1) | Points (of 5) |
|-----------|--------|-------------|---------------|
| Execution-state clarity | 0.10 | 1.00 | 0.500 |
| Central readiness resolver | 0.15 | 1.00 | 0.750 |
| Broker write safety | 0.15 | 1.00 | 0.750 |
| Operator approval evidence binding | 0.10 | 1.00 | 0.500 |
| Options hard-risk blocks | 0.10 | 1.00 | 0.500 |
| Kill switches | 0.08 | 1.00 | 0.400 |
| Broker lifecycle / reconciliation | 0.10 | 1.00 | 0.500 |
| Audit ledger | 0.08 | 1.00 | 0.400 |
| Release readiness | 0.10 | 0.90 | 0.450 |
| Post-trade methodology / critique loop | 0.04 | 1.00 | 0.200 |

## Caps applied

- None — no caps triggered.

## Evidence snapshot

| Signal | Value |
|--------|-------|
| Release status | `WARN_NON_LIVE_ADJACENT` |
| Schwab write policy | PASS (27/27 guards green) |
| No-broker-write-bypass test | PASS |
| Broker-write scanner | clean (0) |
| Central readiness resolver present | True |
| Autonomous live submit blocked | True |
| Per-order 2FA required | True |
| Live-adjacent dirty count | 0 |
| Unknown execution-state inspection | False |
| Kill switches inspectable | True |
| Unit tests passing | 8/8 |

*Autonomous live submit remains disabled. Operator-approved broker submit path is gated by
deterministic controls. Broker truth is authoritative after submit.*

