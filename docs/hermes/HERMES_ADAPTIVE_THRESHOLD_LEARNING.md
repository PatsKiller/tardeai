# Hermes Adaptive Threshold Learning
**Design Document v1.0**  
**Date:** 2026-07-03  
**Status:** Phase 2 implemented (multi-metric scoring + evaluation engine)

## 1. Objective

Enable the Hermes intelligence layer to **automatically adjust its own reaction thresholds** over time based on observed outcomes, while remaining conservative, fully auditable, and under human oversight.

The goal is to move from static, manually tuned thresholds to a system that can gradually improve its sensitivity and decision quality as more outcome data becomes available.

## 2. Design Principles

| Principle              | Requirement                                      | Rationale |
|------------------------|--------------------------------------------------|-----------|
| **Conservative First** | Never relax thresholds aggressively              | Protect capital and research quality |
| **Human-in-the-Loop**  | All changes require review/approval in v1        | Maintain operator trust and control |
| **Fully Auditable**    | Every threshold change must be logged with reasoning | Transparency and rollback capability |
| **Explainable**        | Operator can understand *why* a threshold moved  | Avoid black-box behavior |
| **Safe Bounds**        | Thresholds cannot move outside pre-defined safe ranges | Prevent harmful drift |
| **Small Steps**        | Maximum change per cycle is limited              | Reduce risk of large negative moves |
| **Regime Aware**       | Different thresholds for normal vs high-volatility regimes | Adapt to market conditions |

## 3. Scope – What Should Be Adaptive?

Priority thresholds to make adaptive:

| Threshold                        | Current Static Value | Why Make It Adaptive?                          | Learning Signal                     | Priority |
|----------------------------------|----------------------|------------------------------------------------|-------------------------------------|----------|
| Efficiency Reaction Trigger      | 0.50 for 3 days      | Different regimes need different sensitivity   | Future outcome yield                | High     |
| Stop Quality Divergence (Hot vs Cold) | 13pp            | Some periods need tighter/looser monitoring    | Stop quality vs realized R          | High     |
| Hot Tier Promotion Gate          | 65                   | Can be raised/lowered based on recent performance | Promotion success rate + long-term R | Medium   |
| Scope Creep Sensitivity          | 15% growth in 14d    | Should tighten when overall efficiency is low  | Scope size vs hit rate stability    | Medium   |
| Tag Quality Multiplier Floor     | 0.60                 | Can vary per tag based on long-term lift       | Tag lift stability over 30–60 days  | Low      |

## 4. Architecture

### Core Components

- **Threshold Learner** (`scripts/lib/hermes_thresholds/threshold_learner.py`)
  - Analyzes historical outcome bus data (30–90 days)
  - Identifies correlations between threshold values and downstream outcomes
  - Proposes small, conservative adjustments

- **Threshold Store** (`data/runtime/hermes_thresholds.json`)
  - Current active thresholds + full history of changes

- **Proposal & Review System**
  - Stores proposed changes in `hermes_threshold_proposals.json`
  - Supports **Review Mode** (log only, no application)
  - Human approval workflow (CLI + API + future UI)

- **Governor Integration**
  - `reactions.py` merges learned thresholds over static `hermes_reactions.yaml`

- **Evaluation Engine**
  - Periodically measures whether previous threshold changes improved key metrics

### Data Flow

```
Outcome Bus History (30–90 days)
        ↓
Threshold Learner (hermes_threshold_learner.py)
        ↓
Threshold Proposals (with reasoning + expected impact)
        ↓
Human Review (CLI or API) → Approve / Reject / Modify
        ↓
Active Thresholds (hermes_thresholds.json)
        ↓
Scope Governor applies updated thresholds
```

## 5. Safety Mechanisms (Mandatory in v1)

| Mechanism                    | Description                                      | Implementation |
|-----------------------------|--------------------------------------------------|----------------|
| **Safe Bands**              | Hard limits on how far any threshold can move    | `config/hermes_thresholds.yaml` |
| **Maximum Step Size**       | Max change per learning cycle (e.g. ±0.03)       | Enforced in learner |
| **Review Mode**             | Log proposals but do not apply changes           | Default in config |
| **Human Approval Gate**     | Changes only activate after explicit approval    | `--approve` CLI |
| **Cooldown / Hysteresis**   | Prevent rapid back-and-forth changes             | Reuses reaction cooldown |
| **Full Audit Trail**        | Log every proposal + decision + outcome          | `hermes_threshold_audit.jsonl` |
| **Easy Rollback**           | One-command revert to previous threshold set     | `--rollback` CLI |

## 6. Learning Method (Phase 2 — scoring-v2)

### Efficiency composite (weights sum to 1.0)

| Component | Weight | Rationale |
|-----------|--------|-----------|
| hit_rate_separation | 40% | Primary outcome yield signal |
| maturity_separation | 25% | Closed-loop health |
| realized_r_separation | 15% | Trade quality when n available |
| efficiency_stability | 10% | Avoid noise-only triggers |
| early_detection | 10% | Fires before subsequent yield drop |

Final score = `sum(contributions) × trigger_guard` where trigger_guard penalizes fire rates >35%.

### Stop quality composite

| Component | Weight |
|-----------|--------|
| alignment_separation | 35% |
| trail_delta_separation | 25% |
| maturity_stop_separation | 20% |
| early_detection | 10% |
| trigger_guard | 10% |

### Asymmetric rules

- **Tighten:** min score delta 0.002
- **Loosen:** requires 2× score delta **and** confidence ≥ medium

### Confidence tier

Derived from sample days, regime stability (≤30% high-vol days), score delta, runner-up gap.

### Evaluation engine (`--evaluate`)

Read-only before/after comparison per approved change (14d windows). Verdicts: `helped` / `neutral` / `hurt` / `insufficient_data`. Recommendations: `keep` / `monitor` / `revert` / `needs_more_data`.

## 7. Implementation Phases

| Phase | Focus                              | Key Deliverables                                      | Status |
|-------|------------------------------------|-------------------------------------------------------|--------|
| 1     | Foundation + Efficiency Threshold  | Learner, safe bands, review mode, efficiency + stop quality | **Implemented** |
| 2     | Scoring v2 + Evaluation Engine     | Multi-metric scoring, `--evaluate`, panel evaluations | **Implemented** |
| 3     | UI + Observability                 | Threshold proposal viewer + impact analysis in panel  | Partial (API + panel) |
| 4     | Advanced                           | Regime-specific bands + multi-threshold optimization  | Future |

## 8. Files

| File | Role |
|------|------|
| `config/hermes_thresholds.yaml` | Safe bands, step sizes, learning windows |
| `scripts/lib/hermes_thresholds/store.py` | Active thresholds + proposals persistence |
| `scripts/lib/hermes_thresholds/threshold_learner.py` | Statistical analysis + proposal generation |
| `scripts/lib/hermes_thresholds/workflow.py` | Approve / reject / rollback |
| `scripts/hermes_threshold_learner.py` | Nightly/weekly CLI agent |
| `data/runtime/hermes_thresholds.json` | Active learned values |
| `data/runtime/hermes_threshold_proposals.json` | Pending + decided proposals |
| `data/runtime/hermes_threshold_audit.jsonl` | Append-only audit log |

## 9. Commands

```bash
# Status (active vs static defaults + pending proposals)
.venv/bin/python scripts/hermes_threshold_learner.py --status

# Generate proposals (review mode — does not apply)
.venv/bin/python scripts/hermes_threshold_learner.py --learn

# Approve / reject
.venv/bin/python scripts/hermes_threshold_learner.py --approve tp_<id>
.venv/bin/python scripts/hermes_threshold_learner.py --reject tp_<id> --reason "too aggressive"

# Rollback to static defaults
.venv/bin/python scripts/hermes_threshold_learner.py --rollback

# API
curl -s http://127.0.0.1:7777/api/v2/hermes/thresholds | jq .
```

## 10. Command Center visibility (Closed Loop panel)

`/v3/hermes` → **Closed Loop** → **Adaptive thresholds** section:

- Active vs static vs proposed values per threshold
- Status badge: `static` / `learned` / `pending review`
- `pending_summary`, `history_days`, collecting-data state when &lt;14 bus days
- Inline **Approve** / **Reject** per proposal → `ThresholdProposalModal` confirmation
- Modal: change summary, direction badge, evidence (confidence, metrics, expected impact), loosening warning, optional/required notes
- Success/error toasts; `Esc` / `Ctrl+Enter` keyboard shortcuts
- **Full review details** modal for deep evidence + optional value override

### API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v2/hermes/thresholds` | Status + pending proposals |
| POST | `/api/v2/hermes/thresholds/proposals/{id}/approve` | `{ notes?, reason?, force_apply?: true, override_value? }` |
| POST | `/api/v2/hermes/thresholds/proposals/{id}/reject` | `{ reason?, notes? }` |
| POST | `/api/v2/hermes/thresholds/approve` | Legacy — `{ proposal_id, override_value?, force_apply? }` |
| POST | `/api/v2/hermes/thresholds/reject` | Legacy — `{ proposal_id, reason? }` |
| POST | `/api/v2/hermes/thresholds/learn` | Run learning cycle `{ apply: true }` |

## 11. Validation Checklist (Phase 2)

### `--learn` (scoring-v2)
1. Proposals include `evidence.version: scoring-v2`, `confidence`, `metric_contributions`, `runner_up`
2. Loosen proposals only appear with 2× score delta + medium+ confidence
3. Sparse history (<20d) halves max_step
4. Regime breakdown in evidence when universe history available

### `--evaluate`
5. Read-only — never modifies `hermes_thresholds.json`
6. Writes to `hermes_threshold_evaluations.json` + audit jsonl
7. Skips changes younger than `min_days_after_change` (14d)
8. Each evaluation has `verdict`, `recommendation`, `impact_score`, before/after metrics

### Governance (unchanged)
9. `--approve` / `--reject` / `--rollback` still work
10. Review mode default; governor merges learned thresholds
11. API: `GET /thresholds`, `GET /thresholds/evaluations`, `POST /thresholds/evaluate`
12. Closed Loop panel shows confidence + evaluation summary

---

**Related docs:**
- `docs/hermes/OUTCOME_BUS_IMPLEMENTATION.md`
- `docs/hermes/HERMES_THRESHOLD_EVALUATION_ENGINE.md` (Phase 2 design)
- `docs/hermes/HERMES_THRESHOLD_SCORING_REVIEW.md` (scoring refinements)