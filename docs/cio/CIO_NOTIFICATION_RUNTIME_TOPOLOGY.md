# CIO Notification Runtime Topology

Authority: `READ_ONLY_ADVISORY`. Read-only enumeration of the live timer /
service / release topology for the CIO Telegram desk. No service was stopped or
modified during this audit.

## Release truth (verified 2026-08-17)

The live units run from the deployed release, **not** the workspace:

- `WorkingDirectory=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT`
- `CURRENT` → `968dafb6-main-exact-phase2-20260816-215459` (i.e. main `968dafb6`,
  the base of both PR #341 and #340)
- `PYTHONPATH=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT:...`
- venv: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv`

The workspace (`/home/johnclaw/tradeai-wt-cio-decision-truth`) is the source of
truth for code, but code changes there are **not live** until a release
deployment (not authorized in this pass).

Verified 2026-08-17: the live release does **not** contain
`scripts/lib/cio_notification_signal.py` and its `cio_material_scan.py` has no
`notification_gate` branch — i.e. the live desk is still running the pre-gate
scanner that produced the Aug-17 spam.

## Relevant user timers (verified `systemctl --user list-timers`)

| Timer | Unit | Cadence (observed) |
|---|---|---|
| `tradeai-cio-material-scan.timer` | `tradeai-cio-material-scan.service` | 10 min |
| `tradeai-cio-delivery.timer` | `tradeai-cio-delivery.service` | 5 min |
| `tradeai-cio-defer-revisit.timer` | `tradeai-cio-defer-revisit.service` | 1 hr |
| `tradeai-cio-reactive.timer` | `tradeai-cio-reactive.service` | 2 min |

Long-running: `tradeai-cio-telegram.service` (converse bot, `--loop`).

System-level (`systemctl list-timers`) shows only `tradeai-reprice.timer` and
`tradeai-continuous.timer` — **no** root/system CIO material scanner.

## Scanner service

`tradeai-cio-material-scan.service` → `scripts/cio_material_scan.py --live`
(oneshot, from the release `CURRENT`). This is the observed spam source: the
timer tick fed `scan_office()` → `select_publications()` → `publish_material_decision()`
with no semantic gate.

A `tradeai-cio-material-scan-dry.service` unit also exists (`--dry-run`), but is
`static` (not timer-activated) and does not send.

## No duplicate scanner (verified)

- `crontab -l` (488 lines) contains **no** CIO material-scan entry. The legacy
  `cio_decision_engine.py --run` and `run_alex_daily.py` cron entries are
  commented out (DISABLED, moved to `agent-runtime@*.timer` shadow-live).
- No root/system scanner unit.
- At snapshot, the only long-running CIO processes were
  `cio_telegram_bot.py --loop` (inbound) and `cio_governed_model_bridge.py`
  (governed bridge); no live `cio_material_scan.py` process (it is oneshot).
- `sudo crontab -l` could not be read without a password; this is the one
  residual gap and should be confirmed by the operator before a live cutover.

## Delivery worker

`tradeai-cio-delivery.service` → `scripts/cio_delivery_worker.py --once --mode live`.
This is the outbox-based delivery path (`scripts/lib/cio_notification_delivery.py`).
It is a **separate** path from the scanner's direct delivery; it is shadow-only
by default and is reconciled onto the single notification gate in the explicit
AIF↔CIO integration follow-up (not this pass).

## Direct senders

The repository contains many scripts that reference `send_telegram` /
`send_message`. The CIO **proactive** material path funnels through
`send_cio_message` (CIO-only token/allowlist) via `deliver_decision`:

- `cio_material_scan.py` → `publish_material_decision()` → `deliver_decision()`
  → `cio_telegram_transport.send_cio_message()`.
- `cio_defer_revisit.py` → `publish_material_decision()` (same path).
- `cio_notification_delivery.py` → `send_cio_message()` (same transport).

No live general-channel sender for the CIO desk was found in the material-scan
path. The universal-chokepoint enforcement for the scanner is implemented in
`scan_office()` (see `CIO_NOTIFICATION_POLICY.md`).

## Consequence for this change

This change is implemented on a stacked branch from the exact `#341` head and is
**not deployed**. The live timer continues to run from the current release until
the operator explicitly authorizes a release. No live flag was changed.

```bash
# Verification commands (read-only)
systemctl --user list-timers
systemctl --user cat tradeai-cio-material-scan.service
systemctl --user cat tradeai-cio-delivery.service
```
