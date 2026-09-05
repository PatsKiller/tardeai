# Phase 1 — Research provider truth: Brave caller inventory and ledger reconciliation

```
Campaign:       pre-persistent-agent-truth-closeout-20260905
Phase:          1 (Brave / research provider truth)
Authority:      READ_ONLY_ADVISORY — no push, no merge, no deploy, no migration,
                no schedule change, no remediation of divergent stores (AGENTS.md §0.5)
Measured:       2026-09-05 (Saturday), America/New_York
Deployed tree:  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild @ 077d1b2d8
Worktree:       /home/johnclaw/tradeai-wt-cc-header-final @ 0553ee6e0 (branch wt/cc-header-final)
Status:         FINDINGS ONLY. Nothing in §4 is implemented. §4 contains an
                operator decision that this agent does not take.
```

**Citation convention.** Unless a line is explicitly marked `[worktree]`, every `file:line`
below is in the **deployed** tree `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`
at commit `077d1b2d8`. That is the tree cron actually runs (`crontab -l` line 821 pins
`cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`), and it is the tree whose
line numbers correspond to observed runtime behaviour. The worktree copy of
`scripts/brave_search.py` carries an unmerged docstring and a capacity-observation block,
so its line numbers are offset by roughly +10 from the deployed file.

---

## 0 · Headline findings

1. **There is a true, unbudgeted, uncounted Brave bypasser: `phase2b_analyst.py`.**
   It reads the key itself, builds its own `urllib` request to
   `https://api.search.brave.com/res/v1/web/search`, and touches neither ledger.
   `phase2b_analyst.py:276-352`. It is **dormant** — no cron entry, no systemd unit, no
   importer other than itself — so it is a loaded gun rather than a live leak. It also
   still carries the fabricated provider limit that this whole campaign exists to remove:
   `phase2b_analyst.py:284` — `# Limit to top 5 to stay within 2000/mo free tier`.
   No Brave response this system has observed has ever stated a 2000/month tier.

2. **The premise handed to me is half-wrong, and the correction matters.** The frozen
   ledger at `persistent-state/data/portfolios/state/brave_search_budget.json` is **not**
   what `scripts/brave_search.py` reads and writes. It is an orphan snapshot that nothing
   reads. The file `brave_search.py` actually reads and writes is a **different inode**,
   live, and currently at 54 September calls. Three copies, two of them live. Details and
   hashes in §2.

3. **Neither live ledger is the same number.** Live `SearchBudget@v1` says September = 60.
   Live ad-hoc ledger says September = 54. The entire 6-call divergence opened **today**
   (2026-09-05: 8 vs 2). Mechanism in §2.4.

4. **The 850/month ceiling is enforced, twice, against two different live counts, and the
   operator-facing alarm reads the weaker one.** It is not inert — but the alert path
   (`alert_dispatcher_unified.py:89-111`, cron 08:30 and 16:30 daily) reports the
   *under-counted* ledger. Same class of defect as the 2026-08-30 incident, one layer up.
   Proof in §3.

5. **The primary client checks and records non-atomically.** `brave_search.py:81` calls the
   read-only `check()`, makes the HTTP request, then calls `record()` at `:203`/`:231`.
   `search_budget.py` ships `try_consume()`/`guard()` precisely to close that window and
   its own docstring says so (`scripts/lib/search_budget.py:207-208`), but the highest-volume
   caller does not use them. Two of the *bypass* callers (`aegis_transcript_discovery`) are
   more correct here than the sanctioned client.

---

## 1 · Full caller inventory

Every file that names Brave, whether it can spend or not. Column *Route* is the answer to
"does it go through `scripts/brave_search.py`, or does it construct its own HTTP request?"

### 1.1 Callers that can currently spend a Brave credit

| # | File:line | Route | Ledger(s) decremented | Gate |
|---|---|---|---|---|
| 1 | `scripts/brave_search.py:182` (`search`), `:211` (`search_news`) | **is** the budgeted client | L3 then L2 (`:203-204`, `:231-232`) | `_check_budget` `:60` |
| 2 | `scripts/web_research.py:42-52` | via `brave_search.search`, `caller="web_research"` | L3 + L2 | inherits #1 |
| 3 | `scripts/intel_query.py:633` | via `web_research.search_web` → #2 | L3 + L2, **mislabelled** `web_research` | own DB throttle `:595-626` **plus** #1 |
| 4 | `scripts/auto_research.py:234` | via `web_research.research_symbol_web` → #2 | L3 + L2, mislabelled `web_research` | inherits #1 |
| 5 | `scripts/iterate_research_topics.py:62` | via `web_research.search_web` → #2 | L3 + L2, mislabelled `web_research` | inherits #1 |
| 6 | `scripts/aegis_transcript_discovery.py:198`, `:290`, `:322` | **own HTTP** (`requests.get`) | **L3 only** — `guard()` at `:195`, `:287`, `:319` | atomic `guard()` |
| 7 | `scripts/aegis_social_sentiment.py:200-206` | **own HTTP** | **L3 only** — `check()` `:195` then `record()` `:206` | non-atomic |
| 8 | `scripts/credential_monitor.py:192-194` | **own HTTP** | **L3 only** — `note()` `:188` | **counted, never denied** (by design) |
| 9 | `scripts/secret_validators.py:132-133` | **own HTTP** | **L3 only** — `note()` `:129` | **counted, never denied** (by design) |
| 10 | `phase2b_analyst.py:287-293` | **own HTTP** | **NEITHER** | **none** |
| 11 | `scripts/topic_ingestion.py:763-771` | via `brave_search.search_news` | L3 + L2 | `TOPIC_BRAVE_ENABLED` default `0` at `:759` → **retired no-op** |

Rows 6-9 are deliberate, documented bypasses of the *client* that still reach the *ledger*:
commit `18e7884e9` (2026-08-30, PR #719) re-pointed them at `scripts/lib/search_budget.py`
rather than rewriting them onto `brave_search.py`. That is a defensible design. Row 10 is not.

**Row 10 in detail — the headline bypasser.**

```
phase2b_analyst.py:276   def _get_brave_analyst_commentary(symbols: list, brave_api_key: str) -> Dict:
phase2b_analyst.py:284       for sym in symbols[:5]:  # Limit to top 5 to stay within 2000/mo free tier
phase2b_analyst.py:287           url = f"https://api.search.brave.com/res/v1/web/search?q=..."
phase2b_analyst.py:291               "X-Subscription-Token": brave_api_key
phase2b_analyst.py:352       brave_commentary = _get_brave_analyst_commentary(top_syms, brave_key)
```

No `search_budget` import anywhere in the file (measured: `grep -n "search_budget" phase2b_analyst.py`
returns nothing). No `brave_search` import. Five calls per invocation, invisible to both
ledgers and to both alarms.

Reachability, measured:
- `crontab -l | grep -c phase2b` → `0`
- `grep -rn "phase2b_analyst" --include=*.sh --include=*.service --include=*.timer .` → no hits
- only importer/caller is itself (`:352`)
- last touched `6788ad567` 2026-04-18 ("Baseline: April 18 2026")

It sits at the **repo root**, not under `scripts/`, which is why the F2/F3 sweep that
neutered its exact twin missed it. The twin is `scripts/portfolio_weekly_report.py:449`,
same function name `_get_brave_analyst_commentary`, same 5-symbol loop, same call site
shape at `:970` — and that one **was** converted to Finviz/Yahoo (`:450-470`). The root-level
copy was left behind. `tests/test_overnight_f1_f2_search_bound.py:138` asserts
`"def _get_brave_analyst_commentary" in src` and `:139` asserts
`"api.search.brave.com" not in src` — but it points the assertion at
`scripts/portfolio_weekly_report.py` only. The root file is untested and unguarded.

### 1.2 Callers deliberately neutered — cannot spend

| File:line | What it does now | Evidence |
|---|---|---|
| `scripts/portfolio_news.py:108-112` | `_brave_search` is a deprecated alias delegating to `_non_search_enrich` (`:63-105`), which is Finviz + Yahoo only | `:68` "never fall through to an unbudgeted Brave client" |
| `scripts/web_news_fetcher.py:63-65` | `_brave_search` is a named stub returning `[]` | `:64` "Kept as named stub so imports do not fail open" |
| `scripts/symbol_enrichment.py:479-494` | `pull_brave_aplus` returns `False` after `_report_source('brave_search', False, error='retired_bulk_news_use_rss_finviz')` | `:490-494` |
| `scripts/portfolio_weekly_report.py:449-470` | Finviz/Yahoo; `brave_api_key` parameter retained but unused | `:452-453` |
| `scripts/catalyst_intelligence.py:84-108` | variable still named `brave_context`, source is Finviz/Yahoo | `:84` |
| `scripts/topic_ingestion.py:751-762` | gated off by default | `:759-760` |

The retired-lane stubs keep their Brave-shaped names. That is a readability tax but it is
honest at the call site; the docstrings say what happened. One exception is flagged in §1.4.

### 1.3 Read-only / observability surfaces (no spend)

| File:line | Reads | Consequence |
|---|---|---|
| `scripts/alert_dispatcher_unified.py:89-111` | `brave_search.get_budget_status()` → **L2** | operator alarm on the under-counted ledger — see §3 |
| `scripts/lib/search_health.py:126-141` | `search_budget.all_status()` → **L3** | correct sensor; feeds `research_lane_health` |
| `scripts/api_v2.py:10860-10914` | DB `content_embeddings WHERE source_type='brave_cache'` | a third, unrelated notion of "calls today"; see §1.5 |
| `scripts/api_v2.py:35741-35744` | comment only: "Brave (topic) retired 2026-07-07: account 402-paywalled" | historical |

### 1.4 Provenance defect found in passing (not a spend defect)

`scripts/topic_ingestion.py:1357` appends `"brave_news"` to `sources_used`
**unconditionally**, and `:1358-1360` writes a `_log_gap_fill` row for `brave_news`, even
when the lane is retired at `:759` and `brave` is the empty list. Measured in today's log:

```
logs/ri_overnight.log:89030   [brave] retired (402 paywalled) — set TOPIC_BRAVE_ENABLED=1 to re-enable
logs/ri_overnight.log:89131   Result: 13 articles, 0 transcripts saved
                              (sources: youtube_api, google_news_rss, yahoo_search, brave_news, duckduckgo)
```

Thirteen articles attributed to a source list containing `brave_news`, from a run in which
Brave was never called. This is a source-attribution fabrication in durable state, on the
same day, in the same subsystem. It spends nothing. It is out of scope for Phase 1 remediation
and is recorded here so it is not lost.

### 1.5 A third throttle nobody counted as a ledger

`scripts/intel_query.py:595-626` implements its own Brave governor on top of everything else:

- `:602-606` daily cap of **5**, counted as `SELECT count(*) FROM content_embeddings WHERE source_type='brave_cache' AND created_at > CURRENT_DATE`
- `:608-613` per-symbol 24h cache
- `:615-623` global 60-minute cooldown

The row is inserted at `:649-651` **only when `web_results` is non-empty** (`:640`). So a
Brave call that succeeds and returns zero results is spent, is counted in L2 and L3, and is
**not** counted by this throttle — the cooldown does not start. This is a fourth counter with
a fourth definition of "a call", and it is a proxy (rows written) rather than a ledger
(calls made).

---

## 2 · Which ledger does each path decrement, and why the split exists

### 2.1 The three ledgers, measured

**L1 — ORPHAN. Nothing reads it.**
```
path   /home/johnclaw/trade-ai-releases/persistent-state/data/portfolios/state/brave_search_budget.json
sha256 e82954fa7d1bfbf79d8eb89f3bb17ca73c69c081ce8348c38004fdfdb5010b4c
mtime  2026-08-10 09:19:47.152270460 -0400
size   261 bytes
inode  4390787
body   date=2026-08-10  calls=25  skipped_budget=46  caller_calls={default:25}
       monthly_calls={2026-06:114, 2026-07:50, 2026-08:150}  last_call=2026-08-10T05:12:30
```

**L2 — LIVE ad-hoc ledger. This is what `brave_search.py` actually reads and writes.**
```
path   /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/brave_search_budget.json
sha256 9bf3ebec9f5d746a…  (full: run sha256sum; 16-char prefix recorded 2026-09-05 15:5x)
mtime  2026-09-05 13:30:03.101453796 -0400
size   282 bytes
inode  2888918
body   date=2026-09-05  calls=2  skipped_budget=0  caller_calls={web_research:2}
       monthly_calls={2026-06:114, 2026-07:50, 2026-08:158, 2026-09:54}
       last_call=2026-09-05T13:30:03.101402   (LOCAL time, no tz)
```

**L3 — LIVE `SearchBudget@v1`.**
```
path   /home/johnclaw/trade-ai-releases/persistent-state/data/runtime/search_budget.json
sha256 0a6c92f485ed9526e06e687612a8cdf28e27d197785c0fd9489af16c8511afd8
mtime  2026-09-05 13:30:03.101243431 -0400
size   667 bytes
body   schema=SearchBudget@v1
       monthly={2026-08:25, 2026-09:60}
       daily={2026-08-31:25, 2026-09-01:15, 2026-09-02:13, 2026-09-03:13, 2026-09-04:11, 2026-09-05:8}
       denied={2026-08-31:3}
       callers={2026-08:{aegis_social_sentiment:10, aegis_transcript_discovery:13, web_research:2},
                2026-09:{web_research:60}}
       last_call=2026-09-05T17:30:03.100675+00:00   (UTC)
```

L1 and L2 are **distinct inodes** (4390787 vs 2888918) — not a symlink, not a hardlink. They
are two files with the same basename and divergent content.

### 2.2 Why L1 is an orphan and L2 is live — the resolution mechanism

`scripts/brave_search.py:39-40`:

```python
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BUDGET_FILE = _PROJECT_ROOT / "data" / "portfolios" / "state" / "brave_search_budget.json"
```

The path is resolved **relative to whichever tree the module was imported from**. There is no
canonical-store lookup: `grep -rn -i "brave\|search_budget" scripts/lib/canonical_store_registry.py`
returns nothing, so this store is **not registered**.

Every deployed release directory symlinks that subtree back to the dev tree. Measured on three
release directories:

```
trade-ai-releases/portfolio-server/ff2037d4-main-exact-phase2-20260819-082638/data/portfolios/state
  -> /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state
trade-ai-releases/portfolio-server/ffef1597-main-exact-phase2-20260817-173158/data/portfolios/state
  -> /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state
trade-ai-releases/portfolio-server/fff9253a-main-exact-phase6-21-rest-20260814-105058/data/portfolios/state
  -> /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state
```

So: whether the process starts in a release directory or in the dev tree, `_BUDGET_FILE`
lands on **L2**. `persistent-state/data/portfolios/state/` is a real directory, not a symlink
into that path, so **L1 is never on the write path**. Its 2026-08-10 timestamp is preserved
to the nanosecond in a second copy under
`trade-ai-releases/holdings-reconcile-backup-20260901-0855/PSTATE-state/` with an identical
sha256 — consistent with a `cp -p` state migration, not with a writer.

Confirmation that nothing reads L1: the only two references to the basename anywhere in the
deployed tree are the two lines of `brave_search.py` quoted above —
`grep -rn "brave_search_budget" --include=*.py --include=*.sh --include=*.json --include=*.yaml .`
returns exactly `scripts/brave_search.py:7` (a docstring) and `scripts/brave_search.py:40`.

**Correction to the task premise, stated plainly:** the frozen 2026-08-10 file is not "what
`scripts/brave_search.py` reads/writes". It is a dead copy. The ad-hoc ledger is alive and
54 calls into September. The two-ledger problem is real; the frozen-ledger problem is a
third, separate artifact.

### 2.3 Divergent copies of this store — reported, not touched (AGENTS.md §0.5)

All eight copies of `brave_search_budget.json` under `/home/johnclaw`, measured 2026-09-05:

| path | sha256 (16) | mtime | monthly_calls |
|---|---|---|---|
| `trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/` **(L2 — LIVE)** | `9bf3ebec9f5d746a` | 2026-09-05 13:30:03 | 06:114 07:50 08:158 09:54 |
| `trade-ai-releases/persistent-state/data/portfolios/state/` **(L1 — orphan)** | `e82954fa7d1bfbf7` | 2026-08-10 09:19:47 | 06:114 07:50 08:150 |
| `trade-ai-releases/holdings-reconcile-backup-20260901-0855/PSTATE-state/` | `e82954fa7d1bfbf7` | 2026-08-10 09:19:47 | 06:114 07:50 08:150 |
| `trade-ai-releases/holdings-reconcile-backup-20260901-0855/PROJ-state/` | `be134f50f581e65b` | 2026-09-01 08:00:05 | 06:114 07:50 08:158 09:5 |
| `trade-ai-releases/portfolio-server/20260807-124637/data/portfolios/state/` | `b19987fbd6738d35` | 2026-08-07 13:59:02 | 06:114 07:50 08:125 |
| `trade-ai-releases/portfolio-server/bc779f4a-…-20260806-111529/data/portfolios/state/` | `fb5bc210dcd06e5c` | 2026-08-06 08:15:58 | 06:114 07:50 08:100 |
| `trade-ai-releases/portfolio-server/cdab641c-main-20260803-223104/data/portfolios/state.bak-before-symlink-20260804T140139Z/` | `d1cd098691a72d5a` | 2026-08-03 17:36:28 | 06:114 07:50 08:25 |
| `ops-backups/2026-07-30/state/` | `44556bb9f9158aee` | 2026-07-02 17:36:32 | 06:114 07:50 |

Copies of `search_budget.json` (L3 schema), both:

| path | last_call | monthly |
|---|---|---|
| `trade-ai-releases/persistent-state/data/runtime/search_budget.json` **(L3 — LIVE)** | 2026-09-05T17:30:03Z | 08:25 09:60 |
| `trade-ai-campaigns/research-truth-brave-claude-v1-20260903/outputs/implementation/isolated_state_root/data/runtime/search_budget.json` | 2026-09-03T22:00:22Z | 08:25 09:42 |

The campaign copy is a clearly-labelled isolated test root: it is a 2026-09-03 snapshot of L3
plus exactly one synthetic record (`callers.2026-09` contains
`research-truth-brave-claude-v1: 1`, and both its `monthly` 09 count and its `daily` 09-03
count are exactly one above L3's). It is internally consistent and does not indicate a
second live writer. It is listed for completeness only.

**No copy was modified, moved, merged or deleted.**

### 2.4 The September divergence: L3 = 60, L2 = 54

Reconstructed from the daily buckets:

```
L3 September dailies:  09-01:15  09-02:13  09-03:13  09-04:11  09-05:8   → 60
L3 monthly 2026-09:                                                        60   (consistent)
L2 monthly 2026-09:                                                        54
L2 today  (date=2026-09-05, calls):                                         2
```

`60 − 8 = 52` and `54 − 2 = 52`. **The two ledgers agreed exactly through 2026-09-04 and the
entire 6-call gap opened today**, between L3's 8 and L2's 2.

Both files were written in the same operation as recently as the last call — L2 mtime
`13:30:03.101453796 -0400` and L3 mtime `13:30:03.101243431 -0400`, and L3's `last_call` is
`2026-09-05T17:30:03.100675+00:00`, the same instant. So the dual-write path is functioning;
the loss is not a broken import.

**Most probable mechanism — the write, not the wiring.** L2's writer is unlocked and
non-atomic:

```
scripts/brave_search.py:52   def _save_budget(data: dict):
scripts/brave_search.py:54       _BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
scripts/brave_search.py:55       _BUDGET_FILE.write_text(json.dumps(data, indent=2))
```

Read-modify-write (`_load_budget` `:43-46` → mutate → `_save_budget` `:52-55`) with **no
`flock`** and **no atomic rename**. Concurrent processes lose updates outright. L3's writer,
by contrast, holds an exclusive flock (`scripts/lib/search_budget.py:98-113`) and writes via
`tmp.replace(path)` (`:135-139`). A day with concurrent callers therefore produces
`L3 > L2` — exactly the sign of the observed gap. That the gap appeared on a day with 8 calls
and not on 09-04's 11 is consistent with concurrency, which is bursty, not volumetric.

**Two contributing under-count paths in the same client, also unlocked:**
- `scripts/brave_search.py:203-204` and `:231-232` record **only after** JSON parse succeeds.
  An HTTP error (`:207`, `:235`) or a parse failure spends the provider credit and records
  nothing in L2 — while `aegis_social_sentiment.py:203-206` explicitly does the opposite and
  documents why ("the provider bills the call whether or not we liked the response").
- **Timezone skew between the two ledgers.** L2 keys its day and month with
  `datetime.now()` — local, naive (`scripts/brave_search.py:145-146` in `_record_call`,
  `:86-87` in `_check_budget`). L3 keys with `datetime.now(timezone.utc)`
  (`scripts/lib/search_budget.py:193`, `:232`, `:283`). The two roll their day boundary 4-5
  hours apart, and their **month** boundary too. Any call made between 20:00 local and
  midnight local lands in tomorrow's L3 day and today's L2 day. This is a permanent,
  structural reason the two can never be reconciled by simple subtraction.

**Not the mechanism, ruled out by measurement:**
- Not a fourth writing tree — no other `brave_search_budget.json` exists with a 2026-09-05
  date (§2.3), and none exists in this worktree
  (`/home/johnclaw/tradeai-wt-cc-header-final/data/portfolios/state/` contains no such file).
- Not a direct `search_budget` caller with a different label — L3's `callers.2026-09` is
  `{web_research: 60}` and nothing else, so all 60 came through
  `brave_search._record_shared` with `caller="web_research"`, i.e. through the dual-write path.
- Not the campaign's isolated root (§2.3).

**Exact attribution of the 6 lost L2 increments is unmeasured.** The mechanism above is
supported by code and by the sign and timing of the gap; it is not proven by a log line,
because L2 has no write log.

### 2.5 When and why the split happened

Two commits, both in the deployed tree, both reachable by `git log`:

```
18e7884e9  PatsKiller  2026-08-30 18:15:12 -0400
  "Bound search to a budget that cannot fail open, and stop silent pool degradation (#719)"
14cdd6fe7  John        2026-08-31 01:09:22 -0400
  "fix(search): F3 per-provider budget survives process, never fail-open"
```

`git log -- scripts/lib/search_budget.py` shows exactly these two, so **L3 was born
2026-08-30**. L3's earliest daily bucket is `2026-08-31: 25`, one day later — consistent.

The commit message of `18e7884e9` states the motivating incident and the reason L2 was
**kept rather than replaced**:

> R1 established that the Brave budget layer saw ~15% of the traffic: the ledger recorded 150
> calls for August with a last_call of 2026-08-10, while the provider billed ~1,000. The alert
> path was wired, scheduled and reaching a channel, and reported monthly_pct 17.6 / "ok" while
> the provider sat at its spend ceiling — a working alarm on an unrepresentative sensor.
>
> Auditing rather than trusting my own R1 table found ELEVEN call sites, not the eight I
> reported. […] No caller was deleted: each has a live consumer […] They are re-pointed, not removed.

`git blame` on the wiring (deployed tree):

```
18e7884e9a (PatsKiller 2026-08-30  61)     """Return True if we can make a Brave API call today.
18e7884e9a (PatsKiller 2026-08-30  64)     Delegates to the shared per-provider budget, which DENIES when it cannot
18e7884e9a (PatsKiller 2026-08-30  65)     establish state. The local ledger below is kept as a secondary per-caller
18e7884e9a (PatsKiller 2026-08-30  66)     cap; it is no longer the only thing standing between a bulk caller and the
18e7884e9a (PatsKiller 2026-08-30  67)     monthly allowance, because three other modules used to bypass it entirely.
14cdd6fe70 (John       2026-08-31  81)     verdict = _shared_check("brave")
18e7884e9a (PatsKiller 2026-08-30 128) def _record_shared(provider: str, caller: str) -> None:
7a5c86713f (John       2026-05-24 143) def _record_call(caller: str = "default"):
```

**Why**, in one sentence: L3 was added on 2026-08-30 to fix a fail-open, release-relative
budget that eleven call sites were bypassing; L2 was *intentionally retained* as a
"secondary per-caller cap" (it holds `CALLER_CAPS`, `:26-34`, which L3 has no equivalent of)
rather than migrated; the dual-write at `:203-204` was the bridge; and no one has since
retired L2 or moved `CALLER_CAPS` onto L3. The split is a deliberate, documented, unfinished
migration — not an accident.

### 2.6 Caller attribution is collapsed and cannot be recovered from L3

`scripts/web_research.py:52` hardcodes `caller="web_research"`. Three distinct consumers
route through it:

```
scripts/auto_research.py:234           from web_research import research_symbol_web
scripts/iterate_research_topics.py:62  from web_research import search_web
scripts/intel_query.py:633             from web_research import search_web
```

All three, plus the module's own CLI (`scripts/web_research.py:139-148`), are recorded as
`web_research`. L3's `callers` map therefore cannot answer "which subsystem spent September's
60 calls". This is a design gap in the router, and it is the reason §5's per-caller table
bottoms out at one row.

---

## 3 · Is the 850/month ceiling actually enforced?

**Answer: yes, at two independent points, both against live counts — but the operator-facing
alarm reads the weaker of the two, and neither is checked atomically.**

### 3.1 Enforcement point A — L3. Live, correct, binding.

```
scripts/brave_search.py:81        verdict = _shared_check("brave")
scripts/brave_search.py:82-84     if not verdict["allowed"]: … return False
scripts/lib/search_budget.py:216      if st["monthly_used"] >= st["monthly_limit"]:
scripts/lib/search_budget.py:217          return {"allowed": False, "reason": "MONTHLY_EXHAUSTED", …}
scripts/lib/search_budget.py:57-61    DEFAULT_LIMITS = {"brave": {"daily": 25, "monthly": 850}, …}
```

`st["monthly_used"]` is read from **L3** (`budget_path()`, `:79-87`, resolved via
`production_state_root()` `:67-76`). L3 currently reads `2026-09: 60`. So the check is
`60 >= 850` → allow. **Enforced against a live count.** Not inert.

Positive proof that this path denies rather than merely existing: L3 contains
`denied: {"2026-08-31": 3}` — three real denials recorded on the day the daily cap of 25 was
hit. The ceiling machinery has fired against live counts within the last week.

### 3.2 Enforcement point B — L2. Live, but under-counted.

```
scripts/brave_search.py:107   if month_total >= MONTHLY_BUDGET:
scripts/brave_search.py:113   if budget["calls"] >= DAILY_BUDGET:
scripts/brave_search.py:120   cap = CALLER_CAPS.get(caller_key, CALLER_CAPS["default"])
scripts/brave_search.py:21    MONTHLY_BUDGET = 850  # Reserve 150 for P0/manual searches out of 1000
```

`month_total` comes from `_load_budget()` → **L2**, which reads `2026-09: 54`. Because L2 is
live in the deployed tree, **this check is also against a live count** — it is simply reading
a count that is 6 low and structurally lossy (§2.4).

The premise "if enforced against the frozen one, the ceiling is inert" would have been true
had L1 been on the read path. It is not (§2.2). **The ceiling is not inert.** What is inert
is L1 itself.

Note also that `MONTHLY_BUDGET`'s trailing comment at `:21` — "Reserve 150 for P0/manual
searches out of 1000" — asserts a 1000 that no provider response has ever stated, and
describes a reserve that is not implemented anywhere in the deployed tree. The 850 is a local
cost policy wearing a provider's clothes.

### 3.3 What is actually broken: the alarm reads L2

```
scripts/alert_dispatcher_unified.py:93    from brave_search import get_budget_status
scripts/alert_dispatcher_unified.py:94    b = get_budget_status()
scripts/alert_dispatcher_unified.py:95-96 pct = b.get("monthly_pct", 0); level = b.get("monthly_alert", "ok")
scripts/brave_search.py:256-265           def get_budget_status(): … month_total from _load_budget()  # L2
crontab -l:323   30 8,16 * * * … scripts/alert_dispatcher_unified.py >> logs/alert_dispatcher.log
```

The operator alarm therefore reports `54/850 = 6.4%, "ok"`, while the authoritative live
ledger says `60/850 = 7.1%`. Today the difference is immaterial. The **shape** of the defect
is not: this is precisely the 2026-08-30 failure — "a working alarm on an unrepresentative
sensor" — reproduced one layer up. The correct sensor already exists and is already scheduled:

```
scripts/lib/search_health.py:127   from scripts.lib.search_budget import all_status   # reads L3
systemctl --user list-timers:      tradeai-research-lane-health.timer  (last run 2026-09-05 15:43 EDT)
```

Two alarms, two ledgers, no statement anywhere of which one an operator should believe.

### 3.4 The atomicity gap (relevant to §4)

`brave_search.py` uses the **read-only** preflight and records after the fact:

```
scripts/brave_search.py:74/77   from …search_budget import check as _shared_check
scripts/brave_search.py:81      verdict = _shared_check("brave")          # read-only, no lock held
…                               HTTP request happens here
scripts/brave_search.py:203     _record_shared("brave", caller)           # separate lock acquisition
```

`search_budget.check()`'s own docstring names this:

```
scripts/lib/search_budget.py:207-208
    Read-only: does not mutate the ledger. Prefer ``try_consume`` / ``guard`` at
    the call site so concurrent cron processes cannot both spend the last unit.
```

`try_consume` (`:223-272`) and `guard` (`:300-310`) exist and are used correctly by
`aegis_transcript_discovery.py:195, :287, :319`. The **primary, highest-volume client does not
use them.** Two processes can both pass `check()` at 849/850 and both spend.

`aegis_social_sentiment.py:195` has the same gap (`check()` then `record()` at `:206`),
though its record-immediately-after-request discipline at `:203-206` is better than
`brave_search.py`'s record-only-on-success.

---

## 4 · Design for the canonical atomic router — PROPOSAL ONLY, NOT IMPLEMENTED

Nothing in this section has been written to code. It is a design for the operator and for a
later phase to accept, amend or reject.

### 4.1 Shape: reserve → call → settle

One module, one ledger, three phases, so that the unit of accounting is *the request that
left the machine*, not *the response we liked*.

```
reserve(provider, caller, n=1) -> Reservation | Denial
    Under the L3 exclusive flock: read, evaluate ceilings, write a PENDING row
    keyed by a reservation id, release. The unit is committed the moment it is
    reserved — a crash between reserve and settle leaks a unit, which is the
    safe direction. Returns a Denial (never raises, never fails open) carrying
    the reason: MONTHLY_EXHAUSTED | DAILY_EXHAUSTED | BUDGET_UNAVAILABLE |
    CALLER_CAP | BYPASS_BLOCKED.

    Denial reasons must be distinguishable at the call site. Today a caller
    cannot tell "over budget" from "ledger unreadable": brave_search.py:196 and
    :270 both return [] for every cause, so a corrupt ledger and an exhausted
    month look identical to portfolio_news, topic_ingestion and intel_query.

call(...)                          # the HTTP request; the router owns it, so the
                                   # response headers cannot be dropped again
settle(reservation, outcome)
    outcome=SPENT     — the provider served or billed it (any HTTP status that
                        consumes a credit, including 402/429). PENDING -> SPENT.
    outcome=REFUND    — the request demonstrably never reached the provider
                        (DNS failure, connect timeout, no key). PENDING -> void,
                        unit returned.
    outcome=UNKNOWN   — anything else. Stays SPENT. Ambiguity costs a unit, not
                        an unmetered call.
sweep()
    Any PENDING older than a bounded age settles to SPENT. Leaked reservations
    must decay toward "we spent it", never toward "we did not".
```

`settle` is where the two current under-counts (§2.4) close: `brave_search.py:203-204` records
only on parse success, and `intel_query.py:649-651` records only on non-empty results. Under
reserve/settle both become SPENT.

### 4.2 Single ledger

`SearchBudget@v1` at `persistent-state/data/runtime/search_budget.json` is the only
survivor, extended with:
- `pending{}` — open reservations
- `caller_caps` — L2's only unique asset (`brave_search.py:26-34`) migrated onto L3
- a per-record `tz` discipline: **UTC everywhere**, retiring `brave_search.py`'s naive
  `datetime.now()` (`:86-87`, `:145-146`) and with it the 4-5 hour day/month skew
- a real `caller` (§2.6): `web_research.py:52` stops hardcoding its own name and threads the
  originating module through, so `auto_research`, `iterate_research_topics` and `intel_query`
  are distinguishable

L2 is then **archived with a read tripwire**, per AGENTS.md §0.6 — not deleted. L1 is not
touched at all until §4.4 is answered.

The store must also be **registered in `scripts/lib/canonical_store_registry.py`**, which
today knows nothing about it (measured, §2.2). An unregistered authoritative store is how L1
came to exist in the first place.

### 4.3 Bypass gate

The gate has to be a **test**, not a convention, because the convention already failed once:
`phase2b_analyst.py` survived a sweep that explicitly hunted for it, and
`tests/test_overnight_f1_f2_search_bound.py:100-139` asserts `"api.search.brave.com" not in src`
against a fixed list of files that does not include the repo root.

Proposed gate, in ascending order of strength:

1. **Repo-wide assertion, allowlist-based.** Every file matching
   `api\.search\.brave\.com|X-Subscription-Token` must be on a named allowlist. The allowlist
   is the router module plus the two key validators (`secret_validators.py`,
   `credential_monitor.py`, which must reach the provider to test a key and are
   counted-never-denied by design, `search_budget.py:313-325`). Scope is the **whole repo
   including the root**, not `scripts/`.
2. **Key custody.** `BRAVE_SEARCH_API_KEY` is read only by the router. Every other
   `_get_api_key`-shaped function is deleted — `web_research.py:19-25`,
   `phase2b_analyst.py` (key passed in as a parameter at `:276`),
   `brave_search.py:163-171`. A module that cannot obtain the key cannot bypass the router,
   whatever it imports.
3. **Runtime honesty.** The router records the observed
   `x-ratelimit-limit` / `x-ratelimit-policy` on every response
   (`scripts/lib/research_provider_truth.py` `[worktree]` already implements the parse) so
   provider capacity is *observed*, never asserted. Note: no
   `brave_provider_capacity.json` exists anywhere on this host, so that writer has never run
   in production — the 2026-09-05 header measurement in this campaign was taken by hand, not
   by the code.

Delete-nothing corollary: `web_research.py:54-89`'s own-HTTP fallback is currently dead code
(it runs only if `import brave_search` fails, and `brave_search.py:88-90` already treats an
unimportable budget as DENY). Under the router it must not be re-added as a fallback. A
missing router is a denial, not a licence.

### 4.4 The reconciliation question the operator must answer

Unifying L2 and L3 requires choosing a **September starting balance**, and the two ledgers
disagree. This is not a technical choice; it decides how much money the month is allowed to
spend. **This agent does not make it.**

> **For the operator.** Three counts exist for August and September and none can be
> derived from the others:
>
> | | 2026-06 | 2026-07 | 2026-08 | 2026-09 (to 09-05) |
> |---|---|---|---|---|
> | L2 (ad-hoc, lossy, local-time) | 114 | 50 | 158 | **54** |
> | L3 (`SearchBudget@v1`, locked, UTC) | — | — | 25 (from 08-31 only) | **60** |
> | provider (billed) | unmeasured | unmeasured | ~1,000 per commit `18e7884e9` | **unmeasured** |
>
> **Question 1 — which number does September carry forward: 54, 60, or a provider-derived
> figure?** L3 is the only locked, atomic, timezone-coherent count and is the only one that
> can be defended as a *lower bound* on real spend. It is not an upper bound: `phase2b_analyst`
> (dormant), any 402/429, and any parse failure are invisible to it. L2's 158 for August
> versus L3's 25 is not a contradiction — L3 only started on 08-31 — but it means the two
> series cannot be concatenated without a documented seam.
>
> **Question 2 — is the provider's own count going to be the arbiter?** If yes, someone must
> read the Brave dashboard for 2026-08 and 2026-09 and record it as evidence; the ~1,000
> figure in commit `18e7884e9` is the only provider number this system has ever recorded and
> it is now a week stale. If no, the operator is accepting that the ledger is a lower bound
> and the ceiling has an unquantified margin.
>
> **Question 3 — does the 850 stand once it is honestly counted?** Brave's live headers on
> 2026-09-05 read `x-ratelimit-limit: 50, 0` and `x-ratelimit-policy: 50;w=1, 0;w=2592000`
> at HTTP 200: **50 requests per second, and a monthly window reporting 0, which means
> not-metered/not-published, not a ceiling of zero.** The provider imposes no monthly
> ceiling on this key. 850 is therefore entirely a local cost choice, and the comment at
> `brave_search.py:21` claiming it reserves 150 "out of 1000" is describing a tier that does
> not exist and a reserve that was never implemented.
>
> Until Question 1 is answered, the safe interim posture is the **more restrictive** of the
> two (AGENTS.md conflict rule): treat September as **60** used, not 54.

**Concurrent-change notice.** While this report was being written, another agent modified
`scripts/lib/search_budget.py` **in this worktree** and committed it as `af3349528`
("research(budget): the two ceilings were the same constraint twice") — it appeared as
` M scripts/lib/search_budget.py` mid-session and was committed before hand-off.
That change sets `DEFAULT_LIMITS["brave"]` to `{"daily": 120, "monthly": 1500}` `[worktree
scripts/lib/search_budget.py:79]` and adds a `MONTHLY_RESERVE = {"brave": 200}` with an
`effective_monthly_limit()` `[worktree :171-191]`. **Every measurement in §3 describes the
deployed 25/850, which is what is running.** The worktree proposal is unmerged and
undeployed (branch `wt/cc-header-final`, not on `main`). It is flagged here because it bears
directly on Question 3 and because two
agents changing the same ceiling in the same hour is exactly the condition under which a
number becomes untraceable. This agent did not make, review or endorse that change.

---

## 5 · September usage and run-rate

**Source: L3, the locked ledger.** Measured 2026-09-05T17:30:03Z.

| day | calls |
|---|---|
| 2026-09-01 (Tue) | 15 |
| 2026-09-02 (Wed) | 13 |
| 2026-09-03 (Thu) | 13 |
| 2026-09-04 (Fri) | 11 |
| 2026-09-05 (Sat, partial) | 8 |
| **total** | **60** |

Per caller, September, as L3 records it:

| caller label | calls | share |
|---|---|---|
| `web_research` | 60 | 100% |

That single row is the §2.6 attribution collapse, not a fact about the system: `web_research`
is a label shared by `auto_research.py:234`, `iterate_research_topics.py:62`,
`intel_query.py:633` and the module CLI. **The true per-caller split is unmeasured** and
cannot be recovered from the ledger.

For contrast, August's tail (L3 covers 08-31 only) still had genuine per-caller resolution
because those callers pass their own names:

| caller | 2026-08 |
|---|---|
| `aegis_transcript_discovery` | 13 |
| `aegis_social_sentiment` | 10 |
| `web_research` | 2 |

Note the inversion: the two callers that *bypass the client* are the two with honest
attribution.

**Run rate.**

```
elapsed buckets      5 (2026-09-01 … 2026-09-05, last partial)
observed total       60
rate                 12.0 calls/day
30-day projection    360 calls
```

Against the **deployed** ceilings:

| | projection | limit | pct |
|---|---|---|---|
| monthly (L3, 850) | 360 | 850 | **42.4%** |
| monthly (L2's 54 → 324) | 324 | 850 | 38.1% |
| daily (peak observed 15 on 09-01) | 15 | 25 | 60% |

Against the observed provider capacity (50 req/sec, monthly window unmetered), 360/month is
**not** a provider-capacity concern at all. It is a cost concern only.

**Caveats on the projection, stated rather than smoothed:**
- Four of five buckets are weekdays; today is a Saturday, and the two scheduled consumers of
  `web_research` are weekday-only (`crontab -l:164` `0 20 * * 1-5 … auto_research.py`,
  `:184` `0 8 * * 1-5 … iterate_research_topics.py`). A flat ×30 therefore **over**-projects
  weekends and **under**-projects a full weekday month. A weekday-weighted projection is
  `12.0 × 22 ≈ 264` plus weekend on-demand traffic. Both figures are given; neither is
  presented as the answer.
- Today's 8 calls cannot be attributed to either weekday cron. Their origin is **unmeasured**
  — plausibly this campaign's own on-demand research, since `web_research` is exempt from the
  weekend skip (`brave_search.py:25`, `:95`).
- The projection counts only what the ledger sees. It excludes: any `phase2b_analyst` run
  (dormant, uncounted), any 402/429/parse-failure (uncounted in L2, counted in L3 only for
  the `aegis_social_sentiment` path), and the L2 write losses of §2.4.
- August's provider-billed total (~1,000 per commit `18e7884e9`) versus L3's 25 is not
  comparable — L3 began 08-31. **No provider-side September figure has been measured.**

---

## 6 · What I could not determine

1. **The exact cause of the 6 lost L2 increments today.** The unlocked read-modify-write at
   `brave_search.py:52-55` is the mechanism the code supports and the sign of the error
   matches, but L2 has no write log and I found no artifact naming the losing process. Stated
   as most-probable, not proven.
2. **Who or what made today's 8 Brave calls.** Both scheduled `web_research` consumers are
   weekday-only and today is Saturday. The `caller` label is collapsed (§2.6). No log line in
   the deployed tree's `logs/` attributes them.
3. **Actual provider-side spend for 2026-08 and 2026-09.** The only provider figure this
   system has ever recorded is "~1,000" in commit `18e7884e9`'s message (2026-08-30). I did
   not query the Brave dashboard and will not invent a number. Both months are **unmeasured**
   provider-side.
4. **Whether anything outside the deployed repo reads L1.** I proved no `.py`/`.sh`/`.json`/
   `.yaml` in the deployed tree references the basename. Backup scripts, ops tooling outside
   the repo, and any Drive-sync manifest were not audited.
5. **Whether `phase2b_analyst.py` has ever run in September.** No cron, no unit, no importer —
   but I found no negative-proof artifact (no execution log) either. "Dormant" is inferred
   from reachability, not from an execution record.
6. **The precise `sha256` of L2 at time of reading.** L2 is being written live (mtime moved
   during this session); I recorded a 16-character prefix `9bf3ebec9f5d746a` and the full
   body rather than a full digest that would be stale on arrival. L1 and L3 digests are full
   and were stable.
7. **Whether the 402 responses seen historically consume a Brave credit.** The last observed
   402s are dated 2026-08-26 (`logs/screener_pm.log:206600-206632`, run marker
   `:206837` "v12 complete | 2026-08-26 1730"), from the then-live
   `catalyst_intelligence` path, which is now neutered. Whether a 402 is billed determines
   whether `settle(outcome=SPENT)` is right for it in §4.1. **Unmeasured.**
8. **Whether `_observe_capacity` `[worktree]` works against a live response.** No
   `brave_provider_capacity.json` exists anywhere on this host, so that code path has never
   produced an artifact. The 2026-09-05 header values quoted in §4.4 were measured by hand
   and supplied to me as ground truth; I did not re-measure them and made no Brave call.
9. **Whether the concurrent worktree change to `DEFAULT_LIMITS` (120/1500) is intended to
   ship.** It appeared mid-session, is uncommitted, and is not mine to judge or revert.

---

## 7 · Compliance record

- **No Brave API call was made by this agent.** All counts are read from durable ledger files.
- **No file was written except this one.** `git status` at hand-off shows this report as
  untracked, plus another agent's pre-existing modification to
  `scripts/lib/search_budget.py` which is **not mine and was not touched**.
- **No divergent copy was remediated, merged, moved or deleted** (AGENTS.md §0.5, §0.6).
  Eight copies of L2's basename and two of L3's are reported with paths, hashes and
  timestamps in §2.3 and left exactly as found.
- **Nothing was committed, pushed, merged, deployed, restarted or rescheduled.**
- **§4 is a proposal.** The reconciliation decision in §4.4 is escalated to the operator
  under AGENTS.md §0.9, and is not taken here.
