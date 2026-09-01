# Hermes Journal-Review & Backtesting — Internal Owner → External Escalation (2026-06-07)

Status:      ACTIVE
as_of:       2026-06-07T13:38:00-04:00
Measured at: efcc51365 / not measured

Maps the journal-review and backtesting workflows Hermes is involved in to their INTERNAL agent/owner and
the conditions that ESCALATE a finding to an EXTERNAL researcher lane. All advisory; escalation is
operator-gated per EXTERNAL_LLM_USAGE_POLICY_20260607.md.

## Journal reviews
| Workflow | Internal owner (model) | Writes | Escalate to external when… | Lane |
|----------|------------------------|--------|----------------------------|------|
| Per-trade close review (lessons) | `trade_close_llm_analyzer.py --structured` (gemma3, health-gated) | trade_llm_reviews | a recurring mistake pattern repeats across N trades; lesson is tax/retirement/SSDI-sensitive | Claude (high-stakes) / ChatGPT (synthesis) |
| Journal dual-opinion | `generate_journal_dual_opinions.py` (gemma3) | advisory choices | the two internal opinions diverge sharply on a high-$ trade | Claude / Consensus |
| Journal coach | `journal_agent_coach.py` (Ollama qwen3:1.7b → Anthropic fallback) | coaching notes | low internal confidence + high decision importance | ChatGPT / Claude |
| Deep journal synthesis | `hermes_deep_research_local.py` (gemma3:27b, overnight) | hermes_research_intelligence | overnight deep review flags a systemic issue | Claude (final challenge) |

## Backtesting
| Workflow | Internal owner (model) | Writes | Escalate to external when… | Lane |
|----------|------------------------|--------|----------------------------|------|
| Strategy backtest | `strategy_backtester.py` / `enterprise_backtester.py` / `trade_backtest_engine.py` | strategy_backtest_*/trade_backtest_results | weak strategy (PF<1 or WR low) with sufficient n AND it is live/proposed | ChatGPT (design review) / Claude (retire decision) |
| Structured backtest eval (AI Trade Eval) | `trade_close_llm_analyzer.py --structured` (gemma3) | trade_llm_reviews (structured_backtest_eval) | eval verdict conflicts with realized outcome repeatedly | ChatGPT / Claude |
| Edge comparison (profit-left-on-table) | `compute_edge_comparison.py` | trade_edge_comparison | large captured-vs-potential gap on a high-$ position (giveback risk) | Claude (P0 giveback) |
| Entry-quality / MFE-MAE | backtest analyzers | trade_backtest_results | entry-grade decay trend on an active strategy | ChatGPT (synthesis) / Grok (catalyst/narrative) |

## Routing summary
- **Claude** — high-stakes/tax/retirement decisions, strategy-retire calls, final challenge, profit-giveback P0.
- **ChatGPT (openai-codex OAuth, free)** — design/code review, structured synthesis, alternative reasoning.
- **Grok (xai-oauth proxy, free)** — catalyst/news/social narrative behind a journaled or backtested move.
- **Consensus panel** — sharp internal disagreement + high importance.

## Flow
internal review (gemma3/27b) → finding staged in trade_llm_reviews / trade_edge_comparison / hermes_research_
intelligence → meets an escalation trigger (210G) → operator runs `hermes_external_researcher.py --lane …`
(dry-run → --apply) → external advice stored in hermes_external_research → operator decides. No auto-escalation.

## Status (honest)
Internal owners: **mapped** (here + 209G). External escalation for journal/backtest: **now mapped** (this
doc + 210G triggers). External lanes are advisory + operator-gated; auto-escalation is NOT enabled.
