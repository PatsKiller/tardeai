# Defensive Lean — Directive Review

**Review date:** 2026-07-24
**Directive set:** 2026-07-18 (commit `2840816f`, `defense-v8.6`)
**Config location:** `config/defense_recommendations.json` → `rotation_pairs.defensive_lean`
**Status:** `enabled: true` — **UNCHANGED BY THIS REVIEW**

> This document is analysis only. **No live directive or configuration was modified.**
> The decision field at the bottom is **PENDING OPERATOR APPROVAL**.

---

## 1. The original directive and its evidence

Set by operator on 2026-07-18 per the 5-seat oversight panel. Verbatim attribution from
config:

> `"operator, per the 5-seat oversight panel 2026-07-18 (opus/gpt-5.4: 'defensive rotation,
> not risk-on broadening — equal>cap may be a distribution tell')"`

Mechanics as committed:

| Element | Setting |
|---|---|
| Defensive destinations | `Utilities`, `Consumer Staples`, `Healthcare` |
| Cyclical destinations | **EXCLUDED** — XLE legs cut |
| Income destination | `SCHD` allowed |
| Cash | Takes the remainder as an explicit position |
| Single-destination cap | 50% (XLU pile-up guard) |
| TRIM-WATCH `on_trigger` | → XLU / XLP / XLV **if LEADING and underweight** · else SCHD · else cash |
| Revoke condition | `"set enabled=false when the tape confirms risk-on broadening (breadth + small caps + NH/NL)"` |

The original reasoning rested on an **equal-weight > cap-weight** reading being a
distribution tell rather than healthy broadening.

---

## 2. Current evidence (board of 2026-07-23, the latest complete session)

| Sector | State | RS20 | Breadth |
|---|---|---:|---:|
| Energy | **LEADING** | **+10.26** | 79% |
| Financials | **LEADING** | +3.30 | 48% |
| Healthcare | WEAKENING | +3.52 | 45% |
| RSP−SPY (equal vs cap) | WEAKENING | +0.28 | — |
| Consumer Staples | LAGGING | −0.17 | 49% |
| Utilities | LAGGING | −1.59 | 51% |
| Industrials | LAGGING | −2.22 | 34% |
| IWM−SPY (small caps) | LAGGING | −2.67 | — |
| Technology | IMPROVING | −3.22 | 19% |
| Communications | LAGGING | −3.31 | 29% |
| Materials | LAGGING | −4.21 | 61% |
| Consumer Discretionary | LAGGING | −4.96 | 44% |
| VUG−VTV (growth vs value) | LAGGING | −6.04 | — |

Directive age check (`directive_review`, 5-day SLA):
`{"review_due": true, "age_days": 6, "action": "operator_re_adjudication_required", "auto_revoke": false}`

---

## 3. Conflicts

### C-1 — Every defensive destination is now LAGGING or WEAKENING

The directive routes capital to Utilities, Consumer Staples and Healthcare. **None of the
three is LEADING.** Utilities (−1.59) and Consumer Staples (−0.17) are LAGGING; Healthcare
is WEAKENING.

Operational consequence: the TRIM-WATCH `on_trigger` rule sends money to XLU/XLP/XLV **only
if LEADING and underweight**. With none LEADING, that branch cannot fire, so triggered trims
currently fall through to **SCHD, then cash**. The lean is, in practice, already operating
as a cash-and-income directive rather than a defensive-sector rotation. That is a material
drift from what the directive appears to say, and it happened through the evidence moving,
not through any config change.

### C-2 — The single strongest sector on the board is the one the directive excludes

Energy is LEADING at **RS20 +10.26 with 79% breadth** — the strongest reading on the board
by a wide margin, and the only sector combining leadership with broad participation. The
directive explicitly cut the XLE legs. Financials, also excluded as cyclical, is the other
LEADING sector.

This does **not** by itself invalidate the directive: a defensive directive is *supposed* to
forgo cyclical strength. It is recorded because the cost of the directive is now concrete
and large, rather than hypothetical as it was on 2026-07-18.

### C-3 — The revoke condition partly depends on a signal that cannot measure breadth

The revoke test is `breadth + small caps + NH/NL`. The data-quality tranche in PR #168
establishes that the `market_movers` NH/NL feed is a **capped top-movers sample of exactly
15 rows per signal** — it is structurally incapable of measuring exchange-wide new
highs/lows. One-third of the directive's own revocation test therefore rests on a signal
that cannot answer the question asked of it.

This is a **defect in the revoke condition, not in the directive's premise**, and it must be
repaired regardless of which option below is chosen.

### C-4 — The original "equal > cap" tell has softened but not reversed

RSP−SPY is WEAKENING at **+0.28** — still positive, so equal-weight is still marginally
ahead of cap-weight, but far weaker than a decisive distribution signal. The premise is
neither confirmed nor refuted by current evidence.

---

## 4. Is the revoke condition met?

**No — on the two components that can be measured.**

| Component | Reading | Confirms risk-on broadening? |
|---|---|---|
| Breadth | Tech 19%, Comms 29%, Industrials 34%; only Energy strong at 79% | **No** — narrow, not broadening |
| Small caps | IWM−SPY **LAGGING**, RS20 −2.67 | **No** |
| NH/NL | Capped 15-row sample | **Cannot be evaluated** (C-3) |

The tape has **not** confirmed risk-on broadening. On its own terms the directive should
**not** be revoked today. The tension is not that the defensive stance is wrong — it is that
the chosen defensive *destinations* have stopped working while the stance remains right.

---

## 5. Portfolio exposure constraints

Constraints that bound any change (from `config/defense_recommendations.json`):
`neutral_sector_weight_pct`, `underweight_floor_pct`, `overweight_alert_pct`,
`max_single_destination_pct: 50`.

Position-level exposure is deliberately **not** reproduced in this document — it is
operator-sensitive and not required to adjudicate the directive. The 50% single-destination
cap remains appropriate under every option below and is not proposed for change.

---

## 6. Arguments

### To retain
1. The revoke condition is **not met** on either measurable component (§4).
2. Small-cap leadership is absent — IWM−SPY LAGGING is the classic non-confirmation.
3. Breadth is narrow: three sectors under 35%. Leadership sits in one sector (Energy).
4. Changing a defensive stance *because defensives lagged* is performance-chasing — exactly
   the failure mode a dated, attributed, revocable directive exists to prevent.
5. Six days is a short life for a panel-set directive; C-1 may be noise.

### To relax
1. All three destinations are LAGGING/WEAKENING (C-1). A defensive lean whose destinations
   do not defend is not achieving its purpose.
2. The `on_trigger` branch is already unreachable, so behaviour has drifted to cash/SCHD
   without an explicit decision (C-1).
3. The excluded set contains the only genuinely strong sector on the board (C-2).
4. The revoke condition is partly unmeasurable (C-3), so waiting for it to be "met" may mean
   waiting on a test that cannot resolve.
5. The directive is **6 days old against a 5-day review SLA** — re-adjudication is due.

---

## 7. Options

| # | Option | What changes | What it costs |
|---|---|---|---|
| **A** | **Retain unchanged** | Nothing. Re-review at next SLA. | Destinations keep lagging; `on_trigger` stays unreachable; C-3 unrepaired. |
| **B** | **Narrow** | Keep the lean; drop Utilities and Consumer Staples as destinations while both are LAGGING; route to SCHD/cash explicitly rather than by fall-through. | Makes current behaviour explicit and honest. Reduces optionality if defensives turn. |
| **C** | **Expand eligible research sectors** | Keep the *allocation* lean defensive, but permit Energy/Financials back into **research and watch** scope only — no add authority. | Restores visibility to the strongest sector without loosening allocation. Risks presentation being read as permission. |
| **D** | **Retire** | Set `enabled: false`. | **Not supported by evidence** — the revoke condition is explicitly not met (§4). |

**Independent of A–D — repair required:** rewrite the revoke condition so it depends only on
measurable inputs. Suggested replacement, stated for operator consideration only:
*breadth (≥N sectors above X% on the exact 20-session calculation) + small-cap RS
(IWM−SPY not LAGGING)*, with NH/NL demoted to **corroborating evidence explicitly labelled
as a capped sample**.

### Analyst note (not a decision)
On the evidence assembled here, **B or C is better supported than A or D**: A leaves a known
unreachable branch and a broken revoke test in place, and D is directly contradicted by §4.
This ranking is offered as input, not as an approval, and it does not change any config.

---

## 8. What this review did **not** do

- Did **not** modify `config/defense_recommendations.json` or any live directive.
- Did **not** change `enabled`, destinations, caps or the revoke condition.
- Did **not** alter any recommendation, order, position or approval path.
- Did **not** activate any new methodology.

---

## 9. Operator decision

| Field | Value |
|---|---|
| **Decision** | *(unset)* |
| **Selected option** | *(A / B / C / D — unset)* |
| **Revoke-condition repair approved** | *(yes / no — unset)* |
| **Decided by** | *(unset)* |
| **Decision date** | *(unset)* |
| **Status** | **PENDING OPERATOR APPROVAL** |

---

*Evidence sources: `sector_momentum_state` (board of 2026-07-23), `market_movers` (capture of
2026-07-23), `config/defense_recommendations.json`, commit `2840816f`, and
`defense_data_quality.directive_review`. No broker, order or approval path was accessed.*
