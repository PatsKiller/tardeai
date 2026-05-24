# LLM Fleet Summary — 2026-05-14

**Generated:** 2026-05-14 22:39
**ALPACA_MODE:** paper

## Resident Models

| Model | Role | VRAM |
|-------|------|------|
| qwen3:14b | STANDARD/REALTIME | 10.09GB |
| nomic-embed-text:latest | EMBEDDING | 0.58GB |
| gemma3:4b | MEDIA/PROSE | 4.29GB |

## VRAM

Used: 13.9GB / 16GB

## Fleet Roles

- STANDARD/REALTIME: qwen3:14b
- MEDIA/PROSE: gemma3:4b
- EMBEDDING: nomic-embed-text
- HYBRID OFFLINE: qwen3-embedding:8b (transient)
- DEEP REASONING: gemma3-overnight (transient)

## Rollback

- Phase 2H: `./scripts/rollback_phase2g_canary.sh --disable`
- Phase 3: `./scripts/rollback_phase3_media_prose_routing.sh --disable`

## Status

Fleet operational. No alerts.
