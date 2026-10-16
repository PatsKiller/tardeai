# Roll back the RI overnight crontab changes (operator)

Use path A if other changes may have reached the crontab since the apply. Use path B only if nothing else has touched
it since then.

```bash
CODE=$HOME/trade-ai-releases/portfolio-server/CURRENT
PKT=$CODE/docs/ops/packets/lane-repair-run-research-intelligence-overnight-20261015
W=$HOME/.local/state/lane-repair-ri/rollback-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$W" && cd "$CODE"

# A. Revert C1+C2 in the LIVE crontab and keep any other edit made since the apply.
crontab -l > "$W/crontab.live"
python3 "$PKT/candidate.py" --crontab-file "$W/crontab.live" --out "$W" --revert
#    expect: exit 0, "changes=2 lines_changed=2"; a REFUSED line means a line was edited since: stop and diff by hand
crontab - < "$W/crontab.rollback"
crontab -l | cmp - "$W/crontab.rollback" && echo "reverted"

# B. Restore the backup taken by 03_apply.md step 3.
crontab - < "$HOME/.local/state/lane-repair-ri/<ts>/crontab.backup"
```

**What the rollback restores.** The two lines go back to their 2026-10-15 text. The 02:15 and 05:15 RI runs go
back to PEAK_SKIP under EDT. The topic-ingestion bound (formerly C3/C4) is not in the crontab: it lives in
`family_slot_jobs` B2, so only a release rollback removes it.

**What it does not revert.** Nothing else needs undoing.

- The code fix stays in the release. To roll it back, roll back the release (`promote` the previous one).
- Articles, transcripts and narratives the runs wrote are ordinary lane output.
- Retention-purged rows are restorable from the archive manifests under the retention archive root
  (`lib.retention_archive`), but they are not reverted by this rollback.
