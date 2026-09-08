# Phase F PASS architecture — m2-canary-20260907

Prepared: 2026-09-08T22:46Z  
Pin: `aaa9115cbc2745b34a6d0a48cbdbd012c0ac6816`  
Release: `aaa9115cb-main-exact-phase2-20260908-171709`  
Operator bar: **Stage-3 organic soak seal** (`OPERATOR_DECISIONS` Q9) + independent revalidation.

## 1. Honest PASS predicate

`INDEPENDENT_M2_ARCHITECT_PASS` only if **all** hold:

1. Identity triple agree (API / CURRENT / seal) on pin + release `171709`.
2. All **26 non-organic** prior blocking IDs adjudicated PASS (includes clearing `I-SCHEMA-V2` via DT-09).
3. Stage-3 soak archive (or equivalent collector READY) proves the **8 organic** IDs with real post-activate traces under `ORGANIC_ONLY`.
4. Controlled canary proofs (gateway SETTLED, inbound OK) remain labeled **non-organic** and do not pad research/commitment counts.
5. No manufacturing of organic rows; no PASS from hermetic-green alone.

Anything short of that is **FAIL** or **AWAITING** — not PASS.

## 2. Residual buckets (from Phase F prep)

| Bucket | Count | Action |
|---|---|---|
| A–D clearable | 25 | Re-probe live; write adjudication package |
| Non-organic residual | 1 (`I-SCHEMA-V2`) | Run disposable DT-09 apply+rollback |
| Needs organic E | 8 | Unblock path if broken; wait wall-clock; no invent |

## 3. Critical path tonight

```text
DT-09 disposable migration ──┐
A–D live adjudication ───────┼──► Phase F package (partial OK)
Organic path health fix ─────┤
Hourly feed@:55 / wake@:00 ──┴──► ≥3 known-trigger slots
                                   + research non-none
                                   + commitment create/eval
                                   └──► Stage-3 seal ──► full F PASS
```

Earliest honest 3-slot window (if cron healthy): ~23:00 / 00:00 / 01:00 UTC.  
Organic non-none + commitment remain **open-ended** under `ORGANIC_ONLY`.

## 4. What agents must fix vs wait

**Fix now (engineering):**
- `I-SCHEMA-V2` / DT-09 on disposable DB.
- Any bug preventing CURRENT-resolved feed/wake, known trigger provenance, or consumption with `effect_kind != none` when organic research exists.
- Collector false-negatives (e.g. missing `gateway_canary_delivery` despite SETTLED pmid 50986 in epoch window) if query/time-window bugs.
- Preserve canonical SETTLED gateway proof (already restored; overwrite guard added).

**Wait (cannot force):**
- Three consecutive post-activate known-trigger wakes.
- Organic research non-none / commitment create-eval appearing in nature.

**Forbidden:**
- Inserting fake organic commitment/research rows.
- Relabeling controlled canary as organic.
- Claiming PASS while Stage-3 unsealed.

## 5. Decision if organic stays dark

If after ≥48h post-activate (authority window) organic non-none never appears:
- Emit honest `M2_CANARY_SOAK_AWAITING` / F **FAIL** with residual E-IDs, **or**
- Operator may lock `CANARY_PATH_OK` only for path-proof (still does not pad Stage-3 organic seal per prior advice).

Default remains **ORGANIC_ONLY**.

## 6. Execution ownership

| Track | Owner |
|---|---|
| DT-09 | agent `DT-09 schema v2` |
| Organic path architecture/fix | agent `organic F blockers` |
| A–D adjudication + F package | parent after tracks return |
| Post-23:00 soak recheck | armed one-shot tick |

## 7. Organic detail

Per-ID waiting vs broken, code/ops fixes, and wall-clock limits:  
`evidence/phase_f_prep_20260908/ORGANIC_PASS_ARCHITECTURE.md` (2026-09-08T22:48Z).

## 8. Non-claim

This document is architecture only. It does **not** assert M2 PASS.
