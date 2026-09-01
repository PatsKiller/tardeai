# PHASE 213A — Codex Headless Limitation — Authoritative Finding (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T16:43:49-04:00
Measured at: efcc51365 / not measured

- Current Hermes version: **0.16.0**. Latest available: **0.16.0** (no newer; no pre-release; 0.16.1 absent).
- **No shadow venv created**: there is no newer version to shadow; shadowing the same 0.16.0 would only
  reproduce the limitation. (Phase 212.)
- Tested Codex models: gpt-5-codex, gpt-5, gpt-5.1-codex, gpt-5.1, o4-mini, o3, codex-mini-latest, gpt-5-codex-mini.
- Tested command shapes: `hermes -z --provider openai-codex -m <model>`, `hermes -p dev -z` (configured
  defaults), `--yolo`, `hermes chat --oneshot`, `hermes -p dev --oneshot`, stdin→chat.
- Common failure text: **"no final response was produced; treating the run as failed."**
- Root cause classification: **`hermes_headless_limit`** (NOT auth, NOT credits, NOT model choice, NOT version).
- Interactive status: **working** (`hermes -p dev chat`, openai-codex / gpt-5-codex, subscription-backed/free).
- Automation status: **unavailable**.
- Next re-test trigger: **Hermes version > 0.16.0, or changelog documents a headless/non-interactive Codex fix.**
