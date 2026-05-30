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

## Hermes v4 — Ready for Install Approval

All pre-install gates passed (2026-05-30):

1. `docs/hermes/HERMES_COMPATIBILITY_AUDIT.md` — COMPLETE, no blockers
2. `docs/hermes/HERMES_INSTALL_EXECUTION_PLAN.md` — COMPLETE, 3 gates defined
3. `docs/hermes/HERMES_READ_ONLY_PILOT_PLAN.md` — COMPLETE, 5 agents, 4 phases
4. `docs/hermes/HERMES_PHASE_P0_FINAL_GATE.md` — **GO**, all 7 sections pass
5. `docs/hermes/HERMES_ROLLBACK_PLAN.md` — COMPLETE, `rm -rf hermes_sidecar/`
6. `docs/hermes/HERMES_DATA_INGESTION_ARCHITECTURE.md` — COMPLETE, 4-phase staged pipeline
7. `docs/hermes/HERMES_PREINSTALL_DISCOVERY.md` — COMPLETE, Gate 1 artifacts saved

**Next action:** operator says `Approve Hermes sidecar install.`

Install will:
- Create `hermes_sidecar/` with local venv
- Set `HERMES_HOME=hermes_sidecar/.hermes`
- Configure Ollama-only (no cloud keys)
- Run `hermes version` and `hermes doctor`
- Verify no `~/.hermes` created, no systemd units, no cron
- P0 file-only pilot (no DB writes)

## 6. Do NOT
- Do NOT run classifier apply (3,593/3,593 complete)
- Do NOT change model routing without approval + canary
- Do NOT change ALPACA_MODE or LLM_DISABLE_LIVE_EXECUTION
- Do NOT call Grok, qwen, gemma4 e2b/e4b
- Do NOT run live trading
