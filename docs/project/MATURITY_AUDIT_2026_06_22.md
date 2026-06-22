# Trade AI v12 — System Maturity Audit (2026-06-22)

**Method:** Live system probe (health agent, APIs, DB facts, queue metrics) + prior audit baseline (`MATURITY_AUDIT_20260611.md`).
**Scale:** 10 = institutional prop-desk grade; 5 = works but unproven; 2 = schema/aspiration only.

| # | Area | Score | Trend | One-line |
|---|------|------:|-------|----------|
| 1 | Safety & governance | **9.0** | → | Paper-only locks, kill switches, fail-closed gates |
| 2 | Broker integration (Schwab + Alpaca) | **8.0** | → | Stage 2b/2c proven; guards 21/26 green |
| 3 | Stop management & risk protection | **8.0** | ▲ | Live Schwab stops; 2 fresh stop-outs today (by design) |
| 4 | UI / Command Center v3 | **8.0** | ▲ | Health Hub, fund/ETF cards, Rotation page |
| 5 | Journal & execution coaching | **8.0** | → | Replay grading, Grok reviews, execution coach |
| 6 | Rotation / portfolio advisory | **8.0** | ▲ | Validator 8.0, fee-swap advisory |
| 7 | Observability & ops | **7.5** | ▲▲ | Health Agent (0–100 score) — execution_health currently 0 |
| 8 | LLM & agent architecture | **7.0** | → | 3 lanes healthy; 1,941-item overnight backlog |
| 9 | Documentation & process | **6.5** | → | A1A real; 42 doc drift items vs live facts |
| 10 | Proposal pipeline | **6.5** | → | 11 gates; conversion analytics lossy |
| 11 | Data ingestion | **6.5** | → | Multi-source; screener upsert fix deployed today |
| 12 | Strategy framework | **6.0** | → | 23 YAMLs; zero validated strategies |
| 13 | Signal scoring | **6.0** | → | 7-pillar rubric; needs attributed flow |
| 14 | Hermes intelligence | **6.0** | → | 7-factor composite; thin downstream influence |
| 15 | Cross-system arbitration | **6.0** | → | Evidence packets live; weights not differentiated |
| 16 | Backup & disaster recovery | **5.5** | → | Daily local pg_dump OK; no offsite rclone remote |
| 17 | Runtime control plane | **5.0** | → | Phase 199 incomplete; 7 pipeline skeletons unwired |
| 18 | Backtesting & proof of edge | **5.0** | → | PIT sim exists; swing_breakout = no_edge_oos |
| 19 | Live trading readiness | **3.5** | → | 18/100 closed trades, 1.5/6 months — blocked |

**Overall (weighted): ≈ 7.1 / 10**

**Verdict:** Safety-mature, intelligence-capable, execution-backlogged. Protective half of a prop desk is built; evidence/learning half needs sample time and overnight LLM drain restored.

---

## Live facts (2026-06-22 11:30 ET)

| Metric | Value |
|--------|-------|
| Health score | 64 (unhealthy) — execution_health=0, risk_protection=45 |
| Paper closed trades | 18 (61.1% WR, 3.02 PF) |
| Open paper trades | 3 |
| DB tables | 526 |
| Cron jobs | 306 |
| Strategies (YAML) | 23 |
| Holdings | $1,247,656 (guard passed) |
| Agent jobs queued >2h | 36 |
| Overnight LLM pending | 1,941 |

---

## Priority arc (fastest score movement)

1. **Re-enable overnight LLM cron** — stops backlog growth; unblocks intelligence drain
2. **Drain agent queue** — raise cron limit or run catch-up batches
3. **Configure offsite backup** — rclone remote + restore drill
4. **Let paper trades accumulate** — 12 more to 30-trade sample gate (~30 days at 0.4/day)
5. **Close Phase 199 pipelines** — reduce 306-cron fragmentation

---

## Comparison to 2026-06-11 audit

| Area | 2026-06-11 | 2026-06-22 | Notes |
|------|----------:|----------:|-------|
| Overall | ≈7.4 | ≈7.1 | Overnight LLM drain retired; health agent now surfaces backlog |
| Observability | 7 | 7.5 | Health Agent shipped (Jun 22 commits) |
| UI | 8 | 8 | Health Hub, card enrichments |
| LLM fleet | 7 | 7 | Backlog worsened (cron retired) |