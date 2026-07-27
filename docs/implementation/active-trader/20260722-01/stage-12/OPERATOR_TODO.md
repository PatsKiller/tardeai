# Operator TODO — after Stage 12 (CONDITIONAL_PASS)

**Run:** 20260722-01 · **Date:** 2026-07-23 · PR #150 (draft, do not merge)

Stage 12 litmus = **CONDITIONAL_PASS**. Open operator actions, in order:

1. **Build + check in the Stage 5 observation launcher** (prerequisite for C1/C2). Needs continuous
   07:00–10:05 ET runtime, P1–R2 window segmentation, extended-hours K_1M/TICKER (`Session.ALL`), full
   Level 2 suitability metrics, WAL/Parquet/replay, three-verdict output — plus an exchange-calendar
   source. See `STAGE5_RESUME_REQUIREMENTS.md`. (This is its own authorized build transaction.)
2. **Run the ≥30-min continuous open-session capture** (C1), then the **five-RTH observation** (C2, 0/5),
   then judge **premarket Level 2 suitability** (C3).
3. **Stage 9 scored-fire corpus** (C4) — reach required promotion evidence incl. the ≥60-sample floor
   where the controlling program requires it. Then **Stage 10 promotion review** (C5).
4. **BF-1** (C6) — obtain the affirmative broker-resident-protection (OpenD-down trigger) proof before any
   Moomoo live canary.
5. **Stage 14** (C7) — issue a NEW exact-SHA owner authorization when C1–C6 are green. Do not merge PR #150
   before then.

## Non-blocking
- Doc-precision item (D3): restate the "no real 2FA" invariant to distinguish order/trade 2FA (none wired)
  from one-time data-gateway *device* authorization (the only real 2FA present).

Prior Stage-0 operator items are retained in the run-level `OPERATOR_TODO.md`.
