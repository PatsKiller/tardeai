# Rollback

Status:      ACTIVE
as_of:       2026-08-03T11:40:56-04:00
Measured at: efcc51365 / not measured

```bash
# discard working branch tip back to origin/main
git -C /home/johnclaw/tradeai-wt-deepseek-v4-mainline reset --hard origin/main

# or restore pre-cleanup snapshot
git -C /home/johnclaw/tradeai-wt-deepseek-v4-mainline reset --hard backup/deepseek-v4-mainline-before-cleanup
```

Disable DeepSeek without deploy: set `providers.deepseek.enabled=false` or `kill_switch=true` in `config/llm_model_registry.json` on a future release.

Do not re-enable legacy model IDs.
