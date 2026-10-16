# Apply the RI overnight crontab changes (operator)

This changes the crontab, so you run it. It needs an active `cron` grant. The steps follow the n8n cutover
standard: fix, dry run, regression, then at least one live run. There is no soak.

**Precondition: the lane-repair PR and the RI-packet-after-C1 PR are merged and served.** The topic-ingestion
family (`family_slot_jobs` B2) passes `--budget-s` and `--max-items-per-topic`, and a `topic_ingestion.py` before the
lane-repair PR rejects both flags. This packet changes only C1 and C2; C3/C4 were absorbed by the B-families
consolidation (README).

```bash
CODE=$HOME/trade-ai-releases/portfolio-server/CURRENT
PKT=$CODE/docs/ops/packets/lane-repair-run-research-intelligence-overnight-20261015
W=$HOME/.local/state/lane-repair-ri/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$W" && cd "$CODE"

# 0. Preconditions. Each must print OK.
grep -q -- '--budget-s' scripts/topic_ingestion.py && echo "P1 OK (served code has the bound)"
grep -q 'ri_narrative_enrich' config/llm_process_registry.json && echo "P2 OK (process registered in CURRENT)"
guard show | sed 's/\x1b\[[0-9;]*m//g' | grep -i cron          # P3: an active cron grant (strip colours first)

# 1. Build the candidate from the LIVE crontab. Never install one generated earlier.
crontab -l > "$W/crontab.live"
python3 "$PKT/candidate.py" --crontab-file "$W/crontab.live" --out "$W"
#    expect: exit 0, "changes=2 lines_changed=2"; any REFUSED line means the crontab drifted: stop

# 2. Dry run of the lane (offline; writes nothing)
bash scripts/run_research_intelligence_overnight.sh --phase full --dry-run
#    expect: "DRY-RUN run-research-intelligence-overnight phase=full: would run 6 locked step(s) ... budget 1500s"

# 3. Install. Back up first, and use `crontab -` (`crontab <file>` can fail silently).
cp -p "$W/crontab.live" "$W/crontab.backup"
crontab - < "$W/crontab.candidate"
crontab -l | cmp - "$W/crontab.candidate" && echo "installed exactly"

# 4. Forced run in cron's environment, after 20:00 ET (the market gate skips a regular or premarket session).
#    The archive phase makes no model call, so it is the cheap proof for C2:
bash scripts/non_trading_hours_gate.sh bash scripts/run_research_intelligence_overnight.sh --phase archive \
  >> logs/ri_overnight.log 2>&1; echo "exit=$?"
```

## Proof: one durable artifact per change

Exit 0 is not evidence (§0 rule 8).

| Change | Proof |
|---|---|
| Code fix (lane 1) | After the next 20:30 run, `$HOME/trade-ai-releases/persistent-state/data/runtime/run-research-intelligence-overnight_last.json` shows `status: ok`, `produced_count` ≥ 0 and `skipped_reasons`. `topic_ingestion_run_latest.json` shows `budget_exhausted` and `topics_deferred`. `ri_overnight.log` has `OK ingest` and no `exit=124`. |
| C1 | The first 00:15 tick writes `START phase=full` to `ri_overnight.log`, not `PEAK_SKIP`. |
| C2 | The forced archive run in step 4 writes the `run-research-intelligence-overnight-archive_last.json` receipt now. |
| Family bound (was C3/C4; no crontab change) | After the release, `topic_ingestion.log` at the 20:45 weekday family slot ends with `TOPIC INGESTION COMPLETE` or a `[budget] ... deferred` line, not a kill. If the RI run holds the batch lock, it ends with `skipped -- another batch run holds`. The weekend 02:45 slot shows the same. |

## After install: registry follow-up

`config/lane_registry.json` `run-research-intelligence-overnight` `scheduler.schedules` still lists `15 2 * * *`.
The n8n activation PR updates it to `15 0 * * *` together with the `r1_pending` activation. That PR is blocked on
the bridge route; see README.
