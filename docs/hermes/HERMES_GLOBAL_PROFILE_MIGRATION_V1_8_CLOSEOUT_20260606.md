# Hermes Global Profile Migration v1.8 Closeout — 2026-06-06

## Status

COMPLETE.

## Final Runtime State

- Global Hermes is canonical (`~/.local/bin/hermes`, v0.16.0).
- Old sidecar runtime is rename-retired.
- No active `hermes_sidecar/.hermes` directory was recreated after retirement.
- `hermes-gateway.service` is not running (active=failed) and is disabled.
- No old sidecar gateway launch path remains active (only the operator's live interactive `hermes chat` persists, preserved).
- Retired directories remain preserved on disk (`.hermes.RETIRED_20260606_2140`, `.hermes.RETIRED_20260606_2154`, `install.RETIRED_20260606_2140`).
- Runtime files are untracked and gitignored.

## Canonical Commands

- `hermes chat`
- `tradeai chat`
- `tradeai12b chat`
- `dev chat`
- `serverops chat`

## Model Policy

- `gemma3:4b` is the stable local default for `default` and `tradeai`.
- `gemma3:12b-ctx4k` is experimental and limited to `tradeai12b`.
- Unconstrained `gemma3:12b` is not approved as `default` or `tradeai`.
- `qwen3:14b` is absent and must not be reintroduced.
- Codex remains future `dev` profile only, human-invoked, not autonomous runtime.

## Documentation Updated

- `docs/hermes/HERMES_GLOBAL_INSTALL_MIGRATION_20260606.md`
- `docs/hermes/HERMES_PROFILE_MATRIX_20260606.md`
- `docs/hermes/HERMES_MODEL_CANARY_STATUS_20260606.md`
- `docs/hermes/HERMES_SIDECAR_RETIREMENT_PLAN_20260606.md`
- `docs/hermes/HERMES_CURATED_MIGRATION_INVENTORY_20260606.md`
- `PROJECT_DOC_INDEX.md`
- Canonical Reference Architecture `.docx` (Hermes Global Profile Architecture Update + Migration Completion Addendum; validation 17/17, single section, no duplicate)

## Safety Confirmation

- No deletion performed.
- No gateway enabled.
- No Telegram/Discord enabled.
- No Codex runtime enabled.
- No cron/systemd runtime added.
- No broker/trading/order/stop/proposal/holdings files touched.
- No secrets migrated.

## Remaining Notes

A disabled `hermes-gateway.service` unit file remains as an inactive audit artifact. It must not be enabled without explicit operator approval. Non-blocking follow-ups (optional): remove the disabled unit file; the operator's legacy sidecar `hermes chat` (PID 3549046) can be exited at will.

## 6. Claude Code Execution Prompt

The Hermes v1.8 closeout was executed through a sequence of operator-approved Claude Code prompts, each scoped and run with explicit approval:

- sidecar rename-retirement (Stage D)
- gateway stop/disable (`hermes-gateway.service`)
- git hygiene cleanup (untrack + gitignore retired runtime/state)
- launch-path audit (process / systemd / timer / cron / shell / PATH / repo / git)
- status path repoint (`scripts/api_v2.py`, `scripts/check_system_versions.sh` → global Hermes install)
- Reference Architecture v1.8 verification
- final runtime closeout

### Safety boundary (held across all prompts)

- no deletion
- no gateway/Telegram/Discord/Codex/cron/systemd runtime enablement
- no broker/trading/order/stop/proposal/holdings changes
- no secrets migrated
- `qwen3:14b` not reintroduced
- `gemma3:12b` not promoted outside `tradeai12b`

### Note

The full Claude Code prompts were delivered in the operator chat and are intentionally **not embedded verbatim** here, to avoid bloating the closeout document. This section records that they were used and their scope; the operator chat holds the complete prompt text.
