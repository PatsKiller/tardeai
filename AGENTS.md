# AGENTS.md — Trade AI repository agent instructions

Applies to every coding agent (Codex, Claude, or other) working in this repository.

## Controlling documents
- Architecture (source of truth): `docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md`
- Implementation program: `docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_1.md`
- Litmus review prompt (read-only reviewer): `docs/prompts/ACTIVE_TRADER_ARCHITECT_LITMUS_REVIEW_PROMPT_v1_0.md`
- Run evidence: `docs/implementation/active-trader/<run_id>/`

## Where to work
- Active Trader implementation happens ONLY in the isolated worktree
  `/home/johnclaw/worktrees/active-trader-next` on branch `feat/active-trader-next`.
- The production checkout `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` is
  QUARANTINED: never resolve its conflicts, reset, clean, stash, restore, checkout, pull,
  or modify its index or untracked files.
- Never commit directly to `main`. One draft PR per program run; never mark ready or merge
  without architecture-owner authorization.

## Unrelated changes
- Preserve all unrelated local modifications and untracked files everywhere.
- Do not fix unrelated lint/tests inside a stage; record pre-existing failures instead
  (they must reproduce unchanged at the stage's base and head).
- Validator runs may regenerate tracked evidence docs — restore them before committing so
  stage commits stay additive.

## Stage discipline
- Execute exactly one stage at a time; never start the next stage without a new
  architecture-owner authorization prompt.
- A stage is green only after: plan → implementation → tests → closeout → commit → push →
  Drive sync with SHA-256 verification → checkpoint update → operator email.
- On any failure: stop, preserve the worktree, write a failure closeout, push safe
  evidence, sync artifacts, email the operator, record the exact resume command.

## Tests
- Read-only validator suite: `TRADE_AI_CI=1 python scripts/run_release_ci_equivalent.py --source-only`
- Pytest: `.venv/bin/python -m pytest tests/ -q` (4 live-DB scripts are collect-ignored; see tests/conftest.py)
- Active Trader DB tests run ONLY against the isolated lab cluster (`trade_ai_test`, port
  5433) via the `ACTIVE_TRADER_TEST_DATABASE_DSN` secret from the Bitwarden `trade-ai-lab`
  project. Never against production `trade_ai`.

## Hard prohibitions
- No production database migrations, package upgrades, service changes, or feature-flag changes.
- No changes to `/v3` routes/behavior or to the existing broker adapters, approval service,
  or per-order 2FA rails without explicit stage scope.
- No real 2FA requests; no broker writes; no order queue/submit/modify/cancel; no Moomoo
  install or OpenD unlock during build stages.
- No secrets (DSNs, tokens, passwords, API keys, account numbers) in source, logs, commits,
  Drive uploads, or email — names only. Sentinel placeholder value: `UNSET__OPERATOR_REQUIRED`.
- Bitwarden: machine tokens live only under `~/.openclaw/credentials/`; never in `.env`,
  never in Secrets Manager itself.

## Commit / sync / notify
- Stage commits use the message format given by the stage authorization prompt.
- Drive evidence root: `Trade_AI_Docs_v2/implementation/active-trader/<run_id>/`
  (folder ID 1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR); verify local/GitHub/Drive SHA-256 parity.
- Operator notification: `gog gmail send` to `john@jwwhiting.com`.
