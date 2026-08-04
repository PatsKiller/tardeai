# Hermes + DeepSeek hybrid policy (free OAuth bottleneck → Flash)

**Date:** 2026-08-04  
**Status:** Live on host (config + `cloud_review` + discovery LLM review)  
**Authority:** Advisory only — no broker / order / 2FA / risk-stop writes  

---

## Summary

Hermes cloud second opinions use a **hybrid ladder**:

1. **Local** first (gemma, `fallback=False` — never auto-pays on local failure).  
2. **Free OAuth** (Grok :8645, ChatGPT codex :8646) when escalation is allowed.  
3. If free OAuth **bottlenecks** (unavailable / zero ok lanes) → **one DeepSeek V4 Flash** rollover (FAST, metered, cost-gated).  
4. **Never** DeepSeek Pro / PRO_THINK / PRO_MAX as Hermes bottleneck rollover.  
5. **Never** silent paid fallback for ordinary local-lane failures.  

Credential slot: **`deepseek_tradeai`** (also mirrored in Bitwarden as  
`openclaw/providers/deepseek/apiKey` for OpenClaw).  

---

## Config

| Path | Role |
|------|------|
| `config/hermes_research_budget.yaml` → `cloud_unavailable.free_oauth_bottleneck_rollover` | Policy block (`enabled`, lane, model, never_pro, credential_slot) |
| `scripts/cloud_review.py` | Free OAuth first; DeepSeek Flash if zero free ok lanes |
| `scripts/lib/hermes_discovery/llm_review.py` | Escalation still runs when free OAuth is down so Flash rollover can fire |

### Policy knobs

```yaml
cloud_unavailable:
  free_oauth_bottleneck_rollover:
    enabled: true
    lane: deepseek-flash
    model: deepseek-v4-flash
    policy: FAST
    credential_slot: deepseek_tradeai
    never_pro: true
```

Disable Flash rollover without code change:

```yaml
enabled: false
```

---

## When Pro is appropriate (not Hermes bulk)

| Use | Model |
|-----|--------|
| Hermes bottleneck / discovery review | **Flash only** |
| Agent-flash automation / market-15m | **Flash only** |
| OpenClaw operator chat default | Pro OK if quality preferred |
| CIO / high-stakes multi-evidence synthesis | Pro **only** with process id + reservation + budget |

See operator guidance: Pro is exceptional under the global USD cap.

---

## Bitwarden / secrets (related)

OpenClaw credentials (Telegram, DeepSeek, gateway token, xAI, etc.) resolve via  
exec SecretRef provider **`bws`** → `~/.openclaw/bin/openclaw-bws-resolver.mjs`  
and project **`trade-ai-prod`** keys under `openclaw/...`.

Trade AI Hermes cron still loads `deepseek_tradeai` from approved env (`.env` /  
operator env / BWS injection). Do not print secret values in logs or docs.

---

## Command Center

- **System → LLM** tab: lane chips (local / grok / chatgpt / deepseek-flash / deepseek-v4-pro)  
  + hybrid policy card from `/api/v2/llm-health` (`hybrid_policy`).  
- **Consumption**: free OAuth + metered DeepSeek readiness (`/api/v2/llm/oauth-lanes`).  

---

## Verification (no secrets)

```bash
# Policy present
python3 -c "import yaml; p=yaml.safe_load(open('config/hermes_research_budget.yaml')); print(p['cloud_unavailable']['free_oauth_bottleneck_rollover']['model'])"

# API
curl -sS http://127.0.0.1:7777/api/v2/llm-health | python3 -m json.tool | head -80
```

---

## Related

- `docs/hermes/EXTERNAL_LLM_USAGE_POLICY_20260607.md`  
- `docs/ops/deepseek-v4-mainline-2026-08-03/`  
- OpenClaw: default model `deepseek/deepseek-v4-pro`; web search **SearXNG** (`http://127.0.0.1:18888`)  
