# Phase 208 — Hermes End-to-End Agent Audit — CLOSEOUT (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T11:35:15-04:00
Measured at: efcc51365 / not measured

- Phase 208 complete: **YES** (208A–208L).
- Why old agents retired: sidecar (v0.15.2, own gateway+runtime) superseded by global Hermes v0.16.0 + profiles; always-on `--accept-hooks` gateway was an unwanted autonomous surface → rename-retired, gateway stopped/disabled.
- Keeping retired safe: **YES** (208F proof — no active dependency; mtimes untouched).
- Active global profile count: **5** (default, tradeai, tradeai12b, dev, serverops).
- Live research-fleet agent count: **7** (coordinator, source_discovery, librarian, embedding_curator, promotion_review, backlog_manager, autonomous_research).
- Retired artifact count: **5** tracked (2 sidecar profiles + 1 install runtime + 2 wrapper stubs); ~24 items in legacy inventory.
- Active SOUL count: **5** · Retired SOUL count: **4** (sidecar snapshots).
- Jobs audited: **25** · jobs calling retired wrappers: **0 active** (only the disabled hermes-gateway unit references the path) · jobs depending on retired gateway: **0**.
- Gateway remains disabled: **YES** · retired wrappers executed: **NO**.
- Active jobs healthy: **YES** (all 9 timers last-result = success) · live fleet healthy: **YES** (476 writes/24h, 1947/7d).
- Tool policy safe: **YES** · tradeai/tradeai12b safety tools unchanged: **YES** (0 enabled).
- v3 Hermes visibility improved: **YES** (SOUL hash/mtime provenance added; legacy read-only inventory present).
- v2 UI changed: **NO** · trading/proposal/protection/broker touched: **NO** · live trading: **ZERO** · Level 7: **PROHIBITED**.
- P0 risks found: **0**.
- Next recommended gate: P1 items (operator-approved) — (a) repoint Coordinator kill-switch off retired `.hermes/DISABLED` path; (b) harden `serverops` dangerous tools before configuring it.

Evidence: docs/hermes/PHASE208A..K + data/hermes/hermes_*_audit_latest.json.
