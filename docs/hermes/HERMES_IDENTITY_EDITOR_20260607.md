# Hermes Identity Editor — Command Center v3 (2026-06-07)

Edit Hermes profile **identity (model/provider) + SOUL** from the UI, with hard safety guards. Available on
**System → Hermes** (Profiles table → "Edit Identity") and the **/v3/hermes** graph ("Global Hermes profiles
· edit identity" strip → ✎ Identity). Shared component: `apps/command-center-v3/src/components/HermesSoulEditor.tsx`.

## Modal sections
- **Identity** — editable Model + Provider; read-only context (current tools, config path, SOUL hash,
  policy note). "Save Identity" → backup-first write to the profile `config.yaml`.
- **SOUL / persona** — editable SOUL text; "Save SOUL" → backup-first write to SOUL.md (safety-validated).

## Backend endpoints
- `GET  /api/v2/hermes/identity?profile=<name>` — model/provider/base_url/tools/soul_hash/policy.
- `POST /api/v2/hermes/identity` — `{profile, model?, provider?}` → guarded write + config.yaml backup at
  `~/.hermes/profile_backups/<profile>/config.yaml.bak_<ts>`.
- `GET/POST /api/v2/hermes/soul` — SOUL read/save (backup at `.../SOUL.md.bak_<ts>`).
Allow-listed profiles only; path-traversal rejected.

## Hard guards (server-enforced; verified)
Identity saves are REJECTED when:
- model `qwen3:14b` (any profile) — must not be reintroduced.
- model `gemma3:12b` (unconstrained) on **default/tradeai** — only gemma3:12b-ctx4k on tradeai12b.
- cloud provider on **default/tradeai/tradeai12b** — these stay local Ollama (`provider=custom`).
- **Tools are NOT editable** in this UI — tradeai/tradeai12b remain tool-less by operator decision.
SOUL saves enforce: tradeai/tradeai12b boundary lines required; unsafe enabling phrases rejected
(sentence-scoped negation).

## Safety
Read + guarded-write of profile identity/SOUL only. No gateway/Telegram/Discord/Codex/cron/systemd enable;
no broker/trading/proposal/protection changes; no live trading; backups before every write.


## Update (2026-06-07) — switcher + dropdowns + metadata fields
- **Identity switcher**: left-side list of all 5 profiles; switch identity without closing the modal
  (`GET /api/v2/hermes/identity?profile=__all__`).
- **Dropdowns**: Model (from live `ollama list`) + Provider (allow-list; local-only profiles show only
  `custom`). Cloud/unsafe choices still blocked server-side.
- **Editable metadata**: Label/Name, Role/Purpose, Description — persisted to
  `~/.hermes/profiles/<profile>/identity_meta.json` (our metadata, separate from Hermes config). Defaults
  fall back to built-in labels when no override exists.
- model/provider still write to `config.yaml` (backup-first); SOUL unchanged.
