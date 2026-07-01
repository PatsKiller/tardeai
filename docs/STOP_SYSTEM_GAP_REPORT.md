# Trade AI v12 — Stop System Alignment / Gap Report

**Date:** 2026-07-01
**Scope:** Alignment of the live stop system against `MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md` (v1.0)
and `STOP_METHODOLOGY.md`, plus the "build a full stop monitoring/alerting/management system" request.

---

## 0. The single most important thing: two DIFFERENT stop domains

Your request cited the momentum-scalp policy, but the **Stop Management tab you use is REAL HOLDINGS**.
These are governed by two separate policies and must not be conflated:

| Domain | Policy | Positions | Direction | Execution |
|---|---|---|---|---|
| **Real-account holdings** (SCHG, V, ARKQ, defense, income…) | `STOP_METHODOLOGY.md` | Core compounders / income / defense | **LONG only** | Live Schwab 2FA (working as of today) |
| **Momentum scalp + Social Route** | `MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md` | Fast intraday scalps | Long **and** short | **PAPER only** until maturity 4.5 |

**Consequence:** Long/Short symmetric UI treatment matters for the *scalp* domain (paper), not the real
holdings you're managing (all long). A `direction` tag was added to the holdings rows; it reads `long`
for every real position.

---

## 1. Momentum-scalp policy §8 — as-built status (verbatim reconciliation)

| Layer / Item | Policy status | Reality |
|---|---|---|
| L1 Initial hard stop (Structure+ATR hybrid, ≤1.2R) | ACTIVE | **DONE** — tags + YAML |
| L2 Breakeven (+1.0–1.5R, non-negotiable) | ACTIVE | **DONE** |
| **L3 Trailing (Chandelier/ATR)** | **config-OFF** | **DELIBERATELY OFF** — see §2 |
| L4 Dynamic (regime / heat / freshness) | ACTIVE (advisory) | **PARTIAL** — freshness + heat alerts live; **regime-shift auto-tighten + "Tighten All" one-click PENDING** |
| Journal tags (§5) | Done | **DONE** — `migrate_momentum_scalp_stop_tagging.py` |
| Validation tracker (§6) | Done | **DONE** — reads `INSUFFICIENT SAMPLE` (~3 of 150 closed) |
| AI Critique 4 stop questions | Done | **DONE** |

---

## 2. The biggest "gap" is actually a deliberate control — DO NOT close it

Your prompt asks to "implement and enforce" full trailing (Layer 3). **This must not be enabled.**
The system already tested it:

- `backtest_hybrid_stops.py --mode ctx` (2026-06-29): layered trailing = **−0.451R/trade** vs the
  no-trail baseline (ctx +0.645R vs baseline +1.096R). Higher win rate (40.9% vs 23.8%) but it
  **truncates the momentum fat right-tail** the edge depends on.
- 27-config param sweep (init-mult × activation × regime-multiplier): **0 passed**, best −0.13R.

Policy verdict (§2.1): L3 stays **config-OFF for execution**, computed/tagged/monitored in advisory only,
re-enabled **only** if the intraday micro-cap paper sample (≥150 trades) overturns the prior. Current
sample ≈ 3. **Enforcing L3 now would violate the policy and your own data.** Keep it advisory.

---

## 3. Shipped today (this session)

- **In-app 2FA stop execution fixed end-to-end** (was fully broken). Root cause: evidence-hash drift
  (wall-clock `generated_at` in the readiness hash → revalidation always mismatched). 5 commits on `main`.
  Verified live: V trailing + SCHG fixed placed via Command Center.
- **Live/manual TRAILING stops now display** as active in the table (were dropped as null-price).
- **Inline plain-English narrative + next-action + 2FA trade projection** on every Stop Management row,
  aligned to `STOP_METHODOLOGY.md`. Summary shows a top-3 "Next actions — what to do now" banner
  prioritized by real risk reduction.

Example (live): ARKQ — *"Your live stop \$112.97 sits below the advised \$121.97 — about \$900 MORE open
risk than the methodology recommends. → Tighten to \$121.97. Projection: open risk \$1,934→\$1,034."*

---

## 4. Genuine remaining gaps (prioritized, recommended next phase)

| # | Gap | Domain | Value | Recommendation |
|---|---|---|---|---|
| 1 | L4 **regime-shift auto-tighten** (Trending→Ranging → tighten 0.5×ATR) | Scalp (Risk tab) | Med | Build — it's ACTIVE per policy but only PARTIAL |
| 2 | **"Tighten All Trails"** one-click when heat > 3.5% | Scalp (Risk tab) | Med | Build — §8 item #4 PENDING |
| 3 | ATR-distance + **Trail-Tightness Score** in `ScalpStopMonitorCard` | Scalp (Risk tab) | Low-Med | Build — §4 metrics PARTIAL |
| 4 | Candlestick **`structure_type`** surfacing (engulfing_low, prev_bar_low…) | Scalp advisory | Low | Enhancement — hybrid already respects structure |
| 5 | Long/Short mirrored UI treatment | Scalp only | Low | N/A for real holdings (all long) |

**Note:** items 1–4 live in the **Risk tab / scalp paper domain**, not the real-holdings Stop Management
tab. They do not affect the real stops you place via 2FA.

---

## 5. Validation checklist (policy §6 + institutional)

- [ ] Open a +1.3R paper long → breakeven suggestion appears (L2). *Blocked: needs paper sample.*
- [ ] Simulate portfolio heat > 3.5% → global tighten + pause entries fires (L4 #2). *PENDING build.*
- [ ] AI Critique contains the 4 required stop-quality questions. **PASS.**
- [ ] Short scalp trailing mirrors long logic. *Scalp-domain; unverified (paper sample ~3).*
- [ ] Real-holding stop placed via 2FA shows LIVE BROKER STOP + narrative. **PASS (today).**
- [ ] 150+ closed paper trades, 95% CI lower bound on expectancy > 0, before L3 execution. **~3/150 — not met.**

---

## 6. Bottom line

The stop system is **largely built and now aligned**. The real-holdings execution path works. The one
thing your request asked for that we should **refuse** is enforcing Layer-3 trailing — the data killed it.
The concrete, high-value work remaining is the L4 automation (regime-shift tighten + tighten-all) on the
scalp Risk tab, which is genuinely pending. Recommend building that next; hold L3 in advisory until the
paper sample validates it.
