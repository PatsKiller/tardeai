# Phase 209F — Hermes Librarian Deep Dive (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T12:29:04-04:00
Measured at: efcc51365 / not measured

- **Who handles librarian functions?** The "Hermes Librarian" fleet agent (advisory/staging only).
- **Script:** `scripts/hermes_autonomous_librarian_backlog_loop.py`.
- **Timer:** `hermes-librarian-backlog-loop.timer` (systemd user; last result = success per 208E/209A).
- **Reads:** `hermes_research_intelligence` (staged findings), `hermes_validation_findings`, embeddings metadata.
- **Writes:** `hermes_research_intelligence` (status updates only — routes findings to embed/promote/backlog).
- **research_backlog:** backlog-tagged rows in `hermes_research_intelligence` surfaced by `/api/v2/hermes/
  research-backlog` (a dedicated `hermes_research_backlog` table is NOT yet created — known design note).
- **advisory cache:** `hermes_advisory_cache_worker.py` (separate) caches advisory opinions for fast v3 reads.
- **promotion review:** `hermes_embedding_promotion_reviewer.py` (advisory promotion recommendations →
  `hermes_promotion_audit`; Coordinator may auto-promote under directive B).
- **Hand-off:** Librarian reviews staged findings → routes to Embedding Curator (embed candidates,
  hermes_embedding_queue, gated) / Promotion Review (advisory) / Backlog. It does not embed or promote directly.
- **Reads from TradeAI safe views:** the read-only WALL views (hermes_v_*/safe views) — never the core tables.
- **Never touches:** core trading/broker/order/stop/proposal/holdings; does not embed/promote directly.
- **Inspect in v3:** /v3/hermes graph (Librarian node → drawer) + research-backlog + Source/Provenance tabs.
- **Failure signals:** SIEM (System → SIEM), Queue Control Tower, and a failed `hermes-librarian-backlog-loop.service`
  result (systemctl) → would surface as a staleness/health alert.
