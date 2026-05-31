# Next Session Runbook — 2026-05-29 Final

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

**Phase 3B-3G: ALL COMPLETE**

Timer: active (daily 01:00 UTC, DRY-RUN mode — no --apply)
Research rows: 9 | Embeddings: 7 | Gateway: active

**Next gate: Phase 3H — enable apply-mode autonomous loop**

Pre-Phase 3H checks:
1. Verify dry-run timer has fired at least 1 scheduled cycle
2. Review dry-run output quality in logs
3. Confirm kill switch works in scheduled context
4. Confirm row caps enforced
5. Operator explicitly approves changing `--apply` mode
- No broker/proposal/paper_trades/journal mutation

Rollback: `rm -rf hermes_sidecar/` + `psql -f sql/migrations/20260530_hermes_phase1_staging_tables_rollback.sql`

## 6. Do NOT
- Do NOT run classifier apply (3,593/3,593 complete)
- Do NOT change model routing without approval + canary
- Do NOT change ALPACA_MODE or LLM_DISABLE_LIVE_EXECUTION
- Do NOT call Grok, qwen, gemma4 e2b/e4b
- Do NOT run live trading
