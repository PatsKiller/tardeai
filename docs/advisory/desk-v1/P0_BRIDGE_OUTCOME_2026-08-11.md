# P0 Outcome — Governed Bridge Path for Advisory Desk

**Date:** 2026-08-11  
**Branch:** `feature/advisory-desk-v1`  
**Plan:** [AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md](./AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md)  
**Authority:** READ_ONLY_ADVISORY  

---

## Problem (pre-fix)

The opinion engine **bypassed** `cio_governed_model_bridge` and called `https://api.deepseek.com` directly with `deepseek_tradeai` from the SM env file. Consequences:

- `LLM_GLOBAL_DAILY_USD_CAP` not on path  
- Desk / process sub-budgets not enforced  
- Consumption reservation/settlement not recorded for desk calls  
- Port 8766 not required → no systemd bridge for the desk  

Config claimed `http://127.0.0.1:8766` while runtime ignored it for `provider == "deepseek"`.

---

## Fix (PR-0a / 0b / 0c)

| Item | Change |
|---|---|
| **PR-0a** | `scripts/lib/advisory/advisory_opinion_engine.py` — remove direct DeepSeek override; always use bridge for DeepSeek; surface `COST_CAP_EXCEEDED` as `governance_refused` |
| **PR-0a** | Synthesis prefers `deepseek-pro` + task_type `advisory_synthesis` (not lane[0] flash) |
| **PR-0a** | Bridge honors `X-TradeAI-Task-Type` for process selection; `requested_policy` fixed on model policy resolution |
| **PR-0a** | Register `advisory_desk_opinion` (FAST, $0.05/day) and `advisory_desk_synthesis` (PRO, $0.03/day) in `config/llm_process_registry.json` |
| **PR-0b** | User unit `config/systemd/user/cio-governed-bridge.service` — canary mode, `EnvironmentFile=-%t/tradeai/env`, after `tradeai-sm-render` |
| **PR-0c** | `tests/test_advisory_bridge_routing.py` — no public API URL, cap refuse proof, synthesis task type, process map |

### Flag

`ADVISORY_DESK_V1: false` in `config/advisory_desk.yaml` (default OFF). Enrichment remains opt-in.

### Credential path (unchanged SM wiring)

```
Bitwarden SM trade-ai-prod / deepseek_tradeai
  → tradeai-sm-render → /run/user/<uid>/tradeai/env
  → cio-governed-bridge.service EnvironmentFile
  → RealProvider (canary)
```

Opinion engine never reads the API key for DeepSeek; only the bridge does.

---

## Pass criteria status

| # | Criterion | Status |
|---|---|---|
| 0.1 | Engine routes DeepSeek via 8766 | **CODE PASS** (unit tests) |
| 0.2 | Process registry entries exist | **CODE PASS** |
| 0.3 | systemd unit checked into repo | **CODE PASS** — install/enable is operator step |
| 0.4 | `ADVISORY_DESK_V1` default OFF | **CODE PASS** |
| 0.5 | Cap exhaustion refuses call | **PASS** — unit + **live** 429 `COST_CAP_EXCEEDED` (see ops-evidence) |
| Live | Bridge listening on 127.0.0.1:8766 | **PASS** — `cio-governed-bridge.service` enabled & active 2026-08-11 |

**Evidence:** `ops-evidence/advisory-desk-bridge-p0/CAP_EXHAUSTION_PROOF.json`

**Still deferred (by design for P0):** live paid Flash opinion under normal cap with consumption ledger settlement line — do that in Phase 1 under `ADVISORY_DESK_V1` with a small row budget, not during cap-proof.

---

## Operator install (bridge)

```bash
# 1) Ensure SM env is fresh
systemctl --user start tradeai-sm-render.service

# 2) Install unit (repo copy → user systemd)
cp config/systemd/user/cio-governed-bridge.service \
   ~/.config/systemd/user/cio-governed-bridge.service
systemctl --user daemon-reload
systemctl --user enable --now cio-governed-bridge.service
systemctl --user status cio-governed-bridge.service --no-pager

# 3) Prove listen
ss -ltnp | grep 8766

# 4) Forced-exhaustion (optional live): temporarily set
#    Environment=LLM_GLOBAL_DAILY_USD_CAP=0.0001 in a drop-in,
#    restart bridge, call opinion once, expect COST_CAP_EXCEEDED,
#    restore cap.

# 5) Unit tests (no live spend)
.venv/bin/python -m pytest tests/test_advisory_bridge_routing.py -q
```

---

## Files touched

- `scripts/lib/advisory/advisory_opinion_engine.py`
- `scripts/lib/cio_governed_model_bridge.py`
- `config/advisory_desk.yaml`
- `config/llm_process_registry.json`
- `config/systemd/user/cio-governed-bridge.service`
- `tests/test_advisory_bridge_routing.py`
- `docs/advisory/desk-v1/AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md`
- `docs/advisory/desk-v1/P0_BRIDGE_OUTCOME_2026-08-11.md` (this file)

---

## Next (Phase 1, after live bridge green)

1. Productionize lot rebuild  
2. Catalyst cache path fix  
3. Plausibility on build path  
4. Risk/Tax holdings job enqueue  
5. Flash enrichment under `ADVISORY_DESK_V1` only  

Do **not** start `/v3/advisory` or Telegram delivery until live bridge + cap refuse are evidenced in ops.

---

*Advisory only. No broker credentials or order authority granted.*
