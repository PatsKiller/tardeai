# CC v3 Home — Trust Hardening (Grok lane)

**Branch:** `grok/cc-v3-home-trust-hardening-v1`  
**Owner:** Grok (isolated from agent-runtime / other developer lanes)  
**Date:** 2026-07-26

## Problem set (from live Home audit)

| Issue | Root cause | Fix |
|-------|------------|-----|
| Morning Synthesis = `. **##` spam | Corrupt gemma output cached without quality gate | `llm_content_quality.is_valid_prose` before upsert; HomeBriefingPanel fail-closed |
| Market Movers all zeros on Sunday | RTH-only Finviz capture; empty state looked broken | Empty-state taxonomy: weekend / premarket / afterhours / capture_failed |
| SETUPS 0/0/0 · last run Jul 23 | Scanner idle over weekend; zeros read as empty universe | `isScanStale` → **STALE · last run …** |
| Unprotected 11 vs briefing 7 | LLM invented count | portfolio_risk prompt forces `risk_management.json` count |
| Book map Jul 24 vs prices Jul 26 | holdings.json lag | BookTreemap lag badge |
| Hermes Gateway offline | systemd `hermes-gateway.service` inactive | **Not a false positive** — see below |
| Thin equity curve | metrics-history short | Home note when &lt;10 days |
| Health: unlinked trade / manifest FAIL | Real process debt | plainAlert translations |

## Hermes gateway investigation

**Verdict: not a false positive.**

- Home reads `/api/v2/hermes/health` → `gateway_status`.
- Canonical builder (`scripts/build_hermes_canonical_status.py`) sets:
  `gateway_status = systemctl is-active hermes-gateway.service / is-enabled …`
- **offline / inactive** means the systemd unit is not active.
- **Autonomous loop ON + staged research &gt; 0** is compatible with gateway offline:
  coordinator / autonomous research can write staged rows without the gateway daemon.
- Gateway is the real-time Hermes sidecar; absence degrades live coordination, not necessarily batch staging.

### How to resolve (operator)

```bash
systemctl --user status hermes-gateway.service
systemctl --user start hermes-gateway.service   # if unit exists and should be up
# or system-level:
systemctl status hermes-gateway.service
journalctl -u hermes-gateway.service -n 80 --no-pager
```

If the unit is intentionally stopped on weekends, Home now labels:
`offline · research still staging via loop` when autonomous loop is ON.

## Free LLM preference

`llm_intelligence_enrichment.py` calls `local_llm.generate(..., fast=True, caller=llm_intelligence_enrichment)`.
Local Ollama (gemma) first; cloud only if fallback enabled. Set `LOCAL_LLM_NO_CLOUD=1` to force local-only.

## Files touched

- `scripts/llm_content_quality.py` (new)
- `scripts/llm_intelligence_enrichment.py`
- `apps/command-center-v3/src/lib/homeLabels.ts`
- `apps/command-center-v3/src/components/home/MarketMoversBoard.tsx`
- `apps/command-center-v3/src/components/home/BookTreemap.tsx`
- `apps/command-center-v3/src/components/home/HomeBriefingPanel.tsx` (new)
- `apps/command-center-v3/src/pages/HomeHub.tsx` (wire-up)
- `tests/test_llm_content_quality.py` (new)
- this doc

## Safety

Advisory / display only. No broker, order, approval, 2FA, or production migration.
