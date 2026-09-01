# Hermes Global Install Migration — 2026-06-06

Status:      ACTIVE
as_of:       2026-06-06T21:42:34-04:00
Measured at: efcc51365 / not measured

## Result

Hermes has been promoted from a Trade AI sidecar-only install to a global/default install.

## Confirmed

- Global CLI: `~/.local/bin/hermes`
- Global venv: `~/.local/share/hermes-agent-venv`
- Global Hermes version: `0.16.0`
- Global config: `~/.hermes/config.yaml`
- Default profile: `~/.hermes`
- Trade AI profile: `~/.hermes/profiles/tradeai`
- Dev profile: `~/.hermes/profiles/dev`
- ServerOps profile: `~/.hermes/profiles/serverops`
- Sidecar Hermes version: `0.15.2`
- Sidecar backup exists under `backups/`
- Sidecar file inventory exists under `docs/hermes/`

## Sidecar Role Going Forward

The old Trade AI sidecar install is retained as:

- rollback source
- migration source
- Trade AI profile seed
- audit evidence

It is not the canonical global Hermes install.

## Do Not Migrate Blindly

Do not migrate:

- `.env`
- secrets
- API keys
- raw request dumps
- failing tool-call sessions
- stale qwen3 references
- broker credentials
- Telegram tokens
- runtime lock files
- gateway PID files
- transient DB WAL/SHM files

Migrate selectively:

- `SOUL.md`, after review
- safe Trade AI-specific profile rules
- safe config intent
- curated skills, after review
- durable memories, if reviewed
- docs/reports references

## Current Model Finding

- `gemma3:12b` failed a plain-text canary and is blocked for Hermes until repaired.
- `gemma3:4b` passed exact-string and simple math canaries.
- Local Gemma models do not support Hermes tool-calling through Ollama.
- For local profiles using Ollama, CLI tools must be disabled unless a tool-capable route is configured.

## Profile Policy

- `default`: global/general Hermes, local text-only for now.
- `tradeai`: restricted advisory profile, no broker writes, no raw secrets.
- `dev`: development profile; future direct ChatGPT/Codex route belongs here.
- `serverops`: future controlled server operations profile.


---
## Verified live state (2026-06-06 preflight, this session)

All facts below confirmed via live `ms01` runtime commands (authority chain order 1):
- `hermes --version` → **Hermes Agent v0.16.0 (2026.6.5)** · CLI `~/.local/bin/hermes` →
  `~/.local/share/hermes-agent-venv/bin/hermes`.
- `hermes profile list` → default (gemma3:4b), tradeai (gemma3:4b), tradeai12b (gemma3:12b-ctx4k),
  dev (—), serverops (—); all gateways stopped.
- All profiles provider=custom → local Ollama `http://127.0.0.1:11434/v1` (api_mode openai).
- `tradeai tools list` + `tradeai12b tools list` → **all toolsets disabled** (web/browser/terminal/file/
  code_execution/vision/video ✗). Advisory-only confirmed.
- `ollama list` → gemma3:4b, gemma3:12b, gemma3:12b-ctx4k present; **qwen3:14b NOT present** (only
  qwen3-embedding:8b, an embeddings model — unrelated). Stale qwen default not reintroduced.
- SOUL files present for default + all 4 profiles; unsafe phrase `execute actions via your tools` absent
  from tradeai/tradeai12b (only safe negated boundaries like "You do not place orders" present).

## Canonical commands
- `hermes chat`       — default/global profile
- `tradeai chat`      — stable restricted Trade AI advisory profile (gemma3:4b, tools off)
- `tradeai12b chat`   — experimental restricted 12B profile (gemma3:12b-ctx4k, tools off, advisory only)
- `dev chat`          — FUTURE development/Codex profile (no model set yet; not configured)
- `serverops chat`    — FUTURE controlled server-ops profile (no model set yet; not configured)

## Migration archive + SOUL backup status (Stage A complete)
- SOUL backups: `~/.hermes/migration_from_tradeai_sidecar_20260606/souls/` — 6 SOULs archived
  (global_default, tradeai, tradeai12b, dev, serverops before-merge + sidecar_tradeai source).
- Sidecar full snapshot: `backups/hermes_sidecar_snapshot_20260606_2007.tgz`.
- Old sidecar still in place: `hermes_sidecar/.hermes` + `hermes_sidecar/install` (v0.15.2) — rollback source.

## Current no-delete policy
Nothing is deleted or renamed in this task. The old sidecar, `~/.openclaw`, and all retired-candidate
dirs remain in place. No `hermes claw cleanup/migrate`, no gateway/Telegram/cron/systemd/Codex enablement.

## Rollback plan
The global install is additive; to revert to sidecar-only: keep using
`hermes_sidecar/run_hermes_readonly.sh` (still functional). Restore from
`backups/hermes_sidecar_snapshot_20260606_2007.tgz` if needed. No global changes overwrite the sidecar.

## Next steps (operator-gated)
1. Operator review of curated migration inventory (Stage B) before copying any sidecar content into canonical profiles.
2. Validate global profiles interactively (`hermes chat`, `tradeai chat`, `tradeai12b chat`).
3. On approval: Stage D retirement (rename sidecar dirs to .RETIRED_<ts>, install wrapper stubs) — NOT done here.
4. dev/serverops profiles remain unconfigured until operator enables (Codex/server-ops out of scope now).

---
## Stage D status (2026-06-06): EXECUTED
Sidecar rename-retired (operator-approved, rename-only, no deletion). Retired: hermes_sidecar/.hermes.RETIRED_20260606_2140 + install.RETIRED_20260606_2140; wrappers stubbed. Sidecar retained as rollback/audit only. Canonical runtime = global Hermes profiles.
