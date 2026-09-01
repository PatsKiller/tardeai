# Phase 209K — Operator Guide: Hermes / TradeAI Workflows (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T12:31:23-04:00
Measured at: efcc51365 / not measured

1. **What the graph means** — /v3/hermes is the *research-agent* graph (a live Trade-AI research pipeline),
   separate from the global Hermes *chat profiles* (System → Hermes). Nodes = fleet agents; edges = handoffs.
2. **Who handles Librarian** — `hermes_autonomous_librarian_backlog_loop.py` via `hermes-librarian-backlog-loop.timer`.
   It reviews staged findings in `hermes_research_intelligence` and routes them to embed/promote/backlog (status updates only).
3. **TradeAI chat vs research fleet** — Chat (`tradeai`/`tradeai12b`) = you talk to an advisory model, tool-less,
   reasons over what you give it + the fleet's staged findings. Research fleet = autonomous scripts (timers)
   that gather/stage research into `hermes_*` tables. The chat reads what the fleet produces.
4. **Why both tradeai and tradeai12b** — same advisory role; tradeai = stable default (gemma3:4b),
   tradeai12b = experimental higher-capacity (gemma3:12b-ctx4k) for deeper analysis. Neither is automated.
5. **Which profile for which chat** — Trade questions → `tradeai` (or `tradeai12b` for deep analysis);
   general → `default`; coding → `dev`; server-ops → `serverops` (future). All advisory; none touch the broker.
6. **Which jobs enhance TradeAI** — source discovery, ticker-thesis challenge, librarian, embedding/promotion
   review, advisory cache, momentum catalyst, journal/backtest LLM review (see 209G matrix).
7. **What writes where** — fleet writes staging/advisory only: hermes_research_intelligence (443/24h),
   hermes_memory_events, hermes_promotion_audit, hermes_embedding_queue. Never core trading tables.
8. **What is read-only** — Trade AI safe views (13) + proposal sandbox drafts + chat profiles (0 tools).
9. **What is still not automated** — chat profiles (manual), dedicated research_backlog table, dev/serverops config.
10. **What not to touch** — retired sidecar/gateway (keep disabled), tradeai/tradeai12b tools (keep 0),
    trading/proposal/protection/broker logic, live trading (zero).
