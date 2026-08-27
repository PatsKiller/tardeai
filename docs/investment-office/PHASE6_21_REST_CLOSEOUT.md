# PHASES 6–21 CLOSEOUT — Rest of CIO Acceptance (v3.0)

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY` unchanged  
**Branch:** `wt/cio-acceptance-rest`  
**Versions:** `capital_plan_1.3.0` · `office_home_1.3.0` · `strategy_knowledge_1.0.0` · `seasonality_engine_1.0.0` · `advisory_provenance_1.0.0` · `decision_field_parity_1.0.0`

## Scope delivered

| Phase band | Deliverable | Status |
| --- | --- | --- |
| **6** | Account capital ledger + earmark narrative (not “new raise”) | Done |
| **7** | Decision field parity across plan / NOW / report / Telegram | Done |
| **8** | Advisory provenance on expanded decision rows | Done |
| **9–11** | Report instance SHA stamp; prepare-only Telegram; E2E scorecard | Done |
| **12–17** | Strategy knowledge registry + influence policy + seasonality | Done |
| **18–21** | Acceptance scorecard runner + evidence pack under `data/audit/` | Done |

Phases **0–5** closed earlier (exact deploy, FinancialTruthGate, freshness/materiality, attention KPIs, institutional sizing).

## Modules

| Path | Role |
| --- | --- |
| `scripts/lib/cio_capital_plan.py` | Account ledger + attach strategy/seasonality/provenance/parity |
| `scripts/lib/cio_command_center.py` | Office home strategy context + parity |
| `scripts/lib/cio_decision_semantics.py` | `decision_field_parity` / `ensure_decision_fields` |
| `scripts/lib/cio_advisory_provenance.py` | Expanded-row price/MV/basis/target provenance |
| `scripts/lib/cio_strategy_knowledge.py` | Research fact registry + influence policy |
| `scripts/lib/cio_seasonality_engine.py` | Month + presidential cycle (mechanical, non-partisan) |
| `scripts/run_cio_acceptance.py` | Sections A–H scorecard + evidence artifacts |
| `scripts/api_v2.py` | `_source_sha()` prefers BUILD_SHA / env / release stamp |

## Strategy layer rules (copyright + governance)

- Three layers **never collapsed:** SOURCE CLAIM → TRADE AI REPRODUCTION → CURRENT APPLICATION  
- Max influence role: **`risk_modifier_or_context`** (never autonomous execution)  
- STA-style seed facts are **operator-structured summaries**, not full-text republication  
- Presidential cycle is **year % 4 mechanical** — `partisan_conclusion` always `null`  
- Seed claims remain `unverified_source_claim` until independent reproduction

## Account ledger language

> `$X of current cash is earmarked from prior exits/redeploy; it is not new capital.`  
> Prospective raise is only trims/exits **not yet cash**. Deploy is bounded by investable free cash + prospective raise.

## Tests + CI

New suites (wired into `run_cio_hardening_ci.py`):

- `tests/test_cio_account_capital_ledger.py`
- `tests/test_cio_decision_parity.py`
- `tests/test_cio_advisory_provenance.py`
- `tests/test_cio_strategy_seasonality.py`

## Acceptance scorecard

```bash
python3 scripts/run_cio_acceptance.py
# → data/audit/cio_acceptance_YYYYMMDD/ACCEPTANCE_SCORECARD.json
```

**Pass threshold:** ≥ 95/100 with each major section ≥ 80%.

### Scorecard (2026-08-14)

| Section | Pre-deploy | Post live deploy (`fff9253a`) |
| --- | --- | --- |
| A Release truth | 9.0 / 10 | **10.0 / 10** |
| B Financial truth | 19.0 / 20 | 19.0 / 20 |
| C Decision quality | 19.0 / 20 | **20.0 / 20** |
| D Operator UX | 10.0 / 10 | 10.0 / 10 |
| E Report | 13.0 / 15 | 13.0 / 15 |
| F Telegram | 10.0 / 10 | 10.0 / 10 |
| G Strategy | 10.0 / 10 | 10.0 / 10 |
| H Governance | 5.0 / 5 | 5.0 / 5 |
| **Total** | **95.0 PASS** | **97.0 PASS** |

Evidence: `data/audit/cio_acceptance_20260814/ACCEPTANCE_SCORECARD.json`  
(Run with project venv so `python-docx` is available; PDF remains soft when renderer absent.)

**Live release:** `fff9253a-main-exact-phase6-21-rest-*` → CURRENT  
**Live fields:** `capital_plan_1.3.0`, `office_home_1.3.0`, account ledger, strategy_context, advisory_provenance on 22 decisions, decision_field_parity ok.

Honest residuals (expected until quote unification / full strategy OOS):

1. Dual price-field conflicts on some holdings until broker quote unification  
2. PDF renderer may be absent on some hosts  
3. Strategy facts largely unverified source claims  
4. Live SHA may lag main tip by pin-only commits  

## Telegram

Acceptance runner is **prepare-only**. Live CIO canary requires explicit dual/triple env gates (unchanged). No general bot path.

## Rollback

```bash
ln -sfn /home/johnclaw/trade-ai-releases/portfolio-server/<prior_release> \
  /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT \
  && systemctl --user daemon-reload && systemctl --user restart portfolio-server
```

## Authority

`READ_ONLY_ADVISORY` — no broker, no order, no stop, no 2FA, no autonomous execution.
