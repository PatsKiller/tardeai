# Agent & Hermes Workflows

**Status:** Canonical workflow reference · Validated 2026-06-03
**Scope:** End-to-end workflows for (1) the core agent fleet and (2) the Hermes sidecar challenger system. Linked from `MASTER_SYSTEM_DOCUMENTATION.md` §11 (Agent Layer) and §18b (Hermes Sidecar). See also `AGENT_ROSTER.md`, `AGENT_PAGES_DETAIL.md`, and `docs/hermes/`.

Run-state is reported honestly: **operational** = scheduled and running; **designed** = built, not auto-scheduled; **dormant** = connector ready, awaiting config; **disabled** = present but kill-switched/commented.

---

## Part 1 — Agent Fleet Workflows

The core agents are local-LLM workers (`gemma3:12b` primary, `gemma3:4b` fallback via Ollama — no external APIs for routine work; Alex may escalate to Claude). Conversational access is via the OpenClaw gateway (:18789) over Telegram/WhatsApp. Backend automation runs on cron/systemd.

### Fleet roster & run-state

| Agent | Role | Trigger / schedule | Key outputs | Run-state |
|-------|------|--------------------|-------------|-----------|
| **Maria** | Research / catalyst verification, watchlist batch | Job worker, every ~15 min (`process_watchlist_agent_jobs.py`) | `watchlist_agent_results` | operational |
| **Steph** | Income / allocation & account-fit | Job worker, every ~15 min | `watchlist_agent_results` | operational |
| **Risk** | Stop coverage, portfolio heat, risk-gate validation | Job worker, every ~15 min; `risk_gate.py` | `watchlist_agent_results`, risk-gate evals | operational |
| **Tax** | Tax-loss harvest, Roth/IRMAA, wash-sale | Job worker, every ~15 min | `watchlist_agent_results` | operational |
| **Alex (CIO)** | Escalation arbiter, strategic oversight, retirement | 5:00 AM daily; 7:15 AM hygiene; 8:00 AM Sun weekly; monthly 1st | `cio_decisions`, `alert_events` | operational |
| **Aegis** | Overnight surveillance, morning briefs, social sentiment, synthesis | 8 PM overnight, 8 AM surveillance, 11 AM/3 PM social, 7 PM ingest, 9 PM synthesis, 8:05 AM brief | `aegis_portfolio_briefs`, morning brief (PDF+Telegram) | operational |
| **Iris** | Intelligence librarian — taxonomy, routing, RAG coverage audits | Weekly Sun 10 AM + daily gap scan (Phase 41 migration pending) | `iris_run_log`, `iris_proposals` | designed |
| **Social Scalp** | Social mention scan → GO/WAIT/AVOID | Event-driven (scalp pipeline) | scalp signals | operational |
| **Scalp Critic** | Catalyst validation / signal gating | Event-driven, follows Social Scalp | validated signals | operational |

### Processing schedule (job worker)

| Window | Interval | Jobs/run | Context |
|--------|----------|----------|---------|
| Market hours (6 AM–7 PM) | 15 min | 10 | Active trading |
| Overnight (8 PM–11 PM) | 5 min | 25 | Batch |
| Weekend | 10 min | 15 | Catch-up |

### Allocation workflow chain

```
Maria (catalyst/news)  →  Steph (allocation/income fit)  →  Risk (stops/heat, risk gate)  →  Tax (optimization)
                                                                      │
                                                              Alex (CIO arbiter) ── escalations → John (Telegram/WhatsApp)
```

Agents never execute trades. Their outputs are advisory inputs to the proposal lifecycle (§10), which remains human-in-the-loop.

### LLM input curation (watchlist batch)

`process_watchlist_agent_jobs.py` assembles prompts from layered, fail-closed context — not raw symbol dumps:

| Layer | Source | Notes |
|-------|--------|-------|
| Position truth | `holdings.json` + DB | Explicit **NOT CURRENTLY HELD** when 0 shares (prevents stale RAG inventing positions) |
| Fundamentals | `ticker_enrichment_cache.json`, strategy cards, `ticker_prices` | RSI, SMA, ATR, sector |
| Intelligence | RAG (`rag_retrieval`), Hermes block, news/social sentiment | Agent-scoped; Iris content-gap warnings when thin |
| Collaboration | Peer agent notes (same batch + 30d DB), fused signals | Confidence normalized 0–1 before injection |
| Governance | Strategy YAML playbook, calibration context, G1–G10 global rules | Performance WR/PF adjusts confidence guidance |
| Contract | `cio_agent_v2` JSON | `evidence[]`, `data_i_doubt`, reason codes |

**Symbol gate (2026-07-09):** `gate_watchlist_symbol()` runs before every job. Invalid shapes (numeric garbage), denylist tokens (CEO, AI, …), and unknown symbols are failed without LLM spend. Portfolio-held tickers pass shape check via `holdings.json` allowlist.

**Confidence hygiene:** Parser + API normalize 0–1 / 0–100; values >100 (poisoned income dollars, account ids) are dropped to default 0.5 at ingest and excluded from roster averages.

### v3 surfaces

- **AgentsHub.tsx** — Roster, Calibration, Workflow graph (live handoff edges from `/api/v2/agent-pipeline`), Performance.
- Endpoints: `/api/v2/agent-pipeline`, `/agent-health`, `/agent-calibration/agents`, `/agent-collaboration`, `/agent-dashboard?agent=X`, `/agents/summary`.

---

## Part 2 — Hermes Sidecar Workflows

Hermes is Trade AI's near-24/7 research desk, memory layer, and independent challenger. It is **not** a trading worker: it writes only to `hermes_*` staging tables, has no broker/proposal/trade/journal mutation authority, and every promotion is audited and reversible.

**Architecture note (current, 2026-06-03):** Per Operator Directive B (2026-06-02), the **Chief Hermes Coordinator** runs the fleet live (`--apply`) on a `*/15` flock-guarded cron. Research auto-promotion (staged → promoted, then optional RAG embedding) is **enabled but bounded and reversible** — this concerns *research intelligence only* and does **not** relax any trade/proposal gate (Safety Rules §19 remain in force: proposals are human-in-the-loop, no broker access). Verified live 2026-06-03: coordinator tick at 08:09 ("3 promoted, 4 agents run"), no kill switch present.

### Hermes fleet roster & run-state

| Component | Purpose | Trigger | Key outputs | Run-state |
|-----------|---------|---------|-------------|-----------|
| **Chief Coordinator** | Orchestrate fleet, enforce per-tick caps, route tasks, auto-promote | `*/15` cron, flock-guarded | `hermes_memory_events`, `hermes_promotion_audit` | operational |
| **Autonomous Loop** | Ticker-thesis challenge + pipeline-quality validation | via Coordinator (`--max-rows 3` per sub-loop) | `hermes_research_intelligence` (`ticker_thesis_challenge`, `pipeline_quality`) | operational |
| **Source Discovery** | Discover sources via SearXNG, stage candidates | via Coordinator | `hermes_research_intelligence` (`source_discovery`) | operational |
| **Librarian** | Review staged findings; route to embed/promote/backlog | via Coordinator (cap 10/tick) | status updates (no direct embed/promote) | operational |
| **Embedding Curator** | Select high-confidence research for RAG | via Coordinator (cap 2/tick) | `hermes_embedding_queue` → `content_embeddings` | operational |
| **Auto-Promote** | Staged → promoted (bounded, reversible) | via Coordinator (cap 10/tick) | `hermes_research_intelligence.status='promoted'` + audit | operational |
| **Source Curation** | Track source yield (promoted/total), update registry | Weekly Sun 11:30 PM cron | `research_sources` | operational |
| **Backlog Manager** | Structured research backlog (no dedicated table — surfaces backlog-tagged intel) | via Coordinator | backlog-tagged `hermes_research_intelligence` | designed |
| **Catalyst Momentum Engine** | Catalyst-driven momentum/scalp research on 3 cadence bands via SearXNG | Cron, 3 bands (premarket */30 4–9 ET, swing :30 9–15 ET wkdys, overnight 18/22 daily) — `--apply` advisory only | `hermes_research_intelligence` (`momentum_catalyst`, staged); gated paper proposals only with `--generate-proposals` | operational (2026-06-03) |
| **RSS Ingest** | Parse `config/hermes_rss_feeds.txt`, stage items | Manual | `hermes_research_intelligence` (`source='rss'`) | dormant (no feeds configured) |
| **Backlog Health Check** | Read-only backlog health report | Manual | `docs/hermes/backlog_health/` | designed |
| **Embedding Promotion Reviewer** | Dry-run embed/promote recommendations | Manual | `docs/hermes/embedding_promotion_reviews/` | designed |

### Per-tick caps (Coordinator)

`CAP_LIBRARIAN=10` · `CAP_AUTONOMOUS=3` · `CAP_PROMOTE=10` · `CAP_EMBED=2`. Caps bound load; the kill switch halts everything on the next tick.

### Hermes workflow chain

```
SearXNG ─→ Source Discovery ─┐
RSS (dormant) ───────────────┤
Autonomous Loop ─────────────┤→  staged hermes_research_intelligence
Catalyst Momentum Engine ────┘                    │
                                          Librarian (route)
                                     ┌────────────┼─────────────┐
                              Embedding Curator   Auto-Promote   Backlog
                                     │             │
                            content_embeddings  promoted intel ──→ feeds core agents (Maria/Steph/Risk/Alex)
                              (RAG corpus)        + hermes_promotion_audit (reversible)
```

The Catalyst Momentum Engine has two feeds: (1) advisory research → staging → promote → RAG; (2) gated paper proposals via `auto_proposal_generator.py` — never bypasses the 11 safety gates + risk gate, paper-only, human approval required.

### Safety controls

- **Kill switches** (halt fleet next tick): `hermes_sidecar/.hermes/DISABLED` (master), `COORDINATOR_DISABLED`, `LIBRARIAN_DISABLED`.
- **Locks** (prevent overlap): `/tmp/hermes_coordinator.lock`, `/tmp/hermes_source_curation.lock`, `/tmp/hermes_autonomous_loop.lock`.
- **Reversibility:** every promotion writes `hermes_promotion_audit.rollback_sql`.
- Hermes reads main-system context only through read-only safe views (`hermes_v_*`).

### Data outputs

- **Tables:** `hermes_research_intelligence` (core staging), `hermes_promotion_audit`, `hermes_embedding_queue`, `content_embeddings`, `hermes_memory_events`, `research_sources`, `hermes_validation_findings`, `hermes_alerts`.
- **File reports:** `docs/hermes/observations/`, `docs/hermes/backlog_health/`, `docs/hermes/embedding_promotion_reviews/`, `docs/hermes/librarian_loop_dryruns/`, `docs/hermes/phase3b_dryrun/`.

### v3 surfaces

- **HermesHub.tsx** — Overview, Workflow, Provenance, Sources, Research, Dual Opinion, Pipeline; run-state colors (operational/live/running-unapproved/designed/disabled).
- Endpoints: `/api/v2/hermes/health`, `/self-learning-overview`, `/advisory-choices`, `/research-backlog`, `/dual-opinion`, `/pipeline-quality`, `/promotion-review`, `/agent-footprint`, `/infra`, `/provenance`, `/sources`.

---

## Change history

- **2026-06-03e** — YouTube transcript pipeline restored + extended. Root cause of the 14-day transcript stoppage: `config/youtube_cookies.txt` was logged-out (no auth cookies) → YouTube IP-blocked the ingester (`youtube_transcript_ingest.py`, 0 found). Installed authenticated cookies (untracked + gitignored), ingestion flowing again (13 transcripts). New: (1) `hermes_youtube_discovery.py` — Hermes discovers YouTube content for related targets via SearXNG youtube engine → fetches transcripts → stages `youtube_discovery` into `hermes_research_intelligence` (daily 14:00; Hermes already *looked up* transcripts via the ~1,150 youtube RAG embeddings). (2) Cookie-health stoplight in v3 System→Pipeline (red/amber/green via `/api/v2/system/pipeline-health`). (3) `youtube_cookie_health_check.py` → Telegram refresh alert when cookies go logged-out/stale (daily 19:45).
- **2026-06-03d** — Monitoring + loop-closure hardening. (1) Triaged freshness checks: ~5 were check-bugs querying an outdated schema (false FAILs masking real signals); fixed → real issues now surface (broker recon 22d stale, 142-job agent backlog, empty weekly_learning). (2) New `scripts/job_coverage_monitor.py` — registry of must-run jobs checking SCHEDULED? + PRODUCING?; caught unscheduled drive-sync + stale holdings_llm. Scheduled drive-sync (was manual) + the monitor. (3) New `scripts/iris_proposal_curator.py` closes the iris discovery loop: auto-applies hi-conf (≥0.85) reclassify, expires stale un-appliable new_channel_discovery (>14d), leaves add/retire_channel for review; daily 7:20. Drained iris backlog 1,135→980.
- **2026-06-03c** — Enabled `--generate-proposals` on the premarket & swing catalyst cron bands (gated paper proposals, overnight stays advisory). Fixed broken `topic_ingestion.py --all` cron (invalid arg → crashed every Wed/Sat run) → `--use-llm-queries` (processes all enabled topics). News-to-domain coverage confirmed: `iterate_research_topics.py` (daily 8 AM) actively researches Alex's tax/retirement topics (tax_loss_harvest, irmaa, roth_conversion, ssdi, trust_estate), Steph's income (dividends, bonds, covered calls), Maria's sectors (AI chips/datacenter/network, defense) — 17 topics total.
- **2026-06-03b** — Catalyst Momentum Engine promoted designed→operational. Fixed 3 schema bugs in its `hermes_research_intelligence` INSERT (missing `freshness_date`, `model_used`; `source` must be `'hermes'` not `'searxng'`) that had silently prevented it from ever producing a row. First successful run staged 6 catalyst findings (market_swing). Scheduled all 3 bands (cron, flock-guarded, `--apply` advisory only).
- **2026-06-03** — Initial canonical workflow reference. Captured live coordinator-driven Hermes fleet (directive B), honest run-states, and the agent allocation chain. Supersedes the stale "autonomous timer: daily 01:00 / auto-promotion prohibited" description previously in MASTER §18b.
