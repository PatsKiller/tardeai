# Trade AI v12 — Executive Architecture Overview

**Audience:** application owners / business stakeholders (non-technical)
**Companion (technical):** `docs/MASTER_SYSTEM_DOCUMENTATION.md`
**Status:** Paper-trading validation · **Last validated:** 2026-06-22

---

## 1. What this system does

Trade AI v12 is an **automated trading-intelligence platform** that researches the market, proposes
trades, executes them in a **paper (simulated) account**, and learns from every outcome. It runs an
operator's portfolio strategy end-to-end with AI assistance, while keeping a human in control of any
real-money decision. **It is currently paper-only** — no live brokerage funds are at risk — pending a
6-month validation gate (target: 55% win rate, 1.3 profit factor).

## 2. Core capabilities

| Capability | What it delivers |
|---|---|
| **Market screening** | Scans 15+ data sources (prices, news, filings, transcripts, social, macro) to find candidates. |
| **Strategy engine** | 23 configurable strategies (momentum, swing, income, dividend, defense, etc.) score and classify candidates. |
| **Trade proposals** | Generates reviewed proposals with entry/stop/target, risk sizing, and an AI rationale. |
| **Automated paper trading** | Submits and manages paper trades via the broker (Alpaca), with safety gates and reconciliation. |
| **Profit protection** | Continuously checks whether open winners are protected and advises stop/take-profit action — operator-approved. |
| **Closed-loop learning** | Measures every closed trade (did it give back profit?) and feeds results back to improve the models. |
| **AI agents** | Six assistants (research, wealth, risk, tax, surveillance, content) reachable via Telegram/WhatsApp. |
| **Operator dashboard** | A single web Command Center to see portfolio, proposals, trades, risk, and intelligence. |

## 3. Core workflow — the trade lifecycle (plain English)

```
  Discover            Decide               Execute (paper)        Protect & Learn
  --------            ------               --------------         ---------------
  Screen the     →    Strategy scores  →   Operator/auto     →    Track the trade,
  market for          the candidate,       approves; broker        advise protection,
  candidates          AI writes a          places a paper          measure the outcome,
  (15+ sources)       proposal + rationale order with a stop       feed lessons back
```

1. **Discover** — the platform screens the market on a schedule and shortlists candidates.
2. **Decide** — a strategy + AI rationale turns a candidate into a proposal (entry, stop, target, size).
3. **Execute (paper)** — after approval, the broker places a paper order with a protective stop; safety
   gates block anything stale, oversized, or unsafe.
4. **Protect** — while a position is open, the system flags winners whose stop no longer protects the
   gain and proposes an adjustment; **a real change only happens on an explicit operator click.**
5. **Learn** — when a trade closes, the platform measures profit captured vs. left on the table and
   uses it to tune its advice over time.

## 4. Reference architecture (simplified)

```
   ┌────────────┐   ┌─────────────────┐   ┌───────────────┐   ┌──────────────────┐
   │ DATA IN    │ → │ INTELLIGENCE    │ → │ DECISION      │ → │ PAPER EXECUTION  │
   │ market,    │   │ screeners,      │   │ proposals,    │   │ broker orders,   │
   │ news, SEC, │   │ strategies, AI  │   │ risk gates,   │   │ stops, monitor,  │
   │ social,    │   │ agents, local   │   │ operator      │   │ reconciliation   │
   │ macro      │   │ LLMs            │   │ approval      │   │ (Alpaca paper)   │
   └────────────┘   └─────────────────┘   └───────────────┘   └────────┬─────────┘
                                                                       │
                          ┌────────────────────────────────────────────┘
                          ▼
   ┌──────────────────┐   ┌──────────────────────────────────────────────────────┐
   │ DASHBOARDS       │ ← │ JOURNAL & LEARNING                                     │
   │ Command Center   │   │ record outcomes, measure give-back, protection         │
   │ v3 (web)         │   │ advisories, tune the models                            │
   └──────────────────┘   └──────────────────────────────────────────────────────┘
```

- **Local-first AI:** the AI models run on the operator's own hardware (no external API for core
  decisions), which keeps data private and cost predictable.
- **Single operator dashboard:** Command Center **v3** is the canonical web interface (an older v2 is
  kept only as a frozen fallback).

## 5. Safety posture (non-negotiable)

- **Paper-only.** No live brokerage account is connected for execution; live trading is hard-disabled.
- **Human-in-the-loop for any change to a real (paper) order** — the system advises; the operator
  approves.
- **Guardrails everywhere:** safety gates on every trade, a protected-stop check on every open
  position, and a prohibited "Level 7" autonomy tier that is never enabled.
- **Auditable:** every decision, advisory, and adjustment is logged.

## 6. Where to look

| Need | Go to |
|---|---|
| Live operations | Command Center **v3** dashboard (web) |
| Technical/config detail | `docs/MASTER_SYSTEM_DOCUMENTATION.md` |
| What changed when | `docs/project/PROJECT_DOC_INDEX.md` (change log) |
| Operating procedures | `docs/operator/ATM_RUNBOOK.md`, `docs/CHEAT_SHEET.md` |

---

*This is a business-level overview. For component, schema, pipeline, and deployment detail, see the
technical master document. Live scale figures: `docs/LIVE_SYSTEM_FACTS.md` (regenerate via
`scripts/generate_system_facts.py`). Paper-only; live trading gated.*
