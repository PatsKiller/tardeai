# Session 26B: LLM Review Pipeline + GPU + Incubator Screener + Holdings Refresh
**Date:** 2026-05-08
**Scope:** LLM fallback fixes, GPU enablement, toll gate queue, 4-chunk reviews, incubator LLM screening, holdings LLM health, duplicate prevention, cron hardening

## 1. LLM Fallback Chain — 3 Bugs Fixed

| Bug | File:Line | Fix |
|-----|-----------|-----|
| Ollama timeout too short | `local_llm.py:28` | `DEFAULT_TIMEOUT` 120 → 300s |
| Invalid OpenAI model | `local_llm.py:26` | `gpt-5.4-mini` → `gpt-4o-mini` |
| Anthropic NameError | `local_llm.py:158` | `f"claude-{FALLBACK_MODEL}"` → `FALLBACK_ANTHROPIC` (fixed undefined var + double prefix) |

## 2. GPU Enabled for Ollama (Survives Reboot)

**Root cause:** Ollama 0.20.6 requires `OLLAMA_VULKAN=1` for Intel Arc. Was running qwen3:14b on CPU (0/41 layers, ~300s timeouts).

**Fix:** `/etc/systemd/system/ollama.service.d/override.conf`:
```ini
[Service]
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_VULKAN=1"
Environment="OLLAMA_NUM_GPU=-1"
```
**Result:** 41/41 layers on Intel Arc Pro B50 via Vulkan. ~15s per chunk (was 300s timeout).
**Docs:** `docs/GPU_OLLAMA_SETUP.md`

## 3. 4-Chunk Review Pipeline

Single monolithic prompt couldn't complete within timeout. Split into 4 chunks with state machine:

| Chunk | Content | Fields | Avg Time |
|-------|---------|--------|----------|
| 1. Analysis | bull/bear/technical/catalyst/rr | 5 | ~15s |
| 2. Decision | summary/decision/confidence/conditions | 5 | ~13s |
| 3. Risk | position sizing/correlation/drawdown/grade | 5 | ~13s |
| 4. Catalyst | type/freshness/uniqueness/timing/grade | 5 | ~8s |

**State machine:** Chunks persist in `llm_review_chunks` JSONB column. `llm_review_stage` tracks progress. On re-run, only missing chunks execute. Enrichment loop resets stage when data changes materially (tech refresh, zone change, >10% drift, new catalyst).

**Results (11/11 proposals reviewed):**
- All completed on qwen3:14b GPU, 0 errors
- FNKO consistently WAIT_FOR_DATA (missing technical)
- ~45-60s per complete 4-chunk review when GPU uncontested

## 4. Toll Gate Queue (GPU Contention Prevention)

**Root cause:** 34 stacked `proposal_research_packet_builder.py` + `process_watchlist_agent_jobs.py` flooding Ollama concurrently.

**Fix — Two layers:**

**a) `local_llm.py` toll gate:**
- `fcntl.flock()` on `/tmp/ollama_llm_gate.lock`
- All `generate()` calls acquire exclusive lock before Ollama
- One process at a time; others queue up to 600s then fall through to cloud
- Warmup also acquires gate

**b) Cron flock guards:**
`flock -n /tmp/<name>.lock` on all stacking-prone crons:
- `proposal_research_packet_builder.py`
- `process_watchlist_agent_jobs.py` (4 entries)
- `proposal_enrichment_loop.py`
- `proposal_llm_review_worker.py` (3 entries)
- `incubator_llm_screener.py`
- `holdings_llm_refresh.py`

## 5. Incubator LLM Screener (NEW)

**Script:** `scripts/incubator_llm_screener.py`

Lightweight LLM pre-screen for incubator candidates before promotion. Enriched with:
- Catalyst data (verified/unverified)
- Recent news headlines (7 days, up to 5)
- Social mentions (7 days, up to 3)
- Technical indicators (RSI, ATR, RVOL, confluence)
- Score trends and lifecycle state

**Output:** `screen_grade` (A-F), `verdict` (PROMOTE/HOLD/DROP), `confidence`, `catalyst_assessment`, `momentum`

**Promotion gate:** Promoter now requires grade A or B. Grade C/D/F = HOLD. Verdict DROP = blocked.

**Schema:**
```sql
ALTER TABLE incubator_universe ADD COLUMN llm_screen_grade TEXT;
ALTER TABLE incubator_universe ADD COLUMN llm_screen_verdict TEXT;
ALTER TABLE incubator_universe ADD COLUMN llm_screen_confidence INTEGER;
ALTER TABLE incubator_universe ADD COLUMN llm_screen_model TEXT;
ALTER TABLE incubator_universe ADD COLUMN llm_screen_result JSONB;
ALTER TABLE incubator_universe ADD COLUMN llm_screen_at TIMESTAMPTZ;
```

**Test results (5 candidates):**
| Symbol | Grade | Verdict | Conf |
|--------|-------|---------|------|
| AVTX | C | HOLD | 45 |
| BDSX | C | HOLD | 55 |
| BLBD | B | PROMOTE | 65 |
| BLMN | B | PROMOTE | 65 |
| BLZE | D | HOLD | 30 |

## 6. Holdings LLM Health Refresh (NEW)

**Script:** `scripts/holdings_llm_refresh.py`

Dedicated LLM health check for portfolio positions. Each holding enriched with:
- Latest news (7 days)
- Social mentions (7 days)
- Agent views (Maria, Steph, Risk latest results)
- Technical indicators (RSI, ATR, confluence)

**Output:** `health` (STRONG/STABLE/WATCH/CONCERN/EXIT), `action` (HOLD/ADD/TRIM/EXIT), `thesis_intact`, `catalyst_outlook`, `risk_flag`

**Schema:**
```sql
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_health TEXT;
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_action TEXT;
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_confidence INTEGER;
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_model TEXT;
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_summary JSONB;
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_at TIMESTAMPTZ;
```

**Test results:**
| Holding | Health | Action | Conf |
|---------|--------|--------|------|
| V | STABLE | HOLD | 70 |
| SCHG | STABLE | HOLD | 65 |
| AVAV | WATCH | HOLD | 55 |

**UI:** Health pill on Portfolio page (AI column) and Watchlist page (next to HELD badge).

## 7. Duplicate Proposal Prevention

**Problem:** BLBD/ALGS/FNKO each had 5 pending proposals (one per strategy match).

**Fix — Three layers:**
1. **Promoter:** checks total pending per symbol (not per-run)
2. **DB trigger:** `trg_max_pending_per_symbol` blocks >2 pending per symbol
3. **Cron flock:** prevents stacked promoter runs from racing

**Cleanup:** Expired 9 duplicate proposals, 20 → 11 pending.

## 8. Proposal Sort Order

Changed from `created_at DESC` to `confidence_score DESC, created_at DESC`. Strongest proposals surface first.

## 9. Sector/Strategy Data Gaps

**Sector:** Proposals from incubator had NULL sector. Added sector backfill step (1b) in enrichment loop — copies from latest scan.

**Strategy fit:** `ensure_strategy_identity()` was skipping `screener` proposals because `primary_strategy_id='screener'` was truthy. Fixed to treat `screener` as needing reclassification.

## 10. Midday Social Ingest

Added `social_ingest.py --source all` at 12:35 PM (was only 6:30 AM).

## Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `scripts/incubator_llm_screener.py` | ~290 | Pre-promotion LLM screening with enrichment |
| `scripts/holdings_llm_refresh.py` | ~260 | Holdings health check with news/social/agents/tech |
| `docs/GPU_OLLAMA_SETUP.md` | ~100 | GPU setup, troubleshooting, restore guide |

## Files Changed

| File | Changes |
|------|---------|
| `scripts/local_llm.py` | Toll gate lock, fixed fallbacks, timeout 300s, model tracking all tiers |
| `scripts/proposal_llm_reviewer.py` | 4-chunk pipeline, state machine, compact prompts, None safety |
| `scripts/proposal_llm_review_worker.py` | Warmup, throttle, model in logs |
| `scripts/proposal_enrichment_loop.py` | Stale LLM detection, sector backfill, screener strategy reclassification |
| `scripts/incubator_proposal_promoter.py` | LLM grade gate (A/B only), total pending per symbol check |
| `scripts/api_v2.py` | llm_model_used, llm_review_chunks, llm_review_stage, holdings LLM health in portfolio API, sort by confidence |
| `scripts/full_system_backup.py` | Ollama override.conf in backup scope |
| `apps/.../PaperProposals.tsx` | Model pills, AI Deep Dive section (risk+catalyst grades), chunk progress |
| `apps/.../Portfolio.tsx` | AI health column with pill (STRONG/STABLE/WATCH/CONCERN/EXIT) |
| `apps/.../Watchlist.tsx` | AI health pill next to HELD badge |
| `crontab` | flock guards (10 entries), increased LLM limits, midday social, holdings refresh, incubator screener |

## Schema Changes

```sql
-- Proposals
ALTER TABLE paper_trade_proposals ADD COLUMN llm_model_used TEXT;
ALTER TABLE paper_trade_proposals ADD COLUMN llm_review_stage TEXT;
ALTER TABLE paper_trade_proposals ADD COLUMN llm_review_chunks JSONB;

-- Incubator
ALTER TABLE incubator_universe ADD COLUMN llm_screen_grade TEXT;
ALTER TABLE incubator_universe ADD COLUMN llm_screen_verdict TEXT;
ALTER TABLE incubator_universe ADD COLUMN llm_screen_confidence INTEGER;
ALTER TABLE incubator_universe ADD COLUMN llm_screen_model TEXT;
ALTER TABLE incubator_universe ADD COLUMN llm_screen_result JSONB;
ALTER TABLE incubator_universe ADD COLUMN llm_screen_at TIMESTAMPTZ;

-- Holdings health
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_health TEXT;
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_action TEXT;
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_confidence INTEGER;
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_model TEXT;
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_summary JSONB;
ALTER TABLE watchlist_items ADD COLUMN holdings_llm_at TIMESTAMPTZ;

-- Duplicate prevention trigger
CREATE FUNCTION check_max_pending_per_symbol() ... LANGUAGE plpgsql;
CREATE TRIGGER trg_max_pending_per_symbol ON paper_trade_proposals;
```

## Cron Schedule (LLM-related)

| Time | Script | Limit | Purpose |
|------|--------|-------|---------|
| 7:55 AM | `holdings_llm_refresh.py` | 20 | Morning holdings health |
| 8:10 AM | `incubator_llm_screener.py` | 15 | Pre-promotion screen |
| 8:15 AM | `proposal_llm_review_worker.py` | 10 | Morning proposal reviews |
| 12:30 PM | `proposal_llm_review_worker.py` | 10 | Midday proposal reviews |
| 12:35 PM | `social_ingest.py` | — | Midday social (new) |
| 12:45 PM | `holdings_llm_refresh.py` | 15 | Midday holdings health |
| 6:00 PM | `incubator_llm_screener.py` | 15 | Evening pre-promotion screen |
| 6:30 PM | `proposal_llm_review_worker.py` | 10 | Evening proposal reviews |

## 11. Trade AI Page LLM Integration

**API enrichment:** `/api/v2/trade-ai` now joins incubator screen grades, holdings health, and proposal LLM chunks for every ticker.

**UI — AI Review column:** Shows pills per ticker:
- Incubator grade (A/B/C/D/F) + ↑ for PROMOTE verdict
- Holdings health (STRONG/STABLE/WATCH/CONCERN)
- Risk grade (R:A through R:F) from proposal chunks
- Catalyst grade (C:A through C:F) from proposal chunks

**Detail drawer:** New "AI Review (qwen3:14b)" section showing all LLM data when clicking a ticker.

## 12. Promotion Priority + AVOID Blocking

**Promoter query** now:
- Joins `trade_ai_scans` to get latest scan decision
- Blocks AVOID tickers entirely (excluded from candidates)
- Blocks `llm_screen_verdict = 'DROP'`
- Sorts GO before WAIT at same score level

**Screener prompt** includes scan decision (GO/WAIT/AVOID) in context. Instructs LLM: "If scan=AVOID, verdict should be DROP unless strong catalyst overrides."

## 13. Telegram Notifications

Screener sends Telegram alert after each run:
- Summary: screened/PROMOTE/HOLD/DROP counts
- PROMOTE list with reasoning, catalyst assessment, momentum
- DROP list with reasoning

## Screener Results (Full Run — 13 unique symbols)

| Symbol | Grade | Verdict | Conf | Notes |
|--------|-------|---------|------|-------|
| BLBD | B | PROMOTE | 65 | Ready for promotion |
| BLMN | B | PROMOTE | 65 | Ready for promotion |
| AVTX | C | HOLD | 45 | |
| BDSX | C | HOLD | 55 | |
| CURR | C | HOLD | 45 | |
| EVC | C | HOLD | 45 | |
| FTRE | C | HOLD | 55 | |
| KVHI | C | HOLD | 50 | |
| MNKD | C | HOLD | 45 | |
| NNE | C | HOLD | 55 | |
| OSG | C | HOLD | 55 | |
| EVER | D | HOLD | 30 | Weakest candidate |
| BLZE | D | HOLD | 30 | |

## Pipeline Flow

```
Screener → Incubator (score tracking, days_active)
                ↓ score >= 40
         LLM Screen (news/social/catalyst/tech + scan decision)
                ↓ grade A or B, verdict != DROP, scan != AVOID
         Promoter (GO first → WAIT second, max 2/symbol, DB trigger)
                ↓
         Paper Proposals → 4-chunk LLM Review (analysis→decision→risk→catalyst)
                ↓ stale data → re-review
         Enrichment loop resets stage

Trade AI page → AI Review column + detail drawer (all LLM data)
Holdings → LLM Health 2x/day → Portfolio + Watchlist + Trade AI pages
Telegram → PROMOTE/DROP alerts after each screener run
```
