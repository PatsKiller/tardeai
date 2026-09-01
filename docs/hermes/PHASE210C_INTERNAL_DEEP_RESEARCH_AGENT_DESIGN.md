# Phase 210C — Internal Deep-Research Lane Design (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T13:06:32-04:00
Measured at: efcc51365 / not measured

## Hermes Deep Research — Local
- **Model:** gemma3:27b / gemma3-overnight (BATCH_OVERNIGHT). **NOT gemma4** (not installed → deferred).
- **Process:** batch, overnight window only; no interactive/daytime load on the trading stack.
- **Tools:** none directly (advisory; uses DB context via llm_context_engine + RAG, not live tools).
- **Inputs:** DB context (llm_context_engine), RAG (content_embeddings), promoted research, Trade AI safe
  views, journal/backtest/profit-protection outcomes, edge-comparison + closed-loop outcomes.
- **Outputs:** deep research reports, thesis challenges, strategy reviews, source-credibility assessments,
  operator advisory packets, learning candidates.
- **Writes:** hermes_* staging tables ONLY — never core trading/broker/proposal/execution tables.
- **Safety:** no broker/order/protection actions, no live trading, advisory-only.
- **Promotion path:** deep research → librarian review → embedding/promote → RAG → future advisory context.
- **Evaluation:** compare its recommendations to subsequent realized outcomes (feeds 210F learning chain).

## Why not gemma4 now?
Not installed; unproven on this hardware; no canary/gate history. Promoting an unvetted model into the
deep lane would risk silent quality regression in advisory context.

## Gates to promote gemma4 later
1. installed + direct-Ollama canaries pass (exact-string + math + JSON).
2. no-tools chat sanity pass; no hallucinated current/version facts.
3. overnight batch A/B vs gemma3:27b on a fixed research set (operator-scored).
4. cost/latency within the overnight window; documented + operator-approved.

## vs tradeai12b chat
tradeai12b = interactive, manual, 12B-ctx4k, single-turn advisory. Deep Research Local = batch, overnight,
27B, multi-source synthesis with promotion/evaluation. Different model, cadence, and output contract.

## Automation
Yes — but ONLY during an approved overnight window, behind the existing kill-switch, advisory-only, with
per-run caps. Not enabled in this phase (design only).

---
## IMPLEMENTED (2026-06-07)
Runner built: `scripts/hermes_deep_research_local.py` (manual/overnight, advisory-only). Verified dry-run+apply (id=2003). NOT auto-scheduled. See HERMES_DEEP_RESEARCH_LOCAL_RUNNER_20260607.md.
