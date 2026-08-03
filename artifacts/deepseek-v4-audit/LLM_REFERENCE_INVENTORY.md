# LLM Reference Inventory

- Base SHA: `72b6ddd201e541357cb52f30c3fdeb073adef02d`
- Generated: 2026-08-03T13:35:22.505489+00:00
- Total line hits: **6278**
- Legacy alias hits: **55**
- Direct provider URL hits: **61**

## Hits by risk class

- `active_code`: 2686
- `docs`: 2334
- `archive`: 994
- `test`: 176
- `config`: 88

## Top paths

- `scripts/api_v2.py`: 247
- `docs/_archive/v4_1_discovery/llm_reference_scan_before.txt`: 195
- `docs/CHANGELOG.md`: 166
- `docs/_archive/2026-05-24_cleanup/old_phase_reports/v4_1_deployment_log.md`: 97
- `docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md`: 91
- `scripts/process_watchlist_agent_jobs.py`: 90
- `docs/MASTER_SYSTEM_DOCUMENTATION.md`: 88
- `docs/deepseek_audit_2026-08-02.md`: 81
- `apps/command-center-v3/src/pages/RotationIntelligence.tsx`: 68
- `scripts/llm_router.py`: 66
- `apps/command-center-v3/_archive/20260621/pages_RotationIntelligence.tsx`: 64
- `docs/_archive/2026-05-08/LLM_PROVIDER_GUIDE.md`: 63
- `scripts/local_llm.py`: 47
- `scripts/reporting_engine.py`: 46
- `scripts/llm_lane.py`: 45
- `docs/project/SESSION_2026_05_29_SUMMARY.md`: 43
- `scripts/catalyst_intelligence.py`: 42
- `docs/project/ROTATION_LLM_ADVISOR.md`: 42
- `docs/_archive/prompts/CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md`: 42
- `docs/hermes/HERMES_LLM_AUTH_STATUS_20260607.md`: 36
- `scripts/rotation_dual_llm_advisor.py`: 35
- `scripts/run_deep_overnight_llm_window.sh`: 35
- `apps/command-center-v3/src/pages/ConsumptionHub.tsx`: 35
- `docs/diligence/current/LLM_ROUTING_MATRIX.md`: 33
- `scripts/claude_escalation_handler.py`: 32
- `config/llm_process_registry.json`: 31
- `apps/command-center-v3/src/components/CloudLlmRunButtons.tsx`: 31
- `apps/command-center-v3/src/lib/cloudLlmRun.ts`: 31
- `docs/atm_lifecycle_v1_2026_05_28/LOCAL_LLM_ROUTER_SAFETY_PATCH_REPORT.md`: 29
- `scripts/local_llm_config.py`: 28

## Model / lane literal frequency (sample tokens)

- `Ollama`: 853
- `ollama`: 564
- `chatgpt`: 539
- `ChatGPT`: 519
- `gemma3`: 444
- `gemma3:12`: 413
- `OLLAMA`: 396
- `gemma3:4`: 394
- `gemma`: 258
- `gemma3:27`: 153
- `gemma4:`: 124
- `gemma4`: 102
- `deepseek-flash`: 90
- `Gemma4`: 55
- `grok-3-mini`: 54
- `Gemma`: 54
- `deepseek-v4`: 50
- `gemma4:31`: 38
- `gemma4:26`: 38
- `CHATGPT`: 23
- `grok-oauth-proxy`: 22
- `grok-prompt`: 16
- `gpt-5.4`: 14
- `grok-oauth`: 14
- `grok-3`: 10

## Active-code DeepSeek hotspots (path list)

- `apps/command-center-v3/src/components/CloudLlmRunButtons.tsx`
- `apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx`
- `apps/command-center-v3/src/hooks/useOAuthLanes.ts`
- `apps/command-center-v3/src/lib/cloudLlmRun.ts`
- `apps/command-center-v3/src/pages/ConsumptionHub.tsx`
- `scripts/api_v2.py`
- `scripts/lib/llm_consumption.py`
- `scripts/llm_health_check.py`
- `scripts/llm_lane.py`
- `scripts/session18e_validate_local_llm.py`
- `scripts/session19_validate.py`

## Key findings at 72b6ddd2 (evidence-based)

1. `scripts/llm_lane.py` maps `deepseek-flash`→`deepseek-chat`, `deepseek-v4`→`deepseek-reasoner` (legacy IDs).
2. Logical lane `deepseek-v4` is ambiguous (not exact provider model ID).
3. Frontend duplicates lane types in TypeScript (`cloudLlmRun.ts`, buttons, ConsumptionHub).
4. Process registry at this SHA is still Grok/ChatGPT vocabulary (version 2 lane_policies).
5. Silent Gemma fallback was patched in 72b6ddd2 for DeepSeek lanes — other unknown-lane fallback still needs Stage 1/5 verification.

Full machine-readable rows: `LLM_REFERENCE_INVENTORY.json`.

