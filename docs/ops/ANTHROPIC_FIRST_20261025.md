# Anthropic-first: routing, review and caller inventory

PR #2181 is deployed at `293354f80545`. The operator then explicitly requested: "what disable enable and test call" (2026-10-25). This follow-up enables the promotional policy and admits its credit journal under the existing caps. The rendered manifest lists `ANTHROPIC_API_KEY`; credential values have not been read. Source enablement is not live authentication or canary proof.

After this follow-up is reviewed and deployed, run `scripts/anthropic_governed_canary.py` without flags first. It prints the exact tiny Opus request and limits without dispatch or writes. The operator then runs it from CURRENT with `ANTHROPIC_CANARY_OPERATOR_RUN=1` and `--apply`. One request goes through the registered `cio_operator_reply` bridge route with manual intent, ordinary process admission and 64 output tokens. A fallback, mock response, wrong model, unknown cost, or missing matching credit settlement/provider-cost event fails the proof. No provider key is loaded by the canary client, no process/cap/guard is overridden, and no notification is sent.

Operator model decision 2026-10-25: general tasks use Opus 5.5, including high reasoning; eleven explicitly listed tagging/classification/summary/triage processes use Haiku 5.5. Fable is excluded. The eligible proposal covers 67 processes (56 Opus, 11 Haiku); 23 provider-pinned, independent-review, protected or legacy-sentinel rows retain their routes. All legacy allowed lanes, process caps, request limits and DeepSeek policies remain unchanged. Missing/unusable credit restores each original route.

At the captured observed subset's token volumes, the revised comparable-token estimate is **$5.050121/day**, against the unchanged $10/UTC-day cap. This is not a full-day forecast: unobserved OAuth usage and model output/thinking volumes remain unmeasured. See the regenerated dry-run table, including no-key/expired behavior.

Review A's Sonnet cache-price finding was rechecked against both [current official pricing](https://platform.claude.com/docs/en/about-claude/pricing) and the [Sonnet 5.5 announcement](https://www.anthropic.com/claude-sonnet-5-5): both currently specify $0.10/MTok, so that value is retained. Opus 5.5 thinking is always adaptive; ordinary work explicitly uses low effort rather than claiming thinking is off.

Completed source corrections include pre-provider Ask question/process/global-cap admission (including the original high-reasoning projection), independent provider identity, credit-refusal fallback, full-UTC-day holds and total retention, bounded accounting pauses and append-only operator reset, one-shot billing notes, silent empty digests, guarded/cached monitoring and per-model/fallback detail. Platform, Jobs and the production needs-action probe map are wired. The inbox regression exercises that map and its P1/P2 results without loading API bootstrap or live sources. This is source/test evidence, not live activation.

The operator published the correction to PR #2181 at `448607166`. Full GitHub CI exposed two documentation failures: missing design-registry YAML metadata and a stale generated data dictionary. This follow-up adds that metadata and regenerates the dictionary without changing provider source or authority; both complete affected suites pass locally (67 cases, psycopg2 hidden). New-head CI remains required. No merge, release, key access or provider canary was performed. The provider source passed 308 focused cases across the sandbox and one approved mock HTTP test, the separate 150-test review regression set, and 12 environment-read regressions; these populations overlap and are not added. UI build passed. Actual browser fixtures passed expand/collapse taps and the full LLM Spend/Jobs pages at 412 and 390, with no horizontal overflow. Screenshots remain private. Local native PR-profile execution is incomplete; see the verification packet for the boundaries.

## Historical caller inventory before implementation

Design-Task: DSN-20261025-anthropic-first-P1-T1
Source: `7a17113afedc552a645493972dee46c0ba51a2dd`; captured 2026-10-25T20:33:26.196551+00:00.

No routing/provider implementation has been changed at this inventory checkpoint. This is declared-source accounting, not runtime activation proof.

## Registered population

90 process rows; eight authenticated bridge caller identities, 43 task overrides and 48 distinct bridge-mapped processes. The other 42 registered processes do not have a direct server caller/task pair; that does not mean they bypass all consumption governance.

| Configured route | Process rows |
|---|---:|
| deepseek → deepseek → deepseek | 19 |
| deepseek → grok → chatgpt | 32 |
| grok → chatgpt → deepseek | 38 |
| grok → grok → grok | 1 |

## Entry paths

- n8n model jobs / bridge clients → server-owned caller/task mapping → cio_governed_model_bridge → route walker / provider transports. High reasoning and escalation can change effective order.
- Ask the CIO Deep → governed_cloud_generation with explicit manual intent → registered bridge process; manual mode and request/question caps stay binding.
- CIO watch-review workers → governed_cloud_generation; TRADEAI_LLM_VIA_BRIDGE decides bridge-only versus in-process llm_lane path.
- Hermes/research callers → generate_cloud, llm_lane or agent Flash governance, depending on the caller/executor binding.
- In-process llm_lane → llm_consumption when process_id is present; opt-out/missing process paths are separate findings. The bridge routing JSON alone does not govern this legacy route.
- Conflict rule proposals → existing governed n8n model-job/bridge path; no autonomous rule activation.

## Direct provider paths found

These SDK/REST paths exist in source; runtime use is not inferred from their presence. They remain unchanged in this task. Provider probes and the intended transport adapters are listed separately in direct-provider-candidates.json.

| File | Classification |
|---|---|
| `scripts/alert_missing_conditions.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/alex_hygiene.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/api_v2.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/hermes_external_researcher.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/iris_taxonomy_agent.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/journal_agent_coach.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/lib/ross_catalog_hermes.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/monthly_protection_meta_review.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/multi_tier_trade_reviewer.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/portfolio_monthly_synthesis.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/portfolio_proxy.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/portfolio_yaml_advisor.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/rebalance_verifier.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/scoring.py` | Direct SDK/REST path; conditional invocation / runtime use not verified |
| `scripts/trade_plan.py` | Explicitly disabled named helper; not claimed live |

The broader AST inventory contains 125 candidate call sites in 69 files. 107 use directly imported governed/lane APIs; variable process bindings still require caller-specific trace. A conservative exclusion list of 210 potential execution-related paths was not read; broker/order/stop implementations are outside scope.

## Today’s measured ledger window

America/New_York day beginning `2026-10-25T04:00:00+00:00`, observed through `2026-10-25T20:33:26.196551+00:00`.

- Provider-cost ledger: **236 confirmed sent events, $0.24668593**, all DeepSeek, with token-priced trusted costs.
- 230 events map to eight registered processes; six events ($0.00148530) are unassigned to the registered denominator.
- This ledger does not establish all OAuth calls or a complete platform call total. Absence from it is NOT_MEASURED, not zero.
- The read-only credential-free PostgreSQL aggregate was refused by the sandbox while opening its Unix socket (Operation not permitted). No alternate connection was attempted. Full consumption-ledger call totals remain NOT_MEASURED.

| Registered process | Recorded events | Token-priced USD |
|---|---:|---:|
| `UNMAPPED` | 6 | 0.00148530 |
| `advisory_desk_synthesis` | 8 | 0.00111992 |
| `cio_hermes_research` | 28 | 0.07486432 |
| `cio_operator_reply` | 9 | 0.00071254 |
| `cio_plan_enrichment` | 60 | 0.05018103 |
| `hermes_cloud_json` | 45 | 0.08746935 |
| `hermes_external_research` | 12 | 0.00461424 |
| `hermes_usefulness_score` | 60 | 0.00694202 |
| `l3_judgment_author` | 8 | 0.01929721 |

## Existing Anthropic support and required changes

The source already contains an in-process Anthropic Messages adapter and enabled Haiku/Sonnet 4.5 registry entries. The governed bridge has no Anthropic transport. The approved work adds the bridge/provider-budget integration and updates current IDs/prices; it does not need a new SDK dependency.

Official build-time references: [models](https://platform.claude.com/docs/en/models/overview), [pricing](https://platform.claude.com/docs/en/about-claude/pricing). Confirmed requested IDs: claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5. Prices must remain in config, including Haiku’s over-100k-input tier, cache reads/writes and Batch discount.

## Full registered process inventory

| Process | Existing configured route | Literal call sites found |
|---|---|---|
| `advisory_desk_opinion` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `advisory_desk_synthesis` | deepseek:PRO → deepseek:PRO → deepseek:PRO | dynamic / no literal binding in scanned scope |
| `aegis_steph_review` | deepseek:FAST → grok:FAST → chatgpt:FAST | scripts/aegis_synthesis.py:625 |
| `aegis_synthesis` | deepseek:FAST → grok:FAST → chatgpt:FAST | scripts/aegis_synthesis.py:107 |
| `alex_cio_escalation` | deepseek:PRO_THINK → deepseek:PRO_THINK → deepseek:PRO_THINK | dynamic / no literal binding in scanned scope |
| `alex_cio_synthesis` | deepseek:PRO → deepseek:PRO → deepseek:PRO | scripts/gate_d_bundle_2_advisory_canary.py:441 |
| `architecture_review` | deepseek:PRO_THINK → grok:PRO_THINK → chatgpt:PRO_THINK | dynamic / no literal binding in scanned scope |
| `broker_cloud_oversight` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `cloud_consensus_verdict` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `cloud_review` | deepseek:FAST → grok:FAST → chatgpt:FAST | scripts/cloud_review.py:119 |
| `deepseek_flash_operator_smoke` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `cio_policy_field_advisor` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `directive_keyword_enhancer` | grok:FAST → chatgpt:FAST → deepseek:FAST | scripts/directive_keyword_enhancer.py:106 |
| `grok_execution_review` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `guardian_risk_critique` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `hermes_analyst_coverage` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `hermes_cross_source_synthesizer` | grok:FAST → chatgpt:FAST → deepseek:FAST | scripts/hermes_cross_source_synthesizer.py:185 |
| `hermes_external_research` | grok:FAST → chatgpt:FAST → deepseek:FAST | scripts/cloud_review.py:182, scripts/hermes_external_researcher.py:387 |
| `hermes_scalp_review` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `hermes_tag_engine` | grok:FAST → chatgpt:FAST → deepseek:FAST | scripts/hermes_tag_engine.py:130 |
| `holding_protection_advisor` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `holding_protection_advisor_batch` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `holdings_llm_refresh` | grok:FAST → chatgpt:FAST → deepseek:FAST | scripts/holdings_llm_refresh.py:257 |
| `iris_taxonomy_agent` | deepseek:FAST → grok:FAST → chatgpt:FAST | scripts/iris_taxonomy_agent.py:41 |
| `journal_ask` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `l3_judgment_author` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `l3_independent_critic` | grok:FAST → chatgpt:FAST → deepseek:FAST | scripts/lib/independent_critic.py:109, scripts/run_tiered_validation_gate.py:123 |
| `ledger_tax_critique` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `llm_intelligence_enrichment` | deepseek:FAST → grok:FAST → chatgpt:FAST | scripts/llm_intelligence_enrichment.py:86 |
| `maria_research_critique` | deepseek:FAST → grok:FAST → chatgpt:FAST | scripts/gate_d_bundle_2_advisory_canary.py:382 |
| `morgan_wealth_synthesis` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `multi_tier_trade_reviewer` | deepseek:FAST_THINK → grok:FAST_THINK → chatgpt:FAST_THINK | scripts/multi_tier_trade_reviewer.py:101 |
| `oauth_lane_keepalive` | deepseek:FAST → grok:FAST → chatgpt:FAST | scripts/oauth_lane_keepalive.py:74 |
| `options_ensemble` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `paper_trade_advisory` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `pipeline_health_diagnosis` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `portfolio_ai_analyst` | grok:FAST → chatgpt:FAST → deepseek:FAST | scripts/portfolio_ai_analyst.py:110, scripts/portfolio_ai_analyst.py:159 |
| `portfolio_ask` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `portfolio_monthly_report` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `portfolio_orchestrator` | deepseek:FAST → grok:FAST → chatgpt:FAST | scripts/portfolio_orchestrator.py:1744 |
| `portfolio_weekly_report` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `reflective_critic_flash` | deepseek:FAST → deepseek:FAST → deepseek:FAST | scripts/agent_runtime_live_providers.py:142 |
| `reporting_grok_editorial` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `rotation_grok_review` | grok:FAST → chatgpt:FAST → deepseek:FAST | scripts/api_v2.py:51624 |
| `rotation_oversight` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `steph_allocation_review` | deepseek:PRO → deepseek:PRO → deepseek:PRO | dynamic / no literal binding in scanned scope |
| `stop_drift_alert` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `strategy_planner` | deepseek:PRO_THINK → grok:PRO_THINK → chatgpt:PRO_THINK | dynamic / no literal binding in scanned scope |
| `think_tank_signal_miner` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `topic_curator` | deepseek:FAST → grok:FAST → chatgpt:FAST | scripts/topic_curator.py:200 |
| `topic_ingestion` | grok:FAST → chatgpt:FAST → deepseek:FAST | scripts/topic_ingestion.py:368, scripts/topic_ingestion.py:516, scripts/topic_ingestion.py:1077 |
| `ri_narrative_enrich` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `topic_research_synthesizer` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `unregistered` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `watchlist_agent_debate_flash` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `watchlist_agent_flash_extract` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `watchlist_cio_synthesis` | deepseek:PRO_THINK → grok:PRO_THINK → chatgpt:PRO_THINK | dynamic / no literal binding in scanned scope |
| `watchlist_cio_synthesis_cron` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `grok_stop_review` | grok:FAST → grok:FAST → grok:FAST | dynamic / no literal binding in scanned scope |
| `watchlist_entry_planner` | grok:FAST → chatgpt:FAST → deepseek:FAST | scripts/watchlist_entry_planner.py:545 |
| `watchlist_maria_flash_narrative` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `watchlist_maria_priority` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `watchlist_agent_oauth_fallback` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `watchlist_risk_flash_narrative` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `watchlist_steph_flash_narrative` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `options_thesis_cio_review` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `cio_operator_reply` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `cio_plan_enrichment` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `cio_prompt_judge` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `research_circle_analyzer` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `hermes_cloud_json` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `hermes_usefulness_score` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `cio_hermes_research` | deepseek:FAST → grok:FAST → chatgpt:FAST | dynamic / no literal binding in scanned scope |
| `hermes_golden_judge` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `local_llm_compat` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `contradiction_adjudicator` | deepseek:FAST → deepseek:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `n8n_material_digest_draft` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `n8n_ops_summary_draft` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `n8n_lane_failure_diagnosis` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `incubator_llm_screener` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `journal_review_builder` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `portfolio_lookthrough_themes` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `hermes_usefulness_score_n8n` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `proposal_llm_review` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `defense_weekly_oversight` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `analyst_report_editorial` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `analyst_report_critique` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `due_diligence_questions` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |
| `blind_review_runner` | grok:FAST → chatgpt:FAST → deepseek:FAST | scripts/blind_review_runner.py:217 |
| `cio_ask_deep_research` | grok:FAST → chatgpt:FAST → deepseek:FAST | dynamic / no literal binding in scanned scope |

## Evidence boundaries

Full caller runtime mapping, all-call daily totals, provider key configuration, live canaries and deployment remain unverified. The private ledger capture is counts/costs only; no prompts, responses, portfolio data, account values or credentials are copied into this packet.

## Implementation checkpoint (source only)

The config opts 81 process profiles into Anthropic → Grok OAuth → ChatGPT OAuth → DeepSeek; eight protected/provider-probe processes and the legacy unregistered sentinel retain their original routing. Both the authenticated bridge and native consumption path preserve registration, manual intent, memory checks, per-process limits and paid fallback authorization. Native requested reasoning policies are retained when admitted. Provider/model kill switches remain effective. No caller-map entries were changed.

The adapter uses standard-library HTTPS, no new dependency, bounded retries and deadlines, configured current models/prices, and ephemeral system-prompt caching. It meters input, output, cache reads and both cache-write durations. Explicit asynchronous Batch submission/readback is implemented and tested; existing synchronous callers stay synchronous. No current caller has been granted an automatic async conversion.

The credit journal holds worst-case cost before dispatch and retains ambiguous attempts. A second guard on the existing PostgreSQL reservations checks promotion-total and UTC-day caps under its global advisory lock, excluding promotional usage from the paid global ceiling while retaining process caps. Monetary authorizations round upward to the existing database precision. The journal source is a **proposal** in `config/data_source_authority.json`; no new source grant or backup proof has been invented. Its runtime directory is excluded by the current offsite backup mechanism. The PostgreSQL cap backstop prevents journal loss from resetting durable authorization.

The dry-run table in `packets/anthropic-first-20261025/dry-run-table.md` covers all 90 processes. At equal observed input/output volumes, the measured subset would cost **$0.72263780** on its selected Claude tiers, before caching. Full-day cost is NOT_MEASURED because the capture omits unobserved OAuth/other calls and Claude output/thinking can differ. This is below $10 for that subset, not a full-day spend prediction.

LLM Spend has a token-based, phone-first credit section, 44px details button, routing order, usage/error observations and model costs. The existing provider-health heartbeat carries the same projection, including digest text and milestone/P1 notes through its existing notification-intent path. Runtime-health observer and daily digest consume that projection. Platform/needs-action/Jobs & health completion is pending the active-owner handoffs in `packets/anthropic-first-20261025/OWNER_HANDOFF.md`.

## Verification boundaries and next actions

- Isolated tests use pinned clocks, fake HTTP/ledger services and a temporary PROJECT_ROOT. No real API calls or secrets were used. Canonical pricing is tested against the authorization calculation for all three models, long context, caching and Batch.
- `npm run build` passed with the final nullable-cost presentation; its frontend source tree is unchanged at the tested backend head. The final selected CI-parity run passed 263 tests. Test coverage, host-path and line-ending checks have zero new violations; exact receipts and blocked proof are in the local build report.
- The socket-backed HTTP test was refused by the sandbox (`Operation not permitted`). Do not retry it through another transport or privilege path.
- Chromium launch was refused by the sandbox before the 412/390 fixture could run (`sandbox_host_linux.cc`, `Operation not permitted`). Screenshots and tap proof are **NOT_MEASURED**. `scripts/tests/anthropic_credit_fixture.mjs` is the prepared no-server, network-blocked fixture for an operator-permitted environment.
- Full provider-call counts remain NOT_MEASURED: the read-only PostgreSQL aggregate was OS-refused. The exact readonly SQL is preserved in the packet; do not infer zero OAuth calls.
- No remote push, PR, merge, release, service change, new schedule, key sync or live canary occurred in this task.

## Operator steps after review

1. Review the proposed credit-journal source/writer, retention and backup limitation, plus the shared monitoring integrations. Promote the source only through the normal operator grant process; retain original evidence and never reset credit automatically.
2. Create the API key in the intended Anthropic organization and store it in the existing Bitwarden Secrets Manager project as **ANTHROPIC_API_KEY**. No value belongs in Git, chat or this report.
3. Run the existing secret sync: from the canonical repository, `.venv/bin/python scripts/secrets/render_env.py --now`. The checked-in `cio-governed-bridge.service` already consumes `%t/tradeai/env`; the ordinary release train must rebind the bridge to CURRENT. Do not restart it from this worktree.
4. Complete the 412/390 fixture and blocked HTTP proof in an authorized environment, then publish/review the local branch and let the coordinator merge/release. Source tests do not establish live acceptance.
5. After release/key delivery, use existing registered manual callers with their normal memory/output contracts for tiny canaries. General FAST/PRO/PRO_THINK requests select Opus; the explicit bulk process list selects Haiku for FAST. An admitted PRO_MAX request selects Opus and still requires operator confirmation. Existing PRO_MAX-admitted processes include architecture_review, strategy_planner and watchlist_cio_synthesis. Do not invent a process, bypass a refusal, or widen a cap to obtain green.
6. Verify canonical usage, authorization, consumer readback and provider status for each canary. Under operator control, cap at the measured spend to prove OAuth fallback, then restore the approved cap. Confirm the actual CURRENT/build and serving bridge before claiming live.

## Proposed AGENTS wording (operator review only)

While the configured Anthropic promotional credit is usable, governed cloud calls follow the config order Anthropic API → Grok OAuth → ChatGPT OAuth → DeepSeek. Model tiers and prices come from the model/credit configuration. The promotion is limited to $190 total, $10 per UTC day and its configured per-call limits, expires 2026-11-16 00:00 UTC, and never raises any process or paid fallback limit. Missing credentials, unavailable credit, exhaustion, expiry and provider refusal fall through under the same caller/manual/memory/output rules; billing exhaustion is durable and rate limits are bounded retries, not exhaustion. Local-only and explicitly protected/provider-pinned processes keep their approved routes. Direct bypasses remain named gaps. No LLM path places, sizes or stops orders.


## Final admission correction

81 task profiles opt into the new order. The eight protected/provider probes plus the legacy `unregistered` sentinel are unchanged (nine exclusions). **56** opted-in source rows declare positive USD/request caps; **25** need live DB cap overrides measured or an operator budget decision. No budgets were added. At runtime, absent caps skip Anthropic and preserve existing free-only service; paid fallback still requires its own admission. Missing token-limit fields retain the caller's existing limits while the promotional per-call authorization still bounds worst-case token cost. The dry-run table labels these admission boundaries instead of claiming all 81 are ready.

The first broader compatibility run used system Python's Pydantic 1 and exposed an existing `model_validate` dependency mismatch. The existing CI virtualenv has Pydantic 2; its subsequent 257-test compatibility run passed without installing dependencies. Final exact-head receipts supersede these checkpoint counts. No refusal was bypassed to obtain that result.
