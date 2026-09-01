# PHASE 212E — Codex Headless Test (current build, all command shapes) (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T15:33:32-04:00
Measured at: efcc51365 / not measured

No newer build, so tested every headless **command shape** on v0.16.0 against the authed openai-codex / gpt-5-codex:

| Command | Result |
|---------|--------|
| `hermes -z "..." --provider openai-codex -m gpt-5-codex` | ❌ "no final response was produced; treating the run as failed" |
| same with gpt-5 / gpt-5.1-codex / o4-mini / codex-mini-latest / o3 | ❌ identical |
| `hermes -p dev -z "..."` (configured codex defaults, no overrides) | ❌ identical |
| `hermes -z "..." --provider openai-codex ... --yolo` | ❌ identical |
| `hermes chat --oneshot "..."` | ❌ unrecognized argument |
| `hermes -p dev --oneshot "..."` | ❌ falls through to `-z`, same failure |
| `hermes stdio` / `echo ... | hermes -p dev chat` | ❌ not a one-shot path (chat exits) |

**CONCLUSION: newer Hermes fixes Codex headless = NO (no newer build). Headless Codex on the latest build =
NOT fixed.** Failure mode: the Codex/ChatGPT agent backend does not finalize a response through any
non-interactive path in v0.16.0. Usable command shape: **none headless**; interactive `hermes -p dev chat` only.
