# Command Center — the mental model, verified (2026-08-29)

Status:      HISTORICAL
as_of:       2026-08-29T16:25:41-04:00
Measured at: efcc51365 / not measured

Command Center is **not** the plan warehouse. It is a **composition**
(`cio_command_center.py`) turning plans + capital-plan decisions + operator
product into `/v3/cio`. No LLM. No broker. Notify is a **render** of policy
decisions (`would_send: false`).

Each claim below was checked against the code. Three were true in design and
**false in production** — recorded at the end, because the failure mode is worth
more than the final numbers.

## Three different "plan" numbers

| Surface | What it counts | Typical size |
|---|---|---|
| **Warehouse** | `CIOPlanStore` open drafts/proposed | hundreds |
| **Coverage `with_plan`** | Open **S1/S3/S5/S6** ∩ **non-dust held** | names, not rows |
| **CIO NOW cards** | At most **5** decisions needing attention | 0–5 |

S0 and S7 do **not** count as position coverage —
`COVERAGE_PLAN_SITUATION_TYPES` (L867) lists exactly S1, S3, S5, S6. Dust does
not count as held. `accepted` is treated as **not open** (L152, same bucket as
cancelled/closed), which is why an accepted S0 TEST vanishes from "open" while
still existing.

## How a plan becomes a NOW card

```
position_decisions → sanitize_decisions_now → investment_pool
        → _investment_needs_attention?
             ACT_NOW / REVIEW / REVALIDATE / DATA_CONFLICT / STALE
             or act_now=true
             or concentration fire in risk text
             or TRIM/EXIT/ADD/RE_ENTER
             HOLD / WATCH / empty why → drop
        → sort: unblocked ACT_NOW, then urgency, then |delta|
        → cards[:5]                                    (L394)
```

**Correction to the model as written.** "TRIM/EXIT/ADD/RE_ENTER (even $0 delta —
still REVIEW)" is not quite the rule. L135 requires
`delta >= 0.01 **or** non_neutral` — a $0 delta paired with a *neutral*
`why_now` **drops**. The $0 case surfaces only when the why-text is
non-neutral.

**Freshness beats ACT_NOW.** Stale/conflict → `suppress_untrusted_sizing`
(L203) strips dollar deltas, targets and sizing prose; urgency caps at medium.
Risk text like "concentration > fire" is a **fact**, not an action.

`_action_hint` (L85) can show **Trim** on a formal Hold when `why_now` embeds
"TRIM — SCHD". Display semantics, not a broker order.

## Attention KPIs (disjoint on purpose)

Investment decisions · Workflow actions · Open plans · Material today —
material today is **not** the sum of the other three.

## Opportunities ≠ plans

Two pipes, not merged: queue chips (watch vs reentry), Surface A (former/EXITED),
Surface B (cash-stage, separate producer). `"merged": False` is pinned at
L1123/1143/1184. Watch **BLOCK** is a count, not a card; `fires_s7` is False
(`cio_investment_product` L952/1006).

## Notify block (Wave 3E)

Only `draft`/`proposed` rows reach `NotificationPolicy.decide`. Duplicate
`(situation_type, first symbol)` suppresses. Surfaced rows are
`COMMAND_CENTER_ONLY`, cap 10. `IMMEDIATE` is counted, never delivered. Every
row `would_send: false`, `producer: null`. Suppressed reasons are shown so a
handful of surfaced rows is credible against hundreds considered.

## What CC will not do

Walk ResearchNeedDecision, call Hermes, show 500 plans on NOW, merge the reentry
books, or send chat.

---

## What these numbers were actually reading

Three surfaces counted the wrong plan set. Same shape as the original
`with_plan=1` bug the model already describes.

**1. The notify block could never surface — introduced by me in #653.**
Pointing it at `_coverage_plan_index()` looked like the fix (full store instead
of the 12-row window). But that projection carried four fields and **not
`material`**, so `decide()` read it falsy and every row suppressed
`not_material`: **475 considered, 475 suppressed, 0 surfaced**. A count that
looks plausible while the surface can never show anything. Fixed by adding
`material` and `plan_id` to the projection — a projection that silently drops
the field a consumer branches on is worse than a short one.

**2. A suppressed row could shadow a real fire.** The dup slot was claimed
unconditionally, so the first `('S6…','AMANX')` row — `material: False` —
suppressed as `not_material` *and took the slot*, making a later material AMANX
fire suppress as `duplicate_subject`. A concentration fire disappeared on
iteration order. Only non-suppressed rows claim the slot now.

**3. `attention.open_plans` reported the window.** Live it read **12** against
458 open, while the model defines that KPI as the durable store. `build_cio_now`
now takes `all_open_plans` for the KPI; cards still come from the window and
stay capped at 5.

Six tests pin these, including that a genuine duplicate is still collapsed —
the fix must not disable the dedupe it was correcting.
