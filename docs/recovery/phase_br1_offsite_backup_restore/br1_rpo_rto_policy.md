# BR-1 RPO/RTO Policy

## Targets

| Subsystem | RPO | RTO | Notes |
|-----------|-----|-----|-------|
| PostgreSQL DB | <= 24h (daily dump) | 30-60 min | Most critical state |
| .env/secrets | Manual secure copy | 15-30 min | Never in repo/plain Drive |
| Crontab/systemd | Latest backup | 15-30 min | Restore disabled first |
| Code (git) | Latest commit | 5 min | Push to remote |
| Docs/manifests | Latest Drive sync | 15-30 min | A1A source |
| RAG/embeddings | Rebuildable | 2-8h | Lower priority |
| Logs | Best effort | Non-critical | Audit only |
| LLM models | Re-pullable via Ollama | 1-8h | Bandwidth-dependent |

## Current State

- **DB RPO: ~24h** (daily 2 AM dump, 867MB compressed)
- **DB RTO: ~30 min** (pg_restore from local gzip)
- **Code RPO: ~0** (git, latest commit)
- **Secrets RPO: MANUAL** (no automated secure backup)
- **Offsite RPO: NOT CONFIGURED** (P0 gap)
