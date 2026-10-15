# DD12 outside dead-man + business heartbeat — operator packet (2026-10-15)

Design: `docs/implementation/n8n-maturity/DD12_OUTSIDE_DEADMAN_AND_DR_PLAN_20261015.md`. Nothing here was installed,
activated, pinged or sent by the agent. Every step below is operator-only (provider account, secret, systemd timer).

## What gets activated

| Check | Sender | Config | Secret NAME (value is yours) | Receipt |
|---|---|---|---|---|
| A: alert-path dead-man | `scripts/offbox_deadman.py` | `config/offbox_deadman.json` | `TRADEAI_OFFBOX_DEADMAN_PING_URL` | `data/runtime/offbox_deadman_last.json` |
| B: business-output heartbeat | `scripts/offbox_deadman.py --config config/offbox_business_heartbeat.json` | `config/offbox_business_heartbeat.json` | `TRADEAI_OFFBOX_BUSINESS_HEARTBEAT_PING_URL` | `data/runtime/offbox_business_heartbeat_last.json` |

## 1. Provider (operator)

Create two pull-on-miss checks (healthchecks.io-class) with separate UUIDs:

- A: period 5 min, grace 10 min, email (+ phone push if wanted).
- B: period 15 min, grace 15 min, email.

Store each ping URL in Bitwarden SM under the NAME above. The agent never reads the value.

## 2. Dry runs (no network, safe for anyone)

```bash
cd ~/trade-ai-releases/portfolio-server/CURRENT
python3 scripts/offbox_deadman.py --dry-run
python3 scripts/offbox_deadman.py --dry-run --config config/offbox_business_heartbeat.json
```

Expected: `"outcome": {"status": "DRY_RUN", "network": false}`; each check row `ok` true (or `outside_window` for
`scalp_cycle_rth` outside 09:50-15:55 ET on weekdays). A false row is a real finding: fix it before step 3.

## 3. Timers (operator, `service` grant)

Proposed units (not installed). Both `Type=oneshot`, own timers, never n8n, never the health tick.

```ini
# ~/.config/systemd/user/tradeai-offbox-business-heartbeat.service
[Unit]
Description=Trade AI off-box business-output heartbeat (DD12)
[Service]
Type=oneshot
WorkingDirectory=%h/trade-ai-releases/portfolio-server/CURRENT
EnvironmentFile=%t/tradeai-secrets/offbox_business_heartbeat.env
ExecStart=/usr/bin/python3 scripts/offbox_deadman.py --live --config config/offbox_business_heartbeat.json

# ~/.config/systemd/user/tradeai-offbox-business-heartbeat.timer
[Timer]
OnCalendar=*:0/15
Persistent=false
[Install]
WantedBy=timers.target
```

`EnvironmentFile` is a rendered secret file holding only `TRADEAI_OFFBOX_BUSINESS_HEARTBEAT_PING_URL`. Check A uses
the same shape at `*:0/5` with its own env file (PR #1751's packet).

Apply: `systemctl --user daemon-reload && systemctl --user enable --now tradeai-offbox-business-heartbeat.timer`.
Proof (rule 8): `data/runtime/offbox_business_heartbeat_last.json` with `"status": "PINGED"` and the provider showing
the check green.

## 4. Rollback

`systemctl --user disable --now tradeai-offbox-business-heartbeat.timer`, then pause check B in the provider (a
stopped sender otherwise alarms, which is the design). No host state to undo; the receipt stays as evidence.

## 5. Drill (quarterly, harmless)

Stop both timers for 30 minutes outside market hours; both provider alerts must arrive within period + grace;
restart; both recover. Record the provider alert log path in `docs/RESTORE_GUIDE.md` §0.
