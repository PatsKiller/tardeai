# Re-entry R:R methodology (live system)

Status:      ACTIVE
as_of:       2026-08-12T10:17:19-04:00
Measured at: efcc51365 / not measured

**Source of truth:** [`scripts/lib/data_broker/reentry_decision_desk.py`](../../scripts/lib/data_broker/reentry_decision_desk.py) — deterministic, no LLM.
**Desk-note display filters:** [`scripts/lib/cio_desk_depth.py`](../../scripts/lib/cio_desk_depth.py) (`CORE_MIN_RR`, `MAX_SANE_RR`) — presentation/governance only; does **not** change READY/NEAR/BLOCK states.

---

## Primary formula (per symbol row)

Used when building each decision-desk row:

```text
if price and stop and target and price > stop:
    risk   = price - stop
    reward = target - price
    if risk > 0:
        R:R = round(reward / risk, 2)
```

| Input | Meaning |
|--------|---------|
| `price` | Live/last quote from Data Broker (`market_quote` batch) |
| `stop` | `stop_price` from `entry_plan` |
| `target` | `target_price` from `entry_plan` |

**Definition:**

\[
R:R = \frac{target - price}{price - stop}
\]

i.e. dollars of reward above **current** price per dollar of risk down to stop.

- Requires `price > stop` and `risk > 0`.
- Otherwise `R:R = null` (row cannot claim a numeric ratio).

---

## Zone-aware risk/reward bands (advisory card only)

In `build_advisory()`, the entry zone is also used for **display bands** (not the main row `rr`):

```text
entry_mid = (entry_low + entry_high) / 2   # if both present

risk_hi  ≈ entry_low  - stop    # if entry_low > stop
risk_lo  ≈ entry_high - stop    # if entry_high > stop
reward_lo ≈ target - entry_high
reward_hi ≈ target - entry_low
```

Sizing still uses:

```text
risk_per_share = entry_mid - stop   # when entry_mid > stop
shares ≈ (book × 1%) / risk_per_share
allocation capped at 10% of book
```

---

## Quality thresholds (how the desk *uses* R:R)

| Layer | Rule |
|--------|------|
| Decision-desk criterion `rr` | `met` if `R:R is not None and R:R >= 2.0` (preferred; 3:1 called “ideal” in label) |
| Desk note **core full** card (v1.2.2+) | Full card only if `CORE_MIN_RR (1.5) ≤ R:R ≤ MAX_SANE_RR (12)` |
| Sub-quality NEAR | `0 < R:R < 1.5` → collapsed summary line |
| Bad math | `R:R > 12` (or non-finite / missing) → suppress as data error |

So:

- **Engine truth:** R:R is always `(target − price) / (price − stop)`.
- **Setup quality gate inside reentry desk:** prefers **≥ 2:1**.
- **Operator-facing core filter (desk note):** floor **≥ 1.5** so weak NEARs don’t look equal to real reward/risk setups. (Raising `CORE_MIN_RR` to **2.0** would align display with the engine criterion without changing state labels.)

---

## What R:R is *not*

- Not distance to entry zone (`distance_pct`).
- Not RSI or MA alignment.
- Not portfolio-level risk.
- Not computed if stop or target is missing → no fake ratio.

---

## Implications for filtering

A name can be **NEAR ENTRY** (price near/inside zone + RSI band) and still have **R:R &lt; 1.5** if the plan’s target is tight vs stop relative to *current* price. That is why LMT/HPE-style rows can be “near” but poor reward/risk at the live print — correct behavior of this methodology, and why a **≥ 1.5** (or **≥ 2.0** to match the engine criterion) display floor is coherent.

### Layering (do not conflate)

```
reentry_decision_desk          → READY / NEAR / … + numeric rr (engine)
        ↓
cio_desk_depth (desk note)     → core_full / sub_rr / micro / dropped_bad_rr
        ↓
STAGE_0/1/2                    → cash / quality / opt-in (no execution)
```

---

## Related

- [DESK_NOTE.md](./DESK_NOTE.md) — section 5 re-entry book
- [ARCHITECTURE.md](./ARCHITECTURE.md) — Track A vs reentry desk composition
- [ROADMAP_GAPS.md](./ROADMAP_GAPS.md) — product depth notes
