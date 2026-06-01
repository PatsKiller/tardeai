# Memory Notes for Next Session — 2026-05-29 Final

## Backtest Classification
- **Complete**: 3,593 / 3,593 (100%)
- SHFS id=860 is `speculative_growth` — manual operator-approved correction
- Rollback: `docs/atm_lifecycle_v1_2026_05_29/shfs_860_apply/SHFS_860_ROLLBACK.sql`
- Do NOT run classifier apply — classification is done

## Proposal Lifecycle
- P0 bugs FIXED: expired case, hygiene panel status field
- ATM expiry sets primary status='EXPIRED' (commit e139030)
- Lifecycle inspector endpoint LIVE: `GET /api/v2/paper-proposals/lifecycle-inspector?proposal_id=<id>`
- UI Inspect button: NOT YET ADDED (P2)
- Hygiene panel: 141 total, 65 expired, 74 rejected, 2 linked, 0 needs_review
- 13 orphan proposal/trade links: audited, 1:N pattern, no fix needed

## Backtesting UI
- Source column added (green=replay, yellow=proposal, purple=champion)
- "Strategy Coverage" KPI: 3,593/3,593 in status API
- KPI row is now 7 cards (was 6): Datasets, Runs, Backtest Rows, Results, Strategy Coverage, Flagged, Missed
- Labels clarified: "Backtest Rows" not "Sim Trades", source-aware filter text
- "LLM Review Coverage" tab (was "LLM Reviews") with explainer banner
- Coverage cards: "Real Paper Trades With LLM Review" / "Backtest Rows With LLM Review"
- Sample-size badges: "very small" (<5), "small sample" (<20) on Strategy + Trail Analysis
- Context banner explains backtesting rows are not live broker orders
- 15/15 Playwright screenshots captured verifying new labels

## Self-Healing / Escalation
- retry_cmd direct execution hardened (commit 069fc8a)
- Tier 3a: Gemma4 31B via llama.cpp — validated, ~8min, flock guard
- Tier 3b: gemma3:12b fallback if Tier 3a times out
- Next observation: 4 AM pre-market enrichment cycle

## Model Policy
- Production: gemma3:12b (Ollama)
- Fallback: gemma3:4b (Ollama)
- Deep/offline: Gemma4 31B (llama.cpp only)
- DISABLED: qwen3:14b, gemma4 e2b/e4b, gemma3:27b GPU
- Max concurrent: 1
- Do NOT change routing without operator approval + 50 canary dry-runs

## Environment
- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- Ollama remains production runtime

## Automated Trading Audit
- ATM is **active** and working correctly
- Most proposals are momentum_scalp (intraday skip list) — correctly rejected
- Non-intraday proposals (SNOW, ONDS) were approved and created paper trades
- New endpoint: `GET /api/v2/atm/execution-readiness` (read-only diagnostic)
- No fix needed — if more automated trades desired, generate non-intraday proposals
- R:R floating point gate bug fixed (commit 5e6b7fa) — was blocking all proposals

## Hermes v4 Sidecar Strategy

* Hermes v4 design package has been saved under docs/hermes/.
* Hermes is not a separate trading worker.
* Hermes is Trade AI's near-24/7 research desk, second brain, memory layer, and independent challenger.
* Trade AI remains the source of truth and only execution authority.
* Hermes target design includes 6 pods and 24 logical agents.
* Hermes research scope includes trades, proposals, incubator, percolator, news, related news, YouTube transcripts, tickets, retirement, taxes, portfolio rotation, backtesting, journal, system health, dashboard truth audits, data freshness, and operator decisions.
* Hermes starts read-only and file-memory based.
* Hermes may eventually write advisory memory and recommendation queues only.
* Compatibility audit COMPLETE (2026-05-30): NousResearch/hermes-agent is real Python CLI, MIT license, supports local Ollama, gemma3:12b 131K context exceeds 64K requirement, project-scoped via HERMES_HOME, no Claude Code conflict, clean uninstall.
* Phase P0 final gate: **GO** — all 7 verification sections pass, no blockers.
* **Database-first architecture designed** (supersedes file-first): 6 hermes_* tables, hermes_readonly DB role, shared scoring via content_scoring.py, same embedding model (nomic-embed-text 768-dim), validation challenger with hermes_validation_findings, advisory alerts via hermes_alerts.
* Staging schema: `hermes_research_intelligence`, `hermes_validation_findings`, `hermes_alerts`, `hermes_embedding_queue`, `hermes_memory_events`, `hermes_promotion_audit` (none created yet).
* 8 existing tables assessed: 5 safe for promotion (news_articles, content_embeddings, intelligence_entities, agent_intelligence_rules, deep_overnight_llm_results), 3 staging-only.
* Hermes reads via API + hermes_readonly DB role. Writes only to hermes_* tables. Promotion to production requires --dry-run then --apply with operator approval.
* File outbox is emergency fallback only, not primary architecture.
* Rollback plan documented: `rm -rf hermes_sidecar/` for project-scoped install.
* **Phase 0 install COMPLETE** (2026-05-30): hermes-agent 0.15.2 in hermes_sidecar/, HERMES_HOME override works, no ~/.hermes, local Ollama only.
* **Phase 1 DB staging COMPLETE** (2026-05-30): 6 hermes_* tables created (0 rows), 34 indexes, 18 CHECK constraints, all with source='hermes' enforcement.
* **Roles COMPLETE** (2026-05-30): hermes_readonly (SELECT on hermes_*) and hermes_staging_writer (SELECT/INSERT/UPDATE on hermes_*, sequences) created via sudo -u postgres. NOLOGIN, no passwords, zero production table grants.
* Backup schedule gap: last automated backup April 21. Pre-migration schema backup taken. Weekly timer needs audit.
* **Phase 1B staging writes COMPLETE** (2026-05-30): `scripts/hermes_staging_ingest.py` created (--dry-run default, --apply required). 5/5 tests pass (3 negative). Smoke row id=2 in hermes_memory_events. Production unchanged.
* **Phase 1C read access map COMPLETE** (2026-05-30): 392 tables audited, 32 ALLOW, 8 ALLOW_WITH_MASK, 14 DENY, 6 NEEDS_REVIEW. 8 safe view drafts + grant drafts written. No grants applied.
* **Hermes gateway live** (2026-05-30): port 18790, 0.0.0.0, Bearer auth. Chat page at /v2/hermes. Proxy via /api/v2/hermes/chat (key stays server-side).
* **gemma3:12b tool-use incompatibility**: Ollama gemma3:12b does not support tool-calling mode. Hermes config set to `disable_tools: true`. If future Hermes agents need tool-use, evaluate gemma3:27b or Gemma4 31B.
* **Ollama binding changed**: OLLAMA_HOST=0.0.0.0:11434 (was 127.0.0.1). Accessible via Tailscale. Config in zz-tradeai-llm-safety.conf.
* **Weekly version check cron**: Sundays 06:00, writes to data/state/system_versions_latest.json (14 packages tracked).
* **Future: Hermes agent workflows/orchestration dashboard** — define 5 pilot agents as scheduled workflows, show run history/outputs/schedules in Hermes Chat sidebar. Requires separate approval.
* **Phase 1D safe views and grants APPLIED** (2026-05-30): 8 hermes_v_* views created (account-masked, blob-excluded), 40 SELECT grants to hermes_readonly. Pipeline health view column mismatch fixed. 76K+ rows accessible.
* **Hermes system prompt fixed** (2026-05-30): Injected date, role identity, and anti-hallucination guardrails. Hermes no longer fabricates prices, index levels, or cites inaccessible sources.
* **Phase 1D VERIFIED** (2026-05-30): Independent verification — 8/8 views, 46 SELECT-only grants, 14 denied tables confirmed, zero Hermes embeddings, zero production writes. All checks PASS.
* **Session closed** (2026-05-30): 29 commits. Closeout doc at `docs/hermes/HERMES_PHASE1D_SESSION_CLOSEOUT.md`.

### Hermes Current Allowed State
- Sidecar installed with headless browser (Playwright + Chromium)
- 6 staging tables, 8 safe views, 37 direct table grants, roles/grants active
- Controlled staging ingestion script, gateway on :18790, Chat at /v2/hermes
- 4 staged research rows (FLYW id=1, SPRC id=2, SCHD id=3, APPS id=4)
- Headless browser tested PASS (Yahoo Finance)

### Hermes Current Prohibited State
- No embeddings, no content_embeddings writes, no production promotions
- No dashboard Hermes Challenger, no daemon/cron
- No broker/proposal/trade/journal mutation
- No external API/web research via Hermes agents (browser installed but not agent-integrated)

### Phase 1E+1F Complete
- **Phase 1E** (2026-05-30): FLYW thesis challenge, staged id=1
- **Phase 1F** (2026-05-30): Batch of 5 tasks, 3 staged (SPRC id=2, SCHD id=3, APPS id=4), 2 rejected (pipeline/agent system tasks — model needs prompt refinement for non-ticker tasks)
- hermes_research_intelligence: 4 rows total (1 from 1E + 3 from 1F)
- Ingestion script `alpaca` false-positive fixed
- All using gemma3:12b, local Ollama only, zero external APIs, zero production writes

### Hermes Research Sources (current)
- Hermes reads from approved Trade AI safe views (DB): ticker snapshots, proposals, trades, news, agent results, pipeline health, embeddings metadata, intelligence entities
- **Headless browser ENABLED** (2026-05-30): Playwright + Chromium installed in sidecar, agent-browser npm package installed. Hermes can scrape public pages, read articles, check charts — all local, no cloud APIs.
- Browser test PASS: Yahoo Finance AAPL page fetched successfully.
- NOT connected to: Google API, social media APIs (direct), broker APIs
- Trade AI's existing pipelines already provide: news, social, YouTube, SEC, FRED data via DB

### Source Discovery Design (2026-05-30)
- `hermes_research_sources` table designed: per-ticker source portfolios, quality scoring (0-1), discovery workflow, staleness detection
- Seed sources identified: Yahoo Finance, Seeking Alpha, Finviz, Macrotrends, SEC EDGAR, FRED, ETF DB, etc.
- 5-phase implementation: table creation → seed insert → agent integration → source-first research → dashboard
- Not implemented yet — design only

### Phase 1G Quality Review Complete (2026-05-30)
- All 4 rows PASS. Schema compliance 5/5, safety 5/5. Evidence quality 3.5/5, actionability 3.25/5.
- Key findings: challenge_points are questions not findings (rows 2,4), trade reflections need richer context, system tasks fail validation.
- Quality gate checklist created for future ingestion/embedding/promotion decisions.
- Prompt improvements needed: "state findings not questions", include strategy/MFE context for trades, add example output for system tasks.

### Phase 1H Complete (2026-05-30)
- Prompt hardened: `scripts/hermes_research_prompt.py` — facts/inferences separation, assertive findings, missing_data checklist
- Validator hardened: 7 new checks (evidence depth, limitations, confidence calibration, question rejection, external claims, source_views, credentials)
- 9/9 validator tests pass
- 3/3 tasks staged (INFU id=5, ASPN id=6, pipeline id=7) — 100% success (vs 60% in Phase 1F)
- Pipeline task now passes (was 0% in 1F) — hardened prompt fixed it
- hermes_research_intelligence total: 7 rows

### Phase 2A Embedding Pilot Complete (2026-05-30)
- 2 research rows embedded (FLYW id=1, INFU id=5) via nomic-embed-text 768-dim
- content_embeddings ids: 26858, 26859 (source_type='hermes_research')
- hermes_embedding_queue: 2 items, both completed
- RAG retrieval test: Hermes content found with score 0.741 — competitive with Trade AI content
- Embedding worker: `scripts/hermes_embedding_worker.py` (--dry-run default, --apply required)

### Hermes Current Allowed State (post-2A)
- Sidecar installed, gateway :18790, headless browser, Chat at /v2/hermes
- 7 staged research rows, hardened prompt+validator (9/9 tests)
- 2 pilot embeddings in content_embeddings (ids 26858, 26859, source_type='hermes_research')
- Pilot embeddings discoverable via RAG (score 0.741)

### Hermes Current Prohibited State
- No bulk embeddings, no embedding cron/worker automation
- No dashboard Hermes Challenger, no production promotion
- No autonomous research cron, no broker/trade/journal mutation
- No external APIs/Grok/xAI

### Phase 2B Retrieval Audit Complete (2026-05-30)
- 8 queries tested: 7/8 correct. Direct retrieval strong (INFU rank 1, FLYW rank 5). Negative containment perfect. One semantic miss (abstract phrasing). Zero RAG pollution.
- Recommendation: embed remaining 5 rows + limited dashboard preview

### Hermes Current Allowed State (post-2B)
- Sidecar + gateway + browser + Chat page all operational
- 7 staged research rows, 2 embedded (FLYW, INFU), retrievable via RAG
- Retrieval quality audited: 7/8 pass, negative containment perfect, pollution risk LOW

### Hermes Current Prohibited State
- No additional embeddings without Phase 2C approval
- No dashboard Hermes Challenger without approval
- No production promotion, no autonomous cron
- No broker/trade/journal mutation, no external APIs

### Accelerated Phase 2C-2G Complete (2026-05-31)
- **2C**: 5 remaining rows embedded (total 7), dashboard research preview added (advisory-only)
- **2D**: 16-query retrieval audit: 13/16 pass, negative containment 5/5 perfect, RAG pollution LOW
- **2E**: Dashboard safety audit PASS: no mutation controls, advisory labels clear
- **2F**: Source discovery architecture: 3-tier gates defined, zero external APIs configured
- **2G**: All phases closed, rollback files exist for all embedding phases

### Phase 3A Architecture Complete (2026-05-31)
- Autonomous loop architecture designed: 4 loop types (ticker challenger, portfolio reflection, pipeline quality, source discovery)
- Safety controls: kill file, lockfile, row cap (10/day), model cap (15/day), timeout (600s), failure backoff
- 7-gate rollout: 3A arch → 3B dry-run → 3C manual apply → 3D dashboard → 3E timer draft → 3F activation → 3G review
- Draft timer/service/config files created (NOT installed)
- Safety checklist created

### Hermes Current Allowed State (post-3A)
- Sidecar + gateway + browser + Chat + dashboard preview all operational
- 7 staged research rows, 7 embeddings in RAG, retrieval audited
- Phase 3 autonomous loop designed but NOT active
- Draft timer/service/config in docs/hermes/drafts/ (NOT installed)

### Hermes Current Prohibited State
- No autonomous research active, no timers/cron/services installed
- No auto-embedding, no production promotion
- No external APIs, no broker/trade/journal mutation

### Phase 3B-3G Complete (2026-05-31)
- **3B**: Manual dry-run loop 3/3 validated, kill switch PASS, zero DB writes
- **3C**: Manual apply 2/3 staged (FJSCX id=8, TELO id=9), total 9 research rows
- **3D**: Dashboard monitoring added (kill switch + auto loop status)
- **3E**: Timer/service drafts finalized (not installed at that point)
- **3F**: Dry-run timer activated (daily 01:00 UTC, no --apply)
- **3G**: Closeout verified

### Phase 3H-3K Complete (2026-05-31)
- **3H**: Apply-mode activated, 2/2 staged (APAM id=10, TRX id=11)
- **3I**: Observation audit clean, 275.8s, caps enforced
- **3J**: Quality review PASS, at/above Phase 1H baseline
- **3K**: Closeout + operator runbook created
- Timer: active daily 01:00 UTC, `--apply --max-rows 2`
- Total research rows: 11 | Embeddings: 7 | Production: unchanged

### Hermes Autonomous Loop — ACTIVE
- Timer fires daily at 01:00 UTC (9 PM ET)
- Writes up to 2 staged rows per run
- Kill switch: `touch hermes_sidecar/.hermes/DISABLED`
- Operator runbook: `docs/hermes/HERMES_AUTONOMOUS_LOOP_OPERATOR_RUNBOOK.md`

### Phase 4A Promotion Architecture Complete (2026-05-31)
- Promotion target: `llm_intelligence_cache` (safest — advisory cache, namespaced sections)
- 10/11 rows eligible, 1 rejected (TELO confidence 0.2)
- Dry-run completed, zero DB writes
- Rollback strategy documented

### Phase 4B-4E Promotion Pilot Complete (2026-05-31)
- **4B**: 3 rows promoted to llm_intelligence_cache (APPS, INFU, FLYW)
- **4C**: Impact audit PASS — no execution contamination
- **4D**: Dashboard shows promoted/RAG/staged badges
- **4E**: Closeout — 3 audit records, 3 promoted, 8 staged

### Phase 5A-5D Complete (2026-05-31)
- 4 more promoted (total 7), quality PASS, Hermes Intelligence page live at /v2/hermes-intelligence

### Phase 6A-6D Governance Complete (2026-05-31)
- **6A**: Drift audit PASS — zero drift, 17/17 checks
- **6B**: 4 additional loop types designed (pipeline, portfolio, promotion review, source discovery)
- **6C**: Promotion governance model — auto-promotion PROHIBITED, operator checklist created
- **6D**: Closeout

### Phase 7A-7E Pipeline Quality Loop Complete (2026-05-31)
- **7A**: Dry-run 3 findings (failure rate, error pattern, state consistency)
- **7B**: 3 validation findings staged in hermes_validation_findings
- **7C**: Dashboard pipeline quality section live on Hermes Intelligence page
- **7D**: Quality audit PASS
- **7E**: Closeout

### Phase 7F-7G Model Safety Complete (2026-05-31)
- Ollama audit PASS: gemma3:12b local, keep_alive=5m, MAX_LOADED=1, no conflicts
### MASTER Documentation Rewrite (2026-05-31)
- MASTER rewritten: 50+ corrections (39 model refs, 6 strategy counts, portfolio pointer, Hermes section)
- ARCHITECTURE_OVERVIEW + SYSTEM_ARCHITECTURE_COMPLETE archived → consolidated into MASTER
### Phase 8A-8E Portfolio Reflection Loop Complete (2026-05-31)
- 3 reflections staged (stop coverage, stale intel, recovery watch), quality PASS
- Total validation findings: 6 (3 pipeline + 3 portfolio)
### Phase 9A-9D Observation + Infra Planning Complete (2026-05-31)
- **9A**: Stability audit PASS, zero drift
- **9B**: Docker architecture designed (not installed)
- **9C**: Docker readiness checklist + rollback runbook
- **9D**: Closeout
### Full Session Closeout (2026-05-31)
- 101 commits. Hermes P0→P9 complete. MASTER rewritten. Docker designed.
- Full closeout: `docs/hermes/HERMES_FULL_SESSION_CLOSEOUT_2026_05_31.md`
- Operator summary: `docs/project/SESSION_2026_05_31_HERMES_FULL_CLOSEOUT_SUMMARY.md`
### Phase 11 Observation + Docker (2026-05-31)
- **11A**: Observation PASS — zero drift
- **11B**: Docker pilot PASS — Docker 29.5.2 installed, static docs preview built/run/tested/cleaned up
- **11D**: Closeout
- Docker Engine: 29.5.2, Compose: v5.1.4

### Phase 12 Docker Version-Check (2026-05-31)
- **12A-12D**: Version-check pilot PASS — Python 3.13.13, exited cleanly, auto-removed
- Two Docker pilots complete (static docs + version-check), both safe
### Phase 13 Promotion Review Loop (2026-05-31)
- **13A-13D**: Dry-run PASS — 11 reviewed, 7 already promoted, 3 candidates (FJSCX, APAM, TRX), 1 needs evidence (TELO)
- Auto-promotion: PROHIBITED. Quality audit PASS.
### Phase 14 Promotion Review Dashboard (2026-05-31)
- Read-only promotion review section added to Hermes Intelligence page, safety PASS
- Next: promote 3 candidates, source discovery dry-run, or observation

### Documentation A1A Hygiene Pass (2026-05-31)
- Archived 30 files, trashed 15, moved 2.9G backup zip to ~/backups/
- Fixed SKILLS.md: qwen3:14b → gemma3:12b, LLM routing, model policy
- MASTER stale warning removed (rewrite completed)
- Index thinned: 398→138 lines
- Sync exclusions: morning_brief, _trash, .tgz, CLAUDE_CODE_
- Brief generator writes to docs/ root (aegis_morning_brief_delivery.py:403) — fix deferred
- Pre-hygiene snapshot: commit 47b057c, tar ~/doc_hygiene_backup_2026-05-31.tgz

### Deferred Documentation Work
- MASTER rewrite (qwen3:14b refs throughout)
- Architecture trio consolidation (MASTER + OVERVIEW + COMPLETE)
- Morning brief generator output path fix

### Phase 15 Capped Promotion (2026-05-31)
- 3 candidates promoted: FJSCX (id=8), APAM (id=10), TRX (id=11)
- Total promoted: 10, staged: 1 (TELO), cache sections: 10, audit records: 10
- Rollback: `sql/migrations/20260531_hermes_phase15_promote_3_candidates_rollback.sql`

### Phase 16 SearXNG Shared Layer (2026-05-31)
- SearXNG deployed as internal-only shared search infrastructure
- Docker: searxng/searxng:latest, container name: searxng
- Binding: 127.0.0.1:18888 → container 8080
- Public exposure: NONE
- Hermes integration: NONE
- Config: `infra/searxng/` (compose, settings, .env gitignored)
- Safety audit: PASS
- System Applications: Docker Engine + SearXNG visible (read-only)
- Rollback: `cd infra/searxng && sg docker -c "docker compose down -v"`

### Phase 17 SearXNG Manual Wrapper (2026-05-31)
- Manual query wrapper: `scripts/searxng_manual_query.py`
- Localhost SearXNG only (127.0.0.1:18888)
- File-only output: `data/searxng_queries/<timestamp>/` (gitignored)
- Test query: "Trade AI portfolio management architecture" — 15 results, 3 engines
- Sanitization: secrets, IPs, truncation active
- Safety audit: PASS
- DB writes: ZERO | Hermes: NO | Autonomous: NO | Embeddings: ZERO
- CC query visibility: designed (docs only), not implemented

### Next Gate
- Observation period, source discovery dry-run, or CC query visibility (requires approval)

## What to Check First Next Session
1. `git status` and `git log --oneline -5`
2. `.venv/bin/python scripts/check_local_llm_health.py`
3. Check 4 AM enrichment logs for rejected-before-enrichment=0
4. Check escalation queue/retry_cmd logs
5. If Gemma4 31B Tier 3a ran overnight, verify output captured
6. Check `GET /api/v2/atm/execution-readiness` for pending proposals
7. Verify R:R gate is no longer blocking proposals (fixed in 5e6b7fa)
