# DeepSeek bulk window: 10:00–21:00 US Eastern

Date: 2026-08-19  
Host: ms01  
Authority: READ_ONLY_ADVISORY (no broker / order / stop / risk / 2FA)

## What was wrong

`*/15 0-1` on this host is **12:00–1:59 a.m. Eastern**, not afternoon. Operator policy is:

- **Bulk** DeepSeek Flash / Pro (Hermes substantial work + agent-job drain): **10:00 a.m.–9:00 p.m. America/New_York**
- **Outside that window:** as-needed only (`HERMES_ALLOW_DEEPSEEK_PEAK` / `--allow-peak`), not bulk

Official DeepSeek UTC pricing peaks (01:00–04:00 and 06:00–10:00 UTC) remain an extra skip. They do not overlap 10:00–21:00 ET.

## What is live on the host vs protected `main`

Protected `main` at handoff is `25a1a34a` (merge of #397) with #400/#398/#399 in ancestry.
Host crontab and CURRENT release may still lag that SHA until an immutable exact-main promotion.

Historical note: the original #400 docs said "Protected main Unchanged / PR not merged." That is **stale**. #400 merged as `1dfa064b`.

| Surface | Status |
|---------|--------|
| Crontab bulk drain | `*/15 10-20 * * *` → `scripts/run_watchlist_agent_jobs_offpeak.sh` (10:00–20:59 ET) |
| Midnight `0-1` wrapper ticks | Commented / retargeted |
| Market `--limit 20` `*/15 6-19` | Commented (bulk before 10 a.m.) |
| As-needed 1-call | `run_governed_agent_flash_market.sh` still `*/15 6-19` weekdays |
| Gate code overlay | `scripts/lib/deepseek_offpeak.py`, wrapper, Hermes Flash skip in `hermes_llm_failover.py` / `hermes_autonomous_loop.py` / `hermes_deep_research_local.py` |
| Protected `main` | **`25a1a34a`** includes PR **#400** (`1dfa064b`) plus #398/#399/#397 |

## Crontab backups (host, not Git)

| When | File | SHA256 |
|------|------|--------|
| Before flock `env` fix | `crontab_backup_pre_agent_jobs_env_fix_20260819_131018.txt` | `d54cf4a00bc95b1268ea949f4794195bb2ca9d0f2c34b7c9bd86f698b1d692c2` |
| Before off-peak wrapper | `crontab_backup_pre_offpeak_wrapper_20260819_135001.txt` | `028e02234c22775a194817b4980870f766d983f49404698ef60e6ada74c3a97c` |
| Before ET 10–21 retarget | `crontab_backup_pre_et_bulk_20260819_1402.txt` | `24e602230b8620fa3ca2e8eb51d5619211c6dc2f6087a713d22d5ac773b7d3df` |

Rollback any step: `crontab <that file>`.

## Git / PRs (historical drafts; now merged)

| PR | Merge | Notes |
|----|-------|-------|
| #400 | `1dfa064b` | Bulk window 10:00–21:00 ET + Hermes gate. **Merged.** |
| #399 | `0db697cb` | flock `env` form. **Merged.** |
| #398 | `36dd1c4b` | Watchlist/source/RAG matcher. **Merged.** |
| #397 | `25a1a34a` | Living thesis + CC tab. **Merged** to protected main. |

Do **not** merge `feat/two-way-watchlist-curation`.

## Live soak proof (afternoon ET, inside 10:00–21:00)

Manual wrapper run ~13:53 EDT completed:

- `[watchlist-agent] Done: 15/15 completed`
- `completed` 44740 → 44755
- `last_completed` 2026-08-19 13:50:02 EDT
- No `COST_CONFIGURATION_INVALID` / flock exec failure on that run

Scheduled bulk ticks now fire every 15 minutes from 10:00 through 20:45 ET (`10-20` hour field).

## Hermes

`is_deepseek_offpeak()` now means **bulk allowed**: Eastern 10:00–21:00 and not official UTC peak. Overnight Hermes Flash apply skips unless `--allow-peak`. Local Ollama paths are unchanged.

## Related

Plan: [CLOSE_OPERATOR_GAPS_TO_100_2026-08-19.md](CLOSE_OPERATOR_GAPS_TO_100_2026-08-19.md)
