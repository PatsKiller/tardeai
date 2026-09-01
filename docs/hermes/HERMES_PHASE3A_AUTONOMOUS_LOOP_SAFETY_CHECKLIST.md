# Hermes Autonomous Loop Safety Checklist

Status:      HISTORICAL
as_of:       2026-05-30T22:19:50-04:00
Measured at: efcc51365 / not measured

Must pass ALL checks before any autonomous loop activation.

---

## Pre-Activation Gate

- [ ] Phase 3A architecture approved
- [ ] Phase 3B manual dry-run passed (no DB writes)
- [ ] Phase 3C manual apply passed (capped rows)
- [ ] Phase 3D dashboard monitoring verified
- [ ] Phase 3E timer/service draft reviewed
- [ ] Phase 3F activation explicitly approved by operator

## Safety Controls

- [ ] Kill file mechanism works (`hermes_sidecar/.hermes/DISABLED`)
- [ ] Lockfile prevents concurrent runs
- [ ] Max runtime timeout enforced (600s)
- [ ] Daily row cap enforced (10)
- [ ] Daily model call cap enforced (15)
- [ ] Failure backoff works (skip after error)
- [ ] run_id tracked in every row

## Read/Write Boundaries

- [ ] Reads only from approved safe views
- [ ] No denied table access
- [ ] No secrets/credentials in prompts
- [ ] Writes only to hermes_* staging tables
- [ ] No production table writes
- [ ] No content_embeddings writes (unless separate embedding gate)
- [ ] No broker access
- [ ] No proposal/trade/journal mutation

## Quality

- [ ] Hardened prompt template used
- [ ] Hardened validator used
- [ ] Dry-run before apply (enforced in script)
- [ ] Question-style challenge_points rejected
- [ ] External unsupported claims rejected
- [ ] Limitations required
- [ ] Source_views required

## Model

- [ ] Local Ollama only (gemma3:12b primary, gemma3:4b fallback)
- [ ] No external LLMs
- [ ] No Grok/xAI
- [ ] No cloud providers
- [ ] num_ctx capped at 8192

## Monitoring

- [ ] Last run time visible in dashboard
- [ ] Row count visible in dashboard
- [ ] Errors visible in logs
- [ ] Validation rejects counted

## Rollback

- [ ] Timer can be stopped: `systemctl --user stop hermes-autonomous-loop.timer`
- [ ] Timer can be disabled: `systemctl --user disable hermes-autonomous-loop.timer`
- [ ] Rows can be deleted by run_id
- [ ] Kill file exists and works
- [ ] Rollback SQL documented

## Environment

- [ ] ALPACA_MODE=paper
- [ ] LLM_DISABLE_LIVE_EXECUTION=true
- [ ] No external API keys in hermes .env
- [ ] Gateway running (systemd, auto-restart)
