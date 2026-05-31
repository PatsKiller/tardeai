# Phase 3H Rollback

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
