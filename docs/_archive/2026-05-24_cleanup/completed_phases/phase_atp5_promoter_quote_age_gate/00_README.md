# ATP-5 — Incubator Promoter Quote-Age Gate

**Status:** COMPLETE

## Problem

The incubator promoter was creating Automated Trade Proposals from candidates with stale or never-checked quotes. HDSN was promoted with a 309.9h stale quote — the same class of problem that created SIF/NVST/DOC.

## Fix

1. **Pre-promotion readiness policy** (`pre_promotion_readiness_policy.py`) now checks quote age:
   - `quote_never_checked` → BLOCKED
   - `>168h` quote age → BLOCKED (hard expire)
   - Strategy-specific thresholds: momentum 15min, swing 4h, default 24h → WARNING
   - Gate version: `pre_promotion_v2_quote_age`

2. **Incubator promoter** now queries scan age and passes it to the gate before promotion.

## Gap Report

82 out of ~90 historical proposals would have been blocked by the quote-age gate. Only 8 had fresh-enough quotes (INGM, CODX, EVC, HIMX, EMBC, TLSI — all <24h).

## Tests

11/11 pass.
