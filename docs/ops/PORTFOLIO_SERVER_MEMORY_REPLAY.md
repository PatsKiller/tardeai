# portfolio-server memory replay (tracemalloc)

LQ-20261107-229. On 11-07 the live portfolio-server grew from 1.13 GB to 1.59 GB RSS (peak 1.97 GB)
during one 21-minute walk of the 70 `/v3` pages. RSS shows that memory grew, not which Python lines
hold it. `scripts/ops/portfolio_server_tracemalloc_replay.py` finds those lines without touching live.

## What it does

1. Starts a **second** instance of a release build inside a `bwrap` sandbox:
   - the root filesystem is read-only;
   - `$HOME` is a copy-on-write tmpfs overlay, so every write is discarded when the sandbox exits;
   - the network namespace is private, so the instance cannot reach `:7777`, Telegram, LLMs, n8n or a broker;
   - `XDG_RUNTIME_DIR` and `~/.config/tradeai` are empty tmpfs mounts, so the live serve-proxy socket and the operator env files are invisible;
   - secret-shaped files (`.env*`, `*credential*`, `*secret*`, `*_tokens.*`) are masked with `/dev/null` and left out of the PROJECT_ROOT copy;
   - the DB is the unix socket with peer auth and `PGOPTIONS=-c default_transaction_read_only=on`;
   - the service port in the copy's `config/cc_auth.yaml` is rewritten (default 7787; 7777 is refused).
2. Starts `tracemalloc` with 25 frames before the server module loads.
3. Takes a snapshot after boot. A `SIGUSR1` from the driver runs `gc.collect()` and dumps it.
4. Loads every route in headless Chromium, six at a time, with a 25 s network-idle cap. Non-GET `/api/` requests are aborted, the same method as the page walk. Broker-named pages are skipped unless `--include-broker-pages` is given.
5. Takes a snapshot after each pass and records VmRSS, VmHWM and traced bytes.
6. Writes `report.md` and `report.json` with:
   - the top 20 lines by `size_diff` for each consecutive pair;
   - the caller chain of the top five;
   - the lines that grew in **every** pass after the first. These are the leak candidates: boot → pass 1 also holds first-touch caches.

## Run

```bash
# 1. dry run: prints the sandbox argv, the env keys, the masked files; starts nothing
.venv/bin/python scripts/ops/portfolio_server_tracemalloc_replay.py \
  --build ~/trade-ai-releases/portfolio-server/<release> --routes routes.txt --out <dir> --dry-run
# 2. the replay (3 passes ≈ 15–25 min)
.venv/bin/python scripts/ops/portfolio_server_tracemalloc_replay.py \
  --build ~/trade-ai-releases/portfolio-server/<release> --routes routes.txt --out <dir> --passes 3
# 3. re-rank the snapshots already in <dir>
.venv/bin/python scripts/ops/portfolio_server_tracemalloc_replay.py --report <dir>
```

`<dir>` is the only writable path in the sandbox. Use agent scratch, never a store.

## Reading the result

- **tracemalloc counts Python allocations only.** If RSS grows much faster than "traced MB", the growth is in C extensions (psycopg, the TLS stack, numpy) or in allocator fragmentation. For fragmentation, see `lib/malloc_relief.py` and LQ-20261107-88's `PYTHONMALLOC=malloc` with quiet-tick trims.
- A line that grows in pass 1 and then stops is a cache filling once. A line that grows by a similar amount in every pass is unbounded.
- The live unit's non-secret feature flags are copied into `LIVE_FLAGS`. Outbound senders are forced off in `FORCED`. If a leak depends on a flag that is not in `LIVE_FLAGS`, add the flag; never read the unit's environment, which sits next to credentials.
