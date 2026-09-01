# Hermes → Reports/Watchlist Feed + Curated-LLM & Learning Standard (2026-06-07)

Status:      ACTIVE
as_of:       2026-06-07T14:20:29-04:00
Measured at: efcc51365 / not measured

Honest audit of (a) whether Hermes research feeds the daily/weekly/monthly reports + watchlist, and
(b) whether each LLM submission is curated and learns over time. **Findings include real gaps.**

## A. Does Hermes feed the reports/watchlist? (verified, strict)
| Workflow | Owner script | Reads Hermes research / RAG? | LLM call? | Verdict |
|----------|-------------|------------------------------|-----------|---------|
| Daily intelligence report | generate_daily_intelligence_report.py | NO | no | self-contained (holdings/trades) |
| Morning digest / brief | morning_digest.py / aegis_morning_brief_delivery.py | NO direct | yes | LLM on own context, not Hermes |
| Live readiness report | generate_live_readiness_report.py | NO direct | no | self-contained |
| Weekly portfolio review | generate_weekly_portfolio_review.py / generate_weekly_docx.py | NO | no | self-contained |
| Monthly report / advisory / synthesis | portfolio_monthly_report.py / monthly_advisory.py / portfolio_monthly_synthesis.py | NO | yes (6 calls) | LLM on own context, not Hermes |
| **Watchlist** | process_watchlist_agent_jobs.py / materialize_watchlist_research.py | **YES — RAG/embeddings (28 refs)** | yes (12) | **Hermes-fed via promoted RAG** |

**Conclusion:** Hermes is **NOT** directly feeding the daily/weekly/monthly reports today. They build their
own context (holdings/trades) and (where they use an LLM) do so without Hermes research, the central context
engine, or accumulated lessons. The **watchlist** is the one consumer fed by Hermes (via promoted RAG/
content_embeddings). So the answer to "is Hermes feeding research for all reports" is **NO — only the
watchlist (indirectly via RAG); the reports are a gap.**

## B. Internal/External agent mapping for these workflows
| Workflow | Internal owner (model) | External escalation (operator-gated) | Lane |
|----------|------------------------|--------------------------------------|------|
| Watchlist research | process_watchlist_agent_jobs.py (gemma3 + RAG) | new high-conviction watch needs deep validation | Internal deep (gemma3:27b) → Claude/ChatGPT |
| Daily intelligence | generate_daily_intelligence_report.py | unusual regime/risk flagged | ChatGPT (synthesis) / Grok (narrative) |
| Weekly review | generate_weekly_portfolio_review.py | strategy mix underperforming | Claude / ChatGPT |
| Monthly advisory | monthly_advisory.py | tax/retirement/SSDI/IRMAA-sensitive month-end | Claude (high-stakes) |
| Recovery watch | recovery_watch_daily.py | high-$ position giveback risk | Claude (P0) |

## C. Curated-LLM & Learning Standard (the directive)
Infra that EXISTS: `scripts/llm_context_engine.py` ("Centralized data context builder for ALL LLM prompts")
+ versioned prompt templates in `scripts/prompts/` (v1/v2). Per-trade reviews already version prompts
(STRUCTURED_PROMPT_VERSION) + use summary recovery + deterministic-field stamping.

**Standard — every LLM submission SHOULD:**
1. Build context via `llm_context_engine.build_context(...)` (not ad-hoc strings).
2. Include relevant **Hermes RAG + accumulated lessons** (promoted research, trade_llm_reviews lessons).
3. Use a **versioned prompt template** from `scripts/prompts/` (e.g. `*_v2.md`), not inline prose.
4. Request structured output + validate; recover gracefully; never fabricate.
5. **Feed outcome back** (prediction vs realized → usefulness/calibration) so prompts improve over time.

**Compliance audit (honest):**
- Adopters of the central context engine: **only 2** (llm_context_engine itself + deep_overnight queue).
- The context engine currently injects **DATA context but NOT Hermes RAG/lessons** (0 refs) → gap for "learns over time".
- Report/advisory generators build **ad-hoc prompts** and bypass the engine → not uniformly curated.

## D. Recommended next gates (operator-approved; not done in this audit)
1. Extend `llm_context_engine` to optionally inject Hermes promoted-RAG + recent lessons (`context_type`-scoped).
2. Route the daily/weekly/monthly report + watchlist LLM calls through the context engine + versioned prompts.
3. Add outcome-feedback capture for report/advisory LLM calls (usefulness/calibration → learning loop).
4. Phase it per-workflow (start: monthly_advisory + daily intelligence) with before/after review.

These wire Hermes research INTO the reports AND make every submission curated + self-improving. I can
implement per-workflow on approval.

---
## Wiring pilot — DONE (2026-06-07)
1. **Engine made Hermes-aware:** `llm_context_engine.get_hermes_knowledge(symbol,context_type)` injects
   recent Hermes research findings + recent trade-close lessons; `build_context()` now appends a
   "HERMES RESEARCH & LESSONS" section to EVERY prompt it builds → fixes the "engine lacks RAG/lessons" gap;
   prompts now improve as Hermes learns. Fails open (never blocks a prompt). Verified: 1440-char block;
   build_context(symbol) includes the HERMES section.
2. **First report wired:** `monthly_advisory.py` now appends the Hermes self-learning block to its context,
   so the monthly advisory benefits from accumulated Hermes intelligence (weak-strategy findings, thesis
   challenges, lessons). Advisory-only; additive; fails open.

### Next (operator-gated)
- [DONE 2026-06-07] `generate_daily_intelligence_report.py` now surfaces a Hermes research feed (24h count + top weak-strategy/thesis/deep-research findings) in the report + Telegram output. (Data-report; no LLM, so Hermes findings are surfaced as content.) [morning digest DONE 2026-06-07: _ollama_narrative prepends the cached Hermes self-learning block to all digest narratives.]
- Migrate ad-hoc report prompts to versioned templates in scripts/prompts/.
- Add outcome-feedback capture (usefulness/calibration) for report/advisory LLM calls.
- [DONE 2026-06-07] monthly_advisory routed OFF paid Claude/OpenAI APIs → FREE local gemma3 (27b fiduciary + 12b alternative; dual-perspective preserved) + Hermes self-learning context. Env overrides MONTHLY_ADVISORY_FIDUCIARY_MODEL / _ALT_MODEL. Legacy paid callers retained but unused.
