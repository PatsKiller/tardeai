# Hermes Phase 3F — Timer Disable/Rollback

## Disable Timer
```bash
systemctl --user stop hermes-autonomous-loop.timer
systemctl --user disable hermes-autonomous-loop.timer
systemctl --user stop hermes-autonomous-loop.service
```

## Remove Timer/Service
```bash
rm -f ~/.config/systemd/user/hermes-autonomous-loop.timer
rm -f ~/.config/systemd/user/hermes-autonomous-loop.service
systemctl --user daemon-reload
```

## Verify
```bash
systemctl --user list-timers | grep hermes  # should be empty
systemctl --user is-active hermes-autonomous-loop.timer  # should be inactive
```
