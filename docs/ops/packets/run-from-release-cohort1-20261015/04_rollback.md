# Roll back cohort 1 (operator)

Use path A if other changes may have reached the crontab since apply. Use path B only if nothing else has touched
it since apply.

```bash
CODE=$HOME/trade-ai-releases/portfolio-server/CURRENT
W=$HOME/.local/state/run-from-release/rollback-c1-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$W" && cd "$CODE"

# A. Strip cohort 1 from the LIVE crontab. This keeps any other edit made since apply.
crontab -l > "$W/crontab.live"
python3 scripts/run_from_release.py crontab --crontab-file "$W/crontab.live" --revert c1 --out "$W"
grep -c 'TRADEAI_RUN_FROM_RELEASE=c1' "$W/crontab.candidate"     # expect 0
crontab - < "$W/crontab.candidate"
crontab -l | cmp - "$W/crontab.candidate" && echo "reverted"
#    With no other cohort installed, the two header lines (RPY=, TRADEAI_CODE_ROOT=) are removed too, and the
#    result is byte-identical to the pre-apply crontab.

# B. Restore the backup taken by 03_apply.md step 4.
crontab - < "$HOME/.local/state/run-from-release/c1-<ts>/crontab.backup"
```

Rollback restores the previous interpreter for those five lines, the dev venv. Nothing else needs undoing:
- Cohort 1 changes no file in the release, no unit and no store.
- What the forced runs wrote (profile rows, a draft-plan expiry receipt, report files) is ordinary lane output. It
  is not reverted.
