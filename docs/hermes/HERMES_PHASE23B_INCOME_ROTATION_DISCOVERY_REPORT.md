# Hermes Phase 23B — Income-Rotation Source Discovery Report

**Date:** 2026-06-01
**Status:** COMPLETE — file output only, zero DB writes

## Queries Run (8/8)

| # | Query | Results |
|---|-------|---------|
| 1 | dividend growth ETF income portfolio 2026 SCHD alternatives | 15 |
| 2 | covered call ETF income risk JEPI JEPQ DIVO 2026 | 15 |
| 3 | short duration treasury ETF income ladder 2026 | 15 |
| 4 | preferred stock ETF income risk PFF 2026 | 15 |
| 5 | BDC income portfolio risk ARCC MAIN 2026 | 15 |
| 6 | REIT dividend ETF income risk VNQ 2026 | 15 |
| 7 | closed end fund income discount risk CEF 2026 | 15 |
| 8 | taxable vs IRA Roth income ETF placement tax efficiency | 15 |

## Results Summary

| Metric | Value |
|--------|-------|
| Total results | 120 |
| Unique URLs | 120 |
| Candidates (score >= 3.5) | 55 |
| Rejected (score < 3.5) | 65 |
| Income sleeves covered | 8 (all target sleeves + general + tax_placement) |

## Sleeve Coverage

| Sleeve | Sources Found | Yield Range | Best Account |
|--------|--------------|-------------|-------------|
| Dividend Growth | Multiple | 2.5–4% | Roth IRA |
| Covered Call | Multiple | 6–12% | Roth/IRA |
| Treasury/Bond | Multiple | 4.5–5.5% | Taxable |
| Preferred Stock | Multiple | 5–7% | IRA |
| REIT | Multiple | 3–6% | IRA/Roth |
| BDC | Multiple | 8–12% | IRA |
| CEF | Multiple | 6–10% | IRA/Roth |
| Tax Placement | Multiple | N/A | Depends |

## Output Files

All in `docs/hermes/phase23_income_rotation_discovery/`:
- income_source_candidates.json (55 candidates)
- rejected_sources.json
- income_sleeve_candidates.json (top 5 per sleeve)
- risk_tax_notes.json
- dry_run_summary.md

## Safety

- [x] DB writes: ZERO
- [x] Embeddings: ZERO
- [x] Promotions: ZERO
- [x] Trade recommendations: ZERO
- [x] Broker access: NONE
- [x] Proposal/journal mutations: ZERO

**Candidate for research/operator review only — not a trade recommendation.**
