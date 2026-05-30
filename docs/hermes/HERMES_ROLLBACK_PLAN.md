# Hermes Rollback Plan — Trade AI v12

**Date:** 2026-05-30
**Status:** READY — rollback procedure documented before install

---

## Scope

This plan covers complete removal of Hermes from the Trade AI environment. It applies whether the install was project-scoped (preferred) or global.

---

## 1. Stop Hermes Processes

```bash
# Kill any running Hermes process
pkill -f hermes || true

# Stop gateway if it was enabled (it should not be during pilot)
hermes gateway stop 2>/dev/null || true

# Disable systemd unit if it was created (it should not be during pilot)
systemctl --user disable --now hermes-gateway 2>/dev/null || true
systemctl --user disable --now hermes.service 2>/dev/null || true
```

---

## 2. Remove Sidecar Directory

This is the primary rollback for project-scoped install:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
rm -rf hermes_sidecar/
```

This removes:

- Hermes venv and binary
- All Hermes config (`hermes_sidecar/.hermes/config.yaml`)
- All Hermes memory (`hermes_sidecar/.hermes/memories/`)
- All Hermes sessions (`hermes_sidecar/.hermes/sessions/`)
- All Hermes logs (`hermes_sidecar/.hermes/logs/`)
- All Hermes skills (`hermes_sidecar/.hermes/skills/`)
- All pilot reports (`hermes_sidecar/reports/`)
- All project memory exports (`hermes_sidecar/project_memory/`)
- The sidecar wrapper script

---

## 3. Remove Global Install (only if global install was used)

```bash
pip uninstall hermes-agent -y 2>/dev/null || true
rm -f ~/.local/bin/hermes 2>/dev/null || true
```

---

## 4. Remove Global Config (only if ~/.hermes was created)

**Pre-check:** `~/.hermes` did NOT exist before this project. If it was created during install, it is safe to remove.

```bash
# Only if ~/.hermes was created by this project:
rm -rf ~/.hermes
```

If uncertain, back up first:

```bash
mv ~/.hermes ~/.hermes.backup.$(date +%Y%m%d)
```

---

## 5. Remove Systemd Units (only if gateway was enabled)

```bash
systemctl --user stop hermes-gateway 2>/dev/null || true
systemctl --user disable hermes-gateway 2>/dev/null || true
rm -f ~/.config/systemd/user/hermes-gateway.service 2>/dev/null || true
rm -f ~/.config/systemd/user/hermes.service 2>/dev/null || true
systemctl --user daemon-reload
```

---

## 6. Remove Cron Entries (only if Hermes cron was added)

```bash
# Check for any hermes cron entries
crontab -l 2>/dev/null | grep -i hermes
# If found, edit crontab and remove them:
# crontab -e
```

---

## 7. Clean Git State

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Check what Hermes added to git
git status --short | grep hermes

# If hermes_sidecar was committed:
git rm -rf hermes_sidecar/ 2>/dev/null || true

# Keep docs/hermes/ — these are design docs, not install artifacts
# Only remove if operator explicitly requests

git commit -m "rollback: remove hermes sidecar install"
```

---

## 8. Verify Removal

```bash
# No hermes binary
which hermes 2>/dev/null && echo "WARN: hermes still in PATH" || echo "OK: hermes not in PATH"

# No hermes processes
pgrep -f hermes && echo "WARN: hermes process still running" || echo "OK: no hermes processes"

# No hermes sidecar directory
ls hermes_sidecar/ 2>/dev/null && echo "WARN: sidecar still exists" || echo "OK: sidecar removed"

# No global hermes config
ls ~/.hermes 2>/dev/null && echo "WARN: ~/.hermes still exists" || echo "OK: no global config"

# No hermes systemd units
systemctl --user list-units 2>/dev/null | grep hermes && echo "WARN: hermes unit exists" || echo "OK: no systemd units"

# No hermes cron
crontab -l 2>/dev/null | grep -i hermes && echo "WARN: hermes cron exists" || echo "OK: no hermes cron"

# Trade AI unchanged
grep -E 'ALPACA_MODE|LLM_DISABLE_LIVE_EXECUTION' .env

# Ollama unchanged
curl -s http://127.0.0.1:11434/api/version
```

---

## 9. What Rollback Does NOT Remove

| Item | Reason |
|------|--------|
| `docs/hermes/` design docs | Planning documents, not install artifacts |
| `docs/hermes/discovery/` | Audit artifacts, useful for history |
| Trade AI code | Hermes never modifies Trade AI code |
| Database state | Hermes never writes to the database |
| Cron schedule | Hermes never modifies Trade AI cron |
| `.env` | Hermes never modifies `.env` |
| Ollama models | Hermes uses existing models, doesn't install new ones |
| OpenClaw | Hermes never touches OpenClaw |

---

## 10. Rollback Verification Checklist

| Check | Expected After Rollback |
|-------|------------------------|
| `which hermes` | Not found |
| `ls hermes_sidecar/` | Not found |
| `ls ~/.hermes` | Not found |
| `pgrep -f hermes` | No processes |
| `systemctl --user list-units \| grep hermes` | No units |
| `crontab -l \| grep hermes` | No entries |
| `ALPACA_MODE` | `paper` (unchanged) |
| `LLM_DISABLE_LIVE_EXECUTION` | `true` (unchanged) |
| Ollama responding | Yes (unchanged) |
| Trade AI API responding | Yes (unchanged) |
| OpenClaw responding | Yes (unchanged) |

---

## Estimated Rollback Time

Under 2 minutes for project-scoped install. Under 5 minutes including global cleanup verification.
