# Communications Gateway — Runtime Attestation

**Attested at (UTC):** 2026-09-05T01:13:05Z  
**Attestation host evidence:** `docs/audit/_evidence/`  
**Classifier language:** LIVE / LIVE BUT PARTIAL / BUILT_DARK / DISCONNECTED / DESIGN_ONLY / ABSENT

This document records **runtime evidence**. Repository docs, Drive closeouts, and migration file headers are subordinate to these measurements.

---

## 1. Exact deployed SHA

| Field | Value | Class |
|---|---|---|
| `CURRENT` realpath | `/home/johnclaw/trade-ai-releases/portfolio-server/17e30dcbb-main-exact-phase2-20260904-210453` | LIVE |
| `SOURCE_COMMIT` | `17e30dcbb9a091f2fb9916f3c0d4ccabd5c5e72e` | LIVE |
| `GIT_SHA` | `17e30dcbb9a091f2fb9916f3c0d4ccabd5c5e72e` | LIVE |
| `BUILD_SHA` | `17e30dcbb9a091f2fb9916f3c0d4ccabd5c5e72e` | LIVE |
| Phase 0 worktree HEAD | `17e30dcbb9a091f2fb9916f3c0d4ccabd5c5e72e` | LIVE |
| Planning baseline (earlier) | `741207cc2f0e0ee5fe6445f750e608ddcfbbd3ee` | SUPERSEDED by live tip |
| Drift `741207cc..17e30dcbb` | CC header / CI token fixes only; **no communications file delta** | LIVE |

Evidence: `_evidence/sha_attestation.txt`, `_evidence/sha_drift_741207cc_to_17e30dcbb.txt`, `_evidence/sha_drift_comms_files.txt`.

**Rule:** Any later claim of LIVE capability must cite this SHA (or a newer re-attestation). Do not claim `741207cc` is still served.

---

## 2. Migration / schema level

| Object family | Observation | Class |
|---|---|---|
| Operator alert outbox tables | `mode_diagnostics().tables_missing == []`, `migration_applied: true` | LIVE (schema) |
| Delivery ownership | `delivery_owner: legacy_router_and_legacy_sender` | LIVE (legacy owns egress) |
| Migration SQL header | File still says “NOT APPLIED TO PRODUCTION” | DOC STALE — runtime wins |
| CIO notification stores | JSONL under `data/cio/` (`*notification*`, `*outbox*`) | LIVE BUT PARTIAL |
| `CommunicationEvent` tables | Not present | ABSENT |

Evidence: `_evidence/normalization_mode.json`, `_evidence/cio_notification_files.txt`.

---

## 3. Runtime modes / feature flags

| Control | Observed | Class |
|---|---|---|
| `TELEGRAM_NORMALIZATION_MODE` / policy `runtime_mode` | **OFF** (`policy:runtime_mode`) | LIVE (OFF) |
| Alert plane enum | OFF \| SHADOW \| ACTIVE (no CANARY in this enum) | LIVE code |
| CIO delivery modes | `INTERDICTED` / `PREPARE_ONLY` / `CIO_ONLY_LIVE` + worker `shadow\|live` | LIVE code |
| Advisory notif broker | Timer active; unit marked SHADOW — no egress cutover | BUILT_DARK / SHADOW |
| Email / Slack / WhatsApp enable flags | Names present in units/examples; operational activation **not** attested this pass | DISCONNECTED / UNPROVEN |

Evidence: `_evidence/normalization_mode.json`, `_evidence/operator_alert_policy_mode.txt`, `_evidence/env_flag_names.txt`.

---

## 4. Active queues, schedulers, adapters, agents

### Observed active (user systemd)

| Unit / timer | State (at attestation) | Role |
|---|---|---|
| `tradeai-cio-telegram.service` | active running | CIO dedicated Telegram converse bot |
| `tradeai-cio-delivery.timer` | active waiting | CIO notification delivery worker schedule |
| `tradeai-cio-material-scan.timer` | active waiting | Material decision scan schedule |
| `tradeai-advisory-notif-broker.timer` | active waiting | Advisory Tier-D SHADOW metrics |
| `tradeai-hermes-cio-worker.timer` | active waiting | Hermes CIO research worker |
| Multiple CIO timers (defer, reactive, reflection, memory shadow) | active waiting | CIO desk loops |

Evidence: `_evidence/systemd_units.txt`, `_evidence/systemd_timers.txt`.

### Crontab

Large producer surface: `_evidence/crontab_full.txt` / `_evidence/crontab_comms.txt` (hundreds of `scripts/*.py` references). Crontab presence ≠ sender; sender inventory filters to provider-pattern files.

### Adapters

| Adapter | Class |
|---|---|
| `scripts/telegram_transport.py` (general bot) | LIVE |
| `scripts/lib/cio_telegram_transport.py` | LIVE |
| `scripts/alerting.py` email/Slack/Twilio WhatsApp | DISCONNECTED / BUILT_DARK |
| `scripts/lib/cio_whatsapp_*` | BUILT_DARK (flag-off) |

---

## 5. Chokepoint / bypass debt (source evidence on live tree)

```
producers bypassing the chokepoint: 45
violations (scan): 133
baseline files: 46 / baseline violations: 142
result: ratchet PASS — NOT zero
```

Top offenders (direct `sendMessage` patterns):  
`proposal_alerter.py`, `audit_position_basis.py`, `send_no_leads_diagnostic_alert.py`, `trade_ai_news_monitor.py`, `pro_analyst_monitor.py`, `pipeline_watchdog.py`, `crawl_v3_dashboard.py`, `atm_auto_approver.py`.

Evidence: `_evidence/chokepoint_report_live.txt`, `_evidence/telegram_chokepoint_baseline.json`.

**Classification:** Telegram chokepoint enforcement = **LIVE BUT PARTIAL**. Universal gateway enforcement = **NOT PROVEN**.

---

## 6. Secrets / credentials (names only)

Observed name classes (values not recorded): `TELEGRAM_*`, `TELEGRAM_CIO_*`, `AUTHORIZE_*`, `CIO_*`, `ENABLE_EMAIL|SLACK|WHATSAPP|TELEGRAM`, `SMTP_*`, `SLACK_*`, `TWILIO_*`.

Evidence: `_evidence/env_flag_names.txt`.

---

## 7. Re-attestation procedure

```bash
cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
PYTHONPATH=scripts python3 /path/to/worktree/scripts/comms_phase0_attest.py \
  --current . --out /path/to/worktree/docs/audit/_evidence
PYTHONPATH=scripts python3 /path/to/worktree/scripts/comms_phase0_sender_inventory.py \
  --root . --out /path/to/worktree/docs/audit/_evidence
```

Update this file’s SHA table after every deploy before claiming LIVE.

---

## 8. Attestation sign-off checklist

- [x] Exact `SOURCE_COMMIT` captured from `CURRENT`
- [x] Normalization mode captured (OFF)
- [x] Chokepoint scan captured (non-zero debt)
- [x] Systemd / crontab snapshots captured
- [ ] Operator assigns owners for all `MIGRATE` rows (see sender-inventory.md)
- [ ] Operator signs Phase 0 packet
