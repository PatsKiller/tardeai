# Hermes Autonomous Loop — Operator Runbook

Status:      ACTIVE
as_of:       2026-05-31T09:43:27-04:00
Measured at: efcc51365 / not measured

---

## Current Configuration

| Setting | Value |
|---------|-------|
| Timer | `hermes-autonomous-loop.timer` |
| Schedule | Daily 01:00 UTC (9 PM ET) |
| Mode | Apply (--max-rows 2) |
| Model | gemma3:12b (local Ollama) |
| Writes to | hermes_research_intelligence only |
| Kill file | `hermes_sidecar/.hermes/DISABLED` |

## Check Status

```bash
# Timer status
systemctl --user status hermes-autonomous-loop.timer

# Last run
journalctl --user -u hermes-autonomous-loop.service -n 20 --no-pager

# Row count
PGPASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c "SELECT COUNT(*) FROM hermes_research_intelligence;"

# Dashboard
# http://ms01-openclaw.tail163d14.ts.net:7777/v2/hermes
```

## View Logs

```bash
journalctl --user -u hermes-autonomous-loop.service --since today --no-pager
```

## Activate Kill Switch (emergency stop)

```bash
touch /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/hermes_sidecar/.hermes/DISABLED
```

All loops will abort immediately on next run.

## Remove Kill Switch

```bash
rm /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/hermes_sidecar/.hermes/DISABLED
```

## Revert to Dry-Run Mode

```bash
sed -i 's/--apply --max-rows 2/--max-rows 3/' ~/.config/systemd/user/hermes-autonomous-loop.service
systemctl --user daemon-reload
```

## Disable Timer Entirely

```bash
systemctl --user stop hermes-autonomous-loop.timer
systemctl --user disable hermes-autonomous-loop.timer
```

## Re-Enable Timer

```bash
systemctl --user enable --now hermes-autonomous-loop.timer
```

## Daily Review Checklist

- [ ] Check `journalctl --user -u hermes-autonomous-loop.service -n 10`
- [ ] Verify row count didn't jump unexpectedly
- [ ] Verify no validation errors in logs
- [ ] Verify dashboard shows latest run info
- [ ] Verify no kill switch accidentally active

## Weekly Review

- [ ] Review last 7 days of staged rows for quality
- [ ] Check total row growth rate
- [ ] Verify no production writes occurred
- [ ] Verify embeddings count unchanged (unless separate approval)
- [ ] Verify paper_trades / paper_trade_proposals counts unchanged

## Row Caps

| Cap | Value |
|-----|-------|
| Per run | 2 |
| Per day | 3 (architecture design) |
| Model calls/day | 5 |
| Runtime | 600s |

## What NOT To Do

- Do NOT change --max-rows above 3 without approval
- Do NOT add --apply to additional loop types without approval
- Do NOT enable auto-embedding without approval
- Do NOT add external API keys without approval
- Do NOT change the model without approval
- Do NOT remove the kill switch mechanism

## Escalation Triggers

- Rows inserted > cap in a single run
- Validation errors in logs
- Service failing repeatedly
- Kill switch not working
- Unexpected production table changes
- Runtime exceeding 600s
