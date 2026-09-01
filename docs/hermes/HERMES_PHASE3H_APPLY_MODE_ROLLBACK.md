# Phase 3H Rollback

Status:      HISTORICAL
as_of:       2026-05-31T09:40:49-04:00
Measured at: efcc51365 / not measured

## Revert to dry-run
```bash
sed -i 's/--apply --max-rows 2/--max-rows 3/' ~/.config/systemd/user/hermes-autonomous-loop.service
systemctl --user daemon-reload
```

## Delete Phase 3H rows
```sql
DELETE FROM hermes_research_intelligence WHERE id IN (10, 11) AND source='hermes' AND status='staged';
```

## Stop timer entirely
```bash
systemctl --user stop hermes-autonomous-loop.timer
systemctl --user disable hermes-autonomous-loop.timer
```
