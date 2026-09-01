# Validation Checklist — 4-Layer Stop Policy Enforcement

Status:      ACTIVE
as_of:       2026-07-02T18:53:06-04:00
Measured at: efcc51365 / not measured

Use this checklist to prove the swarm correctly enforces policy before 4.4 → 4.5 gate.

---

## Layer 1 — Initial Hard Stop

- [ ] Entry Validation rejects trades with `initial_risk_r > 1.2`
- [ ] Structure+ATR hybrid computed for long AND short (symmetric)
- [ ] Pure scalp (< 45s freshness) uses 0.8–1.0× ATR band
- [ ] Social Route allows up to 1.5–2.0× ATR
- [ ] Journal tags: `initial_stop_method`, `initial_stop_atr`, `dollar_risk`

**Test:** Submit signal with 1.5R risk → expect rejection with §3 L1 citation.

---

## Layer 2 — Mandatory Breakeven

- [ ] Live Monitor amber alert when +1.2R and `breakeven_secured=false`
- [ ] Orchestrator blocks stop adjustments that leave risk after BE trigger
- [ ] Long: stop moved to ≥ entry; Short: stop moved to ≤ entry
- [ ] Social high-conviction delay to +2.0R only when tagged

**Test:** Paper trade at +1.3R with stop below entry → expect `propose_breakeven` in pending_approvals.

---

## Layer 3 — Trailing (Advisory Only)

- [ ] No automatic trail execution (YAML `layer3_trailing.enabled: false`)
- [ ] Amber alert when >+2R and trail not active
- [ ] Trail multiplier table respected in suggestions (not execution)
- [ ] Replay computes what trail *would* have done

**Test:** Confirm `tighten_all` and stop adjustments never activate Chandelier without approval.

---

## Layer 4 — Dynamic Adjustments

- [ ] Regime shift Trending→Ranging triggers 0.5× ATR tighten suggestion
- [ ] Portfolio heat > 3.5% → pause new entries + tighten-all available
- [ ] Portfolio heat > 4.5% → kill switch + red alert
- [ ] Freshness > 90s + no +0.8R → force breakeven red alert
- [ ] Every adjustment logged in `stop_adjustment_history.json` with policy §

**Test:** Simulate regime shift in `symbol_regime_state.json` → verify amber route to Stop Adjustment.

---

## Dynamic Stoplight Thresholds

- [ ] Yellow/Amber/Red thresholds vary by regime (`stoplight_regime_thresholds.py`)
- [ ] Stop Management UI shows `stoplight_thresholds_used`
- [ ] Ranging regime uses tighter Y/A/R than strong_trending_bull

**Test:** Compare thresholds for ranging vs trending symbol in API response.

---

## Long/Short Symmetry

- [ ] Short stop above swing high + ATR (mirror of long)
- [ ] Short breakeven: stop ≤ entry when +1.2R
- [ ] Short trail: Lowest Low + ATR × mult (advisory)
- [ ] Regime scoring uses `direction` parameter

**Test:** Run monitor on open short paper trade — verify symmetric R calculations.

---

## Human-in-the-Loop

- [ ] New entry requires Telegram approval
- [ ] Stop adjustment requires Telegram approval
- [ ] Exit requires Telegram approval
- [ ] Audit log captures approve/reject with operator ID

---

## Integration Smoke Tests

```bash
# Live monitor once
.venv/bin/python3 scripts/hermes_scalp_live_monitor.py --once

# Orchestrator once
.venv/bin/python3 scripts/hermes_scalp_orchestrator.py --once --json

# API status
curl -s http://127.0.0.1:7777/api/v2/hermes/scalp-swarm/status | python3 -m json.tool

# Validation tracker
.venv/bin/python3 scripts/scalp_stop_validation_tracker.py
```

---

## Gate Metrics (§6)

Track via `validation_tracker.json` + `scalp_stop_validation_tracker.py`:

| Metric | Target |
|--------|--------|
| Closed paper trades | ≥ 150 |
| Social Route trades | ≥ 40 |
| Win Rate | ≥ 58% |
| Expectancy | ≥ +0.35R |
| Freshness compliance | ≥ 92% |
| Trail activation (+2R winners) | ≥ 85% |

Status: **INSUFFICIENT SAMPLE** until ≥ 150 closed trades.