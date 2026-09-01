# Phase 113A — Proposal Authority Control Comparison

Status:      HISTORICAL
as_of:       2026-06-01T15:53:13-04:00
Measured at: efcc51365 / not measured

## Hermes vs TradeAI: Can Hermes Produce Proposals?

The question is not "whose research is better" but "what controls exist for each path."

### Control Comparison Matrix

| Control | TradeAI Proposals | Hermes Draft Proposals |
|---------|------------------|----------------------|
| **Evidence quality** | 60+ Finviz fields, 17 indicators, 7 news sources, catalyst verification, LLM 4-chunk review | Hermes research (gemma3:12b), headless browser scraping, DB views (76K+ rows), but no live Finviz enrichment |
| **Auditability** | proposal_lifecycle_events, atm_decision_log, proposal_agent_reviews, paper_execution_quality | hermes_research_intelligence (staged), hermes_promotion_audit, hermes_advisory_events — full audit trail |
| **Rollback** | proposal status revert, trade cancellation via Alpaca | Sandbox-only: delete draft file or row. No downstream impact. |
| **Schema validation** | 115+ columns on paper_trade_proposals, 8 enrichment satellite tables | Would need its own draft schema — no writes to real proposal tables |
| **Operator review** | ATM auto-approver gates, Telegram approve/reject, risk gate, enrichment requirements | Currently: all Hermes output is advisory. Sandbox would require explicit operator promote step. |
| **False-positive risk** | Proposal → paper trade → real broker order chain exists. Bad proposal can create real position. | Sandbox: zero downstream execution. Draft stays as draft until operator promotes. |
| **Downstream impact** | paper_trades, stop management, P&L, journal, portfolio allocation, tax lots | Zero. Sandbox is isolated. |
| **Blast radius** | HIGH — a bad auto-approval creates a real position | ZERO — sandbox is read-only to the trading system |

### Assessment

TradeAI has **better evidence quality** (live Finviz enrichment, real-time quotes, multi-source catalyst verification) but **higher blast radius** (proposals can become real trades).

Hermes has **lower evidence quality** (no live Finviz, no real-time quotes, relies on DB views and web scraping) but **zero blast radius** (sandbox is isolated from execution).

The right architecture is: let Hermes produce draft proposals in a sandbox, compare them against TradeAI's pipeline quality standards, and only consider promoting when Hermes drafts consistently meet or exceed TradeAI proposal quality scores.
