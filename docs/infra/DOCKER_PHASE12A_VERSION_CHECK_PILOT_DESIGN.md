# Docker Phase 12A — Version-Check Pilot Design

**Date:** 2026-05-31
**Status:** COMPLETE — design only

## Pilot
- Type: One-shot version-check job (exits immediately)
- Base: python:3.13-slim
- Output: OS, Python, Bash, kernel versions + safety confirmation
- Secrets: NONE
- DB: NONE
- Broker: NONE
- Production: NOT CONNECTED

## Files
- `docker/pilots/version-check/Dockerfile`
- `docker/pilots/version-check/run_version_check.sh`
- `docker/pilots/version-check/README.md`
