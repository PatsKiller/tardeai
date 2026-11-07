# DSN-20261107 — Anthropic-first LLM routing

Status: **OPERATOR-APPROVED DESIGN, 2026-11-07 13:52 ET.** The operator's words: "That's an excellent design." Written by claude-lead. Canonical copy for the server docs; the working copy with private spend figures stays in the coordinator store (DSN-20261107-ANTHROPIC-FIRST-ROUTING.md). Rollout status: the tier map, sub-caps and monthly renewal are LQ-20261107-196 (cc-opus-1); the journal repair and reopening of the lane are lead steps after it; the Model Router and monthly Model Scout are LQ-20261107-197.

## 1. Model equivalence: what replaces what

| Today | Anthropic equivalent | Price per Mtok (in/out) | Use it for |
|---|---|---|---|
| DeepSeek Flash, grok-3-mini | **Haiku 5.5** | $0.10 / $0.50, cheaper than DeepSeek Flash off-peak ($0.15/$0.60) | bulk FAST work: extraction, classification, tagging, short narratives, JSON fill-ins, scoring |
| ChatGPT, Grok (full) | **Sonnet 5.5** | $2 / $10 | reasoning and synthesis: CIO replies, critiques, plan enrichment, research write-ups, diagnosis |
| (none today; Opus was being misused for FAST work) | **Opus 5.5** | higher | PRO_THINK only: CIO verdicts, risk/strategy, architecture, adjudication |
| — | Fable | premium | rare; operator-named only |

Measured reliability, 7 days to 11-03:
- Haiku: 1275 calls, 5 failed.
- Sonnet: 91 calls, 0 failed.
- Opus: 1256 of 1374 calls failed (ANTHROPIC_OUTPUT_INVALID). Opus was handed bulk FAST JSON work it was never meant for.

## 2. Why Anthropic went silent on 11-03 (root cause, verified read-only)

1. The credit journal `persistent-state/data/runtime/provider_cost/anthropic_credit.jsonl` has a half-written last record. It was written at 2026-11-03 09:00 ET, during the disk-full incident (18633 lines; the file ends mid-record at `{"at":"2026-11-03T14:`).
   - `CreditBook._read` fails closed with CREDIT_UNAVAILABLE, by design.
   - Every call since then has fallen through to Grok, ChatGPT and DeepSeek.
2. The same day, 178 calls also hit ANTHROPIC_CREDIT_PROCESS_CAP.
3. The policy maps FAST, FAST_THINK and PRO to "standard", which is Opus. This sent the bulk lanes to the most expensive model, which then failed.

Spend history by model is kept in the private provider-cost journal on the host, not in this public repo. Before the fix, Opus carried most of the spend while Haiku carried most of the calls.

Credit expires 2026-11-16, and `renewal: one_time`.

## 3. Changes (config-first, all dry-run before live)

**A. Credit policy** (`config/anthropic_credit_policy.json`)
- `policy_tiers`: FAST → bulk (Haiku); FAST_THINK → mid (Sonnet); PRO → mid (Sonnet); PRO_THINK → standard (Opus).
- `provider_order`: anthropic → deepseek (off-peak only) → grok (until decommissioned). **ChatGPT removed** (allowance used up).
- `renewal`: monthly. Set `monthly_credit_usd` to the operator's allowance (OPERATOR VALUE). Daily cap = monthly / 30. Roll `expires_at` each month.
- Per-tier daily sub-caps, so Opus cannot eat the month: Haiku 40%, Sonnet 45%, Opus 15%.

**B. Process registry** (`config/llm_process_registry.json`)
- Every process gets a task class (below) and `anthropic_first: true`.
- The 40 processes with empty `allowed_lanes` get `[anthropic, deepseek]`.

**C. Task-type → model matrix** (the router's rule; model_chooser reads it)

| Task class | Examples | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|---|
| extract / classify / tag | news tagging, Hermes ingest, holdings refresh | Haiku | DeepSeek Flash (off-peak) | grok-3-mini* |
| short narrative / summary | watchlist flash narratives, digests | Haiku | DeepSeek Flash | grok-3-mini* |
| score / rank | Hermes usefulness, gap resolver | Haiku | DeepSeek Flash | — |
| reason / synthesize | CIO replies, plan enrichment, research write-ups | Sonnet | Haiku (degraded flag) | grok* |
| critique / fact-check | CIO Ask critique, prospectus/AI-claim check | Sonnet | Haiku | — |
| diagnose ops failure | n8n failure diagnosis, incident supervisor | Sonnet | Haiku | — |
| high-stakes verdict | CIO verdict, risk engine, strategy, adjudication | Opus | Sonnet | **none** (fail closed, alert) |

\* Grok fallback is removed at decommission.

Proposed tiers for the 111 registered processes: 93 Haiku, 11 Sonnet, 7 Opus. The full table is in Appendix A.

**D. Router enforcement**
1. `scripts/lib/model_chooser.py` is in SHADOW today. Its receipts are in `data/runtime/model_chooser_receipts.jsonl`.
2. Rollout:
   - shadow 24 h: compare chosen against executed per process.
   - advise 48 h.
   - enforce. Enforce is set by `TRADEAI_MODEL_CHOOSER`, a config key, with a backup first.
3. Every call logs `requested_policy`, `executed_policy`, `model_name`, `returned_model` and `task_class` to `llm_consumption_log`. That table already exists; `task_class` is a new column.

**E. Ops visibility**
- The LLM-use tab gets a "Routing" view: process → task class → primary/fallback → last-7-day actual model → drift flag.
- A drift alert fires when the executed model is not the primary for more than 10% of a process's calls in a day.

## 4. Sequence

| Step | Action | Owner |
|---|---|---|
| 1 | Fix `policy_tiers` and per-tier caps, **before** reopening the lane, so Opus is not hammered again | Opus worker, LQ |
| 2 | Archive the corrupt journal tail with the built-in `jsonl_tail.quarantine_tail`. It archives the fragment beside the file and never deletes. The Anthropic lane reopens. | lead, after step 1 is proven on a temp PROJECT_ROOT |
| 3 | Set monthly renewal and amount | **operator value** |
| 4 | Remove ChatGPT from `provider_order`; flip the chooser shadow → advise → enforce | lead |
| 5 | Grok decommission: once Anthropic serves 7 days with less than 2% fallback, set grok `allowed: false` and keep the key for rollback. The operator then cancels the plan. | operator |
| 6 | Add the Routing view to Ops › LLM use | Sonnet worker |


## 5. Model Router subsystem and the monthly Model Scout (added 2026-11-07 13:20 ET, operator ask)

The router is its own subsystem, with one owner, one config and one page. It is not spread across call sites.

**5.1 Router parts.** Everything else calls `governed_cloud_generation`, which asks the chooser.

| Part | File | Job |
|---|---|---|
| Model registry | config/llm_model_registry.json | Every allowed model: provider, exact id, price, context, status (active / candidate / retired) |
| Task-class matrix | config/llm_task_classes.json (new) | Task class → primary / fallback 1 / fallback 2 by logical tier (bulk / mid / standard), never by raw model id |
| Process registry | config/llm_process_registry.json | Process → task class, caps, allowed lanes |
| Chooser | scripts/lib/model_chooser.py | The ONE decision point; writes a receipt per call |
| Credit and caps | scripts/lib/anthropic_routing.py and anthropic_credit.py | Admission, per-tier caps, monthly renewal |
| Page | Ops › LLM use › Routing (and › Models) | Shows the table, drift, spend and scout findings |

Tier → model is a single mapping in the model registry: bulk = Haiku, mid = Sonnet, standard = Opus. Upgrading to a new model is a one-line registry change plus an eval. No code changes.

**5.2 Model Scout: monthly n8n lane `llm-model-scout`.** It runs on the 1st at 06:00 ET, plus on demand. It is read-only and advisory.

1. **Discover.** GET each provider's list-models endpoint with the existing keys, through the lane: Anthropic /v1/models, DeepSeek /v1/models, xAI /v1/models while Grok is kept.
   - Reuse the existing connectivity probe pattern (scripts/llm_lane.py).
   - Never log keys.
2. **Diff.** Compare against llm_model_registry.json and flag:
   - new model ids;
   - deprecated or retiring ids (provider deprecation dates);
   - ids we route to that the provider no longer lists. This is P1: a retired model silently breaks a lane.
3. **Price and limits.** Record price per Mtok, context window and output limit for each new model.
   - Use the provider's API metadata where it exists, else a curated price row the lead confirms.
   - Never guess a price.
4. **Eval candidates.** For each new model in a family we use, run the fixed eval set, one per task class: extract, summarize, score, reason, critique, verdict.
   - 20 frozen cases per class, stored in tests/fixtures/llm_eval/. No real holdings data: the repo is PUBLIC.
   - Score JSON validity, accuracy against expected output, latency and cost per case.
   - The eval is capped at $2 per run.
5. **Recommend.** Write data/runtime/llm_model_scout/<YYYY-MM>.json plus a short report. Example: "Haiku 5.6 beats Haiku 5.5 on extract (+4% accuracy, −20% cost): recommend tier bulk → haiku-5-6."
   - The DB table llm_model_scout_runs is the system of record. The JSON is a backup.
6. **Gate.** The scout NEVER changes routing.
   - The lead or operator approves a recommendation.
   - The registry change then goes through the normal fold, with the chooser in advise mode for 48 h before enforce.
7. **Report.**
   - The monthly digest gets a "Models" line.
   - Ops › LLM use › Models shows the current vs latest model per provider, price, eval scores and pending recommendations.
   - A P1 alert fires immediately for "routed model no longer listed".

**5.3 Same audit standard as every lane.** The six checks apply to the scout:
- config;
- runs;
- output row;
- data checked against the provider's published list;
- no hallucinated models (every id must come from the API response);
- the consumer page matches.

Implementation: LQ-20261107-197 (cc-opus-1, queued after LQ-196).

## Appendix A: per-process routing (registry + last 7 days actual)
| process | category | tier now | proposed | used last 7d |
|---|---|---|---|---|
| advisory_desk_opinion | AdvisoryDesk | FAST | Haiku | — |
| advisory_desk_synthesis | AdvisoryDesk | PRO | Sonnet | deepseek-flash×28, Opus×2 |
| l3_independent_critic | AgentRuntime | — | Haiku | grok-3-mini×4 |
| l3_judgment_author | AgentRuntime | FAST | Haiku | — |
| reflective_critic_flash | AgentRuntime | FAST | Haiku | — |
| market_risk_alert_curation | Alerts | — | Haiku | — |
| market_risk_deep_brief | Alerts | — | Haiku | — |
| alex_cio_escalation | CIO | PRO_THINK | Opus | — |
| alex_cio_synthesis | CIO | PRO | Sonnet | — |
| cio_ask_critique_chatgpt | CIO | FAST | Haiku | — |
| cio_ask_critique_deepseek | CIO | FAST | Haiku | deepseek-flash×9 |
| cio_ask_critique_grok | CIO | FAST | Haiku | — |
| cio_ask_deep_research | CIO | FAST | Haiku | — |
| cio_ask_reanswer | CIO | FAST | Haiku | deepseek-flash×8 |
| cio_ask_web_search | CIO | FAST | Haiku | Sonnet×1 |
| cio_operator_reply | CIO | FAST | Haiku | deepseek-flash×59, Opus×18, grok-3-mini×1 |
| cio_plan_enrichment | CIO | FAST | Haiku | deepseek-flash×321, grok-3-mini×53, Opus×8 |
| cio_policy_field_advisor | CIO | FAST | Haiku | — |
| cio_prompt_judge | CIO | FAST | Haiku | — |
| guardian_risk_critique | CIO | FAST | Haiku | — |
| ledger_tax_critique | CIO | FAST | Haiku | — |
| maria_research_critique | CIO | FAST | Haiku | — |
| morgan_wealth_synthesis | CIO | FAST | Haiku | — |
| steph_allocation_review | CIO | PRO | Sonnet | — |
| local_llm_compat | Compatibility | FAST | Haiku | Opus×341, deepseek-flash×340, ×302 |
| defense_weekly_oversight | Defense | FAST | Haiku | grok-3-mini×2 |
| cio_hermes_research | Hermes | FAST | Haiku | deepseek-flash×370, grok-3-mini×114, gpt-6.1-sol×3 |
| cloud_review | Hermes | — | Haiku | ×558 |
| hermes_analyst_coverage | Hermes | — | Haiku | grok-3-mini×2 |
| hermes_cloud_json | Hermes | FAST | Haiku | deepseek-flash×313, Haiku×96, grok-3-mini×3 |
| hermes_cross_source_synthesizer | Hermes | — | Haiku | grok-3-mini×20, ×2, Opus×1 |
| hermes_external_research | Hermes | FAST | Haiku | deepseek-flash×423, Opus×292, ×154 |
| hermes_golden_judge | Hermes | FAST | Haiku | — |
| hermes_tag_engine | Hermes | — | Haiku | — |
| hermes_usefulness_score | Hermes | FAST | Haiku | deepseek-flash×1038, Haiku×377, grok-3-mini×3 |
| hermes_usefulness_score_n8n | Hermes | FAST | Haiku | grok-3-mini×2 |
| incubator_llm_screener | Incubator | FAST | Haiku | grok-3-mini×58, Haiku×18 |
| directive_keyword_enhancer | Intel | — | Haiku | grok-3-mini×42, ×2 |
| iris_taxonomy_agent | Intel | — | Haiku | ×4 |
| llm_intelligence_enrichment | Intel | — | Haiku | ×92 |
| think_tank_signal_miner | Intel | — | Haiku | — |
| grok_execution_review | Journal | — | Haiku | — |
| journal_ask | Journal | FAST | Haiku | — |
| journal_review_builder | Journal | FAST | Haiku | grok-3-mini×94, gpt-6.1-sol×2 |
| multi_tier_trade_reviewer | Journal | FAST_THINK | Sonnet | — |
| conflict_rule_proposal | N8nCoordination | FAST | Haiku | — |
| n8n_lane_failure_diagnosis | N8nCoordination | FAST | Haiku | grok-3-mini×23, deepseek-flash×3 |
| n8n_material_digest_draft | N8nCoordination | FAST | Haiku | — |
| n8n_ops_summary_draft | N8nCoordination | FAST | Haiku | — |
| incident_supervisor | Operations | — | Haiku | ×783, Sonnet×91 |
| pr_independent_review | Operations | — | Haiku | — |
| pr_independent_review_deep | Operations | — | Haiku | — |
| pr_independent_review_oauth | Operations | — | Haiku | — |
| options_ensemble | Options | — | Sonnet | ×404 |
| options_thesis_cio_review | Options | FAST | Haiku | deepseek-flash×121 |
| holding_protection_advisor | Portfolio | — | Haiku | ×203 |
| holding_protection_advisor_batch | Portfolio | — | Haiku | — |
| holdings_llm_refresh | Portfolio | — | Haiku | grok-3-mini×163, ×127, Opus×65 |
| portfolio_ai_analyst | Portfolio | — | Haiku | grok-3-mini×11 |
| portfolio_ask | Portfolio | FAST | Haiku | — |
| portfolio_lookthrough_themes | Portfolio | FAST | Haiku | grok-3-mini×2 |
| portfolio_orchestrator | Portfolio | — | Haiku | ×7 |
| stop_drift_alert | Portfolio | — | Haiku | — |
| proposal_llm_review | Proposals | FAST | Haiku | grok-3-mini×2 |
| analyst_report_critique | Reports | FAST | Haiku | grok-3-mini×2 |
| analyst_report_editorial | Reports | FAST | Haiku | grok-3-mini×1 |
| portfolio_monthly_report | Reports | — | Haiku | ×8 |
| portfolio_weekly_report | Reports | — | Haiku | ×10 |
| reporting_grok_editorial | Reports | — | Haiku | — |
| aegis_steph_review | Research | — | Haiku | ×346 |
| aegis_synthesis | Research | — | Haiku | ×136 |
| ai_claim_check | Research | FAST | Haiku | — |
| contradiction_adjudicator | Research | FAST | Haiku | deepseek-flash×80, Opus×60, ×57 |
| deep_overnight_llm_drain | Research | FAST | Haiku | — |
| due_diligence_questions | Research | FAST | Haiku | grok-3-mini×17 |
| prospectus_accuracy_review | Research | PRO_THINK | Opus | — |
| prospectus_cio_news_note | Research | FAST | Haiku | — |
| prospectus_fact_check | Research | FAST | Haiku | — |
| prospectus_fact_check_oauth | Research | — | Haiku | — |
| prospectus_news_classify | Research | FAST | Haiku | — |
| prospectus_writer | Research | PRO_THINK | Opus | — |
| prospectus_writer_premium | Research | PRO_THINK | Opus | — |
| research_circle_analyzer | Research | FAST | Haiku | — |
| ri_narrative_enrich | Research | — | Haiku | ×282, Opus×102, grok-3-mini×44 |
| topic_curator | Research | — | Haiku | ×3931 |
| topic_ingestion | Research | — | Haiku | Haiku×1286, ×1241, grok-3-mini×36 |
| topic_research_synthesizer | Research | — | Haiku | ×505, grok-3-mini×42, deepseek-flash×1 |
| grok_stop_review | Risk | — | Sonnet | ×95 |
| rotation_grok_review | Rotation | — | Haiku | — |
| rotation_oversight | Rotation | — | Haiku | — |
| blind_review_runner | Shadow | FAST | Haiku | grok-3-mini×2 |
| strategy_planner | Strategy | PRO_THINK | Opus | — |
| architecture_review | System | PRO_THINK | Opus | — |
| deepseek_flash_operator_smoke | System | FAST | Haiku | — |
| oauth_lane_keepalive | System | — | Haiku | ×661 |
| pipeline_health_diagnosis | System | FAST | Haiku | — |
| unregistered | System | — | Haiku | — |
| broker_cloud_oversight | Trading | — | Sonnet | — |
| cloud_consensus_verdict | Trading | — | Sonnet | — |
| hermes_scalp_review | Trading | — | Sonnet | — |
| paper_trade_advisory | Trading | — | Sonnet | — |
| watchlist_agent_debate_flash | Watch | FAST | Haiku | grok-3-mini×3 |
| watchlist_agent_flash_extract | Watch | FAST | Haiku | — |
| watchlist_agent_oauth_fallback | Watch | — | Haiku | ×9 |
| watchlist_cio_synthesis | Watch | PRO_THINK | Opus | — |
| watchlist_cio_synthesis_cron | Watch | FAST_THINK | Sonnet | deepseek-flash×55, grok-3-mini×2 |
| watchlist_entry_planner | Watch | — | Haiku | ×2094, Opus×562, grok-3-mini×71 |
| watchlist_maria_flash_narrative | Watch | FAST | Haiku | deepseek-flash×327, grok-3-mini×3 |
| watchlist_maria_priority | Watch | FAST | Haiku | ×49, Opus×1 |
| watchlist_risk_flash_narrative | Watch | FAST | Haiku | deepseek-flash×158, grok-3-mini×2 |
| watchlist_steph_flash_narrative | Watch | FAST | Haiku | deepseek-flash×163, grok-3-mini×3 |

## Decision 2026-11-07 13:55 ET: monthly credit = $200

Anthropic's docs (platform.claude.com/docs/en/about-claude/api-credits-for-subscribers, claude.com/pricing, read 13:55 ET) say the $200/month plan is **Ultra**, with **$200 USD/month in API credits**. The $100 Max plan gets $100.
- The credits refresh on the billing cycle, not on the 1st, and expire unused with no rollover.
- They cover the API, Managed Agents, the Agent SDK and the playground. They do not cover Claude Code sessions.
- policy: monthly_credit_usd = 200, so the daily cap is about $6.67. Pending: period_start, set to the billing day once the operator reads it in Console > Billing > Promotional credits.
