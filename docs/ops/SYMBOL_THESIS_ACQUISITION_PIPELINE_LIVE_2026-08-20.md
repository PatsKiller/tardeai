# Symbol-thesis acquisition pipeline — live (autonomous, debt-sensitive) — 2026-08-20

Authority: **READ_ONLY_ADVISORY**. No broker / order / stop / 2FA mutation.
Status: **LIVE** — worker deployed to canonical tree and scheduled; 3 symbols published end-to-end.

## Verdict

The whole symbol-thesis acquisition loop is now **debt-sensitive, ordered, and wired
end-to-end**, and runs **autonomously** on a daily cron. The first live run proved the
full chain — RAG retrieve → acquire → curate → embed → Flash synthesize → reconcile →
publish — for `DIV`, `DIVI`, `JEPI` (`symbol_div@v1`, `symbol_divi@v1`, `symbol_jepi@v1`).

## What shipped (3 PRs, all merged to `main`)

| PR | Title | Contents |
|----|-------|----------|
| [#407](https://github.com/PatsKiller/tardeai/pull/407) | Autonomous debt-sensitive symbol-thesis acquisition (end-to-end) | runner + governed wrapper + Flash synthesis glue + governed embed + registry budget bump |
| [#408](https://github.com/PatsKiller/tardeai/pull/408) | Make thesis acquisition wrapper self-locating for production | wrapper resolves its own checkout instead of a hardcoded worktree |
| [#409](https://github.com/PatsKiller/tardeai/pull/409) | Fix thesis acquisition wrapper cron hint path | header comment points at canonical tree |

### New / changed files

- `scripts/run_symbol_thesis_acquisition.py` — debt-ordered runner (held → reentry →
  opportunity → P0…P3), RAG-first, resumable JSONL ledger (`data/cio/symbol_thesis_acquisition_ledger.jsonl`).
- `scripts/run_governed_symbol_thesis_acquisition.sh` — governed wrapper (containment
  override, operator env, per-run Flash caps, flock, hard timeout).
- `scripts/lib/symbol_thesis_synthesis.py` — Flash synthesis prompt/parse/normalize, fail-closed.
- `scripts/lib/symbol_thesis_acquisition.py` — `embed_evidence_into_rag` (curation-gated).
- `scripts/lib/agent_flash_governance.py` — optional `response_json` passthrough.
- `config/llm_process_registry.json` — `watchlist_steph_flash_narrative` 800→1600 output tokens
  (living-thesis JSON was truncating mid-object); maria `daily_soft_cap` 120→240 (from #406).

## Deployment

Surgical `git checkout origin/main -- <6 files>` into the canonical tree
(`/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`), which is on a diverged
feature branch. No full-tree merge (would have pulled 20 unrelated commits).

**No release-snapshot redeploy was required**: the worker runs from the canonical tree
(via the cron wrapper's absolute paths), the HTTP server does not import the new worker
modules, and `data/cio` is already symlinked from the release into canonical.

## Schedule

```
17 17 * * 1-5 …/scripts/run_governed_symbol_thesis_acquisition.sh >> …/logs/symbol_thesis_acquisition.log 2>&1 # TRADEAI_GOVERNED_WORKER thesis-acquisition-daily
```

Runs **weekdays 17:17 ET** (= 21:17 UTC = 05:17 Beijing next day), debt-ordered top-10,
`MAX_LLM=3`, fail-closed.

Scheduling rationale (DeepSeek is billed peak/off-peak since 2026-08-16 16:00 UTC):

- **Peak** hours are 01:00–04:00 and 06:00–10:00 UTC (= 21:00–00:00 ET and 02:00–06:00 ET).
- **Off-peak** is everything else, at 50% of peak.
- 17:17 ET = 21:17 UTC is **off-peak**, and lands in Chinese night (Beijing 05:17), i.e.
  low-latency/low-load on DeepSeek's side.
- 17:17 ET is also **after the US market close (16:00 ET)**, so it does not compete with
  market-hours Flash work for the shared `LLM_GLOBAL_DAILY_USD_CAP`, nor with the market
  worker for GPU/Ollama embed capacity.

(The earlier 03:17 ET was **wrong**: 03:17 ET = 07:17 UTC sits inside the 06:00–10:00 UTC
peak window. Corrected 2026-08-20.) The `:17` minute is a deliberate non-round offset to
avoid the `*/5` / `*/15` / `:00` / `:30` cron herd at the top of the hour.

## Bugs found and fixed during bring-up

1. **RAG returned empty** — runner didn't thread a Postgres conn from the canonical
   `.env` (workspace has none). Fixed with `_thesis_conn(root)` + `conn=` threading.
2. **Flash JSON truncated** — synthesis output cut off mid-object at 800 tokens. Fixed by
   enabling `response_json` and raising the steph output budget to 1600.
3. **Theses published to wrong tree** — `apply_synthesis_to_thesis` was called without
   `root=`, landing pins in the workspace `data/cio/` (CWD-relative) instead of canonical.
   Fixed with `root=root`; stray workspace pins purged.

## Live proof

`DIV`, `DIVI`, `JEPI` published `symbol_*@v1` (stance=hold, INCOME) into canonical
`data/cio/cio_theses.jsonl` via real governed Flash calls (`deepseek-v4-flash`,
~$0.0004/call, `fallback_used=false`).

## Remaining / deferred

- SCHG / CSCO / ANET still `BLOCKED_PENDING_ACQUISITION_AND_CURATION` (empty RAG) — the
  pipeline correctly holds synthesis until acquisition + curation produce approved evidence.
- Telegram acceptance (interactive CIO query + proactive non-financial canary) still pending.
- Release snapshot is at `5209c820` (behind `main`) — unrelated to this worker; promote via
  `cio_phase2_exact_main_deploy.sh` when a full redeploy is next wanted.
