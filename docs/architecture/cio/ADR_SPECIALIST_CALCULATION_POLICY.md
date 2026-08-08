# ADR: Specialist Calculation Policy

**Status:** FROZEN (P-1.0 Architecture Freeze)
**Date:** 2026-08-08
**ADR ID:** CIO-P-1.0-SPEC-008
**Phase:** P-1.0 — Phase -1 Architecture Freeze
**Canonical Reference:** `CIO_PHASE_MINUS_1_PLAN_CORRECTED.md` v3.3, Corrections 8, 11

## Decision

Freeze the deterministic-first policy for Guardian and Ledger specialist agents. LLMs are not authoritative numerical engines. Financial calculations come from Trade AI's deterministic service layer. LLM role is critique, explanation, and recommendation — not numeric production.

## Guardian (Risk Specialist)

### Deterministic Calculations (Trade AI Service Layer)

| Calculation | Method | Source |
|---|---|---|
| Portfolio concentration by symbol | Position size / Portfolio value | PostgreSQL query, existing portfolio infrastructure |
| Portfolio concentration by sector | Sector aggregation | PostgreSQL query, sector classification |
| Portfolio concentration by factor | Factor exposure mapping | Factor model data |
| Exposure metrics (beta, delta, notional) | Market data + position data | Existing pricing/risk infrastructure |
| Covariance/correlation matrices | Historical returns | Python statistical computation |
| VaR / stress test calculations | Parametric + historical simulation | Python deterministic computation |
| Stop-loss coverage ratios | Stop levels vs current price | Existing stop infrastructure |
| Protection coverage ratios | Hedge positions vs exposure | Portfolio hedging analysis |
| Event risk scoring | Calendar-based (earnings, FOMC, regulatory) | Event calendar + position mapping |

### LLM Role (Governed Gateway)

The Guardian agent's LLM may:
1. **Read** deterministic risk evidence produced by Trade AI
2. **Critique** the evidence (are there gaps? correlations changing? new risk factors?)
3. **Explain** risk findings in narrative form for the operator
4. **Recommend** risk-aware CIO adjustments (e.g., "concentration in sector X exceeds 20% — consider trim")
5. **Flag** anomalies or unexpected risk patterns

The Guardian agent's LLM must NOT:
1. Invent numeric risk calculations (e.g., "VaR is approximately $X")
2. Produce risk numbers without citing the deterministic source
3. Modify or override deterministic risk outputs
4. Make quantitative claims not supported by deterministic evidence

### Guardian Workspace

**Path:** `~/.openclaw/workspace-risk_agent/`
**Current maturity:** SKELETON (agent SOUL exists but workspace empty — not production-ready)
**Target:** Deterministic-first risk critic, governed LLM gateway only, advisory only

---

## Ledger (Tax/Account Specialist)

### Deterministic Calculations (Trade AI Service Layer)

| Calculation | Method | Source |
|---|---|---|
| Tax lot identification | Lot-level cost basis, acquisition date | Broker transaction data, PostgreSQL |
| Holding period tracking | Short-term vs long-term classification | Acquisition date + current date |
| Wash-sale window detection | 30-day window, across accounts | Trade history, linked account data |
| Account type constraints | IRA, Roth, taxable, HSA rules | Account type metadata |
| Contribution/distribution constraints | RMD calculations, 72(t) rules, penalty risk | Account type + age + balance |
| Estimated tax impact | STCG/LTCG rates, NIIT, state tax | Tax rate tables + holding data |
| Asset location optimization | Tax-efficient placement across account types | Account types + asset classes |

### LLM Role (Governed Gateway)

The Ledger agent's LLM may:
1. **Read** deterministic tax/account evidence produced by Trade AI
2. **Critique** the evidence (are there missed wash-sale windows? overlooked account constraints?)
3. **Explain** tax implications in narrative form for the operator
4. **Recommend** tax-aware CIO adjustments (e.g., "selling lot X triggers short-term gain — consider lot Y instead")
5. **Flag** imminent tax deadlines, RMD requirements, or wash-sale windows

The Ledger agent's LLM must NOT:
1. Invent numeric tax calculations (e.g., "estimated tax is approximately $X")
2. Produce tax numbers without citing the deterministic source
3. Modify or override deterministic tax outputs
4. Make quantitative claims not supported by deterministic evidence
5. Provide tax advice that requires a licensed tax professional (advisory only)

### Ledger Workspace

**Path:** `~/.openclaw/workspace-ledger/` (to be created in P-1.8)
**Current maturity:** NONEXISTENT (no agent, no workspace, no config)
**Target:** Deterministic-first tax/account specialist, governed LLM gateway only, advisory only

**Ledger scope clarification per v3.3 Correction 8:** "Ledger" = tax/account-constraint specialist ONLY. If a separate audit/integrity component is needed, name it separately (e.g., `Auditor` or `IntegrityMonitor`). Ledger is NOT the CIO action ledger auditor.

---

## LLM Role Boundary

```
┌─────────────────────────────────────────────────────────┐
│                    Trade AI (Deterministic)              │
│  ┌───────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ Risk Engine   │  │ Tax Engine   │  │ Pricing Data │ │
│  │ (VaR, conc,  │  │ (lots, wash, │  │ (quotes,     │ │
│  │  exposure,   │  │  constraints,│  │  benchmarks) │ │
│  │  stress)     │  │  tax est)    │  │              │ │
│  └───────┬───────┘  └──────┬───────┘  └──────┬───────┘ │
└──────────┼──────────────────┼──────────────────┼─────────┘
           │                  │                  │
           ▼                  ▼                  ▼
    Deterministic Evidence (structured data)
           │                  │                  │
           └──────────────────┼──────────────────┘
                              │
                              ▼
           ┌─────────────────────────────────────┐
           │     Governed LLM Gateway            │
           │  (agent_flash_governance.py)        │
           │                                     │
           │  Guardian LLM: critique evidence    │
           │  Ledger LLM: critique evidence      │
           │                                     │
           │  Output: narrative, recommendation, │
           │  critique, flagged anomalies        │
           └─────────────────────────────────────┘
```

## Acceptance Criteria

For both Guardian and Ledger:

1. **Deterministic-only mode:** Disable LLM → metrics still computed → structured output available
2. **LLM critique mode:** LLM receives deterministic output → produces narrative critique → links back to deterministic evidence
3. **LLM does not invent numbers:** Audit LLM output → all quantitative claims trace to deterministic source
4. **Governed gateway:** All LLM calls route through Trade AI LLM gateway, not direct OpenClaw DeepSeek
5. **Advisory only:** Neither Guardian nor Ledger execute, modify holdings, or take autonomous actions

---

*Frozen by P-1.0 Architecture Freeze on 2026-08-08. Modification requires ADR amendment.*
