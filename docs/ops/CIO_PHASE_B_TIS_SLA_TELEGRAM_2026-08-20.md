# CIO Phase B — TIS layout, thesis SLA, Telegram digests (2026-08-20)

**Authority:** READ_ONLY_ADVISORY  
**Branch:** `feat/cio-phase-b-tis-sla`

## What you asked for

1. **Phase B** material thesis coverage (holdings + reentry + watch), not concentration-gated.
2. **Telegram should work** for that advisory loop (digest + existing ACT_NOW/concentration IMMEDIATE).
3. **Document the actual layout on a Command Center page**, and make requirements **editable** there.

## TIS = Thesis Investment System

Command Center: **`/v3/cio?tab=tis-layout`**

- Documents the real operating layout (material universe, thesis SLA, holdings parity, reentry/watch progress, Telegram).
- Live SLA strip: % CURRENT for holdings / reentry READY·NEAR / watch desk.
- Editable requirements (SLA %, stale days, concentration fire as *risk-only*, Telegram on/off, digest cooldown, reentry research tier, blocked-RAG `skip_until` hours).
- **Save** → `data/cio/cio_tis_policy_override.json` (backed up). Defaults live in `scripts/lib/cio_tis_policy.py` (`EMBEDDED_DEFAULTS`).

APIs:

- `GET /api/v3/cio/tis-policy`
- `PUT` / `POST /api/v3/cio/tis-policy`
- `GET /api/v3/cio/tis-coverage-sla`

## Thesis SLA (not 12% weight)

| Bucket | Default target |
|--------|----------------|
| Holdings CURRENT pin | 100% |
| Reentry READY/NEAR CURRENT | 100% |
| Watch desk CURRENT | ≥80% |

Concentration fire (default 12%) remains **S6 risk only**. Visa / Dexcom / every holding are thesis-eligible regardless of weight.

## Acquisition + research scheduler

- `run_symbol_thesis_acquisition.py`: on BLOCKED (empty RAG), stamps `skip_until` (default 72h from TIS); skips those symbols on later debt runs until expiry.
- `research_scheduler.py`: new tier **`T0-REENTRY`** + mode **`--mode reentry`** (READY/NEAR from `reentry_decision_desk_latest.json`). SLA refreshes/window overridable via TIS.

## Telegram

| Class | When |
|-------|------|
| IMMEDIATE | Unchanged situation path: S6 fire flip, S3 capital RE_ENTER+ACT_NOW, S1 material, S5, S8 |
| DIGEST | `scripts/cio_tis_telegram_digest.py` — SLA breach, held thesis debt, reentry thesis debt (CIO bot only) |

```bash
# Worktree has no .venv — use canonical Python
PY=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
cd /tmp/wt-cio-phase-a   # or CURRENT / canonical checkout

# Dry
$PY scripts/cio_tis_telegram_digest.py \
  --root /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Live (source CIO bot env first — agent cannot load Bitwarden secrets)
set -a && source ~/.config/tradeai/cio-telegram.env && set +a
export AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1 ENABLE_TELEGRAM=1 CIO_TELEGRAM_INTERDICT=0
$PY scripts/cio_tis_telegram_digest.py \
  --root /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild --apply

# Or governed wrapper (same env load + flock):
bash scripts/run_governed_cio_tis_digest.sh
```

Host still needs `CIO_SITUATION_NOTIFY=1` for situation IMMEDIATE; digests use `send_cio_message` directly with fingerprint cooldown from TIS.

Suggested cron (installed via wrapper comment; weekdays 12:15 + 17:15 ET):

```
15 12,17 * * 1-5 /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/run_governed_cio_tis_digest.sh >> /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/logs/cio_tis_digest.log 2>&1 # TRADEAI_GOVERNED_WORKER cio-tis-digest
```

## Tests

```bash
.venv/bin/python -m pytest tests/test_cio_tis_policy.py -q
```

## Explicit non-goals (still Phase C+)

- Auto-promote watch → S7 candidates when desk is all BLOCK.
- Full 6k discovery theses.
- Broker execution.
