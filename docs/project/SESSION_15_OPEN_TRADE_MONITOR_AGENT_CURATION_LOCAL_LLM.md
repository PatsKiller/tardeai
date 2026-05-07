# Session 15 — Open Trade Monitor + Agent Curation Loop + Local LLM Post-Trade Analysis

**Completed:** 2026-05-06

---

## Scripts Created

| Script | Purpose |
|--------|---------|
| `scripts/open_trade_monitor.py` | 15-min intraday monitor for open paper trades. Checks near-stop, near-target, stale, extended profit, negative news. Sends Telegram for WARN/CRITICAL. |
| `scripts/agent_curation_hooks.py` | Master `on_paper_trade_closed()` hook. Calls Iris, Aegis, outcome lessons, pattern confirmation. Non-blocking. |
| `scripts/paper_trade_analyzer.py` | Overnight LLM analysis of closed paper trades. Uses `local_llm.py` (Ollama qwen3:1.7b) with cloud fallback. |
| `scripts/session15_validate.py` | 25-check validation suite for all Session 15 deliverables. |

---

## Tables Created

| Table | Purpose |
|-------|---------|
| `open_trade_alerts` | Per-trade alerts with dedup (NEAR_STOP, NEAR_TARGET, STALE_TRADE, EXTENDED_PROFIT, NEGATIVE_NEWS) |
| `paper_trade_analysis` | LLM analysis results (summary, worked_reasons, failed_reasons, lessons, confidence) |
| `agent_curation_events` | Iris/Aegis/system curation events (IRIS_OUTCOME_WRITEBACK, AEGIS_POST_TRADE_SYNTHESIS, etc.) |
| `local_llm_runs` | LLM run tracking (model, status, duration, items processed/failed) |

### Enriched Tables

- `paper_trades`: added `monitored_at`, `last_alert_at`, `stale_flag`, `thesis_status`, `post_trade_analyzed`, `iris_curated`, `aegis_summarized`
- `paper_trade_proposals`: added `quality_pass`, `quality_reason_codes`, `hidden_by_quality_filter`

---

## APIs Added

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v2/open-trade-monitor` | GET | Open trades, alerts, summary (open_count, critical/warn alerts, stale, unrealized P&L) |
| `/api/v2/paper-trade-analysis` | GET | Recent LLM analyses + awaiting count |
| `/api/v2/agent-curation-events` | GET | Recent Iris/Aegis/LLM events |
| `/api/v2/local-llm-status` | GET | Ollama availability, model, last run, awaiting counts |

---

## UI Changes

### PaperStatus.tsx
- Open Trade Monitor tile (open count, critical/warn alerts, stale, unrealized P&L, open risk)
- Local LLM tile (available, model, last run status, items processed, trades/proposals awaiting)
- Agent Curation tile (total events, recent events by agent)
- Recent Alerts section for WARN/CRITICAL

### PaperJournal.tsx
- Added columns: Analyzed, Iris, Aegis (Y/- indicators)
- Expandable trade rows: click any closed trade to see LLM analysis, Aegis synthesis, Iris events, trade alerts
- Two-column detail layout in expanded area

### PaperProposals.tsx
- Quality filter: top 5 default, show-all toggle
- Countdown timer with color (green >90min, amber 30-90min, red <30min)
- Quality reason codes displayed for low-quality proposals
- Inline editing: Edit button toggles editable fields for shares/entry/stop/target
- Auto-recompute of Risk $ and R:R on edit
- Modified proposals approve with overrides

---

## Agent Roles

| Agent | Responsibility |
|-------|---------------|
| Maria | Catalyst/news validation, source quality — owns NEGATIVE_NEWS alerts |
| Risk | Entry/stop/target structure — owns NEAR_STOP, NEAR_TARGET, STALE_TRADE alerts |
| Iris | RAG librarian, outcome memory — IRIS_OUTCOME_WRITEBACK events, writes to `agent_intelligence_rules` |
| Aegis | Desk supervisor — AEGIS_POST_TRADE_SYNTHESIS, whiteboard updates |
| Risk Gate | Deterministic authority — proposal quality gate, never overridden by LLM |

---

## Iris Writeback Behavior

On paper trade close:
1. Writes `IRIS_OUTCOME_WRITEBACK` event to `agent_curation_events`
2. Writes/updates `agent_intelligence_rules` with `rule_type='outcome_lessons'`, `rule_key='paper_trade_latest'`
3. Maintains rolling list of last 50 outcome lessons
4. Sets `paper_trades.iris_curated = true`

---

## Aegis Synthesis Behavior

On paper trade close:
1. Generates one-paragraph synthesis (verdict, thesis held/failed, catalyst status, RVOL pattern, hold time)
2. Writes `AEGIS_POST_TRADE_SYNTHESIS` event to `agent_curation_events`
3. Attempts write to `intelligence_whiteboard` (ON CONFLICT DO NOTHING)
4. Sets `paper_trades.aegis_summarized = true`

---

## Local LLM Model/Status

- **Model:** qwen3:1.7b via Ollama (localhost:11434)
- **Available:** true
- **Fallback chain:** qwen3:1.7b -> OpenAI gpt-5.4-mini -> Claude Sonnet
- **Graceful degradation:** if Ollama unavailable, all deterministic monitoring continues

---

## Open Trade Monitor Rules

| Alert | Condition | Severity |
|-------|-----------|----------|
| NEAR_STOP | price <= entry - 0.75 * (entry - stop) | CRITICAL |
| NEAR_TARGET | price >= entry + 0.80 * (target - entry) | INFO |
| STALE_TRADE | age > 3h AND abs(R) < 0.5 | WARN |
| EXTENDED_PROFIT | R >= 1.5 | INFO |
| NEGATIVE_NEWS | headline contains offering/dilution/halt/etc. since entry | WARN |

Dedup: same alert type per trade throttled to 30-minute intervals.

---

## Crons

```
*/15 9-16 * * 1-5  open_trade_monitor.py --once
0 3 * * 1-6        paper_trade_analyzer.py --limit 25
```

---

## Proposal Quality Filter

| Rule | Threshold | Reason Code |
|------|-----------|-------------|
| Score | >= 45 | SCORE_TOO_LOW |
| Intel readiness | >= 50 | INTEL_TOO_THIN |
| Catalyst/RVOL | verified OR rvol >= 8 | NO_VERIFIED_CATALYST_OR_HIGH_RVOL |
| Risk gate | approved | RISK_GATE_REJECTED |
| Duplicate | no pending same symbol+strategy | DUPLICATE_PENDING_PROPOSAL |

Non-passing proposals stored with `quality_pass=false`, `hidden_by_quality_filter=true`.

---

## Validation Results

```
SESSION 15 VALIDATION: PASSED (25/25)
```

- All 4 tables created
- All 3 scripts parse clean
- All 4 API endpoints return ok=true
- Monitor dry-run: 0 trades, 0 alerts (expected)
- Analyzer dry-run: 0 processed (expected, no closed trades)
- Quality filter: correctly filters score < 45
- Curation hooks wired into close_paper_trade() and alpaca detect_closed_positions()
- Real journal clean: 76 real trades, 0 paper
- No hardcoded secrets in S15 files
- No live Alpaca URLs
- Crons not duplicated
- Holdings: $1,180,862 UNTOUCHED
- Frontend build: clean (166ms)

---

## Known Pre-Existing Issues

- Hardcoded DB password fallback in `trade_ai_news_monitor.py`, `intelligence_entity_manager.py`, `seed_intelligence_entities.py`, `pipeline_registry.py` — pre-existing, not introduced by Session 15

---

## Next Recommended Session

Session 16: Strategy Desk Deep Fix (completed same day)
- Clickable strategy cards with detail panel
- Strategy metadata from YAML
- Trade plan backfill for signals
- Propose button per signal
