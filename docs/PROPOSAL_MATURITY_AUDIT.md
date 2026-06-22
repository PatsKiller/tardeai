# Proposal Maturity Audit — 2026-06-22

Target: **Maturity Level 10** — robust, high-edge, low-noise, explainable, proactively monitored.

## Executive Summary

| Area | Pre-audit | Post-audit (this release) | Gap remaining |
|------|-----------|---------------------------|---------------|
| **Options** | Engine existed; UI showed 0/Loading; no fallback | `options_engine.py` v2: fallback tier, BS estimate, health metrics, audit JSONL | Live Schwab chain when creds thin → BS estimate tagged |
| **Trade proposals** | ATM + auto_proposal; edge per-strategy | `unified_edge_score.py` shared composite (adopt in auto_proposal next) | Wire unified edge into `auto_proposal_generator.py` |
| **Watchlist** | Hermes enrichment; agent jobs | Health agent flags stale >7d | Auto-refresh job on stale threshold |
| **Rotation** | `strategy_rotation_recommendations` | Health metrics + empty alert | Deeper CIO/Aegis synergy with options CC flags |
| **Health Agent** | Cron/pipeline focus | `collect_proposal_maturity()` + `/api/v2/health/proposals` | Dashboard tile on Home (optional) |

## Options Module — Gaps & Fixes

### Gaps identified
1. **UI empty despite API data** — slow first fetch + stale dist; fixed OptionsHub error/stale/force-scan UX.
2. **Strict gates with no fallback** — zero proposals when Schwab chain unavailable; added relaxed income-sleeve tier.
3. **Defined-risk skipped without chain** — added Black-Scholes estimate path (tagged `data_source`).
4. **No cross-module health** — added `get_proposal_health_metrics()` + Health Hub panel.
5. **No decision audit** — `logs/options_engine.jsonl` append-only.

### Architecture (production)
- `scripts/options_engine.py` — proposals + monitor + overview + health metrics
- Caches: `options_proposals.json` (10m), `options_monitor.json` (5m)
- Cron: `run_options_monitor.sh` every 10m market hours; IV snapshot 16:20 ET
- API: `/api/v2/options/{proposals,positions,overview,execution/*}`
- UI: `OptionsHub.tsx` under Trading → Options
- Execution: Schwab pilot + `options_pilot_arm` + per-order 2FA

### Quality gates
| Gate | Strict | Fallback |
|------|--------|----------|
| Edge | ≥62 | ≥52 (intent sleeve) |
| POP | ≥52% | ≥47% |
| IV rank | ≥20% | same (intent symbols relaxed) |

## Trade & Strategy Proposals

- **Strength:** ATM fast-track, revalidation, risk gate, concentration cap (APGE lesson).
- **Gap:** Per-strategy edge not unified — `unified_edge_score.py` added for gradual adoption.
- **Recommendation:** Import `compute_unified_edge()` in `auto_proposal_generator.py` ranking pass.

## Watchlist & Rotation

- Watchlist: active items with `updated_at` >7d flagged in health agent.
- Rotation: `strategy_rotation_recommendations` count in health metrics.
- **Synergy:** `portfolio_intent.yaml` `covered_call_candidate` drives options CC priority + relaxed gates.

## Health Agent — Proposal Monitoring

New collector `collect_proposal_maturity()`:
- `options_zero_proposals` (after 10:00 ET, trading day)
- `options_proposals_stale` (cache >4h)
- `trade_proposals_backlog` (pending ≥25)
- `watchlist_stale` (active ≥15 stale >7d)

Auto-remediation (allowlisted): `run_options_monitor.py` on options zero/stale.

Policy: `config/health_agent_policy.json` → `proposal_maturity` section.

## Rollout & Testing

1. `python scripts/run_options_monitor.py` — verify proposals >0
2. `curl localhost:7777/api/v2/options/proposals` — count + SCHD CCs
3. `python scripts/health_agent.py` — check findings for proposal types
4. `npm run build` in `apps/command-center-v3` — reload `/v3/trading?tab=Options`
5. Health → Proposal Maturity panel shows live counts

## Maturity checklist (Level 10)

- [x] Explainable proposals (reasoning, data_source, edge breakdown)
- [x] Quality gates + fallback (not zero-noise failure)
- [x] Real-time position monitor (ITM/OTM, roll/close)
- [x] Schwab chain + BS fallback
- [x] Cron + job coverage registry
- [x] Health agent cross-module monitoring
- [x] Command Center UI (OptionsHub + Health panel)
- [x] Audit trail (`options_engine.jsonl`)
- [ ] Unified edge in trade proposal ranker (next PR)
- [ ] Home dashboard proposal health chip (optional)