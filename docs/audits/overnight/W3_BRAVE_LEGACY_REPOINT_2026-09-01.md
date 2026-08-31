# WAVE 3 — Brave legacy callers + overnight-deep + deepseek

Status: ACTIVE  
as_of: 2026-08-31T17:10:00+00:00  
Authority: READ_ONLY_ADVISORY · MBI_BEHAVIOR=0 · MBI_COGNITION=1  
Root read: `~/trade-ai-releases/persistent-state/data/runtime/search_budget.json`;
`scripts/lib/cio_residual_web.projected_search_volume`; journalctl
`hermes-deep-research-local.service`; `research_lane_health.collect_report`.

---

## 1. Brave callers still exhausting the daily budget

Live ledger (`SearchBudget@v1`, persistent-state) for `2026-08-31`:

| caller | counted calls | class |
|---|---:|---|
| `aegis_social_sentiment` | 10 | legacy-bulk cron |
| `aegis_transcript_discovery` | 13 | legacy-bulk cron |
| `web_research` | 2 | on-demand library |
| **daily total / denied** | **25 / 3** | daily ceiling hit |

News/catalyst callers under F1/F2 remain **0** (bound holds). The burn is the
two Aegis cron paths F1 listed but did not re-point.

### Consumers (named — not deleted)

| caller | consumer | durable non-Brave path kept |
|---|---|---|
| `aegis_social_sentiment` | aegis overnight / social_sentiment store | Reddit + StockTwits |
| `aegis_transcript_discovery` | aegis transcript / discovery store | DB `youtube_transcripts` corpus |
| `web_research` | `auto_research`, `iterate_research_topics`, `intel_query` | left on-demand under `search_budget` — not a news feed cron |

### Change shipped (this branch)

- `AEGIS_BRAVE_ENABLED` default **off** (same shape as `TOPIC_BRAVE_ENABLED`).
- `fetch_brave_social` / Brave loops in `aegis_transcript_discovery` short-circuit
  unless the flag is set. Functions kept; consumers named.
- Census `bound_monthly` for both → **0**. `projected_search_volume` updated.

### Projected monthly volume under bounded policy

```
as_of=2026-08-31T17:10:00+00:00
residual_web monthly_projection = 63   (3 × 1 × 21)
news_catalyst_brave_under_bound = 0
remaining_legacy_bulk_brave     = 0    (was 672)
```

Quoted via `projected_search_volume(as_of=…)` — `store_writes=false`.

**Not done:** no cron install/removal; `web_research` left interactive (2/day
today). Credential probes remain counted/never-denied by design.

---

## 2. overnight-deep — disjoint by construction

| arm | window (America/New_York) |
|---|---|
| `hermes-deep-research-local.timer` | `OnCalendar=*-*-* 22,23,00,01,02,03,04,05:35:00` |
| script bulk gate | DeepSeek bulk Flash/Pro **10:00–21:00** ET |

Journal (host, last ~36h): every firing exits 0 with

`SKIPPED_DEEPSEEK_PEAK: window=as-needed-only bulk Flash/Pro is 10:00-21:00 …`

`attempts_24h` for `overnight-deep` stays **0** because skips write no research
row (detector keys on child-written rows).

### Proposal (operator-only — do not install)

Pick one:

1. **Retarget timer into bulk window** — e.g. `OnCalendar=*-*-* 10,12,14,16,18:00:00 America/New_York` (or a single mid-window slot), keep `--model chatgpt` / bridge policy as today; **or**
2. **Widen script gate for this lane** to include the overnight US window the timer already declares (22:00–06:00 ET), with an explicit `--allow-peak` / overnight-exception documented in the unit.

Either change is scheduler/policy — agent does not install.

---

## 3. deepseek — E1 recovery check

Live `collect_report` as_of `2026-08-31T17:05:04+00:00` (Postgres
`hermes_external_research`):

| lane | attempts_24h | non_error_24h | last_any | ok |
|---|---:|---:|---|---|
| deepseek | **0** | 0 | 2026-08-22 19:54 ET | False (`zero_non_error_24h`) |
| grok | 18 | 18 | 2026-08-31 12:40 ET | True |
| chatgpt | 16 | 16 | 2026-08-31 12:41 ET | True |

**Finding (sharper than "E1 did not take"):** E1 **did** land on CURRENT
(`_resolve_child_python` / `sys.executable` present at tip `efcc51365`). The
interpreter now starts. A dry `dispatch("SCHD","deepseek",…)` on CURRENT still
returns `ok=False` with:

```
FileNotFoundError: .../efcc51365-main-exact-phase2-20260831-114929/.env
```

So `attempts_24h` stays **0** for a **new** reason: the child dies after start
on a release-layout `.env` that releases do not ship. Scheduler log still
reports "N external calls" (E2 accounting bug — `spent += 1` after FAIL).
Sibling grok/chatgpt lanes are live via other producers. **Hand-off to Claude
Code:** fix dotenv resolution for release cwd (hub `.env` / CURRENT overlay) —
do not copy secrets into the release tree; do not agent-install.

---

## What must not happen (honored)

No cron/systemd install or removal. No merge/deploy. No docs/INDEX.md.
No secrets. Callers with named consumers not deleted.
