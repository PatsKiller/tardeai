
## 2026-06-22 — Schwab canary: all 3 accounts, standing unlock (2FA retained)

Pilot allowlist expanded to `schwab_taxable` + both IRAs; `schwab_pilot_standing_unlock` (no session
expiry, armed_until 2099); `CANARY_SESSION_DATE=2099-12-31`; cap 9999. Per-order 2FA unchanged.

## 2026-06-22 — SnapTrade / Fidelity stops + one-share test (docs sync)

**Fidelity (`fidelity_rollover_ira`):** SnapTrade read-only — monitor-only stops (`fidelity_monitored_stop`),
no broker execution, **no 2FA** on arm/breach (alert + Active Trader ticket). Standing unlock:
`snaptrade_pilot_arm.py --approve`. **Schwab:** live stops unchanged (2FA per order). **One-share test**
(no sandbox): `snaptrade_trade_pilot` + `--arm-test` + `POST /api/v2/snaptrade/trade/preflight|execute`
(when trade-capable broker + `ENABLED=True` commit). Specs: `docs/brokers/snaptrade-fidelity-protective-stops-spec.md`,
`stop-management-architecture.md`. Commits: `e205f53d`, `1494257e`, `7f91fadd`.

## 2026-06-22 — Intelligence engine + Command Center hub (all tabs A-grade)

Hermes→RAG closed loop: `hermes_embedding_enqueue.py` on promote, 2246-row backfill,
`hermes_research` in rag_indexer + library APIs, iris library-status deadlock fixed.
Command Center v3 Intelligence hub rebuilt: News/Research/Sources/Rotation tabs, URL sync,
Hermes/RAG KPIs. `CAP_EMBED` 2→10. Doc: `docs/intelligence_maturity_20260622.md`.

## 2026-06-22 — Docs consolidation (A1A) + full commit

Canonical docs aligned to live system: `LIVE_SYSTEM_FACTS.md`, MASTER/EXECUTIVE/CHEAT_SHEET/COST_MODEL
use live-fact pointers; drift detector hardened. Committed 32 pending files (strategy YAML performance
context, runtime JSON, finviz throttle + scripts). Closeout: `docs/project/DOCS_CONSOLIDATION_2026_06_22.md`.

## 2026-06-22 — Stabilization session + maturity audit (Grok CLI)

Full triage of health-agent findings (score 64): agent queue backlog (36 jobs >2h, drain batch started),
screener duplicate-key spam (fixed `53636262`, 10:00 errors pre-fix), overnight LLM queue root cause
(PHASE102-RETIRED cron — 1,941 pending), SIEM alerts acked (fused_signals + DB SSL transient), KTOS/KBR
stop-outs flagged for operator review. Maturity audit ≈7.1/10. Docs:
`docs/project/STABILIZATION_SESSION_2026_06_22.md`, `docs/project/MATURITY_AUDIT_2026_06_22.md`.

## 2026-06-19 — Defense/BDC rotate-gap directives seeded (audit Task 5)

Seeded 8 `rotate_gap` watch directives for held Schwab-taxable defense/BDC positions flagged in the
Aegis brief: LHX, LMT, NOC, BAH, LDOS, KBR, CACI (defense_thesis sleeve) + PFLT (high_yield_bdc).
Mapped onto the REAL `watch_directives` schema (kind='ticker', label=symbol, spec={symbol,gap_type:
rotate_gap,sleeve,flagged}, created_by='operator_audit', status='active', priority='high'). The
rotation/promotion engine consumes active operator directives on its scheduled cycle to surface
sleeve replacements. Advisory only — no position change, no order writes. Note: these were Aegis-brief
flags, not recorded broker-stop triggers (stop_lifecycle had no rows; risk_stops table does not exist).
