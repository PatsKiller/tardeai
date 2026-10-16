# lane-retire-wave1-20261015: RETIRE wave 1, operator packet

**Status: PREPARED, NOT INSTALLED.** Merging changes no crontab, unit, n8n or DB state.

The registry rows stay `ACTIVE` with a `retire_pending` block. They become `RETIRED` only after the lines are really
commented and read back. That step is `apply_registry.py`, run in a follow-up registry PR.

Source: `docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.{csv,md}`, waves R1 and R1b. The crontab was read
with `crontab -l` only (snapshot sha256 `6a5c6768…de4e96`, 394 active job lines). No `.env` or credential file was
read.

## Tier A, 4 lines (`lines_to_retire.tsv`)

Fresh evidence was taken on 2026-10-15. Each of these lines does nothing today.

| Lane | Line | Evidence |
|---|---|---|
| `agent-intelligence-cron-deep` | L162 `0 8 * * 0` | `scripts/agent_intelligence_cron.sh` runs `.venv/bin/python` relative to CURRENT; `CURRENT/.venv` does not exist; every CURRENT-era log is "No such file", 0 steps. retire-wave2 YES |
| `agent-intelligence-cron-daily` | L189 `25 6 * * 1-5` | same; `logs/agent_intelligence_daily_20261015_062501.log` |
| `agent-intelligence-cron-intraday` | L194 `30 11,14 * * 1-5` | same; `logs/agent_intelligence_intraday_20261014_143002.log` |
| `symbol-enrichment` | L252 `30 7 * * 1-5` | argv `--limit 50` is not an option of `symbol_enrichment.py` (strict parser since `1c733d98f`, 10-11): `logs/symbol_enrichment.log` ends `error: unrecognized arguments: --limit` on every run, exit 2. `enrich_symbol()` stays a library for its other callers |

## Tier B, 6 lines (`lines_to_retire_tier_b.tsv`): answer YES or NO for each row

| Lane | Line | Why retire | Risk if wrong |
|---|---|---|---|
| `cleanup-stale-locks` | L232 `*/5` | It deletes holder-less lock files every 5 minutes (59,387 deletes) and races the jobs that create them. `flock` locks need no cleanup. | A pid lock left by a killed `safe_flock` job stays until its next holder check. |
| `risk-gate` | L275 `0 9-16 * * 1-5` | `risk_gate.py --test` writes the 7 synthetic self-test cases into `risk_gate_results` every hour. `api_v2.py:55048` and `/risk` in Telegram aggregate that table as if it held real decisions. | The CC risk-gate counts stop growing. That is the correct result. |
| `backup-generated-docs` | L543 `50 23 * * *` | It pushes from cron, which AGENTS.md §24.5 forbids. It has logged "no generated-doc changes" every night since 10-10. | Generated docs are not pushed nightly. They are in git through normal PRs. |
| `goal-pilot-material-change` | L984 hourly | Every verdict is UNEVALUABLE (missing facts), and no consumer reads it. | none known |
| `dormant-lane-consumers` | L985 hourly | It is a log-only wiring harness ("lanes ok: 10/10"). Nothing reads it. | none known |
| `indicator-engine` | L262 `0 8 * * 1-5` | With no argv it runs only the module's `__main__` demo, `analyze_confluence('AMD','scalp')`, printed to a log. The universe cache belongs to `indicator-cache-refresh` (premarket step). | none known; confirm nobody reads `logs/indicator_engine.log` |

The tier-B TSV is built only with `--tier-b`. To drop a row you answer NO to, delete that row from
`lines_to_retire_tier_b.tsv` and from the registry's `retire_pending` blocks (keep the TSV and the registry in step), then
re-run.

## Apply (operator; `cron` grant)

```bash
cd ~/trade-ai-releases/portfolio-server/CURRENT/docs/ops/packets/lane-retire-wave1-20261015
~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/guard show 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE '^[[:space:]]*cron[[:space:]]'        # an active cron grant (strip colour first)
bash install.sh                                               # DRY RUN: builds from the LIVE table, prints the 4-line diff
CRON_GRANT_ID=<id> bash install.sh --apply                    # tier A: backup, crontab -, read back == candidate, VERIFY OK
# tier B, only for the rows answered YES (works before or after tier A; lines already retired by tier A are skipped):
CRON_GRANT_ID=<id> bash install.sh --tier-b --apply
```

Read-back (also printed by `install.sh`):

```bash
python3 retire_packet.py verify --crontab <(crontab -l) [--tier-b]   # VERIFY OK: N line(s) retired; active job lines now 390 (384)
```

Registry flip, after a VERIFY OK (follow-up PR):

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild      # on a branch
python3 docs/ops/packets/lane-retire-wave1-20261015/apply_registry.py --registry config/lane_registry.json \
  --crontab <(crontab -l) --date $(date +%F) --grant <cron grant id> --write
```

The registry flip only touches rows whose line is commented, tagged `retire-ld-w1`, and absent as a live line. Every
other row keeps `ACTIVE` and its `retire_pending` block.

**Grant wording (suggested).** Type: `cron`. Text: "lane-retire-wave1-20261015: comment 4 crontab lines
(agent_intelligence_cron.sh deep/daily/intraday, symbol_enrichment.py --limit 50) `# RETIRED <date> retire-ld-w1 …` via
install.sh --apply; rollback.sh on failure. PR #<n> sha <sha>." For tier B, add the YES rows by name.

## Rollback

```bash
bash rollback.sh [--tier-b]                                   # DRY RUN
CRON_GRANT_ID=<id> bash rollback.sh [--tier-b] --apply        # uncomments exactly the tagged lines; VERIFY OK (live)
```

`rollback.sh` refuses in two cases:

- the tagged count is not the packet's count;
- a live copy already exists, which would be a double schedule.

It works on the live table and keeps any other line changed since install.

The rehearsal is in `tests/test_lane_disposition_retire_wave1_20261015.py`. It runs `install.sh --apply` then
`rollback.sh --apply` on a fake crontab, and the result is byte-identical to the snapshot.

## Not in this packet

- **`hermes-shadow-scorer`** is a timer. It needs a service grant and is handled by the existing
  `~/n8n-maturity-verification/packets/consolidation-retire-wave2-20261014/timers.sh`.
- **The 7 phantom ACTIVE rows on disabled timers (F03)** need only a registry PR, no host change.
- **The 49 lines that still run under RETIRED rows** (36 premarket, 13 B-family) are CONSOLIDATE, not RETIRE. Their
  flip packets comment them and switch each stage runner to `--apply` in the same act.
