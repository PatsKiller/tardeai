# Next Session Runbook — 2026-05-29 Final

Status:      HISTORICAL
as_of:       2026-06-01T21:56:10-04:00
Measured at: efcc51365 / not measured

## 1. Preflight
```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
git status --short
git log --oneline -10
.venv/bin/python scripts/check_local_llm_health.py
grep -E 'ALPACA_MODE|LLM_DISABLE_LIVE_EXECUTION' .env
curl -s http://127.0.0.1:11434/api/ps | jq .
```

## 1b. Visual Check — Backtesting Labels
1. Open screenshot archive: `playwright_journal_backtest_20260529_1506.tgz` ([Drive](https://drive.google.com/file/d/1DY_kup-0QgZyHSfE74ibvLhrJCLYkLqa/view))
2. Confirm labels are clear: Backtest Rows, Strategy Coverage, LLM Review Coverage, source-aware filter text, small-sample badges
3. Confirm LLM Review Coverage tab doesn't look like thousands of live approvals
4. Confirm Trades tab distinguishes replay from champion via Source column
5. If labels still confusing, create UI polish patch only — no DB/trading changes

## 2. Check Pre-Market Enrichment Health
```bash
# Check for rejected-before-enrichment (should be 0)
PGPASSWORD='...' psql -h localhost -U trade_ai -d trade_ai -c "
SELECT COUNT(*) FROM paper_trade_proposals
WHERE status = 'REJECTED'
  AND enrichment_status NOT IN ('COMPLETE','FAILED')
  AND created_at > NOW() - INTERVAL '24 hours'"

# Check enrichment success rate
PGPASSWORD='...' psql -h localhost -U trade_ai -d trade_ai -c "
SELECT enrichment_status, COUNT(*) FROM paper_trade_proposals
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY enrichment_status"
```

## 3. Check Escalation Logs
```bash
# Check if Gemma4 31B Tier 3a ran
grep -r "gemma4" logs/escalation_* 2>/dev/null | tail -10
# Check retry_cmd execution
grep -r "retry_cmd" logs/escalation_* 2>/dev/null | tail -10
```

## 4. Validate Lifecycle Inspector
```bash
curl -s "http://127.0.0.1:7777/api/v2/paper-proposals/lifecycle-inspector?proposal_id=10" | python3 -m json.tool | head -20
```

## 5. Remaining Work Checklist
- [ ] Add UI "Inspect" button on PaperProposals.tsx (P2)
- [ ] Add retry history UI/dashboard (P2)
- [ ] Observe 4 AM enrichment cycle results
- [ ] Observe Gemma4 31B Tier 3a natural escalation result
- [ ] Continue journal/automated-trading validation if warnings
- [ ] Consider 50+ llama.cpp canary dry-runs before routing change

## Hermes — Phase 1H Complete, Phase 2A Next

All phases through 1H completed and closed (2026-05-30, 42+ commits):

| Phase | Status | Key Result |
|-------|--------|------------|
| P0 Install | COMPLETE | hermes-agent 0.15.2, headless browser, gateway :18790 |
| P1 Tables | COMPLETE | 6 hermes_* tables, 34 indexes, 18 constraints |
| P1A Roles | COMPLETE | hermes_readonly + hermes_staging_writer |
| P1B Writes | COMPLETE | Ingestion script, smoke row |
| P1C Map | COMPLETE | 392 tables audited, 32 allow / 14 deny |
| P1D Views | VERIFIED | 8 views, 46 SELECT grants |
| P1E Research | COMPLETE | FLYW id=1 |
| P1F Batch | COMPLETE | SPRC id=2, SCHD id=3, APPS id=4 |
| P1G Review | PASS | All 4 rows pass, improvements identified |
| P1H Hardening | COMPLETE | INFU id=5, ASPN id=6, pipeline id=7 (100% success) |

**hermes_research_intelligence: 7 rows, all staged. Zero embeddings, zero production writes.**

**Phase 2A embedding pilot: COMPLETE (2 rows, RAG score 0.741)**

**Accelerated Phase 2C-2G: ALL COMPLETE**

| Phase | Status | Key |
|-------|--------|-----|
| 2C | COMPLETE | 7 total embeddings, dashboard preview live |
| 2D | COMPLETE | 13/16 retrieval pass, negative 5/5 |
| 2E | COMPLETE | Dashboard safety PASS |
| 2F | COMPLETE | Source discovery gates defined |
| 2G | COMPLETE | Closeout verified |

**Phase 3A architecture: COMPLETE, closed at `cec3189`**

**Phase 3B-3K: ALL COMPLETE — autonomous loop ACTIVE**

Timer: active (daily 01:00 UTC, APPLY mode --max-rows 2)
Research rows: 11 | Embeddings: 7 | Gateway: active

Operator runbook: `docs/hermes/HERMES_AUTONOMOUS_LOOP_OPERATOR_RUNBOOK.md`

**Phase 4A-5D: ALL COMPLETE — 10 rows promoted, Hermes Intelligence page live**

Promoted: APPS, INFU, FLYW, SPRC, SCHD, ASPN, SYSTEM, FJSCX, APAM, TRX | 1 staged (TELO)
Intelligence page: /v2/hermes-intelligence

**Phase 6A-6D: COMPLETE — governance audit, loop architecture, promotion governance**

**Phase 7A-7E: COMPLETE — Pipeline Quality Loop staged + dashboard**

**Phase 7F-7G: Model safety PASS — no changes needed**

**Phase 8A-8E: COMPLETE — Portfolio Reflection staged + quality PASS**

**Phase 9A-9D: COMPLETE — stability PASS, Docker architecture designed**

**Phase 11-12: Observation PASS, 2 Docker pilots PASS (static docs + version-check)**

**Phase 13: Promotion Review dry-run PASS — 3 candidates (FJSCX, APAM, TRX)**

**Phase 14: Promotion Review dashboard PASS — read-only preview live**

**Phase 15: Capped Promotion COMPLETE — FJSCX, APAM, TRX promoted (10 total, 1 staged)**

**Phase 16: SearXNG Shared Layer COMPLETE — internal-only on 127.0.0.1:18888**

**Phase 17: SearXNG Manual Query Wrapper COMPLETE — file-only, safety PASS**

**Phase 18: Source Discovery Dry-Run COMPLETE — 5 queries, 10 candidates, quality 4.5/5**

**Phase 19: Staged Source Ingestion COMPLETE — 5 rows staged (ids 12–16), safety PASS**

**Phase 20: Agent Model + Actionability Standard COMPLETE — 7 agents, 16 fields, gate defined**

**Phase 21: Librarian Dry-Run COMPLETE — 18 rows reviewed, PASS (4.6/5)**

**Phase 22: Research Backlog Staged-Write COMPLETE — 5 items staged (ids 19–23), safety PASS**

**Phase 23: Income-Rotation Research COMPLETE — 8 queries, 55 candidates, 7 sleeves scored, actionability 0.78**

**Phase 24: Research Backlog Dashboard COMPLETE — read-only card + GET API, safety PASS**

**Phase 25: Embedding Curator Dry-Run COMPLETE — 2 pilot recs (SCHD id=12, TRX id=13), safety PASS**

**Phase 28: Trade AI Coverage Audit COMPLETE — 4/10 surfaces covered, 4 views needed, 13 backlog types**

**Phase 29: Safe View Coverage COMPLETE — 4 views created, coverage 4/10 → 9/10**

**Phase 30: Expanded Librarian Dry-Run COMPLETE — 21 findings, 11 backlog candidates, PASS (4.25/5)**

**Phase 32: Expanded Backlog Staging COMPLETE — 5 rows staged (ids 24–28), 10 total backlog**

**Phase 31: Embedding Pilot COMPLETE — SCHD (0.852) + TRX (0.736), retrieval PASS, RAG LOW**

**Phase 33: Automation Model Audit COMPLETE — Level 3 maturity, 7 levels defined, Phases 34–40 mapped**

**Phase 34: Observation Automation COMPLETE — daily 06:30 UTC timer active, 12/12 checks PASS**

**Phase 35: Backlog Health Automation COMPLETE — daily 06:45 UTC timer active, 10 items, 2 high**

**Phase 36: Cron Consolidation Audit COMPLETE — 187 jobs audited, migration Phases 41–46 planned**

**Phase 37: Low-Latency Bridge Design COMPLETE — queue table + LISTEN/NOTIFY, <60s SLA**

**Phase 41: Systemd Migration Wave 1 COMPLETE — 5 timers, 11 cron lines disabled (187→176)**

**Phase 42: Market Scan Consolidation COMPLETE — 13 duplicates, pipeline designed (not implemented)**

**Phase 46: Job Health Dashboard COMPLETE — GET API + UI card, zero action buttons**

**Phase 44: Event Queue Pilot COMPLETE — hermes_advisory_events table, 60ms latency**

**Phase 38: Backlog Source Discovery COMPLETE — 6 queries, 40 candidates**

**Phase 47: Scheduled Source Discovery Dry-Run COMPLETE — daily 07:15 UTC timer**

**Phase 48: Source Discovery Staged Write COMPLETE — 3 rows staged (ids 29–31)**

**Phase 49: Autonomous Librarian Loop COMPLETE — daily 07:45 UTC, max 5 rows/day, Level 5**

**Phase 50: Level 5 Governance COMPLETE — READY_FOR_PHASE51, all checks PASS**

**Phase 51: Advisory Cache Worker COMPLETE — hourly 08:00-22:00 UTC, Level 6 infra active**

**Phase 52: Review Automation COMPLETE — daily 08:15 UTC, embed/promote recommendations only**

**Phase 53: High-LLM Scheduler COMPLETE — priority formula, quota, dry-run, Phases 54–60 planned**

**Phase 54–60: High-LLM Queue COMPLETE — tables, routing (Hermes+journal+overnight), dashboard, pilot**

**Phase 61–66: Contention fix, Gemma 4 canary (NOT_AVAILABLE), retry (1/3), timer, parallel comparison, Level 6 STABLE**

**Phase 67–71: Incident remediation, alert dedupe, maturity cert, ops backlog, feed resilience**

**Phase 72: Finviz Recovery — 2/3 clean runs (cookie updated, recovery confirmed)**

**Phase 73: Alert Dedupe Applied — dedupe wrapper + false-fixed gate live**

**Phase 74: Feed Health Dashboard — GET /api/v2/system/feed-health**

**Phase 75: LEVEL6_CERTIFIED (conditional on 14:00 3rd clean run)**

**Phase 76: Feed Preflight COMPLETE — finviz_feed_preflight.py, HEALTHY**

**Phase 77: Self-Learning Maturity 8.1/10, Phases 78–86 roadmap**

**Phase 78–82: LEVEL6_CERTIFIED_STABLE, expanded discovery, cache scored, LLM stabilized, 2nd embedding batch**

**Phase 83–87: Promotion review, self-learning dashboard, recertified, Level 7 boundary, 2 promoted**

**Phase 88–90: Auto-promotion policy, shadow (3 eligible), veto queue, first auto-promotion (TRX id=16)**

**Phase 91–93: Dashboard drill-through — clickable cards, lanes, agents, timeline, detail drawer**

SearXNG: running | Hermes rows: 42 | Embeddings: 12 | Cache: **13** | Promoted: **13** | Timers: 9
Dashboard: /v2/self-learning-overview LIVE with drill-through + detail drawer + timeline
Self-learning: **8.1/10** | Level 6: **RECERTIFIED** | Level 7: **PROHIBITED**

**Phase 94–96: Auto-promotion STABLE_KEEP, shadow 2/26 eligible, UX 6.5/10 with P0/P1 backlog**

**Phase 97–100: Visual upgrade (UX 8.0), SCHD auto-promoted, LEVEL6_PRODUCTION_GRADE_WITH_LIMITS**

**Phase 101–106: Observation PASS, overnight retired, 3rd auto-promotion, Recharts live, action design, Level 7 discussion**

**Phase 107+108: Dashboard redesigned as operator workflow cockpit — UX 8.8/10**

**Phase 109: Dashboard URL state, breadcrumbs, click affordance — operator to verify in browser**

**Phase 111: Authority boundary scorecard + SYS→actionable categories**

**111 phases completed. Self-learning maturity: 8.3/10.**

Hermes: 42 rows | 15 promoted | 12 embeddings | 15 cache | 14 timers | 3 auto-promotions
Dashboard: SYS replaced with OPS_FEED/OPS_AGENT/STRATEGY/PORTFOLIO/RESEARCH categories
Authority: 6A (advisory) → progressive ladder defined → Level 7 PROHIBITED

Daily check:
```bash
journalctl --user -u hermes-autonomous-loop.service -n 10 --no-pager
sg docker -c "docker compose -f infra/searxng/docker-compose.yml ps"
```
- No broker/proposal/paper_trades/journal mutation

Rollback Hermes: `rm -rf hermes_sidecar/` + `psql -f sql/migrations/20260530_hermes_phase1_staging_tables_rollback.sql`
Rollback SearXNG: `cd infra/searxng && sg docker -c "docker compose down -v"`

## Session 2026-06-01 Additions (Phases 112–169)

### New Dashboard Pages
- `/v2/alert-siem` — SIEM normalized alert dashboard
- `/v2/proposal-sandbox` — file-only proposal drafts
- `/v2/dual-opinion` — TradeAI vs Hermes side-by-side
- `/v2/queue-control-tower` — 30 timers, 172 crons, categorized

### Key Infrastructure
- Inline dual-opinion panels on 12 pages with evidence drawer + choice capture
- Shadow scorer timer Mon-Fri 10/14/18 ET
- Momentum catalyst timer Mon-Fri 8AM-3PM every 15min
- Telegram gate: 12 noise patterns suppressed
- Journal hold_time capture fixed on all close paths
- Strategy YAML: timestamp-only changes (validated PASS)
- 24 learning queue candidates, 3 high-LLM reviews completed
- Evidence remediation: 10/10 improved via SearXNG

### Tuesday Morning Checklist
1. Verify catalyst timer fired at 8 AM: `systemctl --user status hermes-momentum-catalyst-morning.timer`
2. Check catalyst JSONL: `ls data/hermes/momentum_catalysts/`
3. Check shadow scorer: `ls data/learning/shadow_scores/`
4. Verify SIEM dashboard: `http://localhost:7777/v2/alert-siem`
5. Verify Queue Control Tower: `http://localhost:7777/v2/queue-control-tower`
6. Check operator choices: `curl http://localhost:7777/api/v2/hermes/advisory-choices`
7. Verify Telegram noise reduction (should be fewer alerts)

## 6. Do NOT
- Do NOT run classifier apply (3,593/3,593 complete)
- Do NOT change model routing without approval + canary
- Do NOT change ALPACA_MODE or LLM_DISABLE_LIVE_EXECUTION
- Do NOT call Grok, qwen, gemma4 e2b/e4b
- Do NOT run live trading
