# Rollback

## Git

```bash
# discard implementation worktree/branch tip back to DeepSeek base
git -C /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild worktree remove --force /home/johnclaw/tradeai-wt-deepseek-v4-routing
git -C /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild branch -D fix/deepseek-v4-routing

# if branch was pushed:
git push origin --delete fix/deepseek-v4-routing
```

## Runtime (only if later deployed — not done by this task)

1. Disable DeepSeek provider: set `providers.deepseek.enabled=false` or `kill_switch=true` in `config/llm_model_registry.json`.
2. Restart portfolio-server **only with operator approval**.
3. Do **not** re-enable legacy model IDs as a “fix”.

## Main worktree dirty files

Unrelated dirty files on `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` (main @ 72b6ddd2 + 184 dirty) were **not** modified by this task.
