# Command Center v3 Trust Hardening + Rotation Intelligence

**Status:** Active implementation baseline  
**Date:** 2026-06-16  
**Scope:** Strategy intelligence, release discipline, metric trust, and advisory rotation intelligence  
**Safety posture:** Advisory and validation only. No new broker execution path.

## 1. Why this exists

Four areas were identified as blocking Command Center v3 from a 9/10 maturity rating:

1. Strategy / proposals / analyst-news card intelligence
2. Repo hygiene / release discipline
3. KPI / metric consistency and trust
4. Rotation intelligence: what to trim, add, rotate, or hold by account

The fourth item is the major product gap: the system can display rich data, but it also needs an account-aware capital-allocation engine that can answer questions such as:

- Should defense be trimmed and energy added?
- Should SpaceX/SPCX exposure be increased?
- Should that increase come from cash, taxable trim, Roth, rollover IRA, or a manual 401k ticket?
- What income, tax/account, concentration, and risk impacts follow?

## 2. Files added

| File | Purpose |
|---|---|
| `config/metric_registry.yaml` | Canonical registry for headline KPIs, scopes, denominators, owners, and stale thresholds |
| `scripts/validate_metric_consistency.py` | Scans registry and UI/source/docs for ambiguous KPI labels |
| `scripts/validate_symbol_card_quality.py` | Validates symbol-card coverage: profile, sector, analyst, news, freshness |
| `scripts/repo_hygiene_report.py` | Classifies dirty files by source/docs/generated/secrets/live-adjacent risk |
| `scripts/validate_release_readiness.py` | Aggregates release gate checks into PASS/WARN/FAIL |
| `migrations/20260616_rotation_intelligence.sql` | Advisory rotation tables: opportunities, pairs, evidence, decisions |
| `scripts/rotation_intelligence_engine.py` | Read-only advisory scoring engine for HOLD/ADD/TRIM/ROTATE review ideas |
| `docs/project/METRIC_DEFINITIONS.md` | Human-readable KPI definition and labeling rules |

## 3. Strategy / proposal intelligence target state

The symbol-card intelligence layer must mature from useful context into actionability scoring.

A 9/10 card has:

- company/fund description
- sector and sector-relative performance
- analyst consensus / target / upside when available
- top relevant news with source/date/sentiment
- strategy assignment and current strategy fit
- quote/news/analyst/profile freshness
- explicit quality status: `ACTIONABLE`, `WATCH`, `STALE`, `MISSING_DATA`, or `NO_EDGE`

Validation command:

```bash
python3 scripts/validate_symbol_card_quality.py --input /path/to/symbol_cards.json --json
```

Acceptance threshold: at least 95% of actionable cards have profile, sector, analyst, and recent news coverage, or they must be marked not actionable.

## 4. Repo hygiene target state

A 9/10 release process has:

- zero dirty live-broker or execution-adjacent files before release
- zero dirty secret/config files
- generated/runtime files ignored or classified
- Command Center build passing
- Schwab write-policy validator passing when present
- metric consistency validator passing
- release manifest produced before tagging

Commands:

```bash
python3 scripts/repo_hygiene_report.py --markdown
python3 scripts/validate_release_readiness.py --json
```

The release readiness script is intentionally conservative. It fails if live-broker/protective/approval-adjacent source files are dirty.

## 5. Metric trust target state

Metric trust means each KPI is scoped and denominator-aware. The system must not display a bare `WIN RATE` or ambiguous `LIVE BLOCKED` label when multiple meanings exist.

Examples:

```text
Journal win rate: 55.3% · 121 journal trades
Paper validation: 45.8% · 24 closed paper trades
Live trading: globally blocked
Protective stops: standing authorization active · 8 healthy
```

Validation command:

```bash
python3 scripts/validate_metric_consistency.py --strict
```

## 6. Rotation intelligence target state

Rotation intelligence is advisory. It produces human-reviewed ideas, not trades.

### Actions

- `HOLD`
- `ADD_REVIEW`
- `TRIM_REVIEW`
- `WATCH`
- `ROTATE_REVIEW`
- `WATCH_PAIR`

### Inputs

- current holdings and market value
- account key / account type
- sector exposure
- analyst upside/downside
- news or sentiment score
- protection / stop-health state
- income yield
- concentration percentage

### Account handling

| Account type | Policy |
|---|---|
| Taxable | trimming requires tax-impact review; prefer cash/add-first where possible |
| Roth IRA | preferred home for high-upside long-duration growth when risk budget allows |
| Rollover IRA | supports growth/income rotation but monitor concentration and future RMD/IRMAA context |
| 401k/manual | advisory ticket only; do not assume API trading |

### Example outputs

```text
TRIM_REVIEW: overweight defense holding, negative relative upside, unprotected or near stop
ADD_REVIEW: high-upside growth candidate, positive news, good account fit
ROTATE_REVIEW: review partial source->destination shift with amount range and rationale
```

Run:

```bash
python3 scripts/rotation_intelligence_engine.py --input data/portfolios/state/holdings.json
```

## 7. Safety invariants

This implementation does **not**:

- create an order
- submit an order
- change a position
- change Schwab/Alpaca/Fidelity behavior
- widen any protective-stop envelope
- bypass approval
- change canary or Stage 2c controls

All rotation outputs are advisory and require human review.

## 8. Next integration steps

The files in this baseline provide the validation and advisory foundation. The next runtime/UI wiring should add:

1. `/api/v2/strategy-intelligence-health`
2. `/api/v2/system/release-readiness`
3. `/api/v2/metrics/header`
4. `/api/v2/rotation/summary`
5. `/api/v2/rotation/opportunities`
6. Command Center v3 Rotation Intelligence panel
7. Metric health badge on Home/System

These should consume the new scripts/registry rather than duplicate logic.

## 9. Acceptance for 9/10

| Area | 9/10 acceptance |
|---|---|
| Strategy/proposal cards | 95%+ actionable cards have profile/sector/analyst/news or are marked not actionable |
| Repo hygiene | release gate PASS; no dirty live-adjacent source files |
| Metrics | every header KPI registered, scoped, timestamped, denominator-labeled |
| Rotation | advisory trim/add/rotate ideas include account, risk, income, concentration, and evidence |
