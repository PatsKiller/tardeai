# Docker Readiness Checklist

Status:      ACTIVE
as_of:       2026-05-31T17:44:35-04:00
Measured at: efcc51365 / not measured

Must pass ALL checks before any container pilot.

## Preflight
- [ ] Docker Engine installed
- [ ] Docker Compose available
- [ ] GPU passthrough tested (if Ollama containerization planned)
- [ ] Backup verified before migration
- [ ] Port conflict audit completed
- [ ] .env/secrets NOT baked into images

## First Pilot Only
- [ ] Pilot is read-only or non-production
- [ ] Pilot does NOT touch PostgreSQL
- [ ] Pilot does NOT touch Ollama
- [ ] Pilot does NOT touch broker/execution
- [ ] Pilot does NOT modify .env
- [ ] Pilot has explicit rollback procedure
- [ ] Pilot approved by operator

## Do NOT Containerize
- [ ] PostgreSQL remains bare-metal
- [ ] Ollama remains bare-metal (GPU)
- [ ] Portfolio Server remains bare-metal
- [ ] OpenClaw Gateway remains bare-metal
- [ ] Hermes autonomous timer remains systemd
- [ ] Alpaca/paper execution remains bare-metal
