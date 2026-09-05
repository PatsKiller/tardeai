# Communications Gateway — Sender Inventory

**Attested SOURCE_COMMIT:** `17e30dcbb9a091f2fb9916f3c0d4ccabd5c5e72e`  
**Machine-readable ledger:** `docs/audit/_evidence/sender_inventory.json`  
**Generator:** `scripts/comms_phase0_sender_inventory.py`

Every retained sender has exactly one disposition:

| Disposition | Meaning |
|---|---|
| MIGRATE | Must publish via future gateway client / approved transport only |
| REMOVE | Dead code; delete after observation window |
| DISABLE | Keep file; block execution/egress |
| EXEMPT_WITH_EXPIRY | Allowed temporarily with owner + expiry |

**Unclassified count: 0** (among sender-pattern files).  
**Owners TBD:** 0 (provisional path-heuristic owners assigned 2026-09-05).  
**Phase 0 residual:** operator confirmation of provisional owners still recommended before treating sign-off as final.

---

## Counts (this attestation)

| Metric | Value |
|---|---|
| Senders classified | 224 |
| Excluded non-senders (crontab/refs without send patterns) | 238 |
| MIGRATE | 166 |
| EXEMPT_WITH_EXPIRY | 58 |
| REMOVE | 0 (none auto-assigned) |
| DISABLE | 0 (none auto-assigned) |
| MIGRATE with chokepoint baseline bypass | 44 |
| Owners TBD | 0 (provisional) |
| Provisional owner desks | cio, hermes, advisory, broker, risk, research, ops |

Chokepoint live scan: **45 producers / 133 violations** (ratchet pass, not zero).  
Baseline file: **46 files / 142 recorded violations**.

---

## EXEMPT_WITH_EXPIRY (approved boundaries)

Owner: `comms-gateway` · Expiry: `2026-12-31` (revisit at ACTIVE gate)

### Outbound adapters
- `scripts/telegram_transport.py`
- `scripts/telegram_alert.py`
- `scripts/alert_outbox.py`
- `scripts/lib/cio_telegram_transport.py`
- `scripts/lib/cio_notification_delivery.py`
- `scripts/lib/autonomy_watchdog/telegram_system.py`

### Inbound
- `scripts/telegram_callback_handler.py`
- `scripts/telegram_reply_processor.py`
- `scripts/telegram_command_handler.py`
- `scripts/run_telegram_callback_poller.py`
- `scripts/discover_telegram_chat_id.py`
- `scripts/cio_telegram_bot.py`

### Tooling / scanners
- `scripts/check_telegram_chokepoint.py`
- `scripts/audit_direct_telegram_senders.py`
- `scripts/secret_validators.py`
- `scripts/secrets/rotation_probes.py`
- `scripts/comms_phase0_attest.py`
- `scripts/comms_phase0_sender_inventory.py`
- Plus tests that necessarily mention forbidden patterns (see JSON ledger)

---

## MIGRATE — risk-ordered top cohort (baseline bypass + crontab)

These are the first migration candidates (approvals/protection/ops health priority for Phase 5):

1. `scripts/audit_position_basis.py`
2. `scripts/send_telegram_proposal_alert.py`
3. `scripts/atm_auto_approver.py`
4. `scripts/crawl_v3_dashboard.py`
5. `scripts/freshness_watchdog_heartbeat.py`
6. `scripts/pipeline_watchdog.py`
7. `scripts/premarket_watcher.py`
8. `scripts/pro_analyst_monitor.py`
9. `scripts/system_freshness_monitor.py`
10. `scripts/youtube_cookie_health_check.py`
11. `scripts/audit_enrichment_coverage.py`
12. `scripts/generate_max_hold_exit_proposals.py`
13. `scripts/schwab_position_sync.py`
14. `scripts/technicals_gap_backfill.py`
15. `scripts/watch_directives_service.py`
16. `scripts/eod_open_trade_alert.py`
17. `scripts/iris_taxonomy_agent.py`
18. `scripts/overnight_batch.py`
19. `scripts/send_morning_brief.py`
20. `scripts/social_scalp_scanner.py`
21. `scripts/system_health_alerts.py`
22. `scripts/proposal_alerter.py`
23. `scripts/send_no_leads_diagnostic_alert.py`
24. `scripts/send_watchpool_maturity_alerts.py`
25. `scripts/brokers/approval_service.py`

Full ordered list: `migrate_risk_order` in `sender_inventory.json`.

### Also MIGRATE (wrapper/outbox users)

Any producer calling `send_telegram`, `publish_event`, `send_cio_message`, `send_email`, `send_slack`, or `send_whatsapp` remains MIGRATE until it emits `CommunicationEvent` through the gateway client — even if it already uses a wrapper. Wrappers are transitional, not the end state.

---

## REMOVE / DISABLE

None auto-assigned this pass. Candidates should be promoted from MIGRATE after:

- zero crontab/systemd references for N days, and
- zero observed egress, and
- owner confirmation.

---

## Channel coverage in inventory

| Channel | Inventory treatment |
|---|---|
| Telegram | Primary — chokepoint baseline + wrappers |
| Email | MIGRATE where `send_email` / `smtplib` matched |
| Slack | MIGRATE where webhook helpers matched |
| WhatsApp / Twilio | MIGRATE where matched; product path (Meta vs Twilio) still an open question |
| Webhooks / agent notify / reports / callbacks / pollers | Included when patterns match; inbound pollers EXEMPT_WITH_EXPIRY |

---

## Owner assignment protocol

1. Export `sender_inventory.json`.
2. Provisional owners were assigned by path heuristic (cio/hermes/advisory/broker/risk/research/ops).
3. Operator should confirm or override desks; optionally reclassify DISABLE/REMOVE.
4. Re-run `scripts/comms_phase0_sender_inventory.py` after allowlist changes.
5. Record sign-off below.

---

## Sign-off

| Role | Name | Date | Notes |
|---|---|---|---|
| Attestor (automation) | Phase 0 scripts + host evidence | 2026-09-05 | Inventory + provisional owners |
| Operator | Accepted | 2026-09-05 | Approved provisional desks, exemptions, and baseline; proceed Phase 2 |
| Comms gateway owner | Accepted via operator | 2026-09-05 | Phase 0 closed; Phase 1 ledger already landed; Phase 2 enforcement next |

**Phase 0 exit status:** **ACCEPTED** (operator approved owners/exemptions 2026-09-05).
