# Situation Catalog v1 — FREEZE

**Status:** FROZEN for Grok Build Phase 2 (do not expand scope without operator re-freeze)  
**Date:** 2026-08-11  
**Branch baseline:** `feature/advisory-desk-v1`  
**Authority:** **READ_ONLY_ADVISORY only**

---

## Non-negotiable rules

1. Every field cited in a plan **must** come from Data Broker (or explicit `DATA_UNAVAILABLE`).  
2. **No invented** prices, targets, stops, or quantities.  
3. Output of a fired situation: one **action plan** (options + recommendation + risks + `revisit_at`) → notify CIO channel + action ledger.  
4. No broker/order/stop/2FA execution. No silent Schwab→Moomoo reroute.  
5. No second ranking system that fights Watch / Reentry desks.  
6. No WhatsApp until Telegram path proven.  
7. Desk 30-session promotion remains a **separate** gate (`NOT_PROMOTED` until operator promote).

---

## Shared plan schema (every situation → plan)

| Field | Type | Notes |
|---|---|---|
| `plan_id` | string | Stable id, e.g. `plan_<uuid12>` |
| `situation_type` | enum | `S1`…`S8` codes below |
| `symbols[]` | string[] | Uppercase |
| `status` | enum | `OPEN` \| `ACKNOWLEDGED` \| `SUPERSEDED` \| `EXPIRED` \| `DONE` |
| `options[]` | object[] | Each: `{ id, label, summary }` — advisory choices only |
| `recommendation` | string | One preferred option + why (evidence-bound) |
| `risks[]` | string[] | Counter-arguments / failure modes |
| `evidence_refs[]` | object[] | `{ domain, as_of, quality_state?, source_ref? }` |
| `linked_goal_ids[]` | string[] | From `CIOGoalStore` when applicable |
| `revisit_at` | ISO-8601 | Required |
| `owner_agent` | string | Primary owner (see catalog) |
| `cc_deep_links[]` | string[] | e.g. `/v3/watch`, `/v3/risk`, recovery routes |
| `authority` | const | Always `READ_ONLY_ADVISORY` |

**Fail-closed:** If a **critical** evidence domain for the situation is `STALE` / `UNAVAILABLE` / missing, emit plan with `status` blocked path or plan body that states `DATA_UNAVAILABLE` for that field — **never** fill with fabricated numbers.

---

## Situation catalog

### S1 — `POSITION_LIFECYCLE`

| | |
|---|---|
| **When** | Held symbol with material path change: deep drawdown from basis, partial recovery, basis reclaim, or major catalyst (earnings/lockup) while held. |
| **Evidence pack** | `holdings_detail`, cost_basis/lots, `market_quote`, `analyst_rollup`, `catalyst_record`, `risk_snapshot` (stop), optional technicals + Hermes note. |
| **Example output** | “You hold X; basis ~$B; last ~$L; Street mean target ~$T. Options: hold; hold + stop-above-BE once last ≥ basis; trim. Recommend … Revisit …” |
| **Owner** | Alex (+ Morgan if behavioral/concentration). |

### S2 — `STOP_GAP`

| | |
|---|---|
| **When** | Held name with no stop, or stop clearly inconsistent with basis/policy (e.g. still deep underwater stop after recovery toward basis). |
| **Evidence** | holdings, cost_basis, risk_snapshot/stop policy, quote. |
| **Example** | “Last ≥ basis and no protective stop above break-even — advisory: place stop above BE, not at BE.” |
| **Owner** | Alex + risk/Guardian path. |

### S3 — `REENTRY_CANDIDATE`

| | |
|---|---|
| **When** | Recovery/reentry desk says READY or NEAR for a stopped-out name. |
| **Evidence** | `reentry_decision_desk`, scorecard, quote, catalyst, prior stop context. |
| **Owner** | Alex (+ Steph for sizing/allocation framing). |
| **Note** | Does **not** create broker orders; surfaces plan only. |

### S4 — `SECTOR_ROTATION`

| | |
|---|---|
| **When** | Material change in `sector_momentum` / `rotation_ladders` affecting sectors you hold or are underweight. |
| **Evidence** | sectors, rotation_ladders, holdings weights, correlation if available. |
| **Owner** | Steph + Alex. |

### S5 — `CASH_DEPLOYMENT`

| | |
|---|---|
| **When** | Cash/buying-power above policy band **and** constructive rotation or cluster of watch READY/GO in a sector. |
| **Evidence** | cash/buying_power (mark PARTIAL if soft), rotation, watch_intelligence sample, risk heat. |
| **Owner** | Steph + Alex. |
| **Language** | Staged deployment options + explicit exit/revisit if momentum fades — **never** “buy now” execution. |

### S6 — `CONCENTRATION_OR_DISPOSITION`

| | |
|---|---|
| **When** | Weight too high, or long-held material loser (disposition Rule 1 class). |
| **Evidence** | holdings weights, cost_basis, P&L, behavioral flags, goals. |
| **Owner** | **Morgan** primary; Alex synthesizes. |

### S7 — `WATCH_PROMOTION`

| | |
|---|---|
| **When** | Watch Intelligence READY/GO (or strong NEAR) on symbol not held, or held with new catalyst/Street shift. |
| **Evidence** | watch_intelligence, analyst_rollup, catalyst, holdings membership. |
| **Owner** | Watch/Maria evidence → Alex synthesis. |

### S8 — `DEFENSIVE_REGIME`

| | |
|---|---|
| **When** | Regime risk-off, portfolio heat up, or defensive desk proposals material. |
| **Evidence** | risk_regime, risk_snapshot, defensive/proposal surfaces, stops coverage. |
| **Owner** | Alex + risk. |

---

## Acceptance fixture (build this first)

**Name:** SpaceX-class mock (synthetic fixture — not live broker data)

| Field | Fixture value |
|---|---|
| Symbol | e.g. `SPACEX_MOCK` / held test symbol |
| Basis | **210** |
| Trough | **108** |
| Last | **138** |
| Street mean target | **200+** (from fixture analyst_rollup only) |
| Catalysts | lockup + earnings present in catalyst_record |
| Stop | **none** above break-even |

**Must emit:** **S1 and/or S2** plan that:

1. Mentions basis, last, target **only from fixture evidence**  
2. Mentions reclaim / stop-above-BE option  
3. Includes `evidence_refs[]` with domain + as_of  
4. Contains **zero invented numbers**  
5. Sets `revisit_at` and `owner_agent`  

---

## Explicit non-goals in v1

- No auto orders/stops  
- No silent Schwab→Moomoo reroute  
- No second ranking system that fights Watch/Reentry desks  
- No WhatsApp until Telegram path proven  
- Desk 30-session promotion remains separate  

---

## Implementation boundary for next Grok Build slice

**In scope (Catalog v1 slice only):**

1. Plan object schema (typed + JSON validation)  
2. Situation detector **skeleton** (register S1–S8; implement fixture path for S1/S2 first)  
3. Fixture test: SpaceX-class mock → S1/S2 plan pass  
4. Wire plan → action ledger / notify path **shadow-safe** (no live spam without flag)

**Out of scope for that slice:**

- Full multi-situation production detectors for S3–S8  
- P0 deploy of whole branch (operator step: deploy `feature/advisory-desk-v1` to timer host first if not already)  
- Promotion gate changes  
- WhatsApp / Moomoo write paths  

---

## Related docs

| Doc | Role |
|---|---|
| [AUTONOMY_GOAL_THESIS_COMPLETE.md](./AUTONOMY_GOAL_THESIS_COMPLETE.md) | Goals + dispatcher |
| [RUNTIME_TRUTH_2026-08-11.md](./RUNTIME_TRUTH_2026-08-11.md) | Host unit truth |
| [AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md](./AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md) | Brains vs timers |
| [PHASE7_PROMOTION_OUTCOME_2026-08-11.md](./PHASE7_PROMOTION_OUTCOME_2026-08-11.md) | Desk promotion (separate) |

---

*Freeze complete. Unfreeze only with operator revision + new dated freeze doc.*
