# Rotation Intelligence Production Readiness — 2026-06-19

Status:      HISTORICAL
as_of:       2026-06-19T12:48:08-04:00
Measured at: efcc51365 / not measured

## Status

**Target state:** 8.x advisory-production-ready
**Scope:** Rotation Intelligence, local LLM validation, free/OAuth Grok second opinion, Command Center v3 integration.
**Safety class:** Advisory only. No broker action.

This document defines what moved the rotation workflow from a controlled pilot toward advisory production readiness, and what must remain true before it can be trusted by an operator.

## What changed

| Area | Previous maturity | Target maturity | Hardening added |
|---|---:|---:|---|
| Operational polish | 6.x | 8.x | Clean JSON, prompt-path mode, copy-marker mode, local console capture |
| Grok second opinion | 6.x | 8.x | Free/OAuth/manual-prompt contract, no API key, no paid xAI API, no direct Grok HTTP from the dual script |
| Governance consistency | 6.x | 8.x | Machine-readable `trust_verdict`, final-authority field, no-override rule |
| UI integration | 7.x | 8.x | `/v3/rotation`, `/v3/advisor-changes`, nav links, Intelligence/Portfolio integrations |
| Validation | 6.x | 8.x | New `scripts/validate_rotation_production_readiness.py` static readiness gate |

## Production advisory contract

Every operator-facing result must preserve these statements:

1. `advisory_only: true`
2. `broker_action: none`
3. `final_authority: grounded_rotation_engine`
4. Grok and local LLM are second-opinion lanes only.
5. If `no_model_supported_action` is true, answer mode must be `grounded_no_supported_action`.
6. Grok cannot override grounding.
7. No direct xAI/Grok API key path is allowed in `scripts/rotation_dual_llm_advisor.py`.

## Trust verdict

`rotation_dual_llm_advisor.py` now emits a `trust_verdict` block in JSON mode.

Required fields include:

```json
{
  "final_authority": "grounded_rotation_engine",
  "broker_action": "none",
  "advisory_only": true,
  "grok_mode": "free_oauth_manual_prompt",
  "grok_can_override_grounding": false,
  "uses_api_key": false,
  "uses_paid_xai_api": false,
  "uses_direct_grok_http": false,
  "operator_required": true
}
```

This is intended for both API consumers and Command Center UI trust panels.

## Readiness validator

Run:

```bash
python3 scripts/validate_rotation_production_readiness.py
python3 scripts/validate_rotation_production_readiness.py --json | jq '.ok, .maturity_score, .blockers'
```

The validator checks:

- required files exist
- direct Grok/xAI API-key strings are absent from the dual script
- required CLI flags exist
- trust verdict fields exist
- clean local-output capture exists
- `/v3/rotation` and `/v3/advisor-changes` are routed and visible in nav
- rotation UI contains advisory-only and no-broker-action language
- dangerous order/execution phrases are absent from the Rotation page

## Required local acceptance commands

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

git pull --ff-only

python3 -m py_compile \
  scripts/rotation_dual_llm_advisor.py \
  scripts/rotation_llm_advisor.py \
  scripts/validate_rotation_production_readiness.py

python3 scripts/validate_rotation_production_readiness.py --json | jq '.ok, .maturity_score, .blocker_count, .warning_count'

python3 scripts/rotation_dual_llm_advisor.py \
  --question "Should I trim XLB for SPCX? How much should I trim?" \
  --cards data/runtime/symbol_cards_latest.json \
  --json | jq '.answer_mode, .trust_verdict.final_authority, .trust_verdict.broker_action, .trust_verdict.grok_can_override_grounding'

python3 scripts/rotation_dual_llm_advisor.py \
  --question "Should I trim XLB for SPCX? How much should I trim?" \
  --cards data/runtime/symbol_cards_latest.json \
  --print-grok-prompt | head -60
```

Expected for the XLB/SPCX no-action test:

```text
"grounded_no_supported_action"
"grounded_rotation_engine"
"none"
false
```

## Remaining production-hardening recommendations

These are next, not blockers for advisory production use:

1. Show the `trust_verdict` block visibly in `/v3/rotation` instead of only in raw JSON.
2. Add a small health card for local LLM, Grok OAuth proxy, symbol-card freshness, and last rotation-engine run.
3. Add a regression fixture for the XLB/SPCX question to prevent future false account placement or numeric trim amounts.
4. Feature-flag inline OAuth proxy review separately from manual-paste prompt mode, so the operator can choose strict manual-paste-only.
5. Add periodic readiness validation to the morning brief or a daily cron.

## Maturity assessment after this hardening

| Capability | Rating | Notes |
|---|---:|---|
| Grounded rotation engine | 8.0 | Engine is final authority; no-action cases stay grounded |
| Local LLM validation | 8.0 | Validation issues are explicit; stdout/stderr capture keeps JSON parseable |
| Grok OAuth path | 8.0 | Free/OAuth/manual-prompt path enforced in dual script; inline proxy must stay feature-flagged/governed |
| Command Center UI | 8.0 | Routes/nav/pages exist; remaining enhancement is visible trust-verdict panel |
| Documentation | 8.0 | Drive + Git docs aligned enough for operator use; validator anchors future checks |
| Operational readiness | 8.0 | Readiness validator and acceptance commands now exist |

## Final maturity call

**Advisory production-ready target achieved when `validate_rotation_production_readiness.py` passes locally and the XLB/SPCX regression returns `grounded_no_supported_action`.**

This still does **not** mean autonomous trading. It means the operator can use Rotation Intelligence for grounded portfolio review with local/Grok second opinions while keeping broker action fenced and human-reviewed.
