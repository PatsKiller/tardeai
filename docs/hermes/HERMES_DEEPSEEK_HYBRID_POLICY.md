# Hermes DeepSeek hybrid policy (pointer)

Canonical operator doc:

**`docs/ops/HERMES_DEEPSEEK_HYBRID_FREE_OAUTH_ROLLOVER_2026-08-04.md`**

### Ladder

Local → free OAuth (Grok/ChatGPT) → **DeepSeek Flash on free-OAuth bottleneck only**.

### Not allowed for Hermes bulk

- DeepSeek Pro as default or bottleneck rollover  
- Silent paid fallback when local fails  

Config: `config/hermes_research_budget.yaml` → `cloud_unavailable.free_oauth_bottleneck_rollover`.  
