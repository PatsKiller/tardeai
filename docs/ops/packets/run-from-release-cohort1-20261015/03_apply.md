# Apply cohort 1 (operator)

This changes the crontab, so it is your run. The steps follow the n8n cutover standard: fix, dry run,
regression, then at least one live run of each line. There is no soak.

```bash
CODE=$HOME/trade-ai-releases/portfolio-server/CURRENT
W=$HOME/.local/state/run-from-release/c1-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$W" && cd "$CODE"

# 0. Preconditions. Each must print OK.
test -x "$CODE/.venv/bin/python" && "$CODE/.venv/bin/python" -c "import psycopg2, pandas, requests" && echo "P1 OK"
test -f "$CODE/scripts/run_from_release.py" && echo "P2 OK"
~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/guard show 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE '^[[:space:]]*cron[[:space:]]'     # P3: an active cron grant (strip colour codes first)

# 1. Regenerate from the LIVE crontab. Never install a candidate generated earlier.
crontab -l > "$W/crontab.live"
python3 scripts/run_from_release.py crontab --crontab-file "$W/crontab.live" --cohorts c1 --out "$W"
#    expect: "lines_prefixed": 5, "lines_refused": 0, "lane_gate": {"ok": true, ...}, exit 0
grep -c 'TRADEAI_RUN_FROM_RELEASE=c1' "$W/crontab.candidate"          # expect 5
diff "$W/crontab.live" "$W/crontab.candidate" | grep -c '^>'          # expect 7 (2 header + 5 lines)

# 2. Dry run from CURRENT with the release venv (sandboxed --help; writes nothing)
python3 scripts/run_from_release.py verify --crontab-file "$W/crontab.candidate" --cohorts c1 \
  --python "$CODE/.venv/bin/python" --scratch "$W" --json "$W/verify_c1.json"
#    expect: {"lines": 5, "tally": {"pass": 5}}, exit 0

# 3. Probe in cron's environment (RUN=0 runs nothing)
python3 scripts/run_from_release.py forced-run --crontab-file "$W/crontab.candidate" --cohort c1 --out "$W/forced_run_c1.sh"
bash "$W/forced_run_c1.sh"
#    expect, for each of the 5 lines:
#      probe PY=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/.venv/bin/python
#            TRADEAI_VENV_PYTHON=<same>
#    and exit 0

# 4. Install. Back up first. Use `crontab -` (memory: `crontab <file>` can fail silently).
cp -p "$W/crontab.live" "$W/crontab.backup"
crontab - < "$W/crontab.candidate"
crontab -l | cmp - "$W/crontab.candidate" && echo "installed exactly"

# 5. Forced run: each line once, in cron's environment. Each one writes durable state.
for n in $(grep -n 'TRADEAI_RUN_FROM_RELEASE=c1' "$W/crontab.candidate" | cut -d: -f1); do
  RUN=1 LINE="$n" bash "$W/forced_run_c1.sh"
done 2>&1 | tee "$W/forced_run.log"
#    expect: "line <n> exit=0" for all 5
```

**Step 5 proof: one durable artifact per line.** Exit 0 is not evidence (§0 rule 8).

| Line | Proof |
|---|---|
| `build_symbol_profiles` ×2 | New lines with today's timestamp in `logs/symbol_profiles.log` and `logs/symbol_profiles_watchlist.log`. No `ModuleNotFoundError`. |
| `cio_draft_plan_hygiene` | `$HOME/trade-ai-releases/persistent-state/data/runtime/cio-draft-plan-hygiene_last.json` has `ok_at` advanced to now. The script's own `--dry-run` can be run first if you prefer. |
| `report_goal_loop_baseline` | A new JSON line at the end of `~/logs/goal_loop_baseline.log`. |
| `report_agent_number_grounding` | `data/runtime/agent_number_grounding_slo_last_run.json` has an mtime of now. |

**Step 6: the first natural tick.** Run `journalctl -t CRON --since today | grep RUN_FROM_RELEASE=c1` (the system journal, not `--user`), or
check syslog for a `CMD` line. The 18:40 or 06:45 tick is enough. You only confirm it ran; you do not wait for it
(§8.1).

**Lane registry.** No edit is needed. The gate shows every c1 line still declared (0 → 0).

**If any step fails,** run 04_rollback.md. The revert is byte-exact.
