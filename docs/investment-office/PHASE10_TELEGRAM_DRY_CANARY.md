# PHASE 10 — Telegram DRY Canary (acceptance measurement)

**UTC:** 2026-08-14
**Branch:** `wt/cio-v4-phases-3-21`
**Version:** `cio_telegram_dry_canary_1.0.0`
**Authority:** `READ_ONLY_ADVISORY` unchanged

## Goal

Acceptance must not award Telegram isolation credit from `or True` (already
removed in v4). This phase adds a **DRY** canary that:

1. Uses the real CIO transport (`scripts/lib/cio_telegram_transport.py`)
2. **Measures** that general `TELEGRAM_BOT_TOKEN` is not read for send
3. Prepares a real-shaped portfolio decision (SCHD trim)
4. Records would-send path, chat target type (CIO vs general), duplicate key
5. Writes `data/audit/cio_telegram_canary_receipt.json` **only as DRY**
6. `scripts/run_cio_telegram_canary.py --dry-run` (default) never HTTP
7. Live send stays behind explicit env **and** `--live` **and** the operator
   approval phrase; if any are missing, dry only

## Receipt (DRY only)

`data/audit/cio_telegram_canary_receipt.json`:

```json
{
  "sent": false,
  "dry_run": true,
  "operator_approved": false,
  "cio_chat_confirmed": false,
  "general_sends": 0,
  "release_sha": "<BUILD_SHA if present>",
  "duplicate": false,
  "proof": "dry"
}
```

`general_sends` is a **counted** integer from wrapped `send_message` /
requests / urllib attempts that used the general bot. It is not assumed
`True` and is not `or True`. A missing receipt still leaves G14
`proof_general_sends=None` → FAIL (unproven ≠ pass).

`release_sha` is read from `BUILD_SHA` (env, then
`/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/BUILD_SHA`, then
repo `BUILD_SHA`). Empty if none present.

## CLI

```bash
python3 scripts/run_cio_telegram_canary.py              # dry-run default
python3 scripts/run_cio_telegram_canary.py --dry-run    # explicit
python3 scripts/run_cio_telegram_canary.py --live       # still dry unless fully gated
```

Live send (not run in this phase) requires **all** of:

```bash
# already set in the environment — the script never sets these
export AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1
export CIO_TELEGRAM_CANARY_ENABLE=1
export CIO_TELEGRAM_CANARY_APPROVAL=I_APPROVE_CIO_CANARY_SEND
python3 scripts/run_cio_telegram_canary.py --live
```

`--dry-run` wins if both flags are passed. Pytest always forces dry.
In-process force cannot open the live path.

A live receipt, if it ever exists, is written to
`data/audit/cio_telegram_canary_receipt_live.json` so the DRY file cannot
be overwritten with `sent: true`.

## Package

SCHD trim (capital-plan geometry): weight ~17.66% vs 16.5% fire / 12% policy,
recommended delta about −$44,361. Prepared via
`cio_alex_telegram.prepare_canary_package` / `evaluate_outbound`. Dry path
never calls `send_cio_message` or `execute_canary_send`.

| Field | Dry value |
| --- | --- |
| `would_send_path` | `scripts.lib.cio_telegram_transport.send_cio_message` |
| `chat_target_type` | `cio` (never `general`) |
| `duplicate_key` | decision_id + material-state fingerprint |
| `general_token_reads_for_send` | `0` (measured on `cio_bot_token` / `cio_chat_ids`) |

## Acceptance wiring

`scripts/run_cio_acceptance.py` reads the canonical dry receipt when the
per-run evidence copy is absent, and copies `general_sends` into
`proof_general_sends`. G15 still requires a **live** exact-release canary
(`sent: true`, operator approved, CIO chat confirmed) — prepare-only ≠ pass.

## Tests

```
tests/test_cio_telegram_canary_dry.py
tests/test_cio_phase1_notification_containment.py
tests/test_cio_phase9_alex_telegram.py
```

## Safety

## REAL TELEGRAM SENDS: 0
## BROKER CALLS: 0
## SECRETS PRINTED: 0
## AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY SET BY THIS PHASE: NO
## FINANCIAL AUTHORITY CHANGED: NO
