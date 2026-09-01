# Momentum Scalp Regime Detection Algorithm

Status:      ACTIVE
as_of:       2026-07-02T18:42:35-04:00
Measured at: efcc51365 / not measured

**Version:** 1.0 · **Effective:** 2026-07-02
**Policy:** [`MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md`](MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md) Layer 3 multiplier table + Layer 4
**Implementation:** `scripts/lib/momentum_scalp_regime.py` · `config/momentum_scalp_regime.yaml`

---

## 1. Purpose

Fast, per-symbol regime classification for **Stop Management** and Layer 4 dynamic adjustments. Designed for momentum/scalp responsiveness (intraday–daily bars), not slow macro models.

Outputs feed:
- Dynamic Yellow/Amber/Red distance thresholds (`stoplight_regime_thresholds.py`)
- Layer 4 **0.5× ATR tighten** on Trending → Ranging shift
- AI Trade Critique context (`regime`, `regime_at_entry`, `explanation`)

---

## 2. Regimes

| Regime ID | Label | Detection criteria (scoring) | Layer 3 trail band |
|-----------|-------|------------------------------|-------------------|
| `strong_trending_bull` | Strong Trending (Bull) | RVOL ≥ **1.8**, ADX ≥ **25**, bullish structure (HH/HL or price above SMA20+50) | 3.0–4.0× ATR |
| `strong_trending_bear` | Strong Trending (Bear) | Same with bearish structure / short | 3.0–4.0× ATR |
| `trending` | Trending (Normal) | ADX 20–25 or moderate trend score | 2.0–3.0× ATR |
| `ranging` | Ranging / Low Vol | ADX < **20**, RVOL ≤ **1.2**, tight MA stack | 1.0–1.5× ATR |
| `high_volatility` | High Vol / Event | ATR% expansion ≥ **25%**, gap ≥ 4%, or RVOL ≥ 3.5 | 1.5–2.5× ATR |
| `regime_shift` | Regime Shift (overlay) | Hysteresis-confirmed change from entry/prior regime | **Tighten 0.5× ATR** (Layer 4.1) |

---

## 3. Inputs

| Input | Source | Notes |
|-------|--------|-------|
| RVOL | `ticker_enrichment_cache.json` (Finviz) | Policy Strong Trending gate: 1.8 |
| ATR(14), ATR% | Finviz enrich + live price | Expansion vs 25% threshold |
| ADX(14) | Optional DB / computed | If missing: **MA-proxy** from SMA20/50/200 alignment |
| Structure | SMA stack % above/below | Bullish / bearish / neutral |
| Direction | Holdings qty sign | Long/short symmetry for scoring |

---

## 4. Scoring & decision tree

1. Score each base regime (0–5 points per rule).
2. Winner = highest score; **confidence** = winner / sum(scores) × 100.
3. **Hysteresis:** new regime must lead for **3 consecutive scans** AND confidence ≥ **60** before label flips (`symbol_regime_state.json`).
4. **Shift detection:** `regime_at_entry` ≠ `regime` after confirmed flip → `regime_shift_detected=true`.
5. **Layer 4 tighten:** Trending/Strong → Ranging ⇒ `trail_tighten_atr_mult=0.5`.

---

## 5. Default parameters

See `config/momentum_scalp_regime.yaml`. Rationale:
- RVOL 1.8 / ADX 25 — matches policy §3 multiplier table “Strong Trending (RVOL > 1.8)”.
- ADX 20 ranging — matches `stop_trailing_hybrid.yaml`.
- 3-bar hysteresis — prevents stoplight flicker on 60s management refresh.

---

## 6. Integration

| Consumer | Field |
|----------|-------|
| `/api/v2/stops/management` | `regime`, `regime_label`, `regime_shift_*`, `policy_suggestions` |
| Stop Management UI | Regime column, shift filter, policy panel |
| AI Critique | `regime_explanation`, `regime_at_entry` |

**API usage:**
```python
from momentum_scalp_regime import build_context_from_enrich, detect_regime
ctx = build_context_from_enrich(enrich_row, price=px, direction="long")
out = detect_regime("SMCI", ctx, project_root=PROJECT_ROOT)
```

---

## 7. Validation checklist

- [ ] RVOL 2.1, ADX 28, bullish MAs → `strong_trending_bull`, confidence > 60
- [ ] ADX 15, RVOL 0.9 → `ranging`
- [ ] ATR% 30, gap 5% → `high_volatility` or shift modifier
- [ ] 3 scans trending → ranging → `regime_shift_detected`, `trail_tighten_atr_mult=0.5`
- [ ] Layer 2 breakeven trigger unchanged regardless of regime